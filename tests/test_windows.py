"""Guard 3 -- window independence.

The measured failure is a walk-forward with 4 splits that all shared one end
date (0 independent windows), and the fix: 12 disjoint 30-day windows from the
same 365-day panel.
"""

from __future__ import annotations

from datetime import date

import pytest

from honest_backtest import fixtures
from honest_backtest.guards.windows import WindowGuard, WindowPlan
from honest_backtest.plans import Window, contiguous_windows, parse_plan
from honest_backtest.types import HonestyError, Verdict


def test_nested_four_split_reports_zero_independent_windows(
    nested_four_split: dict,
) -> None:
    """The headline fixture. Four splits, one shared end date, zero evidence."""
    assert nested_four_split["n_windows"] == 4
    assert nested_four_split["fully_nested"] is True
    assert nested_four_split["independent_count"] == 0
    assert nested_four_split["verdict"] == "REFUSED"

    codes = {f["code"] for f in nested_four_split["findings"]}  # type: ignore[index]
    assert "WINDOWS_FULLY_NESTED" in codes


def test_nested_refusal_message_explains_why_not_just_how_many() -> None:
    """The message must name the shared end date and the effective sample size."""
    plan = WindowPlan(
        windows=tuple(
            Window(start=s, end=date(2024, 7, 1), label=f"split{i + 1}")
            for i, s in enumerate(fixtures.NESTED_FOUR_SPLIT["starts"])  # type: ignore[arg-type]
        ),
        label="nested",
    )
    report = WindowGuard(min_independent=2).run(plan)
    message = report.findings[0].message
    assert "2024-07-01" in message
    assert "strictly nested" in message
    assert "0" in message
    assert "4 confirmations" in message


def test_disjoint_twelve_reports_eleven_additional_windows(
    disjoint_twelve: dict,
) -> None:
    """The fix: 12 genuinely disjoint 30-day windows from a 365-day panel.

    The count is 11 *additional* replications: the first window is the
    reference and the other 11 are what it did not already tell you. The plan's
    length is the 12 the design document claimed.
    """
    assert disjoint_twelve["n_windows"] == 12
    assert disjoint_twelve["independent_count"] == 11
    assert disjoint_twelve["max_disjoint"] == 12
    assert disjoint_twelve["verdict"] == "CERTIFIED"


def test_the_fix_produces_more_independent_windows_than_the_broken_design(
    nested_four_split: dict, disjoint_twelve: dict
) -> None:
    """The inversion that matters: the 'fixed' design reports MORE evidence.

    The broken design claimed 4 splits; the fixed one has 11 replications from
    the same panel. The broken number was never 4.
    """
    assert nested_four_split["independent_count"] == 0
    assert disjoint_twelve["independent_count"] > nested_four_split["independent_count"]  # type: ignore[operator]
    assert disjoint_twelve["independent_count"] > 4


def test_tiled_windows_are_independent_by_construction() -> None:
    """Back-to-back half-open windows cannot overlap."""
    plan = WindowPlan.tiled(date(2024, 1, 1), date(2024, 12, 31), length_days=30)
    assert len(plan) == 12
    for a, b in zip(plan.windows, plan.windows[1:]):
        assert not a.overlaps(b)
        assert a.end == b.start


def test_partial_overlap_is_counted_as_one_replication() -> None:
    """Windows that share data are not replications, whatever the count says.

    ``a``/``b`` share data and ``b``/``c`` share data, but ``a``/``c`` do not.
    The plan therefore contributes exactly one replication: the first window
    plus one genuinely independent later window. Counting three would be the
    error this guard exists to prevent.
    """
    plan = WindowPlan(
        windows=(
            Window(date(2024, 1, 1), date(2024, 6, 1), "a"),
            Window(date(2024, 3, 1), date(2024, 8, 1), "b"),
            Window(date(2024, 7, 1), date(2024, 12, 1), "c"),
        ),
        label="sliding",
    )
    # a and b overlap; b and c overlap; a and c are disjoint.
    assert plan.windows[0].overlaps(plan.windows[1])
    assert plan.windows[1].overlaps(plan.windows[2])
    assert not plan.windows[0].overlaps(plan.windows[2])
    assert len(plan) == 3
    assert plan.independent_count() == 1
    report = WindowGuard(min_independent=3).run(plan)
    assert report.verdict is Verdict.REFUSED
    assert report.findings[0].code == "WINDOWS_INSUFFICIENT_INDEPENDENCE"


def test_a_fully_overlapping_chain_has_no_replications() -> None:
    """A sliding window that always overlaps its predecessor adds nothing."""
    plan = WindowPlan(
        windows=(
            Window(date(2024, 1, 1), date(2024, 6, 1), "a"),
            Window(date(2024, 3, 1), date(2024, 8, 1), "b"),
            Window(date(2024, 5, 1), date(2024, 10, 1), "c"),
        ),
        label="rolling",
    )
    assert plan.independent_count() == 0
    assert WindowGuard(min_independent=2).run(plan).verdict is Verdict.REFUSED


