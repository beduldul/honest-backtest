"""Guard 4 -- the benchmark-eligibility asymmetry.

The measured defect: the cohort filter excluded stale/dormant subjects and the
benchmark filter did not, so dormant subjects (flat 0% forward return) dragged
the benchmark toward zero and made the cohort look skilful.

The test that matters here is
:func:`test_divergent_predicates_are_caught` -- a guard against divergence that
is never tested against divergence is decoration.
"""

from __future__ import annotations

import pytest

from honest_backtest import fixtures
from honest_backtest.guards.universe import (
    Selection,
    UniverseGuard,
    predicate_fingerprint,
    require_shared_predicate,
)
from honest_backtest.types import Verdict

STALE_THRESHOLD = fixtures.STALE_THRESHOLD_DAYS


def _eligible(subject: dict[str, object]) -> bool:
    """The correct shared predicate: drop stale and dormant subjects."""
    return bool(subject.get("age_days", 0) >= STALE_THRESHOLD) and not bool(  # type: ignore[operator]
        subject.get("dormant", False)
    )


def _cohort_only(subject: dict[str, object]) -> bool:
    """The defect: staleness excluded on the cohort side only."""
    return bool(subject.get("age_days", 0) >= STALE_THRESHOLD)  # type: ignore[operator]


def test_divergent_predicates_are_caught() -> None:
    """THE test. Two different filters must be refused, always."""
    report = UniverseGuard(require_identical_object=True).run(
        Selection(name="cohort", predicate=_eligible, selected=("a", "b")),
        Selection(name="benchmark", predicate=_cohort_only, selected=("a", "b", "c")),
    )
    assert report.symmetric is False
    assert report.verdict is Verdict.REFUSED
    assert report.findings[0].code == "UNIVERSE_ASYMMETRIC_PREDICATE"
    assert report.same_object is False


def test_same_predicate_object_is_symmetric() -> None:
    """The fix: one predicate object routes both sides."""
    shared = _eligible
    subjects = tuple({"id": i, "age_days": 90, "dormant": False} for i in range(10))
    report = UniverseGuard().run(
        Selection(name="cohort", predicate=shared, selected=subjects[:5]),
        Selection(name="benchmark", predicate=shared, selected=subjects[5:]),
    )
    assert report.symmetric is True
    assert report.verdict is Verdict.CERTIFIED
    assert report.same_object is True
    assert report.fingerprint is not None


def test_fixture_reproduces_the_recorded_defect() -> None:
    """The shipped fixture must refuse, and the error must name the halves."""
    payload = fixtures.universe_asymmetric()
    assert payload["verdict"] == "REFUSED"
    codes = {f["code"] for f in payload["findings"]}  # type: ignore[index]
    assert "UNIVERSE_ASYMMETRIC_PREDICATE" in codes


def test_relaxing_identity_still_catches_a_source_difference() -> None:
    """``require_identical_object=False`` does not make the guard a no-op.

    With identity relaxed, two closures over the same source body are accepted
    -- but two closures with genuinely different bodies are still refused. That
    is the whole point of the fingerprint fallback.
    """
    guard = UniverseGuard(require_identical_object=False)

    def make_predicate(threshold: int) -> object:
        def eligible(subject: dict[str, object]) -> bool:
            return bool(subject.get("age_days", 0) >= threshold)  # type: ignore[operator]

        return eligible

    report = guard.run(
        Selection(name="cohort", predicate=make_predicate(30), selected=("a",)),
        Selection(name="benchmark", predicate=make_predicate(60), selected=("a",)),
    )
    assert report.same_object is False
    assert report.verdict is Verdict.REFUSED


def test_require_shared_predicate_raises_on_divergence() -> None:
    """The standalone helper is the enforcement arm for code that can't use the guard."""
    with pytest.raises(ValueError, match="different predicates"):
        require_shared_predicate(
            Selection(name="cohort", predicate=_eligible, selected=("a",)),
            Selection(name="benchmark", predicate=_cohort_only, selected=("a",)),
        )


def test_require_shared_predicate_accepts_a_matched_pair() -> None:
    """No exception when both sides share one object."""
    shared = _eligible
    require_shared_predicate(
        Selection(name="cohort", predicate=shared, selected=("a",)),
        Selection(name="benchmark", predicate=shared, selected=("b",)),
    )


def test_empty_benchmark_is_refused() -> None:
    """An empty universe makes every excess statistic undefined."""
    shared = _eligible
    report = UniverseGuard(min_size=1).run(
        Selection(name="cohort", predicate=shared, selected=("a",)),
        Selection(name="benchmark", predicate=shared, selected=()),
    )
    assert report.verdict is Verdict.REFUSED
    assert any(f.code == "UNIVERSE_EMPTY_SELECTION" for f in report.findings)


