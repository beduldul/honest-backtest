"""Static guard-bypass detection.

The design goal of this library is that a user *cannot accidentally* skip a
guard. Types get us most of the way: you cannot subtract an ``int`` from a
``Certification``, so a result that arrived as a ``Certification`` is either
certified or it raised.

What types cannot stop is someone manufacturing a verdict by hand::

    Certification(verdict=Verdict.CERTIFIED)   # no guard ever ran

That is not an accident, but it is easy to *drift* into -- a helper returns a
bool, someone wraps it, and three refactors later the guards are gone while the
word CERTIFIED is still printed. :func:`audit_result` closes that hole by
parsing the caller's source and asserting that no ``Certification`` was
constructed anywhere except by :func:`honest_backtest.audit.audit_result`.

Usage::

    report = audit_result(result, assert_no_unguarded_construction=True)

The flag defaults to ``False`` so the audit is never a surprise, but every
example and the CLI pass ``True``. The exception message names the file, line,
and the offending expression.

This is a lint, not a sandbox. It is not trying to defeat a determined attacker
who writes ``exec``; it is trying to defeat a future version of *you*.
"""

from __future__ import annotations

import ast
import inspect
import os
from dataclasses import dataclass
from typing import Iterable, Sequence

from .types import GuardBypassError

__all__ = ["Bypass", "scan_source", "scan_callers", "assert_no_bypass", "audit_result"]

_ALLOWED_CALL_FILES = (
    # The places a Certification is *supposed* to be born:
    #   audit.py  -- the sanctioned factory
    #   types.py  -- the class definition itself
    #   report.py -- the aggregator, which is the sanctioned composite factory
    os.path.join("honest_backtest", "audit.py"),
    os.path.join("honest_backtest", "types.py"),
    os.path.join("honest_backtest", "report.py"),
)

_CONSTRUCTED = {"Certification"}


@dataclass(frozen=True, slots=True)
class Bypass:
    """One suspicious construction site."""

    filename: str
    lineno: int
    expression: str
    reason: str

    def render(self) -> str:
        return f"{self.filename}:{self.lineno}: {self.reason}: {self.expression}"


def _is_certification_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name) and func.id in _CONSTRUCTED:
        return True
    if isinstance(func, ast.Attribute) and func.attr in _CONSTRUCTED:
        return True
    return False


def _expression_text(source: str, node: ast.AST) -> str:
    try:
        seg = ast.get_source_segment(source, node)
    except Exception:  # pragma: no cover - defensive
        seg = None
    if seg:
        return " ".join(seg.split())
    return ast.dump(node)[:80]


def scan_source(source: str, filename: str = "<string>") -> tuple[Bypass, ...]:
    """Find unguarded ``Certification(...)`` constructions in ``source``.

    ``CERTIFIED`` verdict *literals* are reported too when they appear as an
    argument to a direct ``Certification(...)`` call, since that is the
    hand-forged-verdict pattern.
    """
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as exc:  # pragma: no cover - defensive
        raise GuardBypassError(f"cannot parse {filename}: {exc}") from exc

    found: list[Bypass] = []
    for node in ast.walk(tree):
        if _is_certification_call(node):
            expr = _expression_text(source, node)
            reason = "Certification constructed outside audit_result()"
            if "CERTIFIED" in expr:
                reason = "hand-forged CERTIFIED verdict"
            found.append(
                Bypass(
                    filename=filename,
                    lineno=getattr(node, "lineno", 0),
                    expression=expr,
                    reason=reason,
                )
            )
    return tuple(sorted(found, key=lambda b: (b.filename, b.lineno)))


def _caller_files(skip: Iterable[str]) -> tuple[str, ...]:
    """Walk the stack and collect real source files, nearest first."""
    files: list[str] = []
    frame = inspect.currentframe()
    skip_set = set(skip)
    try:
        f = frame
        while f is not None:
            name = f.f_code.co_filename
            if name not in skip_set and os.path.isfile(name) and name not in files:
                files.append(os.path.abspath(name))
            f = f.f_back
    finally:
        del frame
    return tuple(files)


def scan_callers(
    *, max_frames: int = 12, skip: Sequence[str] = ()
) -> tuple[Bypass, ...]:
    """Scan the caller's stack (excluding this library) for bypasses."""
    here = os.path.abspath(__file__)
    files = _caller_files(skip=(here, *skip))[:max_frames]
    out: list[Bypass] = []
    for path in files:
        if any(path.endswith(allowed) for allowed in _ALLOWED_CALL_FILES):
            continue
        try:
            with open(path, "r", encoding="utf-8") as fh:
                source = fh.read()
        except (OSError, UnicodeDecodeError):  # pragma: no cover - defensive
            continue
        out.extend(scan_source(source, filename=path))
    return tuple(out)


def assert_no_bypass(*, max_frames: int = 12, skip: Sequence[str] = ()) -> None:
    """Raise :class:`GuardBypassError` if a caller manufactures a verdict."""
    bypasses = scan_callers(max_frames=max_frames, skip=skip)
    if bypasses:
        detail = "\n".join("  " + b.render() for b in bypasses)
        raise GuardBypassError(
            "unguarded Certification construction detected in caller source:\n"
            f"{detail}\n"
            "Build the verdict with honest_backtest.audit.audit_result() instead."
        )


def audit_result(
    result: object,
    *,
    assert_no_unguarded_construction: bool = False,
    guards: Sequence[object] | None = None,
) -> object:
    """Run the full guard pipeline on ``result`` and return an ``HonestyReport``.

    This is the sanctioned entry point -- the *only* place outside
    :mod:`honest_backtest.report` where a composite verdict is assembled. It is
    a thin, explicitly-named wrapper over
    :meth:`honest_backtest.report.HonestyReport.run` so that:

    * the call site reads as an auditable act ("this verdict was audited")
      rather than as an ordinary function call, and
    * ``assert_no_unguarded_construction=True`` has an obvious home at the
      place a caller is already declaring intent.

    ``result`` is an :class:`honest_backtest.report.ResultSet`. The parameter is
    typed loosely here to avoid a circular import between :mod:`audit` and
    :mod:`report`; the runtime check below makes the contract explicit.
    """
    from .report import HonestyReport, ResultSet

    if not isinstance(result, ResultSet):
        raise TypeError(
            f"audit_result() expects a ResultSet, got {type(result).__name__}"
        )
    report = HonestyReport.run(
        result,
        guards=guards,
        config=None,
    )
    if assert_no_unguarded_construction:
        # Re-audit *after* the report exists, so a caller that forged a verdict
        # anywhere on the stack is caught at the moment of certification.
        assert_no_bypass(skip=(os.path.abspath(__file__),))
    return report
