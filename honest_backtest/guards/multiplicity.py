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
and meaningless for the family. The fix is not a better p-value; it is
*counting how many times you looked*.

THE GUARD
---------
:class:`ExperimentCounter` is the reckoning. It tracks configurations, reports
the expected false-positive count, and corrects any claimed p-value.

Both standard corrections are provided, and the guard reports which it applied:

Bonferroni
    ``p_adj = min(1, p * m)``. Controls the family-wise error rate. Conservative
    and assumption-free; use it when the configurations are not exchangeable or
    when you cannot say anything about their dependence.
Sidak
    ``p_adj = 1 - (1 - p) ** m``. Exact under independence, slightly less
    conservative than Bonferroni. The corrections diverge in the direction
    Sidak is weaker, so the guard defaults to Bonferroni: this library's job is
    to make the refusal easy, not to find the most favourable defensible
    correction.

Neither correction is valid under arbitrary positive dependence, and neither
is valid when the family size is chosen *after* seeing the results. Both are
recorded as limitations in ``known_limitations`` so the number is never read as
stronger than it is.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from ..types import Certification, Finding, Severity, Status, Verdict

__all__ = [
    "ExperimentCounter",
    "MultiplicityReport",
    "Correction",
    "expected_false_positives",
    "correct_p",
]

Correction = Literal["bonferroni", "sidak", "none"]

UNCORRECTED_FAILURE = "MULTIPLICITY_UNCORRECTED"
FAMILY_EXCEEDED_FAILURE = "MULTIPLICITY_AT_CHANCE_RATE"
OVERCOUNT_FAILURE = "MULTIPLICITY_INVALID_FAMILY"

KNOWN_LIMITATIONS: tuple[str, ...] = (
    "Bonferroni and Sidak assume the family size is fixed in advance; if the "
    "number of configurations was chosen after seeing results, no correction "
    "restores validity",
    "Neither correction is exact under arbitrary positive dependence between "
    "configurations; the true family-wise rate may be higher than reported",
    "Counting configurations cannot see configurations that were tried and "
    "never recorded",
)


@dataclass(frozen=True, slots=True)
class MultiplicityReport:
    """Outcome of the family-wise error accounting."""

    n_experiments: int
    alpha: float
    expected_false_positives: float
    n_nominal_positives: int
    correction: Correction
    original_p: float | None
    adjusted_p: float | None
    at_chance_rate: bool
    findings: tuple[Finding, ...]
    known_limitations: tuple[str, ...] = KNOWN_LIMITATIONS

    @property
    def survives_correction(self) -> bool:
        """True when the adjusted p-value clears ``alpha``.

        ``None`` original p means no claim was made, which is not a survival.
        """
        if self.adjusted_p is None:
            return False
        return self.adjusted_p < self.alpha

    @property
    def verdict(self) -> Verdict:
        """Three-valued, and the only guard here that uses all three.

        ``CERTIFIED`` -- no claim was made, or the claim survives correction.
        ``SUSPECT``   -- a claim was made without correction, or the family is
                         large enough that chance explains the count.
        ``REFUSED``   -- a claim was made, the family is large, and the claim
                         does not survive correction.

        The middle band is real here because the multiplicity guard is often run
        on a design-time census (341 configurations, no single p-value). That
        census should not block work; it should forbid *quoting* a result from
        that family without correction.
        """
        if any(f.code == UNCORRECTED_FAILURE and f.status is Status.FAIL for f in self.findings):
            return Verdict.REFUSED
        if any(f.code == OVERCOUNT_FAILURE for f in self.findings):
            return Verdict.REFUSED
        if self.n_nominal_positives > 0 and not self.survives_correction:
            return Verdict.REFUSED
        if self.at_chance_rate or self.correction == "none":
            return Verdict.SUSPECT
        return Verdict.CERTIFIED

    def certify(self) -> Certification:
        """Produce the :class:`Certification` for this report."""
        reasons = tuple(f.message for f in self.findings if f.status is Status.FAIL)
        return Certification(
            verdict=self.verdict,
            reasons=reasons,
            provenance=("multiplicity",),
            findings=self.findings,
        )

    def as_dict(self) -> dict[str, object]:
        """JSON-serialisable view."""
        return {
            "n_experiments": self.n_experiments,
            "alpha": self.alpha,
            "expected_false_positives": self.expected_false_positives,
            "n_nominal_positives": self.n_nominal_positives,
            "correction": self.correction,
            "original_p": self.original_p,
            "adjusted_p": self.adjusted_p,
            "at_chance_rate": self.at_chance_rate,
            "survives_correction": self.survives_correction,
            "verdict": self.verdict.value,
            "findings": [f.as_dict() for f in self.findings],
            "known_limitations": list(self.known_limitations),
        }


