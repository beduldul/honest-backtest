"""honest-backtest: a validation framework for refusing to fool yourself.

Most backtesting libraries help you produce a number. This one helps you
disbelieve it.

The central object is :class:`~honest_backtest.report.HonestyReport`, which
aggregates every guard and yields one of three verdicts -- ``CERTIFIED``,
``SUSPECT`` or ``REFUSED``. A refused result is not reportable as a finding:
the refusal path is the *easy* path, and getting a ``CERTIFIED`` requires
having actually run the guards.

Quick start::

    from honest_backtest import (
        HonestyReport, ResultSet, Config,
        LookaheadGuard, ConcentrationGuard, WindowGuard,
    )

    report = HonestyReport.run(
        ResultSet(name="copier_pnl", split_effects=..., split_distances_days=...),
        guards=[LookaheadGuard(r_threshold=0.5, min_splits=5)],
        config=Config(),
    )
    print(report.verdict)          # Verdict.REFUSED
    report.require_certified()     # raises RefusedError

See ``README.md`` for the ten documented failures each guard reproduces.
Some are measured and some are constructed to show a mechanism; each fixture
states which (``honest_backtest.fixtures.PROVENANCE``), and
``fixtures.provenance()`` audits the labels.
"""

from __future__ import annotations

from .types import (
    Certification,
    Finding,
    GuardBypassError,
    HonestyError,
    RefusedError,
    Severity,
    Status,
    Verdict,
)

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "Verdict",
    "Status",
    "Severity",
    "Finding",
    "Certification",
    "HonestyError",
    "RefusedError",
    "GuardBypassError",
]


def __getattr__(name: str) -> object:
    """Lazily expose the heavier submodules without import cycles.

    ``honest_backtest.guards`` imports ``honest_backtest.types``, and the
    aggregator imports the guards. Doing those imports eagerly here would make
    ``import honest_backtest`` pull in the whole tree, which is both slow and
    circular-prone. ``__getattr__`` keeps ``from honest_backtest import
    HonestyReport`` working while leaving the import graph acyclic.
    """
    if name in {"report", "guards", "stats", "cli", "plans", "audit"}:
        import importlib

        return importlib.import_module(f".{name}", __name__)
    if name in {"HonestyReport", "ResultSet", "Config"}:
        from . import report

        return getattr(report, name)
    if name in {
        "LookaheadGuard",
        "ConcentrationGuard",
        "WindowGuard",
        "UniverseGuard",
        "MultiplicityGuard",
        "SeriesGuard",
        "EvidenceGuard",
        "ComparisonGuard",
    }:
        from . import guards

        return getattr(guards, name)
    if name in {"block_bootstrap_ci", "permutation_null"}:
        from . import stats

        return getattr(stats, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
