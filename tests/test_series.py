"""Guard 6 -- structural data traps.

The measured failures: a level discontinuity that fabricates a -24,046 pp
"daily return" when differenced across; a portfolio 11 days old returning 365
points because the series was zero-padded; and a 185 bps error from assuming a
forward 15m bar starts one minute after its left edge.
"""

from __future__ import annotations

import random
from datetime import date, datetime, timedelta

import pytest

from honest_backtest import fixtures
from honest_backtest.guards.series import (
    SeriesGuard,
    check_contiguous,
    detect_splice,
    forward_bar_offset,
    left_edge_bar_start,
    left_edge_window,
    price_error_bps,
    truncate_leading_padding,
)
from honest_backtest.types import Verdict


# ---------------------------------------------------------------------------
# the splice
# ---------------------------------------------------------------------------


def test_spliced_metrics_fixture_reproduces_the_fabricated_value(
    spliced_metrics: dict,
) -> None:
    """The headline fixture: differencing across the splice fabricates -24,046 pp."""
    assert spliced_metrics["expected_fabricated_daily_return_pp"] == -24046.0
    assert spliced_metrics["detected"] is True
    assert spliced_metrics["jump"] == pytest.approx(-24046.0, abs=0.5)
    assert spliced_metrics["verdict"] == "REFUSED"
    assert spliced_metrics["splice_index"] == 119


def test_splice_ratio_is_orders_of_magnitude_not_a_margin() -> None:
    """The flag is not a close call; that is what makes it trustworthy."""
    payload = fixtures.spliced_metrics()
    assert float(payload["ratio"]) > 1000.0  # type: ignore[arg-type]


def test_splice_finding_names_both_metrics_implication() -> None:
    """The message must explain the consequence, not just the symptom."""
    payload = fixtures.spliced_metrics()
    message = payload["findings"][0]["message"]  # type: ignore[index]
    assert "two different metrics spliced end-to-end" in message
    assert "fabricated" in message


def test_clean_series_has_no_splice() -> None:
    """The negative direction: a stationary high-variance series is clean."""
    report = detect_splice(fixtures.clean_series(), threshold=25.0)
    assert report.detected is False
    assert report.verdict is Verdict.CERTIFIED
    assert report.findings == ()


def test_a_volatile_series_is_not_flagged_merely_for_being_volatile() -> None:
    """Local comparison, not global: volatility is not a splice."""
    rng = random.Random(4)
    volatile = [100.0]
    for _ in range(200):
        volatile.append(volatile[-1] + rng.gauss(0.0, 25.0))
    report = detect_splice(volatile, threshold=25.0)
    assert report.detected is False


def test_a_splice_inside_a_quiet_region_is_caught_by_the_z_backstop() -> None:
    """A uniformly flat series with one step: the local test alone is blind."""
    flat = [1.0] * 100
    flat[50] = 400.0
    report = detect_splice(flat, threshold=25.0)
    assert report.detected is True
    assert report.index == 49


def test_a_level_shift_is_distinguished_from_a_gradual_ramp() -> None:
    """A ramp is a real trend; a step is a splice. Only the step fires."""
    ramp = [100.0 + 5.0 * i for i in range(120)]
    report = detect_splice(ramp, threshold=25.0)
    assert report.detected is False, "a constant-slope ramp is not a discontinuity"


def test_short_series_is_reported_not_silently_passed() -> None:
    """Too few points to scan is stated, and it is not a certification claim."""
    report = detect_splice([1.0, 2.0, 3.0], min_points=8)
    assert report.detected is False
    assert any("not attempted" in f.message for f in report.findings)


def test_constant_series_returns_no_false_alarm() -> None:
    """A constant series has no scale; the guard must not divide by zero."""
    report = detect_splice([5.0] * 50)
    assert report.detected is False


# ---------------------------------------------------------------------------
# zero padding
# ---------------------------------------------------------------------------


def test_zero_padded_inception_fixture() -> None:
    """An 11-day-old portfolio returning 365 points."""
    payload = fixtures.zero_padded_inception()
    assert payload["n_points"] == 365
    assert payload["padding_detected"] == 354
    assert payload["usable_points"] == 11
    assert payload["verdict"] == "REFUSED"


