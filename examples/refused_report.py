"""The full pipeline: a convincing result set, and its refusal.

This is the worked example the README points at. It builds a result set that
*looks* like a finding -- a positive spread, a high win rate, a tight interval
-- and runs it through the aggregator.

THE REFUSAL IS THE FEATURE
--------------------------
Everything here passes a significance test. What kills it is the guards.
"""

from __future__ import annotations

import sys

from honest_backtest.guards.comparison import Population, Predicate
from honest_backtest.guards.evidence import Observation
from honest_backtest.guards.windows import WindowPlan
from honest_backtest.plans import Window
from honest_backtest.report import Config, HonestyReport, ResultSet
from honest_backtest.types import RefusedError
from datetime import date

# ---------------------------------------------------------------------------
# The result set, in the shape a researcher would actually have it.
# ---------------------------------------------------------------------------

# Twelve splits, taken from the research archive (query key: copier_pnl; see
# honest_backtest/fixtures.COPIER_PNL, provenance MEASURED). Effect is largest
# nearest the data snapshot and decays with distance -- the signature of a label
# that leaks the future. The apparent spread is +0.1344 and significant at
# p < 0.001.
SPLIT_EFFECTS = (
    0.0881, 0.1023, 0.0802, 0.0134, 0.2468, 0.0111,
    0.0979, 0.1057, 0.1972, 0.1191, 0.2072, 0.3435,
)
SPLIT_DISTANCES_DAYS = (
    362.0, 332.0, 302.0, 272.0, 242.0, 212.0,
    182.0, 152.0, 122.0, 92.0, 62.0, 32.0,
)

# Twelve evaluation windows, of which nine "won". Mean -138.7, median +37.0.
WINDOW_EXCESSES = (
    41.0, 41.0, 52.0, 29.0, 44.0, 33.0, 61.0, 25.0, 48.0,
    -1534.0, -380.0, -124.0,
)
WIN_COUNT = 9

# The walk-forward as designed: four splits, all sharing one end date.
WALK_FORWARD = WindowPlan(
    windows=tuple(
        Window(start=s, end=date(2024, 7, 1), label=f"split{i + 1}")
        for i, s in enumerate(
            (date(2024, 1, 1), date(2024, 2, 1), date(2024, 3, 1), date(2024, 4, 1))
        )
    ),
    label="walk_forward",
    claimed=4,
)


def main() -> int:
    """Build a convincing result set, run the guards, show the refusal."""
    result = ResultSet(
        name="the_convincing_result",
        split_effects=SPLIT_EFFECTS,
        split_distances_days=SPLIT_DISTANCES_DAYS,
        window_excesses=WINDOW_EXCESSES,
        win_count=WIN_COUNT,
        window_plan=WALK_FORWARD,
        # The evidence behind the "no prior art" claim: a code search that
        # returned nothing, including for a term that is everywhere.
        observations=(
            Observation(subject="def sharpe_ratio [lang:python]", code="0"),
            Observation(subject="numba", code="1"),
        ),
        claimed_absent=("def sharpe_ratio [lang:python]",),
        negative_claim="nobody has implemented this, so there is no prior art",
        # The comparison behind the "beats the benchmark" claim: two declared
        # predicates that are not the same rule.
        cohort_population=Population(
            name="cohort",
            predicate=Predicate(
                name="eligible_as_of",
                clauses=("history_days >= 30", "not stale", "not frozen as of split_ts"),
                ordered=True,
            ),
            size=3151,
            forward_returns=(5.0, -2.0, 0.0, 8.5),
        ),
        benchmark_population=Population(
            name="benchmark",
            predicate=Predicate(
                name="benchmark_filter",
                clauses=("history_days >= 30",),
                ordered=True,
            ),
            size=3151,
            forward_returns=(0.0, 0.0, 0.0, 0.0, 0.0, 5.0, -2.0, 0.0),
        ),
    )

    print("=" * 72)
    print("The result set")
    print("=" * 72)
    print("  predictor spread        : +0.1344  (significant at p < 0.001)")
    print("  evaluation windows won  : 9 of 12")
    print("  walk-forward splits     : 4")
    print("  prior art               : 'none found' (the search tool returned 0)")
    print("  benchmark               : 'same universe as the cohort'")
    print("  declared verdict        : THIS IS AN EDGE")
    print()

    report = HonestyReport.run(
        result,
        config=Config(assert_no_unguarded_construction=True),
    )

    print("=" * 72)
    print("The audit")
    print("=" * 72)
    print(report.explanation())
    print()

    print("=" * 72)
    print("Why each guard fired")
    print("=" * 72)
    for i, finding in enumerate(report.failures(), start=1):
        print(f"  {i}. {finding.code}")
        print(f"     {finding.message}")
        print()

    print("=" * 72)
    print("The refusal")
    print("=" * 72)
    print(f"  verdict: {report.verdict.value}")
    print(f"  blocked by: {', '.join(report.failure_codes())}")
    print()
    try:
        report.require_certified()
        print("  -> certified: publish it")
    except RefusedError as exc:
        print("  -> REFUSED. This result cannot be reported as a finding.")
        print()
        print(f"     {exc}")
    print()

    print("=" * 72)
    print("What the numbers actually said")
    print("=" * 72)
    print("  The spread of +0.1344 was real arithmetic on contaminated labels.")
    print("  The 9-of-12 win rate was real and irrelevant: the three losses")
    print("  invert the mean. The 4 splits were 1 observation measured 4 times.")
    print()
    print("  Every one of those numbers was true. None of them was evidence.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
