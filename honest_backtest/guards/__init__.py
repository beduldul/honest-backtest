"""The guards.

Each module is small, independently testable, and reproduces one real measured
failure. A guard never returns a bare boolean: it returns an immutable report
carrying its findings and a ``certify()`` method, and the report's ``verdict``
is the only thing a caller is allowed to propagate.

===============================  ==============================================
module                           real failure it caught
===============================  ==============================================
:mod:`~.lookahead`               ``copier_pnl`` spread +0.1344, r = -0.598
:mod:`~.outliers`                mean -138.7 vs median +37.0 on 9/12 wins;
                                 top decile = 121% of **net** PnL
:mod:`~.windows`                 4 splits, all sharing one end date, 0 independent
:mod:`~.universe`                cohort filtered for staleness, benchmark not
:mod:`~.multiplicity`            341 configurations, ~17 expected false positives
:mod:`~.series`                  -24,046 pp fabricated daily return across a splice
===============================  ==============================================
"""

from __future__ import annotations

from .lookahead import LookaheadGuard, LookaheadReport, sign_consistency
from .multiplicity import (
    ExperimentCounter,
    MultiplicityReport,
    correct_p,
    expected_false_positives,
)
from .outliers import ConcentrationGuard, ConcentrationReport
from .series import (
    SeriesGuard,
    SeriesReport,
    SpliceReport,
    check_contiguous,
    detect_splice,
    forward_bar_offset,
    left_edge_bar_start,
    left_edge_window,
    price_error_bps,
    truncate_leading_padding,
)
from .universe import (
    Selection,
    UniverseGuard,
    UniverseReport,
    predicate_fingerprint,
    require_shared_predicate,
)
from .windows import IndependentWindowReport, WindowGuard, WindowPlan

__all__ = [
    # look-ahead
    "LookaheadGuard",
    "LookaheadReport",
    "sign_consistency",
    # outliers / concentration
    "ConcentrationGuard",
    "ConcentrationReport",
    # windows
    "WindowGuard",
    "WindowPlan",
    "IndependentWindowReport",
    # universe
    "UniverseGuard",
    "UniverseReport",
    "Selection",
    "require_shared_predicate",
    "predicate_fingerprint",
    # multiplicity
    "ExperimentCounter",
    "MultiplicityReport",
    "expected_false_positives",
    "correct_p",
    # series
    "SeriesGuard",
    "SeriesReport",
    "SpliceReport",
    "detect_splice",
    "truncate_leading_padding",
    "check_contiguous",
    "left_edge_bar_start",
    "left_edge_window",
    "forward_bar_offset",
    "price_error_bps",
]
