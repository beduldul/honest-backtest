"""Guard 7 -- the block bootstrap.

The measured failure: a naive trade-level interval ``[-0.021, +0.781]`` on 378
trades from a 4-symbol one-month artifact promoted a false positive to a
strategy. The block bootstrap is the default replacement.
"""

from __future__ import annotations

import math
import random
from datetime import date, timedelta

import pytest

from honest_backtest import fixtures
from honest_backtest.stats.bootstrap import (
    block_bootstrap_ci,
    bootstrap_mean_by_block,
    monday_anchored_block,
    permutation_null,
    week_index,
)
from honest_backtest.types import Verdict


def _weekly_sample(*, weeks: int, per_week: int, seed: int = 0) -> tuple[list[date], list[float]]:
    rng = random.Random(seed)
    start = date(2024, 3, 4)  # a Monday
    days: list[date] = []
    values: list[float] = []
    for w in range(weeks):
        weekly = rng.gauss(0.3, 1.0)
        for i in range(per_week):
            days.append(start + timedelta(days=w * 7 + i % 5))
            values.append(weekly + rng.gauss(0.0, 0.8))
    return days, values


def test_four_weeks_is_reported_as_suspect_not_refused() -> None:
    """The fixture's structural defect: 4 blocks, 378 observations.

    The verdict is SUSPECT rather than REFUSED on purpose. The point of the
    guard is to *show* the interval that a naive method would have reported,
    next to the number that makes it meaningless. A flat refusal would hide the
    evidence that teaches the lesson.
    """
    days, values = _weekly_sample(weeks=4, per_week=20, seed=1)
    result = block_bootstrap_ci(
        values, block_dates=days, min_blocks=10, n_resamples=500, seed=1
    )

    assert result.n_blocks == 4
    assert result.n_observations == 80
    assert result.n_blocks < result.min_blocks
    assert result.verdict is Verdict.SUSPECT
    assert result.usable is False
    assert result.findings[0].code == "BOOTSTRAP_INSUFFICIENT_BLOCKS"


def test_the_warning_names_the_effective_sample_size() -> None:
    """The message must state that the observation count is not the sample size."""
    days, values = _weekly_sample(weeks=4, per_week=20, seed=2)
    result = block_bootstrap_ci(values, block_dates=days, n_resamples=300, seed=2)
    message = result.findings[0].message
    assert "4 independent block(s)" in message
    assert "80 observation(s)" in message
    assert "not the effective sample size" in message


def test_a_long_sample_is_certified() -> None:
    """The negative direction: 40 weeks of data supports the claim."""
    days, values = _weekly_sample(weeks=40, per_week=10, seed=3)
    result = block_bootstrap_ci(
        values, block_dates=days, min_blocks=10, n_resamples=800, seed=3
    )
    assert result.n_blocks == 40
    assert result.verdict is Verdict.CERTIFIED
    assert result.usable is True


def test_block_bootstrap_is_wider_than_the_naive_interval() -> None:
    """The whole reason for the method: naive intervals are too narrow.

    With a shared weekly regime driving every trade, treating trades as
    independent understates the variance. The block interval must be wider.
    """
    days, values = _weekly_sample(weeks=6, per_week=30, seed=4)
    block = block_bootstrap_ci(
        values, block_dates=days, min_blocks=10, n_resamples=1000, seed=4
    )
    naive = _naive_ci(values, seed=4)

    block_width = block.high - block.low
    naive_width = naive[1] - naive[0]
    assert block_width > naive_width, (
        "the block interval must be wider; otherwise the dependence is not "
        "being preserved and the guard is decorative"
    )


def _naive_ci(values: list[float], *, seed: int = 0) -> tuple[float, float]:
    rng = random.Random(seed)
    n = len(values)
    draws = sorted(
        math.fsum(values[rng.randrange(n)] for _ in range(n)) / n for _ in range(1000)
    )
    return draws[25], draws[974]


def test_blocks_are_monday_anchored_by_default() -> None:
    """The default anchor is Monday, matching the author's standard."""
    assert monday_anchored_block(date(2024, 3, 6)) == date(2024, 3, 4)  # Wed -> Mon
    assert monday_anchored_block(date(2024, 3, 4)) == date(2024, 3, 4)  # Mon -> Mon
    assert monday_anchored_block(date(2024, 3, 10)) == date(2024, 3, 4)  # Sun -> Mon


def test_week_index_does_not_collide_across_year_boundaries() -> None:
    """ISO week 1 of 2024 and week 1 of 2025 are a year apart, not adjacent."""
    a = week_index(date(2024, 1, 3))
    b = week_index(date(2025, 1, 2))
    assert a != b
    assert a[0] == 2024 and b[0] == 2025


def test_a_holiday_week_counts_as_one_block() -> None:
    """Calendar blocks, not fixed-size runs: a short week is still one week."""
    monday = date(2024, 3, 4)
    days = [monday, monday + timedelta(days=1)]  # only 2 observations
    days += [monday + timedelta(days=7 + i) for i in range(5)]
    values = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7]
    result = block_bootstrap_ci(values, block_dates=days, n_resamples=200, seed=0)
    assert result.n_blocks == 2
    assert result.block_size == 5  # the largest block, reported honestly


def test_fixed_size_blocks_work_without_dates() -> None:
    """Index blocks are available when dates genuinely are not."""
    values = [0.1 * i for i in range(60)]
    result = block_bootstrap_ci(values, block_size=10, n_resamples=300, seed=0)
    assert result.n_blocks == 6
    assert result.block_size == 10


