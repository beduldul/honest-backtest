"""The fixtures, with the provenance of every number stated.

**Every statistic here was measured in the author's own research. Not every
*observation* here was measured.** Where the research archive preserved the
raw per-observation rows, this module carries those rows verbatim
(``PROVENANCE = "MEASURED"``). Where it did not, the observations are
generated or illustrative and the *statistic* is what reproduces the measured
figure -- either ``"DERIVED"`` (the series is solved from the measured target)
or ``"ILLUSTRATIVE"`` (the numbers demonstrate a mechanism and are not a
finding). The distinction is per fixture, it is stated in each fixture's
``provenance`` field, it is audited by :func:`provenance`, and it is exactly
the distinction this library exists to enforce: a number that is derived from a
target is not the same kind of object as a number that was observed.

The fixtures live in the library (not only in ``tests/``) so that examples, the
CLI and the test suite all reproduce *the same* failures rather than three
drifting approximations of them.

Every fixture reproduces the figure it claims to reproduce -- the measured
number where the archive preserved it, and the stated target where it did not --
rather than a plausible approximation of either. The six ``ILLUSTRATIVE``
fixtures reproduce a *mechanism*, not a measurement, and their numbers are not
findings.

==================================  ===============  =======================================
fixture                             provenance       quantity
==================================  ===============  =======================================
:func:`copier_pnl`                  MEASURED         spread +0.1344, r = -0.598
:func:`roi`                         MEASURED         spread +1.0190, r = +0.43
:func:`nine_of_twelve`              ILLUSTRATIVE     mean -138.7, median +37.0, 9/12 wins
:func:`top_decile_121`              DERIVED          top 10% of trades = 121% of net PnL
:func:`top_decile_164`              ILLUSTRATIVE     top-10% share = 1.64
:func:`nested_four_split`           MEASURED_DESIGN  4 splits, one shared end date, 0 independent
:func:`disjoint_twelve`             MEASURED_DESIGN  12 disjoint 30-day windows from a 365-day panel
:func:`spliced_metrics`             ILLUSTRATIVE     365D cumulative spliced to 30D rolling
:func:`zero_padded_inception`       MEASURED         11-day-old portfolio with 365 points
:func:`left_edge_bar`               MEASURED         15m bar at t0 read as starting t0+1m
:func:`trade_level_false_positive`  ILLUSTRATIVE     CI [-0.021, +0.781] on 378 trades, 4 symbols
:func:`multiplicity_341`            DERIVED          341 configurations, 17.05 expected false positives
:func:`multiplicity_60`             ILLUSTRATIVE     60 configurations, 1 positive, ~3 expected
:func:`clean_control`               ILLUSTRATIVE     a genuinely clean control
==================================  ===============  =======================================

Provenance labels
-----------------
``MEASURED``
    The per-observation rows are the research archive's own rows, transcribed
    without adjustment. Running the guard over them recomputes the measured
    statistic; nothing was chosen to make that happen. This is the only label
    that asserts observations were observed, and it is reserved for the two
    look-ahead fixtures and the three series/panel fixtures that carry real
    archive rows.
``MEASURED_DESIGN``
    The *design* is the archive's -- the window geometry, the split spacing, the
    calendar construction -- but the per-observation values are not, because
    there may be none to measure. This label exists so that a real design is not
    silently upgraded to real data; the earlier draft labelled these MEASURED,
    which asserted more than the archive supports.
``DERIVED``
    The statistic is measured and the per-observation series reproduces it *by
    construction* -- the series is solved from the target, not observed. The
    archive preserved the summary but not the underlying rows.
``ILLUSTRATIVE``
    Neither the rows nor the statistic come from the archive. The fixture
    demonstrates a failure mechanism; the numbers are invented for that purpose
    and must not be quoted as findings.

Real per-split data exists for two of the look-ahead fixtures and they now use
it (``copier_pnl`` and ``roi``, 12 real splits each from
``research/edge-hunt/q4_results.json``). The tail-concentration fixture is
solved from the real measured share rather than measured, and the remaining
fixtures -- including ``top_decile_164``, whose supporting numbers exist in
``research/first-bar/shape_extras.json`` but whose per-week rows the archive did
not persist in a usable form -- are labelled accordingly.

The ``clean_*`` fixtures matter as much as the broken ones. A library that
rejects everything is not a validator.
"""

from __future__ import annotations

import math
import random
from datetime import date, datetime, timedelta
from typing import Callable

from .guards.lookahead import LookaheadGuard
from .guards.multiplicity import ExperimentCounter
from .guards.outliers import ConcentrationGuard
from .guards.series import SeriesGuard, detect_splice
from .guards.universe import Selection, UniverseGuard
from .guards.windows import WindowGuard, WindowPlan
from .stats.bootstrap import block_bootstrap_ci

__all__ = [
    # raw fixture data
    "COPIER_PNL",
    "ROI",
    "NINE_OF_TWELVE",
    "TOP_DECILE_121",
    "TOP_DECILE_164",
    "NESTED_FOUR_SPLIT",
    "DISJOINT_TWELVE",
    "SPLICED_METRICS",
    "ZERO_PADDED_INCEPTION",
    "LEFT_EDGE_BAR",
    "TRADE_LEVEL_FALSE_POSITIVE",
    "CLEAN_CONTROL",
    "PYPI_THREE_STATE_CORRECTED",
    "PYPI_SCAN_503",
    "CODE_SEARCH_NULL_WITHOUT_CONTROL",
    "NESTED_FOUR_SPLIT_ASYMMETRY",
    "DORMANT_ZERO_FORWARD_RETURNS",
    "GUARD_FIXTURES",
    "PROVENANCE",
    "PROVENANCE_MEASURED",
    "PROVENANCE_MEASURED_DESIGN",
    "PROVENANCE_DERIVED",
    "PROVENANCE_ILLUSTRATIVE",
    "render",
    "provenance",
    # builders
    "copier_pnl",
    "roi",
    "nine_of_twelve",
    "top_decile_121",
    "top_decile_164",
    "nested_four_split",
    "disjoint_twelve",
    "spliced_metrics",
    "zero_padded_inception",
    "left_edge_bar",
    "trade_level_false_positive",
    "clean_control",
    "clean_series",
    "evidence_negative_evidence",
    "evidence_corrected",
    "evidence_null_without_control",
    "comparison_asymmetric",
    "comparison_shared",
]

# ---------------------------------------------------------------------------
# 1. look-ahead: two contaminated predictors
# ---------------------------------------------------------------------------

#: ``copier_pnl`` -- apparent spread +0.1344, measured today, pure look-ahead.
#:
#: ``PROVENANCE = "MEASURED"``. The twelve per-split spreads and split dates are
#: the research archive's own rows, transcribed verbatim from
#: ``research/edge-hunt/q4_results.json``. Each split ranks the roster by
#: ``leaders.copier_pnl`` (a point-in-time field, as of the snapshot) and takes
#: the top-minus-bottom decile 30-day forward log return; ``n`` is the roster
#: size at that split.
#:
#: Nothing here was tuned. The distances are ``snapshot_date - split_date``
#: computed from the real split days, and the guard recomputes the measured
#: correlation from them: r = -0.5976.
#:
#: The effect is largest at the splits nearest the snapshot and decays with
#: distance -- the signature of a label that leaks the future. This is the one
#: library fixture whose r is *not* set: it falls out of the data.
COPIER_PNL: dict[str, object] = {
    "name": "copier_pnl",
    "apparent_spread": 0.1343666324745018,
    "expected_r": -0.598,
    "provenance": "MEASURED",
    "source": "research/edge-hunt/q4_results.json (key: copier_pnl)",
    "snapshot_date": date(2026, 9, 28),
    "splits": [
        # (split_day, roster n, top decile, bottom decile, spread, week)
        (20362, 1385, 0.08873832938554721, 0.0006622738556346725, 0.08807605552991253, 2909),
        (20392, 1673, 0.05781391397596576, -0.044474452316832495, 0.10228836629279825, 2913),
        (20422, 1906, 0.00039596793673503866, -0.07983824573267778, 0.08023421366941282, 2917),
        (20452, 2119, 0.026896957169036277, 0.013466257781450414, 0.013430699387585864, 2922),
        (20482, 2399, 0.02212871327396903, -0.22468471672711937, 0.2468134300010884, 2926),
        (20512, 2685, 0.023095438406331048, 0.012027080096285838, 0.01106835831004521, 2930),
        (20542, 3031, 0.08359898809180515, -0.014339999725520037, 0.09793898781732518, 2935),
        (20572, 3442, 0.04846610561385307, -0.057195893576459114, 0.10566199919031219, 2939),
        (20602, 3940, -0.0001435671179871588, -0.19732191434395963, 0.19717834722597247, 2943),
        (20632, 4468, 0.08678372782094367, -0.03230200462536688, 0.11908573244631054, 2947),
        (20662, 5172, 0.26661399544568537, 0.05945411185185779, 0.2071598835938276, 2952),
        (20692, 6616, 0.2013713666454472, -0.14209214958398345, 0.3434635162294306, 2956),
    ],
    # Derived from the rows above, not chosen: spread = top - bottom, and the
    # distances are (snapshot_date - split_day) in days. Kept explicit so the
    # guard's two inputs are inspectable without arithmetic.
    "effects": [
        0.08807605552991253,
        0.10228836629279825,
        0.08023421366941282,
        0.013430699387585864,
        0.2468134300010884,
        0.01106835831004521,
        0.09793898781732518,
        0.10566199919031219,
        0.19717834722597247,
        0.11908573244631054,
        0.2071598835938276,
        0.3434635162294306,
    ],
    "distances_days": [
        362.0,
        332.0,
        302.0,
        272.0,
        242.0,
        212.0,
        182.0,
        152.0,
        122.0,
        92.0,
        62.0,
        32.0,
    ],
    "measured_r": -0.597561,
}

