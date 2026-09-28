# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Two guards added, both from failures that actually happened and are documented
in the research archive. Both ship with a fixture that reproduces the broken
case, a fixture that reproduces the corrected one, and tests in both directions.

### Added

**Guards**

- `guards/evidence.py` — provenance of *negative evidence*. A package-availability
  scan recorded every non-200 as `{"exists": false, "code": 503}`; HTTP 503 is
  not 404, and five names (`pbo`, `cscv`, `overfit`, `probabilistic-sharpe`,
  `backtest-overfit`) were written down as absent on a rate-limit response. The
  claim that followed was reproduced by accident rather than verified: re-run
  the same day with a three-state classifier, `overfit` was **present** on PyPI.
  A second instance of the same failure, from a different instrument: a code
  search returned zero and the zero became "nobody does this", while control
  queries proved the tool was broken (`numba` returned 1). The decider number
  moved from a false **4** to **10–18**.

  The classification is a named table (`DEFAULT_CODE_CLASSES`) rather than an
  if-chain, so the boundary between "it is not there" and "I could not reach it"
  is readable in one place. `ABSENT` requires an explicit not-found signal
  (`404`, `410`, `ENOENT`); **429/503/timeout/connection-error are `UNKNOWN`**,
  and any code the table does not name also defaults to `UNKNOWN` — the default
  direction of the mistake is deliberately the harmless one. Nothing is
  HTTP-specific: `code_classes=` reclassifies for GraphQL (200 with a null
  body), a JSON `{"found": false}` field, a filesystem, or anything else, and
  `unknown_codes=` forces codes to `UNKNOWN` for a source that lies.

  A second instrument refuses a **null result with no positive control**: if the
  instrument returned nothing anywhere and no known-positive input demonstrates
  it can return something, the null is not evidence. The report always carries
  the **conclusive fraction** — the share of observations the instrument
  actually resolved — because a set that is 90% `UNKNOWN` says almost nothing
  however clean the rest of it looks.

- `guards/comparison.py` — **declared selection predicates**. A walk-forward run
  compared a cohort that excluded stale/dormant subjects against a benchmark
  that did not, and reported **"POSITIVE 4/4 splits"**; dormant subjects have a
  flat 0% forward return that drags the benchmark toward zero and makes any
  active cohort look skilful. The violating code carried a comment stating the
  principle it broke: *"its flat stretch would be counted as a genuine 0%
  return."* The retraction table shows the benchmark mean positive in **all
  four** splits while the cohort mean runs between −330 and −1136.

  This is harder than `guards/universe.py` and is shaped to be honest about it.
  That guard fingerprints a predicate *callable*; this one receives populations
  assembled hours apart, or by another script, where there is no callable to
  fingerprint. A selection rule cannot be recovered from the selected values —
  two populations of the same size with the same mean can be built by any two
  filters — so the guard **requires the caller to declare its predicates** and
  refuses when the declarations differ. It detects different clauses, one side
  filtered and the other not (a distinct failure from a *different* filter),
  identical clauses under different names, and different clause *order* where
  the caller declares order observable. `report.py` additionally accepts a
  `comparison_predicate=` so each declaration is checked against a third,
  independent statement of the rule the run claims to have used.

  A secondary numeric instrument warns when one population carries a large mass
  of exactly-zero forward returns and the other does not. It is a **heuristic,
  not proof** — it cannot distinguish a dormant benchmark from a genuinely quiet
  cohort — so it emits `WARN` at `INFO` severity and **can never move the
  verdict**.

**Fixtures**

- `PYPI_THREE_STATE_CORRECTED` — `MEASURED`. The corrected scan's own
  twenty-five rows, transcribed from `/tmp/pypi_fixed.json`: 15 `PRESENT`,
  8 genuine `404`s, and 2 recorded honestly as `UNKNOWN` (the run saw a 404 on
  one endpoint and refused to resolve them when the other never answered).
  Preserving those two is the point — tidying them into `ABSENT` would make the
  corrected scan look more decisive than it was.
- `PYPI_SCAN_503` — `MEASURED`. The broken scan, transcribed from
  `/tmp/pypi_scan.json`. All five 503s are kept, and the artifact's *successful*
  rows are recorded as `present-no-code-recorded` rather than `"200"`: the scan
  wrote a `code` only on the error path, and inventing one would be a small tidy
  fabrication inside a fixture whose entire subject is a small tidy fabrication.
- `CODE_SEARCH_NULL_WITHOUT_CONTROL` — `ILLUSTRATIVE`, and labelled so on
  purpose. The control-query counts (`"def sharpe_ratio"` → 0, `numba` → 1) are
  described in the study narrative but **no captured output of them survives on
  disk**, so they are illustrative and the fixture says so rather than borrowing
  the credibility of the neighbouring `MEASURED` fixtures. The 4 → 10–18
  correction *is* transcribed.
