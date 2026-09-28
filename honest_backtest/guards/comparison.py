"""Guard 8 -- declared selection predicates, and the asymmetry between them.

THE MEASURED FAILURE
--------------------
A walk-forward evaluation compared a cohort of leaders against a benchmark
universe. The cohort excluded stale and dormant subjects. The benchmark did
not. The first README draft of that study then reported the comparison as a
**"POSITIVE 4/4 splits"** result.

Dormant subjects have a flat ``0.0`` forward return, and that zero is *fake
data*, not a flat performance: a subject that stopped trading has no forward
return to measure, and recording one as 0.0 pulls the benchmark's mean toward
zero. A benchmark dragged toward zero makes any active cohort look skilful, and
it does so without any number in the output looking wrong. The spread was
positive; the t-stat was respectable; the only symptom was statistical, which
is the worst kind, because a statistical symptom invites tuning rather than a
fix. The violating code carried a comment stating the very principle it broke --
*"its flat stretch would be counted as a genuine 0% return."*

The fix was one shared predicate, ``_eligible_as_of()``, called by both sides.

The four nested splits of that design are preserved as ``NESTED_FOUR_SPLIT``,
and each of the four has ``bench > 0`` with a cohort ``mean_fwd`` between
``-330`` and ``-1136``: the asymmetry was present in every one of the splits
that the earlier draft counted as confirmations.

THE GUARD
---------
This is a genuinely harder problem than guard 4 (``universe``), and the
difference is worth stating precisely, because it is the reason this module
exists rather than an extra parameter.

:class:`~honest_backtest.guards.universe.UniverseGuard` takes two
``Selection`` objects, which carry the predicate *callable*, and fingerprints
it -- source plus closure state. That is strong, and it only works when both
sides are built **in the same process from the same code**. In a walk-forward
study the cohort and the benchmark are frequently assembled hours apart, from
different scripts, out of a database, or by a different person. There is no
callable to fingerprint, only a *declaration* of what was done.

So this guard does the only honest thing available: it **requires the caller to
declare its predicates** and refuses when the declarations differ. It compares

* the declared predicate *names*
* the declared filter *clauses*, as a set and as an ordered sequence
* whether one side was filtered at all and the other was not
* the order of clauses where the caller says order is observable

and it refuses on divergence. What it cannot do is infer the truth from values:
two populations of numbers with the same mean and the same size can have been
selected by wildly different rules, and no arithmetic recovers the rule. The
guard is explicit about that and does not guess. **A guard that cannot be fooled
is worth more than one that guesses**, and a declaration is checkable in a way
an inference is not -- it can be diffed, reviewed, and pinned in a test.

The secondary, numeric instrument
---------------------------------
One symptom *is* visible numerically, and the module implements it as
:meth:`ComparisonGuard.zero_mass_symptom`: when one population carries a large
mass of exactly-zero forward returns and the other does not, that is consistent
with the recorded failure. It is a **heuristic, not proof**. It cannot
distinguish "dormant subjects were left in" from "this cohort genuinely had a
quiet period", and a caller who treats it as a finding has replaced one
self-deception with another. It therefore emits ``WARN``, never ``FAIL``, and
the report says so in the finding's own message.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from ..types import Certification, Finding, Severity, Status, Verdict

__all__ = [
    "Predicate",
    "Population",
    "PredicateAuditReport",
    "ComparisonGuard",
    "undeclared_population",
    "UNFILTERED_CLAUSES",
    "DIVERGENT_PREDICATE_FAILURE",
    "CLAUSE_ORDER_FAILURE",
    "ONE_SIDED_FILTER_FAILURE",
    "UNDECLARED_PREDICATE_FAILURE",
    "ZERO_MASS_SYMPTOM_WARNING",
]

DIVERGENT_PREDICATE_FAILURE = "COMPARISON_DIVERGENT_PREDICATE"
CLAUSE_ORDER_FAILURE = "COMPARISON_CLAUSE_ORDER"
ONE_SIDED_FILTER_FAILURE = "COMPARISON_ONE_SIDED_FILTER"
UNDECLARED_PREDICATE_FAILURE = "COMPARISON_PREDICATE_UNDECLARED"
ZERO_MASS_SYMPTOM_WARNING = "COMPARISON_ZERO_MASS_SYMPTOM"

#: Clause names that mean "no filtering was applied by this side".
#:
#: Spelled out rather than inferred, because "the benchmark was unfiltered" is
#: the exact shape of the recorded defect: the cohort had a staleness clause and
#: the benchmark had an empty predicate, and an empty predicate is not a
#: *different* filter, it is the *absence* of one. Those are different failures
#: and they get different findings.
UNFILTERED_CLAUSES: frozenset[str] = frozenset({"", "none", "all", "unfiltered", "identity"})


@dataclass(frozen=True, slots=True)
class Predicate:
    """A declared selection rule: a name, and the clauses it is made of.

    ``clauses`` are the individual filter terms in the order they were applied
    -- ``("history >= 30d", "not dormant")``. Names are compared, clauses are
    compared, and the *sequence* is compared only when **both** sides set
    ``ordered = True``, because clause order is observable for some pipelines (a
    streaming filter chain, a SQL ``WHERE`` applied before a join) and invisible
    for others (a set intersection). Claiming order-observability you do not
    have would manufacture findings; denying it when you do have it would hide a
    real divergence, which is why it is a declaration rather than a guess. One
    side declaring it does not license a finding against a side that did not.
    """

    name: str
    clauses: tuple[str, ...] = ()
    ordered: bool = False
    source: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("Predicate.name must be a non-empty identifier")

    @property
    def normalized(self) -> tuple[str, ...]:
        """Clauses, stripped and lowercased, in declared order."""
        return tuple(c.strip().lower() for c in self.clauses)

    @property
    def clause_set(self) -> frozenset[str]:
        """Clauses as an unordered set, for the order-insensitive comparison."""
        return frozenset(self.normalized)

    @property
    def filters(self) -> bool:
        """False when this predicate is declared as an explicit no-op."""
        if not self.normalized:
            return False
        return not all(c in UNFILTERED_CLAUSES for c in self.normalized)

    def as_dict(self) -> dict[str, object]:
        """JSON-serialisable view."""
        return {
            "name": self.name,
            "clauses": list(self.clauses),
            "ordered": self.ordered,
            "source": self.source,
            "filters": self.filters,
        }


@dataclass(frozen=True, slots=True)
class Population:
    """One side of a comparison: its members, and the predicate that made it.

    ``forward_returns`` is optional and only feeds the numeric symptom
    instrument. It is *not* how the guard decides whether the predicates match
    -- a value-based check cannot see the rule, which is the whole point.
    """

    name: str
    predicate: Predicate
    size: int
    forward_returns: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("Population.name must be a non-empty identifier")
        if self.size < 0:
            raise ValueError(f"Population.size must be >= 0, got {self.size}")

    @property
    def zero_fraction(self) -> float | None:
        """Share of forward returns that are exactly ``0.0``, or ``None``.

        ``None`` when no returns were supplied, so a caller can tell "clean"
        from "not measured" -- the distinction the whole library is about.
        """
        if not self.forward_returns:
            return None
        return sum(1 for r in self.forward_returns if r == 0.0) / len(self.forward_returns)

    def as_dict(self) -> dict[str, object]:
        """JSON-serialisable view."""
        return {
            "name": self.name,
            "size": self.size,
            "predicate": self.predicate.as_dict(),
            "n_forward_returns": len(self.forward_returns),
            "zero_fraction": self.zero_fraction,
        }


@dataclass(frozen=True, slots=True)
class PredicateAuditReport:
    """Outcome of the declared-predicate comparison."""

    cohort_name: str
    benchmark_name: str
    cohort_size: int
    benchmark_size: int
    same_name: bool
    same_clauses: bool
    same_order: bool
    asymmetric_filtering: bool
    zero_fraction_gap: float | None
    findings: tuple[Finding, ...]

    @property
    def predicate_identical(self) -> bool:
        """True when name, clause set, and (if claimed observable) order match."""
        return self.same_name and self.same_clauses and self.same_order

    @property
    def comparable(self) -> bool:
        """True when no blocking finding was raised."""
        return not any(f.severity is Severity.BLOCKING for f in self.findings)

    @property
    def verdict(self) -> Verdict:
        """``REFUSED`` on a declared divergence, else ``CERTIFIED``.

        Within *this* report the numeric symptom cannot move the verdict: it is
        emitted at ``INFO`` severity, and this property reads ``Severity``. That
        is a property of this class and no more than that.

        On the **composite** report it does more, and the difference is worth
        stating rather than glossing: ``report.py`` maps any ``Status.WARN`` to
        ``Verdict.SUSPECT``, and it reads ``status``, not ``severity``. So a
        zero-mass symptom alone leaves this report ``CERTIFIED`` while downgrading
        the aggregate to ``SUSPECT``. That is the intended behaviour — a heuristic
        must never *refuse* a result, but it must not be invisible either — and
        an earlier draft of this docstring claimed the heuristic could not reach
        the verdict at all, which was false.
        """
        return Verdict.CERTIFIED if self.comparable else Verdict.REFUSED

    def certify(self) -> Certification:
        """Produce the :class:`Certification` for this report."""
        reasons = tuple(f.message for f in self.findings if f.status is Status.FAIL)
        return Certification(
            verdict=self.verdict,
            reasons=reasons,
            provenance=("comparison",),
            findings=self.findings,
        )

    def as_dict(self) -> dict[str, object]:
        """JSON-serialisable view."""
        return {
            "cohort_name": self.cohort_name,
            "benchmark_name": self.benchmark_name,
            "cohort_size": self.cohort_size,
            "benchmark_size": self.benchmark_size,
            "same_name": self.same_name,
            "same_clauses": self.same_clauses,
            "same_order": self.same_order,
            "asymmetric_filtering": self.asymmetric_filtering,
            "predicate_identical": self.predicate_identical,
            "zero_fraction_gap": self.zero_fraction_gap,
            "comparable": self.comparable,
            "verdict": self.verdict.value,
            "findings": [f.as_dict() for f in self.findings],
        }


class ComparisonGuard:
    """Refuse a two-population comparison whose predicates were not shared.

    Parameters
    ----------
    require_declared_clauses:
        Default ``True``. A predicate declared with a name and *no* clauses
        cannot be compared to anything, so a nameless comparison is reported
        rather than silently passed. Set ``False`` only when the caller genuinely
        cannot enumerate the clauses -- and note that the guard then has no
        evidence at all, which the finding says out loud.
    allow_empty_clauses:
        Default ``False``. When ``False``, a predicate that declares no clauses
        is treated as under-specified rather than as "unfiltered".
    zero_mass_gap_threshold:
        The gap in exactly-zero forward-return share between the two
        populations at which the numeric *heuristic* warns. ``0.20`` means "one
        side has 20 percentage points more exact zeros than the other". This
        raises ``WARN`` at ``INFO`` severity and can never refuse anything.
    """

    name = "comparison"

    def __init__(
        self,
        *,
        require_declared_clauses: bool = True,
        allow_empty_clauses: bool = False,
        zero_mass_gap_threshold: float = 0.20,
    ) -> None:
        if not 0.0 <= zero_mass_gap_threshold <= 1.0:
            raise ValueError(
                "zero_mass_gap_threshold must be in [0, 1], got "
                f"{zero_mass_gap_threshold}"
            )
        self.require_declared_clauses = require_declared_clauses
        self.allow_empty_clauses = allow_empty_clauses
        self.zero_mass_gap_threshold = zero_mass_gap_threshold

    # ------------------------------------------------------------------
    # the numeric symptom (heuristic, never blocking)
    # ------------------------------------------------------------------

    def zero_mass_symptom(
        self, cohort: Population, benchmark: Population
    ) -> tuple[float | None, Finding | None]:
        """Compare exact-zero mass between the two populations.

        Returns ``(gap, finding_or_None)``. The gap is
        ``benchmark.zero_fraction - cohort.zero_fraction``: positive means the
        benchmark carries more dead zeros, which is the recorded direction.

        **This is a symptom, not a diagnosis.** A cohort of genuinely quiet
        subjects has the same signature as a benchmark of dormant ones, and this
        function cannot tell them apart -- it has only the numbers, and the rule
        that produced them is not in the numbers. That is why it warns instead
        of refusing.
        """
        c_zero, b_zero = cohort.zero_fraction, benchmark.zero_fraction
        if c_zero is None or b_zero is None:
            return None, None
        gap = b_zero - c_zero
        if abs(gap) < self.zero_mass_gap_threshold:
            return gap, None
        side, other = (
            (benchmark, cohort) if gap > 0 else (cohort, benchmark)
        )
        return gap, Finding(
            code=ZERO_MASS_SYMPTOM_WARNING,
            message=(
                f"heuristic, not proof: {side.name!r} is {abs(gap):.0%} exact-zero "
                f"forward returns against {other.name!r}'s "
                f"{(other.zero_fraction or 0.0):.0%}. A dormant subject's forward "
                "return is a flat 0.0, so a population carrying more of them is "
                "dragged toward zero -- the signature of the cohort/benchmark "
                "asymmetry. This cannot distinguish dormancy from a genuinely "
                "quiet period and is reported as a symptom only"
            ),
            status=Status.WARN,
            severity=Severity.INFO,
            detail={
                "zero_fraction_gap": round(gap, 6),
                "threshold": self.zero_mass_gap_threshold,
                "cohort_zero_fraction": None if c_zero is None else round(c_zero, 6),
                "benchmark_zero_fraction": None if b_zero is None else round(b_zero, 6),
            },
        )

    # ------------------------------------------------------------------
    # the structural check (the guard proper)
    # ------------------------------------------------------------------

    def run(self, cohort: Population, benchmark: Population) -> PredicateAuditReport:
        """Compare the two declared predicates and refuse a divergence."""
        findings: list[Finding] = []
        cp, bp = cohort.predicate, benchmark.predicate

        same_name = cp.name == bp.name
        same_clauses = cp.clause_set == bp.clause_set
        # Order is compared only when BOTH sides declare it observable. One
        # side claiming order while the other denies it does not license a
        # finding against the denying side -- that would assert something about
        # a pipeline that explicitly said the assertion cannot be made, which is
        # the kind of inference this module refuses everywhere else.
        order_observable = cp.ordered and bp.ordered
        same_order = (not order_observable) or cp.normalized == bp.normalized
        asymmetric_filtering = cp.filters != bp.filters

        # -- (a) under-specified declarations -------------------------------
        if self.require_declared_clauses and not self.allow_empty_clauses:
            undeclared = [p for p in (cp, bp) if not p.normalized]
            if undeclared:
                findings.append(
                    Finding(
                        code=UNDECLARED_PREDICATE_FAILURE,
                        message=(
                            "the comparison guard cannot check what was not "
                            "declared: "
                            + ", ".join(repr(p.name) for p in undeclared)
                            + " list no filter clauses, so there is nothing to "
                            "compare. Declare the clauses, or the two populations "
                            "have no evidence of sharing a selection rule"
                        ),
                        status=Status.FAIL,
                        severity=Severity.BLOCKING,
                        detail={
                            "sides": ", ".join(p.name for p in undeclared),
                            "n_clauses": sum(len(p.clauses) for p in undeclared),
                        },
                    )
                )
        elif not cp.normalized and not bp.normalized:
            # The check above was relaxed, so the guard is about to compare two
            # empty declarations and find them identical. It must not do that
            # silently: "identical" on no information is a positive claim of
            # shared selection drawn from nothing, and the report's own
            # ``predicate_identical`` would export it. Record the caveat so the
            # relaxation cannot look like a result.
            findings.append(
                Finding(
                    code=UNDECLARED_PREDICATE_FAILURE,
                    message=(
                        "both sides declare no filter clauses, so their predicates "
                        "match only because there is nothing to disagree about; "
                        "this comparison carries no evidence that the two "
                        "populations shared a selection rule"
                    ),
                    status=Status.WARN,
                    severity=Severity.INFO,
                    detail={"cohort_predicate": cp.name, "benchmark_predicate": bp.name},
                )
            )

        # -- (b) one side filtered, the other not ---------------------------
        if asymmetric_filtering:
            filtered = cp if cp.filters else bp
            unfiltered = bp if cp.filters else cp
            findings.append(
                Finding(
                    code=ONE_SIDED_FILTER_FAILURE,
                    message=(
                        f"{filtered.name!r} applies {len(filtered.normalized)} filter "
                        f"clause(s) and {unfiltered.name!r} applies none "
                        f"({filtered.name} = {'; '.join(filtered.normalized)}); an "
                        "unfiltered benchmark is drawn from a different population "
                        "than a filtered cohort, and any excess return measured "
                        "against it is a comparison against a differently-defined "
                        "universe"
                    ),
                    status=Status.FAIL,
                    severity=Severity.BLOCKING,
                    detail={
                        "filtered_side": filtered.name,
                        "unfiltered_side": unfiltered.name,
                        "filtered_clauses": "; ".join(filtered.normalized),
                    },
                )
            )
        elif not same_clauses:
            only_cohort = sorted(cp.clause_set - bp.clause_set)
            only_bench = sorted(bp.clause_set - cp.clause_set)
            findings.append(
                Finding(
                    code=DIVERGENT_PREDICATE_FAILURE,
                    message=(
                        f"cohort and benchmark were selected by different "
                        f"predicates: {cohort.name!r} is missing "
                        f"{{{', '.join(only_bench) or 'nothing'}}} and "
                        f"{benchmark.name!r} is missing "
                        f"{{{', '.join(only_cohort) or 'nothing'}}}. Route both "
                        "sides through one shared predicate; see "
                        "honest_backtest.guards.comparison"
                    ),
                    status=Status.FAIL,
                    severity=Severity.BLOCKING,
                    detail={
                        "cohort_clauses": "; ".join(cp.normalized),
                        "benchmark_clauses": "; ".join(bp.normalized),
                        "only_in_cohort": "; ".join(only_cohort),
                        "only_in_benchmark": "; ".join(only_bench),
                    },
                )
            )
        elif not same_name:
            # Same clauses, different name: weaker than a clause divergence, but
            # still two rules that will drift apart on the next edit. Reported,
            # and blocking, because the name is the caller's own declaration of
            # identity and it does not match.
            findings.append(
                Finding(
                    code=DIVERGENT_PREDICATE_FAILURE,
                    message=(
                        f"the two sides declare the same clauses under different "
                        f"predicate names ({cp.name!r} vs {bp.name!r}); identical "
                        "today is not the same as one shared predicate, and the "
                        "next edit to one of them will not touch the other"
                    ),
                    status=Status.FAIL,
                    severity=Severity.BLOCKING,
                    detail={
                        "cohort_predicate": cp.name,
                        "benchmark_predicate": bp.name,
                        "clauses": "; ".join(cp.normalized),
                    },
                )
            )

        # -- (c) clause order, where observable ------------------------------
        if not same_order and same_clauses:
            findings.append(
                Finding(
                    code=CLAUSE_ORDER_FAILURE,
                    message=(
                        "the same clauses were applied in a different order "
                        f"({cohort.name!r}: {' -> '.join(cp.normalized)}; "
                        f"{benchmark.name!r}: {' -> '.join(bp.normalized)}); the "
                        "caller declared order observable for this pipeline, and "
                        "an order-dependent filter chain that differs between the "
                        "two sides is not one shared predicate"
                    ),
                    status=Status.FAIL,
                    severity=Severity.BLOCKING,
                    detail={
                        "cohort_order": " -> ".join(cp.normalized),
                        "benchmark_order": " -> ".join(bp.normalized),
                    },
                )
            )

        # -- (d) the numeric symptom, at INFO severity -----------------------
        gap, symptom = self.zero_mass_symptom(cohort, benchmark)
        if symptom is not None:
            findings.append(symptom)

        return PredicateAuditReport(
            cohort_name=cohort.name,
            benchmark_name=benchmark.name,
            cohort_size=cohort.size,
            benchmark_size=benchmark.size,
            same_name=same_name,
            same_clauses=same_clauses,
            same_order=same_order,
            asymmetric_filtering=asymmetric_filtering,
            zero_fraction_gap=None if gap is None else round(gap, 6),
            findings=tuple(findings),
        )

    def check(self, cohort: Population, benchmark: Population) -> PredicateAuditReport:
        """Alias for :meth:`run`, matching the other guards' entry point."""
        return self.run(cohort, benchmark)


def undeclared_population(
    name: str, size: int, forward_returns: Sequence[float] = ()
) -> Population:
    """Build a population whose predicate is explicitly *not* declared.

    A convenience for the case the guard is meant to catch in the wild: a
    benchmark whose selection rule nobody wrote down. The predicate is named
    ``<name>:undeclared`` and carries no clauses, so the guard reports the
    absence rather than passing it in silence.
    """
    return Population(
        name=name,
        predicate=Predicate(name=f"{name}:undeclared", clauses=()),
        size=size,
        forward_returns=tuple(forward_returns),
    )
