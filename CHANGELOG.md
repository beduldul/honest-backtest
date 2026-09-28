# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-09-28

Initial release. Every guard in this version exists because it caught a real
false positive in the author's own research, and every fixture reproduces the
figure it claims to reproduce rather than a plausible approximation of it --
and states which kind of figure that is:

- `MEASURED` -- the per-observation rows are the research archive's own rows.
- `DERIVED` -- the statistic is measured; the rows are solved from it.
- `ILLUSTRATIVE` -- both are constructed to demonstrate a mechanism. These are
  not findings and must not be quoted as such.

Six of the fourteen fixtures are `ILLUSTRATIVE`. The previous wording of this
paragraph ("every fixture reproduces the measured number") overstated exactly
that, in a library built to catch overstatement.

### Added

**Guards**

- `guards/lookahead.py` -- distance-decay contamination diagnostic. Reproduces
  `copier_pnl` (apparent spread +0.1344, r = -0.5976) and `roi` (apparent spread
  +1.0190, r = +0.4285) from the twelve real per-split archive rows, unrounded
  and untuned. Includes an independent near/far sign-consistency check, which on
  the real data is the *only* check that refuses `roi` -- its r sits just below
  the 0.5 threshold.
- `guards/outliers.py` -- mean-vs-median sign disagreement and top-decile
  concentration. Reproduces 9-of-12 wins with mean -138.7 against median +37.0,
  and top-decile net-PnL shares of 1.21 and 1.64 (both implying a losing tail).
  The share's denominator is **net PnL**, not gross: a share of gross profit
  cannot exceed 1.0, so a net denominator is the only one under which these
  numbers are expressible at all. The module docstring now spells this out.
- `guards/windows.py` -- independent-window counting. Reproduces the nested
  4-split design (4 splits, one shared end date, **0** independent windows) and
  the fix (12 disjoint 30-day windows from the same 365-day panel).
- `guards/universe.py` -- cohort/benchmark shared-predicate validation, with a
  divergence test that fails if the two filters ever differ. Fingerprints
  include closure state, so two closures from the same factory are
  distinguishable.
- `guards/multiplicity.py` -- experiment counter, expected false positives, and
  Bonferroni/Sidak correction. Reproduces the 341-configuration study (17.05
  expected false positives) and the 60-configuration study (1 positive, ~3
  expected).
- `guards/series.py` -- structural trap detection. Reproduces the metric splice
  that fabricated a -24,046 pp "daily return", the 354-point zero-padded
  inception of an 11-day-old portfolio, and the left-edge bar error (9,333 bps
  of timing error, 185 bps of price error).

**Provenance**

- `fixtures.provenance()` -- audits every fixture's own provenance label. Each
  fixture declares `MEASURED` (the per-observation rows are the research
  archive's), `DERIVED` (the statistic is measured, the series is solved from
  it), or `ILLUSTRATIVE` (the numbers demonstrate a mechanism, they are not a
  finding). The audit recomputes each `MEASURED` fixture's claimed statistic
  from its own rows and reports any that fails to reproduce it -- the library
  applying its own standard to itself.

**Statistics**

- `stats/bootstrap.py` -- block bootstrap CI as the default method, with
  Monday-anchored calendar-week blocks, reported block counts, and a
  `min_blocks` gate. Also a permutation null that shuffles within blocks,
  preserving block totals.

**Aggregation**

- `report.py` -- `HonestyReport` aggregates every guard into one of
  `CERTIFIED`, `SUSPECT` or `REFUSED`, takes the strictest verdict, and refuses
  to certify when a guard could not run.
- `audit.py` -- static detection of hand-forged `Certification` constructions,
  so a verdict cannot be manufactured by hand and still call itself audited.
- `cli.py` -- `honest-backtest` console script with exit codes 0/1/2/3 ordered
  by severity, so `honest-backtest check ... || alert` does the obvious thing.
- `fixtures.py` -- every measured fixture, in the library rather than only in
  the test suite, so examples, tests and the CLI reproduce the same failures.

**Design**

- Verdicts are `Certification` objects, not booleans. There is no code path that
  returns a result while dropping the verdict.
- Every guard returns an immutable report with a `certify()` method; refusing is
  the easy path and bypassing is explicit.

[0.1.0]: https://github.com/beduldul/honest-backtest/releases/tag/v0.1.0
