"""The examples must actually run.

An example that has rotted is worse than no example: it teaches something false.
These tests execute every script in ``examples/`` as a subprocess, offline, and
assert both the exit status and that the headline measured numbers appear in the
output. They are the reason the README's numbers can be trusted.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"

SCRIPTS = sorted(p.name for p in EXAMPLES_DIR.glob("*.py"))


def run_example(name: str) -> subprocess.CompletedProcess[str]:
    """Run one example script and capture its output."""
    return subprocess.run(
        [sys.executable, str(EXAMPLES_DIR / name)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_examples_exist() -> None:
    """There is one runnable example per guard, plus the two capstones."""
    assert len(SCRIPTS) >= 9
    for expected in (
        "lookahead.py",
        "outliers.py",
        "windows.py",
        "universe.py",
        "multiplicity.py",
        "series.py",
        "bootstrap.py",
        "refused_report.py",
        "clean_control.py",
    ):
        assert expected in SCRIPTS, f"missing example: {expected}"


@pytest.mark.parametrize("name", SCRIPTS)
def test_example_runs_clean(name: str) -> None:
    """Every example exits 0 and prints something."""
    result = run_example(name)
    assert result.returncode == 0, f"{name} failed:\n{result.stderr}"
    assert result.stdout.strip(), f"{name} produced no output"
    assert "Traceback" not in result.stderr


def test_lookahead_example_reproduces_the_measured_correlations() -> None:
    """The example must show the real fixtures' r values, not approximations.

    These are the unrounded values the guard recomputes from the real per-split
    rows: -0.5976 and +0.4285. The published figures are the rounded -0.598 and
    +0.43, and the example prints both so the rounding is visible rather than
    papered over.
    """
    out = run_example("lookahead.py").stdout
    assert "-0.5976" in out, "copier_pnl r must be the recomputed -0.5976"
    assert "+0.4285" in out, "roi r must be the recomputed +0.4285"
    assert "-0.598" in out, "and the published rounded figure must be shown"
    assert "+0.430" in out
    assert "+0.1344" in out
    assert "+1.0190" in out
    assert "provenance: MEASURED" in out
    assert "REFUSED" in out


def test_readme_pasted_output_matches_reality() -> None:
    """The README's pasted output must be what the code actually prints.

    This is the drift this library exists to catch, applied to its own README.
    The README quotes guard output verbatim; if the fixtures change and the
    quotes do not, the README becomes a second, silently-wrong source of
    truth. Two things are pinned here: no stale 8-split wording survives
    anywhere, and the worked example really does produce the lines it claims.
    """
    from pathlib import Path

    repo = Path(__file__).resolve().parent.parent
    readme = (repo / "README.md").read_text(encoding="utf-8")

    assert "across 8 splits" not in readme, (
        "README still quotes the old 8-split calibrated output"
    )
    assert "across 12 splits" in readme, (
        "README must quote the real 12-split output"
    )

    # The old calibrated per-split values must not survive anywhere.
    for stale in ("0.2557", "0.3533", "-0.3811", "-0.1841", "+0.0266"):
        assert stale not in readme, f"README still quotes the old value {stale}"

    # And the printed lines the README attributes to the code must be real.
    proc = subprocess.run(
        [sys.executable, str(repo / "examples" / "refused_report.py")],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=repo,
    )
    out = proc.stdout
    assert "across 12 splits" in out, "the example must report 12 splits"
    assert "r = -0.598" in out
    assert "REFUSED" in out
    # The README's pasted finding lines must be a subset of the real output.
    for line in (
        "the_convincing_result: REFUSED",
        "guards run: lookahead, concentration, windows",
    ):
        assert line in out, f"README quotes a line the code does not print: {line!r}"


def test_outliers_example_states_the_net_denominator() -> None:
    """The example must not print a share above 1.0 without saying 'net'."""
    out = run_example("outliers.py").stdout
    assert "NET PnL" in out
    assert "net, not gross" in out
    assert "121% of gross" not in out, "a gross share above 1.0 is self-contradictory"
    assert "121% of net PnL" in out


def test_outliers_example_reproduces_the_measured_extremes() -> None:
    """-138.7 / +37.0, and top-decile shares of 1.21 and 1.64."""
    out = run_example("outliers.py").stdout
    assert "-138.7" in out
    assert "+37.0" in out
    assert "1.2100" in out
    assert "1.6400" in out
    assert "loses without top 10%  : True" in out


def test_windows_example_reproduces_zero_and_eleven() -> None:
    """The nested plan reports 0; the fixed plan reports 11 additional."""
    out = run_example("windows.py").stdout
    assert "independent windows    : 0" in out
    assert "independent windows    : 11" in out
    assert "2024-07-01" in out
    assert "The broken number was never 4." in out


def test_series_example_reproduces_the_fabricated_value() -> None:
    """-24,046 pp across the splice, and the 354-point padding."""
    out = run_example("series.py").stdout
    assert "-24,046.0 pp" in out
    assert "354" in out
    assert "11 days" in out
    assert "185 bps" in out


def test_multiplicity_example_reproduces_seventeen_point_zero_five() -> None:
    """341 configurations imply 17.05 expected false positives."""
    out = run_example("multiplicity.py").stdout
    assert "17.05" in out
    assert "3.00" in out
    assert "REFUSED" in out


def test_refused_report_example_shows_a_refusal_with_all_guards() -> None:
    """The capstone: four rules fire at once and the result is refused."""
    out = run_example("refused_report.py").stdout
    assert "LOOKAHEAD_DISTANCE_DECAY" in out
    assert "CONCENTRATION_MIXED_SIGNS" in out
    assert "WINDOWS_FULLY_NESTED" in out
    assert "REFUSED. This result cannot be reported as a finding." in out


def test_clean_control_example_proves_discrimination() -> None:
    """The other capstone: a clean input is CERTIFIED, not rejected."""
    out = run_example("clean_control.py").stdout
    assert "CERTIFIED" in out
    assert "require_certified() did not raise" in out
    assert "not a machine that rejects everything" in out
