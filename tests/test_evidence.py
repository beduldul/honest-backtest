"""Guard 7 (evidence presence): does a null claim rest on a clean observation?

The tests that matter in this file are the two directions on the real fixtures:

* the guard **fires** on ``PYPI_SCAN_503`` -- five names recorded as absent on a
  503, one of which is present on PyPI; and
* the guard **stays silent** on ``PYPI_THREE_STATE_CORRECTED`` -- the same probe
  run afterwards, which classified non-404s as ``UNKNOWN`` instead of absent.

Both directions are required. A guard that refuses everything is a rejection
machine, and a guard that refuses nothing is decoration.
"""

from __future__ import annotations

import pytest

from honest_backtest import fixtures
from honest_backtest.guards.evidence import (
    CONTROL_FAILED_FAILURE,
    DEFAULT_CODE_CLASSES,
    NO_OBSERVATIONS_FAILURE,
    UNSUPPORTED_ABSENCE_FAILURE,
    UNCONTROLLED_NULL_FAILURE,
    UNKNOWN_CLASS_FAILURE,
    EvidenceClass,
    EvidenceGuard,
    Observation,
    classify_codes,
)

# ---------------------------------------------------------------------------
# the classification table
# ---------------------------------------------------------------------------


def test_status_codes_are_not_found_codes() -> None:
    """The recorded failure in its smallest possible form.

    503 means "I could not answer"; 404 means "the answer is no". The guard
    exists because those two were written down in the same shape.
    """
    guard = EvidenceGuard()
    assert guard.classify("404") is EvidenceClass.ABSENT
    assert guard.classify("503") is EvidenceClass.UNKNOWN
    assert guard.classify("429") is EvidenceClass.UNKNOWN
    assert guard.classify("200") is EvidenceClass.PRESENT


def test_every_recorded_infrastructure_failure_is_unknown() -> None:
    """Rate limits, outages, timeouts and resets are all inconclusive."""
    guard = EvidenceGuard()
    for code in (
        "429", "500", "502", "503", "504",
        "TIMEOUT", "ETIMEDOUT", "ECONNRESET", "ECONNREFUSED", "EAI_AGAIN",
    ):
        assert guard.classify(code) is EvidenceClass.UNKNOWN, code


def test_unnamed_codes_default_to_unknown_not_absent() -> None:
    """The asymmetry is the whole design.

    A code nobody thought about must never be read as a finding of absence:
    calling a present object unknown costs a lead, calling an unreachable
    object absent costs a false conclusion. So the unknown direction is the
    default and it is not configurable.
    """
    guard = EvidenceGuard()
    for code in ("418", "IM_A_TEAPOT", "sprocket", "0x1f", ""):
        assert guard.classify(code) is EvidenceClass.UNKNOWN, code


def test_gone_and_enoent_are_absent_by_default() -> None:
    """410 and ENOENT both resolve the question, and the table says so.

    These are the documented reclassifications from the brief: an API that
    retires packages answers 410, a filesystem answers ENOENT, and both mean
    the object was asked for and is not there.
    """
    guard = EvidenceGuard()
    assert guard.classify("410") is EvidenceClass.ABSENT
    assert guard.classify("enoent") is EvidenceClass.ABSENT


def test_the_table_covers_the_three_classes() -> None:
    """No class may be unreachable from the public table."""
    for cls in EvidenceClass:
        assert cls.value in set(DEFAULT_CODE_CLASSES.values()), cls


def test_codes_are_configurable_for_non_http_sources() -> None:
    """GraphQL returns 200 with a null body; a JSON API returns a field.

    Nothing in the guard is HTTP-specific, and this is the test that says so:
    a caller that reclassifies ``GRAPHQL_NULL`` as UNKNOWN while ``200`` keeps
    its default still gets the rest of the table.
    """
    guard = EvidenceGuard(code_classes={"FOUND_FALSE": "ABSENT", "GRAPHQL_NULL": "UNKNOWN"})
    assert guard.classify("FOUND_FALSE") is EvidenceClass.ABSENT
    assert guard.classify("GRAPHQL_NULL") is EvidenceClass.UNKNOWN
    # The merge does not wipe out the defaults.
    assert guard.classify("404") is EvidenceClass.ABSENT
    assert guard.classify("503") is EvidenceClass.UNKNOWN