#: ``roi`` -- apparent spread +1.0190, pure look-ahead, positive decay slope.
#:
#: ``PROVENANCE = "MEASURED"``, same archive file and same method as
#: :data:`COPIER_PNL`, with ``leaders.roi`` as the ranking field. The guard
#: recomputes r = +0.4285, matching the study's +0.43.
#:
#: The sign is opposite to ``copier_pnl``'s because the contamination enters
#: through a different construction, but it is the same mechanism: the measured
#: effect depends on when you measured it. Note what this one does *not* do --
#: it clears the 0.5 correlation threshold and is caught by the sign-flip
#: instrument instead, which is why the library ships both.
ROI: dict[str, object] = {
    "name": "roi",
    "apparent_spread": 1.0189864161700548,
    "expected_r": 0.43,
    "provenance": "MEASURED",
    "source": "research/edge-hunt/q4_results.json (key: roi)",
    "snapshot_date": date(2026, 9, 28),
    "splits": [
        # (split_day, roster n, top decile, bottom decile, spread, week)
        (20362, 1385, 0.2661221987519486, -1.6766453873422749, 1.9427675860942235, 2909),
        (20392, 1673, 0.19962861751905736, -1.5789282367936615, 1.7785568543127188, 2913),
        (20422, 1906, 0.027277146879908374, -0.6204131009117346, 0.647690247791643, 2917),
        (20452, 2119, 0.08457997296135723, -0.6387299296381806, 0.7233099025995379, 2922),
        (20482, 2399, 0.0918777932925726, -1.0397270229955353, 1.1316048162881078, 2926),
        (20512, 2685, 0.07696459463695893, -0.649261068422537, 0.7262256630594959, 2930),
        (20542, 3031, 0.13279925308850948, -0.6810743057482581, 0.8138735588367676, 2935),
        (20572, 3442, 0.08813130897364124, -0.3833854541385798, 0.471516763112221, 2939),
        (20602, 3940, 0.07778016040708811, -0.928630999818066, 1.006411160225154, 2943),
        (20632, 4468, 0.1446267082169143, -0.7196547181811027, 0.864281426398017, 2947),
        (20662, 5172, 0.46558381950231176, -0.5206810823878678, 0.9862649018901796, 2952),
        (20692, 6616, 0.4120706783120362, -0.7232634351205578, 1.135334113432594, 2956),
    ],
    "effects": [
        1.9427675860942235,
        1.7785568543127188,
        0.647690247791643,
        0.7233099025995379,
        1.1316048162881078,
        0.7262256630594959,
        0.8138735588367676,
        0.471516763112221,
        1.006411160225154,
        0.864281426398017,
        0.9862649018901796,
        1.135334113432594,
    ],
    "distances_days": [
        362.0,
        332.0,
        302.0,
        272.0,
        242.0,
        212.0,
        182.0,
        152.0,
        122.0,
        92.0,
        62.0,
        32.0,
    ],
    "measured_r": 0.428523,
}


def copier_pnl(*, r_threshold: float = 0.5) -> dict[str, object]:
    """Run the look-ahead guard on the ``copier_pnl`` fixture.

    ``provenance_ok`` is the fixture checking itself: the guard's recomputed
    ``r`` is compared against ``measured_r``, the figure the study published.
    A ``MEASURED`` fixture that no longer reproduces its own statistic is a
    defect, and this field is how the test suite says so out loud.
    """
    guard = LookaheadGuard(r_threshold=r_threshold, min_splits=5)
    report = guard.run(
        _floats(COPIER_PNL["effects"]), _floats(COPIER_PNL["distances_days"])
    )
    claimed = float(COPIER_PNL["measured_r"])  # type: ignore[arg-type]
    return {
        "fixture": "copier_pnl",
        "provenance": COPIER_PNL["provenance"],
        "source": COPIER_PNL["source"],
        "apparent_spread": COPIER_PNL["apparent_spread"],
        "expected_r": COPIER_PNL["expected_r"],
        "r": round(report.r, 4),
        "claimed_r": claimed,
        "provenance_ok": abs(report.r - claimed) < 5e-4,
        "n_splits": report.n_splits,
        "verdict": report.verdict.value,
        "detected": report.contaminated,
        "findings": [f.as_dict() for f in report.findings],
    }


def roi(*, r_threshold: float = 0.5) -> dict[str, object]:
    """Run the look-ahead guard on the ``roi`` fixture.

    Same self-check as :func:`copier_pnl`. Note the threshold: at the default
    ``0.5``, ``r = +0.4285`` does *not* clear the bar and the refusal comes from
    the sign-flip instrument instead. ``detected`` is therefore True via
    ``findings``, not via ``r`` -- do not read ``abs(r) >= threshold`` into it.
    """
    guard = LookaheadGuard(r_threshold=r_threshold, min_splits=5)
    report = guard.run(_floats(ROI["effects"]), _floats(ROI["distances_days"]))
    claimed = float(ROI["measured_r"])  # type: ignore[arg-type]
    return {
        "fixture": "roi",
        "provenance": ROI["provenance"],
        "source": ROI["source"],
        "apparent_spread": ROI["apparent_spread"],
        "expected_r": ROI["expected_r"],
        "r": round(report.r, 4),
        "claimed_r": claimed,
        "provenance_ok": abs(report.r - claimed) < 5e-4,
        "n_splits": report.n_splits,
        "sign_flipped": not (
            (report.near_mean is None or report.far_mean is None)
            or ((report.near_mean >= 0.0) == (report.far_mean >= 0.0))
        ),
        "verdict": report.verdict.value,
        "detected": report.contaminated,
        "findings": [f.as_dict() for f in report.findings],
    }


# ---------------------------------------------------------------------------
# 2. outliers
# ---------------------------------------------------------------------------

def _top_decile_pnls(
    *,
    top: list[float],
    target_share: float,
    rest_n: int,
    seed: int,
    noise: float = 0.40,
) -> list[float]:
    """Build a PnL series whose top decile is ``target_share`` of net PnL.

    Solved rather than tuned. With ``T = sum(top)`` and a share denominator of
    net PnL, ``share = T / net`` gives ``net = T / target_share``, and the
    remaining ``rest_n`` observations must therefore sum to ``net - T``. Since
    the target is above 1.0, that remainder is necessarily negative -- which is
    the entire point of the fixture, and why the construction is done in closed
    form instead of by searching for numbers that happen to work.

    A small amount of noise is applied to the remainder and then rescaled back
    to the exact required total, so the series looks like data rather than like
    a solved equation while still hitting the measured share exactly.
    """
    rng = random.Random(seed)
    head = math.fsum(top)
    net = head / target_share
    rest_total = net - head
    raw = [rest_total / rest_n * (1.0 + rng.gauss(0.0, noise)) for _ in range(rest_n)]
    scale = rest_total / math.fsum(raw)
    return list(top) + [x * scale for x in raw]


#: 9 of 12 windows won; mean excess -138.7, median +37.0.
#: The nine winners are small; the three losers are three orders larger.
#:
#: ``PROVENANCE = "ILLUSTRATIVE"``. The archive preserves this failure as a
#: narrative in ``research/edge-hunt/REPORT.md`` and ``research/alt-edges``
#: (the 4-month H3 fade study, 13/17 weeks positive, then -1128 bps in one
#: week), but not as a persisted 12-row window series. The twelve values below
#: were chosen to reproduce the published mean and median exactly (sum
#: -1664.4, middle pair averaging 37.0). They demonstrate the mechanism; they
#: are not the weeks that were measured and must not be quoted as such.
NINE_OF_TWELVE: dict[str, object] = {
    "name": "nine_of_twelve",
    "provenance": "ILLUSTRATIVE",
    "source": "mechanism from research/edge-hunt/REPORT.md; rows not persisted",
    "win_count": 9,
    "n_windows": 12,
    "mean_excess": -138.7,
    "median_excess": 37.0,
    # Nine small winners, three large losers. Sum = -1664.4, so mean = -138.7;
    # the 6th and 7th order statistics average 37.0, so median = +37.0. The mean
    # and the median point opposite ways, which is the alarm.
    "excesses": [
        41.0, 41.0, 52.0, 29.0, 44.0, 33.0, 61.0, 25.0, 48.0,
        -1534.0, -380.0, -124.0,
    ],
}

#: Top 10% of trades produced 121% of **net** PnL.
#:
#: ``PROVENANCE = "DERIVED"``. The share is the real measured figure from
#: ``research/alt-edges/out/h3_tail.json``
#: (``top_10pct_share_of_total_pnl = 121.31380884934697``), over n = 1909 fade
#: trades. The 100 per-trade PnLs are *solved from it* by
#: :func:`_top_decile_pnls` -- the archive kept the summary, not the trade rows.
#:
#: Reading note: the archive's own script divided the top-decile sum by the
#: gross mean, so its printed denominator is gross. That is not expressible as
#: the ``tail_threshold`` this guard applies, which warns on ``share >= 1.0``
#: -- and a gross-denominated share is bounded above by 1.0 exactly when the
#: remainder is non-negative, which never fires. The figure is only meaningful
#: with a net denominator. See ``guards/outliers.py`` for the full explanation;
#: this is a labelling defect in the archive's own printout, not a change to
#: the number.
TOP_DECILE_121: dict[str, object] = {
    "name": "top_decile_121",
    "provenance": "DERIVED",
    "source": "research/alt-edges/out/h3_tail.json (n = 1909, share = 1.2131)",
    "expected_share": 1.21,
    # Top decile (10 of 100) sums to 4570; net is 4570/1.21 = 3776.86, so the
    # remaining 90 observations net to -793.14. Remove the top decile and the
    # strategy is a loser -- which is what the real study found too: excluding
    # 2026-W36, the archive's net is +32.56 against a gross mean of +42.72.
    "pnls": _top_decile_pnls(
        top=[1450.0, 980.0, 640.0, 410.0, 320.0, 250.0, 180.0, 140.0, 110.0, 90.0],
        target_share=1.21,
        rest_n=90,
        seed=7,
    ),
}

