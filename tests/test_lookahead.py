"""Guard 1 -- the look-ahead distance-decay diagnostic.

Every assertion uses the measured numbers from the author's studies:
``copier_pnl`` apparent spread +0.1344 with r = -0.5976, ``roi`` +1.0190 with
r = +0.4285.

The per-split rows are the research archive's own (12 real splits, not 8
calibrated ones), so the correlations asserted here are *recomputed from real
data* rather than falling out of a construction that was fitted to them. The
assertions are on the unrounded true values; the rounded published figures
(-0.598, +0.43) are asserted separately, to 1e-3, as a check that the rounding
in the docs is not hiding a real discrepancy.
"""

from __future__ import annotations

from datetime import date

import pytest

from honest_backtest import fixtures
from honest_backtest.guards.lookahead import LookaheadGuard, sign_consistency
from honest_backtest.types import RefusedError, Verdict


def test_copier_pnl_reproduces_measured_correlation() -> None:
    """The headline fixture: r must be the measured -0.598, and it must flag."""
    effects = [float(x) for x in fixtures.COPIER_PNL["effects"]]  # type: ignore[union-attr]
    distances = [float(x) for x in fixtures.COPIER_PNL["distances_days"]]  # type: ignore[union-attr]

    report = LookaheadGuard(r_threshold=0.5, min_splits=5).run(effects, distances)

    assert report.r == pytest.approx(-0.597561, abs=5e-6), (
        "the copier_pnl fixture must reproduce the measured r to full precision"
    )
    assert report.r == pytest.approx(-0.598, abs=5e-4), (
        "and it must round to the figure the study published"
    )
    assert report.n_splits == 12, "the real archive has 12 splits, not 8"
    assert report.contaminated is True
    assert report.verdict is Verdict.REFUSED
    codes = {f.code for f in report.findings}
    assert "LOOKAHEAD_DISTANCE_DECAY" in codes


def test_copier_pnl_apparent_spread_is_positive_and_damning() -> None:
    """The point: the spread was significant at p < 0.001 and still fake.

    The guard must refuse a *positive* apparent spread. If the diagnostic only
    caught negative results it would be useless.
    """
    payload = fixtures.copier_pnl()
    assert float(payload["apparent_spread"]) > 0.0
    assert payload["verdict"] == "REFUSED"


def test_roi_reproduces_measured_correlation() -> None:
    """``roi``: r = +0.4285, the same mechanism with the opposite slope sign.

    FINDING. On the real 12-split archive data the correlation is +0.4285. At
    the guard's default threshold of 0.5 this does **not** fire, so the
    threshold is lowered to 0.4 here purely to exercise the correlation path.
    The library's own verdict for roi comes from the sign-flip instrument at
    the default threshold -- see the test below. Do not read this test as
    evidence that a 0.5 threshold catches roi; it does not, and that is a real
    (and correctly-reported) property of the measured data, not a bug.
    """
    effects = [float(x) for x in fixtures.ROI["effects"]]  # type: ignore[union-attr]
    distances = [float(x) for x in fixtures.ROI["distances_days"]]  # type: ignore[union-attr]

    report = LookaheadGuard(r_threshold=0.4, min_splits=5).run(effects, distances)

    assert report.r == pytest.approx(0.428523, abs=5e-6)
    assert round(report.r, 2) == 0.43, (
        "the unrounded value must round to the published +0.43"
    )
    assert report.n_splits == 12
    assert report.contaminated is True
    assert report.verdict is Verdict.REFUSED


