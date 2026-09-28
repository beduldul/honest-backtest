"""Guard 8 (comparison predicates): were the two populations built the same way?

The hard truth this file encodes: a comparison guard cannot recover the
selection rule from the selected values. Two populations of the same size with
the same mean can have been produced by completely different filters, and no
arithmetic sees the difference. So the guard requires the caller to **declare**
its predicates and refuses when the declarations diverge -- and the tests below
check both that it does that, and that it does not pretend to more.

Both directions are required:

* it **fires** on the real cohort/benchmark asymmetry behind the retracted
  "POSITIVE 4/4 splits"; and
* it **stays silent** when both sides declare one shared predicate.
"""

from __future__ import annotations

from datetime import date

import pytest

from honest_backtest import fixtures
from honest_backtest.guards.comparison import (
    CLAUSE_ORDER_FAILURE,
    DIVERGENT_PREDICATE_FAILURE,
    ONE_SIDED_FILTER_FAILURE,
    UNDECLARED_PREDICATE_FAILURE,
    ZERO_MASS_SYMPTOM_WARNING,
    ComparisonGuard,
    Population,
    Predicate,
    undeclared_population,
)

SHARED = Predicate(
    name="eligible_as_of",
    clauses=("history_days >= 30", "not stale", "not frozen as of split_ts"),
    ordered=True,
)


def cohort(size: int = 20, predicate: Predicate = SHARED) -> Population:
    return Population(name="cohort", predicate=predicate, size=size)


def benchmark(size: int = 400, predicate: Predicate = SHARED) -> Population:
    return Population(name="benchmark", predicate=predicate, size=size)


# ---------------------------------------------------------------------------
# the broken case: the guard must fire
# ---------------------------------------------------------------------------


def test_guard_fires_on_the_documented_asymmetry(comparison_broken: dict[str, object]) -> None:
    """The real defect: one clause on one side, fewer on the other."""
    assert comparison_broken["fixture"] == "nested_four_split_asymmetry"
    assert comparison_broken["verdict"] == "REFUSED"
    codes = [f["code"] for f in comparison_broken["findings"]]  # type: ignore[union-attr]
    assert DIVERGENT_PREDICATE_FAILURE in codes


def test_the_fixture_reproduces_the_retracted_claim() -> None:
    """The fixture carries the claim it refutes, in the claim's own words."""
    spec = fixtures.NESTED_FOUR_SPLIT_ASYMMETRY
    assert spec["claimed"] == "POSITIVE 4/4 splits"
    assert spec["independent_windows"] == 0


def test_the_asymmetry_is_present_in_every_split() -> None:
    """Not a stray window: the benchmark mean is positive in all four."""
    payload = fixtures.comparison_asymmetric()
    assert payload["n_splits"] == 4
    assert payload["bench_positive_in_every_split"] is True


def test_the_split_aggregates_reproduce_the_published_table() -> None:
    """``excess == mean_fwd - bench`` for every row, as the README prints it.

    These four rows are the retraction table's, and the arithmetic has to hold
    on them or the fixture is carrying numbers it cannot justify.
    """
    rows = fixtures.NESTED_FOUR_SPLIT_ASYMMETRY["splits"]
    assert isinstance(rows, list)
    for split, fwd_days, eligible, mean_fwd, median, hit, bench, excess in rows:
        assert excess == pytest.approx(mean_fwd - bench, abs=0.05), split
        assert eligible > 0 and fwd_days > 0 and 0 <= hit <= 100


def test_the_fixture_names_the_splits_the_retraction_names() -> None:
    """The design is the study's, not a convenience construction."""
    rows = fixtures.NESTED_FOUR_SPLIT_ASYMMETRY["splits"]
    assert isinstance(rows, list)
    assert [r[0] for r in rows] == [
        "2025-12-10", "2026-02-21", "2026-05-05", "2026-07-17",
    ]
    # All four end on the same date, which is what makes them nested and the
    # independent-window count zero. This is the copytrade study's design, not
    # the library's earlier ``nested_four_split`` fixture (a different study
    # whose shared end is 2024-07-01); the two are separate failures that
    # happen to share a shape.
    assert fixtures.NESTED_FOUR_SPLIT_ASYMMETRY["shared_end"] == date(2026, 9, 28)
    assert fixtures.NESTED_FOUR_SPLIT["shared_end"] == date(2024, 7, 1)