#: A second study's 15m result: top-10% share 1.64.
#:
#: ``PROVENANCE = "ILLUSTRATIVE"``. The archive confirms the *mechanism* at this
#: magnitude -- ``research/first-bar/shape_extras.json`` records the carrying
#: weeks of the H3 fade as ``top3_share_of_sum = 0.9256`` (2026-06) and
#: ``0.5543`` (2026-08), and ``research/first-bar/REPORT_SHAPE.md`` §4 states
#: that the effect lives in ~4 of 17 weeks -- but no artifact persists a
#: per-observation series whose top decile is 1.64, and the 1.64 mapping is the
#: narrative's. The series below is solved from the target, as with
#: ``top_decile_121``, and must not be quoted as a finding.
TOP_DECILE_164: dict[str, object] = {
    "name": "top_decile_164",
    "provenance": "ILLUSTRATIVE",
    "source": "magnitude from research/first-bar/ (1.64 not persisted); rows solved",
    "expected_share": 1.64,
    # Top decile sums to 8050; net is 8050/1.64 = 4908.54, so the remaining 90
    # observations net to -3141.46.
    "pnls": _top_decile_pnls(
        top=[2600.0, 1900.0, 1200.0, 830.0, 470.0, 340.0, 260.0, 190.0, 150.0, 110.0],
        target_share=1.64,
        rest_n=90,
        seed=7,
    ),
}


def nine_of_twelve() -> dict[str, object]:
    """Run the mean/median disagreement check on the 9-of-12 fixture."""
    guard = ConcentrationGuard(min_obs=8)
    report = guard.check_windows(
        _floats(NINE_OF_TWELVE["excesses"]),
        win_count=int(NINE_OF_TWELVE["win_count"]),  # type: ignore[arg-type]
    )
    return {
        "fixture": "nine_of_twelve",
        "win_count": NINE_OF_TWELVE["win_count"],
        "mean_excess": round(report.mean_excess or 0.0, 2),
        "median_excess": round(report.median_excess or 0.0, 2),
        "signs_disagree": report.signs_disagree,
        "verdict": report.verdict.value,
        "findings": [f.as_dict() for f in report.findings],
    }


def top_decile_121() -> dict[str, object]:
    """Run the tail-concentration check on the 121%-of-gross fixture."""
    return _tail_fixture("top_decile_121", TOP_DECILE_121)


def top_decile_164() -> dict[str, object]:
    """Run the tail-concentration check on the 1.64-share fixture."""
    return _tail_fixture("top_decile_164", TOP_DECILE_164)


def _tail_fixture(name: str, spec: dict[str, object]) -> dict[str, object]:
    guard = ConcentrationGuard(top_fraction=0.10, tail_threshold=1.0)
    report = guard.check_trades(_floats(spec["pnls"]))
    pnls = _floats(spec["pnls"])
    share = report.top_share or 0.0
    net = math.fsum(pnls)
    ranked = sorted(pnls)
    cut = max(1, int(len(ranked) * 0.10))
    without = math.fsum(ranked[:-cut])
    return {
        "fixture": name,
        "provenance": spec["provenance"],
        "source": spec["source"],
        "expected_share": spec["expected_share"],
        "top_share": round(share, 4),
        "net_pnl": round(net, 2),
        "net_without_top_decile": round(without, 2),
        "loses_without_top_decile": without < 0.0,
        "verdict": report.verdict.value,
        "findings": [f.as_dict() for f in report.findings],
    }


# ---------------------------------------------------------------------------
# 3. windows
# ---------------------------------------------------------------------------

#: 4 splits, all sharing the same end date -> strictly nested -> 0 independent.
#:
#: ``PROVENANCE = "MEASURED_DESIGN"``. The claim is narrower than plain
#: ``MEASURED`` and is the honest one: what came from the archive is the
#: *design* -- a four-split walk-forward in which every split's evaluation
#: window ends at the same date (the snapshot), so the four "splits" are four
#: different start dates for one overlapping window, and the split count and
#: shared end date are the archive's. The per-observation ``effects`` are
#: invented: the guard's verdict here is decided by the window geometry, not by
#: the returns, so there is nothing to measure. Labelling this MEASURED would
#: have asserted that rows were observed when they were not.
NESTED_FOUR_SPLIT: dict[str, object] = {
    "name": "nested_four_split",
    "provenance": "MEASURED_DESIGN",
    "source": "archive's nested walk-forward design (all splits share the end date); effects illustrative",
    "claimed_splits": 4,
    "shared_end": date(2024, 7, 1),
    "starts": [date(2024, 1, 1), date(2024, 2, 1), date(2024, 3, 1), date(2024, 4, 1)],
    "effects": [-0.02, -0.01, 0.01, -0.03],
}

#: 365 days, 12 disjoint 30-day windows.
#:
#: ``PROVENANCE = "MEASURED_DESIGN"``. The 365D panel and the 30-day split
#: spacing are the archive's: ``research/edge-hunt/panel365.py`` builds exactly
#: this panel and ``q45_run.py`` steps splits by 30 days through it
#: (``range(60, n_days-1, 30)``), producing the 12 real split rows in
#: ``q4_results.json``. What is not the archive's is the calendar anchor: the
#: absolute dates are illustrative, because the archive's day indices are not
#: wall-clock dates. The shape -- 12 non-overlapping 30-day windows inside one
#: year -- is the design that was run. This fixture carries no per-observation
#: rows at all, which is why the label claims the design rather than the data.
DISJOINT_TWELVE: dict[str, object] = {
    "name": "disjoint_twelve",
    "provenance": "MEASURED_DESIGN",
    "source": "research/edge-hunt/panel365.py + q45_run.py (30-day spacing); calendar anchor illustrative",
    "panel_start": date(2024, 1, 1),
    "panel_end": date(2024, 12, 31),
    "window_days": 30,
    "expected_independent": 12,
}


def _nested_plan() -> WindowPlan:
    from .plans import Window

    starts = NESTED_FOUR_SPLIT["starts"]
    end = NESTED_FOUR_SPLIT["shared_end"]
    assert isinstance(starts, list) and isinstance(end, date)
    return WindowPlan(
        windows=tuple(
            Window(start=s, end=end, label=f"split{i + 1}")  # type: ignore[arg-type]
            for i, s in enumerate(starts)
        ),
        label="nested_four_split",
        claimed=4,
    )


def _disjoint_plan() -> WindowPlan:
    return WindowPlan.tiled(
        DISJOINT_TWELVE["panel_start"],  # type: ignore[arg-type]
        DISJOINT_TWELVE["panel_end"],  # type: ignore[arg-type]
        length_days=int(DISJOINT_TWELVE["window_days"]),  # type: ignore[arg-type]
        label="disjoint_twelve",
    )


def nested_four_split() -> dict[str, object]:
    """Run the independence guard on the nested 4-split fixture."""
    plan = _nested_plan()
    report = WindowGuard(min_independent=2).run(plan)
    return {
        "fixture": "nested_four_split",
        "claimed_splits": 4,
        "n_windows": len(plan),
        "fully_nested": plan.fully_nested,
        "independent_count": report.independent_count,
        "verdict": report.verdict.value,
        "findings": [f.as_dict() for f in report.findings],
    }


def disjoint_twelve() -> dict[str, object]:
    """Run the independence guard on the 12-disjoint-window fixture."""
    plan = _disjoint_plan()
    report = WindowGuard(min_independent=2).run(plan)
    return {
        "fixture": "disjoint_twelve",
        "n_windows": len(plan),
        "independent_count": report.independent_count,
        "max_disjoint": plan.max_disjoint(),
        "span_days": plan.span_days(),
        "verdict": report.verdict.value,
        "findings": [f.as_dict() for f in report.findings],
    }


# ---------------------------------------------------------------------------
# 4. universe asymmetry
# ---------------------------------------------------------------------------

#: Cohort filtered for staleness; benchmark filter omitted the same clause.
#: Dormant subjects have a flat 0% forward return, dragging the benchmark to
#: zero and making the cohort look skilful.
STALE_THRESHOLD_DAYS = 30


def _eligible(subject: dict[str, object]) -> bool:
    """The *correct* shared predicate: drop stale and dormant subjects."""
    age = int(subject.get("age_days", 0))  # type: ignore[arg-type]
    dormant = bool(subject.get("dormant", False))
    return age >= STALE_THRESHOLD_DAYS and not dormant


def _cohort_only_predicate(subject: dict[str, object]) -> bool:
    """The defect: staleness excluded on the cohort side only."""
    age = int(subject.get("age_days", 0))  # type: ignore[arg-type]
    return age >= STALE_THRESHOLD_DAYS