def test_re_derivation_detects_a_hand_assembled_universe() -> None:
    """A declared universe that its own predicate does not reproduce is refused.

    This catches the asymmetry hiding *below* the predicate comparison: a
    manual exclusion list, a post-hoc filter, a stale cache.
    """
    shared = _eligible
    subjects = tuple(
        {"id": i, "age_days": 90 if i < 8 else 5, "dormant": False} for i in range(10)
    )
    # Declares all 10 as the cohort, but the predicate only selects the 8 fresh.
    report = UniverseGuard().check(
        Selection(name="cohort", predicate=shared, selected=subjects),
        Selection(name="benchmark", predicate=shared, selected=subjects),
        subjects=subjects,
    )
    assert report.verdict is Verdict.REFUSED
    assert any("assembled by something other than the predicate" in f.message for f in report.findings)


def test_dormant_subjects_are_the_mechanism() -> None:
    """The statistical symptom, made explicit.

    Dormant subjects have a flat 0% forward return. Including them on the
    benchmark side but not the cohort side drags the benchmark toward zero,
    which is what manufactured the apparent skill: the cohort's excess return
    is computed against a benchmark that is half asleep.
    """
    # 20 active subjects: long-lived, genuine 1.2% forward return.
    active = tuple(
        {"id": i, "age_days": 90, "dormant": False, "fwd_return": 0.012}
        for i in range(20)
    )
    # 20 dormant subjects: also 90 days old, so they pass any age test -- they
    # are excluded by the *dormancy* clause alone. Flat 0% forward return.
    # This is the shape of the real defect: only the cohort filter checked
    # dormancy, so these 20 dragged the benchmark toward zero.
    dormant = tuple(
        {"id": 100 + i, "age_days": 90, "dormant": True, "fwd_return": 0.0}
        for i in range(20)
    )
    subjects = active + dormant

    cohort = tuple(s for s in subjects if _eligible(s))
    buggy_benchmark = tuple(s for s in subjects if _cohort_only(s))
    fixed_benchmark = tuple(s for s in subjects if _eligible(s))

    assert len(cohort) == 20
    assert len(buggy_benchmark) == 40, "the buggy filter keeps the dormant half"
    assert len(fixed_benchmark) == 20

    cohort_ret = mean_return(cohort)
    buggy_ret = mean_return(buggy_benchmark)
    fixed_ret = mean_return(fixed_benchmark)

    assert buggy_ret == pytest.approx(0.006)
    assert fixed_ret == pytest.approx(0.012)
    assert buggy_ret < fixed_ret, "the defect drags the benchmark toward zero"

    buggy_excess = cohort_ret - buggy_ret
    fixed_excess = cohort_ret - fixed_ret
    assert buggy_excess > fixed_excess, (
        "the defect inflates the apparent excess return -- this is how a "
        "code defect produced a statistical symptom"
    )
    assert buggy_excess == pytest.approx(0.006)
    assert fixed_excess == pytest.approx(0.0)


def mean_return(subjects: tuple[dict[str, object], ...]) -> float:
    """Mean forward return of a subject selection."""
    if not subjects:
        raise ValueError("empty selection")
    return sum(float(s["fwd_return"]) for s in subjects) / len(subjects)  # type: ignore[arg-type]


def test_fingerprint_is_stable_and_source_sensitive() -> None:
    """Fingerprints must be deterministic and must move when the body moves."""
    assert predicate_fingerprint(_eligible) == predicate_fingerprint(_eligible)
    assert predicate_fingerprint(_eligible) != predicate_fingerprint(_cohort_only)


def test_fingerprint_survives_a_builtin() -> None:
    """Builtins have no recoverable source; the guard must not crash."""
    fp = predicate_fingerprint(bool)
    assert isinstance(fp, str) and len(fp) == 16


def test_empty_cohort_and_benchmark_both_reported() -> None:
    """Both sides are checked, not just the first failure found."""
    shared = _eligible
    report = UniverseGuard(min_size=2).run(
        Selection(name="cohort", predicate=shared, selected=()),
        Selection(name="benchmark", predicate=shared, selected=()),
    )
    sides = {f.detail.get("side") for f in report.findings}
    assert sides == {"cohort", "benchmark"}


def test_report_is_serialisable() -> None:
    """The report must survive JSON."""
    shared = _eligible
    payload = (
        UniverseGuard()
        .run(
            Selection(name="cohort", predicate=shared, selected=("a",)),
            Selection(name="benchmark", predicate=shared, selected=("b",)),
        )
        .as_dict()
    )
    assert payload["symmetric"] is True
    assert payload["verdict"] == "CERTIFIED"
    assert isinstance(payload["fingerprint"], str)


def test_invalid_min_size_rejected() -> None:
    """Negative sizes are rejected at construction."""
    with pytest.raises(ValueError):
        UniverseGuard(min_size=-1)
