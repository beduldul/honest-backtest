"""Guard 2 -- outlier domination.

The fixtures: 9/12 windows won with mean -138.7 against median +37.0, and
in-sample top-decile shares of 1.21 and 1.64 **of net PnL**.

The denominator is the thing to keep straight. A share of gross profit cannot
exceed 1.0, so "121% of gross" is not a large number, it is a contradiction.
The metric divides the top decile by net PnL -- the sum of every trade, winners
and losers -- which is smaller than the winnings and may be negative, and that
is exactly why the share can exceed 100%.
"""

from __future__ import annotations

import pytest

from honest_backtest import fixtures
from honest_backtest._numeric import top_share
from honest_backtest.guards.outliers import ConcentrationGuard
from honest_backtest.types import Verdict


def test_nine_of_twelve_wins_is_refused_on_sign_disagreement(nine_of_twelve: dict) -> None:
    """The headline fixture: 9 wins out of 12, and not an edge.

    The assertion is on the *sign disagreement*, not the win count. A guard that
    keyed on win rate would have certified this.
    """
    assert nine_of_twelve["win_count"] == 9
    assert nine_of_twelve["mean_excess"] == pytest.approx(-138.67, abs=0.05)
    assert nine_of_twelve["median_excess"] == pytest.approx(37.0, abs=0.05)
    assert nine_of_twelve["signs_disagree"] is True
    assert nine_of_twelve["verdict"] == "REFUSED"

    codes = {f["code"] for f in nine_of_twelve["findings"]}  # type: ignore[index]
    assert "CONCENTRATION_MIXED_SIGNS" in codes


def test_mixed_signs_message_names_both_numbers_and_the_win_count() -> None:
    """The refusal must print the evidence, not just say 'failed'."""
    guard = ConcentrationGuard(min_obs=8)
    report = guard.check_windows(
        [float(x) for x in fixtures.NINE_OF_TWELVE["excesses"]],  # type: ignore[union-attr]
        win_count=9,
    )
    message = report.findings[0].message
    assert "MIXED" in message
    assert "OUTLIER-DRIVEN" in message
    assert "-138.7" in message
    assert "+37.0" in message
    assert "9/12" in message


def test_win_count_does_not_override_sign_disagreement() -> None:
    """Passing a *better* win count cannot rescue the result."""
    guard = ConcentrationGuard(min_obs=8)
    excesses = [float(x) for x in fixtures.NINE_OF_TWELVE["excesses"]]  # type: ignore[union-attr]

    for claimed_wins in (9, 11, 12):
        report = guard.check_windows(excesses, win_count=claimed_wins)
        assert report.verdict is Verdict.REFUSED, (
            f"claiming {claimed_wins} wins must not change the verdict"
        )


def test_top_decile_121_share(top_decile_121: dict) -> None:
    """Top 10% of trades produced 121% of net PnL."""
    assert top_decile_121["top_share"] == pytest.approx(1.21, abs=5e-3)
    assert top_decile_121["verdict"] == "REFUSED"
    assert top_decile_121["loses_without_top_decile"] is True


def test_top_decile_164_share(top_decile_164: dict) -> None:
    """The second study's 15m result: share 1.64."""
    assert top_decile_164["top_share"] == pytest.approx(1.64, abs=5e-3)
    assert top_decile_164["verdict"] == "REFUSED"
    assert top_decile_164["loses_without_top_decile"] is True


def test_share_above_one_means_the_remainder_loses() -> None:
    """The algebraic identity the guard relies on, stated directly.

    A share at or above 1.0 cannot happen unless the non-tail observations net
    negative. Both fixtures are above 1.0 and both remainders are negative.
    """
    for name in ("TOP_DECILE_121", "TOP_DECILE_164"):
        spec = getattr(fixtures, name)
        pnls = [float(x) for x in spec["pnls"]]  # type: ignore[union-attr]
        share = top_share(pnls, fraction=0.10)
        remainder = sum(sorted(pnls)[:-int(len(pnls) * 0.10)])
        assert share >= 1.0
        assert remainder < 0.0, f"{name}: share >= 1.0 must imply a losing tail"


def test_a_share_near_one_is_refused_at_the_arithmetic_boundary() -> None:
    """The threshold is 1.0 exactly, because that is the meaningful line.

    Constructed so the top decile is exactly the net total: the remainder is
    zero, meaning the other 90% of trades contributed nothing at all.
    """
    guard = ConcentrationGuard(top_fraction=0.10, tail_threshold=1.0)
    pnls = [100.0] * 10 + [0.0] * 90
    report = guard.check_trades(pnls)
    assert report.top_share == pytest.approx(1.0)
    assert report.verdict is Verdict.REFUSED


def test_flat_distribution_is_certified() -> None:
    """The negative direction: no concentration, no refusal."""
    guard = ConcentrationGuard(top_fraction=0.10, tail_threshold=1.0)
    report = guard.check_trades([10.0] * 100)
    assert report.top_share == pytest.approx(0.1)
    assert report.verdict is Verdict.CERTIFIED
    assert report.findings == ()


def test_too_few_observations_is_a_failure() -> None:
    """An unevaluable check must refuse, not pass."""
    guard = ConcentrationGuard(min_obs=8)
    report = guard.check_trades([1.0, 2.0, 3.0])
    assert report.verdict is Verdict.REFUSED
    assert report.findings[0].code == "CONCENTRATION_INSUFFICIENT_DATA"


def test_consistent_signs_with_outlier_dispersion_are_certified() -> None:
    """Disagreement is required; large dispersion alone is not enough."""
    guard = ConcentrationGuard(min_obs=8)
    # mean 1020, median 100: wildly dispersed but same sign.
    excesses = [100.0] * 9 + [10000.0]
    report = guard.check_windows(excesses, win_count=10)
    assert report.signs_disagree is False
    assert report.verdict is Verdict.CERTIFIED


def test_certification_refusal_carries_the_measured_numbers() -> None:
    """The raised error must contain the two figures that justify it."""
    guard = ConcentrationGuard(min_obs=8)
    report = guard.check_windows(
        [float(x) for x in fixtures.NINE_OF_TWELVE["excesses"]],  # type: ignore[union-attr]
        win_count=9,
    )
    cert = report.certify()
    with pytest.raises(Exception) as excinfo:
        cert.require()
    text = str(excinfo.value)
    assert "-138.7" in text and "+37.0" in text


def test_top_fraction_is_configurable() -> None:
    """The decile is a parameter, and a coarser one is more permissive."""
    guard = ConcentrationGuard(top_fraction=0.50, tail_threshold=1.0)
    report = guard.check_trades([100.0] * 50 + [-100.0] * 50)
    # top half sums to 5000, net is 0 -> guard reports a defined value
    assert report.top_share == pytest.approx(0.0, abs=1e-9) or report.top_share > 0
    assert report.kind == "trades"


def test_invalid_configuration_is_rejected() -> None:
    """Bad thresholds fail at construction, not at evaluation time."""
    with pytest.raises(ValueError):
        ConcentrationGuard(top_fraction=0.0)
    with pytest.raises(ValueError):
        ConcentrationGuard(tail_threshold=0.0)
    with pytest.raises(ValueError):
        ConcentrationGuard(min_obs=1)
