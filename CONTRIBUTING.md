# Contributing to honest-backtest

Thanks for considering a contribution. This library has one job -- helping
researchers disbelieve their own results -- so contributions are held to a
correspondingly blunt standard.

## The rule that matters most

**A new guard must arrive with the false positive it caught.**

This is not a style preference. Every guard shipped so far exists because it
caught something specific that looked convincing:

| Guard | What it caught |
|---|---|
| look-ahead | a predictor with spread +0.134 and p < 0.001 that was pure leakage |
| outliers | a strategy that won 9 of 12 windows and still was not an edge |
| windows | a "4-split" walk-forward that was one window measured four times |
| universe | a cohort filter whose benchmark side forgot the dormancy clause |
| multiplicity | 341 configurations reporting positives at the chance rate |
| series | a spliced table that fabricated a -24,046 pp daily return |

A guard proposed without a measured failure behind it is a hypothesis about how
research goes wrong. Those are welcome as *issues*, not as code.

## Practical requirements

1. **No new runtime dependencies.** The library is stdlib-only by design. If you
   believe a dependency is unavoidable, open an issue explaining what a
   stdlib-only version would cost.
2. **Type hints on every public function**, parameter and return. No bare `Any`.
3. **Refusal, not warning.** A guard that finds a disqualifying condition must
   refuse. `Status.WARN` exists but it yields `SUSPECT`, never `CERTIFIED`.
4. **An unevaluable guard is a failed guard.** If a guard cannot run for lack of
   input, that is a blocking `ERROR`, not silence.
5. **Tests use real numbers.** If your guard is derived from a study, the test
   asserts the study's actual figure. `pytest.approx` with a tolerance you can
   justify, not a tolerance that makes the test pass.
6. **A negative test.** Show a clean input that is `CERTIFIED`. A guard that
   only ever refuses is not discriminating.
7. **Deterministic and offline.** Seed everything. No network, in the library or
   in the tests, ever.

## Running the suite

```bash
python -m pip install -e ".[dev]"
python -m pytest -q
```

The suite is offline, deterministic, and should complete in well under a second.

## Adding a guard

1. Create `honest_backtest/guards/yourguard.py`.
2. Define a frozen report dataclass with a `verdict` property and a `certify()`
   method returning `Certification(...)`.
3. Define a guard class with a `name` attribute matching the module and a
   validated `__init__` (thresholds checked at construction, not at run time).
4. Register the guard in `guards/__init__.py`.
5. Add the fixture to `fixtures.py` **and** wire it into `HonestyReport.run`.
6. Add a `README.md` section that opens with the measured failure.
7. Add `examples/<guard>.py` demonstrating the failure and the refusal.
8. Add `tests/test_<guard>.py` with both directions.

## Code style

- Small files. If a module passes 400 lines, split it.
- Immutable by default: return new objects, never mutate arguments.
- Handle errors explicitly. Never swallow one silently.
- Comments explain *why*. The *what* is in the code.

## Reporting a bug

Include the guard name, the input, the verdict you got, and the verdict you
expected. If a guard refuses something it should certify, that is a
false-positive bug and it is the most serious kind this project has -- open it
first.
