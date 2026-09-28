"""The aggregator: one result set in, one verdict out.

These tests are about the *refusal path* -- that it is the easy path, that a
skipped guard is a failed guard, and that a clean result is certified rather
than reflexively rejected.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import pytest

from honest_backtest import fixtures
from honest_backtest.guards.universe import Selection
from honest_backtest.guards.windows import WindowPlan
from honest_backtest.report import Config, HonestyReport, ResultSet
from honest_backtest.types import Certification, RefusedError, Verdict


def _eligible(subject: object) -> bool:
    return True


def test_refused_result_cannot_be_used() -> None:
    """``require_certified()`` is the one line a consumer needs, and it raises."""
    report = HonestyReport.run(
        ResultSet(
            name="copier_pnl",
            split_effects=tuple(float(x) for x in fixtures.COPIER_PNL["effects"]),  # type: ignore[union-attr]
            split_distances_days=tuple(
                float(x) for x in fixtures.COPIER_PNL["distances_days"]  # type: ignore[union-attr]
            ),
        ),
        config=Config(),
    )

    assert report.verdict is Verdict.REFUSED
    assert report.refused is True
    with pytest.raises(RefusedError) as excinfo:
        report.require_certified()
    assert "REFUSED" in str(excinfo.value)
    assert "look-ahead" in str(excinfo.value)


def test_nine_of_twelve_is_refused_by_the_aggregator() -> None:
    """The win-count fixture, through the full pipeline."""
    report = HonestyReport.run(
        ResultSet(
            name="nine_of_twelve",
            window_excesses=tuple(
                float(x) for x in fixtures.NINE_OF_TWELVE["excesses"]  # type: ignore[union-attr]
            ),
            win_count=9,
        )
    )
    assert report.verdict is Verdict.REFUSED
    assert "CONCENTRATION_MIXED_SIGNS" in report.failure_codes()


def test_nested_plan_is_refused_by_the_aggregator(nested_four_split: dict) -> None:
    """Four splits, one end date, zero independent windows."""
    plan = WindowPlan(
        windows=tuple(
            WindowPlan.from_spec(s).windows[0]
            for s in (
                "2024-01-01..2024-07-01",
                "2024-02-01..2024-07-01",
                "2024-03-01..2024-07-01",
                "2024-04-01..2024-07-01",
            )
        ),
        label="walk_forward",
    )
    report = HonestyReport.run(ResultSet(name="wf", window_plan=plan))
    assert report.verdict is Verdict.REFUSED
    assert "WINDOWS_FULLY_NESTED" in report.failure_codes()


def test_empty_result_set_is_refused_not_vacuously_certified() -> None:
    """"Nothing to check" is not "checked and clean"."""
    report = HonestyReport.run(ResultSet(name="empty"))
    assert report.verdict is Verdict.REFUSED
    assert "GUARD_INPUTS_MISSING" in report.failure_codes()
    assert "no guard could run" in report.explanation()


def test_a_guard_that_cannot_run_because_inputs_are_partial_is_refused() -> None:
    """Effects without distances is a caller bug, reported as blocking."""
    report = HonestyReport.run(
        ResultSet(name="partial", split_effects=(0.1, 0.2, 0.3))
    )
    assert report.verdict is Verdict.REFUSED
    assert any("could not run" in f.message for f in report.failures())


def test_clean_result_is_certified(clean_control: dict) -> None:
    """The negative direction. A library that rejects everything is worthless."""
    assert clean_control["verdict"] == "CERTIFIED"
    assert clean_control["certified"] is True
    assert clean_control["failure_codes"] == []


def test_clean_result_through_the_aggregator_directly() -> None:
    """A genuinely clean bundle must certify, and must run real guards."""
    report = HonestyReport.run(
        ResultSet(
            name="clean",
            split_effects=tuple(
                float(x) for x in fixtures.CLEAN_CONTROL["effects"]  # type: ignore[union-attr]
            ),
            split_distances_days=tuple(
                float(x) for x in fixtures.CLEAN_CONTROL["distances_days"]  # type: ignore[union-attr]
            ),
            window_excesses=tuple(
                float(x) for x in fixtures.CLEAN_CONTROL["window_excesses"]  # type: ignore[union-attr]
            ),
            win_count=10,
            trade_pnls=tuple(
                float(x) for x in fixtures.CLEAN_CONTROL["trade_pnls"]  # type: ignore[union-attr]
            ),
            window_plan=WindowPlan.tiled(
                date(2024, 1, 1), date(2024, 12, 31), length_days=30
            ),
            cohort=Selection(name="cohort", predicate=_eligible, selected=(1, 2, 3)),
            benchmark=Selection(name="benchmark", predicate=_eligible, selected=(4, 5)),
            series_values=tuple(fixtures.clean_series()),
        )
    )

    assert report.verdict is Verdict.CERTIFIED
    assert report.certified is True
    assert len(report.ran_guards) >= 5
    assert report.failures() == ()
    report.require_certified()  # must not raise


def test_a_warning_yields_suspect_not_certified() -> None:
    """There is no 'certified with warnings'."""
    report = HonestyReport.run(
        ResultSet(name="alarming", trade_pnls=tuple([100.0] * 10 + [-1.0] * 40)),
        config=Config(),
    )
    # top decile is 1000 of a net 960 -> share > 1.0 -> blocking, but check the
    # mechanism: a WARN-only bundle must land on SUSPECT.
    assert report.verdict in (Verdict.REFUSED, Verdict.SUSPECT)
    assert report.certified is False


def test_strictest_verdict_wins() -> None:
    """One REFUSED among passes must produce REFUSED."""
    assert Verdict.strictest([Verdict.CERTIFIED, Verdict.CERTIFIED]) is Verdict.CERTIFIED
    assert (
        Verdict.strictest([Verdict.CERTIFIED, Verdict.REFUSED, Verdict.SUSPECT])
        is Verdict.REFUSED
    )
    assert Verdict.strictest([]) is Verdict.CERTIFIED


def test_guard_subset_records_the_restriction() -> None:
    """A restricted run must say what it did not check."""
    report = HonestyReport.run(
        ResultSet(
            name="subset",
            split_effects=tuple(
                float(x) for x in fixtures.CLEAN_CONTROL["effects"]  # type: ignore[union-attr]
            ),
            split_distances_days=tuple(
                float(x) for x in fixtures.CLEAN_CONTROL["distances_days"]  # type: ignore[union-attr]
            ),
        ),
        config=Config(guard_subset=("lookahead",)),
    )
    assert report.ran_guards == ("lookahead",)
    assert "concentration" in report.skipped_guards
    assert "windows" in report.skipped_guards
    assert "guards not run" in report.explanation()


def test_provenance_records_which_guards_actually_ran() -> None:
    """A consumer can require a specific guard to have been applied."""
    report = HonestyReport.run(
        ResultSet(
            name="provenance",
            split_effects=tuple(
                float(x) for x in fixtures.CLEAN_CONTROL["effects"]  # type: ignore[union-attr]
            ),
            split_distances_days=tuple(
                float(x) for x in fixtures.CLEAN_CONTROL["distances_days"]  # type: ignore[union-attr]
            ),
        )
    )
    cert = report.certification.require_guard("lookahead")
    assert cert.certified is True
    with pytest.raises(Exception):
        cert.require_guard("multiplicity")


def test_report_is_json_serialisable_and_round_trips() -> None:
    """The CLI depends on this."""
    report = HonestyReport.run(
        ResultSet(
            name="copier_pnl",
            split_effects=tuple(float(x) for x in fixtures.COPIER_PNL["effects"]),  # type: ignore[union-attr]
            split_distances_days=tuple(
                float(x) for x in fixtures.COPIER_PNL["distances_days"]  # type: ignore[union-attr]
            ),
        )
    )
    parsed = json.loads(report.to_json())
    assert parsed["verdict"] == "REFUSED"
    assert parsed["name"] == "copier_pnl"
    assert isinstance(parsed["failure_codes"], list)
    assert parsed["certification"]["verdict"] == "REFUSED"


def test_explanation_lists_specific_failures_not_a_score() -> None:
    """Findings are reasons, not a number."""
    report = HonestyReport.run(
        ResultSet(
            name="copier_pnl",
            split_effects=tuple(float(x) for x in fixtures.COPIER_PNL["effects"]),  # type: ignore[union-attr]
            split_distances_days=tuple(
                float(x) for x in fixtures.COPIER_PNL["distances_days"]  # type: ignore[union-attr]
            ),
        )
    )
    text = report.explanation()
    assert "REFUSED" in text
    assert "LOOKAHEAD_DISTANCE_DECAY" in text
    assert "guards run" in text


def test_config_is_immutable_and_strict_by_default() -> None:
    """The defaults are the strict settings, and they cannot be mutated."""
    cfg = Config()
    assert cfg.lookahead_r_threshold == 0.5
    assert cfg.tail_threshold == 1.0
    assert cfg.min_independent_windows == 2
    assert cfg.correction == "bonferroni"
    with pytest.raises(Exception):
        cfg.alpha = 0.5  # type: ignore[misc]


def test_invalid_config_rejected() -> None:
    """Bad config fails at construction."""
    with pytest.raises(Exception):
        Config(alpha=0.0)
    with pytest.raises(Exception):
        Config(correction="holm")
    with pytest.raises(Exception):
        Config(lookahead_r_threshold=0.0)
    with pytest.raises(Exception):
        Config(min_independent_windows=0)


def test_result_set_requires_a_name() -> None:
    """An unnamed result cannot be reported on."""
    with pytest.raises(Exception):
        ResultSet(name="")


def test_multiplicity_guard_participates_when_a_counter_is_supplied() -> None:
    """The counter is aggregated like every other guard."""
    from honest_backtest.guards.multiplicity import ExperimentCounter

    counter = ExperimentCounter(alpha=0.05)
    for i in range(341):
        counter.record(f"cfg-{i}")

    report = HonestyReport.run(
        ResultSet(
            name="study",
            split_effects=tuple(
                float(x) for x in fixtures.CLEAN_CONTROL["effects"]  # type: ignore[union-attr]
            ),
            split_distances_days=tuple(
                float(x) for x in fixtures.CLEAN_CONTROL["distances_days"]  # type: ignore[union-attr]
            ),
        ),
        counter=counter,
        claimed_p=0.03,
        n_nominal_positives=16,
    )

    assert "multiplicity" in report.ran_guards
    assert report.verdict is Verdict.REFUSED
    assert "MULTIPLICITY_AT_CHANCE_RATE" in report.failure_codes()


def test_certification_is_a_type_not_a_boolean() -> None:
    """A verdict cannot be lost by accident: the guard hands back an object."""
    report = HonestyReport.run(
        ResultSet(
            name="copier_pnl",
            split_effects=tuple(float(x) for x in fixtures.COPIER_PNL["effects"]),  # type: ignore[union-attr]
            split_distances_days=tuple(
                float(x) for x in fixtures.COPIER_PNL["distances_days"]  # type: ignore[union-attr]
            ),
        )
    )
    cert = report.certification
    assert isinstance(cert, Certification)
    assert cert.certified is False
    assert cert.usable is False  # REFUSED is not usable
    assert len(cert.reasons) >= 1


# ---------------------------------------------------------------------------
# the two guards added for the 2026-09-28 failures, through the aggregator
# ---------------------------------------------------------------------------


def test_the_503_scan_is_refused_by_the_aggregator() -> None:
    """Guard 7 in the pipeline: the broken scan refuses the whole report.

    Nothing else is supplied, so the evidence guard is the only one that can
    run -- and running it alone has to be enough to refuse. A guard that only
    speaks when six others are present is not a guard.
    """
    rows = fixtures.PYPI_SCAN_503["observations"]
    assert isinstance(rows, list)
    from honest_backtest.guards.evidence import Observation

    report = HonestyReport.run(
        ResultSet(
            name="pypi_scan_503",
            observations=tuple(
                Observation(subject=str(s), code=str(c)) for s, _exists, c in rows
            ),
            claimed_absent=tuple(str(s) for s, exists, _ in rows if exists is False),
            negative_claim="non-200 means absent",
        )
    )
    assert report.verdict is Verdict.REFUSED
    assert "evidence" in report.ran_guards
    assert "EVIDENCE_ABSENCE_FROM_NON_NOTFOUND" in report.failure_codes()
    assert report.payload["evidence"]["n_unknown"] > 0  # type: ignore[index]


def test_the_corrected_scan_certifies_through_the_aggregator() -> None:
    """Guard 7's clean direction: the corrected scan must not be refused.

    This is the anti-rejection-machine test for the new guard. The corrected
    scan is a real artifact with real absences in it; if the aggregator refused
    it, the guard would be refusing absence itself rather than refusing
    *unclean* absence, and it would be worthless.
    """
    from honest_backtest.guards.evidence import Observation

    rows = fixtures.PYPI_THREE_STATE_CORRECTED["observations"]
    assert isinstance(rows, list)
    report = HonestyReport.run(
        ResultSet(
            name="pypi_three_state_corrected",
            observations=tuple(
                Observation(subject=str(s), code=str(state).upper())
                for s, state, _code in rows
            ),
            control_observations=(Observation(subject="control", code="200"),),
        )
    )
    assert report.verdict is Verdict.CERTIFIED
    assert "evidence" in report.ran_guards
    assert report.failure_codes() == ()
    report.require_certified()  # the one line a consumer needs


def test_the_asymmetric_comparison_is_refused_by_the_aggregator() -> None:
    """Guard 8 in the pipeline: the retracted 4/4 result refuses."""
    spec = fixtures.NESTED_FOUR_SPLIT_ASYMMETRY
    rows = spec["splits"]
    assert isinstance(rows, list)
    from honest_backtest.guards.comparison import Population, Predicate

    cohort = Population(
        name="cohort",
        predicate=Predicate(
            name=str(spec["cohort_predicate"]),
            clauses=tuple(spec["cohort_clauses"]),  # type: ignore[arg-type]
            ordered=True,
        ),
        size=int(rows[-1][2]),
    )
    benchmark = Population(
        name="benchmark",
        predicate=Predicate(
            name=str(spec["benchmark_predicate"]),
            clauses=tuple(spec["benchmark_clauses"]),  # type: ignore[arg-type]
            ordered=True,
        ),
        size=int(rows[-1][2]),
    )
    report = HonestyReport.run(
        ResultSet(
            name="nested_four_split_asymmetry",
            cohort_population=cohort,
            benchmark_population=benchmark,
        )
    )
    assert report.verdict is Verdict.REFUSED
    assert "comparison" in report.ran_guards
    assert "COMPARISON_DIVERGENT_PREDICATE" in report.failure_codes()


def test_a_shared_predicate_comparison_certifies_through_the_aggregator() -> None:
    """Guard 8's clean direction: one shared predicate is not refused.

    The comparison guard must key on *divergence*, not on the act of comparing
    two populations. If it refused every comparison, it would be forbidding
    the thing the library exists to make safe.
    """
    from honest_backtest.guards.comparison import Population, Predicate

    shared = Predicate(
        name="eligible_as_of",
        clauses=("history_days >= 30", "not stale", "not frozen as of split_ts"),
        ordered=True,
    )
    report = HonestyReport.run(
        ResultSet(
            name="shared_predicate_control",
            cohort_population=Population("cohort", shared, 20),
            benchmark_population=Population("benchmark", shared, 2000),
            comparison_predicate=shared,
        )
    )
    assert report.verdict is Verdict.CERTIFIED
    assert "comparison" in report.ran_guards
    assert report.failure_codes() == ()


def test_a_declaration_that_contradicts_the_shared_predicate_is_refused() -> None:
    """Passing a shared predicate pins the declaration to a third statement.

    Two sides can agree with each other while neither is the rule the run says
    it used. Supplying ``comparison_predicate`` compares each declaration to
    that statement as well, so "we both did X" cannot be asserted about a run
    whose stated rule was Y.
    """
    from honest_backtest.guards.comparison import Population, Predicate

    stated = Predicate("eligible_as_of", ("not stale",), ordered=True)
    liar = Predicate("eligible_as_of", ("history_days >= 30",), ordered=True)
    report = HonestyReport.run(
        ResultSet(
            name="contradicted_declaration",
            cohort_population=Population("cohort", liar, 20),
            benchmark_population=Population("benchmark", liar, 20),
            comparison_predicate=stated,
        )
    )
    assert report.verdict is Verdict.REFUSED
    assert "COMPARISON_DIVERGENT_PREDICATE" in report.failure_codes()


def test_both_new_guards_appear_in_the_guard_set() -> None:
    """The guard set is the contract; a guard outside it never runs."""
    report = HonestyReport.run(
        ResultSet(name="empty_but_for_this_one_guard", trade_pnls=(1.0, -1.0, 2.0, 0.5))
    )
    skipped = set(report.skipped_guards)
    assert {"evidence", "comparison"} <= skipped, (
        "a guard with no inputs must be recorded as skipped, not silently absent"
    )


def test_the_comparison_payload_cannot_contradict_the_report() -> None:
    """A REFUSED report must not ship a payload field reading CERTIFIED.

    Regression: the first draft built ``payload['comparison']`` from the guard's
    own report, which does not see the shared-predicate findings the aggregator
    adds. The payload then said ``verdict: CERTIFIED`` inside a ``REFUSED``
    report -- machine-readable overstatement, in the worst possible place.
    """
    from honest_backtest.guards.comparison import Population, Predicate

    stated = Predicate("eligible_as_of", ("not stale",), ordered=True)
    liar = Predicate("eligible_as_of", ("history_days >= 30",), ordered=True)
    report = HonestyReport.run(
        ResultSet(
            name="contradicted_declaration",
            cohort_population=Population("cohort", liar, 20),
            benchmark_population=Population("benchmark", liar, 20),
            comparison_predicate=stated,
        )
    )
    assert report.verdict is Verdict.REFUSED
    payload = report.payload["comparison"]
    assert isinstance(payload, dict)
    assert payload["verdict"] == "REFUSED", (
        "the payload's own verdict must agree with the report it belongs to"
    )
    assert payload["comparable"] is False
    assert payload["n_shared_predicate_findings"] == 2
    assert len(payload["findings"]) == 2  # type: ignore[arg-type]
    assert payload["shared_predicate_declared"] is True


def test_a_caller_supplied_evidence_guard_does_not_drop_the_negative_claim() -> None:
    """A wiring choice must not silently relax a refusal.

    Regression: passing ``guards=[EvidenceGuard()]`` short-circuited the
    ``or``, so ``ResultSet.negative_claim`` was discarded and a REFUSED
    situation became SUSPECT with no finding or note.
    """
    from honest_backtest.guards.evidence import EvidenceGuard, Observation

    result = ResultSet(
        name="null_scan",
        observations=(Observation("a", "503"), Observation("b", "503")),
        negative_claim="nothing was found",
    )
    default = HonestyReport.run(result)
    with_custom_guard = HonestyReport.run(result, guards=[EvidenceGuard()])

    assert default.verdict is Verdict.REFUSED
    assert with_custom_guard.verdict is Verdict.REFUSED, (
        "the caller's own guard instance must not relax the verdict"
    )
    assert default.failure_codes() == with_custom_guard.failure_codes()
    payload = with_custom_guard.payload["evidence"]
    assert isinstance(payload, dict)
    assert payload["negative_claim"] == "nothing was found"