def test_different_clauses_are_refused() -> None:
    """The minimal form: one side dropped two clauses."""
    report = ComparisonGuard().run(
        cohort(),
        benchmark(predicate=Predicate(name="benchmark_filter", clauses=("history_days >= 30",))),
    )
    assert report.verdict.value == "REFUSED"
    assert report.same_clauses is False
    finding = next(f for f in report.findings if f.code == DIVERGENT_PREDICATE_FAILURE)
    assert "not stale" in finding.message
    assert finding.detail["only_in_cohort"] == "not frozen as of split_ts; not stale"


def test_one_side_filtered_and_the_other_not_gets_its_own_finding() -> None:
    """An empty predicate is not a different filter, it is the absence of one.

    Those are different failures -- "the benchmark used a different rule" and
    "the benchmark used no rule at all" -- and conflating them would hide the
    exact shape of the recorded defect.
    """
    report = ComparisonGuard().run(
        cohort(),
        benchmark(predicate=Predicate(name="none", clauses=())),
    )
    assert ONE_SIDED_FILTER_FAILURE in [f.code for f in report.findings]
    assert report.asymmetric_filtering is True
    assert report.verdict.value == "REFUSED"


def test_both_sides_unfiltered_is_not_an_asymmetry() -> None:
    """Two identical no-ops are symmetric. Refusing them would be a false alarm."""
    report = ComparisonGuard(allow_empty_clauses=True).run(
        Population("cohort", Predicate("none", ()), 10),
        Population("benchmark", Predicate("none", ()), 10),
    )
    assert report.asymmetric_filtering is False
    assert report.verdict.value == "CERTIFIED"


def test_identical_clauses_under_different_names_are_refused() -> None:
    """Identical today is not the same as one shared rule.

    Two names that agree by coincidence will drift on the next edit -- the
    cohort's name gets touched, the benchmark's does not. The name is the
    caller's own declaration of identity, so a mismatch is a mismatch.
    """
    report = ComparisonGuard().run(
        cohort(),
        benchmark(predicate=Predicate(name="other_rule", clauses=SHARED.clauses, ordered=True)),
    )
    assert report.verdict.value == "REFUSED"
    assert report.same_clauses is True
    assert DIVERGENT_PREDICATE_FAILURE in [f.code for f in report.findings]


def test_clause_order_divergence_is_caught_when_order_is_observable() -> None:
    """Order only counts when the caller says it is observable.

    For a streaming filter chain it is; for a set intersection it is not, and
    claiming a divergence there would be inventing evidence. So it is a
    declaration, and here the declaration is made.
    """
    report = ComparisonGuard().run(
        cohort(),
        benchmark(
            predicate=Predicate(
                name="eligible_as_of",
                clauses=("not stale", "history_days >= 30", "not frozen as of split_ts"),
                ordered=True,
            )
        ),
    )
    assert report.same_clauses is True, "same clauses, different order"
    assert report.verdict.value == "REFUSED"
    assert CLAUSE_ORDER_FAILURE in [f.code for f in report.findings]


def test_clause_order_is_ignored_when_neither_side_claims_it() -> None:
    """A set intersection has no order to compare, and the guard does not guess."""
    report = ComparisonGuard().run(
        cohort(predicate=Predicate("p", tuple(reversed(SHARED.clauses)), ordered=False)),
        benchmark(predicate=Predicate("p", SHARED.clauses, ordered=False)),
    )
    assert report.same_order is True
    assert report.verdict.value == "CERTIFIED"


def test_an_undeclared_predicate_is_refused_not_assumed() -> None:
    """The guard cannot check what was not declared, and says so."""
    report = ComparisonGuard().run(
        cohort(),
        undeclared_population("benchmark", 400),
    )
    assert UNDECLARED_PREDICATE_FAILURE in [f.code for f in report.findings]
    assert report.verdict.value == "REFUSED"


