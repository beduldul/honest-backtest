"""Guard 5 -- multiple-testing accounting.

The measured failures: 341 configurations with ~17 expected false positives at
alpha = 0.05 and nominal positives sitting right at that rate; and 60
configurations with one positive where ~3 are expected.
"""

from __future__ import annotations

import pytest

from honest_backtest import fixtures
from honest_backtest.guards.multiplicity import (
    ExperimentCounter,
    correct_p,
    expected_false_positives,
)
from honest_backtest.types import Verdict


def test_341_configurations_imply_17_expected_false_positives() -> None:
    """The headline arithmetic: 341 * 0.05 = 17.05."""
    counter = ExperimentCounter(alpha=0.05)
    for i in range(341):
        counter.record(f"cfg-{i}")

    assert len(counter) == 341
    report = counter.report()

    assert report.n_experiments == 341
    assert report.expected_false_positives == pytest.approx(17.05)


def test_nominal_positives_at_the_chance_rate_are_refused() -> None:
    """16 positives where ~17 are expected is not a finding."""
    counter = ExperimentCounter(alpha=0.05)
    for i in range(341):
        counter.record(f"cfg-{i}")

    report = counter.report(n_nominal_positives=16)

    assert report.at_chance_rate is True
    assert report.verdict is Verdict.REFUSED
    codes = {f.code for f in report.findings}
    assert "MULTIPLICITY_AT_CHANCE_RATE" in codes
    message = next(f.message for f in report.findings if f.code == "MULTIPLICITY_AT_CHANCE_RATE")
    assert "17.1" in message
    assert "chance" in message


def test_a_claimed_p_value_does_not_survive_bonferroni() -> None:
    """p = 0.03 over a family of 341 becomes 1.0."""
    counter = ExperimentCounter(alpha=0.05, correction="bonferroni")
    for i in range(341):
        counter.record(f"cfg-{i}")

    report = counter.report(claimed_p=0.03)

    assert report.adjusted_p is not None
    assert report.adjusted_p == pytest.approx(1.0)
    assert report.survives_correction is False
    assert report.verdict is Verdict.REFUSED
    assert "does not survive bonferroni correction" in report.findings[0].message


def test_bonferroni_and_sidak_are_both_available_and_ordered() -> None:
    """Sidak is uniformly the weaker correction; the default is Bonferroni."""
    p, m = 0.01, 100
    bonf = ExperimentCounter.bonferroni(p, m)
    sidak = ExperimentCounter.sidak(p, m)

    assert bonf == pytest.approx(1.0)
    assert sidak < bonf or sidak == bonf
    assert sidak == pytest.approx(1 - (1 - 0.01) ** 100)


def test_60_configurations_with_one_positive_is_at_chance() -> None:
    """One positive in a family where ~3 are expected carries no evidence."""
    counter = ExperimentCounter(alpha=0.05)
    for i in range(60):
        counter.record(f"cfg-{i}")

    report = counter.report(n_nominal_positives=1)

    assert report.expected_false_positives == pytest.approx(3.0)
    assert report.at_chance_rate is True
    assert report.verdict is Verdict.REFUSED


def test_an_uninstrumented_family_size_is_flagged_as_declared() -> None:
    """A declared family size is exactly the number an author is tempted to trim."""
    counter = ExperimentCounter(alpha=0.05)
    report = counter.report(n_experiments=341)

    codes = {f.code for f in report.findings}
    assert "MULTIPLICITY_UNCORRECTED" in codes
    assert any("declared, not observed" in f.message for f in report.findings)
    assert report.n_experiments == 341


def test_a_strong_p_value_survives_a_small_family() -> None:
    """The negative direction: a real effect in a small family passes."""
    counter = ExperimentCounter(alpha=0.05, correction="bonferroni")
    for i in range(5):
        counter.record(f"cfg-{i}")

    report = counter.report(claimed_p=0.0001, n_nominal_positives=1)

    assert report.adjusted_p is not None
    assert report.adjusted_p == pytest.approx(0.0005)
    assert report.survives_correction is True
    assert report.verdict is Verdict.CERTIFIED


