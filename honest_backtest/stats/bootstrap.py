"""Guard 7 -- block bootstrap confidence intervals, and a permutation null.

THE MEASURED FAILURE
--------------------
The author's own prior work documented the case precisely: a naive trade-level
confidence interval **promoted a false positive to a strategy**:

    CI = [-0.021, +0.781]        # on 378 trades

The interval excludes zero by a hair. It came from **4 symbols in a one-month
artifact**. A trade-level bootstrap over that data treats 378 trades as 378
independent draws, when in truth they are 4 clusters of intraday noise sharing
one month of one market regime. The effective sample is far closer to 4 than to
378, and the interval that pretends otherwise is not conservative -- it is
wrong in the direction of enthusiasm.

THE GUARD
---------
:func:`block_bootstrap_ci` resamples **contiguous blocks**, not individual
trades, so within-block dependence is preserved by construction. The default
block is a whole week, Monday-anchored, because weekly seasonality is the
dominant autocorrelation in intraday and daily equity studies and a Monday
anchor makes the blocks line up with the calendar the strategy actually trades.

Two things are reported that a naive CI omits:

``n_blocks``
    The number of distinct blocks the sample contains. This, not the trade
    count, is the effective sample size. On the fixture it is 4-ish. A CI
    built from 4 blocks is a CI built from 4 observations and should be read as
    such.
``warning``
    Emitted when ``n_blocks`` is too low to support a claim at the requested
    confidence. The warning is *reported* rather than raised because a caller
    may legitimately want to see the interval that would have been quoted --
    seeing it next to ``n_blocks = 4`` is the lesson.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable, Literal, Sequence

from .._numeric import mean, percentile
from ..types import Certification, Finding, Severity, Status, Verdict

__all__ = [
    "BlockBootstrapResult",
    "block_bootstrap_ci",
    "permutation_null",
    "PermutationResult",
    "monday_anchored_block",
    "week_index",
]

Anchor = Literal["monday", "sunday", "iso", "none"]

LOW_BLOCK_COUNT_FAILURE = "BOOTSTRAP_INSUFFICIENT_BLOCKS"
DEGENERATE_FAILURE = "BOOTSTRAP_DEGENERATE_INPUT"


def _week_start(day: date, anchor: Anchor) -> date:
    """Return the first day of the anchoring week containing ``day``."""
    if anchor == "none":
        return day
    if anchor == "monday":
        return day - timedelta(days=day.weekday())
    if anchor == "sunday":
        return day - timedelta(days=(day.weekday() + 1) % 7)
    if anchor == "iso":
        iso = day.isocalendar()
        return date.fromisocalendar(iso.year, iso.week, 1)
    raise ValueError(f"unknown anchor {anchor!r}")


def week_index(day: date, *, anchor: Anchor = "monday") -> tuple[int, int, int]:
    """Stable key identifying the block containing ``day``.

    See :func:`_calendar_block_key` for why the ordinal is part of the key.
    """
    return _calendar_block_key(day, anchor)


def monday_anchored_block(day: date) -> date:
    """The Monday on or before ``day``."""
    return _week_start(day, "monday")


def _as_date(value: date | datetime) -> date:
    return value.date() if isinstance(value, datetime) else value


@dataclass(frozen=True, slots=True)
class BlockBootstrapResult:
    """A block-bootstrap interval, with its effective sample size attached.

    There is no way to get the interval *without* ``n_blocks``: they are the
    same object. That is the design.
    """

    point: float
    low: float
    high: float
    confidence: float
    n_observations: int
    n_blocks: int
    block_size: int
    n_resamples: int
    anchor: Anchor
    excludes_zero: bool
    min_blocks: int
    findings: tuple[Finding, ...]

    @property
    def usable(self) -> bool:
        """True when the block count supports the claim being made."""
        return self.n_blocks >= self.min_blocks

    @property
    def verdict(self) -> Verdict:
        """``SUSPECT`` when the block count is too low, ``REFUSED`` if degenerate.

        Not ``REFUSED`` on a low block count, and the difference matters. The
        point of this guard is to *show* you the interval that a naive method
        would have reported, next to the number that makes it meaningless. A
        flat refusal would hide the evidence. ``SUSPECT`` means: here is the
        interval, here is why you may not quote it as a finding.
        """
        if any(f.code == DEGENERATE_FAILURE for f in self.findings):
            return Verdict.REFUSED
        if not self.usable:
            return Verdict.SUSPECT
        return Verdict.CERTIFIED

    @property
    def naive_comparison(self) -> str:
        """One-line statement of what the naive interval would have claimed."""
        if not self.excludes_zero:
            return "interval includes zero"
        if not self.usable:
            return (
                f"interval excludes zero, but rests on {self.n_blocks} independent "
                f"block(s) (minimum {self.min_blocks}) and must not be reported"
            )
        return f"interval excludes zero on {self.n_blocks} independent block(s)"

    def certify(self) -> Certification:
        """Produce the :class:`Certification` for this result."""
        reasons = tuple(f.message for f in self.findings if f.status is Status.FAIL)
        return Certification(
            verdict=self.verdict,
            reasons=reasons,
            provenance=("bootstrap",),
            findings=self.findings,
        )

    def as_dict(self) -> dict[str, object]:
        """JSON-serialisable view."""
        return {
            "point": self.point,
            "low": self.low,
            "high": self.high,
            "confidence": self.confidence,
            "n_observations": self.n_observations,
            "n_blocks": self.n_blocks,
            "block_size": self.block_size,
            "n_resamples": self.n_resamples,
            "anchor": self.anchor,
            "excludes_zero": self.excludes_zero,
            "min_blocks": self.min_blocks,
            "usable": self.usable,
            "verdict": self.verdict.value,
            "naive_comparison": self.naive_comparison,
            "findings": [f.as_dict() for f in self.findings],
        }


def _block_spans(
    n: int, block_size: int
) -> list[tuple[int, int]]:
    """Contiguous index spans of length at most ``block_size``."""
    return [
        (start, min(start + block_size, n)) for start in range(0, n, block_size)
    ]


def _calendar_block_key(day: date, anchor: Anchor) -> tuple[int, int, int]:
    """Stable key for the calendar block containing ``day``.

    Returns ``(year, week)`` from the anchor's own calendar, plus a tiebreak
    ordinal so that the keys sort chronologically. Using an absolute ordinal
    rather than the ISO week number matters: ISO week 1 of one year and ISO
    week 1 of the next are a year apart, not adjacent, and sorting on
    ``(year, week)`` gets that right while sorting on ``week`` alone does not.
    """
    start = _week_start(day, anchor)
    iso = start.isocalendar()
    return (iso.year, iso.week, start.toordinal())


def block_bootstrap_ci(
    values: Sequence[float],
    *,
    block_dates: Sequence[date | datetime] | None = None,
    block_size: int | None = None,
    anchor: Anchor = "monday",
    statistic: Callable[[Sequence[float]], float] = mean,
    confidence: float = 0.95,
    n_resamples: int = 2000,
    min_blocks: int = 10,
    seed: int = 0,
) -> BlockBootstrapResult:
    """Bootstrap a CI over contiguous blocks.

    Parameters
    ----------
    values:
        Per-trade or per-period statistics (typically per-trade PnL or returns).
    block_dates:
        The date of each observation. When given, blocks are *calendar* blocks
        (weeks, by ``anchor``) rather than fixed-size index runs, so a week with
        a holiday has fewer observations and still counts as one block. Supply
        this whenever you have dates: it is the whole point of the method.
    block_size:
        Fixed block length in observations. Required when ``block_dates`` is
        not supplied.
    anchor:
        Which day starts a block. ``"monday"`` is the default and the method the
        author's work standardised on.
    min_blocks:
        Default ``10``. Below this the interval is reported with a warning and a
        ``SUSPECT`` verdict. Ten is the smallest count at which a bootstrap
        distribution has anything like a stable 2.5th percentile; below it, the
        interval endpoints are themselves noise.
    seed:
        Deterministic. The whole library is reproducible offline.

    Raises
    ------
    ValueError
        If neither ``block_dates`` nor ``block_size`` is supplied -- there is no
        safe default block structure, and choosing one silently is exactly the
        mistake this function exists to prevent.
    """
    if not values:
        raise ValueError("block_bootstrap_ci requires at least one observation")
    if block_size is None and block_dates is None:
        raise ValueError(
            "supply block_dates (preferred) or block_size; defaulting silently "
            "to trade-level resampling is the failure this function prevents"
        )
    if block_size is not None and block_size < 1:
        raise ValueError(f"block_size must be >= 1, got {block_size}")
    if not 0.0 < confidence < 1.0:
        raise ValueError(f"confidence must be in (0, 1), got {confidence}")
    if n_resamples < 100:
        raise ValueError(f"n_resamples must be >= 100, got {n_resamples}")

    n = len(values)

    if block_dates is not None:
        if len(block_dates) != n:
            raise ValueError(
                f"block_dates length {len(block_dates)} != values length {n}"
            )
        groups: dict[tuple[int, int, int], list[float]] = {}
        for value, raw_day in zip(values, block_dates):
            key = _calendar_block_key(_as_date(raw_day), anchor=anchor)
            groups.setdefault(key, []).append(value)
        keys = sorted(groups)
        blocks = [groups[k] for k in keys]
        effective_block_size = max(len(b) for b in blocks)
    else:
        assert block_size is not None
        spans = _block_spans(n, block_size)
        blocks = [list(values[s:e]) for s, e in spans]
        effective_block_size = block_size

    n_blocks = len(blocks)
    pool: list[float] = [v for b in blocks for v in b]
    point = statistic(pool)

    rng = random.Random(seed)
    draws: list[float] = []
    for _ in range(n_resamples):
        # Standard block bootstrap: draw n_blocks blocks with replacement and
        # concatenate. Sampling the same number of blocks as the sample
        # contains is what makes the resampled size comparable to the original;
        # drawing fewer would shrink the variance and produce an interval that
        # is too narrow, which is the failure mode being fixed.
        sample: list[float] = []
        for _ in range(n_blocks):
            sample.extend(rng.choice(blocks))
        draws.append(statistic(sample))

    tail = (1.0 - confidence) / 2.0
    low = percentile(draws, tail * 100.0)
    high = percentile(draws, (1.0 - tail) * 100.0)
    excludes_zero = (low > 0.0 and high > 0.0) or (low < 0.0 and high < 0.0)

    findings: list[Finding] = []
    if n_blocks < min_blocks:
        findings.append(
            Finding(
                code=LOW_BLOCK_COUNT_FAILURE,
                message=(
                    f"{n_blocks} independent block(s) support a {confidence:.0%} "
                    f"interval over {n} observation(s); below the minimum of "
                    f"{min_blocks} the interval endpoints are themselves noise and "
                    "the observation count is not the effective sample size"
                ),
                status=Status.FAIL,
                severity=Severity.BLOCKING,
                detail={
                    "n_blocks": n_blocks,
                    "n_observations": n,
                    "min_blocks": min_blocks,
                    "block_size": effective_block_size,
                    "confidence": confidence,
                },
            )
        )
    if all(v == values[0] for v in values):
        findings.append(
            Finding(
                code=DEGENERATE_FAILURE,
                message="all observations are identical; no interval is defined",
                status=Status.FAIL,
                severity=Severity.BLOCKING,
                detail={"value": values[0], "n": n},
            )
        )

    return BlockBootstrapResult(
        point=point,
        low=low,
        high=high,
        confidence=confidence,
        n_observations=n,
        n_blocks=n_blocks,
        block_size=effective_block_size,
        n_resamples=n_resamples,
        anchor=anchor,
        excludes_zero=excludes_zero,
        min_blocks=min_blocks,
        findings=tuple(findings),
    )


@dataclass(frozen=True, slots=True)
class PermutationResult:
    """A permutation null for a shape or ordering statistic."""

    observed: float
    p_value: float
    n_permutations: int
    n_blocks: int
    block_size: int
    null_quantiles: tuple[float, float, float]
    """``(5th, 50th, 95th)`` percentiles of the null distribution."""

    findings: tuple[Finding, ...] = ()

    @property
    def significant(self) -> bool:
        """True when ``p_value < 0.05``."""
        return self.p_value < 0.05

    def as_dict(self) -> dict[str, object]:
        """JSON-serialisable view."""
        return {
            "observed": self.observed,
            "p_value": self.p_value,
            "n_permutations": self.n_permutations,
            "n_blocks": self.n_blocks,
            "block_size": self.block_size,
            "null_quantiles": list(self.null_quantiles),
            "significant": self.significant,
        }


def permutation_null(
    values: Sequence[float],
    statistic: Callable[[Sequence[float]], float],
    *,
    block_size: int = 7,
    n_permutations: int = 1000,
    seed: int = 0,
) -> PermutationResult:
    """Permutation null that shuffles **within** blocks.

    For statistics that test *shape* or *ordering* rather than magnitude --
    "do the winners cluster", "is the drawdown early" -- you cannot simply
    shuffle the values, because that destroys the block structure and produces a
    null that is too wide, i.e. a test that is too easy to pass.

    Shuffling within blocks preserves each block's total and its membership
    while randomising the arrangement. The totals are invariant, so the null
    answers the question actually being asked: given these weekly totals, how
    surprising is this arrangement?

    ``p_value`` is the standard ``(1 + #{null >= observed}) / (1 + n)``
    estimator, which never returns 0 and is unbiased at small ``n``.
    """
    if not values:
        raise ValueError("permutation_null requires at least one observation")
    if block_size < 1:
        raise ValueError(f"block_size must be >= 1, got {block_size}")
    if n_permutations < 1:
        raise ValueError(f"n_permutations must be >= 1, got {n_permutations}")

    observed = statistic(values)
    spans = _block_spans(len(values), block_size)
    blocks = [list(values[s:e]) for s, e in spans]

    rng = random.Random(seed)
    null: list[float] = []
    for _ in range(n_permutations):
        shuffled: list[float] = []
        for block in blocks:
            copy = list(block)
            rng.shuffle(copy)
            shuffled.extend(copy)
        null.append(statistic(shuffled))

    n_null = len(null)
    at_least = sum(1 for x in null if x >= observed)
    p_value = (1 + at_least) / (1 + n_null)

    return PermutationResult(
        observed=observed,
        p_value=p_value,
        n_permutations=n_null,
        n_blocks=len(blocks),
        block_size=block_size,
        null_quantiles=(
            percentile(null, 5.0),
            percentile(null, 50.0),
            percentile(null, 95.0),
        ),
    )


def bootstrap_mean_by_block(
    values: Sequence[float], *, block_size: int
) -> float:
    """Mean of per-block means -- the effective-sample view of a series."""
    spans = _block_spans(len(values), block_size)
    if not spans:
        raise ValueError("no blocks produced")
    means = [mean(values[s:e]) for s, e in spans]
    return mean(means)


def _normal_ci_halfwidth(values: Sequence[float], confidence: float) -> float:
    """Normal-approximation half-width, for comparison in examples only."""
    n = len(values)
    if n < 2:
        return math.inf
    mu = mean(values)
    var = sum((v - mu) ** 2 for v in values) / (n - 1)
    z = {0.90: 1.6449, 0.95: 1.96, 0.99: 2.5758}.get(
        round(confidence, 2), 1.96
    )
    return z * math.sqrt(var / n)