def test_declared_empty_is_allowed_only_when_the_caller_opts_in() -> None:
    """``allow_empty_clauses`` is the escape hatch, and it is explicit."""
    pair = (
        Population("cohort", Predicate("none", ()), 10),
        Population("benchmark", Predicate("none", ()), 10),
    )
    assert ComparisonGuard().run(*pair).verdict.value == "REFUSED"
    assert ComparisonGuard(allow_empty_clauses=True).run(*pair).verdict.value == "CERTIFIED"


def test_require_declared_clauses_can_be_relaxed_only_deliberately() -> None:
    """Turning the check off leaves the guard with no evidence, and it warns.

    Both predicates are empty here, so the guard finds them "identical" from no
    information at all. That must not read as a clean comparison: it downgrades
    the aggregate to SUSPECT and says why, rather than exporting
    ``predicate_identical: True`` as if it meant something.
    """
    report = ComparisonGuard(require_declared_clauses=False, allow_empty_clauses=True).run(
        Population("cohort", Predicate("a", ()), 10),
        Population("benchmark", Predicate("b", ()), 10),
    )
    # The under-specification finding is now a warning, not a block ...
    warn = next(f for f in report.findings if f.code == UNDECLARED_PREDICATE_FAILURE)
    assert warn.status.value == "WARN"
    assert warn.severity.value == "INFO"
    assert "nothing to disagree about" in warn.message
    # ... while the *name* divergence still blocks, because it is a real
    # declaration mismatch and the relaxation did not touch it.
    assert DIVERGENT_PREDICATE_FAILURE in [f.code for f in report.findings]
    assert report.verdict.value == "REFUSED"


# ---------------------------------------------------------------------------
# the clean case: the guard must stay silent
# ---------------------------------------------------------------------------


def test_guard_stays_silent_on_the_shared_predicate(comparison_clean: dict[str, object]) -> None:
    """Both sides through one rule: nothing to report."""
    assert comparison_clean["verdict"] == "CERTIFIED"
    assert comparison_clean["findings"] == []
    assert comparison_clean["comparable"] is True


def test_matched_predicate_certifies() -> None:
    """The plain positive direction, on synthetic data."""
    report = ComparisonGuard().run(cohort(size=20), benchmark(size=2000))
    assert report.verdict.value == "CERTIFIED"
    assert report.predicate_identical is True
    assert report.findings == ()


def test_an_identical_no_op_pair_is_symmetric() -> None:
    """Two sides that both declare "no filter" were selected the same way."""
    report = ComparisonGuard(allow_empty_clauses=True).run(
        Population("cohort", Predicate("all", ("all",)), 10),
        Population("benchmark", Predicate("all", ("all",)), 10),
    )
    assert report.comparable is True


def test_size_difference_alone_is_not_a_finding() -> None:
    """A 20-name cohort against a 3,000-name universe is normal.

    The guard must not confuse "these populations differ in size" with "these
    populations were selected differently" -- the first is the design, the
    second is the defect.
    """
    report = ComparisonGuard().run(cohort(size=20), benchmark(size=3000))
    assert report.verdict.value == "CERTIFIED"
    assert report.cohort_size == 20 and report.benchmark_size == 3000


def test_clause_case_and_whitespace_do_not_manufacture_a_finding() -> None:
    """``"Not Stale "`` and ``"not stale"`` are one clause, not two."""
    report = ComparisonGuard().run(
        cohort(),
        benchmark(
            predicate=Predicate(
                name="eligible_as_of",
                clauses=("  History_Days >= 30 ", "NOT STALE", "not frozen as of split_ts"),
                ordered=True,
            )
        ),
    )
    assert report.same_clauses is True
    assert report.verdict.value == "CERTIFIED"


# ---------------------------------------------------------------------------
# the numeric symptom: a warning, and explicitly not proof
# ---------------------------------------------------------------------------


