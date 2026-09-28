"""The library's provenance check: is a fixture actually what it claims to be?

This module exists because of the defect it guards against. The fixtures once
labelled eight synthetic, back-solved per-split values as though they were
measurements -- in a library whose entire purpose is catching work that
overstates its evidence. The fix was to use the real 12 archive rows and to
label every remaining fixture honestly.

A label is only worth having if something checks it, so this file asserts:

* every fixture carries a provenance label, and the registry agrees with it;
* a fixture labelled ``MEASURED`` really does reproduce the statistic it
  claims, recomputed from its own rows;
* a fixture whose rows are constructed is *not* silently labelled measured.

That is the guard the brief asked for, and it is deliberately narrow: it checks
what can be checked offline and does not pretend to verify the archive itself.
"""

from __future__ import annotations

import pytest

from honest_backtest import fixtures
from honest_backtest._numeric import pearson_r

VALID_LABELS = {"MEASURED", "MEASURED_DESIGN", "DERIVED", "ILLUSTRATIVE"}


def test_every_fixture_has_a_provenance_label() -> None:
    """No fixture may be silent about where its numbers came from."""
    for name, spec in fixtures._FIXTURE_DATA.items():
        label = spec.get("provenance")
        assert label is not None, f"{name} declares no provenance"
        assert label in VALID_LABELS, f"{name} has an unknown label {label!r}"


def test_registry_agrees_with_each_fixture() -> None:
    """The central registry and the data dicts must not drift apart."""
    assert set(fixtures.PROVENANCE) == set(fixtures._FIXTURE_DATA)
    for name, label in fixtures.PROVENANCE.items():
        assert fixtures._FIXTURE_DATA[name]["provenance"] == label, (
            f"{name}: registry says {label}, the data dict says "
            f"{fixtures._FIXTURE_DATA[name]['provenance']!r}"
        )


def test_every_fixture_states_its_source() -> None:
    """A provenance label without a source is a label you cannot audit."""
    for name, spec in fixtures._FIXTURE_DATA.items():
        source = spec.get("source")
        assert isinstance(source, str) and source.strip(), f"{name} names no source"


def test_provenance_audit_is_clean() -> None:
    """The library's own self-check passes on its own fixtures."""
    report = fixtures.provenance()
    assert report["labels_consistent"] is True
    assert report["mismatched"] == []
    assert report["measured_fixtures_that_fail_to_reproduce"] == []
    assert report["all_consistent"] is True
    assert report["n_fixtures"] == len(fixtures.PROVENANCE)


def test_measured_lookahead_fixtures_reproduce_their_claimed_r() -> None:
    """The sharp end: a MEASURED fixture must recompute its own statistic.

    ``copier_pnl`` and ``roi`` carry the archive's real 12 per-split rows. If
    the declared ``measured_r`` and the correlation actually present in those
    rows ever diverge, this is where it shows up -- which is the whole point of
    labelling them measured rather than asserting it in prose.
    """
    for name in ("copier_pnl", "roi"):
        spec = fixtures._FIXTURE_DATA[name]
        claimed = spec["measured_r"]
        observed = pearson_r(spec["effects"], spec["distances_days"])  # type: ignore[arg-type]
        assert observed == pytest.approx(claimed, abs=5e-4), (
            f"{name} is labelled MEASURED but its rows give r = {observed}, "
            f"not the claimed {claimed}"
        )


def test_measured_fixtures_have_twelve_real_splits() -> None:
    """The real archive holds 12 splits; the old calibrated fixtures held 8."""
    for name in ("copier_pnl", "roi"):
        spec = fixtures._FIXTURE_DATA[name]
        assert len(spec["effects"]) == 12  # type: ignore[arg-type]
        assert len(spec["distances_days"]) == 12  # type: ignore[arg-type]
        assert len(spec["splits"]) == 12  # type: ignore[arg-type]


def test_real_split_rows_keep_the_roster_size() -> None:
    """``n`` is real data in the archive; dropping it would be a loss.

    Every split row carries the roster size at that split (1385 -> 6616), and
    the fixture keeps it. It is the reason the real rows are recognisably real:
    the roster grows monotonically as leaders accumulate history, which no
    calibrated construction would have produced.
    """
    for name in ("copier_pnl", "roi"):
        splits = fixtures._FIXTURE_DATA[name]["splits"]  # type: ignore[assignment]
        ns = [row[1] for row in splits]
        assert len(ns) == 12
        assert all(isinstance(n, int) and n > 0 for n in ns)
        assert ns == sorted(ns), "the roster only grows across these splits"
        assert ns[0] == 1385 and ns[-1] == 6616


