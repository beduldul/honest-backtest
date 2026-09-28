"""Guard 7 -- provenance of negative evidence: never read an error as absence.

THE MEASURED FAILURE
--------------------
A package-availability scan recorded every candidate as::

    {"exists": false, "code": 503}

HTTP **503 (Service Unavailable / rate-limited)** is not **404 (Not Found)**.
Five of the twenty-two names in the scan came back 503 and were written down as
absent -- ``pbo``, ``cscv``, ``overfit``, ``probabilistic-sharpe`` and
``backtest-overfit``. The claim that followed ("7/7 names return 404") was
therefore *reproduced by accident* rather than verified: the instrument had
failed, and the failure was recorded in the same shape as a finding.
After correction on the same day (``/tmp/pypi_fixed.json``), ``overfit`` was
**PRESENT** on PyPI, and the run reported no 503s at all -- because it
classified a non-404 as ``UNKNOWN`` and backed off instead of concluding.

A second instance of the same failure, a different instrument. A code-search
tool returned **zero results** for a query, and the zero was read as "nobody
does this". It was not: control queries proved the tool was broken --
``lang:python "def sharpe_ratio"`` returned 0, and even ``numba`` returned 1.
A null result from an instrument that cannot be shown to return non-null results
is not evidence of anything. The decider number moved from a false **4** to
**10-18** once the zeros were discarded.

THE GUARD
---------
:class:`EvidenceGuard` takes a set of observations, each carrying the status or
outcome code the instrument returned, and classifies each one as ``PRESENT``,
``ABSENT`` or ``UNKNOWN``. Two things can then be refused:

1. An ``ABSENT`` claim resting on a non-404 observation. Absence is a *claim*;
   a 503 is an *error*. They are different objects and the report says which
   ones were conflated.
2. A **null result with no positive control**. If an instrument returned nothing
   anywhere in the observation set, and no known-positive input demonstrates
   that it can return something, the null is not evidence. This is the
   Sourcegraph failure exactly, and it is blocking **by default** — not only
   when the caller asserts a negative claim. A run in which nothing resolved is
   not a run that found nothing.

   The control cuts both ways and both directions are findings. A control that
   returns the success code demonstrates the instrument works. A control on a
   **known-positive input that returns anything else** demonstrates the
   instrument is *broken*, which is stronger evidence than having no control at
   all — that is the ``numba`` → 1 case, and it is reported as a failed control
   rather than quietly discarded.

The classification is a *table*, not an if-chain, because the boundary between
"the thing is not there" and "I could not reach the thing" is the entire
subject of this guard and it should be readable in one place.

Non-HTTP sources
----------------
Nothing here is HTTP-specific. :data:`DEFAULT_CODE_CLASSES` happens to be
written in HTTP status codes because the recorded failure was, but the codes are
strings and every one of them is an example exception rather than a rule:
GraphQL returns HTTP 200 with ``data: null``, a JSON API returns 200 with a body
field saying the record was not found, a filesystem returns ``ENOENT`` versus
``EACCES``, PyPI's simple index returns 404 but its JSON API can return 404 for
a *transient* reason. Pass ``code_classes`` to reclassify, and pass
``unknown_codes`` for anything the table does not name -- an unnamed code
defaults to ``UNKNOWN``, never to ``ABSENT``. The default direction of the
mistake must be the harmless one.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Sequence

from ..types import Certification, Finding, Severity, Status, Verdict

__all__ = [
    "EvidenceClass",
    "Observation",
    "EvidenceReport",
    "EvidenceGuard",
    "classify_codes",
    "DEFAULT_CODE_CLASSES",
    "UNKNOWN_CLASS_FAILURE",
    "UNSUPPORTED_ABSENCE_FAILURE",
    "CONTROL_FAILED_FAILURE",
    "UNCONTROLLED_NULL_FAILURE",
    "NO_OBSERVATIONS_FAILURE",
]

#: The classification table, as data rather than as control flow.
#:
#: The three classes are exhaustive and mutually exclusive:
#:
#: ``PRESENT``
#:     The instrument resolved the object and returned it. Only this class
#:     supports a positive claim.
#: ``ABSENT``
#:     The instrument resolved the *question* and the answer was "not there".
#:     Requires an explicit not-found signal. A server that never answered has
#:     not told you the object is missing; it has told you nothing.
#: ``UNKNOWN``
#:     Everything else, including every code not named below. Rate limits
#:     (429), outages (500/502/503/504), timeouts, connection resets and
#:     truncated responses are all ``UNKNOWN``: the object may or may not
#:     exist and the instrument did not find out.
#:
#: The HTTP codes are examples from the recorded failure, not a claim that the
#: source is HTTP. Reclassify with ``EvidenceGuard(code_classes=...)`` for
#: GraphQL (200 + null body), a JSON ``{"found": false}`` field, ``ENOENT``,
#: an empty-but-successful API response, and so on.
DEFAULT_CODE_CLASSES: Mapping[str, str] = {
    # -- present: the object was returned ----------------------------------
    "200": "PRESENT",
    "201": "PRESENT",
    "OK": "PRESENT",
    "FOUND": "PRESENT",
    "PRESENT": "PRESENT",
    "EXISTS": "PRESENT",
    "TRUE": "PRESENT",
    # -- absent: an explicit not-found signal ------------------------------
    "404": "ABSENT",  # Not Found -- the only HTTP code that means this
    "410": "ABSENT",  # Gone -- deliberately retained, still a resolution
    "NOT_FOUND": "ABSENT",
    "NOTFOUND": "ABSENT",
    "ENOENT": "ABSENT",
    "ABSENT": "ABSENT",
    "FALSE": "ABSENT",
    # -- unknown: the instrument did not resolve the question ---------------
    "0": "UNKNOWN",
    "EMPTY": "UNKNOWN",
    "NULL": "UNKNOWN",
    "NONE": "UNKNOWN",
    "UNKNOWN": "UNKNOWN",
    "TIMEOUT": "UNKNOWN",
    "ETIMEDOUT": "UNKNOWN",
    "ECONNRESET": "UNKNOWN",
    "ECONNREFUSED": "UNKNOWN",
    "EAI_AGAIN": "UNKNOWN",
    "ERR": "UNKNOWN",
    "ERROR": "UNKNOWN",
    "429": "UNKNOWN",  # Too Many Requests -- rate limited, not absent
    "500": "UNKNOWN",
    "502": "UNKNOWN",
    "503": "UNKNOWN",  # Service Unavailable -- the recorded failure
    "504": "UNKNOWN",
}

UNKNOWN_CLASS_FAILURE = "EVIDENCE_ABSENCE_FROM_NON_NOTFOUND"
UNSUPPORTED_ABSENCE_FAILURE = "EVIDENCE_ABSENCE_WITHOUT_SUPPORT"
CONTROL_FAILED_FAILURE = "EVIDENCE_CONTROL_FAILED"
UNCONTROLLED_NULL_FAILURE = "EVIDENCE_NULL_WITHOUT_POSITIVE_CONTROL"
NO_OBSERVATIONS_FAILURE = "EVIDENCE_NO_OBSERVATIONS"


class EvidenceClass(str, Enum):
    """What one observation actually established."""

    PRESENT = "PRESENT"
    """The object was returned. The only class that supports a positive claim."""

    ABSENT = "ABSENT"
    """An explicit not-found signal: the object was asked for and is not there."""

    UNKNOWN = "UNKNOWN"
    """Inconclusive. Includes every code the table does not name."""


@dataclass(frozen=True, slots=True)
class Observation:
    """One probe of one subject, with the code the instrument returned.

    ``code`` is stored as a string because the codes that matter here are
    heterogeneous -- ``404``, ``"null"``, ``"ENOENT"``, ``{"found": false}`` --
    and normalising them to integers would silently drop the ones that are not
    numbers, which is precisely the failure mode this guard exists for.
    """

    subject: str
    code: str
    note: str = ""

    def __post_init__(self) -> None:
        if not self.subject:
            raise ValueError("Observation.subject must be a non-empty identifier")
        if self.code is None:
            raise ValueError("Observation.code must be supplied; a missing code is "
                             "UNKNOWN, not ABSENT -- write 'UNKNOWN' if unsure")

    def as_dict(self) -> dict[str, str]:
        """JSON-serialisable view."""
        return {"subject": self.subject, "code": self.code, "note": self.note}


@dataclass(frozen=True, slots=True)
class EvidenceReport:
    """Outcome of the negative-evidence provenance check."""

    n_observations: int
    n_present: int
    n_absent: int
    n_unknown: int
    absent_codes: tuple[str, ...]
    unknown_codes: tuple[str, ...]
    controlled: bool
    control_subject: str | None
    findings: tuple[Finding, ...]

    @property
    def conclusive_fraction(self) -> float:
        """Share of observations the instrument actually resolved.

        ``PRESENT`` or ``ABSENT`` both count: the instrument answered. A report
        where most observations are ``UNKNOWN`` says almost nothing, however
        clean the rest of it looks, and this number is the reader's only warning
        of that.
        """
        if self.n_observations == 0:
            return 0.0
        return (self.n_present + self.n_absent) / self.n_observations

    @property
    def sound(self) -> bool:
        """True when no blocking finding was raised."""
        return not any(f.severity is Severity.BLOCKING for f in self.findings)

    @property
    def verdict(self) -> Verdict:
        """``REFUSED`` when absence was inferred from an unclean observation.

        ``REFUSED`` rather than ``SUSPECT`` on purpose. A null claim that rests
        on an infrastructure failure is not a weak claim, it is a *wrong* one:
        the recorded failure named five packages as missing that were not
        missing, and no amount of hedging makes that number usable.
        """
        return Verdict.CERTIFIED if self.sound else Verdict.REFUSED

    def certify(self) -> Certification:
        """Produce the :class:`Certification` for this report."""
        reasons = tuple(f.message for f in self.findings if f.status is Status.FAIL)
        return Certification(
            verdict=self.verdict,
            reasons=reasons,
            provenance=("evidence",),
            findings=self.findings,
        )

    def as_dict(self) -> dict[str, object]:
        """JSON-serialisable view."""
        return {
            "n_observations": self.n_observations,
            "n_present": self.n_present,
            "n_absent": self.n_absent,
            "n_unknown": self.n_unknown,
            "conclusive_fraction": round(self.conclusive_fraction, 6),
            "absent_codes": list(self.absent_codes),
            "unknown_codes": list(self.unknown_codes),
            "controlled": self.controlled,
            "control_subject": self.control_subject,
            "sound": self.sound,
            "verdict": self.verdict.value,
            "findings": [f.as_dict() for f in self.findings],
        }


class EvidenceGuard:
    """Validate the provenance of negative evidence.

    Parameters
    ----------
    code_classes:
        Override or extend :data:`DEFAULT_CODE_CLASSES`. Merged over the
        defaults, so naming one new code does not silently unclassify the rest.
        Use this for a non-HTTP source: ``{"found_false": "ABSENT"}`` for a JSON
        body field, ``{"GRAPHQL_NULL": "UNKNOWN"}`` for a 200-with-null.
    unknown_codes:
        Codes that must be ``UNKNOWN`` regardless of the table. This is the
        blunt instrument for a caller who knows a source lies about its codes
        (an API that returns 404 for transient errors, say). Membership here
        beats any table entry.
    negative_claim:
        Optional. Set it when the caller is asserting "nothing was found" --
        the guard then checks the assertion against the observations rather than
        only checking the observations against each other. This is the switch
        that turns the Sourcegraph failure (a null asserted with nothing behind
        it) into a blocking finding.
    known_positive_code:
        The code a *working* instrument returns for an object it did find.
        Default ``"200"``. A control observation must carry it — enforced, not
        merely recorded: a control carrying anything else is reported as a
        failed control, which is a stronger statement than an absent one.
    min_conclusive_fraction:
        If fewer than this share of observations are conclusive, warn. Not a
        failure: an honest report of "I could not reach the API" is a valid
        report, it is just not evidence.
    """

    name = "evidence"

    def __init__(
        self,
        *,
        code_classes: Mapping[str, str] | None = None,
        unknown_codes: Sequence[str] = (),
        negative_claim: str | None = None,
        known_positive_code: str = "200",
        min_conclusive_fraction: float = 0.5,
    ) -> None:
        if not 0.0 <= min_conclusive_fraction <= 1.0:
            raise ValueError(
                f"min_conclusive_fraction must be in [0, 1], got {min_conclusive_fraction}"
            )
        merged: dict[str, str] = dict(DEFAULT_CODE_CLASSES)
        if code_classes:
            merged.update({str(k).upper(): str(v).upper() for k, v in code_classes.items()})
        self.code_classes: Mapping[str, str] = merged
        self.unknown_codes = tuple(str(c).upper() for c in unknown_codes)
        self.negative_claim = negative_claim
        self.known_positive_code = known_positive_code
        self.min_conclusive_fraction = min_conclusive_fraction

    # ------------------------------------------------------------------
    # classification
    # ------------------------------------------------------------------

    def classify(self, code: str) -> EvidenceClass:
        """Map one status/outcome code to one of the three evidence classes.

        Unnamed codes are ``UNKNOWN``. That default is the guard's whole
        asymmetry: a code nobody thought about must never be read as a finding
        of absence, because the cost of the two mistakes is not symmetric.
        Calling a present object unknown costs you a research lead; calling an
        unreachable object absent costs you a false conclusion.
        """
        key = str(code).strip().upper()
        if key in self.unknown_codes:
            return EvidenceClass.UNKNOWN
        raw = self.code_classes.get(key)
        if raw is None:
            return EvidenceClass.UNKNOWN
        try:
            return EvidenceClass(str(raw).upper())
        except ValueError:
            return EvidenceClass.UNKNOWN

    # ------------------------------------------------------------------
    # evaluation
    # ------------------------------------------------------------------

    def is_known_positive(self, code: str) -> bool:
        """True when ``code`` is a *success* code for this instrument.

        A positive control is only a control when it comes back with the code a
        working instrument returns for something it found. ``known_positive_code``
        is that code, and it is enforced rather than merely recorded: a control
        observation carrying anything else is reported as a **failed control**,
        which is a stronger statement than an absent one. A check whose
        constraint is never read is not a check, and a docstring promising one
        is worse than either.
        """
        return self.classify(code) is EvidenceClass.PRESENT and (
            code.strip().upper() == self.known_positive_code.strip().upper()
        )

    def run(
        self,
        observations: Sequence[Observation],
        *,
        controls: Sequence[Observation] = (),
        claimed_absent: Sequence[str] | None = None,
    ) -> EvidenceReport:
        """Classify every observation and refuse a null built on an error.

        ``controls`` are observations of a **known-positive** input -- an object
        the caller has already verified exists. They are the only thing that
        can demonstrate the instrument works. A null result with no control is
        refused when ``negative_claim`` is set, and warned about otherwise,
        because "I found nothing and I cannot show my tool finds anything" is
        the Sourcegraph failure verbatim.
        """
        findings: list[Finding] = []
        if not observations:
            # Controls alone are not a scan. A control demonstrates the
            # instrument works; it says nothing about the subjects, and a report
            # with no subjects has established nothing. This is the same rule
            # the aggregator applies to a skipped guard: "nothing to check" is
            # not "checked and clean".
            findings.append(
                Finding(
                    code=NO_OBSERVATIONS_FAILURE,
                    message=(
                        "no observations were supplied"
                        + (
                            f" ({len(controls)} control(s) were, but a control "
                            "demonstrates the instrument works, not that any "
                            "subject was examined)"
                            if controls
                            else ""
                        )
                        + ", so nothing was established; an empty scan is not a "
                        "clean scan"
                    ),
                    status=Status.ERROR,
                    severity=Severity.BLOCKING,
                    detail={"n_observations": 0, "n_controls": len(controls)},
                )
            )
            return EvidenceReport(
                n_observations=0,
                n_present=0,
                n_absent=0,
                n_unknown=0,
                absent_codes=(),
                unknown_codes=(),
                controlled=False,
                control_subject=None,
                findings=tuple(findings),
            )

        classified = tuple((o, self.classify(o.code)) for o in observations)
        ctrl_classified = tuple((o, self.classify(o.code)) for o in controls)

        n_present = sum(1 for _, c in classified if c is EvidenceClass.PRESENT)
        n_absent = sum(1 for _, c in classified if c is EvidenceClass.ABSENT)
        n_unknown = sum(1 for _, c in classified if c is EvidenceClass.UNKNOWN)
        absent_codes = tuple(sorted({o.code for o, c in classified if c is EvidenceClass.ABSENT}))
        unknown_codes = tuple(sorted({o.code for o, c in classified if c is EvidenceClass.UNKNOWN}))

        # -- (1) absence claimed from an unclean observation ---------------
        # Two ways this appears, and both are the same defect:
        #   a. the code says UNKNOWN, yet the subject was declared absent;
        #   b. the caller asserted a blanket negative claim and the set it
        #      rests on contains UNKNOWN observations.
        declared = set(claimed_absent or ())
        if self.negative_claim is not None and not declared:
            declared = {o.subject for o, c in classified if c is not EvidenceClass.PRESENT}

        misread = [
            o
            for o, c in classified
            if c is EvidenceClass.UNKNOWN and o.subject in declared
        ]
        if misread:
            findings.append(
                Finding(
                    code=UNKNOWN_CLASS_FAILURE,
                    message=(
                        f"absence was inferred from {len(misread)} observation(s) that "
                        "did not resolve the question: "
                        + ", ".join(f"{o.subject}={o.code}" for o in misread[:6])
                        + (f" (+{len(misread) - 6} more)" if len(misread) > 6 else "")
                        + ". A 429/503/timeout answers 'I could not reach it', not "
                        "'it is not there'; these subjects must be UNKNOWN, not ABSENT"
                    ),
                    status=Status.FAIL,
                    severity=Severity.BLOCKING,
                    detail={
                        "n_misread": len(misread),
                        "subjects": ", ".join(o.subject for o in misread),
                        "codes": ", ".join(sorted({o.code for o in misread})),
                    },
                )
            )

        # -- (1b) an absence claim with no observation behind it -----------
        # The mirror of the check above, and the other half of the same
        # principle: an absence is a *claim* that requires an observation. A
        # subject declared absent with nothing behind it, or with a PRESENT
        # observation contradicting it, is exactly the unsupported negative the
        # module exists to refuse -- and checking only the UNKNOWN direction
        # would have left it unreported.
        observed = {o.subject: c for o, c in classified}
        unsupported = sorted(
            s
            for s in declared
            if s not in observed or observed[s] is not EvidenceClass.ABSENT
        )
        if unsupported:
            contradicted = [s for s in unsupported if observed.get(s) is EvidenceClass.PRESENT]
            findings.append(
                Finding(
                    code=UNSUPPORTED_ABSENCE_FAILURE,
                    message=(
                        f"{len(unsupported)} subject(s) were declared absent with no "
                        "observation supporting it: "
                        + ", ".join(unsupported[:6])
                        + (f" (+{len(unsupported) - 6} more)" if len(unsupported) > 6 else "")
                        + (
                            f"; {len(contradicted)} of them were observed PRESENT"
                            if contradicted
                            else "; no observation of them was supplied at all"
                        )
                    ),
                    status=Status.FAIL,
                    severity=Severity.BLOCKING,
                    detail={
                        "n_unsupported": len(unsupported),
                        "subjects": ", ".join(unsupported),
                        "contradicted_by_present": ", ".join(contradicted),
                    },
                )
            )

        # -- (2) the control instrument -------------------------------------
        # A control is a probe of a **known-positive** input. Two things can
        # happen to it and both are findings:
        #   * it returned PRESENT  -> the instrument demonstrably works;
        #   * it returned anything else -> the instrument demonstrably does
        #     NOT work on an input known to be there. That is *stronger*
        #     evidence of a broken instrument than having no control at all,
        #     and it must be reported rather than silently discarded. This is
        #     the `numba` -> 1 case: a control that fails is the whole finding.
        control_present = [
            o
            for o, c in ctrl_classified
            if c is EvidenceClass.PRESENT and self.is_known_positive(o.code)
        ]
        control_failed = [
            o
            for o, c in ctrl_classified
            if not (c is EvidenceClass.PRESENT and self.is_known_positive(o.code))
        ]
        controlled = bool(control_present)
        null_result = n_present == 0

        if control_failed:
            findings.append(
                Finding(
                    code=CONTROL_FAILED_FAILURE,
                    message=(
                        "the positive control failed: "
                        + ", ".join(f"{o.subject}={o.code}" for o in control_failed[:6])
                        + " on an input known to be present. A control that cannot "
                        "return a thing on a known-positive input proves the "
                        "instrument is broken, so every null result in this set is "
                        "an instrument failure rather than a finding"
                    ),
                    status=Status.FAIL,
                    severity=Severity.BLOCKING,
                    detail={
                        "n_controls": len(controls),
                        "n_control_failed": len(control_failed),
                        "subjects": ", ".join(o.subject for o in control_failed),
                        "codes": ", ".join(sorted({o.code for o in control_failed})),
                    },
                )
            )

        if null_result and not controlled and not control_failed:
            # Nothing anywhere returned a thing, and no control was attempted.
            # Either the world is empty -- which no scan can establish -- or the
            # instrument is broken, and this run cannot tell which. That
            # distinction is not available, so the null cannot stand.
            #
            # BLOCKING regardless of whether the caller *asserted* a negative
            # claim. An earlier draft only failed when a claim was asserted and
            # merely warned otherwise, which meant the default configuration
            # CERTIFIED a set where nothing had been resolved -- the recorded
            # failure, produced by the defaults. "I have not finished looking"
            # is a reason not to draw a conclusion, not a reason to certify one.
            findings.append(
                Finding(
                    code=UNCONTROLLED_NULL_FAILURE,
                    message=(
                        "the instrument returned a null result everywhere "
                        f"({n_unknown} UNKNOWN, {n_absent} ABSENT, 0 PRESENT) and no "
                        "positive control demonstrates it can return anything; a "
                        "control query on a known-positive input is required before "
                        "any zero in this set may be read as 'not there'"
                    ),
                    status=Status.FAIL,
                    severity=Severity.BLOCKING,
                    detail={
                        "n_present": n_present,
                        "n_unknown": n_unknown,
                        "n_absent": n_absent,
                        "n_controls": len(controls),
                    },
                )
            )

        # -- (3) conclusiveness --------------------------------------------
        # Guarded: `observations` can be empty while `controls` is not, and the
        # class counts below would divide by zero. The report property handles
        # the empty case already; this call site must agree with it.
        conclusive = (
            0.0
            if not observations
            else (n_present + n_absent) / len(observations)
        )
        if observations and conclusive < self.min_conclusive_fraction and not any(
            f.code == UNKNOWN_CLASS_FAILURE for f in findings
        ):
            findings.append(
                Finding(
                    code=UNKNOWN_CLASS_FAILURE,
                    message=(
                        f"only {conclusive:.0%} of observations are conclusive "
                        f"({n_present} PRESENT, {n_absent} ABSENT, {n_unknown} UNKNOWN); "
                        "most of this evidence set was never resolved, so it cannot "
                        "carry a claim in either direction"
                    ),
                    status=Status.WARN,
                    severity=Severity.INFO,
                    detail={
                        "conclusive_fraction": round(conclusive, 6),
                        "threshold": self.min_conclusive_fraction,
                    },
                )
            )

        return EvidenceReport(
            n_observations=len(observations),
            n_present=n_present,
            n_absent=n_absent,
            n_unknown=n_unknown,
            absent_codes=absent_codes,
            unknown_codes=unknown_codes,
            controlled=controlled,
            control_subject=control_present[0].subject if control_present else None,
            findings=tuple(findings),
        )

    def check(
        self,
        observations: Sequence[Observation],
        *,
        controls: Sequence[Observation] = (),
        claimed_absent: Sequence[str] | None = None,
    ) -> EvidenceReport:
        """Alias for :meth:`run`, matching the other guards' entry point."""
        return self.run(observations, controls=controls, claimed_absent=claimed_absent)


def classify_codes(
    observations: Sequence[Observation],
    *,
    code_classes: Mapping[str, str] | None = None,
    unknown_codes: Sequence[str] = (),
) -> dict[str, tuple[Observation, ...]]:
    """Group observations by class, for display or triage.

    A thin helper so a caller can print "these five were never resolved" without
    re-implementing the table -- the table is the guard's interface, not a
    private detail.
    """
    guard = EvidenceGuard(code_classes=code_classes, unknown_codes=unknown_codes)
    groups: dict[str, list[Observation]] = {c.value: [] for c in EvidenceClass}
    for o in observations:
        groups[guard.classify(o.code).value].append(o)
    return {k: tuple(v) for k, v in groups.items()}
