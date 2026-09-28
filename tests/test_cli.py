"""The command-line interface.

The CLI exists so the refusal is visible from a shell with no Python written,
and so a CI job can gate on it. Exit codes are ordered by severity:
0 CERTIFIED, 1 SUSPECT, 2 REFUSED, 3 usage error.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from honest_backtest.cli import EXIT, USAGE_ERROR, build_parser, main
from honest_backtest.types import Verdict


def test_check_on_the_builtin_fixture_exits_refused(capsys: pytest.CaptureFixture[str]) -> None:
    """The headline behaviour: a contaminated result set is refused."""
    code = main(["check", "--example"])
    out = capsys.readouterr().out
    assert code == EXIT[Verdict.REFUSED] == 2
    assert "REFUSED" in out
    assert "LOOKAHEAD_DISTANCE_DECAY" in out
    assert "blocking finding" in out


def test_check_json_is_machine_readable(capsys: pytest.CaptureFixture[str]) -> None:
    """``--json`` emits the full report, parseable."""
    code = main(["check", "--example", "--json"])
    out = capsys.readouterr().out
    payload = json.loads(out)

    assert code == 2
    assert payload["verdict"] == "REFUSED"
    assert payload["certified"] is False
    assert "LOOKAHEAD_DISTANCE_DECAY" in payload["failure_codes"]
    assert isinstance(payload["findings"], list)
    assert payload["certification"]["verdict"] == "REFUSED"


def test_check_from_a_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A supplied result set is read and judged."""
    path = tmp_path / "result.json"
    path.write_text(
        json.dumps(
            {
                "name": "from-file",
                "window_excesses": [41.0, 41.0, 52.0, 29.0, 44.0, 33.0, 61.0, 25.0, 48.0,
                                    -1534.0, -380.0, -124.0],
                "win_count": 9,
            }
        ),
        encoding="utf-8",
    )
    code = main(["check", str(path)])
    out = capsys.readouterr().out
    assert code == 2
    assert "CONCENTRATION_MIXED_SIGNS" in out
    assert "from-file" in out


