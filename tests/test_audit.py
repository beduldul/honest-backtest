"""Static guard-bypass detection.

The library's central promise is that a user cannot *accidentally* skip a
guard. Types carry most of that weight; :func:`audit_result` closes the
remaining hole -- manufacturing a verdict by hand.
"""

from __future__ import annotations

import textwrap

import pytest

from honest_backtest.audit import Bypass, scan_source
from honest_backtest.types import GuardBypassError


def test_forged_certified_verdict_is_found() -> None:
    """The exact pattern the audit exists to catch."""
    source = textwrap.dedent(
        """
        from honest_backtest.types import Certification, Verdict

        def fast_path(result):
            return Certification(verdict=Verdict.CERTIFIED)
        """
    )
    found = scan_source(source, filename="forged.py")
    assert len(found) == 1
    assert found[0].reason == "hand-forged CERTIFIED verdict"
    assert found[0].lineno > 0
    assert "Certification(" in found[0].expression


def test_unguarded_construction_without_certified_is_also_found() -> None:
    """Constructing a verdict at all outside the audit is the offence."""
    source = textwrap.dedent(
        """
        from honest_backtest.types import Certification, Verdict

        cert = Certification(verdict=Verdict.SUSPECT, reasons=("meh",))
        """
    )
    found = scan_source(source, filename="shady.py")
    assert len(found) == 1
    assert found[0].reason == "Certification constructed outside audit_result()"


def test_qualified_construction_is_found() -> None:
    """``types.Certification(...)`` is still a construction."""
    source = "import honest_backtest.types as t\nx = t.Certification(verdict='X')\n"
    found = scan_source(source, filename="qualified.py")
    assert len(found) == 1


def test_clean_source_reports_nothing() -> None:
    """The negative direction: ordinary code is not flagged."""
    source = textwrap.dedent(
        """
        from honest_backtest import HonestyReport, ResultSet

        def validate(result):
            report = HonestyReport.run(ResultSet(name="x"))
            report.require_certified()
            return report
        """
    )
    assert scan_source(source, filename="clean.py") == ()


def test_reading_a_certification_is_not_construction() -> None:
    """Passing a Certification around must not be flagged."""
    source = textwrap.dedent(
        """
        def use(cert):
            if cert.certified:
                return cert
            return cert.require()
        """
    )
    assert scan_source(source, filename="uses.py") == ()


def test_multiple_bypasses_are_all_reported() -> None:
    """One forged verdict does not hide another."""
    source = textwrap.dedent(
        """
        a = Certification(verdict="CERTIFIED")
        b = Certification(verdict="SUSPECT")
        c = Certification(verdict="REFUSED")
        """
    )
    found = scan_source(source, filename="many.py")
    assert len(found) == 3
    assert [b.lineno for b in found] == sorted(b.lineno for b in found)


def test_bypass_render_names_the_location_and_reason() -> None:
    """A developer must be able to find the line from the error alone."""
    bypass = Bypass(
        filename="/tmp/x.py",
        lineno=42,
        expression="Certification(verdict=Verdict.CERTIFIED)",
        reason="hand-forged CERTIFIED verdict",
    )
    rendered = bypass.render()
    assert "/tmp/x.py:42" in rendered
    assert "hand-forged" in rendered
    assert "Certification(" in rendered


def test_scan_reports_line_numbers_accurately() -> None:
    """The reported line must be the offending line."""
    source = "x = 1\ny = 2\nz = Certification(verdict='CERTIFIED')\n"
    found = scan_source(source, filename="lines.py")
    assert found[0].lineno == 3


def test_syntax_error_raises_a_bypass_error() -> None:
    """Unparseable source is an error, not a silent pass."""
    with pytest.raises(GuardBypassError, match="cannot parse"):
        scan_source("def broken(:\n", filename="bad.py")


def test_assert_no_bypass_passes_for_this_test_module() -> None:
    """This module itself must be clean -- no Certification literals here."""
    from honest_backtest.audit import assert_no_bypass

    # The test file constructs no Certification, so the audit must pass.
    assert_no_bypass()


def test_audit_can_be_enabled_through_config() -> None:
    """The report wires the flag through, and it defaults to off."""
    from honest_backtest.report import Config

    assert Config().assert_no_unguarded_construction is False
    assert Config(assert_no_unguarded_construction=True).assert_no_unguarded_construction is True


def test_audit_enabled_does_not_flag_a_clean_caller() -> None:
    """With the audit on, ordinary use still works."""
    from honest_backtest import fixtures
    from honest_backtest.report import Config, HonestyReport, ResultSet

    report = HonestyReport.run(
        ResultSet(
            name="copier_pnl",
            split_effects=tuple(float(x) for x in fixtures.COPIER_PNL["effects"]),  # type: ignore[union-attr]
            split_distances_days=tuple(
                float(x) for x in fixtures.COPIER_PNL["distances_days"]  # type: ignore[union-attr]
            ),
        ),
        config=Config(assert_no_unguarded_construction=True),
    )
    assert report.refused is True
