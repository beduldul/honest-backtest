"""Guard 4 -- benchmark-eligibility asymmetry.

THE MEASURED FAILURE
--------------------
The cohort filter excluded stale and dormant subjects. The benchmark filter did
not. Dormant subjects have a flat 0% forward return, so including them drags
the benchmark toward zero, and a cohort of active subjects thereby looks
skilful against a benchmark that is half asleep.

Nothing in the output looked wrong. The spread was positive, the t-stat was
respectable, and the only symptom was statistical -- which is the worst kind,
because a statistical symptom invites tuning rather than a fix. The fix was to
route both sides through one shared predicate.

THE GUARD
---------
:func:`require_shared_predicate` is a runtime check: it audits that the callable
objects are identical and that the two selected sets were produced by the same
one.

:class:`UniverseGuard` adds the structural half. It hashes the *source* of the
predicate and records it in the report, so the certification carries the
identity of the rule it certified against. If a later refactor changes one side
independently, the hash changes and any consumer holding an older certification
can see that the rule moved.

The test that matters is in ``tests/test_universe.py``: it monkeypatches the two
filters apart and asserts the guard fails. A guard against divergence that is
never tested against divergence is decoration.
"""

from __future__ import annotations

import hashlib
import inspect
import textwrap
from dataclasses import dataclass
from typing import Callable, Generic, Sequence, TypeVar

from ..types import Certification, Finding, Severity, Status, Verdict

__all__ = [
    "UniverseGuard",
    "UniverseReport",
    "Selection",
    "require_shared_predicate",
    "predicate_fingerprint",
    "ASYMMETRIC_FAILURE",
    "EMPTY_SIDE_FAILURE",
]

ASYMMETRIC_FAILURE = "UNIVERSE_ASYMMETRIC_PREDICATE"
EMPTY_SIDE_FAILURE = "UNIVERSE_EMPTY_SELECTION"

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class Selection(Generic[T]):
    """One side's selected universe, plus the predicate that produced it.

    ``selected`` is the *result*; ``predicate`` is the *rule*. Both are carried,
    because checking only the results misses the case where two different
    predicates happen to agree today and diverge tomorrow -- which is precisely
    how the original defect survived review.
    """

    name: str
    predicate: Callable[[T], bool]
    selected: tuple[T, ...]

    @property
    def size(self) -> int:
        """Number of selected members."""
        return len(self.selected)


def predicate_fingerprint(predicate: Callable[..., bool]) -> str:
    """Stable short hash of a predicate's behaviour-defining source and state.

    Source alone is not enough. Two closures built by the same factory have
    identical source text and behave differently, because the difference lives
    in the closed-over value::

        make_predicate(30)   # excludes subjects younger than 30 days
        make_predicate(60)   # excludes subjects younger than 60 days

    Hashing only the source would call those two predicates identical, which is
    the exact bug this guard exists to catch, reintroduced one level down. The
    fingerprint therefore includes the free variables' values alongside the
    source.

    Falls back to ``module.qualname`` for builtins and C functions, which have
    no recoverable source. Such a fallback cannot see a closure rebind, which is
    why :func:`require_shared_predicate` prefers object identity.
    """
    try:
        source = textwrap.dedent(inspect.getsource(predicate))
    except (OSError, TypeError):
        source = f"{getattr(predicate, '__module__', '?')}."\
                 f"{getattr(predicate, '__qualname__', repr(predicate))}"
    norm = "\n".join(line.rstrip() for line in source.splitlines() if line.strip())

    closure = getattr(predicate, "__closure__", None) or ()
    freevars = getattr(getattr(predicate, "__code__", None), "co_freevars", ())
    state = "|".join(
        f"{name}={_repr_cell(cell)}" for name, cell in zip(freevars, closure)
    )
    defaults = getattr(predicate, "__defaults__", None) or ()
    default_state = "|".join(repr(d) for d in defaults)

    digest = hashlib.sha256(
        f"{norm}\x00{state}\x00{default_state}".encode("utf-8")
    ).hexdigest()
    return digest[:16]


