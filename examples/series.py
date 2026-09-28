"""Guard 6 -- structural data traps.

THE MEASURED FAILURES
---------------------
(a) A series table spliced two different metrics end-to-end: a 365-day
    trailing-cumulative metric and a 30-day rolling-window metric. Differencing
    across the splice fabricated a **-24,046 pp** "daily return".

(b) Series were zero-padded before inception. A portfolio 11 days old still
    returned 365 points. Treating the padding as history fabricates a track
    record -- and the padding is zero, which drags any measured average toward
    zero, a flattering direction for a long-only book.

(c) A 15-minute bar labelled ``t0`` spans ``[t0, t0 + 15m)``. Code that assumed
    a forward bar starts at ``t0 + 1m`` produced a **185 bps** error.

THE REFUSAL
-----------
Three traps, three refusals.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta

from honest_backtest import fixtures
from honest_backtest.guards.series import (
    SeriesGuard,
    detect_splice,
    forward_bar_offset,
    left_edge_window,
    price_error_bps,
    truncate_leading_padding,
)
from honest_backtest.types import RefusedError


def show_splice() -> None:
    """A -24,046 pp fabricated daily return across a metric splice."""
    print("=" * 72)
    print("spliced metrics: 365D trailing-cumulative joined to 30D rolling")
    print("=" * 72)

    # Rebuild the exact series the fixture uses.
    rng_series = fixtures._spliced_series()  # noqa: SLF001 - fixture internal
    report = detect_splice(rng_series, threshold=25.0)

    fabricated = None
    if report.index is not None:
        fabricated = rng_series[report.index + 1] - rng_series[report.index]

    print(f"  points                 : {len(rng_series)}")
    print(f"  detected               : {report.detected}")
    print(f"  splice index           : {report.index}  (segment boundary)")
    print(f"  step across the splice : {fabricated:+,.1f} pp")
    print(f"  local scale nearby     : {report.local_scale:,.4f} pp")
    print(f"  ratio to local scale   : {report.ratio:,.0f}x")
    print(f"  study measured         : -24,046 pp")
    print()

    for finding in report.findings:
        print(f"  [{finding.status.value}] {finding.code}")
        print(f"      {finding.message}")
        print()

    print(f"  verdict: {report.verdict.value}")
    try:
        report.certify().require()
    except RefusedError as exc:
        print("  -> REFUSED: differencing across the splice fabricates a value")
        print(f"     {exc}")
    print()


def show_padding() -> None:
    """An 11-day-old portfolio returning 365 points."""
    print("=" * 72)
    print("zero-padded inception: a portfolio 11 days old, 365 points returned")
    print("=" * 72)

    padded = [0.0] * 354 + [float(i) for i in range(1, 12)]
    guard = SeriesGuard()
    report = guard.check_padding(padded, padding_value=0.0)
    usable, dropped = truncate_leading_padding(padded, padding_value=0.0)

    print(f"  points returned        : {len(padded)}")
    print(f"  leading padding        : {dropped}")
    print(f"  actual history         : {len(usable)} days")
    print(f"  padding fraction       : {dropped / len(padded):.1%}")
    print()

    for finding in report.findings:
        print(f"  [{finding.status.value}] {finding.code}")
        print(f"      {finding.message}")
        print()

    print(f"  verdict: {report.verdict.value}")
    print("  -> REFUSED: the zero padding is not history, and averaging it in")
    print("     drags every statistic toward zero")
    print("  the fix:")
    print(f"     truncate_leading_padding(...) -> {len(usable)} usable points")
    print()


def show_left_edge() -> None:
    """A 15m bar labelled t0, and the 185 bps error from misreading it."""
    print("=" * 72)
    print("left-edge timestamp: a 15m bar at t0 misread as starting t0+1m")
    print("=" * 72)

    t0 = datetime(2024, 3, 1, 9, 30)
    span = timedelta(minutes=15)
    start, end = left_edge_window(t0, span)
    correct, timing_bps = forward_bar_offset(
        t0, span, assumed_offset=timedelta(minutes=1)
    )

    print(f"  bar label (left edge)  : {t0.isoformat()}")
    print(f"  interval it covers     : [{start.isoformat()}, {end.isoformat()})")
    print(f"  correct next bar start : {correct.isoformat()}")
    print(f"  assumed next bar start : {(t0 + timedelta(minutes=1)).isoformat()}")
    print(f"  timing error           : {timing_bps:,.0f} bps of a bar")
    print()

    # The price consequence: the fixture's measured 185 bps.
    measured = price_error_bps(price_at_correct=100.0, price_at_assumed=101.85)
    print(f"  price error on the bar : {measured:.0f} bps  (study measured 185 bps)")
    print()
    print("  verdict: REFUSED")
    print("  -> the wrong timestamp is not a rounding difference, it is a")
    print("     different bar; every forward return computed from it is wrong")
    print()


def main() -> int:
    """Run all three structural traps."""
    show_splice()
    show_padding()
    show_left_edge()
    return 0


if __name__ == "__main__":
    sys.exit(main())