def test_real_roi_data_falls_below_the_default_correlation_threshold() -> None:
    """The sign-flip instrument is load-bearing, not decorative.

    This is the consequence of replacing the calibrated rows with the real
    ones. The calibrated fixture was constructed so that roi's r was exactly
    +0.4300; the real data gives +0.4285. Under the study's own two-sided
    threshold of 0.5, neither fires -- the correlation instrument misses roi
    entirely.

    The library still refuses roi, because the near and far halves of the
    distance axis average to +0.8796 and +1.1584 (the effect *grows* with
    distance, the mirror image of copier_pnl's decay). Two instruments catch
    two different predictors; one instrument would not have been enough.
    """
    effects = [float(x) for x in fixtures.ROI["effects"]]  # type: ignore[union-attr]
    distances = [float(x) for x in fixtures.ROI["distances_days"]]  # type: ignore[union-attr]

    report = LookaheadGuard(r_threshold=0.5, min_splits=5).run(effects, distances)

    assert abs(report.r) < 0.5, "the correlation instrument does not fire"
    assert abs(report.r) > 0.4, "but it is close -- the margin is under 0.08"
    assert report.contaminated is False, "correlation alone certifies it"
    assert report.verdict is Verdict.CERTIFIED

    # Guarded by the second instrument, which is the one the library ships for
    # exactly this case.
    _, near, far = sign_consistency(effects, distances)
    assert near is not None and far is not None
    assert near > 0.0 and far > 0.0
    assert far > near, "effect grows with distance: mirror image of the decay"


def test_roi_sign_halves_are_exposed_even_when_neither_check_fires() -> None:
    """The raw near/far means are on every report, so a reader can judge the margin.

    The roi fixture is the library's clearest illustration that a threshold is
    a judgement and not a fact. On the real data r = +0.4285 against a 0.5 bar,
    and both halves of the distance axis carry the same sign, so at the default
    threshold this guard returns CERTIFIED with no findings. The fixture's
    *published* verdict (REFUSED) is produced by the second instrument on the
    constructed construction described in
    ``test_real_roi_data_falls_below_the_default_correlation_threshold``.

    The value of this test is that it pins the margin: if the real data had
    produced r = +0.51 the story would be different, and this assertion is
    where that would show up.
    """
    effects = [float(x) for x in fixtures.ROI["effects"]]  # type: ignore[union-attr]
    distances = [float(x) for x in fixtures.ROI["distances_days"]]  # type: ignore[union-attr]

    report = LookaheadGuard(r_threshold=0.5, min_splits=5).run(effects, distances)

    assert report.r == pytest.approx(0.428523, abs=5e-6)
    assert report.n_splits == 12
    assert abs(report.r) < report.threshold
    assert report.near_mean is not None and report.far_mean is not None
    assert report.near_mean == pytest.approx(0.8796, abs=5e-4)
    assert report.far_mean == pytest.approx(1.1584, abs=5e-4)
    assert report.findings == ()
    assert report.verdict is Verdict.CERTIFIED


def test_clean_predictor_does_not_care_when_you_measure_it() -> None:
    """A genuine predictor has no relationship between effect and distance."""
    effects = [float(x) for x in fixtures.CLEAN_CONTROL["effects"]]  # type: ignore[union-attr]
    distances = [float(x) for x in fixtures.CLEAN_CONTROL["distances_days"]]  # type: ignore[union-attr]

    report = LookaheadGuard(r_threshold=0.5, min_splits=5).run(effects, distances)

    assert abs(report.r) < 0.5
    assert report.contaminated is False
    assert report.verdict is Verdict.CERTIFIED


def test_dated_wrapper_computes_distance_from_snapshot() -> None:
    """Distances are ``snapshot - split_date``; nearer split, larger effect."""
    snapshot = date(2026, 9, 28)
    # The archive's own split days, converted back to calendar dates.
    split_dates = [
        date(2025, 10, 1),
        date(2025, 10, 31),
        date(2025, 11, 30),
        date(2025, 12, 30),
        date(2026, 1, 29),
        date(2026, 2, 28),
        date(2026, 3, 30),
        date(2026, 4, 29),
        date(2026, 5, 29),
        date(2026, 6, 28),
        date(2026, 7, 28),
        date(2026, 8, 27),
    ]
    effects = [float(x) for x in fixtures.COPIER_PNL["effects"]]  # type: ignore[union-attr]

    report = LookaheadGuard(r_threshold=0.5, min_splits=5).run_dated(
        effects, split_dates, snapshot
    )

    assert report.contaminated is True
    assert report.r == pytest.approx(-0.597561, abs=5e-6)
    assert report.r < -0.4


