"""Shared test fixtures.

The real measured numbers live in :mod:`honest_backtest.fixtures` so the tests,
the examples and the CLI all exercise *the same* data rather than three drifting
approximations. This module only adds pytest wiring.
"""

from __future__ import annotations

import pytest

from honest_backtest import fixtures


@pytest.fixture()
def copier_pnl() -> dict[str, object]:
    """``copier_pnl``: apparent spread +0.1344, distance-decay r = -0.5976."""
    return fixtures.copier_pnl()


@pytest.fixture()
def roi() -> dict[str, object]:
    """``roi``: apparent spread +1.0190, distance-decay r = +0.4285."""
    return fixtures.roi()


@pytest.fixture()
def nine_of_twelve() -> dict[str, object]:
    """9/12 windows won, mean -138.7, median +37.0."""
    return fixtures.nine_of_twelve()


@pytest.fixture()
def top_decile_121() -> dict[str, object]:
    """Top 10% of trades produced 121% of net PnL."""
    return fixtures.top_decile_121()


@pytest.fixture()
def top_decile_164() -> dict[str, object]:
    """Top-10% share = 1.64."""
    return fixtures.top_decile_164()


@pytest.fixture()
def nested_four_split() -> dict[str, object]:
    """4 splits sharing one end date -> 0 independent windows."""
    return fixtures.nested_four_split()


@pytest.fixture()
def disjoint_twelve() -> dict[str, object]:
    """12 disjoint 30-day windows from a 365-day panel."""
    return fixtures.disjoint_twelve()


@pytest.fixture()
def spliced_metrics() -> dict[str, object]:
    """A -24,046 pp fabricated daily return across a metric splice."""
    return fixtures.spliced_metrics()


@pytest.fixture()
def clean_control() -> dict[str, object]:
    """A genuinely clean setup that must be CERTIFIED."""
    return fixtures.clean_control()