def test_zero_mass_symptom_warns_and_never_refuses() -> None:
    """The heuristic has INFO severity, so it cannot move the verdict."""
    dormant = [0.0] * 8 + [5.0, -2.0]
    active = [5.0, -2.0, 8.5, 3.25, -1.5, 12.0, 4.0, 1.0]
    report = ComparisonGuard().run(
        Population("cohort", SHARED, 8, tuple(active)),
        Population("benchmark", SHARED, 10, tuple(dormant)),
    )
    symptom = next(f for f in report.findings if f.code == ZERO_MASS_SYMPTOM_WARNING)
    assert symptom.status.value == "WARN"
    assert symptom.severity.value == "INFO"
    # The predicates matched, so the verdict is untouched by the symptom.
    assert report.verdict.value == "CERTIFIED"
    assert "heuristic, not proof" in symptom.message


def test_the_symptom_fixture_has_the_recorded_direction() -> None:
    """The benchmark carries the dead zeros, as in the recorded failure."""
    payload = fixtures.comparison_asymmetric()
    assert payload["zero_fraction_gap"] is not None
    assert payload["zero_fraction_gap"] > 0  # type: ignore[operator]


def test_the_symptom_does_not_fire_when_zero_mass_matches() -> None:
    """Two populations with the same zero mass raise nothing.

    This is the limit case that keeps the symptom honest: it cannot see the
    rule, only the shape, so it has nothing to say when the shapes agree.
    """
    same = [0.0, 0.0, 1.0, 2.0]
    report = ComparisonGuard().run(
        Population("cohort", SHARED, 4, tuple(same)),
        Population("benchmark", SHARED, 4, tuple(same)),
    )
    assert ZERO_MASS_SYMPTOM_WARNING not in [f.code for f in report.findings]
    assert report.findings == ()


def test_the_symptom_needs_returns_on_both_sides() -> None:
    """``None`` is not ``0.0``: unmeasured is not clean.

    Without returns the symptom is silent, and the report says ``None`` rather
    than ``0`` so a caller can tell "no symptom" from "not looked for".
    """
    report = ComparisonGuard().run(cohort(size=20), benchmark(size=400))
    assert report.zero_fraction_gap is None
    assert ZERO_MASS_SYMPTOM_WARNING not in [f.code for f in report.findings]


def test_the_symptom_cannot_be_tuned_into_a_refusal() -> None:
    """There is no threshold setting that makes the heuristic blocking."""
    dormant = [0.0] * 20
    active = [float(i) for i in range(1, 21)]
    for threshold in (0.0, 0.5, 1.0):
        report = ComparisonGuard(zero_mass_gap_threshold=threshold).run(
            Population("cohort", SHARED, 20, tuple(active)),
            Population("benchmark", SHARED, 20, tuple(dormant)),
        )
        assert report.verdict.value == "CERTIFIED", threshold
    assert report.findings, "the symptom still reports, it just does not refuse"


def test_zero_mass_gap_threshold_is_validated() -> None:
    """A share outside [0, 1] is a caller error."""
    with pytest.raises(ValueError):
        ComparisonGuard(zero_mass_gap_threshold=2.0)


# ---------------------------------------------------------------------------
# what the guard cannot do, stated as a test
# ---------------------------------------------------------------------------


def test_values_alone_cannot_reveal_the_predicate() -> None:
    """The honest limit of this guard, pinned so nobody forgets it.

    Two populations with *identical* members and identical sizes pass when both
    declare the same predicate and fail when they do not -- because the guard
    only ever looked at the declarations. The numbers were never consulted.
    That is the design: an inference would be a guess, and a guard that guesses
    is one you cannot trust when it stays silent.
    """
    members = tuple(float(i) for i in range(12))
    divergent = ComparisonGuard().run(
        Population("cohort", SHARED, 12, members),
        Population("benchmark", Predicate("other", ("history_days >= 30",)), 12, members),
    )
    assert divergent.verdict.value == "REFUSED", (
        "identical values, divergent declarations: the declaration is what is checked"
    )

    identical = ComparisonGuard().run(
        Population("cohort", SHARED, 12, members),
        Population("benchmark", SHARED, 12, members),
    )
    assert identical.verdict.value == "CERTIFIED"


def test_predicate_requires_a_name() -> None:
    """An unnamed rule cannot be diffed against anything."""
    with pytest.raises(ValueError):
        Predicate("", ("a",))