def _repr_cell(cell: object) -> str:
    """Render a closure cell's contents for fingerprinting.

    Values that are not safely representable fall back to their type name, so
    the fingerprint degrades to *less* specific rather than raising inside a
    validation path.
    """
    try:
        value = cell.cell_contents  # type: ignore[attr-defined]
    except ValueError:
        return "<empty>"
    try:
        return repr(value)
    except Exception:  # pragma: no cover - defensive
        return f"<{type(value).__name__}>"


def _same_members(a: Sequence[T], b: Sequence[T]) -> bool:
    """Multiset equality that tolerates unhashable members.

    ``set(a) != set(b)`` raises ``TypeError`` on a list of dicts, which is the
    most natural way to represent subjects, so a plain set comparison would
    crash on exactly the input this guard is meant to inspect.
    """
    if len(a) != len(b):
        return False
    try:
        return set(a) == set(b)
    except TypeError:
        remaining = list(b)
        for item in a:
            for i, candidate in enumerate(remaining):
                if candidate == item:
                    del remaining[i]
                    break
            else:
                return False
        return not remaining


def require_shared_predicate(
    cohort: Selection[T], benchmark: Selection[T]
) -> None:
    """Raise ``ValueError`` unless both sides use one and the same predicate.

    Identity first, fingerprint second. Identity is the strong statement: the
    *same object* filtered both sides, so they cannot drift. When identity
    fails, we do not immediately reject -- a rebuilt lambda over the same source
    is a common and harmless pattern -- but we require the fingerprints to
    match, which is the strongest statement available at that point.
    """
    same_object = cohort.predicate is benchmark.predicate
    if same_object:
        return
    fp_cohort = predicate_fingerprint(cohort.predicate)
    fp_bench = predicate_fingerprint(benchmark.predicate)
    if fp_cohort != fp_bench:
        raise ValueError(
            "cohort and benchmark were selected by different predicates: "
            f"{cohort.name}={fp_cohort!r} vs {benchmark.name}={fp_bench!r}. "
            "Route both sides through one shared predicate; see "
            "honest_backtest.guards.universe"
        )


@dataclass(frozen=True, slots=True)
class UniverseReport:
    """Outcome of the eligibility-symmetry check."""

    cohort_name: str
    benchmark_name: str
    cohort_size: int
    benchmark_size: int
    same_object: bool
    fingerprint: str | None
    findings: tuple[Finding, ...]

    @property
    def symmetric(self) -> bool:
        """True when no blocking finding was raised."""
        return not any(f.severity is Severity.BLOCKING for f in self.findings)

    @property
    def verdict(self) -> Verdict:
        """``REFUSED`` on asymmetry or an empty side."""
        return Verdict.CERTIFIED if self.symmetric else Verdict.REFUSED

    def certify(self) -> Certification:
        """Produce the :class:`Certification` for this report."""
        reasons = tuple(f.message for f in self.findings if f.status is Status.FAIL)
        return Certification(
            verdict=self.verdict,
            reasons=reasons,
            provenance=("universe",),
            findings=self.findings,
        )

    def as_dict(self) -> dict[str, object]:
        """JSON-serialisable view."""
        return {
            "cohort_name": self.cohort_name,
            "benchmark_name": self.benchmark_name,
            "cohort_size": self.cohort_size,
            "benchmark_size": self.benchmark_size,
            "same_object": self.same_object,
            "fingerprint": self.fingerprint,
            "symmetric": self.symmetric,
            "verdict": self.verdict.value,
            "findings": [f.as_dict() for f in self.findings],
        }


