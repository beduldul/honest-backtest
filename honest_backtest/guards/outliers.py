"""Guard 2 -- outlier domination: mean/median disagreement and tail concentration.

THE MEASURED FAILURES
---------------------
**(a)** A strategy won **9 of 12** independent windows and was not an edge::

    mean excess   = -138.7
    median excess =  +37.0      # opposite signs

Nine wins out of twelve sounds like a result. It is not, because the three
losses were large enough to invert the mean. The win-count and the dollar
total tell opposite stories, and the dollar total is the one that reaches your
P&L. **The sign disagreement is the alarm**: it says the distribution is not
centred where the median sits, so the summary statistic you quote is a choice,
not a fact.

**(b)** A strategy's in-sample **top 10% of trades produced 121% of net PnL** --
removing the best decile leaves it negative. A second, illustrative 15m-shaped
case uses a top-10% share of **1.64** (``ILLUSTRATIVE``: the magnitude is the
narrative's, not a persisted measurement); a 1m variant had essentially all of
its gross in **one week**.

WHY THE DENOMINATOR IS NET PnL, AND WHY THE SHARE CAN EXCEED 100%
-----------------------------------------------------------------
This is the one place in the library where the arithmetic genuinely surprises
people, so it is worth being explicit.

The share is ``(sum of the top decile) / (net PnL)``. It is **not** a share of
gross profit, and it could not be: a fraction of a non-negative quantity is
bounded above by 1.0, so "121% of gross" is not a small number, it is a
self-contradiction. There is no such quantity.

Net PnL is the sum of *every* trade, winners and losers alike:

* it is **smaller** than the gross winnings, because the losers are netted off;
* it can be **zero** or **negative**, when the losers outweigh the winners.

Both of those are exactly what makes a share above 100% possible. If the top
decile earns 4570 and the other 90% of trades together lose 793, net PnL is
3777, and the top decile's share is ``4570 / 3777 = 121%``. The sentence that
produces is the useful one: **remove the best 10% of trades and what is left is
a loser of 793.** A gross-denominated share cannot say that -- a non-negative
denominator is incapable of falling below its own part.

So: share at or above 1.0 always means the same thing -- the remainder is a net
loser, and what you are calling an edge is a handful of draws. The threshold is
1.0 rather than 0.5 or 0.8 because 1.0 is the point where that reading becomes
arithmetic fact rather than taste.

THE GUARDS
----------
:meth:`ConcentrationGuard.check_windows` handles (a).
:meth:`ConcentrationGuard.check_trades` handles (b).
Both refuse. Neither is satisfied by a high win-rate, which is the point --
the win-rate is exactly the statistic that lied in (a).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .._numeric import mean, median, top_share
from ..types import Certification, Finding, Severity, Status, Verdict

__all__ = ["ConcentrationReport", "ConcentrationGuard"]

MIXED_SIGNS_FAILURE = "CONCENTRATION_MIXED_SIGNS"
TAIL_FAILURE = "CONCENTRATION_TAIL_DOMINANCE"
ONE_SIDED_FAILURE = "CONCENTRATION_ONE_SIDED_TAIL"
INSUFFICIENT_FAILURE = "CONCENTRATION_INSUFFICIENT_DATA"


@dataclass(frozen=True, slots=True)
class ConcentrationReport:
    """Result of the outlier-domination checks.

    ``mean_excess`` / ``median_excess`` are populated by the window check;
    ``top_share`` / ``share_excluding_tail`` by the trade check. A caller that
    only ran one of the two sees ``None`` for the other, and the report says so
    rather than defaulting to a friendly zero.
    """

    kind: str
    """``"windows"`` or ``"trades"``."""

    n: int
    mean_excess: float | None
    median_excess: float | None
    top_share: float | None
    share_excluding_tail: float | None
    top_fraction: float
    win_count: int | None
    outlier_driven: bool
    findings: tuple[Finding, ...]

    @property
    def signs_disagree(self) -> bool:
        """True when mean and median point opposite ways."""
        if self.mean_excess is None or self.median_excess is None:
            return False
        return (self.mean_excess >= 0.0) != (self.median_excess >= 0.0)

    @property
    def verdict(self) -> Verdict:
        """``REFUSED`` when outlier-driven, else ``CERTIFIED``.

        Binary by design, for the same reason as the look-ahead guard: you
        cannot salvage a mean from 12 windows when one window is doing the
        work, and "SUSPECT" would invite someone to quote it anyway.
        """
        return Verdict.REFUSED if self.outlier_driven else Verdict.CERTIFIED

    def certify(self) -> Certification:
        """Produce the :class:`Certification` for this report."""
        reasons = tuple(f.message for f in self.findings if f.status is Status.FAIL)
        return Certification(
            verdict=self.verdict,
            reasons=reasons,
            provenance=("concentration",),
            findings=self.findings,
        )

    def as_dict(self) -> dict[str, object]:
        """JSON-serialisable view."""
        return {
            "kind": self.kind,
            "n": self.n,
            "mean_excess": self.mean_excess,
            "median_excess": self.median_excess,
            "top_share": self.top_share,
            "share_excluding_tail": self.share_excluding_tail,
            "top_fraction": self.top_fraction,
            "win_count": self.win_count,
            "signs_disagree": self.signs_disagree,
            "outlier_driven": self.outlier_driven,
            "verdict": self.verdict.value,
            "findings": [f.as_dict() for f in self.findings],
        }


class ConcentrationGuard:
    """Mean-vs-median disagreement and top-decile PnL share.

    Parameters
    ----------
    top_fraction:
        Size of the "tail" as a fraction of observations. ``0.10`` reproduces
        the measured study (top 10% -> 121% of net PnL).
    tail_threshold:
        Top-decile **net**-PnL share at or above which the result is
        outlier-driven. The denominator is net PnL -- the sum of every trade,
        winners *and* losers -- not gross profit; see the module docstring for
        why the distinction is load-bearing. Net PnL is smaller than the gross
        winnings and may be zero or negative, which is exactly why a share
        above 1.0 is expressible at all.
        The default is deliberately exactly ``1.0``, not a round 0.5 or 0.8.
        A share of 1.0 is the sharpest available line: it means the top decile
        produced the *entire* net PnL, so the remaining 90% nets to zero or
        worse. Anything above 1.0 (the 1.64 fixture) is strictly worse. A
        lower threshold would be a taste judgement; this one is arithmetic.
    min_obs:
        Minimum observations before either check is meaningful.
    """

    name = "concentration"

    def __init__(
        self,
        *,
        top_fraction: float = 0.10,
        tail_threshold: float = 1.0,
        min_obs: int = 8,
    ) -> None:
        if not 0.0 < top_fraction <= 1.0:
            raise ValueError(f"top_fraction must be in (0, 1], got {top_fraction}")
        if tail_threshold <= 0.0:
            raise ValueError(f"tail_threshold must be positive, got {tail_threshold}")
        if min_obs < 2:
            raise ValueError(f"min_obs must be >= 2, got {min_obs}")
        self.top_fraction = top_fraction
        self.tail_threshold = tail_threshold
        self.min_obs = min_obs

    def check_windows(
        self,
        excesses: Sequence[float],
        *,
        win_count: int | None = None,
    ) -> ConcentrationReport:
        """Mean-vs-median sign disagreement across independent windows.

        ``excesses`` are per-window excess returns (strategy minus benchmark).
        ``win_count``, when supplied, is *recorded* rather than trusted -- it is
        printed alongside the verdict precisely so that a 9-of-12 win count
        cannot be quoted without the sign disagreement next to it.
        """
        n = len(excesses)
        if n < self.min_obs:
            return self._insufficient("windows", n, None, None, win_count)

        mu, med = mean(excesses), median(excesses)
        findings: list[Finding] = []
        outlier_driven = False

        if (mu >= 0.0) != (med >= 0.0):
            outlier_driven = True
            wins = win_count if win_count is not None else sum(
                1 for x in excesses if x > 0.0
            )
            findings.append(
                Finding(
                    code=MIXED_SIGNS_FAILURE,
                    message=(
                        f"MIXED / OUTLIER-DRIVEN: mean excess {mu:+.1f} and median "
                        f"excess {med:+.1f} have opposite signs; win count "
                        f"{wins}/{n} does not override this -- one or two windows "
                        "dominate the total in the opposite direction"
                    ),
                    status=Status.FAIL,
                    severity=Severity.BLOCKING,
                    detail={
                        "mean_excess": round(mu, 6),
                        "median_excess": round(med, 6),
                        "win_count": wins,
                        "n": n,
                    },
                )
            )

        return ConcentrationReport(
            kind="windows",
            n=n,
            mean_excess=mu,
            median_excess=med,
            top_share=None,
            share_excluding_tail=None,
            top_fraction=self.top_fraction,
            win_count=win_count,
            outlier_driven=outlier_driven,
            findings=tuple(findings),
        )

    def check_trades(self, pnls: Sequence[float]) -> ConcentrationReport:
        """Top-decile net-PnL-share concentration in a trade or bar PnL series."""
        n = len(pnls)
        if n < self.min_obs:
            return self._insufficient("trades", n, None, None, None)

        share = top_share(pnls, fraction=self.top_fraction)
        # Remainder under the same net-PnL convention the share uses: everything
        # outside the top decile, summed. When the share is at or above 1.0 this
        # figure is necessarily <= 0, and printing it is the whole point -- it
        # is the sentence "remove the best 10% and you have a loser".
        n_top = max(1, int(len(pnls) * self.top_fraction))
        remainder = sum(sorted(pnls)[:-n_top]) if n_top < len(pnls) else 0.0
        findings: list[Finding] = []
        outlier_driven = share >= self.tail_threshold

        if outlier_driven:
            pct = int(round(self.top_fraction * 100))
            findings.append(
                Finding(
                    code=TAIL_FAILURE,
                    message=(
                        f"top {pct}% of observations produce {share * 100:.0f}% of "
                        f"net PnL (threshold {self.tail_threshold:.2f}); "
                        f"excluding the tail the result is {remainder:+.1f}"
                    ),
                    status=Status.FAIL,
                    severity=Severity.BLOCKING,
                    detail={
                        "top_share": round(share, 6),
                        "top_fraction": self.top_fraction,
                        "threshold": self.tail_threshold,
                        "remainder_pnl": round(remainder, 6),
                        "n": n,
                    },
                )
            )
        elif share >= self.tail_threshold * 0.5:
            findings.append(
                Finding(
                    code=ONE_SIDED_FAILURE,
                    message=(
                        f"top {int(round(self.top_fraction * 100))}% of observations "
                        f"produce {share * 100:.0f}% of net PnL, half or more of "
                        "the total; note that this alone is not fatal"
                    ),
                    status=Status.WARN,
                    severity=Severity.INFO,
                    detail={"top_share": round(share, 6), "n": n},
                )
            )

        return ConcentrationReport(
            kind="trades",
            n=n,
            mean_excess=None,
            median_excess=None,
            top_share=share,
            share_excluding_tail=remainder,
            top_fraction=self.top_fraction,
            win_count=None,
            outlier_driven=outlier_driven,
            findings=tuple(findings),
        )

    def _insufficient(
        self,
        kind: str,
        n: int,
        mu: float | None,
        med: float | None,
        win_count: int | None,
    ) -> ConcentrationReport:
        finding = Finding(
            code=INSUFFICIENT_FAILURE,
            message=(
                f"concentration check on {kind} could not be evaluated: {n} "
                f"observation(s), need >= {self.min_obs}"
            ),
            status=Status.FAIL,
            severity=Severity.BLOCKING,
            detail={"n": n, "min_obs": self.min_obs, "kind": kind},
        )
        return ConcentrationReport(
            kind=kind,
            n=n,
            mean_excess=mu,
            median_excess=med,
            top_share=None,
            share_excluding_tail=None,
            top_fraction=self.top_fraction,
            win_count=win_count,
            outlier_driven=True,
            findings=(finding,),
        )
