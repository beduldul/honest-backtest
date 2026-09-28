"""Guard 3 -- overlapping and nested evaluation windows.

THE MEASURED FAILURE
--------------------
A walk-forward design reported **4 splits**. All four shared the same end date.
The forward windows were strictly nested, each containing the previous one's
data. The number of pairwise-independent windows was **zero**.

The report said "0 of 4 negative". That reads as four confirmations. It is one
observation, repeated four times, with a shrinking start date. The effective
sample was **one**.

The fix was a non-overlapping design that extracted **12 genuinely disjoint
30-day windows** from the same 365-day panel. Note the inversion: the number
went *up*, from 4 to 12, because the 4 were never 4.

THE REFUSAL
-----------
This script shows both plans side by side, and the refusal that the nested one
earns.
"""

from __future__ import annotations

import sys
from datetime import date

from honest_backtest import fixtures
from honest_backtest.guards.windows import WindowGuard, WindowPlan
from honest_backtest.plans import Window
from honest_backtest.types import RefusedError


def nested_plan() -> WindowPlan:
    """The broken design: four splits, one shared end date."""
    starts = fixtures.NESTED_FOUR_SPLIT["starts"]
    end = fixtures.NESTED_FOUR_SPLIT["shared_end"]
    assert isinstance(starts, list) and isinstance(end, date)
    return WindowPlan(
        windows=tuple(
            Window(start=s, end=end, label=f"split{i + 1}")  # type: ignore[arg-type]
            for i, s in enumerate(starts)
        ),
        label="walk_forward (as designed)",
        claimed=4,
    )


def disjoint_plan() -> WindowPlan:
    """The fix: twelve disjoint 30-day windows from the same panel."""
    spec = fixtures.DISJOINT_TWELVE
    return WindowPlan.tiled(
        spec["panel_start"],  # type: ignore[arg-type]
        spec["panel_end"],  # type: ignore[arg-type]
        length_days=int(spec["window_days"]),  # type: ignore[arg-type]
        label="non-overlapping rebuild",
    )


def show(plan: WindowPlan, story: str) -> None:
    """Report one plan's independence count and verdict."""
    print("=" * 72)
    print(f"{plan.label}: {story}")
    print("=" * 72)

    report = WindowGuard(min_independent=2).run(plan)

    print(f"  windows supplied       : {len(plan)}")
    print(f"  claimed                : {plan.claimed if plan.claimed is not None else '(not stated)'}")
    print(f"  all share one end date : {plan.fully_nested}")
    print(f"  shared end count       : {plan.shared_end_count}")
    print(f"  independent windows    : {report.independent_count}")
    print(f"  max disjoint subset    : {plan.max_disjoint()}")
    print(f"  span (days)            : {plan.span_days()}")
    print(f"  required minimum       : {report.required}")
    print()

    for finding in report.findings:
        print(f"  [{finding.status.value}] {finding.code}")
        print(f"      {finding.message}")
        print()

    if report.findings:
        print("  In other words:")
        for finding in report.findings:
            for sentence in str(finding.message).split("; "):
                print(f"    - {' '.join(sentence.split())}")
        print()

    print(f"  verdict: {report.verdict.value}")
    if report.verdict.value == "REFUSED":
        try:
            report.certify().require()
        except RefusedError as exc:
            print("  -> REFUSED: '0 of 4 negative' cannot be read as four confirmations")
            print(f"     {exc}")
    else:
        print("  -> usable: this design supports a claim")
    print()


def main() -> int:
    """Show the broken design, the fix, and the inversion between them."""
    broken = nested_plan()
    fixed = disjoint_plan()

    show(broken, '"4 splits" that were four views of one window')
    show(fixed, "12 genuinely disjoint 30-day windows from the same 365-day panel")

    print("=" * 72)
    print("the inversion")
    print("=" * 72)
    print(f"  broken design claimed      : 4 splits")
    print(f"  broken design independent  : {WindowGuard().run(broken).independent_count}")
    print(f"  fixed design independent   : {WindowGuard().run(fixed).independent_count}")
    print()
    print("  The fixed design reports MORE independent windows than the broken")
    print("  one claimed. The broken number was never 4.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
