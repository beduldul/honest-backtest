"""Guard 5 -- multiple-testing accounting.

THE MEASURED FAILURE
--------------------
One study evaluated **341 configurations**. At alpha = 0.05 that implies

    341 * 0.05 = 17.05

expected false positives, and the study's nominal positives -- p-values sitting
in the 0.01-0.05 band -- sat right at that rate. They were not findings; they
were the arithmetic of looking 341 times.

A second study ran **60 configurations** and reported one positive, inside a
family where ~3 are expected.

Neither study lied. Both reported a p-value that was true for the single test
and meaningless for the family. The fix is not a better p-value; it is counting
how many times you looked.

THE REFUSAL
-----------
This script counts the family, reports the expected false positives, and applies
Bonferroni to the claimed p-value.
"""

from __future__ import annotations

import sys

from honest_backtest.guards.multiplicity import ExperimentCounter
from honest_backtest.types import RefusedError


def show(n_experiments: int, claimed_p: float, n_positives: int, story: str) -> None:
    """Count a family, correct a claim, and show the refusal."""
    print("=" * 72)
    print(f"{n_experiments} configurations: {story}")
    print("=" * 72)

    counter = ExperimentCounter(alpha=0.05, correction="bonferroni")
    for i in range(n_experiments):
        counter.record(f"config-{i}")

    report = counter.report(
        claimed_p=claimed_p,
        n_nominal_positives=n_positives,
    )

    print(f"  configurations evaluated : {report.n_experiments}")
    print(f"  alpha                    : {report.alpha:g}")
    print(f"  expected false positives : {report.expected_false_positives:.2f}")
    print(f"  nominal positives found  : {report.n_nominal_positives}")
    print(f"  claimed p-value          : {report.original_p}")
    print(f"  correction               : {report.correction}")
    print(f"  adjusted p-value         : {report.adjusted_p:.4f}")
    print(f"  survives correction      : {report.survives_correction}")
    print(f"  positives at chance rate : {report.at_chance_rate}")
    print()

    for finding in report.findings:
        print(f"  [{finding.status.value}] {finding.code}")
        print(f"      {finding.message}")
        print()

    print(f"  verdict: {report.verdict.value}")
    try:
        report.certify().require()
    except RefusedError as exc:
        print("  -> REFUSED: the positives are indistinguishable from chance")
        print(f"     {exc}")
    print()


def show_limitations() -> None:
    """The correction is never presented as stronger than it is."""
    print("=" * 72)
    print("known limitations, carried on every report")
    print("=" * 72)

    counter = ExperimentCounter(alpha=0.05)
    counter.record("only")
    report = counter.report()
    for i, limitation in enumerate(report.known_limitations, start=1):
        print(f"  {i}. {limitation}")
    print()
    print("  These are printed rather than filed away because the whole failure")
    print("  mode is a corrected p-value read as stronger than it is.")
    print()


def main() -> int:
    """The 341-configuration study, the 60-configuration study, and the caveats."""
    show(
        341,
        claimed_p=0.03,
        n_positives=16,
        story="nominal positives sit right at the chance rate",
    )
    show(
        60,
        claimed_p=0.041,
        n_positives=1,
        story="one positive where ~3 are expected",
    )
    show_limitations()
    return 0


if __name__ == "__main__":
    sys.exit(main())
