"""Guard 7 -- block bootstrap, not naive CIs.

THE MEASURED FAILURE
--------------------
The author's own prior work documented the case precisely. A naive trade-level
confidence interval **promoted a false positive to a strategy**:

    CI = [-0.021, +0.781]        on 378 trades

The interval excludes zero by a hair. It came from **4 symbols in a one-month
artifact**. A trade-level bootstrap over that data treats 378 trades as 378
independent draws, when they are really a handful of weekly regimes sharing one
month of one market. The effective sample is far closer to 4 than to 378, and
the interval that pretends otherwise is not conservative -- it is wrong in the
direction of enthusiasm.

THE REFUSAL
-----------
A block bootstrap resamples whole weeks, reports the block count, and refuses to
support a claim built on too few blocks.
"""

from __future__ import annotations

import sys

from honest_backtest import fixtures
from honest_backtest.stats.bootstrap import (
    block_bootstrap_ci,
    monday_anchored_block,
    permutation_null,
)


def show_comparison() -> None:
    """Naive trade-level CI against the block bootstrap, on the same data."""
    print("=" * 72)
    print("378 trades, 4 symbols, one month: naive CI vs block bootstrap")
    print("=" * 72)

    payload = fixtures.trade_level_false_positive()

    naive = payload["naive_ci"]
    block = payload["block_ci"]
    print(f"  trades                 : {payload['n_trades']}")
    print(f"  symbols                : {payload['n_symbols']}")
    print(f"  weeks                  : {fixtures.TRADE_LEVEL_FALSE_POSITIVE['n_weeks']}")
    print()
    print(f"  naive trade-level CI   : [{naive[0]:+.4f}, {naive[1]:+.4f}]   (study: [-0.021, +0.781])")
    print(f"  block bootstrap CI     : [{block[0]:+.4f}, {block[1]:+.4f}]")
    print(f"  independent blocks     : {payload['n_blocks']}")
    print(f"  required minimum       : {payload['min_blocks']}")
    print()
    print(f"  {payload['naive_comparison']}")
    print()

    for finding in payload["findings"]:  # type: ignore[union-attr]
        print(f"  [{finding['status']}] {finding['code']}")
        print(f"      {finding['message']}")
        print()

    print(f"  verdict: {payload['block_verdict']}")
    print("  -> SUSPECT, not CERTIFIED: the interval is shown, next to the")
    print("     number that makes it meaningless. 4 blocks is not 378 trades.")
    print()


def show_blocks() -> None:
    """Calendar blocks: a holiday week is still one week."""
    print("=" * 72)
    print("blocks are calendar weeks, Monday-anchored")
    print("=" * 72)

    from datetime import date

    for day in (date(2024, 3, 4), date(2024, 3, 6), date(2024, 3, 10)):
        print(f"  {day.isoformat()} ({day.strftime('%a')}) -> block starts "
              f"{monday_anchored_block(day).isoformat()}")

    print()
    print("  A holiday week has fewer observations and is still one block.")
    print("  Fixed-size index runs would split it and overstate independence.")
    print()


def show_long_sample() -> None:
    """The negative direction: enough blocks, and the claim is supported."""
    print("=" * 72)
    print("40 weeks of data: enough blocks to support the claim")
    print("=" * 72)

    from datetime import date, timedelta
    import random

    rng = random.Random(11)
    start = date(2024, 1, 1)  # a Monday
    days = []
    values = []
    for w in range(40):
        weekly = rng.gauss(0.35, 1.0)
        for i in range(10):
            days.append(start + timedelta(days=w * 7 + i % 5))
            values.append(weekly + rng.gauss(0.0, 0.7))

    result = block_bootstrap_ci(
        values, block_dates=days, min_blocks=10, n_resamples=2000, seed=11
    )

    print(f"  observations           : {result.n_observations}")
    print(f"  independent blocks     : {result.n_blocks}")
    print(f"  95% CI                 : [{result.low:+.4f}, {result.high:+.4f}]")
    print(f"  excludes zero          : {result.excludes_zero}")
    print(f"  usable                 : {result.usable}")
    print(f"  verdict                : {result.verdict.value}")
    print()
    print("  Same method, enough data, and the interval is reportable.")
    print()


def show_permutation() -> None:
    """A permutation null for shape tests: shuffle within blocks, keep totals."""
    print("=" * 72)
    print("permutation null: shuffle within blocks, preserving block totals")
    print("=" * 72)

    values = [float(x) for x in range(28)]

    def spread(v: list[float]) -> float:
        return max(v) - min(v)

    result = permutation_null(
        values, statistic=spread, block_size=7, n_permutations=2000, seed=3
    )

    print(f"  observed spread        : {result.observed:.1f}")
    print(f"  blocks                 : {result.n_blocks} of {result.block_size} observations")
    print(f"  null 5th/50th/95th     : "
          f"{result.null_quantiles[0]:.1f} / {result.null_quantiles[1]:.1f} / "
          f"{result.null_quantiles[2]:.1f}")
    print(f"  p-value                : {result.p_value:.4f}")
    print()
    print("  Shuffling values freely would destroy the block structure and")
    print("  produce a null that is too wide -- a test too easy to pass. Shuffling")
    print("  within blocks keeps every weekly total intact and randomises only")
    print("  the arrangement, which is the question actually being asked.")
    print()


def main() -> int:
    """Compare methods, explain blocks, and show both outcomes."""
    show_comparison()
    show_blocks()
    show_long_sample()
    show_permutation()
    return 0


if __name__ == "__main__":
    sys.exit(main())
