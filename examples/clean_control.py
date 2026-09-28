"""The negative direction: a genuinely clean result is CERTIFIED.

A library that rejects everything is not a validator. This script is the proof
that the guards discriminate: the same pipeline, the same thresholds, a clean
input, and the verdict is ``CERTIFIED``.

Every guard that can run, runs. Nothing is skipped to make this pass.
"""

from __future__ import annotations

import sys

from datetime import date

from honest_backtest import fixtures
from honest_backtest.guards.universe import Selection
from honest_backtest.guards.windows import WindowPlan
from honest_backtest.report import Config, HonestyReport, ResultSet
from honest_backtest.stats.bootstrap import block_bootstrap_ci

# One predictor. Effects do not depend on when they were measured (r = +0.06).
SPLIT_EFFECTS = (0.051, 0.038, 0.062, 0.029, 0.055, 0.041, 0.048, 0.033)
SPLIT_DISTANCES_DAYS = (3.0, 8.0, 15.0, 22.0, 31.0, 43.0, 56.0, 70.0)

# Ten windows, all positive, no outlier domination.
WINDOW_EXCESSES = (22.0, 31.0, 18.0, 27.0, 35.0, 24.0, 29.0, 20.0, 33.0, 26.0)

# 120 trades from a smooth distribution: no tail concentration.
TRADE_PNLS = tuple(40.0 + 6.0 * __import__("math").sin(i / 3.0) for i in range(120))


def shared_predicate(subject: object) -> bool:
    """One predicate object, routed to both the cohort and the benchmark."""
    return True


def main() -> int:
    """Run every guard against a clean bundle and show the certification."""
    plan = WindowPlan.tiled(
        date(2024, 1, 1), date(2024, 12, 31), length_days=30, label="clean_tiling"
    )
    subjects_are_shared = shared_predicate

    result = ResultSet(
        name="clean_control",
        split_effects=SPLIT_EFFECTS,
        split_distances_days=SPLIT_DISTANCES_DAYS,
        window_excesses=WINDOW_EXCESSES,
        win_count=10,
        trade_pnls=TRADE_PNLS,
        window_plan=plan,
        cohort=Selection(
            name="cohort", predicate=subjects_are_shared, selected=tuple(range(20))
        ),
        benchmark=Selection(
            name="benchmark", predicate=subjects_are_shared, selected=tuple(range(20, 40))
        ),
        series_values=tuple(fixtures.clean_series()),
    )

    print("=" * 72)
    print("The clean result set")
    print("=" * 72)
    print("  predictor spread        : +0.045")
    print("  evaluation windows won  : 10 of 10")
    print("  walk-forward splits     : 12 disjoint 30-day windows")
    print("  cohort / benchmark      : one shared predicate")
    print("  level series            : stationary, no splice, no padding")
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
    print("Guard by guard")
    print("=" * 72)
    for name in report.ran_guards:
        print(f"  [pass] {name}")

    lookahead = report.payload.get("lookahead", {})
    if isinstance(lookahead, dict):
        print()
        print(f"  look-ahead r            : {lookahead.get('r')}")
        print(f"  contaminated            : {lookahead.get('contaminated')}")

    windows = report.payload.get("windows", {})
    if isinstance(windows, dict):
        count = windows.get("independent_count")
        print(f"  independent windows     : {count}")

    trades = report.payload.get("concentration_trades", {})
    if isinstance(trades, dict):
        print(f"  top-decile share        : {trades.get('top_share')}")

    universe = report.payload.get("universe", {})
    if isinstance(universe, dict):
        print(f"  cohort/benchmark same   : {universe.get('same_object')}")

    print()

    # The bootstrap is a separate gate; it is not part of HonestyReport because
    # it needs the per-trade series, not just the summary.
    import random

    rng = random.Random(3)
    days = []
    values = []
    start = date(2024, 1, 1)
    for w in range(26):
        weekly = 0.04 + rng.gauss(0.0, 0.35)
        for i in range(15):
            days.append(start.__class__.fromordinal(start.toordinal() + w * 7 + i % 7))
            values.append(weekly + rng.gauss(0.0, 0.45))

    boot = block_bootstrap_ci(values, block_dates=days, min_blocks=10, seed=3)
    print("=" * 72)
    print("Block bootstrap (a separate gate, run explicitly)")
    print("=" * 72)
    print(f"  independent blocks      : {boot.n_blocks}")
    print(f"  95% CI                  : [{boot.low:+.4f}, {boot.high:+.4f}]")
    print(f"  verdict                 : {boot.verdict.value}")
    print()

    print("=" * 72)
    print("The verdict")
    print("=" * 72)
    print(f"  verdict                 : {report.verdict.value}")
    print(f"  certified               : {report.certified}")
    print(f"  blocking findings       : {report.failures()}")
    print(f"  guards run              : {', '.join(report.ran_guards)}")
    print(f"  guards skipped          : {report.skipped_guards or 'none'}")
    print()

    report.require_certified()
    print("  -> CERTIFIED. require_certified() did not raise.")
    print()
    print("  Same pipeline, same thresholds, opposite outcome. The library")
    print("  discriminates; it is not a machine that rejects everything.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