def test_unknown_codes_override_the_table() -> None:
    """A source that lies about its codes can be forced to UNKNOWN.

    An API that returns 404 for transient errors is exactly this case, and the
    caller's knowledge has to beat the table -- otherwise the guard would be
    fooled by the same class of lie it was built to catch.
    """
    guard = EvidenceGuard(unknown_codes=["404"])
    assert guard.classify("404") is EvidenceClass.UNKNOWN


def test_classify_codes_groups_without_reimplementing_the_table() -> None:
    """The table is the interface, so triage does not get its own copy."""
    groups = classify_codes(
        [Observation("a", "200"), Observation("b", "404"), Observation("c", "503")]
    )
    assert [o.subject for o in groups["PRESENT"]] == ["a"]
    assert [o.subject for o in groups["ABSENT"]] == ["b"]
    assert [o.subject for o in groups["UNKNOWN"]] == ["c"]


# ---------------------------------------------------------------------------
# the broken case: the guard must fire
# ---------------------------------------------------------------------------


def test_guard_fires_on_the_503_scan(evidence_broken: dict[str, object]) -> None:
    """The real defect: absence inferred from a rate-limited scan."""
    assert evidence_broken["fixture"] == "pypi_scan_503"
    assert evidence_broken["verdict"] == "REFUSED"
    codes = [f["code"] for f in evidence_broken["findings"]]  # type: ignore[union-attr]
    assert UNKNOWN_CLASS_FAILURE in codes


def test_the_503_scan_recorded_five_names_as_absent() -> None:
    """The count is the fixture's, and it is the claim's whole basis."""
    rows = fixtures.PYPI_SCAN_503["observations"]
    assert isinstance(rows, list)
    declared = [r[0] for r in rows if r[1] is False]
    assert len([r for r in rows if r[2] == "503"]) == 5
    assert "overfit" in declared, "the name that was actually present"


def test_the_guard_names_the_subjects_it_refused() -> None:
    """A refusal has to say *which* observations were misread.

    "Something was wrong" is not actionable. The finding carries the subjects
    and the codes so the reader can re-run those five probes.
    """
    report = EvidenceGuard().run(
        [
            Observation("pbo", "503"),
            Observation("cscv", "503"),
            Observation("backtest-overfitting", "404"),
        ],
        claimed_absent=["pbo", "cscv"],
    )
    finding = next(f for f in report.findings if f.code == UNKNOWN_CLASS_FAILURE)
    assert "pbo=503" in finding.message
    assert "cscv=503" in finding.message
    assert finding.detail["n_misread"] == 2


def test_one_misread_observation_is_enough_to_refuse() -> None:
    """No tolerance band: a single false absence is a wrong number.

    The recorded failure turned on one name (``overfit``) that was reported
    missing and was not. A threshold that let one through would have let that
    one through.
    """
    report = EvidenceGuard().run([Observation("overfit", "503")], claimed_absent=["overfit"])
    assert report.verdict.value == "REFUSED"
    assert report.n_absent == 0


def test_a_null_claim_without_a_positive_control_is_refused() -> None:
    """The Sourcegraph failure: zero read as "nobody does this".

    Nothing in the set returned a thing, and nothing demonstrates the
    instrument can return a thing. The zero is not evidence of absence.
    """
    report = EvidenceGuard(negative_claim="no prior art exists").run(
        [Observation("def sharpe_ratio", "0")]
    )
    assert report.verdict.value == "REFUSED"
    assert UNCONTROLLED_NULL_FAILURE in [f.code for f in report.findings]
    assert report.controlled is False


def test_the_broken_control_proves_the_instrument_was_broken() -> None:
    """``numba`` returning 1 is the control that condemns the zeros.

    A term guaranteed to appear in thousands of repositories returned one
    match. The instrument was not measuring the world, and the near-zero is the
    evidence -- read as a passing control it would have certified the zeros.
    """
    payload = fixtures.evidence_null_without_control()
    assert payload["verdict"] == "REFUSED"
    codes = [f["code"] for f in payload["findings"]]  # type: ignore[union-attr]
    assert UNKNOWN_CLASS_FAILURE in codes
    assert payload["control_subject"] == "numba"
    assert payload["control_count"] == 1
    assert payload["control_passed"] is False, (
        "a control that returns 1 for a term present in thousands of repositories "
        "has failed; treating it as a pass would certify the zeros"
    )