def test_no_claim_means_no_refusal() -> None:
    """A design-time census with no quoted p-value must not block work."""
    counter = ExperimentCounter(alpha=0.05)
    for i in range(341):
        counter.record(f"cfg-{i}")

    report = counter.report()

    assert report.original_p is None
    assert report.verdict is Verdict.CERTIFIED
    assert report.n_nominal_positives == 0


def test_uncorrected_family_is_refused() -> None:
    """Explicitly asking for no correction on a large family is refused."""
    counter = ExperimentCounter(alpha=0.05, correction="none")
    for i in range(100):
        counter.record(f"cfg-{i}")

    report = counter.report(claimed_p=0.02)

    assert report.verdict is Verdict.REFUSED
    message = report.findings[0].message
    assert "no correction" in message
    assert "5.0" in message  # 100 * 0.05


def test_known_limitations_are_carried_on_every_report() -> None:
    """The correction is never presented as stronger than it is."""
    counter = ExperimentCounter(alpha=0.05)
    counter.record("only")
    report = counter.report()

    assert len(report.known_limitations) >= 3
    joined = " ".join(report.known_limitations)
    assert "fixed in advance" in joined
    assert "dependence" in joined
    assert "never recorded" in joined


def test_module_level_helpers_match_the_class() -> None:
    """The convenience functions and the class agree."""
    assert expected_false_positives(341) == pytest.approx(17.05)
    assert correct_p(0.01, 100, method="bonferroni") == pytest.approx(1.0)
    assert correct_p(0.01, 100, method="sidak") == pytest.approx(1 - 0.99**100)
    assert correct_p(0.01, 100, method="none") == pytest.approx(0.01)
    with pytest.raises(ValueError):
        correct_p(0.01, 100, method="magic")  # type: ignore[arg-type]


def test_batching_does_not_undercount() -> None:
    """A vectorised sweep of 40 must be recorded as 40, not one call."""
    counter = ExperimentCounter(alpha=0.05)
    counter.record("batch", weight=40)
    assert len(counter) == 40
    assert counter.report().n_experiments == 40


def test_fixture_reproduces_the_341_study() -> None:
    """The shipped fixture lands on the measured numbers."""
    payload = fixtures.multiplicity_341()
    assert payload["n_experiments"] == 341
    assert payload["expected_false_positives"] == pytest.approx(17.05)
    assert payload["n_nominal_positives"] == 16
    assert payload["adjusted_p"] == pytest.approx(1.0)
    assert payload["verdict"] == "REFUSED"


def test_invalid_inputs_are_rejected() -> None:
    """Bounds are checked at the boundary."""
    with pytest.raises(ValueError):
        ExperimentCounter(alpha=0.0)
    with pytest.raises(ValueError):
        ExperimentCounter(alpha=1.0)
    with pytest.raises(ValueError):
        ExperimentCounter(correction="holm")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        ExperimentCounter.bonferroni(0.5, 0)
    with pytest.raises(ValueError):
        ExperimentCounter.bonferroni(1.5, 10)
    with pytest.raises(ValueError):
        ExperimentCounter.sidak(-0.1, 10)
    with pytest.raises(ValueError):
        ExperimentCounter().record("x", weight=0)


def test_report_is_serialisable() -> None:
    """The report must survive JSON."""
    counter = ExperimentCounter(alpha=0.05)
    for i in range(341):
        counter.record(f"cfg-{i}")
    payload = counter.report(claimed_p=0.03, n_nominal_positives=16).as_dict()

    assert payload["n_experiments"] == 341
    assert payload["expected_false_positives"] == pytest.approx(17.05)
    assert payload["verdict"] == "REFUSED"
    assert isinstance(payload["known_limitations"], list)
