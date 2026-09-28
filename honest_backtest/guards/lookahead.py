"""Guard 1 -- look-ahead contamination, caught by distance decay.

THE MEASURED FAILURE
--------------------
Two predictors produced spreads significant at p < 0.001:

===========================  ==================  =====================
predictor                    apparent spread     distance-decay r
===========================  ==================  =====================
``copier_pnl``               +0.1344             **-0.598**
``roi``                      +1.0190             **+0.43**
===========================  ==================  =====================

The correlation is taken per split between the spread and the split's distance
in days from the data snapshot. Both predictors were pure look-ahead: their
ranking fields are point-in-time values as of the snapshot, so using them to
rank at a split twelve months earlier injects the future. Neither was detected
by significance testing -- they were detected by asking a question
significance testing does not ask: *does the measured effect depend on when I
measured it?*

A genuine predictor does not care when you measure it. A contaminated one
does: the effect is largest for the split nearest the data snapshot (where the
future has leaked furthest into the past) and decays as you move away. That
monotone decay is the signature.

THE GUARD
---------
Given per-split effects and each split's distance in days from the snapshot,
compute the correlation. Flag ``|r| >= threshold``. Refuse.

The guard is one-sided in *meaning* (decay, r negative) but two-sided in
*detection* (r positive is just as damning -- it is the same mechanism with the
sign flipped by how the split was constructed), so the threshold is on ``|r|``.

A third instrument is included because it is cheap and independent:
:func:`sign_consistency`. A predictor whose effect changes sign between the
near half and the far half of the distances has no stable relationship to the
target at all, decay or no decay.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Sequence

from .._numeric import mean, pearson_r, spearman_r
from ..plans import days_between
from ..types import Certification, Finding, Severity, Status, Verdict

__all__ = ["LookaheadReport", "LookaheadGuard", "DISTANCE_DECAY_FAILURE"]

DISTANCE_DECAY_FAILURE = "LOOKAHEAD_DISTANCE_DECAY"
SIGN_FLIP_FAILURE = "LOOKAHEAD_SIGN_FLIP"
MIN_SPLITS_FAILURE = "LOOKAHEAD_INSUFFICIENT_SPLITS"


@dataclass(frozen=True, slots=True)
class LookaheadReport:
    """Result of the distance-decay diagnostic.

    Immutable. Carries the raw correlation so a caller can reproduce the
    judgement rather than trust it.
    """

    r: float
    """Pearson correlation of effect against distance-to-snapshot (days)."""

    spearman: float
    """Rank correlation, for the case where the decay is monotone but curved."""

    n_splits: int
    threshold: float
    near_mean: float | None
    far_mean: float | None
    contaminated: bool
    findings: tuple[Finding, ...]

    @property
    def verdict(self) -> Verdict:
        """``REFUSED`` on contamination, else ``CERTIFIED``.

        This guard is binary. It has no SUSPECT band on purpose: contamination
        is not a matter of degree. An effect that is partly look-ahead is
        unusable, because you cannot subtract the contaminated part -- you do
        not know its magnitude, only that it is there.
        """
        return Verdict.REFUSED if self.contaminated else Verdict.CERTIFIED

    def certify(self) -> Certification:
        """Produce a :class:`Certification` -- the only supported way to carry
        this report's verdict forward."""
        reasons = tuple(f.message for f in self.findings if f.status is Status.FAIL)
        return Certification(
            verdict=self.verdict,
            reasons=reasons,
            provenance=("lookahead",),
            findings=self.findings,
        )

    def as_dict(self) -> dict[str, object]:
        """JSON-serialisable view."""
        return {
            "r": self.r,
            "spearman": self.spearman,
            "n_splits": self.n_splits,
            "threshold": self.threshold,
            "near_mean": self.near_mean,
            "far_mean": self.far_mean,
            "contaminated": self.contaminated,
            "verdict": self.verdict.value,
            "findings": [f.as_dict() for f in self.findings],
        }