def test_truncate_leading_padding_drops_only_the_leading_run() -> None:
    """Interior zeros are data; only the leading run is padding."""
    values = [0.0, 0.0, 0.0, 1.0, 0.0, 2.0, 0.0]
    trimmed, dropped = truncate_leading_padding(values, padding_value=0.0)
    assert dropped == 3
    assert trimmed == [1.0, 0.0, 2.0, 0.0]


def test_padding_check_refuses_any_unremoved_padding() -> None:
    """Default tolerance is zero: unremoved padding fabricates a track record."""
    guard = SeriesGuard()
    report = guard.check_padding([0.0] * 354 + [float(i) for i in range(1, 12)])
    assert report.verdict is Verdict.REFUSED
    assert report.padding == 354
    assert report.findings[0].code == "SERIES_LEADING_PADDING"


def test_a_series_with_no_padding_is_certified() -> None:
    """The negative direction."""
    guard = SeriesGuard()
    report = guard.check_padding([1.0, 2.0, 3.0] * 40)
    assert report.verdict is Verdict.CERTIFIED
    assert report.padding == 0


def test_padding_and_timestamps_must_agree_in_length() -> None:
    """A length mismatch is a caller bug and must raise."""
    stamps = [datetime(2024, 1, 1) + timedelta(days=i) for i in range(5)]
    with pytest.raises(ValueError, match="length mismatch"):
        truncate_leading_padding([1.0, 2.0], timestamps=stamps)


# ---------------------------------------------------------------------------
# index contiguity
# ---------------------------------------------------------------------------


def test_contiguous_index_passes() -> None:
    """A regular grid is clean."""
    stamps = [datetime(2024, 1, 1) + timedelta(days=i) for i in range(30)]
    report = check_contiguous(stamps, step=timedelta(days=1))
    assert report.contiguity_ok is True
    assert report.monotonic_ok is True
    assert report.verdict is Verdict.CERTIFIED


def test_a_missing_bar_is_detected_and_counted() -> None:
    """A silently dropped bar breaks event-based statistics invisibly."""
    stamps = [datetime(2024, 1, 1) + timedelta(days=i) for i in range(30)]
    del stamps[10]
    report = check_contiguous(stamps, step=timedelta(days=1))
    assert report.contiguity_ok is False
    assert report.verdict is Verdict.REFUSED
    assert report.n_missing >= 1
    assert report.findings[0].code == "SERIES_INDEX_NOT_CONTIGUOUS"


def test_duplicate_timestamps_are_detected() -> None:
    """Reverse or duplicate bars break every cumulative statistic."""
    base = datetime(2024, 1, 1)
    stamps = [base, base + timedelta(days=1), base + timedelta(days=1), base + timedelta(days=2)]
    report = check_contiguous(stamps, step=timedelta(days=1))
    assert report.monotonic_ok is False
    assert report.verdict is Verdict.REFUSED
    assert any(f.code == "SERIES_INDEX_NOT_MONOTONIC" for f in report.findings)


def test_empty_index_is_refused() -> None:
    """An empty index is not a clean index."""
    report = check_contiguous([], step=timedelta(days=1))
    assert report.verdict is Verdict.REFUSED
    assert report.n_points == 0


def test_non_strict_mode_downgrades_gaps_to_a_warning() -> None:
    """Gaps can be legitimate (market closures); the caller decides."""
    stamps = [datetime(2024, 1, 1) + timedelta(days=i) for i in range(30)]
    del stamps[10]
    report = check_contiguous(stamps, step=timedelta(days=1), strict=False)
    assert report.contiguity_ok is False
    assert report.verdict is Verdict.CERTIFIED
    assert report.findings[0].status.value == "WARN"


def test_expected_start_mismatch_is_flagged() -> None:
    """A series that does not begin where the panel says it should is noted."""
    stamps = [datetime(2024, 1, 5) + timedelta(days=i) for i in range(10)]
    report = check_contiguous(
        stamps, step=timedelta(days=1), expected_start=datetime(2024, 1, 1)
    )
    assert any("not the expected" in f.message for f in report.findings)