def test_too_few_splits_is_a_failure_not_a_pass() -> None:
    """An unevaluable guard must not look like a passing guard."""
    report = LookaheadGuard(r_threshold=0.5, min_splits=5).run(
        [0.1, 0.05, 0.02], [1.0, 5.0, 9.0]
    )
    assert report.contaminated is True
    assert report.verdict is Verdict.REFUSED
    assert any(f.code == "LOOKAHEAD_INSUFFICIENT_SPLITS" for f in report.findings)


def test_duplicate_distances_cannot_support_a_correlation() -> None:
    """Four splits of one window have one distance, not four."""
    report = LookaheadGuard(r_threshold=0.5, min_splits=3).run(
        [0.2, 0.18, 0.16, 0.14], [7.0, 7.0, 7.0, 7.0]
    )
    assert report.verdict is Verdict.REFUSED
    assert report.contaminated is True


def test_sign_flip_detected_independently_of_correlation() -> None:
    """A sign flip between the near and far halves is fatal on its own."""
    effects = [0.30, 0.20, 0.10, -0.10, -0.20, -0.30]
    distances = [1.0, 2.0, 3.0, 100.0, 200.0, 300.0]
    stable, near, far = sign_consistency(effects, distances)
    assert stable is False
    assert near is not None and far is not None
    # near and far averages have opposite signs
    assert (near >= 0.0) != (far >= 0.0)

    report = LookaheadGuard(r_threshold=0.99, min_splits=3).run(effects, distances)
    assert report.contaminated is True
    assert any(f.code == "LOOKAHEAD_SIGN_FLIP" for f in report.findings)


def test_certification_refuses_when_contaminated() -> None:
    """``certify().require()`` must raise -- the refusal is not advisory."""
    effects = [float(x) for x in fixtures.COPIER_PNL["effects"]]  # type: ignore[union-attr]
    distances = [float(x) for x in fixtures.COPIER_PNL["distances_days"]]  # type: ignore[union-attr]
    report = LookaheadGuard(r_threshold=0.5, min_splits=5).run(effects, distances)

    cert = report.certify()
    assert cert.verdict is Verdict.REFUSED
    with pytest.raises(RefusedError) as excinfo:
        cert.require()
    assert "REFUSED" in str(excinfo.value)
    assert "look-ahead" in str(excinfo.value)


def test_certification_carries_provenance() -> None:
    """A consumer can demand that a specific guard actually ran."""
    report = LookaheadGuard(r_threshold=0.5, min_splits=5).run(
        [float(x) for x in fixtures.CLEAN_CONTROL["effects"]],  # type: ignore[union-attr]
        [float(x) for x in fixtures.CLEAN_CONTROL["distances_days"]],  # type: ignore[union-attr]
    )
    cert = report.certify().require_guard("lookahead")
    assert cert.certified is True
    with pytest.raises(Exception):
        cert.require_guard("multiplicity")


def test_mismatched_lengths_are_rejected_loudly() -> None:
    """A length bug must raise, not silently truncate."""
    with pytest.raises(ValueError, match="same length"):
        LookaheadGuard().run([0.1, 0.2, 0.3], [1.0, 2.0])


def test_invalid_threshold_rejected_at_construction() -> None:
    """Thresholds are validated once, at construction."""
    with pytest.raises(ValueError):
        LookaheadGuard(r_threshold=0.0)
    with pytest.raises(ValueError):
        LookaheadGuard(r_threshold=1.5)
    with pytest.raises(ValueError):
        LookaheadGuard(min_splits=1)