def test_real_distances_have_no_ties() -> None:
    """The guard needs distinct distances; the real rows supply twelve.

    ``min_distinct_distances`` defaults to 3 and ``min_splits`` to 5. The real
    archive rows are spaced 30 days apart, so all twelve distances are distinct
    and neither condition is anywhere near binding. Had the rows produced ties,
    that would be a finding worth reporting -- the guard does not silently
    deduplicate to manufacture a shape it likes.
    """
    for name in ("copier_pnl", "roi"):
        distances = fixtures._FIXTURE_DATA[name]["distances_days"]  # type: ignore[assignment]
        assert len(distances) == 12
        assert len(set(distances)) == 12, f"{name}: distances contain ties"
        # Listed nearest-first, so gaps are -30 (the split spacing).
        assert {b - a for a, b in zip(distances, distances[1:])} == {-30.0}


def test_real_split_rows_are_internally_consistent() -> None:
    """``spread == top - bottom`` for every archive row, as measured.

    The tolerance is 1e-12, not a loose one: these are the archive's own
    doubles, and ``spread`` is *defined* as ``top - bottom`` in the research
    code. A transcription that reproduces the shape but not the digits is
    exactly the failure this file exists to catch -- an earlier draft of this
    fixture rounded ``top`` and ``bottom`` to ~13 significant figures while
    keeping ``spread`` exact, which passed every behavioural test and was still
    a misrepresentation of the data.
    """
    for name in ("copier_pnl", "roi"):
        spec = fixtures._FIXTURE_DATA[name]
        splits = spec["splits"]  # type: ignore[assignment]
        effects = spec["effects"]  # type: ignore[assignment]
        for row, effect in zip(splits, effects):
            day, n, top, bottom, spread, week = row
            assert spread == pytest.approx(top - bottom, abs=1e-12), (
                f"{name} split {day}: spread != top - bottom at full precision"
            )
            assert effect == spread, f"{name} split {day}: effects must be spread"
            assert n > 0 and day > 0 and week > 0


def test_row_fields_are_full_precision_doubles() -> None:
    """No field may be a pre-rounded stand-in for the archive's value.

    Round-tripping each value through ``repr`` must be lossless, and the values
    must carry enough significant digits to be the archive's doubles rather
    than a 3- or 6-decimal summary. This is deliberately a *weak* structural
    check -- the strong check is
    ``test_real_split_rows_are_internally_consistent`` plus the exact-value
    assertion in ``test_effects_are_the_archive_spreads``.
    """
    for name in ("copier_pnl", "roi"):
        splits = fixtures._FIXTURE_DATA[name]["splits"]  # type: ignore[assignment]
        for row in splits:
            day, n, top, bottom, spread, week = row
            assert float(repr(top)) == top, "top lost precision through repr"
            assert float(repr(bottom)) == bottom, "bottom lost precision"
            assert float(repr(spread)) == spread, "spread lost precision"
            assert len(repr(spread).split(".")[-1]) > 6, (
                f"{name} spread {spread!r} looks rounded, not measured"
            )


def test_effects_are_the_archive_spreads() -> None:
    """The guard's ``effects`` input is the archive's ``spread`` column, verbatim.

    Pinned as literals so any drift is caught even without the archive present.
    Values cross-checked against ``q4_results.json`` at 17 significant figures.
    """
    copier_spreads = (
        0.08807605552991253, 0.10228836629279825, 0.08023421366941282,
        0.013430699387585864, 0.2468134300010884, 0.01106835831004521,
        0.09793898781732518, 0.10566199919031219, 0.19717834722597247,
        0.11908573244631054, 0.2071598835938276, 0.3434635162294306,
    )
    roi_spreads = (
        1.9427675860942235, 1.7785568543127188, 0.647690247791643,
        0.7233099025995379, 1.1316048162881078, 0.7262256630594959,
        0.8138735588367676, 0.471516763112221, 1.006411160225154,
        0.864281426398017, 0.9862649018901796, 1.135334113432594,
    )
    assert tuple(fixtures.COPIER_PNL["effects"]) == copier_spreads  # type: ignore[arg-type]
    assert tuple(fixtures.ROI["effects"]) == roi_spreads  # type: ignore[arg-type]


