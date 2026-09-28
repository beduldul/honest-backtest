"""Small numeric helpers.

Stdlib only. No numpy, by design: the guards deal in hundreds of numbers, not
hundreds of millions, and a zero-dependency install is worth more than a
microbenchmark nobody will ever run on this code.
"""

from __future__ import annotations

import math
from typing import Sequence

__all__ = [
    "mean",
    "median",
    "stdev",
    "pearson_r",
    "spearman_r",
    "percentile",
    "top_share",
    "safe_ratio",
]


def mean(xs: Sequence[float]) -> float:
    """Arithmetic mean. Raises on empty input."""
    if not xs:
        raise ValueError("mean() of empty sequence")
    return math.fsum(xs) / len(xs)


def median(xs: Sequence[float]) -> float:
    """Lower-of-two-middle median. Raises on empty input."""
    if not xs:
        raise ValueError("median() of empty sequence")
    s = sorted(xs)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2.0


def stdev(xs: Sequence[float], *, ddof: int = 1) -> float:
    """Sample standard deviation. Returns 0.0 for degenerate input."""
    n = len(xs)
    if n - ddof <= 0:
        return 0.0
    mu = mean(xs)
    var = math.fsum((x - mu) ** 2 for x in xs) / (n - ddof)
    return math.sqrt(var)


def pearson_r(xs: Sequence[float], ys: Sequence[float]) -> float:
    """Pearson correlation.

    Returns 0.0 when either series is constant (zero variance): there is no
    measurable association, and silently returning NaN would push the decision
    into a comparison that forgets to handle it.
    """
    if len(xs) != len(ys):
        raise ValueError(f"pearson_r length mismatch: {len(xs)} vs {len(ys)}")
    if len(xs) < 2:
        raise ValueError("pearson_r needs at least 2 paired observations")
    mx, my = mean(xs), mean(ys)
    dx = [x - mx for x in xs]
    dy = [y - my for y in ys]
    sxx = math.fsum(d * d for d in dx)
    syy = math.fsum(d * d for d in dy)
    if sxx <= 0.0 or syy <= 0.0:
        return 0.0
    sxy = math.fsum(a * b for a, b in zip(dx, dy))
    return sxy / math.sqrt(sxx * syy)


def _ranks(xs: Sequence[float]) -> list[float]:
    """Average ranks, 1-based, ties shared."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman_r(xs: Sequence[float], ys: Sequence[float]) -> float:
    """Spearman rank correlation (Pearson on average ranks)."""
    if len(xs) != len(ys):
        raise ValueError(f"spearman_r length mismatch: {len(xs)} vs {len(ys)}")
    return pearson_r(_ranks(xs), _ranks(ys))


def percentile(xs: Sequence[float], q: float) -> float:
    """Linear-interpolated percentile. ``q`` in [0, 100]."""
    if not xs:
        raise ValueError("percentile() of empty sequence")
    if not 0.0 <= q <= 100.0:
        raise ValueError(f"percentile q out of range: {q}")
    s = sorted(xs)
    if len(s) == 1:
        return s[0]
    pos = (q / 100.0) * (len(s) - 1)
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return s[lo]
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def top_share(values: Sequence[float], *, fraction: float = 0.10) -> float:
    """Share of total PnL contributed by the largest ``fraction`` of values.

    The denominator is the **net** total, ``sum(values)`` -- the sum of every
    value, winners *and* losers. It is not gross profit and it cannot be: a
    share of a non-negative quantity is bounded above by 1, so ``1.21`` would
    be *unrepresentable* rather than merely large. The net denominator is both
    the definition the measured studies used and the only one under which the
    measured observation exists at all.

    Net PnL is smaller than the gross winnings (losers are netted off) and may
    be zero or negative, which is precisely why the ratio can exceed 1.0.

    Reading: ``1.21`` means the top decile by itself accounts for 121% of the
    strategy's net PnL. Since the top decile cannot exceed the net total unless
    the rest is negative, any value at or above 1.0 carries exactly one
    interpretation:

        strip out the top ``fraction`` and the strategy is a net loser.

    Returns 0.0 when the net total is zero, and a negative ratio when the net
    total is negative -- which is itself informative: the top decile made money
    in a strategy that lost money overall.

    The sign convention is preserved rather than absolute-valued so that a
    caller can tell "winners carry everything" from "winners are the only thing
    keeping a loser afloat".
    """
    if not values:
        raise ValueError("top_share() of empty sequence")
    if not 0.0 < fraction <= 1.0:
        raise ValueError(f"fraction must be in (0, 1], got {fraction}")
    n = max(1, math.ceil(len(values) * fraction))
    ranked = sorted(values, reverse=True)
    top = math.fsum(ranked[:n])
    net = math.fsum(values)
    if net == 0.0:
        return 0.0
    return top / net


def safe_ratio(num: float, den: float) -> float:
    """``num / den`` with a defined answer when ``den`` is 0."""
    if den == 0.0:
        return 0.0 if num == 0.0 else math.copysign(math.inf, num)
    return num / den