def test_the_correction_is_transcribed_alongside_the_illustrative_counts() -> None:
    """The decider moved 4 -> 10-18; that part is real and is labelled so."""
    payload = fixtures.evidence_null_without_control()
    correction = payload["measured_correction"]
    assert isinstance(correction, dict)
    assert correction["false_decider"] == 4
    assert correction["corrected_decider_low"] == 10
    assert correction["corrected_decider_high"] == 18


def test_an_empty_observation_set_is_refused_not_passed() -> None:
    """An empty scan is not a clean scan -- same rule as the aggregator's."""
    report = EvidenceGuard().run([])
    assert report.verdict.value == "REFUSED"
    assert report.findings[0].code == NO_OBSERVATIONS_FAILURE
    assert report.findings[0].status.value == "ERROR"


# ---------------------------------------------------------------------------
# the corrected case: the guard must stay silent
# ---------------------------------------------------------------------------


def test_guard_stays_silent_on_the_corrected_scan(evidence_corrected: dict[str, object]) -> None:
    """The same probes, classified honestly, must pass."""
    assert evidence_corrected["fixture"] == "pypi_three_state_corrected"
    assert evidence_corrected["verdict"] == "CERTIFIED"
    assert evidence_corrected["findings"] == []
    assert evidence_corrected["controlled"] is True


def test_corrected_scan_matches_the_artifact_counts() -> None:
    """The fixture's own totals, recomputed from its rows."""
    payload = fixtures.evidence_corrected()
    spec = fixtures.PYPI_THREE_STATE_CORRECTED["measured_counts"]
    assert isinstance(spec, dict)
    assert payload["n_present"] == spec["PRESENT"]
    assert payload["n_absent"] == spec["ABSENT"]
    assert payload["n_unknown"] == spec["UNKNOWN"]


def test_the_corrected_scan_resolves_the_name_the_broken_one_lost() -> None:
    """``overfit`` is PRESENT, and that is the finding, not a footnote."""
    correction = fixtures.PYPI_THREE_STATE_CORRECTED["measured_correction"]
    assert isinstance(correction, dict)
    assert correction["actually_present"] == ["overfit"]
    rows = fixtures.PYPI_THREE_STATE_CORRECTED["observations"]
    assert isinstance(rows, list)
    overfit = next(r for r in rows if r[0] == "overfit")
    assert overfit[1] == "PRESENT"


def test_the_corrected_scan_keeps_its_two_honest_unknowns() -> None:
    """404 is not enough when the other endpoint never answered.

    ``overfit-diagnostic`` and ``purgekit`` both produced a 404 in the
    corrected run and the run still refused to call them absent. A fixture that
    tidied those two into ABSENT would make the corrected scan look *cleaner*
    than it was, which is the same overstatement in the other direction.
    """
    payload = fixtures.evidence_corrected()
    assert payload["n_unknown"] == 2
    assert payload["conclusive_fraction"] < 1.0


def test_a_clean_scan_with_a_control_certifies() -> None:
    """The plain positive direction, on synthetic data.

    Every absence is a 404 and a known-positive control came back 200, so the
    null is supported and there is nothing to refuse.
    """
    report = EvidenceGuard().run(
        [Observation("a", "404"), Observation("b", "404"), Observation("c", "200")],
        controls=[Observation("deflated-sharpe", "200")],
    )
    assert report.verdict.value == "CERTIFIED"
    assert report.findings == ()
    assert report.controlled is True
    assert report.control_subject == "deflated-sharpe"


def test_an_instrument_that_found_something_needs_no_explicit_control() -> None:
    """A PRESENT observation is its own control: the instrument demonstrably
    returned something, so the absences beside it are supported.

    The control requirement is a requirement that *something* in the run show
    the instrument works, not a requirement for a designated control row.
    """
    report = EvidenceGuard().run([Observation("a", "200"), Observation("b", "404")])
    assert report.verdict.value == "CERTIFIED"
    assert report.controlled is False, "no *designated* control was supplied"
    assert report.n_present == 1, "but one was demonstrated by the data"
    assert report.findings == ()