def test_a_clean_result_set_exits_certified(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The negative direction, through the CLI. Exit code 0."""
    from honest_backtest import fixtures

    path = tmp_path / "clean.json"
    path.write_text(
        json.dumps(
            {
                "name": "clean",
                "split_effects": list(fixtures.CLEAN_CONTROL["effects"]),  # type: ignore[arg-type]
                "split_distances_days": list(fixtures.CLEAN_CONTROL["distances_days"]),  # type: ignore[arg-type]
                "window_excesses": list(fixtures.CLEAN_CONTROL["window_excesses"]),  # type: ignore[arg-type]
                "win_count": 10,
                "trade_pnls": list(fixtures.CLEAN_CONTROL["trade_pnls"]),  # type: ignore[arg-type]
                "series_values": fixtures.clean_series(),
                # 12 disjoint 30-day windows, back to back -- the fix shape.
                "window_plan": [
                    "2024-01-01..2024-01-31",
                    "2024-01-31..2024-03-01",
                    "2024-03-01..2024-03-31",
                    "2024-03-31..2024-04-30",
                ],
            }
        ),
        encoding="utf-8",
    )
    code = main(["check", str(path), "--json"])
    out = capsys.readouterr().out
    payload = json.loads(out)

    assert code == EXIT[Verdict.CERTIFIED] == 0
    assert payload["verdict"] == "CERTIFIED"
    assert payload["certified"] is True
    assert payload["failure_codes"] == []


def test_universe_asymmetry_through_the_cli(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The cohort/benchmark JSON shape is accepted and refused."""
    path = tmp_path / "universe.json"
    path.write_text(
        json.dumps(
            {
                "name": "universe",
                "cohort": {"name": "cohort", "min_age_days": 30, "members": ["a", "b"]},
                "benchmark": {"name": "benchmark", "min_age_days": 30, "members": ["a"]},
            }
        ),
        encoding="utf-8",
    )
    code = main(["check", str(path), "--json"])
    payload = json.loads(capsys.readouterr().out)
    # The CLI routes both sides through one shared predicate, so this must pass
    # the symmetry check -- proving the fix is what the CLI does by default.
    assert code == 0
    assert payload["verdict"] == "CERTIFIED"
    assert "universe" in payload["ran_guards"]


def test_multiplicity_through_the_cli(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A claimed p-value from a 341-configuration family is refused."""
    path = tmp_path / "study.json"
    path.write_text(
        json.dumps(
            {
                "name": "study",
                "split_effects": [0.051, 0.038, 0.062, 0.029, 0.055, 0.041, 0.048, 0.033],
                "split_distances_days": [3.0, 8.0, 15.0, 22.0, 31.0, 43.0, 56.0, 70.0],
                "n_experiments": 341,
                "claimed_p": 0.03,
                "n_nominal_positives": 16,
            }
        ),
        encoding="utf-8",
    )
    code = main(["check", str(path), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 2
    assert "MULTIPLICITY_AT_CHANCE_RATE" in payload["failure_codes"]
    assert payload["payload"]["multiplicity"]["expected_false_positives"] == pytest.approx(17.05)


def test_missing_file_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    """A bad path exits 3 and explains itself on stderr."""
    code = main(["check", "/nonexistent/result.json"])
    err = capsys.readouterr().err
    assert code == USAGE_ERROR
    assert "error:" in err


def test_malformed_json_is_a_usage_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Broken JSON is a usage error, not a crash."""
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    code = main(["check", str(path)])
    assert code == USAGE_ERROR
    assert "error:" in capsys.readouterr().err


def test_non_object_payload_is_a_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A list is not a result set."""
    path = tmp_path / "list.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    code = main(["check", str(path)])
    assert code == USAGE_ERROR
    assert "must be a JSON object" in capsys.readouterr().err


def test_guard_subcommand_renders_a_fixture(capsys: pytest.CaptureFixture[str]) -> None:
    """Each guard has a one-command demonstration."""
    for name, expected in (
        ("lookahead", "REFUSED"),
        ("outliers", "REFUSED"),
        ("windows", "REFUSED"),
        ("universe", "REFUSED"),
        ("multiplicity", "REFUSED"),
        ("series", "REFUSED"),
        ("evidence", "REFUSED"),
        ("comparison", "REFUSED"),
    ):
        code = main([name])
        out = capsys.readouterr().out
        assert code == 2, f"{name} should exit REFUSED"
        assert expected in out
        assert name in out


def test_guard_subcommand_json(capsys: pytest.CaptureFixture[str]) -> None:
    """Guard subcommands support --json."""
    code = main(["series", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 2
    assert payload["fixture"] == "spliced_metrics"
    assert payload["detected"] is True


def test_guard_subcommand_reproduce_headline_numbers(
    capsys: pytest.CaptureFixture[str]
) -> None:
    """The CLI reproduces the real fixtures, not approximations of them."""
    main(["lookahead", "--json"])
    lookahead = json.loads(capsys.readouterr().out)
    assert lookahead["r"] == pytest.approx(-0.598, abs=5e-4)

    main(["multiplicity", "--json"])
    multiplicity = json.loads(capsys.readouterr().out)
    assert multiplicity["expected_false_positives"] == pytest.approx(17.05)

    main(["windows", "--json"])
    windows = json.loads(capsys.readouterr().out)
    assert windows["independent_count"] == 0

    main(["evidence", "--json"])
    evidence = json.loads(capsys.readouterr().out)
    assert evidence["fixture"] == "pypi_scan_503"
    assert evidence["n_unknown"] >= 5, "the 503s the scan called absent"

    main(["comparison", "--json"])
    comparison = json.loads(capsys.readouterr().out)
    assert comparison["fixture"] == "nested_four_split_asymmetry"
    assert comparison["same_clauses"] is False


def test_guard_restriction_is_recorded(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """``--guard`` restricts the run, and the report says so."""
    path = tmp_path / "r.json"
    path.write_text(
        json.dumps(
            {
                "name": "restricted",
                "split_effects": [0.051, 0.038, 0.062, 0.029, 0.055, 0.041, 0.048, 0.033],
                "split_distances_days": [3.0, 8.0, 15.0, 22.0, 31.0, 43.0, 56.0, 70.0],
                "window_excesses": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0],
            }
        ),
        encoding="utf-8",
    )
    main(["check", str(path), "--json", "--guard", "lookahead"])
    payload = json.loads(capsys.readouterr().out)

    assert payload["ran_guards"] == ["lookahead"]
    assert "concentration" in payload["skipped_guards"]


def test_min_independent_windows_override(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A stricter minimum flips a passing plan to refused.

    Four back-to-back windows contribute three replications, so a minimum of 2
    passes and a minimum of 5 refuses. The threshold moves the verdict without
    the data changing.
    """
    path = tmp_path / "plan.json"
    path.write_text(
        json.dumps(
            {
                "name": "few",
                "window_plan": [
                    "2024-01-01..2024-01-31",
                    "2024-01-31..2024-03-01",
                    "2024-03-01..2024-03-31",
                    "2024-03-31..2024-04-30",
                ],
            }
        ),
        encoding="utf-8",
    )
    code_lenient = main(["check", str(path), "--json", "--min-independent-windows", "2"])
    payload_lenient = json.loads(capsys.readouterr().out)
    assert code_lenient == 0
    assert payload_lenient["payload"]["windows"]["independent_count"] == 3

    code_strict = main(
        ["check", str(path), "--json", "--min-independent-windows", "5"]
    )
    payload = json.loads(capsys.readouterr().out)
    assert code_strict == 2
    assert "WINDOWS_INSUFFICIENT_INDEPENDENCE" in payload["failure_codes"]


def test_parser_requires_a_subcommand() -> None:
    """Bare invocation is a usage error, not a crash."""
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_quiet_suppresses_the_summary_but_keeps_the_verdict(
    capsys: pytest.CaptureFixture[str]
) -> None:
    """``--quiet`` still prints the verdict."""
    code = main(["check", "--example", "--quiet"])
    out = capsys.readouterr().out
    assert code == 2
    assert "REFUSED" in out
    assert "blocking finding" not in out
