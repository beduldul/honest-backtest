"""Core shared types.

Everything in this module is stdlib-only, immutable, and fully typed.

The public surface is deliberately narrow: a verdict enum, a status enum for
individual guards, a finding dataclass, and the composite result type that the
AST auditor inspects. Guard modules define their own report dataclasses on top
of these primitives.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterator, Sequence

__all__ = [
    "Verdict",
    "Status",
    "Severity",
    "Finding",
    "Certification",
    "HonestyError",
    "RefusedError",
    "GuardBypassError",
]


class Verdict(str, Enum):
    """The single top-level verdict for a result set.

    The ordering in :data:`Verdict.RANK` is the ordering of permissiveness.
    A composite report always takes the *least* permissive verdict of its
    constituent guards, so a single hard failure can never be averaged away by
    a pile of passes.

    ``str`` mixin so the value round-trips through JSON and the CLI cleanly.
    """

    CERTIFIED = "CERTIFIED"
    SUSPECT = "SUSPECT"
    REFUSED = "REFUSED"

    @property
    def rank(self) -> int:
        """Permissiveness rank; lower is stricter."""
        return {"CERTIFIED": 0, "SUSPECT": 1, "REFUSED": 2}[self.value]

    @staticmethod
    def strictest(verdicts: Sequence["Verdict"]) -> "Verdict":
        """Return the least permissive verdict in ``verdicts``.

        An empty sequence is ``CERTIFIED`` by convention: nothing objected.
        """
        if not verdicts:
            return Verdict.CERTIFIED
        return max(verdicts, key=lambda v: v.rank)


class Status(str, Enum):
    """Outcome of a single guard evaluation."""

    PASS = "PASS"
    """The guard ran and the input cleared it."""

    WARN = "WARN"
    """The guard ran and found something worth reporting, but not fatal.

    Note that ``WARN`` never yields a ``CERTIFIED`` verdict for the composite
    report: it yields ``SUSPECT``. There is no "certified with warnings".
    """

    FAIL = "FAIL"
    """The guard ran and the input violates the guard's contract."""

    ERROR = "ERROR"
    """The guard could not be evaluated (bad input, insufficient data).

    Treated as ``FAIL`` for verdict purposes. A guard that cannot run is not a
    guard that passed.
    """


class Severity(str, Enum):
    """How much a finding blocks certification."""

    INFO = "INFO"
    BLOCKING = "BLOCKING"


class HonestyError(Exception):
    """Base class for all library errors."""


class RefusedError(HonestyError):
    """Raised when a consumer tries to use a non-certified result.

    This is the enforcement arm of the library. ``Certification.require()``
    raises this; so does ``HonestyReport.require_certified()``.
    """

    def __init__(self, verdict: Verdict, reasons: Sequence[str]) -> None:
        self.verdict = verdict
        self.reasons = tuple(reasons)
        detail = "; ".join(self.reasons) if self.reasons else "no detail recorded"
        super().__init__(f"result is {verdict.value}, not CERTIFIED: {detail}")


class GuardBypassError(HonestyError):
    """Raised when code attempts to sidestep the guard pipeline.

    Two situations raise this:

    * calling ``Certification`` helpers that assert the value was produced by
      an audit when it was not (``.assume()`` with a non-certified verdict);
    * the ``assert_no_unguarded_construction=True`` audit finding a
      ``Certification(...)`` / ``Verdict.CERTIFIED`` literal somewhere it was
      not produced by :func:`honest_backtest.audit.audit_result`.
    """


@dataclass(frozen=True, slots=True)
class Finding:
    """One thing a guard has to say.

    ``code`` is a stable machine-readable identifier (``LOOKAHEAD_DECAY``);
    ``message`` is the human sentence; ``detail`` carries the measured numbers
    so a caller can reproduce the judgement without re-running the guard.
    """

    code: str
    message: str
    status: Status
    severity: Severity = Severity.BLOCKING
    detail: dict[str, float | int | str | bool | None] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.code:
            raise ValueError("Finding.code must be a non-empty identifier")
        if not self.message:
            raise ValueError("Finding.message must be non-empty")

    def as_dict(self) -> dict[str, object]:
        """JSON-serialisable view."""
        return {
            "code": self.code,
            "message": self.message,
            "status": self.status.value,
            "severity": self.severity.value,
            "detail": dict(self.detail),
        }


@dataclass(frozen=True, slots=True)
class Certification:
    """A verdict that carries its own provenance.

    The type is the enforcement mechanism. Guards hand out ``Certification``
    objects, not booleans, so a caller cannot lose the verdict by accident:
    the only way to obtain one is through a guard's ``.certify()`` or through
    :func:`honest_backtest.audit.audit_result`.

    ``provenance`` records which guards actually ran. Consumers that require a
    specific guard to have been applied call :meth:`require_guard`.
    """

    verdict: Verdict
    reasons: tuple[str, ...] = ()
    provenance: tuple[str, ...] = ()
    findings: tuple[Finding, ...] = ()

    @property
    def certified(self) -> bool:
        """True only for a clean ``CERTIFIED``."""
        return self.verdict is Verdict.CERTIFIED

    @property
    def usable(self) -> bool:
        """True when nothing blocking was found (``CERTIFIED`` or ``SUSPECT``).

        Read the name literally. A ``SUSPECT`` result is still *usable* in the
        sense that it is reportable as an explicitly-labelled caveat. It is
        never reportable as a finding.
        """
        return self.verdict is not Verdict.REFUSED

    def blocking_reasons(self) -> tuple[str, ...]:
        """Reasons attached to blocking findings, in order."""
        blocking = [
            f.message for f in self.findings if f.severity is Severity.BLOCKING
        ]
        return tuple(blocking) if blocking else self.reasons

    def require(self) -> "Certification":
        """Return self if ``CERTIFIED``; raise :class:`RefusedError` otherwise."""
        if not self.certified:
            raise RefusedError(self.verdict, self.blocking_reasons())
        return self

    def require_guard(self, *guard_names: str) -> "Certification":
        """Assert the named guards ran before returning self.

        This is how a downstream consumer says "I will only trust a number
        that has been through the look-ahead diagnostic".
        """
        missing = tuple(g for g in guard_names if g not in self.provenance)
        if missing:
            raise GuardBypassError(
                "certification is missing required guard(s): " + ", ".join(missing)
            )
        return self

    def __iter__(self) -> Iterator[str]:
        """Iterate reasons, so ``list(cert)`` reads naturally."""
        return iter(self.reasons)

    def as_dict(self) -> dict[str, object]:
        """JSON-serialisable view."""
        return {
            "verdict": self.verdict.value,
            "certified": self.certified,
            "reasons": list(self.reasons),
            "provenance": list(self.provenance),
            "findings": [f.as_dict() for f in self.findings],
        }
