"""Guard 3 -- overlapping and nested evaluation windows.

THE MEASURED FAILURE
--------------------
A walk-forward design reported **4 splits**. All four shared the same end date.
The forward windows were therefore strictly nested: each one contained the
previous one's data. The number of pairwise-independent windows was **zero**.

The report said "0 of 4 negative". That reads as four confirmations. It is one
observation, repeated four times, with a shrinking start date. The effective
sample size was **one**.

The fix was a non-overlapping design that extracted **12 genuinely disjoint
30-day windows** from the same 365-day panel. Note what happened to the number:
it went *up*, from 4 to 12, because the 4 were never 4.

THE GUARD
---------
:class:`WindowPlan` counts. :class:`WindowGuard` refuses when the count of
pairwise-independent windows is below a configured minimum.

Two counts are reported because they fail differently:

``independent_count``
    Number of pairwise-disjoint windows. Zero for nested designs.
``effective_count``
    Number of disjoint windows *and* of non-overlapping-but-not-disjoint
    windows taken greedily. For the fixtures these agree; they diverge when a
    design has partial overlaps, which are independent of nothing but still
    share data.

The guard uses ``effective_count`` for its threshold test, because a partial
overlap is exactly the "looks like more evidence than it is" case.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from ..plans import Window, contiguous_windows
from ..types import Certification, Finding, Severity, Status, Verdict

__all__ = [
    "WindowPlan",
    "IndependentWindowReport",
    "WindowGuard",
    "NESTED_FAILURE",
    "INSUFFICIENT_INDEPENDENCE_FAILURE",
    "SPAN_DISAGREEMENT_FAILURE",
]

NESTED_FAILURE = "WINDOWS_FULLY_NESTED"
INSUFFICIENT_INDEPENDENCE_FAILURE = "WINDOWS_INSUFFICIENT_INDEPENDENCE"
SPAN_DISAGREEMENT_FAILURE = "WINDOWS_CLAIMED_SPAN_MISMATCH"


@dataclass(frozen=True, slots=True)
class WindowPlan:
    """A named set of evaluation windows, as *claimed* by the user.

    ``claimed`` is what the design document says. The plan does not trust it:
    every count below is derived from the intervals, and
    :meth:`span_agreement` reports the gap. If someone writes "12 monthly
    windows" and supplies 12 windows that are all the same month, the plan
    knows.
    """

    windows: tuple[Window, ...]
    label: str = "plan"
    claimed: int | None = None

    def __post_init__(self) -> None:
        cleaned: list[Window] = []
        for i, w in enumerate(self.windows):
            if not isinstance(w, Window):
                raise TypeError(f"windows[{i}] is {type(w).__name__}, expected Window")
            cleaned.append(w if w.label else Window(w.start, w.end, f"w{i + 1}"))
        object.__setattr__(self, "windows", tuple(cleaned))

    def __len__(self) -> int:
        return len(self.windows)

    def __iter__(self) -> Iterable[Window]:
        return iter(self.windows)

    @property
    def shared_end_count(self) -> int:
        """How many windows share the single most common end date."""
        if not self.windows:
            return 0
        counts: dict[object, int] = {}
        for w in self.windows:
            counts[w.end] = counts.get(w.end, 0) + 1
        return max(counts.values())

    @property
    def fully_nested(self) -> bool:
        """True when every window ends on the same date.

        This is the fixture shape: 4 splits, one shared end date, zero
        independent windows. Detected explicitly so the failure message can say
        *why* rather than only *how many*.
        """
        return len(self.windows) >= 2 and self.shared_end_count == len(self.windows)

    def span(self) -> tuple[object, object] | None:
        """Earliest start and latest end, or ``None`` for an empty plan."""
        if not self.windows:
            return None
        return (min(w.start for w in self.windows), max(w.end for w in self.windows))

    def span_days(self) -> int:
        """Calendar days covered from earliest start to latest end."""
        s = self.span()
        if s is None:
            return 0
        return (s[1] - s[0]).days  # type: ignore[operator]

    def independent_count(self) -> int:
        """Number of *additional* pairwise-independent windows beyond the first.

        The fixture makes the semantics concrete. Four splits all ending on the
        same date share data with one another, and the reported figure is **0**:
        the design contributed no confirmation that the first window did not
        already provide. Saying "1" would be technically true of a maximum
        disjoint subset and completely misleading about the evidence, so this
        method counts *replications*, not representatives.

        Mechanically: the first window is the reference; a later window counts
        only if it is disjoint from every window accepted so far. A plan of 12
        back-to-back 30-day windows therefore reports 11 additional -- the
        twelfth window is the eleventh replication of the first. The window
        count itself is always available as :func:`len`, and
        :meth:`max_disjoint` gives the subset size for callers who want it.
        """
        if not self.windows:
            return 0
        if self.fully_nested:
            return 0
        ordered = sorted(self.windows, key=lambda w: (w.start, w.end))
        accepted: list[Window] = [ordered[0]]
        for candidate in ordered[1:]:
            if all(not candidate.overlaps(a) for a in accepted):
                accepted.append(candidate)
        return len(accepted) - 1

    def max_disjoint(self) -> int:
        """Largest pairwise-disjoint subset, by greedy earliest-end scheduling.

        This is the interval-scheduling optimum. It is the right number when the
        question is "how many non-overlapping measurements fit in this span"
        and the wrong number when the question is "how much independent evidence
        does this plan contain" -- use :meth:`independent_count` for that.
        """
        if not self.windows:
            return 0
        ordered = sorted(self.windows, key=lambda w: (w.end, w.start))
        count = 0
        last_end = None
        for w in ordered:
            if last_end is None or w.start >= last_end:
                count += 1
                last_end = w.end
        return count

    def effective_count(self) -> int:
        """Independent windows, as the guard's threshold test sees them.

        Alias for :meth:`independent_count`. Kept as a distinct name because
        the guard's threshold means "effective sample", and it is worth being
        able to grep for the places that decide on evidence rather than on
        interval geometry.
        """
        return self.independent_count()

    def span_agreement(self) -> bool:
        """True when ``claimed`` (if given) matches the derived span count."""
        return self.claimed is None or self.claimed == len(self.windows)

    def report(self) -> dict[str, object]:
        """Structural summary, independent of any threshold."""
        return {
            "label": self.label,
            "n_windows": len(self.windows),
            "claimed": self.claimed,
            "fully_nested": self.fully_nested,
            "shared_end_count": self.shared_end_count,
            "independent_count": self.independent_count(),
            "max_disjoint": self.max_disjoint(),
            "span_days": self.span_days(),
            "windows": [str(w) for w in self.windows],
        }

    @classmethod
    def from_spec(cls, spec: str, *, label: str = "plan") -> "WindowPlan":
        """Build from the textual plan format (see :mod:`honest_backtest.plans`)."""
        from ..plans import parse_plan

        return cls(windows=parse_plan(spec), label=label)

    @classmethod
    def tiled(
        cls,
        start: object,
        end: object,
        *,
        length_days: int,
        label: str = "tiled",
    ) -> "WindowPlan":
        """Build a back-to-back tiling of ``[start, end)``.

        This is the recommended constructor. Tiling short-circuits the entire
        problem: back-to-back half-open windows cannot overlap, so every window
        is an independent replication and :meth:`independent_count` equals
        ``len(plan) - 1`` by construction.
        """
        from datetime import date

        if not isinstance(start, date) or not isinstance(end, date):
            raise TypeError("tiled() requires date start and end")
        return cls(
            windows=contiguous_windows(start, end, length_days=length_days),
            label=label,
        )


@dataclass(frozen=True, slots=True)
class IndependentWindowReport:
    """Outcome of the independence check."""

    plan: WindowPlan
    independent_count: int
    required: int
    findings: tuple[Finding, ...]

    @property
    def supported(self) -> bool:
        """True when enough independent windows exist to support a claim."""
        return self.independent_count >= self.required

    @property
    def verdict(self) -> Verdict:
        """``REFUSED`` on insufficient independence *or* any blocking finding.

        Checking the findings rather than only the count matters: the arity
        mismatch raised by :meth:`WindowGuard.check` is a blocking finding that
        does not change the count at all, and a verdict derived purely from
        ``independent_count`` would report it as ``CERTIFIED``.
        """
        blocking = any(
            f.severity is Severity.BLOCKING and f.status in (Status.FAIL, Status.ERROR)
            for f in self.findings
        )
        return Verdict.CERTIFIED if (self.supported and not blocking) else Verdict.REFUSED

    def certify(self) -> Certification:
        """Produce the :class:`Certification` for this report."""
        reasons = tuple(f.message for f in self.findings if f.status is Status.FAIL)
        return Certification(
            verdict=self.verdict,
            reasons=reasons,
            provenance=("windows",),
            findings=self.findings,
        )

    def as_dict(self) -> dict[str, object]:
        """JSON-serialisable view."""
        return {
            "independent_count": self.independent_count,
            "required": self.required,
            "supported": self.supported,
            "verdict": self.verdict.value,
            "plan": self.plan.report(),
            "findings": [f.as_dict() for f in self.findings],
        }


class WindowGuard:
    """Enforce a minimum number of independent evaluation windows.

    Parameters
    ----------
    min_independent:
        Default ``2``. Two is the smallest number that can disagree with
        itself, which is the entire value of having more than one window. Raise
        it for anything claiming a strong result; the CLI uses ``3``.
    """

    name = "windows"

    def __init__(self, *, min_independent: int = 2) -> None:
        if min_independent < 1:
            raise ValueError(f"min_independent must be >= 1, got {min_independent}")
        self.min_independent = min_independent

    def run(
        self,
        plan: WindowPlan,
        *,
        min_independent: int | None = None,
    ) -> IndependentWindowReport:
        """Count independent windows in ``plan`` and compare to the minimum."""
        required = self.min_independent if min_independent is None else min_independent
        if required < 1:
            raise ValueError(f"min_independent must be >= 1, got {required}")

        count = plan.effective_count()
        findings: list[Finding] = []

        if not plan.span_agreement():
            findings.append(
                Finding(
                    code=SPAN_DISAGREEMENT_FAILURE,
                    message=(
                        f"plan {plan.label!r} claims {plan.claimed} window(s) but "
                        f"supplies {len(plan.windows)}"
                    ),
                    status=Status.WARN,
                    severity=Severity.INFO,
                    detail={"claimed": plan.claimed, "supplied": len(plan.windows)},
                )
            )

        if count < required:
            if plan.fully_nested:
                message = (
                    f"all {len(plan.windows)} splits share the same end date "
                    f"({plan.windows[0].end.isoformat()}); the forward windows are "
                    f"strictly nested and the count of pairwise-independent windows "
                    f"is {count}, below the required {required}. An effective "
                    f"sample of {count} cannot be read as {len(plan.windows)} "
                    "confirmations"
                )
                code = NESTED_FAILURE
            else:
                message = (
                    f"only {count} pairwise-independent window(s) out of "
                    f"{len(plan.windows)} supplied, below the required {required}; "
                    "nested or overlapping windows are repeated measurements of "
                    "the same data, not replications"
                )
                code = INSUFFICIENT_INDEPENDENCE_FAILURE
            findings.append(
                Finding(
                    code=code,
                    message=message,
                    status=Status.FAIL,
                    severity=Severity.BLOCKING,
                    detail={
                        "independent_count": count,
                        "n_windows": len(plan.windows),
                        "required": required,
                        "fully_nested": plan.fully_nested,
                        "span_days": plan.span_days(),
                    },
                )
            )

        return IndependentWindowReport(
            plan=plan,
            independent_count=count,
            required=required,
            findings=tuple(findings),
        )

    def check(
        self,
        effects: Sequence[float],
        plan: WindowPlan,
        *,
        min_independent: int | None = None,
    ) -> IndependentWindowReport:
        """Independence check with an arity guard on the supplied effects.

        Supplying effects whose length disagrees with the plan is a bug in the
        caller, and it is reported as a blocking finding rather than an
        exception so a batch runner does not lose the rest of its results.
        """
        report = self.run(plan, min_independent=min_independent)
        if len(effects) != len(plan.windows):
            extra = Finding(
                code=SPAN_DISAGREEMENT_FAILURE,
                message=(
                    f"{len(effects)} effect(s) supplied for "
                    f"{len(plan.windows)} window(s); per-window statistics cannot "
                    "be trusted against this plan"
                ),
                status=Status.FAIL,
                severity=Severity.BLOCKING,
                detail={"n_effects": len(effects), "n_windows": len(plan.windows)},
            )
            return IndependentWindowReport(
                plan=plan,
                independent_count=report.independent_count,
                required=report.required,
                findings=(*report.findings, extra),
            )
        return report