def test_distances_match_the_snapshot_date() -> None:
    """Distances are ``snapshot - split_date`` with the archive's snapshot."""
    from datetime import timedelta

    epoch_shift = 0  # split_day values are days since 1970-01-01
    for name in ("copier_pnl", "roi"):
        spec = fixtures._FIXTURE_DATA[name]
        snapshot = spec["snapshot_date"]
        splits = spec["splits"]  # type: ignore[assignment]
        distances = spec["distances_days"]  # type: ignore[assignment]
        for (day, *_), distance in zip(splits, distances):
            from datetime import date

            split_date = date(1970, 1, 1) + timedelta(days=day - epoch_shift)
            assert (snapshot - split_date).days == pytest.approx(distance), (  # type: ignore[operator]
                f"{name} split {day}: distance does not match the snapshot"
            )


def test_only_row_carrying_fixtures_claim_measured() -> None:
    """``MEASURED`` is reserved for fixtures that actually carry archive rows.

    This is the guard against the specific overstatement an independent review
    found in the first draft: ``nested_four_split`` and ``disjoint_twelve`` were
    labelled ``MEASURED`` when the archive supplied only their *design* (window
    geometry, split spacing) and their per-observation values were invented.
    ``MEASURED_DESIGN`` exists so a real design cannot be silently upgraded to
    real data.
    """
    row_carrying = {
        "copier_pnl", "roi", "zero_padded_inception", "left_edge_bar",
    }
    for name, label in fixtures.PROVENANCE.items():
        if label == "MEASURED":
            assert name in row_carrying, (
                f"{name} is labelled MEASURED but is not a row-carrying fixture"
            )
        if name in row_carrying:
            assert label == "MEASURED", f"{name} carries archive rows but is {label}"


def test_measured_design_fixtures_say_so_in_their_own_prose() -> None:
    """A design-level label must be matched by design-level prose.

    The review's complaint was a *conflict*: the label said MEASURED while the
    fixture's own comment said "the effects are illustrative". Both now agree;
    this pins it.
    """
    for name in ("nested_four_split", "disjoint_twelve"):
        assert fixtures.PROVENANCE[name] == "MEASURED_DESIGN"
        source = str(fixtures._FIXTURE_DATA[name]["source"])
        assert "illustrative" in source or "design" in source


def test_multiplicity_341_is_derived_not_measured() -> None:
    """The statistic is the study's; the configuration rows are constructed.

    341 x 0.05 = 17.05 is real arithmetic, but the builder records
    ``config-0..config-340`` synthetically, and the nearest artifact
    (``h1_xs.json``, counts.total = 234) does not match the 341 figure. Calling
    that MEASURED asserted rows were observed when they were generated.
    """
    assert fixtures.PROVENANCE["multiplicity_341"] == "DERIVED"
    source = str(fixtures._FIXTURE_DATA["multiplicity_341"]["source"])
    assert "not reconciled" in source, "the 234-vs-341 discrepancy must be recorded"


def test_derived_fixture_is_not_labelled_measured() -> None:
    """The solved tail fixture must not claim to be observed data.

    ``top_decile_121`` reproduces a real measured share, but its 100 per-trade
    values are solved from that share -- the archive kept the summary, not the
    rows. Labelling it MEASURED would be exactly the overstatement this library
    exists to catch.
    """
    assert fixtures.PROVENANCE["top_decile_121"] == "DERIVED"
    spec = fixtures._FIXTURE_DATA["top_decile_121"]
    assert spec["provenance"] != "MEASURED"
    assert "h3_tail.json" in str(spec["source"])


def test_measured_count_is_reported_and_nonzero() -> None:
    """The audit summarises rather than only listing."""
    report = fixtures.provenance()
    assert report["n_measured"] >= 2, "at least the two look-ahead fixtures"
    total = (
        report["n_measured"]
        + report["n_measured_design"]
        + report["n_derived"]
        + report["n_illustrative"]
    )
    assert total == report["n_fixtures"]


def test_provenance_is_exposed_on_the_builders() -> None:
    """A caller sees the label without reaching into the data dict."""
    for payload in (fixtures.copier_pnl(), fixtures.roi()):
        assert payload["provenance"] == "MEASURED"
        assert payload["provenance_ok"] is True
        assert isinstance(payload["source"], str)