class UniverseGuard:
    """Verify cohort and benchmark come from one eligibility rule.

    Parameters
    ----------
    require_identical_object:
        Default ``True``. With ``True`` a same-source rebuild of the predicate
        still fails, and the only way to pass is to pass the same object. That
        is the setting to use when you can change the calling code, which is
        almost always. Set ``False`` to accept a matching fingerprint.
    min_size:
        Either side smaller than this is reported. An empty benchmark silently
        makes every excess number meaningless.
    """

    name = "universe"

    def __init__(
        self, *, require_identical_object: bool = True, min_size: int = 1
    ) -> None:
        if min_size < 0:
            raise ValueError(f"min_size must be >= 0, got {min_size}")
        self.require_identical_object = require_identical_object
        self.min_size = min_size

    def run(
        self, cohort: Selection[T], benchmark: Selection[T]
    ) -> UniverseReport:
        """Evaluate the two selections for eligibility symmetry."""
        findings: list[Finding] = []
        same_object = cohort.predicate is benchmark.predicate
        fp_cohort = predicate_fingerprint(cohort.predicate)
        fp_bench = predicate_fingerprint(benchmark.predicate)
        fingerprint = fp_cohort if fp_cohort == fp_bench else None

        asymmetric = (not same_object) and (
            self.require_identical_object or fp_cohort != fp_bench
        )
        if asymmetric:
            findings.append(
                Finding(
                    code=ASYMMETRIC_FAILURE,
                    message=(
                        f"cohort {cohort.name!r} and benchmark {benchmark.name!r} "
                        "were selected by different predicates, so their excess "
                        "return is a comparison against a differently-defined "
                        "universe"
                    ),
                    status=Status.FAIL,
                    severity=Severity.BLOCKING,
                    detail={
                        "same_object": False,
                        "cohort_fingerprint": fp_cohort,
                        "benchmark_fingerprint": fp_bench,
                        "cohort_size": cohort.size,
                        "benchmark_size": benchmark.size,
                    },
                )
            )

        for sel in (cohort, benchmark):
            if sel.size < self.min_size:
                findings.append(
                    Finding(
                        code=EMPTY_SIDE_FAILURE,
                        message=(
                            f"{sel.name!r} selected {sel.size} member(s), below the "
                            f"minimum {self.min_size}; an empty or near-empty "
                            "universe makes every excess statistic undefined"
                        ),
                        status=Status.FAIL,
                        severity=Severity.BLOCKING,
                        detail={"side": sel.name, "size": sel.size},
                    )
                )

        return UniverseReport(
            cohort_name=cohort.name,
            benchmark_name=benchmark.name,
            cohort_size=cohort.size,
            benchmark_size=benchmark.size,
            same_object=same_object,
            fingerprint=fingerprint,
            findings=tuple(findings),
        )

    def check(
        self,
        cohort: Selection[T],
        benchmark: Selection[T],
        *,
        subjects: Sequence[T] = (),
    ) -> UniverseReport:
        """Symmetry check, plus an optional re-derivation from raw subjects.

        When ``subjects`` is supplied, both sides are recomputed from the
        shared predicate and compared to the declared members. A mismatch means
        the declared universe was assembled some other way -- a filter applied
        afterwards, a manual exclusion list, a stale cache -- which reintroduces
        the very asymmetry the guard exists to catch, just below the level the
        predicate comparison can see.
        """
        report = self.run(cohort, benchmark)
        if not subjects or not report.symmetric:
            return report

        drift: list[Finding] = []
        for sel in (cohort, benchmark):
            derived = tuple(s for s in subjects if sel.predicate(s))
            if not _same_members(derived, sel.selected):
                drift.append(
                    Finding(
                        code=ASYMMETRIC_FAILURE,
                        message=(
                            f"{sel.name!r} declares {sel.size} member(s) but its "
                            f"own predicate selects {len(derived)} from the "
                            "supplied subjects; the universe was assembled by "
                            "something other than the predicate it claims"
                        ),
                        status=Status.FAIL,
                        severity=Severity.BLOCKING,
                        detail={
                            "side": sel.name,
                            "declared": sel.size,
                            "derived": len(derived),
                        },
                    )
                )
        if not drift:
            return report
        return UniverseReport(
            cohort_name=report.cohort_name,
            benchmark_name=report.benchmark_name,
            cohort_size=report.cohort_size,
            benchmark_size=report.benchmark_size,
            same_object=report.same_object,
            fingerprint=report.fingerprint,
            findings=(*report.findings, *drift),
        )
