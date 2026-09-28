"""Guard 1 -- look-ahead contamination, caught by distance decay.

THE MEASURED FAILURE
--------------------
Two predictors produced spreads significant at p < 0.001:

    copier_pnl   apparent spread +0.1344   distance-decay r = -0.598
    roi          apparent spread +1.0190   distance-decay r = +0.43

Both were pure look-ahead. Neither was caught by significance testing; both
were caught by asking whether the measured effect depends on *when* it was
measured.

PROVENANCE
----------
Both fixtures are MEASURED: the twelve per-split spreads and the split dates
below are the research archive's own rows (``research/edge-hunt/q4_results.json``)
and nothing has been tuned. The correlation you are about to watch the guard
compute is recomputed from that data -- which is why it lands on -0.5976 and
+0.4285 rather than on the rounded published figures, and why that difference
is the point.

THE REFUSAL
-----------
This script measures the correlation, prints it next to the published figure,
and shows the refusal that follows.
"""

from __future__ import annotations

import sys

from honest_backtest import fixtures
from honest_backtest.guards.lookahead import LookaheadGuard
from honest_backtest.types import RefusedError


def demo(
    name: str,
    effects: list[float],
    distances: list[float],
    apparent_spread: float,
    expected_r: float,
    provenance: str = "UNKNOWN",
) -> None:
    """Run the diagnostic, print the measurement, and attempt to use it."""
    print("=" * 72)
    print(f"{name}: apparent spread {apparent_spread:+.4f} (significant at p < 0.001)")
    print(f"  provenance: {provenance}")
    print("=" * 72)

    guard = LookaheadGuard(r_threshold=0.5, min_splits=5)
    report = guard.run(effects, distances)

    print(f"  splits                 : {report.n_splits}")
    print(f"  distance-decay r       : {report.r:+.4f}   (study measured {expected_r:+.3f})")
    if abs(report.r - expected_r) < 5e-4:
        print("                           -> reproduced from the real per-split rows")
    print(f"  spearman rho           : {report.spearman:+.4f}")
    print(f"  near-half mean effect  : {report.near_mean:+.4f}")
    print(f"  far-half mean effect   : {report.far_mean:+.4f}")
    print(f"  threshold on |r|       : {report.threshold}")
    print(f"  contaminated           : {report.contaminated}")
    print()

    for finding in report.findings:
        print(f"  [{finding.status.value}] {finding.code}")
        print(f"      {finding.message}")
        print()

    print("  A genuine predictor does not care when you measure it.")
    print("  This one does: largest nearest the snapshot, decaying with distance.")
    print()

    cert = report.certify()
    print(f"  verdict: {cert.verdict.value}")
    try:
        cert.require()
        print("  -> usable as a finding")
    except RefusedError as exc:
        print(f"  -> REFUSED, cannot be reported: {exc}")
    print()


def main() -> int:
    """Run both contaminated fixtures, then a clean control."""
    demo(
        "copier_pnl",
        [float(x) for x in fixtures.COPIER_PNL["effects"]],  # type: ignore[union-attr]
        [float(x) for x in fixtures.COPIER_PNL["distances_days"]],  # type: ignore[union-attr]
        float(fixtures.COPIER_PNL["apparent_spread"]),  # type: ignore[arg-type]
        float(fixtures.COPIER_PNL["expected_r"]),  # type: ignore[arg-type]
        str(fixtures.COPIER_PNL["provenance"]),
    )
    demo(
        "roi",
        [float(x) for x in fixtures.ROI["effects"]],  # type: ignore[union-attr]
        [float(x) for x in fixtures.ROI["distances_days"]],  # type: ignore[union-attr]
        float(fixtures.ROI["apparent_spread"]),  # type: ignore[arg-type]
        float(fixtures.ROI["expected_r"]),  # type: ignore[arg-type]
        str(fixtures.ROI["provenance"]),
    )

    # The control: a predictor whose effect does not depend on measurement date.
    print("=" * 72)
    print("clean_control: a predictor that does not care when you measure it")
    print("=" * 72)
    clean = LookaheadGuard(r_threshold=0.5, min_splits=5).run(
        [float(x) for x in fixtures.CLEAN_CONTROL["effects"]],  # type: ignore[union-attr]
        [float(x) for x in fixtures.CLEAN_CONTROL["distances_days"]],  # type: ignore[union-attr]
    )
    print(f"  distance-decay r       : {clean.r:+.4f}")
    print(f"  contaminated           : {clean.contaminated}")
    print(f"  verdict                : {clean.verdict.value}")
    print()
    print("  Same guard, opposite outcome. The library is not a rejection machine.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