def universe_asymmetric() -> dict[str, object]:
    """Reproduce the cohort/benchmark asymmetry."""
    report = UniverseGuard(require_identical_object=True).run(
        Selection(name="cohort", predicate=_eligible, selected=("a", "b", "c")),
        Selection(
            name="benchmark", predicate=_cohort_only_predicate, selected=("a", "b", "c", "d")
        ),
    )
    return {
        "fixture": "universe_asymmetric",
        "verdict": report.verdict.value,
        "findings": [f.as_dict() for f in report.findings],
    }


# ---------------------------------------------------------------------------
# 5. multiplicity
# ---------------------------------------------------------------------------

#: 341 configurations evaluated; ~17 false positives expected at alpha = 0.05.
#:
#: ``PROVENANCE = "DERIVED"``. The arithmetic is real and the figure is the
#: study's: 341 configurations at alpha = 0.05 imply 341 x 0.05 = 17.05
#: expected false positives. What is *not* an archive row is the configuration
#: list -- the builder records ``config-0``..``config-340`` synthetically,
#: because the point of the fixture is the family size, not the identities.
#:
#: Two honest caveats, recorded because the fixture previously overstated them.
#: (1) The nearest archive artifact, ``alt-edges/out/h1_xs.json``, records
#: ``counts.total = 234`` for the H1 cross-sectional family, not 341; 341 is the
#: project-wide configuration count, and the two are not reconciled by any
#: artifact I recovered. (2) ``n_nominal_positives = 16`` and ``claimed_p =
#: 0.03`` are asserted, not sourced. Neither affects the guard's arithmetic,
#: but neither is measured either.
MULTIPLICITY_341: dict[str, object] = {
    "name": "multiplicity_341",
    "provenance": "DERIVED",
    "source": "341-config family (project-wide count; not reconciled with h1_xs counts.total=234); config rows constructed",
    "n_experiments": 341,
    "alpha": 0.05,
    "expected_false_positives": 17.05,
    "claimed_p": 0.03,
    "n_nominal_positives": 16,
}

#: 60 configurations, one positive, ~3 expected.
MULTIPLICITY_60: dict[str, object] = {
    "name": "multiplicity_60",
    "provenance": "ILLUSTRATIVE",
    "source": "smaller-family variant; neither the 60-configuration count nor the rows are persisted",
    "n_experiments": 60,
    "alpha": 0.05,
    "expected_false_positives": 3.0,
    "claimed_p": 0.041,
    "n_nominal_positives": 1,
}


def multiplicity_341() -> dict[str, object]:
    """Run the family-wise accounting on the 341-configuration study."""
    counter = ExperimentCounter(alpha=0.05)
    for i in range(int(MULTIPLICITY_341["n_experiments"])):  # type: ignore[arg-type]
        counter.record(f"config-{i}")
    report = counter.report(
        claimed_p=float(MULTIPLICITY_341["claimed_p"]),  # type: ignore[arg-type]
        n_nominal_positives=int(MULTIPLICITY_341["n_nominal_positives"]),  # type: ignore[arg-type]
    )
    return {
        "fixture": "multiplicity_341",
        "n_experiments": report.n_experiments,
        "expected_false_positives": report.expected_false_positives,
        "n_nominal_positives": report.n_nominal_positives,
        "claimed_p": report.original_p,
        "adjusted_p": report.adjusted_p,
        "verdict": report.verdict.value,
        "findings": [f.as_dict() for f in report.findings],
    }


# ---------------------------------------------------------------------------
# 6. series
# ---------------------------------------------------------------------------

#: A 365-day trailing-cumulative metric spliced onto a 30-day rolling one.
#: Differencing across the splice fabricated a -24,046 pp "daily return".
SPLICED_METRICS: dict[str, object] = {
    "name": "spliced_metrics",
    "provenance": "ILLUSTRATIVE",
    "source": "the 365D->30D splice is the archive's metric pair; the -24,046 pp level is not persisted",
    "fabricated_daily_return_pp": -24046.0,
    "left_metric": "365D trailing-cumulative",
    "right_metric": "30D rolling-window",
}

#: A portfolio 11 days old that returned 365 points.
ZERO_PADDED_INCEPTION: dict[str, object] = {
    "name": "zero_padded_inception",
    "provenance": "MEASURED",
    "source": "research/edge-hunt/panel_full.py (365 points/leader, leading zeros contiguous)",
    "age_days": 11,
    "n_points_returned": 365,
    "padding": 354,
}

#: A 15m bar labelled t0 spans [t0, t0+15m); reading a forward bar as
#: starting at t0+1m produced a 185 bps error.
LEFT_EDGE_BAR: dict[str, object] = {
    "name": "left_edge_bar",
    "provenance": "MEASURED",
    "source": "research/first-bar/REPORT_SHAPE.md section 5 (185 bps discrepancy, t0+15m not t0+1m)",
    "bar_span_minutes": 15,
    "assumed_offset_minutes": 1,
    "measured_error_bps": 185.0,
}


def _spliced_series() -> list[float]:
    """Build a realistic spliced level series.

    Segment one is a slow, low-variance cumulative level (the 365D metric).
    Segment two is a rolling-window level that, by construction, sits at a
    completely different altitude. The join between them is one enormous step
    inconsistent with both segments' local variation -- and differencing across
    that join is what produced the -24,046 pp figure.
    """
    rng = random.Random(20240101)
    left = [100.0]
    for _ in range(119):
        left.append(left[-1] + rng.gauss(0.0, 0.35))
    # The splice: the rolling metric re-bases, so the next level is far away.
    right_start = left[-1] - 24046.0
    right = [right_start]
    for _ in range(119):
        right.append(right[-1] + rng.gauss(0.0, 0.30))
    return left + right


def spliced_metrics() -> dict[str, object]:
    """Run the splice detector on the fabricated -24,046 pp series."""
    values = _spliced_series()
    report = detect_splice(values, threshold=25.0)
    fabricated = None
    if report.index is not None:
        fabricated = values[report.index + 1] - values[report.index]
    return {
        "fixture": "spliced_metrics",
        "expected_fabricated_daily_return_pp": SPLICED_METRICS[
            "fabricated_daily_return_pp"
        ],
        "n_points": len(values),
        "detected": report.detected,
        "splice_index": report.index,
        "jump": None if fabricated is None else round(fabricated, 3),
        "local_scale": None if report.local_scale is None else round(report.local_scale, 4),
        "ratio": None if report.ratio is None else round(report.ratio, 1),
        "verdict": report.verdict.value,
        "findings": [f.as_dict() for f in report.findings],
    }


def zero_padded_inception() -> dict[str, object]:
    """Reproduce the zero-padded track record."""
    guard = SeriesGuard()
    padded = [0.0] * 354 + [float(i) for i in range(1, 12)]
    report = guard.check_padding(padded, padding_value=0.0)
    from .guards.series import truncate_leading_padding

    usable, dropped = truncate_leading_padding(padded, padding_value=0.0)
    return {
        "fixture": "zero_padded_inception",
        "n_points": len(padded),
        "padding_detected": dropped,
        "usable_points": len(usable),
        "fraction": round(dropped / len(padded), 4),
        "verdict": report.verdict.value,
        "findings": [f.as_dict() for f in report.findings],
    }


def left_edge_bar() -> dict[str, object]:
    """Reproduce the left-edge timestamp error."""
    from .guards.series import forward_bar_offset, left_edge_window

    span = timedelta(minutes=int(LEFT_EDGE_BAR["bar_span_minutes"]))  # type: ignore[arg-type]
    assumed = timedelta(minutes=int(LEFT_EDGE_BAR["assumed_offset_minutes"]))  # type: ignore[arg-type]
    t0 = datetime(2024, 3, 1, 9, 30)
    start, end = left_edge_window(t0, span)
    correct, timing_bps = forward_bar_offset(t0, span, assumed_offset=assumed)
    return {
        "fixture": "left_edge_bar",
        "t0": t0.isoformat(),
        "covered_interval": f"[{start.isoformat()}, {end.isoformat()})",
        "correct_forward_start": correct.isoformat(),
        "assumed_forward_start": (t0 + assumed).isoformat(),
        "timing_error_bps": round(timing_bps, 1),
        "measured_price_error_bps": LEFT_EDGE_BAR["measured_error_bps"],
        "verdict": "REFUSED",
        "findings": [
            {
                "code": "SERIES_LEFT_EDGE_WINDOW",
                "message": (
                    f"a {int(span.total_seconds() // 60)}m bar labelled {t0.isoformat()} "
                    f"covers [{start.isoformat()}, {end.isoformat()}); reading the "
                    f"next bar as starting at {(t0 + assumed).isoformat()} assumes a "
                    f"forward bar begins inside the current one, a timing error of "
                    f"{timing_bps:,.0f} bps"
                ),
                "status": "FAIL",
                "severity": "BLOCKING",
            }
        ],
    }


# ---------------------------------------------------------------------------
# 7. bootstrap
# ---------------------------------------------------------------------------

#: A naive trade-level CI promoted a false positive to a strategy: the interval
#: [-0.021, +0.781] on 378 trades, from 4 symbols in a one-month artifact.
TRADE_LEVEL_FALSE_POSITIVE: dict[str, object] = {
    "name": "trade_level_false_positive",
    "provenance": "ILLUSTRATIVE",
    "source": "the 4-symbol one-month artifact shape; the CI and trade count are not persisted",
    "naive_ci": (-0.021, 0.781),
    "n_trades": 378,
    "n_symbols": 4,
    "n_days": 21,
    "n_weeks": 4,
}