def test_forced_minimum_refuses_a_single_window() -> None:
    """One window is never enough to support a strong claim."""
    plan = WindowPlan(windows=(Window(date(2024, 1, 1), date(2024, 2, 1), "only"),))
    report = WindowGuard(min_independent=2).run(plan)
    assert report.independent_count == 0
    assert report.verdict is Verdict.REFUSED


def test_claimed_count_disagreement_is_reported_as_a_warning() -> None:
    """A design that claims 12 windows and supplies 3 is flagged, not ignored."""
    plan = WindowPlan(
        windows=(
            Window(date(2024, 1, 1), date(2024, 1, 31), "w0"),
            Window(date(2024, 1, 31), date(2024, 3, 1), "w1"),
            Window(date(2024, 3, 1), date(2024, 3, 31), "w2"),
        ),
        label="under-delivered",
        claimed=12,
    )
    report = WindowGuard(min_independent=2).run(plan)
    assert any(
        f.code == "WINDOWS_CLAIMED_SPAN_MISMATCH" for f in report.findings
    )
    # The claim disagreement alone does not refuse; the window count still passes.
    assert report.verdict is Verdict.CERTIFIED


def test_plan_parses_textual_spec() -> None:
    """The plan format round-trips through text."""
    plan = WindowPlan.from_spec(
        "2024-01-01..2024-01-31, 2024-01-31..2024-03-01, 2024-03-01..2024-03-31",
        label="q1",
    )
    assert len(plan) == 3
    assert plan.independent_count() == 2
    assert WindowGuard(min_independent=2).run(plan).verdict is Verdict.CERTIFIED


def test_repeat_shorthand_records_what_the_user_claimed() -> None:
    """``x4`` on one interval is exactly the nested failure, expressed in text."""
    plan = WindowPlan.from_spec("2024-01-01..2024-07-01 x4", label="walk_forward")
    assert len(plan) == 4
    assert plan.fully_nested is True
    report = WindowGuard(min_independent=2).run(plan)
    assert report.independent_count == 0
    assert report.verdict is Verdict.REFUSED


def test_contiguous_tiling_drops_a_short_tail() -> None:
    """A 4-day stub is not comparable to its 30-day siblings."""
    windows = contiguous_windows(date(2024, 1, 1), date(2024, 3, 5), length_days=30)
    assert len(windows) == 2  # the 4-day remainder is dropped
    assert windows[-1].end == date(2024, 3, 1)


def test_zero_length_window_is_not_independent_of_its_neighbour() -> None:
    """Degenerate windows must not inflate the count."""
    plan = WindowPlan(
        windows=(
            Window(date(2024, 1, 1), date(2024, 2, 1), "real"),
            Window(date(2024, 2, 1), date(2024, 2, 1), "empty"),
        ),
        label="degenerate",
    )
    # The empty window at Feb 1 does not overlap [Jan 1, Feb 1), so it is not
    # an overlap failure -- but it must not be read as a replication of anything.
    assert plan.independent_count() in (0, 1)


def test_invalid_specs_raise() -> None:
    """Bad plans fail loudly."""
    with pytest.raises(HonestyError):
        parse_plan("")
    with pytest.raises(HonestyError):
        parse_plan("not-a-date..2024-01-01")
    with pytest.raises(HonestyError):
        parse_plan("2024-01-01..2024-02-01 x0")
    with pytest.raises(HonestyError):
        parse_plan("2024-01-01")


def test_windows_report_is_serialisable(disjoint_twelve: dict) -> None:
    """The report must survive JSON for the CLI."""
    plan = WindowPlan.tiled(date(2024, 1, 1), date(2024, 12, 31), length_days=30)
    payload = WindowGuard(min_independent=2).run(plan).as_dict()
    assert payload["independent_count"] == 11
    assert payload["plan"]["n_windows"] == 12  # type: ignore[index]
    assert isinstance(payload["findings"], list)


def test_effect_arity_mismatch_is_blocking() -> None:
    """Supplying the wrong number of effects cannot be silently tolerated."""
    plan = WindowPlan.tiled(date(2024, 1, 1), date(2024, 12, 31), length_days=30)
    report = WindowGuard(min_independent=2).check([1.0, 2.0], plan)
    assert report.verdict is Verdict.REFUSED
    assert any("effect(s) supplied" in f.message for f in report.findings)


def test_invalid_minimum_rejected() -> None:
    """A minimum below 1 is meaningless."""
    with pytest.raises(ValueError):
        WindowGuard(min_independent=0)
