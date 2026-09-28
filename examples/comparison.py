"""Shared selection predicates: a comparison needs two populations, not two rules.

Guard 8, in both directions:

* the walk-forward run that compared a cohort selected for staleness against a
  benchmark that was not, and reported **"POSITIVE 4/4 splits"** -- retracted
  afterwards; and
* the corrected design, where both sides call one shared predicate.

What this example is careful *not* to claim: the guard does not read the
numbers and deduce the rule. It cannot. Two populations of numbers do not carry
the filter that made them, and any inference would be a guess dressed as a
check. So it requires the caller to declare its predicates and refuses when the
declarations differ -- which is checkable, reviewable, and pinnable in a test.
"""

from __future__ import annotations

import sys

from honest_backtest import fixtures
from honest_backtest.guards.comparison import ComparisonGuard, Population, Predicate
from honest_backtest.report import Config, HonestyReport, ResultSet


def main() -> int:
    spec = fixtures.NESTED_FOUR_SPLIT_ASYMMETRY
    rows = spec["splits"]
    assert isinstance(rows, list)

    print("=" * 72)
    print("The nested four-split design, as the study's retraction table gives it")
    print("=" * 72)
    print(f"  {'split':12} {'fwd_days':>9} {'eligible':>9} {'mean_fwd':>10} {'bench':>7} {'excess':>9}")
    for split, fwd_days, eligible, mean_fwd, _median, _hit, bench, excess in rows:
        print(f"  {split:12} {fwd_days:>9} {eligible:>9} {mean_fwd:>10.1f} {bench:>7.1f} {excess:>9.1f}")
    print()
    print(f"  all four end on {spec['shared_end']} -> "
          f"{spec['independent_windows']} independent windows")
    print(f"  the earlier draft read these as: {spec['claimed']!r}")
    print("  the benchmark mean is positive in every one of the four.")
    print()

    cohort_predicate = Predicate(
        name=str(spec["cohort_predicate"]),
        clauses=tuple(spec["cohort_clauses"]),  # type: ignore[arg-type]
        ordered=True,
        source="copytrade/backtest.py::_eligible_as_of",
    )
    benchmark_predicate = Predicate(
        name=str(spec["benchmark_predicate"]),
        clauses=tuple(spec["benchmark_clauses"]),  # type: ignore[arg-type]
        ordered=True,
        source="the defect: staleness excluded on the cohort side only",
    )

    print("=" * 72)
    print("The declarations, side by side")
    print("=" * 72)
    print(f"  cohort    : {cohort_predicate.name}")
    for clause in cohort_predicate.clauses:
        print(f"      - {clause}")
    print(f"  benchmark : {benchmark_predicate.name}")
    for clause in benchmark_predicate.clauses:
        print(f"      - {clause}")
    print()
    print("  Three clauses the cohort applied and the benchmark did not. The")
    print("  cohort dropped dormant subjects; the benchmark kept them, and a")
    print("  dormant subject's forward return is a flat 0.0 that drags a mean.")
    print()

    broken = ComparisonGuard().run(
        Population(
            name="cohort",
            predicate=cohort_predicate,
            size=int(rows[-1][2]),
            forward_returns=tuple(
                float(x)  # type: ignore[arg-type]
                for x in fixtures.DORMANT_ZERO_FORWARD_RETURNS["cohort_forward_returns"]
            ),
        ),
        Population(
            name="benchmark",
            predicate=benchmark_predicate,
            size=int(rows[-1][2]),
            forward_returns=tuple(
                float(x)  # type: ignore[arg-type]
                for x in fixtures.DORMANT_ZERO_FORWARD_RETURNS["benchmark_forward_returns"]
            ),
        ),
    )

    print("=" * 72)
    print("Guard 8 on the asymmetric comparison")
    print("=" * 72)
    for finding in broken.findings:
        print(f"  [{finding.status.value}] {finding.code}")
        print(f"    {finding.message}")
        print()
    print(f"  verdict: {broken.verdict.value}")
    print()

    asymmetry_report = HonestyReport.run(
        ResultSet(
            name="nested_four_split_asymmetry",
            cohort_population=Population("cohort", cohort_predicate, int(rows[-1][2])),
            benchmark_population=Population("benchmark", benchmark_predicate, int(rows[-1][2])),
        ),
        config=Config(assert_no_unguarded_construction=True),
    )
    print("  Through the aggregator:")
    print(f"    verdict          : {asymmetry_report.verdict.value}")
    print(f"    failure codes    : {', '.join(asymmetry_report.failure_codes())}")
    print()

    shared = Predicate(
        name="eligible_as_of",
        clauses=tuple(spec["cohort_clauses"]),  # type: ignore[arg-type]
        ordered=True,
        source="copytrade/backtest.py::_eligible_as_of",
    )
    fixed = HonestyReport.run(
        ResultSet(
            name="the corrected design",
            cohort_population=Population("cohort", shared, 431,
                                         (5.0, -2.0, 1.5)),
            benchmark_population=Population("benchmark", shared, 1256,
                                            (2.0, -1.0, 0.5)),
            comparison_predicate=shared,
        ),
        config=Config(assert_no_unguarded_construction=True),
    )
    print("=" * 72)
    print("The fix: both sides call one shared predicate")
    print("=" * 72)
    print(fixed.explanation())
    print()
    print(f"  verdict: {fixed.verdict.value}")
    print()

    print("=" * 72)
    print("What this guard can and cannot do")
    print("=" * 72)
    print("  CAN    : refuse when two declarations differ -- different clauses,")
    print("           different order where order is declared observable, or one")
    print("           side filtered and the other not.")
    print("  CANNOT : recover the rule from the numbers. Two populations of the")
    print("           same size with the same mean can be built by any two")
    print("           filters. A guard that guessed here would be unfalsifiable.")
    print()
    print("  The numeric symptom (one side carrying more exact-zero returns) is")
    print("  reported at INFO severity only. On this fixture the gap is")
    print(f"  {broken.zero_fraction_gap}, and it still cannot move the verdict.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