def trade_level_false_positive(*, seed: int = 7) -> dict[str, object]:
    """Compare a naive trade-level CI to the block bootstrap on 378 trades.

    The synthetic generator reproduces the *structure* of the artifact that
    produced the bad interval: 4 symbols, ~1 month, all trades sharing a handful
    of weekly regimes. The naive interval is computed by treating every trade
    as independent; the block bootstrap is computed by resampling whole weeks.
    """
    rng = random.Random(seed)
    start = date(2024, 3, 4)  # a Monday
    n_weeks = int(TRADE_LEVEL_FALSE_POSITIVE["n_weeks"])  # type: ignore[arg-type]
    n_symbols = int(TRADE_LEVEL_FALSE_POSITIVE["n_symbols"])  # type: ignore[arg-type]
    target_trades = int(TRADE_LEVEL_FALSE_POSITIVE["n_trades"])  # type: ignore[arg-type]

    # One shared weekly mean drives everything: this is the dependence a
    # trade-level bootstrap ignores and a block bootstrap preserves.
    weekly_means = [rng.gauss(0.35, 1.15) for _ in range(n_weeks)]
    days: list[date] = []
    values: list[float] = []
    # Spread the target trade count across the weeks exactly, giving the first
    # weeks the remainder. Approximating here would silently change the
    # headline number (378) that makes the fixture recognisable.
    per_week = [target_trades // n_weeks] * n_weeks
    for w in range(target_trades % n_weeks):
        per_week[w] += 1
    for w in range(n_weeks):
        for i in range(per_week[w]):
            days.append(start + timedelta(days=w * 7 + (i % 5)))
            symbol_shift = rng.gauss(0.0, 0.25) * (1 + i % n_symbols)
            values.append(weekly_means[w] + symbol_shift + rng.gauss(0.0, 0.9))

    block = block_bootstrap_ci(
        values,
        block_dates=days,
        anchor="monday",
        confidence=0.95,
        n_resamples=2000,
        min_blocks=10,
        seed=seed,
    )
    naive_low, naive_high = _naive_trade_ci(values, confidence=0.95, seed=seed)
    return {
        "fixture": "trade_level_false_positive",
        "n_trades": len(values),
        "n_symbols": n_symbols,
        "recorded_naive_ci": list(TRADE_LEVEL_FALSE_POSITIVE["naive_ci"]),  # type: ignore[arg-type]
        "naive_ci": [round(naive_low, 4), round(naive_high, 4)],
        "naive_excludes_zero": (naive_low > 0 and naive_high > 0)
        or (naive_low < 0 and naive_high < 0),
        "block_ci": [round(block.low, 4), round(block.high, 4)],
        "n_blocks": block.n_blocks,
        "min_blocks": block.min_blocks,
        "block_verdict": block.verdict.value,
        "naive_comparison": block.naive_comparison,
        "findings": [f.as_dict() for f in block.findings],
    }


def _naive_trade_ci(
    values: list[float], *, confidence: float = 0.95, seed: int = 0
) -> tuple[float, float]:
    """IID trade-level bootstrap -- the method this library replaces.

    Implemented here so the comparison in the example is live rather than
    quoted from a slide.
    """
    rng = random.Random(seed)
    n = len(values)
    draws: list[float] = []
    for _ in range(2000):
        sample = [values[rng.randrange(n)] for _ in range(n)]
        draws.append(math.fsum(sample) / n)
    draws.sort()
    lo = draws[int(0.025 * len(draws))]
    hi = draws[int(0.975 * len(draws)) - 1]
    return lo, hi


# ---------------------------------------------------------------------------
# 8. evidence presence: the 503 read as a 404
# ---------------------------------------------------------------------------

#: The corrected three-state package-availability scan: fifteen PRESENT, eight
#: genuine 404s, and two recorded honestly as ``UNKNOWN`` rather than as absent.
#:
#: ``PROVENANCE = "MEASURED"``. The twenty-five observations are transcribed from
#: ``/tmp/pypi_fixed.json``, the artifact the corrected scan wrote on
#: 2026-09-28, which classified each name as ``PRESENT`` (HTTP 200), ``ABSENT``
#: (HTTP 404 from both endpoints after retries) or ``UNKNOWN`` (everything
#: else). Every ``code`` below is that file's own ``code`` field, and the row
#: order is that file's own order; nothing was rounded, tidied, or inferred.
#:
#: The two ``UNKNOWN`` rows are the ones the earlier scan got wrong in the
#: opposite direction from what one might expect: ``overfit-diagnostic`` and
#: ``purgekit`` produced *404s that the corrected run still refused to call
#: absent*, because a 404 from a single endpoint is not a resolution when the
#: other endpoint never answered. That is the honest reading and it is preserved
#: verbatim, including the fact that it makes the corrected scan less decisive
#: than a naive pass over the same bytes would be.
#:
#: This fixture is the *clean* direction: it must not be refused.
PYPI_THREE_STATE_CORRECTED: dict[str, object] = {
    "name": "pypi_three_state_corrected",
    "provenance": "MEASURED",
    "source": "/tmp/pypi_fixed.json (scan run 2026-09-28, artifact /tmp/pypi_fix.py)",
    "scanned_on": date(2026, 9, 28),
    "n_observations": 25,
    "measured_counts": {"PRESENT": 15, "ABSENT": 8, "UNKNOWN": 2},
    # (subject, state as the artifact recorded it, the artifact's own code)
    "observations": [
        ("pbo", "ABSENT", "404"),
        ("cscv", "ABSENT", "404"),
        ("overfit", "PRESENT", "200"),
        ("backtest-overfitting", "ABSENT", "404"),
        ("deflated-sharpe", "PRESENT", "200"),
        ("probabilistic-sharpe", "ABSENT", "404"),
        ("pypbo", "ABSENT", "404"),
        ("quantstats", "PRESENT", "200"),
        ("mlfinlab", "PRESENT", "200"),
        ("skfolio", "PRESENT", "200"),
        ("vectorbt", "PRESENT", "200"),
        ("bt", "PRESENT", "200"),
        ("backtrader", "PRESENT", "200"),
        ("empyrical", "PRESENT", "200"),
        ("quantstats-lumi", "PRESENT", "200"),
        ("freqtrade", "PRESENT", "200"),
        ("deflated_sharpe", "PRESENT", "200"),
        ("probabilistic_sharpe_ratio", "ABSENT", "404"),
        ("pyfolio", "PRESENT", "200"),
        ("riskfolio-lib", "PRESENT", "200"),
        ("pypbo-cscv", "ABSENT", "404"),
        ("backtest-overfit", "ABSENT", "404"),
        # The two the corrected run refused to resolve, recorded as such.
        ("overfit-diagnostic", "UNKNOWN", "404"),
        ("purgekit", "UNKNOWN", "404"),
        ("skepsis", "PRESENT", "200"),
    ],
    # The five names the earlier draft listed as absent, four of which resolve.
    "measured_correction": {
        "declared_absent_by_broken_scan": ["pbo", "cscv", "overfit", "probabilistic-sharpe",
                                           "backtest-overfit"],
        "still_absent_after_correction": ["pbo", "cscv", "probabilistic-sharpe",
                                          "backtest-overfit"],
        "actually_present": ["overfit"],
    },
}

#: The broken scan: 503s written down as ``{"exists": false}``.
#:
#: ``PROVENANCE = "MEASURED"``. Transcribed from ``/tmp/pypi_scan.json``, the
#: artifact of the defect. Five names returned HTTP 503 and the scan recorded
#: each of them as absent -- ``pbo``, ``cscv``, ``overfit``,
#: ``probabilistic-sharpe`` and ``backtest-overfit``. One of them (``overfit``)
#: is present on PyPI; the corrected scan above resolves it to ``PRESENT``.
#:
#: One transcription note, because it matters: the artifact's *successful* rows
#: carry **no** ``code`` field at all -- the scan wrote ``code`` only on the
#: error path, which is itself part of how the two outcomes came to look alike.
#: Those rows are recorded below with the code ``"present-no-code-recorded"``
#: rather than ``"200"``. Writing ``"200"`` would have been a small, tidy
#: fabrication in a fixture whose entire subject is a small tidy fabrication,
#: and the guard classifies an unrecognised code as ``UNKNOWN``, which is the
#: honest reading of "the artifact never said".
#:
#: This is the *broken* direction: the guard must refuse it.
PYPI_SCAN_503: dict[str, object] = {
    "name": "pypi_scan_503",
    "provenance": "MEASURED",
    "source": "/tmp/pypi_scan.json (scan run 2026-09-28, artifact /tmp/pypi_scan.py)",
    "scanned_on": date(2026, 9, 28),
    "n_observations": 22,
    # (subject, the scan's `exists` verdict, the code field it recorded)
    # 503 rows first: these are the defect, verbatim.
    "observations": [
        ("pbo", False, "503"),
        ("cscv", False, "503"),
        ("overfit", False, "503"),
        ("backtest-overfitting", False, "404"),
        ("deflated-sharpe", True, "present-no-code-recorded"),
        ("probabilistic-sharpe", False, "503"),
        ("pypbo", False, "404"),
        ("quantstats", True, "present-no-code-recorded"),
        ("mlfinlab", False, "404"),
        ("skfolio", True, "present-no-code-recorded"),
        ("vectorbt", True, "present-no-code-recorded"),
        ("bt", True, "present-no-code-recorded"),
        ("backtrader", True, "present-no-code-recorded"),
        ("empyrical", True, "present-no-code-recorded"),
        ("quantstats-lumi", True, "present-no-code-recorded"),
        ("freqtrade", True, "present-no-code-recorded"),
        ("deflated_sharpe", True, "present-no-code-recorded"),
        ("probabilistic_sharpe_ratio", False, "404"),
        ("pyfolio", True, "present-no-code-recorded"),
        ("riskfolio-lib", True, "present-no-code-recorded"),
        ("pypbo-cscv", False, "404"),
        ("backtest-overfit", False, "503"),
    ],
    # The blanket claim the broken scan supported, stated as the claim it was.
    "measured_claim": "the names that returned a non-200 are absent from PyPI",
}

#: A code-search instrument whose control queries prove it was broken.
#:
#: ``PROVENANCE = "ILLUSTRATIVE"``. This is the part the brief asked to be
#: marked honestly if the artifacts could not be found: **they were not found.**
#: The Sourcegraph control-query result (``lang:python "def sharpe_ratio"`` ->
#: 0, ``numba`` -> 1) is described in the study narrative but no captured output
#: of those two queries survives on disk, so the two zero counts below are
#: recorded as the narrative states them and the fixture is labelled
#: ``ILLUSTRATIVE`` rather than ``MEASURED``. The *mechanism* is the finding;
#: these two numbers are not.
#:
#: What is real and on disk: the decider number moved from a false **4** to
#: **10-18** once the zeros were discarded -- recorded in
#: ``measured_correction`` so the consequence is not lost with the evidence.
CODE_SEARCH_NULL_WITHOUT_CONTROL: dict[str, object] = {
    "name": "code_search_null_without_control",
    "provenance": "ILLUSTRATIVE",
    "source": (
        "study narrative; the two control-query counts are NOT persisted in any "
        "recovered artifact, so they are illustrative. Only the 4 -> 10-18 "
        "correction is transcribed"
    ),
    "measured_correction": {"false_decider": 4, "corrected_decider_low": 10,
                            "corrected_decider_high": 18},
    # (subject, the tool's reported match count, note)
    "observations": [
        ("def sharpe_ratio [lang:python]", "0",
         "the target query -- read as 'nobody does this'"),
        ("numba", "1",
         "the control -- a term guaranteed to appear across thousands of "
         "repositories returning 1 match is what proves the instrument, not "
         "the world, produced the zero"),
    ],
    "claimed_absent": ["def sharpe_ratio [lang:python]"],
    "negative_claim": "no repository implements this, so there is no prior art",
    # The control is deliberately *broken*: `numba` is a known-positive input
    # whose probe returned a near-zero count, so it must NOT be treated as a
    # successful control. A working control on the same instrument would be a
    # match count in the hundreds or thousands.
    "control_subject": "numba",
    "control_returned": "1",
    "expected_control_min_count": 100,
}


def evidence_negative_evidence() -> dict[str, object]:
    """Run the evidence guard on the broken 503 scan (must refuse)."""
    from .guards.evidence import EvidenceGuard, Observation

    rows = PYPI_SCAN_503["observations"]
    assert isinstance(rows, list)
    observations = tuple(
        Observation(subject=str(subject), code=str(code), note=f"scan said exists={exists}")
        for subject, exists, code in rows
    )
    # The scan's own declaration: every non-200 row was read as absent.
    claimed = tuple(str(subject) for subject, exists, _ in rows if exists is False)
    report = EvidenceGuard(
        negative_claim=str(PYPI_SCAN_503["measured_claim"]),
        # The artifact recorded no code on its success path, so its own "found
        # it" rows cannot be read as PRESENT without assuming the code it never
        # wrote. Supply the one control the artifact does support: a 200 from
        # the same endpoint, which the corrected scan recorded for these names.
        code_classes={"PRESENT-NO-CODE-RECORDED": "UNKNOWN"},
    ).run(
        observations,
        claimed_absent=claimed,
        controls=(
            Observation(subject="deflated-sharpe", code="200",
                        note="known-present control (PyPI JSON API)"),
        ),
    )
    return {
        "fixture": "pypi_scan_503",
        "provenance": PYPI_SCAN_503["provenance"],
        "source": PYPI_SCAN_503["source"],
        "n_observations": report.n_observations,
        "n_present": report.n_present,
        "n_absent": report.n_absent,
        "n_unknown": report.n_unknown,
        "conclusive_fraction": round(report.conclusive_fraction, 4),
        "claimed_absent": list(claimed),
        "verdict": report.verdict.value,
        "findings": [f.as_dict() for f in report.findings],
    }


def evidence_corrected() -> dict[str, object]:
    """Run the evidence guard on the corrected three-state scan (must pass)."""
    from .guards.evidence import EvidenceGuard, Observation

    rows = PYPI_THREE_STATE_CORRECTED["observations"]
    assert isinstance(rows, list)
    # The artifact's three-state vocabulary is its own: it wrote a `state` of
    # PRESENT / ABSENT / UNKNOWN and, separately, the HTTP code it last saw.
    # Reading only the code would lose the resolution: `overfit-diagnostic` and
    # `purgekit` carry a bare `404` while the artifact's own state for them is
    # `UNKNOWN`, because one endpoint answered 404 and the other never answered
    # at all. Classifying the *state* the run recorded is the faithful reading;
    # classifying the code would upgrade two honest unknowns to absences and
    # make the corrected scan look more decisive than it was.
    observations = tuple(
        Observation(subject=str(subject), code=str(state).upper(), note=str(state))
        for subject, state, _code in rows
    )
    report = EvidenceGuard().run(
        observations,
        controls=(
            Observation(subject="deflated-sharpe", code="200",
                        note="known-present positive control"),
        ),
    )
    return {
        "fixture": "pypi_three_state_corrected",
        "provenance": PYPI_THREE_STATE_CORRECTED["provenance"],
        "source": PYPI_THREE_STATE_CORRECTED["source"],
        "n_observations": report.n_observations,
        "n_present": report.n_present,
        "n_absent": report.n_absent,
        "n_unknown": report.n_unknown,
        "conclusive_fraction": round(report.conclusive_fraction, 4),
        "controlled": report.controlled,
        "control_subject": report.control_subject,
        "verdict": report.verdict.value,
        "findings": [f.as_dict() for f in report.findings],
    }


def evidence_null_without_control() -> dict[str, object]:
    """The code-search null: a zero read as absence, with a broken control."""
    from .guards.evidence import EvidenceGuard, Observation

    rows = CODE_SEARCH_NULL_WITHOUT_CONTROL["observations"]
    claimed = CODE_SEARCH_NULL_WITHOUT_CONTROL["claimed_absent"]
    assert isinstance(rows, list) and isinstance(claimed, list)
    observations = tuple(
        Observation(subject=str(subject), code=str(code), note=str(note))
        for subject, code, note in rows
    )
    # Match counts are not status codes, so the table is declared outright: a
    # count is PRESENT only when the instrument returned matches at all.
    classes = {"0": "UNKNOWN", "1": "PRESENT"}
    report = EvidenceGuard(
        negative_claim=str(CODE_SEARCH_NULL_WITHOUT_CONTROL["negative_claim"]),
        code_classes=classes,
    ).run(observations, claimed_absent=tuple(str(c) for c in claimed))

    # The control probe, evaluated on its own. `numba` is a known-positive
    # input; a working search instrument returns hundreds or thousands of
    # matches for it. Returning 1 means the instrument is broken, so this
    # control *fails* -- and a failed control is the whole finding, not a
    # caveat. The same near-zero code that classifies as PRESENT in the
    # presence table (`count >= 1` means matches were returned) is a failure
    # against the control's own expected magnitude.
    control_count = int(CODE_SEARCH_NULL_WITHOUT_CONTROL["control_returned"])  # type: ignore[arg-type]
    expected_min = int(CODE_SEARCH_NULL_WITHOUT_CONTROL["expected_control_min_count"])  # type: ignore[arg-type]
    control_passed = control_count >= expected_min
    return {
        "fixture": "code_search_null_without_control",
        "provenance": CODE_SEARCH_NULL_WITHOUT_CONTROL["provenance"],
        "source": CODE_SEARCH_NULL_WITHOUT_CONTROL["source"],
        "measured_correction": CODE_SEARCH_NULL_WITHOUT_CONTROL["measured_correction"],
        "n_present": report.n_present,
        "n_absent": report.n_absent,
        "n_unknown": report.n_unknown,
        "control_subject": CODE_SEARCH_NULL_WITHOUT_CONTROL["control_subject"],
        "control_count": control_count,
        "control_expected_min": expected_min,
        "control_passed": control_passed,
        "verdict": report.verdict.value,
        "findings": [f.as_dict() for f in report.findings],
    }


# ---------------------------------------------------------------------------
# 9. shared selection predicate: the false "POSITIVE 4/4 splits"
# ---------------------------------------------------------------------------
#: The nested four-split design, with the cohort/benchmark asymmetry in it.
#:
#: ``PROVENANCE = "MEASURED_DESIGN"``, and the same label as
#: :data:`NESTED_FOUR_SPLIT` because it is the same design: the four splits, the
#: shared end date of 2026-09-28 and the two-tag eligibility rule are the
#: study's, preserved in ``NESTED_FOUR_SPLIT``. The per-split cohort and
#: benchmark aggregates are transcribed from the retraction table in
#: ``copytrade/README.md`` section 6.2 (``bench`` 18.3 / 26.1 / 16.0 / 11.7 and
#: ``mean_fwd`` -330.4 / -452.6 / -510.7 / -1135.7), which are real reported
#: figures for that run, and ``excess`` reproduces them by subtraction.
#:
#: The four *subjects* are not archive rows -- no per-subject table survives for
#: that run -- so the population members below are representative counts
#: (``eligible`` 1256 / 1604 / 2184 / 3151, transcribed) rather than observed
#: rows. The declared predicates are the ones the section 6.4 correction notice
#: names: the cohort excluded stale and dormant leaders, the benchmark did not,
#: and both sides now call ``_eligible_as_of()``.
#:
#: What is measured here and worth noting: in **all four** splits the benchmark
#: mean is positive while the cohort mean is between -330 and -1136, so the
#: asymmetry was present in every split the earlier draft counted as a
#: confirmation.
NESTED_FOUR_SPLIT_ASYMMETRY: dict[str, object] = {
    "name": "nested_four_split_asymmetry",
    "provenance": "MEASURED_DESIGN",
    "source": (
        "copytrade/README.md section 6.2 retraction table (4 nested splits, "
        "shared end 2026-09-28); per-subject rows illustrative"
    ),
    "shared_end": date(2026, 9, 28),
    "claimed": "POSITIVE 4/4 splits",
    "independent_windows": 0,
    "min_independent_windows": 6,
    # (split, fwd_days, eligible, mean_fwd, median_fwd, hit_pct, bench, excess)
    "splits": [
        ("2025-12-10", 292, 1256, -330.4, -200.1, 0.0, 18.3, -348.7),
        ("2026-02-21", 219, 1604, -452.6, -265.6, 0.0, 26.1, -478.7),
        ("2026-05-05", 146, 2184, -510.7, -483.5, 10.0, 16.0, -526.7),
        ("2026-07-17", 73, 3151, -1135.7, -968.7, 5.0, 11.7, -1147.4),
    ],
    "cohort_predicate": "eligible_as_of",
    "cohort_clauses": (
        "history_days >= min_history_days",
        "not stale",
        "first_ts <= split_ts",
        "not frozen as of split_ts",
    ),
    "benchmark_predicate": "benchmark_filter",
    "benchmark_clauses": ("history_days >= min_history_days",),
}

#: Dormant subjects as the study defines them: a flat 0% forward return.
#:
#: ``PROVENANCE = "ILLUSTRATIVE"``. The *rule* is real -- ``copytrade/backtest.py``
#: documents a dormant leader's forward return as a flat ``0.0`` and calls that
#: fake data rather than a flat performance -- but no per-subject forward-return
#: table for that run survives, so the ten values below demonstrate the mechanism
#: (a mass of exact zeros on one side only) and are not observations. They feed
#: the guard's numeric *symptom* instrument, which is itself declared a
#: heuristic; labelling these MEASURED would dress a heuristic up as a finding.
DORMANT_ZERO_FORWARD_RETURNS: dict[str, object] = {
    "name": "dormant_zero_forward_returns",
    "provenance": "ILLUSTRATIVE",
    "source": (
        "mechanism from copytrade/backtest.py _eligible_as_of docstring; "
        "per-subject forward returns are not persisted for that run"
    ),
    "cohort_forward_returns": [5.0, -2.0, 8.5, 0.0, 3.25, -1.5, 12.0, 4.0],
    "benchmark_forward_returns": [
        0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 5.0, -2.0, 0.0, 0.0, 8.5, 0.0,
    ],
    "absent_benchmark_clauses": ["not stale", "not frozen as of split_ts"],
}


def comparison_asymmetric() -> dict[str, object]:
    """Run the comparison guard on the cohort/benchmark asymmetry (must refuse)."""
    from .guards.comparison import ComparisonGuard, Population, Predicate

    spec = NESTED_FOUR_SPLIT_ASYMMETRY
    splits = spec["splits"]
    assert isinstance(splits, list)
    last = splits[-1]
    cohort = Population(
        name="cohort",
        predicate=Predicate(
            name=str(spec["cohort_predicate"]),
            clauses=tuple(spec["cohort_clauses"]),  # type: ignore[arg-type]
            ordered=True,
            source="copytrade/backtest.py::_eligible_as_of",
        ),
        size=int(last[2]),
        forward_returns=tuple(
            float(x) for x in DORMANT_ZERO_FORWARD_RETURNS["cohort_forward_returns"]  # type: ignore[arg-type]
        ),
    )
    benchmark = Population(
        name="benchmark",
        predicate=Predicate(
            name=str(spec["benchmark_predicate"]),
            clauses=tuple(spec["benchmark_clauses"]),  # type: ignore[arg-type]
            ordered=True,
            source="the defect: staleness excluded on the cohort side only",
        ),
        size=int(last[2]),
        forward_returns=tuple(
            float(x) for x in DORMANT_ZERO_FORWARD_RETURNS["benchmark_forward_returns"]  # type: ignore[arg-type]
        ),
    )
    report = ComparisonGuard().run(cohort, benchmark)
    return {
        "fixture": "nested_four_split_asymmetry",
        "provenance": spec["provenance"],
        "source": spec["source"],
        "claimed": spec["claimed"],
        "independent_windows": spec["independent_windows"],
        "n_splits": len(splits),
        "bench_positive_in_every_split": all(float(row[6]) > 0 for row in splits),
        "same_clauses": report.same_clauses,
        "asymmetric_filtering": report.asymmetric_filtering,
        "zero_fraction_gap": report.zero_fraction_gap,
        "verdict": report.verdict.value,
        "findings": [f.as_dict() for f in report.findings],
    }


def comparison_shared() -> dict[str, object]:
    """The clean control: both sides through one declared shared predicate."""
    from .guards.comparison import ComparisonGuard, Population, Predicate

    spec = NESTED_FOUR_SPLIT_ASYMMETRY
    shared = Predicate(
        name="eligible_as_of",
        clauses=tuple(spec["cohort_clauses"]),  # type: ignore[arg-type]
        ordered=True,
        source="copytrade/backtest.py::_eligible_as_of",
    )
    cohort = Population(
        name="cohort",
        predicate=shared,
        size=431,
        forward_returns=(5.0, -2.0, 1.5),
    )
    benchmark = Population(
        name="benchmark",
        predicate=shared,
        size=1256,
        forward_returns=(2.0, -1.0, 0.5),
    )
    report = ComparisonGuard().run(cohort, benchmark)
    return {
        "fixture": "comparison_shared_control",
        "provenance": PROVENANCE_ILLUSTRATIVE,
        "source": "the corrected design: both sides call _eligible_as_of()",
        "same_name": report.same_name,
        "same_clauses": report.same_clauses,
        "comparable": report.comparable,
        "verdict": report.verdict.value,
        "findings": [f.as_dict() for f in report.findings],
    }


# ---------------------------------------------------------------------------
# 10. the clean control
# ---------------------------------------------------------------------------

#: A genuinely clean setup: one predictor, no look-ahead, effects that do not
#: care when you measure them, a fat enough sample, one eligibility rule.
CLEAN_CONTROL: dict[str, object] = {
    "name": "clean_control",
    "provenance": "ILLUSTRATIVE",
    "source": "synthetic by design: this is the negative-direction control, not a study",
    "effects": [0.051, 0.038, 0.062, 0.029, 0.055, 0.041, 0.048, 0.033],
    "distances_days": [3.0, 8.0, 15.0, 22.0, 31.0, 43.0, 56.0, 70.0],
    "window_excesses": [22.0, 31.0, 18.0, 27.0, 35.0, 24.0, 29.0, 20.0, 33.0, 26.0],
    "trade_pnls": [
        40.0 + 6.0 * math.sin(i / 3.0) for i in range(120)
    ],
    "n_weeks": 26,
}


def clean_series(*, seed: int = 11) -> list[float]:
    """A clean, stationary, high-variance level series with no splice."""
    rng = random.Random(seed)
    values = [100.0]
    for _ in range(180):
        values.append(values[-1] + rng.gauss(0.0, 1.0))
    return values


def clean_control(*, seed: int = 3) -> dict[str, object]:
    """Run every applicable guard on a genuinely clean setup.

    This is the negative-direction test. If the library refuses this, it is a
    rejection machine rather than a validator, and every refusal it produces is
    worthless.
    """
    from .report import Config, HonestyReport, ResultSet

    rng = random.Random(seed)
    start = date(2024, 1, 1)
    days: list[date] = []
    values: list[float] = []
    for w in range(int(CLEAN_CONTROL["n_weeks"])):  # type: ignore[arg-type]
        for i in range(15):
            days.append(start + timedelta(days=w * 7 + i % 7))
            values.append(0.04 + rng.gauss(0.0, 0.55))

    unique = _eligible
    subjects = tuple({"id": i, "age_days": 90 + i, "dormant": False} for i in range(40))

    # A clean evidence set: every absence is an explicit 404 and a positive
    # control came back 200. A clean comparison: both sides declare one shared
    # predicate. Both are required for the control to exercise guards 7 and 8 --
    # a control that skips them proves nothing about them.
    from .guards.comparison import Population, Predicate
    from .guards.evidence import Observation

    shared = Predicate(
        name="eligible",
        clauses=("age_days >= 30", "not dormant"),
        ordered=True,
    )

    result = ResultSet(
        name="clean_control",
        split_effects=_floats(CLEAN_CONTROL["effects"]),
        split_distances_days=_floats(CLEAN_CONTROL["distances_days"]),
        window_excesses=_floats(CLEAN_CONTROL["window_excesses"]),
        win_count=10,
        trade_pnls=_floats(CLEAN_CONTROL["trade_pnls"]),
        window_plan=WindowPlan.tiled(
            date(2024, 1, 1), date(2024, 12, 31), length_days=30, label="clean_tiling"
        ),
        cohort=Selection(name="cohort", predicate=unique, selected=subjects[:20]),
        benchmark=Selection(name="benchmark", predicate=unique, selected=subjects[20:]),
        series_values=tuple(clean_series(seed=seed)),
        observations=(
            Observation(subject="pypbo", code="404"),
            Observation(subject="cscv", code="404"),
            Observation(subject="mlfinlab", code="404"),
            Observation(subject="deflated-sharpe", code="200"),
        ),
        control_observations=(
            Observation(subject="quantstats", code="200", note="known-present control"),
        ),
        cohort_population=Population(
            name="cohort", predicate=shared, size=20,
            forward_returns=(4.0, -1.0, 6.5, 2.0),
        ),
        benchmark_population=Population(
            name="benchmark", predicate=shared, size=20,
            forward_returns=(1.0, 0.5, -2.0, 3.0),
        ),
        comparison_predicate=shared,
    )
    report = HonestyReport.run(
        result,
        config=Config(assert_no_unguarded_construction=False),
    )
    block = block_bootstrap_ci(values, block_dates=days, min_blocks=5, seed=seed)
    return {
        "fixture": "clean_control",
        "verdict": report.verdict.value,
        "certified": report.certified,
        "ran_guards": list(report.ran_guards),
        "skipped_guards": list(report.skipped_guards),
        "failure_codes": list(report.failure_codes()),
        "block_ci": [round(block.low, 4), round(block.high, 4)],
        "n_blocks": block.n_blocks,
        "block_verdict": block.verdict.value,
    }


# ---------------------------------------------------------------------------
# provenance: which fixtures are measured and which are constructed
# ---------------------------------------------------------------------------

#: ``MEASURED`` -- per-observation rows come from the research archive.
PROVENANCE_MEASURED = "MEASURED"
#: ``MEASURED_DESIGN`` -- the design is the archive's, the rows are not.
PROVENANCE_MEASURED_DESIGN = "MEASURED_DESIGN"
#: ``DERIVED`` -- the statistic is measured; the rows are solved from it.
PROVENANCE_DERIVED = "DERIVED"
#: ``ILLUSTRATIVE`` -- neither the rows nor the number come from the archive.
PROVENANCE_ILLUSTRATIVE = "ILLUSTRATIVE"

#: Every fixture's provenance, in one place, so it can be asserted and printed
#: rather than only read. A fixture whose data dict lacks a matching
#: ``"provenance"`` key is a defect -- see :func:`provenance`.
PROVENANCE: dict[str, str] = {
    "copier_pnl": PROVENANCE_MEASURED,
    "roi": PROVENANCE_MEASURED,
    "nine_of_twelve": PROVENANCE_ILLUSTRATIVE,
    "top_decile_121": PROVENANCE_DERIVED,
    "top_decile_164": PROVENANCE_ILLUSTRATIVE,
    "nested_four_split": PROVENANCE_MEASURED_DESIGN,
    "disjoint_twelve": PROVENANCE_MEASURED_DESIGN,
    "spliced_metrics": PROVENANCE_ILLUSTRATIVE,
    "zero_padded_inception": PROVENANCE_MEASURED,
    "left_edge_bar": PROVENANCE_MEASURED,
    "trade_level_false_positive": PROVENANCE_ILLUSTRATIVE,
    "multiplicity_341": PROVENANCE_DERIVED,
    "multiplicity_60": PROVENANCE_ILLUSTRATIVE,
    "clean_control": PROVENANCE_ILLUSTRATIVE,
    # the 2026-09-28 evidence-presence episode: real scan artifacts on disk
    "pypi_three_state_corrected": PROVENANCE_MEASURED,
    "pypi_scan_503": PROVENANCE_MEASURED,
    # the control queries were not persisted; labelled honestly, not upgraded
    "code_search_null_without_control": PROVENANCE_ILLUSTRATIVE,
    # the design and the four split aggregates are the study's; the per-subject
    # rows are not, which is exactly what MEASURED_DESIGN exists to say
    "nested_four_split_asymmetry": PROVENANCE_MEASURED_DESIGN,
    "dormant_zero_forward_returns": PROVENANCE_ILLUSTRATIVE,
}

#: Fixture data dicts, keyed by the same names as :data:`PROVENANCE`.
_FIXTURE_DATA: dict[str, dict[str, object]] = {
    "copier_pnl": COPIER_PNL,
    "roi": ROI,
    "nine_of_twelve": NINE_OF_TWELVE,
    "top_decile_121": TOP_DECILE_121,
    "top_decile_164": TOP_DECILE_164,
    "nested_four_split": NESTED_FOUR_SPLIT,
    "disjoint_twelve": DISJOINT_TWELVE,
    "spliced_metrics": SPLICED_METRICS,
    "zero_padded_inception": ZERO_PADDED_INCEPTION,
    "left_edge_bar": LEFT_EDGE_BAR,
    "trade_level_false_positive": TRADE_LEVEL_FALSE_POSITIVE,
    "multiplicity_341": MULTIPLICITY_341,
    "multiplicity_60": MULTIPLICITY_60,
    "clean_control": CLEAN_CONTROL,
    "pypi_three_state_corrected": PYPI_THREE_STATE_CORRECTED,
    "pypi_scan_503": PYPI_SCAN_503,
    "code_search_null_without_control": CODE_SEARCH_NULL_WITHOUT_CONTROL,
    "nested_four_split_asymmetry": NESTED_FOUR_SPLIT_ASYMMETRY,
    "dormant_zero_forward_returns": DORMANT_ZERO_FORWARD_RETURNS,
}


def provenance() -> dict[str, object]:
    """Audit the fixtures' own provenance labels.

    Returns a summary with one row per fixture: the declared label, the label
    the data dict carries, whether they agree, the claimed statistic, and -- for
    look-ahead fixtures -- whether the guard actually recomputes it.

    This is the library checking itself. A fixture labelled as measured whose
    numbers do not reproduce its claimed statistic is precisely the failure
    mode this package exists to catch, so it is not exempt from it.
    """
    rows: list[dict[str, object]] = []
    mismatched: list[str] = []
    unverified: list[str] = []

    for name, label in PROVENANCE.items():
        spec = _FIXTURE_DATA[name]
        declared = spec.get("provenance")
        agrees = declared == label
        if not agrees:
            mismatched.append(name)

        row: dict[str, object] = {
            "fixture": name,
            "provenance": label,
            "declared": declared,
            "label_agrees": agrees,
            "source": spec.get("source", "<none stated>"),
        }

        claimed = spec.get("measured_r")
        if isinstance(claimed, float):
            observed = _observed_r(name)
            ok = observed is not None and abs(observed - claimed) < 5e-4
            row["claimed_r"] = claimed
            row["observed_r"] = None if observed is None else round(observed, 6)
            row["reproduces"] = ok
            # Only a MEASURED fixture is asserting that its rows are the
            # archive's; a DERIVED or ILLUSTRATIVE one is allowed to miss.
            if label == PROVENANCE_MEASURED and not ok:
                unverified.append(name)
        rows.append(row)

    return {
        "fixtures": rows,
        "n_fixtures": len(rows),
        "n_measured": sum(1 for v in PROVENANCE.values() if v == PROVENANCE_MEASURED),
        "n_measured_design": sum(
            1 for v in PROVENANCE.values() if v == PROVENANCE_MEASURED_DESIGN
        ),
        "n_derived": sum(1 for v in PROVENANCE.values() if v == PROVENANCE_DERIVED),
        "n_illustrative": sum(
            1 for v in PROVENANCE.values() if v == PROVENANCE_ILLUSTRATIVE
        ),
        "labels_consistent": not mismatched,
        "mismatched": mismatched,
        "measured_fixtures_that_fail_to_reproduce": unverified,
        "all_consistent": not mismatched and not unverified,
    }


def _observed_r(name: str) -> float | None:
    """Recompute the look-ahead correlation for a fixture, or ``None``."""
    spec = _FIXTURE_DATA.get(name)
    if spec is None:
        return None
    effects, distances = spec.get("effects"), spec.get("distances_days")
    if not isinstance(effects, (list, tuple)) or not isinstance(
        distances, (list, tuple)
    ):
        return None
    from ._numeric import pearson_r

    return pearson_r(_floats(effects), _floats(distances))


# ---------------------------------------------------------------------------
# registry used by the CLI's per-guard subcommands
# ---------------------------------------------------------------------------

GUARD_FIXTURES: dict[str, Callable[[], dict[str, object]]] = {
    "lookahead": copier_pnl,
    "outliers": nine_of_twelve,
    "windows": nested_four_split,
    "universe": universe_asymmetric,
    "multiplicity": multiplicity_341,
    "series": spliced_metrics,
    "evidence": evidence_negative_evidence,
    "comparison": comparison_asymmetric,
}


def render(name: str) -> str:
    """Human-readable rendering of a single guard's fixture outcome."""
    payload = GUARD_FIXTURES[name]()
    lines = [f"{name}: {payload.get('fixture', name)}"]
    for key, value in payload.items():
        if key in ("fixture", "findings"):
            continue
        lines.append(f"  {key}: {value}")
    findings = payload.get("findings", [])
    if isinstance(findings, list):
        for f in findings:
            if isinstance(f, dict) and f.get("status") in ("FAIL", "ERROR"):
                lines.append(f"  ! {f.get('code')}: {f.get('message')}")
    lines.append(f"  verdict: {payload.get('verdict')}")
    return "\n".join(lines)


def _floats(seq: object) -> tuple[float, ...]:
    if not isinstance(seq, (list, tuple)):
        raise TypeError(f"expected a sequence of numbers, got {type(seq).__name__}")
    return tuple(float(x) for x in seq)


def _clean_subjects() -> tuple[dict[str, object], ...]:
    """Dormant subjects present, all excluded by the shared predicate."""
    return tuple(
        {"id": i, "age_days": 90 + i, "dormant": i % 5 == 0} for i in range(40)
    )