# ---------------------------------------------------------------------------
# the left edge
# ---------------------------------------------------------------------------


def test_left_edge_convention_is_the_contract() -> None:
    """A 15m bar labelled t0 spans [t0, t0+15m)."""
    t0 = datetime(2024, 3, 1, 9, 30)
    span = timedelta(minutes=15)
    assert left_edge_bar_start(t0, span) == t0
    start, end = left_edge_window(t0, span)
    assert start == t0
    assert end == t0 + timedelta(minutes=15)


def test_forward_bar_offset_reproduces_the_timing_error() -> None:
    """Assuming a forward bar starts at t0+1m is 9,333 bps of timing error."""
    t0 = datetime(2024, 3, 1, 9, 30)
    span = timedelta(minutes=15)
    correct, error_bps = forward_bar_offset(
        t0, span, assumed_offset=timedelta(minutes=1)
    )
    assert correct == t0 + timedelta(minutes=15)
    assert error_bps == pytest.approx(9333.3, abs=0.1)


def test_correct_assumption_yields_no_error() -> None:
    """Assuming the next bar starts at the current bar's end is exact."""
    t0 = datetime(2024, 3, 1, 9, 30)
    span = timedelta(minutes=15)
    correct, error_bps = forward_bar_offset(t0, span, assumed_offset=span)
    assert correct == t0 + span
    assert error_bps == 0.0


def test_tolerance_collapses_a_small_miss_to_zero() -> None:
    """A caller can distinguish 'no error' from 'small error'.

    A one-second miss on a 15-minute bar is 11.1 bps of timing error. That is
    within a 20 bps tolerance and outside a 10 bps one, and the guard must
    report each correctly rather than rounding both to zero.
    """
    t0 = datetime(2024, 3, 1, 9, 30)
    span = timedelta(minutes=15)
    miss = span - timedelta(seconds=1)

    _, within = forward_bar_offset(t0, span, assumed_offset=miss, tolerance_bps=20.0)
    _, outside = forward_bar_offset(t0, span, assumed_offset=miss, tolerance_bps=10.0)

    assert within == 0.0
    assert outside == pytest.approx(11.111, abs=0.01)


def test_price_error_bps_matches_the_measured_185_bps() -> None:
    """The fixture's measured price error, expressed directly.

    A 15m bar read one minute off, on a bar whose price moved 1.85% between the
    two candidate timestamps, is 185 bps.
    """
    measured = price_error_bps(price_at_correct=100.0, price_at_assumed=101.85)
    assert measured == pytest.approx(185.0, abs=1e-9)
    assert measured == pytest.approx(
        float(fixtures.LEFT_EDGE_BAR["measured_error_bps"]), abs=1e-9
    )


def test_left_edge_fixture_payload() -> None:
    """The shipped fixture reproduces the interval and the error."""
    payload = fixtures.left_edge_bar()
    assert payload["covered_interval"] == "[2024-03-01T09:30:00, 2024-03-01T09:45:00)"
    assert payload["correct_forward_start"] == "2024-03-01T09:45:00"
    assert payload["assumed_forward_start"] == "2024-03-01T09:31:00"
    assert payload["verdict"] == "REFUSED"


def test_invalid_bar_span_is_rejected() -> None:
    """A non-positive bar span is meaningless."""
    with pytest.raises(ValueError):
        left_edge_bar_start(datetime(2024, 1, 1), timedelta(0))
    with pytest.raises(ValueError):
        price_error_bps(0.0, 1.0)


def test_series_guard_wraps_the_checks() -> None:
    """The guard object exposes the same behaviour as the free functions."""
    guard = SeriesGuard(splice_ratio=25.0)
    assert guard.check_splice(fixtures.clean_series()).detected is False
    stamps = [datetime(2024, 1, 1) + timedelta(days=i) for i in range(20)]
    assert guard.check_index(stamps, step=timedelta(days=1)).verdict is Verdict.CERTIFIED


def test_invalid_guard_thresholds_rejected() -> None:
    """Thresholds are validated at construction."""
    with pytest.raises(ValueError):
        SeriesGuard(splice_ratio=1.0)
    with pytest.raises(ValueError):
        SeriesGuard(z_threshold=1.0)
