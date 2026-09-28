"""Provenance of negative evidence: an error is not an absence.

Guard 7, in both directions:

* the broken scan, which wrote ``{"exists": false, "code": 503}`` and thereby
  reported five packages as missing, one of which was on PyPI all along; and
* the corrected scan of the same names, which classified non-404 responses as
  ``UNKNOWN`` and refused to conclude from them.

Both are real artifacts from the same day. The guard refuses the first and
certifies the second, and the difference between them is entirely in how the
two runs wrote down a failure.
"""

from __future__ import annotations

import sys

from honest_backtest import fixtures
from honest_backtest.guards.evidence import Observation
from honest_backtest.report import Config, HonestyReport, ResultSet


def show_the_broken_scan() -> HonestyReport:
    """Run the aggregator on the scan whose 503s became absences."""
    rows = fixtures.PYPI_SCAN_503["observations"]
    assert isinstance(rows, list)
    claimed = tuple(str(s) for s, exists, _ in rows if exists is False)

    report = HonestyReport.run(
        ResultSet(
            name="pypi_scan_503 (the broken scan)",
            observations=tuple(
                Observation(subject=str(s), code=str(c)) for s, _e, c in rows
            ),
            control_observations=(Observation(subject="deflated-sharpe", code="200"),),
            claimed_absent=claimed,
            negative_claim="non-200 means the package is absent",
        ),
        config=Config(assert_no_unguarded_construction=True),
    )
    return report


def show_the_corrected_scan() -> HonestyReport:
    """Run the aggregator on the three-state scan that replaced it."""
    rows = fixtures.PYPI_THREE_STATE_CORRECTED["observations"]
    assert isinstance(rows, list)
    return HonestyReport.run(
        ResultSet(
            name="pypi_three_state_corrected (the corrected scan)",
            observations=tuple(
                Observation(subject=str(s), code=str(state).upper())
                for s, state, _c in rows
            ),
            control_observations=(Observation(subject="deflated-sharpe", code="200"),),
        ),
        config=Config(assert_no_unguarded_construction=True),
    )


def main() -> int:
    print("=" * 72)
    print("The original scan: HTTP 503 recorded as absence")
    print("=" * 72)
    print("  The scan's own rows, verbatim from /tmp/pypi_scan.json:")
    rows = fixtures.PYPI_SCAN_503["observations"]
    assert isinstance(rows, list)
    for subject, exists, code in rows:
        if code == "503":
            print(f"    {subject:28} exists={str(exists):5} code={code}   <- not a 404")
    print()
    print("  The claim it supported:")
    print("    'the names that returned a non-200 are absent from PyPI'")
    print()

    broken = show_the_broken_scan()
    print("=" * 72)
    print("Guard 7 on the broken scan")
    print("=" * 72)
    print(broken.explanation())
    print()

    payload = broken.payload.get("evidence", {})
    if isinstance(payload, dict):
        print(f"  PRESENT  : {payload.get('n_present')}")
        print(f"  ABSENT   : {payload.get('n_absent')}")
        print(f"  UNKNOWN  : {payload.get('n_unknown')}   <- 5 of these were called absent")
        print(f"  conclusive: {payload.get('conclusive_fraction')}")
        print()

    print("=" * 72)
    print("The same question, asked again the same day")
    print("=" * 72)
    corrected = show_the_corrected_scan()
    print(corrected.explanation())
    print()

    payload = corrected.payload.get("evidence", {})
    if isinstance(payload, dict):
        print(f"  PRESENT  : {payload.get('n_present')}")
        print(f"  ABSENT   : {payload.get('n_absent')}")
        print(f"  UNKNOWN  : {payload.get('n_unknown')}   <- still two honest unknowns")
        print(f"  conclusive: {payload.get('conclusive_fraction')}")
        print()

    correction = fixtures.PYPI_THREE_STATE_CORRECTED["measured_correction"]
    assert isinstance(correction, dict)
    print("=" * 72)
    print("What the correction recovered")
    print("=" * 72)
    print(f"  called absent on a 503 : {', '.join(correction['declared_absent_by_broken_scan'])}")  # type: ignore[arg-type]
    print(f"  actually present       : {', '.join(correction['actually_present'])}")  # type: ignore[arg-type]
    print(f"  still absent           : {', '.join(correction['still_absent_after_correction'])}")  # type: ignore[arg-type]
    print()
    print("  One package reported missing was there the whole time. The earlier")
    print("  count was not wrong about the world; it was wrong about itself.")
    print()

    print("=" * 72)
    print("The verdicts")
    print("=" * 72)
    print(f"  broken scan    : {broken.verdict.value}  ({len(broken.failures())} blocking)")
    print(f"  corrected scan : {corrected.verdict.value}")
    print()
    print("  Same instrument, same names, same day. The only difference is that")
    print("  the second run wrote down what it could not find out.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