def sign_consistency(
    effects: Sequence[float], distances: Sequence[float]
) -> tuple[bool, float | None, float | None]:
    """Split at the median distance; report whether the sign is stable.

    Returns ``(stable, near_mean, far_mean)``. ``stable`` is False when the
    near and far halves average to opposite signs, which means the predictor
    has no direction that survives a change of measurement window.
    """
    if len(effects) != len(distances):
        raise ValueError("effects and distances must be the same length")
    if len(effects) < 2:
        return True, None, None
    order = sorted(range(len(effects)), key=lambda i: distances[i])
    half = max(1, len(order) // 2)
    near = [effects[i] for i in order[:half]]
    far = [effects[i] for i in order[half:]]
    if not near or not far:
        return True, mean(near) if near else None, None
    near_mean, far_mean = mean(near), mean(far)
    stable = (near_mean >= 0.0) == (far_mean >= 0.0)
    return stable, near_mean, far_mean


class LookaheadGuard:
    """Distance-decay contamination check.

    Parameters
    ----------
    r_threshold:
        Absolute correlation at or above which contamination is declared.
        ``0.5`` is the default: it is the point at which distance explains a
        quarter of the variance in the measured effect, which is far too much
        for a clean predictor, and it fires on the ``copier_pnl`` fixture
        (``r = -0.598``) while leaving well-measured predictors alone.

        Note the ``roi`` fixture at ``r = +0.4285``: it sits just *below* this
        threshold and therefore escapes the correlation instrument. That is the
        whole reason :func:`sign_consistency` exists as a second, independent
        check -- a single instrument with one threshold is a judgement call, and
        a predictor designed to survive that call is exactly what an edge search
        produces by accident.
    min_splits:
        Fewer than this many splits cannot support a correlation at all.
        Reported as a failure rather than skipped -- an unevaluable guard is
        not a passing guard.
    min_distinct_distances:
        Duplicate distances (four splits of one window) cannot produce a
        meaningful correlation. Also a failure.
    """

    name = "lookahead"

    def __init__(
        self,
        *,
        r_threshold: float = 0.5,
        min_splits: int = 5,
        min_distinct_distances: int = 3,
    ) -> None:
        if not 0.0 < r_threshold <= 1.0:
            raise ValueError(f"r_threshold must be in (0, 1], got {r_threshold}")
        if min_splits < 2:
            raise ValueError(f"min_splits must be >= 2, got {min_splits}")
        if min_distinct_distances < 2:
            raise ValueError("min_distinct_distances must be >= 2")
        self.r_threshold = r_threshold
        self.min_splits = min_splits
        self.min_distinct_distances = min_distinct_distances

    def run(
        self,
        effects: Sequence[float],
        distances_days: Sequence[float],
    ) -> LookaheadReport:
        """Evaluate per-split effects against their distance from the snapshot."""
        if len(effects) != len(distances_days):
            raise ValueError(
                "effects and distances_days must be the same length: "
                f"{len(effects)} vs {len(distances_days)}"
            )
        findings: list[Finding] = []
        n = len(effects)
        distinct = len(set(distances_days))

        if n < self.min_splits or distinct < self.min_distinct_distances:
            detail: dict[str, float | int | str | bool | None] = {
                "n_splits": n,
                "distinct_distances": distinct,
                "min_splits": self.min_splits,
                "min_distinct_distances": self.min_distinct_distances,
            }
            if n >= 2:
                detail["r"] = round(pearson_r(effects, distances_days), 6)
            findings.append(
                Finding(
                    code=MIN_SPLITS_FAILURE,
                    message=(
                        f"look-ahead diagnostic could not be evaluated: {n} split(s) "
                        f"at {distinct} distinct distance(s), need >= "
                        f"{self.min_splits} and >= {self.min_distinct_distances}"
                    ),
                    status=Status.FAIL,
                    severity=Severity.BLOCKING,
                    detail=detail,
                )
            )
            return LookaheadReport(
                r=detail.get("r", 0.0) if isinstance(detail.get("r"), float) else 0.0,
                spearman=0.0,
                n_splits=n,
                threshold=self.r_threshold,
                near_mean=None,
                far_mean=None,
                contaminated=True,
                findings=tuple(findings),
            )

        r = pearson_r(effects, distances_days)
        rho = spearman_r(effects, distances_days)
        stable, near_mean, far_mean = sign_consistency(effects, distances_days)
        contaminated = abs(r) >= self.r_threshold

        if contaminated:
            direction = "decays with distance" if r < 0 else "grows with distance"
            findings.append(
                Finding(
                    code=DISTANCE_DECAY_FAILURE,
                    message=(
                        f"effect is contaminated by look-ahead: {direction}, "
                        f"r = {r:+.3f} (|r| >= {self.r_threshold}) across "
                        f"{n} splits"
                    ),
                    status=Status.FAIL,
                    severity=Severity.BLOCKING,
                    detail={
                        "r": round(r, 6),
                        "spearman": round(rho, 6),
                        "n_splits": n,
                        "threshold": self.r_threshold,
                        "near_mean": None if near_mean is None else round(near_mean, 6),
                        "far_mean": None if far_mean is None else round(far_mean, 6),
                    },
                )
            )
        if not stable:
            contaminated = True
            findings.append(
                Finding(
                    code=SIGN_FLIP_FAILURE,
                    message=(
                        "effect changes sign between the near and far halves of "
                        f"the split distances (near {near_mean:+.4f}, "
                        f"far {far_mean:+.4f})"
                    ),
                    status=Status.FAIL,
                    severity=Severity.BLOCKING,
                    detail={
                        "near_mean": None if near_mean is None else round(near_mean, 6),
                        "far_mean": None if far_mean is None else round(far_mean, 6),
                    },
                )
            )

        return LookaheadReport(
            r=r,
            spearman=rho,
            n_splits=n,
            threshold=self.r_threshold,
            near_mean=near_mean,
            far_mean=far_mean,
            contaminated=contaminated,
            findings=tuple(findings),
        )

    def run_dated(
        self,
        effects: Sequence[float],
        split_dates: Sequence[date],
        snapshot_date: date,
    ) -> LookaheadReport:
        """Convenience wrapper: distances are ``snapshot_date - split_date``.

        Positive distance means the split happened *before* the snapshot, which
        is the normal case: you snapshot the data, then you look back at splits
        that end at various points prior to it. The nearer the split end is to
        the snapshot, the smaller the distance.
        """
        distances = [float(days_between(d, snapshot_date)) for d in split_dates]
        return self.run(effects, distances)
