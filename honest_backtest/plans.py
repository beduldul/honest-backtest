"""Parsing for declarative evaluation-window plans.

A window plan is how a user states *when* they measured. It is deliberately
boring and text-friendly so it can live in a config file, a CLI argument, or a
test fixture without a schema negotiation::

    "2024-01-01..2024-02-01, 2024-02-01..2024-03-01"     # explicit ranges
    "2024-01-01..2024-03-01 x4"                           # 4 anchored windows

Dates are ISO-8601 and inclusive of the start, exclusive of the end (matching
how a bar labelled ``t0`` covers ``[t0, t0 + step)``; see
:mod:`honest_backtest.guards.series`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from .types import HonestyError

__all__ = ["Window", "parse_window", "parse_plan", "days_between"]


@dataclass(frozen=True, slots=True, order=True)
class Window:
    """A half-open date interval ``[start, end)`` with a stable label."""

    start: date
    end: date
    label: str = ""

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise HonestyError(
                f"window end {self.end} precedes start {self.start}"
            )

    @property
    def days(self) -> int:
        """Length in days."""
        return (self.end - self.start).days

    @property
    def key(self) -> tuple[date, date]:
        """Identity of the interval, independent of its label."""
        return (self.start, self.end)

    def overlaps(self, other: "Window") -> bool:
        """True when the two half-open intervals share any time."""
        return self.start < other.end and other.start < self.end

    def __str__(self) -> str:
        return f"{self.start.isoformat()}..{self.end.isoformat()}"


def _parse_date(text: str) -> date:
    try:
        return date.fromisoformat(text.strip())
    except ValueError as exc:
        raise HonestyError(f"not an ISO-8601 date: {text!r}") from exc


def days_between(a: date, b: date) -> int:
    """Calendar days from ``a`` to ``b``; negative when ``b`` is earlier."""
    return (b - a).days


def parse_window(text: str, *, label: str = "") -> Window:
    """Parse one ``start..end`` range."""
    text = text.strip()
    if ".." not in text:
        raise HonestyError(
            f"window {text!r} is not a 'start..end' range (ISO-8601 dates)"
        )
    left, right = text.split("..", 1)
    start, end = _parse_date(left), _parse_date(right)
    return Window(start=start, end=end, label=label or f"{start.isoformat()}..{end.isoformat()}")


def parse_plan(spec: str) -> tuple[Window, ...]:
    """Parse a comma-separated plan.

    Supports the ``<start>..<end> xN`` shorthand, which repeats the *same*
    interval ``N`` times with distinct labels. That looks useless and is in
    fact the exact shape of the failure this library was built after: a
    walk-forward that reported "4 splits" which were four views of one window.
    Rather than guess what the user meant, the parser records what they said
    and :mod:`honest_backtest.guards.windows` reports the independence count.
    """
    if not spec or not spec.strip():
        raise HonestyError("empty window plan")
    out: list[Window] = []
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        repeat = 1
        if " x" in chunk:
            chunk, _, count = chunk.rpartition(" x")
            try:
                repeat = int(count)
            except ValueError as exc:
                raise HonestyError(f"bad repeat count in {chunk!r} x{count!r}") from exc
            if repeat < 1:
                raise HonestyError(f"repeat count must be >= 1, got {repeat}")
        base = parse_window(chunk)
        for i in range(repeat):
            suffix = f"#{i + 1}" if repeat > 1 else ""
            out.append(
                Window(
                    start=base.start,
                    end=base.end,
                    label=f"{base.start.isoformat()}..{base.end.isoformat()}{suffix}",
                )
            )
    if not out:
        raise HonestyError(f"plan {spec!r} produced no windows")
    return tuple(out)


def contiguous_windows(
    start: date, end: date, *, length_days: int
) -> tuple[Window, ...]:
    """Tile ``[start, end)`` into back-to-back ``length_days`` windows.

    Any remainder shorter than ``length_days`` is dropped rather than kept as a
    stub, because a 4-day tail window is not comparable to its 30-day siblings
    and silently mixing them corrupts every downstream count.
    """
    if length_days <= 0:
        raise HonestyError(f"length_days must be positive, got {length_days}")
    out: list[Window] = []
    cursor = start
    while cursor + timedelta(days=length_days) <= end:
        nxt = cursor + timedelta(days=length_days)
        out.append(Window(start=cursor, end=nxt, label=f"{cursor.isoformat()}..{nxt.isoformat()}"))
        cursor = nxt
    return tuple(out)