@dataclass(slots=True)
class _Registry:
    """Mutable census of configurations actually evaluated."""

    configurations: dict[str, int] = field(default_factory=dict)

    def record(self, label: str) -> int:
        n = self.configurations.get(label, 0) + 1
        self.configurations[label] = n
        return n


class ExperimentCounter:
    """Count configurations and correct claimed significance.

    The counter is deliberately *stateful*: the honest family size is the
    number of configurations that were actually run, which is only knowable if
    something watched them run. Call :meth:`record` inside the sweep.

    ::

        counter = ExperimentCounter()
        for params in grid:
            counter.record(f"{params}")
            p = evaluate(params)
        report = ExperimentCounter.report(counter, claimed_p=best_p)

    When the sweep is not instrumented, :meth:`report` accepts a raw
    ``n_experiments`` and the report notes that the family size was declared
    rather than observed. That distinction is not cosmetic: a declared family
    size is exactly the number an author is tempted to trim.
    """

    name = "multiplicity"

    def __init__(
        self,
        *,
        alpha: float = 0.05,
        correction: Correction = "bonferroni",
        chance_rate_tolerance: float = 1.5,
    ) -> None:
        if not 0.0 < alpha < 1.0:
            raise ValueError(f"alpha must be in (0, 1), got {alpha}")
        if correction not in ("bonferroni", "sidak", "none"):
            raise ValueError(f"unknown correction {correction!r}")
        if chance_rate_tolerance < 1.0:
            raise ValueError("chance_rate_tolerance must be >= 1.0")
        self.alpha = alpha
        self.correction = correction
        self.chance_rate_tolerance = chance_rate_tolerance
        self._registry = _Registry()
        self._declared_family: bool = False

    @property
    def n_recorded(self) -> int:
        """Total configurations observed via :meth:`record`.

        The sum of the per-label counts, not the number of distinct labels. A
        configuration evaluated twice was evaluated twice, and the family size
        that governs the correction is the number of tests run.
        """
        return sum(self._registry.configurations.values())

    @property
    def recorded_labels(self) -> tuple[str, ...]:
        """Distinct configuration labels observed, sorted."""
        return tuple(sorted(self._registry.configurations))

    def record(self, label: str, *, weight: int = 1) -> None:
        """Register one evaluated configuration.

        ``weight`` exists for sweeps that are evaluated in batches. Recording a
        batch of 40 as a single configuration is precisely how a family of 341
        becomes a family of 9 on paper, so each unit of weight is registered as
        a distinct configuration with a stable derived label. The label is what
        makes the census auditable -- the same batch recorded twice is counted
        twice, because the second call is a configuration that was run again.
        """
        if weight < 1:
            raise ValueError(f"weight must be >= 1, got {weight}")
        if weight == 1:
            self._registry.record(label)
            return
        for i in range(weight):
            self._registry.record(f"{label}#{i + 1}")

    def __len__(self) -> int:
        return self.n_recorded

    @staticmethod
    def expected_false_positives(
        n_experiments: int, *, alpha: float = 0.05
    ) -> float:
        """``n * alpha`` -- how many 'findings' chance alone will hand you."""
        if n_experiments < 0:
            raise ValueError(f"n_experiments must be >= 0, got {n_experiments}")
        if not 0.0 < alpha < 1.0:
            raise ValueError(f"alpha must be in (0, 1), got {alpha}")
        return n_experiments * alpha

    @staticmethod
    def bonferroni(p: float, n_experiments: int) -> float:
        """Family-wise adjusted p, Bonferroni."""
        ExperimentCounter._validate_p(p)
        if n_experiments < 1:
            raise ValueError(f"n_experiments must be >= 1, got {n_experiments}")
        return min(1.0, p * n_experiments)

    @staticmethod
    def sidak(p: float, n_experiments: int) -> float:
        """Family-wise adjusted p, Sidak."""
        ExperimentCounter._validate_p(p)
        if n_experiments < 1:
            raise ValueError(f"n_experiments must be >= 1, got {n_experiments}")
        return 1.0 - (1.0 - p) ** n_experiments

    @staticmethod
    def _validate_p(p: float) -> None:
        if not 0.0 <= p <= 1.0:
            raise ValueError(f"p-value must be in [0, 1], got {p}")

    def report(
        self,
        *,
        n_experiments: int | None = None,
        claimed_p: float | None = None,
        n_nominal_positives: int | None = None,
        correction: Correction | None = None,
    ) -> MultiplicityReport:
        """Summarise the family and correct any claimed p-value.

        Parameters
        ----------
        n_experiments:
            Override the observed count. Used when the sweep was not
            instrumented; the report records the correction as applied to a
            declared family.
        claimed_p:
            The best p-value from the family, if one is being quoted.
        n_nominal_positives:
            How many configurations produced p < alpha. When this is at or
            below the expected false-positive count, the positives are
            indistinguishable from chance and the report says so in those
            words.
        correction:
            Override the instance default for this report only.
        """
        applied: Correction = correction if correction is not None else self.correction
        n = self.n_recorded if n_experiments is None else n_experiments
        if n < 0:
            raise ValueError(f"n_experiments must be >= 0, got {n}")
        if n_experiments is not None:
            self._declared_family = True
        if claimed_p is not None:
            self._validate_p(claimed_p)

        expected = self.expected_false_positives(n, alpha=self.alpha)
        findings: list[Finding] = []

        if self._declared_family and n_experiments is not None:
            findings.append(
                Finding(
                    code=UNCORRECTED_FAILURE,
                    message=(
                        f"family size {n} was declared, not observed; the number "
                        "of configurations is only defensible if something "
                        "watched them run (ExperimentCounter.record)"
                    ),
                    status=Status.WARN,
                    severity=Severity.INFO,
                    detail={"n_experiments": n, "observed": self.n_recorded},
                )
            )

        adjusted: float | None = None
        if claimed_p is not None:
            if applied == "none" or n <= 1:
                adjusted = claimed_p
                if applied == "none" and n > 1:
                    findings.append(
                        Finding(
                            code=UNCORRECTED_FAILURE,
                            message=(
                                f"p = {claimed_p:.4g} quoted from a family of {n} "
                                f"configuration(s) with no correction; {expected:.1f} "
                                "false positive(s) are expected at this family size"
                            ),
                            status=Status.FAIL,
                            severity=Severity.BLOCKING,
                            detail={
                                "original_p": claimed_p,
                                "n_experiments": n,
                                "expected_false_positives": round(expected, 6),
                            },
                        )
                    )
            else:
                adjusted = (
                    self.bonferroni(claimed_p, n)
                    if applied == "bonferroni"
                    else self.sidak(claimed_p, n)
                )
                if adjusted >= self.alpha:
                    findings.append(
                        Finding(
                            code=UNCORRECTED_FAILURE,
                            message=(
                                f"p = {claimed_p:.4g} does not survive "
                                f"{applied} correction for {n} configurations: "
                                f"adjusted p = {adjusted:.4g} >= alpha = "
                                f"{self.alpha:g}"
                            ),
                            status=Status.FAIL,
                            severity=Severity.BLOCKING,
                            detail={
                                "original_p": claimed_p,
                                "adjusted_p": round(adjusted, 8),
                                "n_experiments": n,
                                "correction": applied,
                                "alpha": self.alpha,
                            },
                        )
                    )

        at_chance = False
        if n_nominal_positives is not None:
            at_chance = (
                n_nominal_positives <= expected * self.chance_rate_tolerance
            )
            if at_chance and n_nominal_positives > 0:
                findings.append(
                    Finding(
                        code=FAMILY_EXCEEDED_FAILURE,
                        message=(
                            f"{n_nominal_positives} nominal positive(s) from {n} "
                            f"configuration(s), where {expected:.1f} are expected "
                            "by chance alone; the positives sit at the chance rate "
                            "and carry no evidence"
                        ),
                        status=Status.FAIL,
                        severity=Severity.BLOCKING,
                        detail={
                            "n_nominal_positives": n_nominal_positives,
                            "expected_false_positives": round(expected, 6),
                            "n_experiments": n,
                            "alpha": self.alpha,
                        },
                    )
                )

        return MultiplicityReport(
            n_experiments=n,
            alpha=self.alpha,
            expected_false_positives=expected,
            n_nominal_positives=0 if n_nominal_positives is None else n_nominal_positives,
            correction=applied if n > 1 else "none",
            original_p=claimed_p,
            adjusted_p=adjusted,
            at_chance_rate=at_chance,
            findings=tuple(findings),
        )


def expected_false_positives(n_experiments: int, *, alpha: float = 0.05) -> float:
    """Module-level alias for the common calculation."""
    return ExperimentCounter.expected_false_positives(n_experiments, alpha=alpha)


def correct_p(p: float, n_experiments: int, *, method: Correction = "bonferroni") -> float:
    """Correct a single p-value for a family of ``n_experiments``."""
    if method == "bonferroni":
        return ExperimentCounter.bonferroni(p, n_experiments)
    if method == "sidak":
        return ExperimentCounter.sidak(p, n_experiments)
    if method == "none":
        return p
    raise ValueError(f"unknown correction method {method!r}")