# ---------------------------------------------------------------------------
# the instruments that are not conclusions
# ---------------------------------------------------------------------------


def test_a_null_without_a_control_is_refused_even_unclaimed() -> None:
    """The default configuration must not certify an unresolved scan.

    An earlier draft only refused when the caller *asserted* a negative claim
    and merely warned otherwise, which meant the default path CERTIFIED a set
    where nothing had been resolved -- the recorded failure, produced by the
    defaults. "I have not finished looking" is a reason not to draw a
    conclusion, not a reason to certify one.
    """
    report = EvidenceGuard().run([Observation("a", "503")])
    assert report.verdict.value == "REFUSED"
    assert UNCONTROLLED_NULL_FAILURE in [f.code for f in report.findings]
    assert report.controlled is False


def test_mostly_unknown_evidence_refuses_when_nothing_resolved() -> None:
    """Four of five probes never resolved the question.

    Not a warning: the set *is* a null result, and nothing in it shows the
    instrument works, so it refuses. The conclusive fraction is still reported
    for the reader, but it is no longer the only thing standing between this
    scan and a clean bill of health.
    """
    report = EvidenceGuard().run(
        [Observation("a", "503"), Observation("b", "429"),
         Observation("c", "TIMEOUT"), Observation("d", "503"),
         Observation("e", "404")]
    )
    assert report.conclusive_fraction == pytest.approx(0.2)
    assert report.verdict.value == "REFUSED"
    assert UNCONTROLLED_NULL_FAILURE in [f.code for f in report.findings]


def test_mostly_unknown_with_one_present_still_warns() -> None:
    """One PRESENT observation is its own control: the instrument did return.

    The null guard does not fire, so a set that is mostly unresolved is a
    warning rather than a refusal -- but it still is not allowed to look clean.
    """
    report = EvidenceGuard().run(
        [Observation("a", "503"), Observation("b", "429"),
         Observation("c", "TIMEOUT"), Observation("d", "503"),
         Observation("e", "200")]
    )
    assert report.verdict.value == "CERTIFIED"
    assert UNKNOWN_CLASS_FAILURE in [f.code for f in report.findings]
    assert all(f.status.value == "WARN" for f in report.findings)


def test_conclusive_fraction_is_one_when_everything_resolved() -> None:
    """PRESENT and ABSENT both count: the instrument answered."""
    report = EvidenceGuard().run([Observation("a", "200"), Observation("b", "404")])
    assert report.conclusive_fraction == 1.0


def test_conclusive_fraction_is_zero_for_an_empty_set() -> None:
    """No division by zero, and no vacuous 100%."""
    assert EvidenceGuard().run([]).conclusive_fraction == 0.0


# ---------------------------------------------------------------------------
# typing, immutability and serialisation
# ---------------------------------------------------------------------------


def test_observation_requires_a_code() -> None:
    """A missing code is UNKNOWN, and the type says so rather than defaulting.

    Defaulting the code to absence would rebuild the recorded defect inside the
    guard that exists to catch it.
    """
    with pytest.raises(TypeError):
        Observation("a")  # type: ignore[call-arg]


def test_observation_requires_a_subject() -> None:
    """An unattributable observation cannot be reported on."""
    with pytest.raises(ValueError):
        Observation("", "404")


def test_reports_are_frozen() -> None:
    """The verdict travels with the finding, not beside it."""
    report = EvidenceGuard().run([Observation("a", "404")])
    with pytest.raises(Exception):
        report.n_absent = 99  # type: ignore[misc]


def test_report_serialises_and_certifies() -> None:
    """The same two directions, through the ``certify()`` path."""
    good = EvidenceGuard().run([Observation("a", "404")], controls=[Observation("k", "200")])
    assert good.certify().certified is True
    assert good.certify().provenance == ("evidence",)

    bad = EvidenceGuard().run([Observation("a", "503")], claimed_absent=["a"])
    cert = bad.certify()
    assert cert.certified is False
    assert "404" in cert.reasons[0] or "not there" in cert.reasons[0]

    payload = bad.as_dict()
    assert payload["verdict"] == "REFUSED"
    assert payload["n_unknown"] == 1
    assert isinstance(payload["findings"], list)