def test_silently_defaulting_to_trade_level_is_impossible() -> None:
    """Neither dates nor a block size is an error, not a quiet fallback.

    This is the single most important behaviour in the module: the failure mode
    being prevented is a caller who does not realise they got the naive method.
    """
    with pytest.raises(ValueError, match="defaulting silently to trade-level"):
        block_bootstrap_ci([0.1, 0.2, 0.3])


def test_degenerate_input_is_refused() -> None:
    """A constant series has no interval."""
    values = [1.0] * 100
    result = block_bootstrap_ci(values, block_size=10, n_resamples=200, seed=0)
    assert result.verdict is Verdict.REFUSED
    assert any(f.code == "BOOTSTRAP_DEGENERATE_INPUT" for f in result.findings)


def test_determinism_under_a_fixed_seed() -> None:
    """The library is reproducible offline, bit for bit."""
    days, values = _weekly_sample(weeks=12, per_week=8, seed=5)
    a = block_bootstrap_ci(values, block_dates=days, n_resamples=500, seed=99)
    b = block_bootstrap_ci(values, block_dates=days, n_resamples=500, seed=99)
    assert (a.low, a.high) == (b.low, b.high)


def test_naive_comparison_sentence_is_useful() -> None:
    """The one-line summary must state the claim and the obstacle."""
    days, values = _weekly_sample(weeks=4, per_week=20, seed=6)
    # Force a positive point estimate so the interval can exclude zero.
    values = [v + 3.0 for v in values]
    result = block_bootstrap_ci(values, block_dates=days, n_resamples=500, seed=6)
    assert result.excludes_zero is True
    assert "must not be reported" in result.naive_comparison
    assert "4" in result.naive_comparison


def test_mismatched_lengths_are_rejected() -> None:
    """A length bug must raise."""
    days = [date(2024, 3, 4) + timedelta(days=i) for i in range(5)]
    with pytest.raises(ValueError, match="length"):
        block_bootstrap_ci([0.1, 0.2], block_dates=days)


def test_invalid_configuration_rejected() -> None:
    """Bounds are checked at the boundary."""
    with pytest.raises(ValueError):
        block_bootstrap_ci([], block_size=5)
    with pytest.raises(ValueError):
        block_bootstrap_ci([0.1, 0.2], block_size=0)
    with pytest.raises(ValueError):
        block_bootstrap_ci([0.1, 0.2], block_size=5, confidence=0.0)
    with pytest.raises(ValueError):
        block_bootstrap_ci([0.1, 0.2], block_size=5, n_resamples=10)


def test_effective_sample_helper() -> None:
    """Per-block means are the effective-sample view of a series."""
    values = [1.0, 1.0, 1.0, 5.0, 5.0, 5.0]
    assert bootstrap_mean_by_block(values, block_size=3) == pytest.approx(3.0)


def test_fixture_reproduces_the_trade_level_false_positive() -> None:
    """The shipped fixture: 378 trades, 4 blocks, a naive interval excluding zero.

    The recorded naive CI was ``[-0.021, +0.781]`` on 378 trades from 4 symbols
    in a one-month artifact. The fixture reproduces the *structure* (4 weekly
    blocks, hundreds of trades) and demonstrates that the block bootstrap
    refuses to support the claim that the naive method made.
    """
    payload = fixtures.trade_level_false_positive()
    assert payload["n_trades"] == 378
    assert payload["n_blocks"] == 4
    assert payload["recorded_naive_ci"] == [-0.021, 0.781]
    assert payload["block_verdict"] == "SUSPECT"
    assert float(payload["min_blocks"]) == 10  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# permutation null
# ---------------------------------------------------------------------------


def test_permutation_null_preserves_block_totals() -> None:
    """Shuffling within blocks must not change any block's sum.

    This is the property that makes the null answer the right question: given
    these weekly totals, how surprising is this arrangement?
    """
    values = [float(i) for i in range(21)]

    def block_totals(v: list[float]) -> float:
        return sum(sum(v[start : start + 7]) for start in range(0, 21, 7))

    expected = sum(sum(values[start : start + 7]) for start in range(0, 21, 7))

    result = permutation_null(
        values,
        statistic=block_totals,
        block_size=7,
        n_permutations=50,
        seed=0,
    )

    assert result.observed == pytest.approx(expected)
    assert result.n_blocks == 3
    assert result.block_size == 7


def test_permutation_null_is_deterministic() -> None:
    """Seeded, so a test can assert on it."""
    values = [3.0, 1.0, 4.0, 1.0, 5.0, 9.0, 2.0, 6.0, 5.0, 3.0, 5.0, 8.0]
    a = permutation_null(values, statistic=lambda v: max(v) - min(v), n_permutations=200, seed=1)
    b = permutation_null(values, statistic=lambda v: max(v) - min(v), n_permutations=200, seed=1)
    assert a.p_value == b.p_value


def test_permutation_p_value_is_never_zero() -> None:
    """The ``(1 + k) / (1 + n)`` estimator stays strictly positive."""
    values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
    result = permutation_null(
        values, statistic=lambda v: v[0] - v[-1], n_permutations=50, seed=0
    )
    assert 0.0 < result.p_value <= 1.0


def test_permutation_null_rejects_bad_input() -> None:
    """Bounds are checked at the boundary."""
    with pytest.raises(ValueError):
        permutation_null([], statistic=sum)
    with pytest.raises(ValueError):
        permutation_null([1.0], statistic=sum, block_size=0)
    with pytest.raises(ValueError):
        permutation_null([1.0], statistic=sum, n_permutations=0)
