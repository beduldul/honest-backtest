"""Guard 4 -- benchmark-eligibility asymmetry.

THE MEASURED FAILURE
--------------------
The cohort filter excluded stale and dormant subjects. The benchmark filter did
not. Dormant subjects have a flat 0% forward return, so including them drags
the benchmark toward zero -- and a cohort of active subjects then looks skilful
against a benchmark that is half asleep.

Nothing in the output looked wrong. The spread was positive, the t-stat was
respectable, and the only symptom was statistical, which is the worst kind: a
statistical symptom invites tuning rather than a fix. The fix was to route both
sides through one shared predicate.

THE REFUSAL
-----------
This script shows the arithmetic of the defect first, then the guard refusing
two divergent filters.
"""

from __future__ import annotations

import sys

from honest_backtest import fixtures
from honest_backtest.guards.universe import (
    Selection,
    UniverseGuard,
    require_shared_predicate,
)
from honest_backtest.types import RefusedError

STALE_DAYS = fixtures.STALE_THRESHOLD_DAYS


def eligible(subject: dict[str, object]) -> bool:
    """The correct shared predicate: drop stale AND dormant subjects."""
    age = int(subject.get("age_days", 0))  # type: ignore[arg-type]
    dormant = bool(subject.get("dormant", False))
    return age >= STALE_DAYS and not dormant


def cohort_only(subject: dict[str, object]) -> bool:
    """The defect: staleness excluded on the cohort side only."""
    age = int(subject.get("age_days", 0))  # type: ignore[arg-type]
    return age >= STALE_DAYS


def mean_return(subjects: tuple[dict[str, object], ...]) -> float:
    """Mean forward return of a subject selection."""
    return sum(float(s["fwd_return"]) for s in subjects) / len(subjects)  # type: ignore[arg-type]


def show_arithmetic() -> None:
    """The statistical symptom, in numbers."""
    print("=" * 72)
    print("the arithmetic of the defect")
    print("=" * 72)

    active = tuple(
        {"id": i, "age_days": 90, "dormant": False, "fwd_return": 0.012}
        for i in range(20)
    )
    # Dormant subjects are also 90 days old, so they pass any age test. They
    # are excluded by the dormancy clause alone, which is what the buggy
    # benchmark filter forgot to check.
    dormant = tuple(
        {"id": 100 + i, "age_days": 90, "dormant": True, "fwd_return": 0.0}
        for i in range(20)
    )
    subjects = active + dormant

    cohort = tuple(s for s in subjects if eligible(s))
    buggy = tuple(s for s in subjects if cohort_only(s))
    fixed = tuple(s for s in subjects if eligible(s))

    print(f"  cohort (both clauses)        : {len(cohort):3d} subjects, "
          f"mean fwd return {mean_return(cohort):+.4f}")
    print(f"  benchmark (age clause only)  : {len(buggy):3d} subjects, "
          f"mean fwd return {mean_return(buggy):+.4f}")
    print(f"  benchmark (both clauses)     : {len(fixed):3d} subjects, "
          f"mean fwd return {mean_return(fixed):+.4f}")
    print()
    print(f"  apparent excess, buggy bench : {mean_return(cohort) - mean_return(buggy):+.4f}")
    print(f"  apparent excess, fixed bench : {mean_return(cohort) - mean_return(fixed):+.4f}")
    print()
    print("  The buggy benchmark is dragged toward zero by the 20 dormant")
    print("  subjects, manufacturing +0.6% of apparent skill that does not exist.")
    print()


def show_refusal() -> None:
    """The guard refusing two divergent predicates."""
    print("=" * 72)
    print("the guard: cohort and benchmark must share one predicate")
    print("=" * 72)

    guard = UniverseGuard(require_identical_object=True)
    report = guard.run(
        Selection(name="cohort", predicate=eligible, selected=("a", "b", "c")),
        Selection(name="benchmark", predicate=cohort_only, selected=("a", "b", "c", "d")),
    )

    print(f"  same predicate object  : {report.same_object}")
    print(f"  cohort size            : {report.cohort_size}")
    print(f"  benchmark size         : {report.benchmark_size}")
    print(f"  fingerprint            : {report.fingerprint}")
    print()

    for finding in report.findings:
        print(f"  [{finding.status.value}] {finding.code}")
        print(f"      {finding.message}")
        print()

    print(f"  verdict: {report.verdict.value}")
    try:
        report.certify().require()
    except RefusedError as exc:
        print("  -> REFUSED: the excess statistic compares two different universes")
        print(f"     {exc}")
    print()

    print("  The standalone helper, for code that cannot use the guard object:")
    try:
        require_shared_predicate(
            Selection(name="cohort", predicate=eligible, selected=("a",)),
            Selection(name="benchmark", predicate=cohort_only, selected=("a",)),
        )
    except ValueError as exc:
        print(f"     raised ValueError: {exc}")
    print()


def show_the_fix() -> None:
    """The fix: one predicate object, routed to both sides."""
    print("=" * 72)
    print("the fix: route both sides through one shared predicate")
    print("=" * 72)

    shared = eligible
    report = UniverseGuard().run(
        Selection(name="cohort", predicate=shared, selected=("a", "b", "c")),
        Selection(name="benchmark", predicate=shared, selected=("d", "e")),
    )
    print(f"  same predicate object  : {report.same_object}")
    print(f"  fingerprint            : {report.fingerprint}")
    print(f"  symmetric              : {report.symmetric}")
    print(f"  verdict                : {report.verdict.value}")
    print()
    print("  A predicate fingerprint is recorded in the report, so a later")
    print("  refactor that changes one side independently is visible.")
    print()


def main() -> int:
    """Show the defect, the refusal, and the fix."""
    show_arithmetic()
    show_refusal()
    show_the_fix()
    return 0


if __name__ == "__main__":
    sys.exit(main())