def test_min_conclusive_fraction_is_validated() -> None:
    """A threshold outside [0, 1] is a caller error, not a silent clamp."""
    with pytest.raises(ValueError):
        EvidenceGuard(min_conclusive_fraction=1.5)


# ---------------------------------------------------------------------------
# regressions for defects an independent review found in the first draft
# ---------------------------------------------------------------------------


def test_empty_observations_with_controls_do_not_crash() -> None:
    """The class counts must not divide by zero when only controls exist.

    ``EvidenceReport.conclusive_fraction`` already handled ``n==0``; the call
    site inside ``run()`` did not, so a caller passing only controls hit a
    ZeroDivisionError from a guard whose entire job is to be dependable on
    malformed input.
    """
    report = EvidenceGuard().run((), controls=(Observation("control", "200"),))
    assert report.n_observations == 0
    assert report.conclusive_fraction == 0.0
    assert report.verdict.value == "REFUSED"  # no observations is not a pass


def test_a_failed_control_is_a_blocking_finding() -> None:
    """The `numba` -> 1 case: a control that fails is stronger than no control.

    A control probe on a known-positive input that does not come back present
    proves the instrument is broken. Discarding it and behaving as though no
    control was supplied would throw away the clearest evidence in the run.
    """
    report = EvidenceGuard().run(
        [Observation("def sharpe_ratio", "0")],
        controls=[Observation("numba", "1")],
        claimed_absent=["def sharpe_ratio"],
    )
    codes = [f.code for f in report.findings]
    assert CONTROL_FAILED_FAILURE in codes
    finding = next(f for f in report.findings if f.code == CONTROL_FAILED_FAILURE)
    assert finding.status.value == "FAIL"
    assert finding.severity.value == "BLOCKING"
    assert "numba=1" in finding.message
    assert report.controlled is False


def test_known_positive_code_is_enforced_not_merely_recorded() -> None:
    """A control must carry the *configured* success code, not just any pass.

    The parameter was dead in the first draft: it appeared in the signature and
    the docstring and was never read, so a caller pinning it believed a
    constraint existed that did not.
    """
    # A control coded '201' is PRESENT by the table, but not the configured code.
    strict = EvidenceGuard(known_positive_code="200").run(
        [Observation("a", "404")], controls=(Observation("control", "201"),)
    )
    assert strict.controlled is False
    assert CONTROL_FAILED_FAILURE in [f.code for f in strict.findings]

    # Declaring '201' as the code this instrument returns accepts it.
    lenient = EvidenceGuard(known_positive_code="201").run(
        [Observation("a", "404")], controls=(Observation("control", "201"),)
    )
    assert lenient.controlled is True
    assert CONTROL_FAILED_FAILURE not in [f.code for f in lenient.findings]


def test_absence_claimed_without_an_observation_is_refused() -> None:
    """The mirror of the 503 check: an absence is a claim needing support."""
    report = EvidenceGuard().run(
        [Observation("a", "404")], claimed_absent=["a", "b", "c"]
    )
    assert UNSUPPORTED_ABSENCE_FAILURE in [f.code for f in report.findings]
    finding = next(f for f in report.findings if f.code == UNSUPPORTED_ABSENCE_FAILURE)
    assert finding.detail["subjects"] == "b, c"
    assert report.verdict.value == "REFUSED"


def test_absence_contradicted_by_a_present_observation_is_refused() -> None:
    """Claiming a subject is absent while observing it present is a refusal."""
    report = EvidenceGuard().run(
        [Observation("a", "200")], claimed_absent=["a"]
    )
    finding = next(
        f for f in report.findings
        if f.code == UNSUPPORTED_ABSENCE_FAILURE
    )
    assert finding.detail["contradicted_by_present"] == "a"
    assert report.verdict.value == "REFUSED"


def test_a_supported_absence_claim_is_not_refused() -> None:
    """The clean direction for the new check: every claim has its 404.

    A guard that refuses every absence claim would forbid the thing it exists
    to make safe, so this pins that a properly-supported claim passes.
    """
    report = EvidenceGuard().run(
        [Observation("a", "404"), Observation("b", "404")],
        controls=(Observation("control", "200"),),
        claimed_absent=["a", "b"],
    )
    assert report.verdict.value == "CERTIFIED"
    assert report.findings == ()