def test_population_requires_a_name_and_a_nonnegative_size() -> None:
    """Both are declared data, and both are validated at the boundary."""
    with pytest.raises(ValueError):
        Population("", SHARED, 1)
    with pytest.raises(ValueError):
        Population("cohort", SHARED, -1)


# ---------------------------------------------------------------------------
# serialisation
# ---------------------------------------------------------------------------


def test_reports_are_frozen_and_serialise() -> None:
    """The verdict travels with the findings, and the view is JSON-shaped."""
    broken = ComparisonGuard().run(
        cohort(), benchmark(predicate=Predicate("other", ("history_days >= 30",)))
    )
    with pytest.raises(Exception):
        broken.same_clauses = True  # type: ignore[misc]

    payload = broken.as_dict()
    assert payload["verdict"] == "REFUSED"
    assert payload["same_clauses"] is False
    assert payload["asymmetric_filtering"] is False
    assert isinstance(payload["findings"], list)

    cert = broken.certify()
    assert cert.certified is False
    assert cert.provenance == ("comparison",)
    assert "shared predicate" in cert.reasons[0]


# ---------------------------------------------------------------------------
# regressions for defects an independent review found in the first draft
# ---------------------------------------------------------------------------


def test_one_sided_order_declaration_does_not_manufacture_a_finding() -> None:
    """Order is compared only when BOTH sides declare it observable.

    The first draft used ``cp.ordered or bp.ordered``, so one side declaring
    order licensed a finding against a side that had explicitly said its order
    is not knowable -- the exact inference this module refuses everywhere else.
    """
    report = ComparisonGuard().run(
        Population("cohort", Predicate("p", ("a", "b"), ordered=True), 10),
        Population("benchmark", Predicate("p", ("b", "a"), ordered=False), 10),
    )
    assert report.same_order is True, "the denying side's order is not asserted"
    assert CLAUSE_ORDER_FAILURE not in [f.code for f in report.findings]
    assert report.verdict.value == "CERTIFIED"


def test_both_sides_declaring_order_still_catches_a_reversal() -> None:
    """The fix must not disable the check it guards."""
    report = ComparisonGuard().run(
        Population("cohort", Predicate("p", ("a", "b"), ordered=True), 10),
        Population("benchmark", Predicate("p", ("b", "a"), ordered=True), 10),
    )
    assert CLAUSE_ORDER_FAILURE in [f.code for f in report.findings]
    assert report.verdict.value == "REFUSED"


def test_identical_empty_declarations_record_the_absence_of_evidence() -> None:
    """Two empty predicates matching is not evidence of a shared rule.

    With the under-specification check relaxed, the guard would otherwise find
    two empty declarations "identical" and export ``predicate_identical: True``
    drawn from no information at all.
    """
    report = ComparisonGuard(allow_empty_clauses=True).run(
        Population("cohort", Predicate("none", ()), 10),
        Population("benchmark", Predicate("none", ()), 10),
    )
    warn = next(
        f for f in report.findings if f.code == UNDECLARED_PREDICATE_FAILURE
    )
    assert warn.status.value == "WARN"
    assert "nothing to disagree about" in warn.message


def test_the_zero_mass_symptom_downgrades_the_composite_to_suspect() -> None:
    """The heuristic cannot *refuse*, but it is not invisible either.

    The report-local verdict stays CERTIFIED; the aggregate maps any WARN to
    SUSPECT. An earlier docstring claimed the heuristic could not reach the
    verdict at all, which was false -- this pins the real behaviour.
    """
    from honest_backtest.report import HonestyReport, ResultSet

    shared = Predicate("p", ("a",), ordered=True)
    report = HonestyReport.run(
        ResultSet(
            name="symptom_only",
            cohort_population=Population("cohort", shared, 4, (1.0, 2.0, 3.0, 4.0)),
            benchmark_population=Population(
                "benchmark", shared, 8, (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 5.0)
            ),
        )
    )
    assert report.verdict.value == "SUSPECT"
    assert ZERO_MASS_SYMPTOM_WARNING in [
        f.code for f in report.findings
    ]
    assert not report.failures(), "the heuristic produced no BLOCKING finding"
