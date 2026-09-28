"""Guard 6 -- structural data traps.

THE MEASURED FAILURES
---------------------
**(a) Spliced metrics.** A series table stitched two different measurements
end-to-end: a 365-day trailing-cumulative metric and a 30-day rolling-window
metric. Both were named "return". Differencing across the splice fabricated a
**-24,046 pp** "daily return". The arithmetic was correct; the input was two
different quantities wearing one column name.

**(b) Zero-padding before inception.** Series were padded with zeros back to a
common start date. A portfolio 11 days old returned 365 points. Treating the
padding as history fabricates a track record out of nothing -- and the padding
is *zero*, so it drags any measured average toward zero, which is a flattering
direction for a long-only book.

**(c) Left-edge timestamp bug.** A 15-minute bar labelled ``t0`` spans
``[t0, t0 + 15m)``. Code that assumed a forward bar starts at ``t0 + 1m``
produced a **185 bps** error -- not a rounding difference, a different bar.

THE GUARDS
----------
:func:`detect_splice` (a)
:func:`truncate_leading_padding` (b)
:func:`check_contiguous` (c1)
:func:`left_edge_bar_start` (c2) and :func:`forward_bar_offset`

The splice detector is the interesting one. It cannot know that a column holds
two metrics -- nothing in the data says so. What it can do is notice a *level
discontinuity inconsistent with the local variation*: a single difference that
is enormous relative to the dispersion of the differences around it. On the
fixture the fake daily return is -24,046 pp against neighbouring differences of
order 0.1-2 pp, which is not an outlier, it is a different population.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Sequence

from .._numeric import median, percentile, stdev
from ..types import Certification, Finding, Severity, Status, Verdict

__all__ = [
    "SpliceReport",
    "SeriesReport",
    "detect_splice",
    "truncate_leading_padding",
    "check_contiguous",
    "left_edge_bar_start",
    "left_edge_window",
    "forward_bar_offset",
    "price_error_bps",
    "SeriesGuard",
]

SPLICE_FAILURE = "SERIES_SPLICE_DETECTED"
PADDING_FAILURE = "SERIES_LEADING_PADDING"
INDEX_FAILURE = "SERIES_INDEX_NOT_CONTIGUOUS"
INDEX_NOT_MONOTONIC = "SERIES_INDEX_NOT_MONOTONIC"
LEFT_EDGE_FAILURE = "SERIES_LEFT_EDGE_WINDOW"

@dataclass(frozen=True, slots=True)
class SpliceReport:
    """Result of the level-discontinuity scan."""

    detected: bool
    index: int | None
    jump: float | None
    local_scale: float | None
    ratio: float | None
    z_score: float | None
    threshold: float
    findings: tuple[Finding, ...]

    @property
    def verdict(self) -> Verdict:
        """``REFUSED`` when a splice is detected."""
        return Verdict.REFUSED if self.detected else Verdict.CERTIFIED

    def certify(self) -> Certification:
        """Produce the :class:`Certification` for this report."""
        reasons = tuple(f.message for f in self.findings if f.status is Status.FAIL)
        return Certification(
            verdict=self.verdict,
            reasons=reasons,
            provenance=("series",),
            findings=self.findings,
        )

    def as_dict(self) -> dict[str, object]:
        """JSON-serialisable view."""
        return {
            "detected": self.detected,
            "index": self.index,
            "jump": self.jump,
            "local_scale": self.local_scale,
            "ratio": self.ratio,
            "z_score": self.z_score,
            "threshold": self.threshold,
            "verdict": self.verdict.value,
            "findings": [f.as_dict() for f in self.findings],
        }


def detect_splice(
    values: Sequence[float],
    *,
    threshold: float = 25.0,
    min_points: int = 8,
    neighbourhood: int = 10,
    z_threshold: float = 25.0,
) -> SpliceReport:
    """Find a single level discontinuity inconsistent with local variation.

    Method: take first differences. Compute a robust local scale as the median
    absolute deviation of the differences (scaled by 1.4826 to be comparable to
    a standard deviation), then score every difference as
    ``|d| / local_scale``. Report the largest when it clears ``threshold``.

    Why a robust scale rather than a plain standard deviation: one -24,046 pp
    value inflates the standard deviation to the point where it stops being an
    outlier. The median absolute deviation is unmoved by it, which is the whole
    reason the -24,046 is visible at all.

    Why the *local* variation and not the global: a legitimately volatile series
    should not be flagged for being volatile. Comparing a jump to a window of
    ``neighbourhood`` surrounding differences asks the right question -- is this
    jump out of character *here*?

    Two tests are applied and either can fire, because they fail in different
    regimes. ``threshold`` compares the jump to the local p75 of non-zero
    differences and is the sensitive test. ``z_threshold`` compares it to the
    global robust scale and is the backstop for a jump sitting inside a
    uniformly quiet stretch, where no local comparison can see it.
    """
    n = len(values)
    if n < min_points:
        return SpliceReport(
            detected=False,
            index=None,
            jump=None,
            local_scale=None,
            ratio=None,
            z_score=None,
            threshold=threshold,
            findings=(
                Finding(
                    code=SPLICE_FAILURE,
                    message=(
                        f"splice scan not attempted: {n} point(s), need >= "
                        f"{min_points}"
                    ),
                    status=Status.WARN,
                    severity=Severity.INFO,
                    detail={"n": n, "min_points": min_points},
                ),
            ),
        )

    diffs = [values[i + 1] - values[i] for i in range(n - 1)]
    abs_diffs = [abs(d) for d in diffs]

    # Robust global scale: median absolute deviation of the differences.
    # Unmoved by a single enormous value, which is the whole point -- a plain
    # standard deviation is inflated by the very jump we are looking for.
    med_abs = median(abs_diffs)
    mad = median([abs(a - med_abs) for a in abs_diffs]) * 1.4826
    positive = sorted(a for a in abs_diffs if a > 0.0)

    # A series that is flat except for a handful of steps has no usable scale:
    # with the vast majority of differences equal to zero, the median, the MAD
    # and the standard deviation are all either zero or dominated by the steps
    # themselves. This is not a degenerate input to be skipped -- a flat series
    # with one or two large steps is the *clearest* possible splice, and
    # returning "cannot evaluate" would let the most obvious case through.
    #
    # The test is on the *share* of non-zero differences, not their count: a
    # series where fewer than a quarter of the steps move at all has no local
    # variation to compare a jump against, by construction.
    if positive and len(positive) <= max(2, (n - 1) // 4):
        moving = sorted(
            (i for i, a in enumerate(abs_diffs) if a > 0.0),
            key=lambda i: abs_diffs[i],
            reverse=True,
        )
        worst = moving[0]
        jump = diffs[worst]
        return SpliceReport(
            detected=True,
            index=worst,
            jump=jump,
            local_scale=0.0,
            ratio=math.inf if positive[-1] > 0.0 else 0.0,
            z_score=math.inf,
            threshold=threshold,
            findings=(
                Finding(
                    code=SPLICE_FAILURE,
                    message=(
                        f"level discontinuity at index {worst} -> {worst + 1}: only "
                        f"{len(positive)} of {n - 1} consecutive differences are "
                        f"non-zero, and the largest steps {jump:+,.1f}; a series "
                        "that is otherwise flat has no local variation to compare "
                        "against, and a flat level joined to a different one is two "
                        "measurements spliced end-to-end"
                    ),
                    status=Status.FAIL,
                    severity=Severity.BLOCKING,
                    detail={
                        "index": worst,
                        "jump": round(jump, 6),
                        "local_scale": 0.0,
                        "moving_steps": len(positive),
                        "n": n,
                    },
                ),
            ),
        )
    if not positive:
        return SpliceReport(
            detected=False,
            index=None,
            jump=None,
            local_scale=0.0,
            ratio=None,
            z_score=None,
            threshold=threshold,
            findings=(),
        )

    # Enough non-zero differences to have a scale: fall back to the spread of
    # the non-zero differences when the MAD is zero.
    fallback = stdev(positive) if len(positive) > 1 else positive[0]
    global_scale = mad if mad > 0.0 else fallback
    if global_scale <= 0.0:
        return SpliceReport(
            detected=False,
            index=None,
            jump=None,
            local_scale=0.0,
            ratio=None,
            z_score=None,
            threshold=threshold,
            findings=(),
        )

    worst_i = max(range(len(diffs)), key=lambda i: abs(diffs[i]))

    # Local scale: the *typical large* difference near the candidate, not the
    # median of all nearby differences. A series with long flat stretches
    # (constant levels, zero-volume bars) has a neighbourhood median of exactly
    # zero, which would make the ratio infinite for any jump at all -- and a
    # fallback to the global scale would then understate a genuine splice that
    # sits inside a quiet region. The 75th percentile of the non-zero
    # neighbouring differences answers the right question: how big does a step
    # get around here when it moves at all?
    lo = max(0, worst_i - neighbourhood)
    hi = min(len(diffs), worst_i + neighbourhood + 1)
    neighbours = [abs_diffs[i] for i in range(lo, hi) if i != worst_i]
    neighbours_nonzero = [a for a in neighbours if a > 0.0]
    if neighbours_nonzero:
        local_scale = percentile(neighbours_nonzero, 75.0)
    elif neighbours:
        local_scale = median(neighbours)
    else:
        local_scale = med_abs
    if local_scale <= 0.0:
        local_scale = global_scale

    jump = diffs[worst_i]
    ratio = abs(jump) / local_scale
    z = abs(jump) / global_scale
    detected = ratio >= threshold or z >= z_threshold

    findings: list[Finding] = []
    if detected:
        findings.append(
            Finding(
                code=SPLICE_FAILURE,
                message=(
                    f"level discontinuity at index {worst_i} -> {worst_i + 1}: "
                    f"step of {jump:+,.1f} is {ratio:,.0f}x the local scale "
                    f"({local_scale:,.3f}); a single step this large against the "
                    "surrounding variation is the signature of two different "
                    "metrics spliced end-to-end, and differencing across it "
                    "produces a fabricated value"
                ),
                status=Status.FAIL,
                severity=Severity.BLOCKING,
                detail={
                    "index": worst_i,
                    "jump": round(jump, 6),
                    "local_scale": round(local_scale, 6),
                    "ratio": round(ratio, 6),
                    "z_score": round(z, 6),
                    "threshold": threshold,
                    "n": n,
                },
            )
        )

    return SpliceReport(
        detected=detected,
        index=worst_i if detected else None,
        jump=jump if detected else None,
        local_scale=local_scale,
        ratio=ratio if detected else None,
        z_score=z if detected else None,
        threshold=threshold,
        findings=tuple(findings),
    )


@dataclass(frozen=True, slots=True)
class SeriesReport:
    """Result of the contiguous-index and padding checks."""

    contiguity_ok: bool
    monotonic_ok: bool
    n_points: int
    n_expected: int | None
    n_missing: int
    first_index: object | None
    last_index: object | None
    padding: int
    findings: tuple[Finding, ...]

    @property
    def verdict(self) -> Verdict:
        """``REFUSED`` if the index is broken or padding is present and unreported."""
        return Verdict.CERTIFIED if self.clean else Verdict.REFUSED

    @property
    def clean(self) -> bool:
        """True when nothing blocking was found."""
        return not any(f.severity is Severity.BLOCKING for f in self.findings)

    def certify(self) -> Certification:
        """Produce the :class:`Certification` for this report."""
        reasons = tuple(f.message for f in self.findings if f.status is Status.FAIL)
        return Certification(
            verdict=self.verdict,
            reasons=reasons,
            provenance=("series",),
            findings=self.findings,
        )

    def as_dict(self) -> dict[str, object]:
        """JSON-serialisable view."""
        return {
            "contiguity_ok": self.contiguity_ok,
            "monotonic_ok": self.monotonic_ok,
            "n_points": self.n_points,
            "n_expected": self.n_expected,
            "n_missing": self.n_missing,
            "first_index": None if self.first_index is None else str(self.first_index),
            "last_index": None if self.last_index is None else str(self.last_index),
            "padding": self.padding,
            "clean": self.clean,
            "verdict": self.verdict.value,
            "findings": [f.as_dict() for f in self.findings],
        }


def check_contiguous(
    timestamps: Sequence[datetime],
    *,
    step: timedelta,
    strict: bool = True,
    expected_start: datetime | None = None,
) -> SeriesReport:
    """Verify a timestamp index is monotonic and evenly spaced.

    ``strict=True`` requires every step to equal ``step`` exactly. Missing bars
    are the failure this catches: a silently dropped bar makes an event-based
    statistic (drawdown duration, holding period) wrong in a way that no
    aggregate return will reveal.
    """
    n = len(timestamps)
    findings: list[Finding] = []

    if n == 0:
        findings.append(
            Finding(
                code=INDEX_FAILURE,
                message="timestamp index is empty",
                status=Status.FAIL,
                severity=Severity.BLOCKING,
                detail={"n": 0},
            )
        )
        return SeriesReport(False, False, 0, None, 0, None, None, 0, tuple(findings))

    monotonic_ok = all(
        timestamps[i] < timestamps[i + 1] for i in range(n - 1)
    )
    if not monotonic_ok:
        bad = next(
            i for i in range(n - 1) if timestamps[i] >= timestamps[i + 1]
        )
        findings.append(
            Finding(
                code=INDEX_NOT_MONOTONIC,
                message=(
                    f"timestamps are not strictly increasing at index {bad}: "
                    f"{timestamps[bad]!s} then {timestamps[bad + 1]!s}; duplicate "
                    "or reversed bars break every cumulative statistic"
                ),
                status=Status.FAIL,
                severity=Severity.BLOCKING,
                detail={"index": bad},
            )
        )

    gaps: list[int] = []
    expected_steps = n - 1
    for i in range(n - 1):
        delta = timestamps[i + 1] - timestamps[i]
        if delta != step:
            gaps.append(i)

    n_expected = expected_steps + 1
    n_missing = 0
    if gaps:
        # Count how many bars are absent relative to a regular grid.
        span = timestamps[-1] - timestamps[0]
        if step.total_seconds() > 0:
            n_expected = int(span / step) + 1
            n_missing = max(0, n_expected - n)
        findings.append(
            Finding(
                code=INDEX_FAILURE,
                message=(
                    f"timestamp index is not contiguous at step {step}: "
                    f"{len(gaps)} irregular step(s), first at index {gaps[0]}; "
                    f"{n_missing} bar(s) missing relative to a regular grid"
                ),
                status=Status.FAIL if strict else Status.WARN,
                severity=Severity.BLOCKING if strict else Severity.INFO,
                detail={
                    "n_irregular": len(gaps),
                    "first_gap_index": gaps[0],
                    "n_missing": n_missing,
                    "step_seconds": step.total_seconds(),
                },
            )
        )

    contiguity_ok = not gaps
    if expected_start is not None and timestamps[0] != expected_start:
        findings.append(
            Finding(
                code=INDEX_FAILURE,
                message=(
                    f"series starts at {timestamps[0]!s}, not the expected "
                    f"{expected_start!s}"
                ),
                status=Status.WARN,
                severity=Severity.INFO,
                detail={"first": str(timestamps[0]), "expected": str(expected_start)},
            )
        )

    return SeriesReport(
        contiguity_ok=contiguity_ok,
        monotonic_ok=monotonic_ok,
        n_points=n,
        n_expected=n_expected,
        n_missing=n_missing,
        first_index=timestamps[0],
        last_index=timestamps[-1],
        padding=0,
        findings=tuple(findings),
    )


def truncate_leading_padding(
    values: Sequence[float],
    *,
    padding_value: float = 0.0,
    tol: float = 0.0,
    timestamps: Sequence[datetime] | None = None,
) -> tuple[list[float], int]:
    """Drop leading ``padding_value`` entries, returning ``(series, dropped)``.

    Only *leading* runs are dropped. Interior zeros are data -- a day the
    strategy genuinely made nothing -- and removing them would be a different
    fabrication from the one being fixed.
    """
    if timestamps is not None and len(timestamps) != len(values):
        raise ValueError(
            f"values/timestamps length mismatch: {len(values)} vs {len(timestamps)}"
        )
    i = 0
    while i < len(values) and abs(values[i] - padding_value) <= tol:
        i += 1
    return list(values[i:]), i


def left_edge_bar_start(bar_timestamp: datetime, bar_span: timedelta) -> datetime:
    """Return the start of the interval a bar labelled ``bar_timestamp`` covers.

    The convention this library enforces: a bar is labelled by its **left
    edge**. A 15-minute bar labelled ``t0`` covers ``[t0, t0 + 15m)``.
    """
    if bar_span <= timedelta(0):
        raise ValueError(f"bar_span must be positive, got {bar_span}")
    return bar_timestamp


def left_edge_window(
    bar_timestamp: datetime, bar_span: timedelta
) -> tuple[datetime, datetime]:
    """Return ``(start, end)`` of the interval a left-edge-labelled bar covers.

    For the fixture: ``left_edge_window(t0, 15m) == (t0, t0 + 15m)``.
    """
    start = left_edge_bar_start(bar_timestamp, bar_span)
    return start, start + bar_span


def forward_bar_offset(
    bar_timestamp: datetime,
    bar_span: timedelta,
    *,
    assumed_offset: timedelta,
    tolerance_bps: float = 0.0,
) -> tuple[datetime, float]:
    """Compute the correct forward bar start, and how far the assumption missed.

    Models the fixture's bug directly. Code assumed that the bar following one
    labelled ``t0`` starts at ``t0 + assumed_offset``. Under the left-edge
    convention the next bar starts at ``t0 + bar_span``.

    Returns ``(correct_start, timing_error_bps)`` where ``timing_error_bps`` is
    the mis-taken fraction of a bar in basis points: for the fixture's
    ``assumed_offset = 1 minute`` against ``bar_span = 15 minutes`` that is

        |1m - 15m| / 15m * 10_000 = 9,333 bps

    of timing error, which is what produced the 185 bps of *price* error the
    study measured. Use :func:`price_error_bps` to express a price difference in
    bps directly.

    ``tolerance_bps`` returns 0.0 for misses within tolerance, so a caller can
    distinguish "no error" from "small error" without a second comparison. The
    tolerance is expressed in the same unit as the returned error, so a caller
    comparing against a stated measurement accuracy can pass it through
    unchanged.
    """
    correct = left_edge_bar_start(bar_timestamp, bar_span) + bar_span
    mis_taken = bar_timestamp + assumed_offset
    fraction = abs((mis_taken - correct).total_seconds()) / bar_span.total_seconds()
    error_bps = fraction * 10_000.0
    if tolerance_bps and error_bps <= tolerance_bps:
        return correct, 0.0
    return correct, error_bps


def price_error_bps(
    price_at_correct: float, price_at_assumed: float
) -> float:
    """Price error between the correct and assumed bar, in basis points."""
    if price_at_correct == 0.0:
        raise ValueError("price_at_correct must be non-zero")
    return (price_at_assumed - price_at_correct) / price_at_correct * 10_000.0


class SeriesGuard:
    """The series-structure checks in one object.

    Parameters
    ----------
    splice_ratio:
        Local-scale multiple at which a single step is called a splice.
        Default ``25``. Calibrated to be far above any real single-bar move
        while far below the fixture's ratio (tens of thousands).
    splice_min_points:
        Minimum series length for the scan to mean anything.
    z_threshold:
        Optional global-robust-z backstop, evaluated alongside the ratio.
    """

    name = "series"

    def __init__(
        self,
        *,
        splice_ratio: float = 25.0,
        splice_min_points: int = 8,
        z_threshold: float = 8.0,
    ) -> None:
        if splice_ratio <= 1.0:
            raise ValueError(f"splice_ratio must be > 1, got {splice_ratio}")
        if z_threshold <= 1.0:
            raise ValueError(f"z_threshold must be > 1, got {z_threshold}")
        self.splice_ratio = splice_ratio
        self.splice_min_points = splice_min_points
        self.z_threshold = z_threshold

    def check_splice(self, values: Sequence[float]) -> SpliceReport:
        """Run :func:`detect_splice` with this guard's thresholds."""
        return detect_splice(
            values,
            threshold=self.splice_ratio,
            min_points=self.splice_min_points,
        )

    def check_index(
        self,
        timestamps: Sequence[datetime],
        *,
        step: timedelta,
        strict: bool = True,
        expected_start: datetime | None = None,
    ) -> SeriesReport:
        """Run :func:`check_contiguous`."""
        return check_contiguous(
            timestamps, step=step, strict=strict, expected_start=expected_start
        )

    def check_padding(
        self,
        values: Sequence[float],
        *,
        padding_value: float = 0.0,
        tol: float = 0.0,
        timestamps: Sequence[datetime] | None = None,
        max_fraction: float = 0.0,
    ) -> SeriesReport:
        """Detect leading padding and refuse unless it has been truncated.

        ``max_fraction`` is the share of the series allowed to be padding
        without complaint. Default ``0.0``: padding that has not been removed is
        a fabricated track record, and the only acceptable amount of it is none.
        """
        if not 0.0 <= max_fraction <= 1.0:
            raise ValueError(f"max_fraction must be in [0, 1], got {max_fraction}")
        n = len(values)
        _, dropped = truncate_leading_padding(
            values, padding_value=padding_value, tol=tol
        )
        fraction = dropped / n if n else 0.0
        findings: list[Finding] = []
        if dropped > 0 and fraction > max_fraction:
            findings.append(
                Finding(
                    code=PADDING_FAILURE,
                    message=(
                        f"{dropped} leading zero-padded point(s) out of {n} "
                        f"({fraction:.1%}); the series did not exist for that "
                        "stretch and treating the padding as history fabricates "
                        "a track record"
                    ),
                    status=Status.FAIL,
                    severity=Severity.BLOCKING,
                    detail={
                        "padding": dropped,
                        "n": n,
                        "fraction": round(fraction, 6),
                        "usable": n - dropped,
                    },
                )
            )
        return SeriesReport(
            contiguity_ok=True,
            monotonic_ok=True,
            n_points=n,
            n_expected=None,
            n_missing=0,
            first_index=None if not timestamps else timestamps[0],
            last_index=None if not timestamps else timestamps[-1],
            padding=dropped,
            findings=tuple(findings),
        )
