"""The aggregator: one result set in, one verdict out.

Design rules, in priority order:

1. **The verdict is the strictest guard's verdict.** No averaging, no scoring,
   no "overall confidence". A single ``REFUSED`` makes the report ``REFUSED``,
   because a result whose numbers are contaminated is not 90% usable.

2. **The refusal path is the easy path.** ``HonestyReport.run()`` is the only
   intended constructor and it runs every guard it is given.
   ``require_certified()`` is the one line a consumer needs, and it raises.
   The unsafe route -- ``report.verdict = CERTIFIED`` -- does not exist,
   because the report is frozen.

3. **A skipped guard is a failed guard.** A guard in the configured list that
   could not run because the result set lacked its inputs produces an
   ``ERROR`` finding, not silence. "We didn't check" and "we checked and it was
   fine" must never look the same downstream.

4. **Findings are reasons, not scores.** The report prints the specific guard
   failures in words, with the measured numbers.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Callable, Iterable, Mapping, Sequence

from .audit import assert_no_bypass
from .guards.lookahead import LookaheadGuard, LookaheadReport
from .guards.multiplicity import ExperimentCounter, MultiplicityReport
from .guards.outliers import ConcentrationGuard, ConcentrationReport
from .guards.series import SeriesGuard, SeriesReport, SpliceReport
from .guards.universe import Selection, UniverseGuard, UniverseReport
from .guards.windows import IndependentWindowReport, WindowGuard, WindowPlan
from .types import (
    Certification,
    Finding,
    HonestyError,
    RefusedError,
    Severity,
    Status,
    Verdict,
)

__all__ = ["ResultSet", "Config", "HonestyReport"]

UNGUARDED_FAILURE = "AUDIT_UNGUARDED_VERDICT"
GUARD_NOT_RUN_FAILURE = "GUARD_INPUTS_MISSING"


@dataclass(frozen=True, slots=True)
class ResultSet:
    """Everything a caller might want validated, in one immutable bundle.

    Every field is optional. The report runs each guard against the fields it
    needs and turns a missing input into a blocking ``ERROR`` -- so an empty
    ``ResultSet`` is a ``REFUSED`` report, not a vacuous pass. That is the
    intended behaviour: "nothing to check" is not "checked and clean".
    """

    name: str

    # look-ahead
    split_effects: tuple[float, ...] = ()
    split_distances_days: tuple[float, ...] = ()
    split_dates: tuple[date, ...] = ()
    snapshot_date: date | None = None

    # outliers
    window_excesses: tuple[float, ...] = ()
    win_count: int | None = None
    trade_pnls: tuple[float, ...] = ()

    # windows
    window_plan: WindowPlan | None = None

    # universe
    cohort: Selection[object] | None = None
    benchmark: Selection[object] | None = None

    # series
    series_values: tuple[float, ...] = ()
    series_timestamps: tuple[datetime, ...] = ()
    series_step_seconds: float | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise HonestyError("ResultSet.name must be non-empty")

    def as_dict(self) -> dict[str, object]:
        """JSON-serialisable summary (universe predicates are summarised)."""
        return {
            "name": self.name,
            "n_split_effects": len(self.split_effects),
            "n_split_distances": len(self.split_distances_days),
            "n_split_dates": len(self.split_dates),
            "snapshot_date": None if self.snapshot_date is None else self.snapshot_date.isoformat(),
            "n_window_excesses": len(self.window_excesses),
            "win_count": self.win_count,
            "n_trade_pnls": len(self.trade_pnls),
            "has_window_plan": self.window_plan is not None,
            "has_cohort": self.cohort is not None,
            "has_benchmark": self.benchmark is not None,
            "n_series_values": len(self.series_values),
            "n_series_timestamps": len(self.series_timestamps),
        }


@dataclass(frozen=True, slots=True)
class Config:
    """Guard thresholds, in one place and in one direction (strict).

    Every default is the strict setting. Relaxing one is a visible, explicit
    act with a name; there is no ``strict=False`` master switch, because a
    master switch is what gets flipped and forgotten.
    """

    lookahead_r_threshold: float = 0.5
    lookahead_min_splits: int = 5

    top_fraction: float = 0.10
    tail_threshold: float = 1.0
    min_obs: int = 8

    min_independent_windows: int = 2
    require_identical_predicate: bool = True

    alpha: float = 0.05
    correction: str = "bonferroni"

    splice_ratio: float = 25.0

    bootstrap_min_blocks: int = 10
    bootstrap_block_size: int = 7

    assert_no_unguarded_construction: bool = False
    """Set ``True`` to have the report parse caller source for forged verdicts.

    Default ``False``. The CLI and every example set it ``True``; a library
    caller that owns its whole call stack should too.
    """

    guard_subset: tuple[str, ...] = ()
    """Restrict to these guard names. Empty means all applicable guards.

    Restricting is allowed -- some result sets have no series data. But a
    restricted report records the restriction in ``skipped_guards`` and can
    never reach ``CERTIFIED`` unless at least one guard ran, so a subset cannot
    silently become a rubber stamp.
    """

    def __post_init__(self) -> None:
        if not 0.0 < self.alpha < 1.0:
            raise HonestyError(f"alpha must be in (0, 1), got {self.alpha}")
        if self.correction not in ("bonferroni", "sidak", "none"):
            raise HonestyError(f"unknown correction {self.correction!r}")
        if not 0.0 < self.lookahead_r_threshold <= 1.0:
            raise HonestyError("lookahead_r_threshold must be in (0, 1]")
        if self.lookahead_min_splits < 2:
            raise HonestyError("lookahead_min_splits must be >= 2")
        if self.min_independent_windows < 1:
            raise HonestyError("min_independent_windows must be >= 1")

    def as_dict(self) -> dict[str, object]:
        """JSON-serialisable view."""
        return {
            "lookahead_r_threshold": self.lookahead_r_threshold,
            "lookahead_min_splits": self.lookahead_min_splits,
            "top_fraction": self.top_fraction,
            "tail_threshold": self.tail_threshold,
            "min_obs": self.min_obs,
            "min_independent_windows": self.min_independent_windows,
            "require_identical_predicate": self.require_identical_predicate,
            "alpha": self.alpha,
            "correction": self.correction,
            "splice_ratio": self.splice_ratio,
            "bootstrap_min_blocks": self.bootstrap_min_blocks,
            "bootstrap_block_size": self.bootstrap_block_size,
            "assert_no_unguarded_construction": self.assert_no_unguarded_construction,
            "guard_subset": list(self.guard_subset),
        }


@dataclass(frozen=True, slots=True)
class HonestyReport:
    """The aggregate verdict.

    Constructed only through :meth:`run`, which is the only place in the
    library that may build a :class:`Certification` from this many sources.
    """

    name: str
    verdict: Verdict
    findings: tuple[Finding, ...]
    ran_guards: tuple[str, ...]
    skipped_guards: tuple[str, ...]
    certification: Certification
    payload: Mapping[str, object] = field(default_factory=dict)

    @property
    def certified(self) -> bool:
        """True only for a clean ``CERTIFIED``."""
        return self.verdict is Verdict.CERTIFIED

    @property
    def refused(self) -> bool:
        """True when the report is ``REFUSED``."""
        return self.verdict is Verdict.REFUSED

    def failures(self) -> tuple[Finding, ...]:
        """Findings that blocked, in the order the guards produced them."""
        return tuple(
            f
            for f in self.findings
            if f.severity is Severity.BLOCKING
            and f.status in (Status.FAIL, Status.ERROR)
        )

    def failure_codes(self) -> tuple[str, ...]:
        """The machine-readable codes of the blocking findings."""
        return tuple(f.code for f in self.failures())

    def require_certified(self) -> "HonestyReport":
        """Return self if ``CERTIFIED``; raise :class:`RefusedError` otherwise.

        The one method a downstream consumer needs. Use it to fence reporting::

            report.require_certified()
            publish(report.payload)     # unreachable unless certified
        """
        if not self.certified:
            raise RefusedError(
                self.verdict,
                tuple(f.message for f in self.failures()) or self.certification.reasons,
            )
        return self

    def explanation(self) -> str:
        """Multi-line human-readable account of the verdict."""
        lines = [f"{self.name}: {self.verdict.value}"]
        for f in self.failures():
            lines.append(f"  [{f.status.value}] {f.code}: {f.message}")
        for f in self.findings:
            if f not in self.failures() and f.status is not Status.PASS:
                lines.append(f"  [{f.status.value}] {f.code}: {f.message}")
        if self.skipped_guards:
            lines.append(
                "  guards not run (no inputs supplied): "
                + ", ".join(self.skipped_guards)
            )
        if self.ran_guards:
            lines.append("  guards run: " + ", ".join(self.ran_guards))
        return "\n".join(lines)

    def as_dict(self) -> dict[str, object]:
        """JSON-serialisable view."""
        return {
            "name": self.name,
            "verdict": self.verdict.value,
            "certified": self.certified,
            "ran_guards": list(self.ran_guards),
            "skipped_guards": list(self.skipped_guards),
            "failure_codes": list(self.failure_codes()),
            "findings": [f.as_dict() for f in self.findings],
            "certification": self.certification.as_dict(),
            "payload": dict(self.payload),
        }

    def to_json(self, *, indent: int = 2) -> str:
        """Serialise the report."""
        return json.dumps(self.as_dict(), indent=indent, sort_keys=False)

    # ------------------------------------------------------------------
    # construction
    # ------------------------------------------------------------------

    @classmethod
    def run(
        cls,
        result: ResultSet,
        *,
        config: Config | None = None,
        guards: Sequence[object] | None = None,
        counter: ExperimentCounter | None = None,
        claimed_p: float | None = None,
        n_nominal_positives: int | None = None,
    ) -> "HonestyReport":
        """Run every applicable guard and aggregate to one verdict.

        ``guards`` optionally supplies pre-built guard instances (useful for
        custom thresholds per test). When omitted, guards are built from
        ``config``. The guard *set* is the same either way; there is no path
        that runs guards and does not include their verdicts.
        """
        cfg = config or Config()
        if cfg.assert_no_unguarded_construction:
            assert_no_bypass()

        findings: list[Finding] = []
        ran: list[str] = []
        skipped: list[str] = []
        payload: dict[str, object] = {}

        all_guards = (
            "lookahead",
            "concentration",
            "windows",
            "universe",
            "multiplicity",
            "series",
        )

        def wanted(name: str) -> bool:
            if cfg.guard_subset and name not in cfg.guard_subset:
                # Excluded by explicit configuration. Recorded as skipped so a
                # restricted run can never be mistaken for a full one: the
                # report's own provenance says what was not checked.
                skipped.append(name)
                return False
            return True

        # -- look-ahead -------------------------------------------------
        if wanted("lookahead"):
            if result.split_effects:
                lag = _find_lookahead(guards) or LookaheadGuard(
                    r_threshold=cfg.lookahead_r_threshold,
                    min_splits=cfg.lookahead_min_splits,
                )
                if result.split_distances_days:
                    lr: LookaheadReport = lag.run(
                        result.split_effects, result.split_distances_days
                    )
                elif result.split_dates and result.snapshot_date:
                    lr = lag.run_dated(
                        result.split_effects,
                        result.split_dates,
                        result.snapshot_date,
                    )
                else:
                    lr = None  # type: ignore[assignment]
                    findings.append(
                        _missing_inputs(
                            "lookahead",
                            "split_effects supplied but neither "
                            "split_distances_days nor (split_dates + snapshot_date)",
                        )
                    )
                if lr is not None:
                    findings.extend(lr.findings)
                    ran.append("lookahead")
                    payload["lookahead"] = lr.as_dict()
            else:
                skipped.append("lookahead")

        # -- concentration: windows -------------------------------------
        if wanted("concentration"):
            if result.window_excesses:
                conc = _find_concentration(guards) or ConcentrationGuard(
                    top_fraction=cfg.top_fraction,
                    tail_threshold=cfg.tail_threshold,
                    min_obs=cfg.min_obs,
                )
                cr: ConcentrationReport = conc.check_windows(
                    result.window_excesses, win_count=result.win_count
                )
                findings.extend(cr.findings)
                ran.append("concentration")
                payload["concentration_windows"] = cr.as_dict()
            else:
                skipped.append("concentration")

            # -- concentration: trades ----------------------------------
            if result.trade_pnls:
                conc = _find_concentration(guards) or ConcentrationGuard(
                    top_fraction=cfg.top_fraction,
                    tail_threshold=cfg.tail_threshold,
                    min_obs=cfg.min_obs,
                )
                tr = conc.check_trades(result.trade_pnls)
                findings.extend(tr.findings)
                if "concentration" not in ran:
                    ran.append("concentration")
                payload["concentration_trades"] = tr.as_dict()

        # -- windows ----------------------------------------------------
        if wanted("windows"):
            if result.window_plan is not None:
                wg = _find_windows(guards) or WindowGuard(
                    min_independent=cfg.min_independent_windows
                )
                wr: IndependentWindowReport = wg.run(result.window_plan)
                findings.extend(wr.findings)
                ran.append("windows")
                payload["windows"] = wr.as_dict()
            else:
                skipped.append("windows")

        # -- universe ---------------------------------------------------
        if wanted("universe"):
            if result.cohort is not None and result.benchmark is not None:
                ug = _find_universe(guards) or UniverseGuard(
                    require_identical_object=cfg.require_identical_predicate
                )
                ur: UniverseReport = ug.run(
                    result.cohort,  # type: ignore[arg-type]
                    result.benchmark,  # type: ignore[arg-type]
                )
                findings.extend(ur.findings)
                ran.append("universe")
                payload["universe"] = ur.as_dict()
            else:
                skipped.append("universe")

        # -- multiplicity -----------------------------------------------
        if wanted("multiplicity"):
            if counter is not None or claimed_p is not None or n_nominal_positives is not None:
                mc = counter or ExperimentCounter(
                    alpha=cfg.alpha, correction=cfg.correction  # type: ignore[arg-type]
                )
                mr: MultiplicityReport = mc.report(
                    claimed_p=claimed_p,
                    n_nominal_positives=n_nominal_positives,
                )
                findings.extend(mr.findings)
                ran.append("multiplicity")
                payload["multiplicity"] = mr.as_dict()
            else:
                skipped.append("multiplicity")

        # -- series -----------------------------------------------------
        if wanted("series"):
            sg = _find_series(guards) or SeriesGuard(splice_ratio=cfg.splice_ratio)
            if result.series_values:
                sr: SpliceReport = sg.check_splice(result.series_values)
                findings.extend(sr.findings)
                ran.append("series")
                payload["series_splice"] = sr.as_dict()
            if result.series_timestamps:
                if result.series_step_seconds is None:
                    findings.append(
                        _missing_inputs(
                            "series", "series_timestamps supplied without series_step_seconds"
                        )
                    )
                else:
                    from datetime import timedelta

                    ir: SeriesReport = sg.check_index(
                        result.series_timestamps,
                        step=timedelta(seconds=result.series_step_seconds),
                    )
                    findings.extend(ir.findings)
                    if "series" not in ran:
                        ran.append("series")
                    payload["series_index"] = ir.as_dict()
            if not result.series_values and not result.series_timestamps:
                skipped.append("series")

        # -- aggregate --------------------------------------------------
        if not ran:
            findings.append(
                Finding(
                    code=GUARD_NOT_RUN_FAILURE,
                    message=(
                        f"no guard could run against result set {result.name!r}: "
                        f"missing inputs for {', '.join(skipped) or 'all guards'}"
                    ),
                    status=Status.ERROR,
                    severity=Severity.BLOCKING,
                    detail={"skipped": ", ".join(skipped)},
                )
            )

        verdict = _verdict_from(findings, ran)
        certification = _certification(result.name, verdict, findings, ran)

        return cls(
            name=result.name,
            verdict=verdict,
            findings=tuple(findings),
            ran_guards=tuple(ran),
            skipped_guards=tuple(skipped),
            certification=certification,
            payload=payload,
        )


def _missing_inputs(guard: str, detail: str) -> Finding:
    return Finding(
        code=GUARD_NOT_RUN_FAILURE,
        message=f"{guard} guard could not run: {detail}",
        status=Status.ERROR,
        severity=Severity.BLOCKING,
        detail={"guard": guard, "detail": detail},
    )


def _verdict_from(findings: Sequence[Finding], ran: Sequence[str]) -> Verdict:
    """Strictest verdict implied by the findings.

    ``ERROR`` counts as blocking, so a guard that could not run refuses the
    report. There is deliberately no path from "no guards ran" to ``CERTIFIED``.
    """
    if not ran:
        return Verdict.REFUSED
    verdicts: list[Verdict] = [Verdict.CERTIFIED]
    for f in findings:
        if f.status is Status.FAIL and f.severity is Severity.BLOCKING:
            verdicts.append(Verdict.REFUSED)
        elif f.status is Status.ERROR:
            verdicts.append(Verdict.REFUSED)
        elif f.status is Status.WARN:
            verdicts.append(Verdict.SUSPECT)
    return Verdict.strictest(verdicts)


def _certification(
    name: str, verdict: Verdict, findings: Sequence[Finding], ran: Sequence[str]
) -> Certification:
    blocking = tuple(
        f.message
        for f in findings
        if f.severity is Severity.BLOCKING and f.status is not Status.PASS
    )
    return Certification(
        verdict=verdict,
        reasons=blocking,
        provenance=tuple(ran),
        findings=tuple(findings),
    )


def _find_lookahead(guards: Sequence[object] | None) -> LookaheadGuard | None:
    return _typed_guard(guards, LookaheadGuard)


def _find_concentration(guards: Sequence[object] | None) -> ConcentrationGuard | None:
    return _typed_guard(guards, ConcentrationGuard)


def _find_windows(guards: Sequence[object] | None) -> WindowGuard | None:
    return _typed_guard(guards, WindowGuard)


def _find_universe(guards: Sequence[object] | None) -> UniverseGuard | None:
    return _typed_guard(guards, UniverseGuard)


def _find_series(guards: Sequence[object] | None) -> SeriesGuard | None:
    return _typed_guard(guards, SeriesGuard)


def _typed_guard(
    guards: Sequence[object] | None, cls: type
) -> object | None:
    """Return the first instance of ``cls`` in ``guards``, if any."""
    if not guards:
        return None
    return next((g for g in guards if isinstance(g, cls)), None)