- `NESTED_FOUR_SPLIT_ASYMMETRY` — `MEASURED_DESIGN`. The copytrade study's
  nested four-split design and its four transcribed split aggregates
  (`copytrade/README.md` §6.2), with `excess == mean_fwd − bench` holding on
  every row. The per-subject rows are not in the archive, so the population
  members are representative counts — the same distinction `MEASURED_DESIGN`
  already makes for `nested_four_split`.
- `DORMANT_ZERO_FORWARD_RETURNS` — `ILLUSTRATIVE`. The `0.0` forward returns
  that feed the zero-mass *heuristic*. The rule ("a dormant leader's forward
  return is a flat 0.0") is real and cited; the per-subject values are not
  persisted, and a heuristic fed by invented rows is doubly weak, so it is
  labelled rather than dressed up.

**Aggregation**

- `report.py` runs both new guards, and both participate in the
  `CERTIFIED`/`SUSPECT`/`REFUSED` verdict. New `Config` knobs:
  `evidence_min_conclusive_fraction` (default 0.5) and
  `comparison_zero_mass_gap` (default 0.20, non-blocking).
- `fixtures.clean_control()` now exercises evidence and comparison as well, so
  the clean control still prints `CERTIFIED` with both guards running.
- `cli.py` gains `evidence` and `comparison` subcommands alongside the existing
  per-guard commands.
- `examples/evidence.py` and `examples/comparison.py` show both directions for
  each new guard. `examples/refused_report.py` now fires six rules at once
  instead of four.

### Fixed

An independent review of the two new guards found six high-severity defects and
four medium ones. All ten are fixed, each with a regression test. They are
listed because the pattern they share *is* this library's subject: every one of
them reported an absence of evidence as a positive finding of soundness, in code
whose entire purpose is to prevent exactly that.

- **The null guard was off by default.** `EVIDENCE_NULL_WITHOUT_POSITIVE_CONTROL`
  was blocking only when the caller asserted a `negative_claim` and merely warned
  otherwise — so the *default* configuration certified a scan in which nothing
  had resolved, which is the recorded Sourcegraph failure produced by the
  defaults. It is now blocking unconditionally.
- **A control that failed was silently discarded.** A control probe on a
  known-positive input returning a non-success code was ignored, and the run
  behaved as though no control had been supplied. That is the `numba` → 1 case,
  the clearest evidence of a broken instrument in the whole episode. New
  `EVIDENCE_CONTROL_FAILED` finding, blocking.
- **`known_positive_code` was dead.** It appeared in the signature and the
  docstring and was never read, so a caller pinning it believed a constraint
  existed that did not. Now enforced via `EvidenceGuard.is_known_positive`.
- **`run()` crashed on empty observations with non-empty controls.**
  `ZeroDivisionError` from a guard whose job is to be dependable on malformed
  input; `EvidenceReport.conclusive_fraction` handled the case but the call site
  did not. Also: controls alone no longer certify — a control shows the
  instrument works, not that any subject was examined.
- **`payload["comparison"]["verdict"]` could read `CERTIFIED` inside a `REFUSED`
  report.** The payload was built from the guard's own report, which never sees
  the shared-predicate findings the aggregator adds. Machine-readable
  overstatement in the worst available place; the payload is now built from the
  combined findings.
- **A caller-supplied `EvidenceGuard` silently dropped `ResultSet.negative_claim`.**
  The `or` short-circuited, relaxing a refusal to `SUSPECT` through a wiring
  choice. The `ResultSet`-level claim is now applied to whichever guard resolves.
- **`PredicateAuditReport.verdict`'s docstring claimed the heuristic could not
  move the verdict.** `Severity.INFO` does not prevent that — `report.py` maps any
  `Status.WARN` to `SUSPECT`, reading `status` rather than `severity`. The
  behaviour is intended; the docstring was false and now states the real
  mechanism.
- **Clause order was asserted against a side that denied it was knowable.**
  `cp.ordered or bp.ordered` meant one side declaring order licensed a finding
  against the other — the exact inference the module refuses everywhere else.
  Now `and`.
- **Two empty declarations compared as "identical"** with the under-specification
  check relaxed, exporting `predicate_identical: True` from no information. Now
  warns that there is nothing to disagree about.
- **An absence claim with no observation behind it was not checked.** A subject
  declared absent with nothing supporting it, or with a `PRESENT` observation
  contradicting it, raised nothing — the one direction the guard did not check,
  and the module's own premise. New `EVIDENCE_ABSENCE_WITHOUT_SUPPORT` finding.
  A dead `elif` branch that read as an implemented check was also removed.

### Changed

- `fixtures.provenance()` now audits nineteen fixtures, up from fourteen. Six
  are `MEASURED`, three `MEASURED_DESIGN`, two `DERIVED` and eight
  `ILLUSTRATIVE`.
- The README's provenance paragraph is now a table of the four labels plus a
  per-fixture listing, and the "What this does NOT do" and "Known limitations"
  sections state the two new guards' blind spots explicitly — in particular that
  the comparison guard reads declarations rather than data, and that the
  evidence guard cannot catch a source that names its own outage `404`.

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
