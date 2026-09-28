"""Guard 2 -- outlier domination.

THE MEASURED FAILURES
---------------------
(a) A strategy won **9 of 12** independent windows and was not an edge:

        mean excess   = -138.7
        median excess =  +37.0      # opposite signs

    Nine wins out of twelve sounds like a result. The three losses were large
    enough to invert the mean. The win-count and the dollar total tell opposite
    stories, and the dollar total is the one that reaches your P&L.

(b) A strategy's in-sample **top 10% of trades produced 121% of net PnL** --
    remove the best decile and it is a loser. A second study's 15m result had a
    top-10% share of **1.64**.

THE REFUSAL
-----------
Neither guard is satisfied by a high win rate, which is the point: the win rate
is exactly the statistic that lied in (a).
"""

from __future__ import annotations

import sys

from honest_backtest import fixtures
from honest_backtest.guards.outliers import ConcentrationGuard
from honest_backtest.types import RefusedError


def demo_windows() -> None:
    """9 wins out of 12, and not an edge."""
    spec = fixtures.NINE_OF_TWELVE
    excesses = [float(x) for x in spec["excesses"]]  # type: ignore[union-attr]

    print("=" * 72)
    print("nine_of_twelve: 9 of 12 windows won")
    print("=" * 72)

    guard = ConcentrationGuard(min_obs=8)
    report = guard.check_windows(excesses, win_count=9)

    print(f"  windows                : {report.n}")
    print(f"  win count              : {report.win_count} / {report.n}")
    print(f"  mean excess            : {report.mean_excess:+.1f}   (study measured -138.7)")
    print(f"  median excess          : {report.median_excess:+.1f}    (study measured +37.0)")
    print(f"  signs disagree         : {report.signs_disagree}")
    print()

    for finding in report.findings:
        print(f"  [{finding.status.value}] {finding.code}")
        print(f"      {finding.message}")
        print()

    print("  Nine of twelve wins is real. It is not an edge. The three losses")
    print("  are large enough to invert the mean, so the summary statistic you")
    print("  choose decides the conclusion -- which means there is no conclusion.")
    print()
    print(f"  verdict: {report.verdict.value}")
    try:
        report.certify().require()
        print("  -> usable as a finding")
    except RefusedError as exc:
        print(f"  -> REFUSED: cannot be reported as a finding")
        print(f"     {exc}")
    print()


def demo_tail(name: str, spec: dict[str, object], story: str) -> None:
    """Top-decile concentration in a trade PnL series."""
    pnls = [float(x) for x in spec["pnls"]]  # type: ignore[union-attr]

    print("=" * 72)
    print(f"{name}: {story}")
    print("=" * 72)

    guard = ConcentrationGuard(top_fraction=0.10, tail_threshold=1.0)
    report = guard.check_trades(pnls)

    assert report.top_share is not None
    assert report.share_excluding_tail is not None
    top_sum = sum(sorted(pnls)[-max(1, int(len(pnls) * 0.10)):])
    print(f"  trades                 : {report.n}")
    print(f"  provenance             : {spec['provenance']} -- {spec['source']}")
    print(f"  top decile share       : {report.top_share:.4f}   (study measured {spec['expected_share']})")
    print(f"      = top-decile sum {top_sum:+.2f} / NET PnL {sum(pnls):+.2f}")
    print("      net, not gross: net PnL nets the losers off, so the denominator")
    print("      is smaller than the winnings and the share can exceed 1.0.")
    print(f"  net PnL                : {sum(pnls):+.2f}")
    print(f"  net PnL without top 10%: {report.share_excluding_tail:+.2f}")
    print(f"  loses without top 10%  : {report.share_excluding_tail < 0.0}")
    print()

    for finding in report.findings:
        print(f"  [{finding.status.value}] {finding.code}")
        print(f"      {finding.message}")
        print()

    print(f"  verdict: {report.verdict.value}")
    print("  A share at or above 1.0 has exactly one reading: strip the tail and")
    print("  the strategy loses money. What you are calling an edge is a handful")
    print("  of draws.")
    print()


def main() -> int:
    """Run all three outlier fixtures."""
    demo_windows()
    demo_tail(
        "top_decile_121",
        fixtures.TOP_DECILE_121,
        "top 10% of trades = 121% of net PnL  [DERIVED from the real 1.2131]",
    )
    demo_tail(
        "top_decile_164",
        fixtures.TOP_DECILE_164,
        "a 15m result: top-10% share 1.64  [ILLUSTRATIVE: rows not persisted]",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
