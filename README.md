# honest-backtest

**A backtest that cannot refuse is not evidence.**

Most backtesting libraries help you produce a result. This one helps you
*disbelieve* it.

Every guard in this package exists because it caught a specific false positive
that looked completely convincing — in the author's own research, measured, with
numbers recorded below. None of them is a hypothetical.

```python
from honest_backtest import HonestyReport, ResultSet, Config

report = HonestyReport.run(result_set, config=Config(assert_no_unguarded_construction=True))
report.require_certified()          # raises RefusedError unless CERTIFIED
```

The refusal path is the easy path. That is the whole design.

---

## Contents

- [The idea](#the-idea)
- [Install](#install)
- [Verdicts](#verdicts)
- [The guards](#the-guards)
  - [1. Look-ahead contamination](#1-look-ahead-contamination)
  - [2. Outlier domination](#2-outlier-domination)
  - [3. Window independence](#3-window-independence)
  - [4. Benchmark-eligibility asymmetry](#4-benchmark-eligibility-asymmetry)
  - [5. Multiple-testing accounting](#5-multiple-testing-accounting)
  - [6. Structural data traps](#6-structural-data-traps)
  - [7. Block bootstrap confidence intervals](#7-block-bootstrap-confidence-intervals)
- [A full worked example: a result being refused](#a-full-worked-example-a-result-being-refused)
- [Command line](#command-line)
- [What this does NOT do](#what-this-does-not-do)
- [Dependencies](#dependencies)
- [Known limitations](#known-limitations)
- [Contributing](#contributing)
- [License](#license)

---

## The idea

A backtest result arrives as a number. The number is almost always *true* — the
arithmetic was correct — and almost never *evidence*. The gap between those two
things is where nearly all self-deception lives.

Every failure documented below produced a real number. A spread of +0.1344 with
p < 0.001. Nine wins out of twelve. A confidence interval of
`[-0.021, +0.781]` that just excludes zero. Each one was computed correctly, and
each one was worthless.

**And the fixtures are not exempt from that standard.** Every fixture in this
library carries a provenance label, and the library checks it: `MEASURED` when
the per-observation rows are the research archive's own, `DERIVED` when the
statistic is measured and the series is solved from it, `ILLUSTRATIVE` when the
numbers demonstrate a mechanism rather than report a finding.
`fixtures.provenance()` audits the lot. A library about not overstating your
evidence does not get to overstate its own.

So this library does not compute results. It **refuses** them. A guard that
finds a disqualifying condition returns `REFUSED`, and a refused result is not
reportable as a finding — not with a caveat, not with a footnote, not in the
appendix.

Two design decisions follow from that, and they are the reason the library looks
the way it does:

**The verdict is a type, not a boolean.** Guards hand back `Certification`
objects. You cannot accidentally drop a verdict, because you cannot do anything
with a `Certification` except ask it to prove itself. `report.require_certified()`
is the one line a consumer needs, and it raises.

**A skipped guard is a failed guard.** If a guard is configured but cannot run
for lack of input, that is a blocking `ERROR`. "We didn't check" and "we checked
and it was fine" must never look the same downstream.

---

## Install

```bash
pip install honest-backtest
```

Python 3.10+. No runtime dependencies.

From a checkout:

```bash
git clone https://github.com/beduldul/honest-backtest
cd honest-backtest
python -m pip install -e ".[dev]"
python -m pytest -q
```

---

## Verdicts

Exactly three, and the composite takes the **strictest** of its parts:

| Verdict | Meaning | Exit code |
|---|---|---|
| `CERTIFIED` | Every applicable guard ran and passed. | 0 |
| `SUSPECT` | Something is worth reporting but does not block. Never "certified with warnings". | 1 |
| `REFUSED` | At least one guard found something disqualifying. **Not reportable as a finding.** | 2 |

A single `REFUSED` makes the report `REFUSED`. There is no averaging, no score,
no "overall confidence". A result whose numbers are contaminated is not 90%
usable.

---

## The guards

### 1. Look-ahead contamination

**The failure it caught.** Two predictors produced spreads significant at
p < 0.001:

| predictor | apparent spread | distance-decay r |
|---|---|---|
| `copier_pnl` | **+0.1344** | **−0.598** |
| `roi` | **+1.0190** | **+0.43** |

Both were pure look-ahead. Neither was caught by significance testing. Both were
caught by asking a question significance testing does not ask: *does the measured
effect depend on when I measured it?*

These two are the library's `MEASURED` fixtures: the twelve per-split spreads and
split dates are the research archive's own rows, unrounded and untuned, and the
correlation printed below is recomputed from them (which is why it reads
`-0.5976` and `+0.4285` rather than the rounded published figures). Nothing was
chosen to make those numbers come out.

A genuine predictor does not care when you measure it. A contaminated one does.
For `copier_pnl` the effect was largest nearest the data snapshot — where the
future has leaked furthest into the past — and decayed with distance. That
monotone decay is the signature.

```python
from honest_backtest.guards.lookahead import LookaheadGuard

guard = LookaheadGuard(r_threshold=0.5, min_splits=5)
report = guard.run(split_effects, split_distances_days)
report.r              # -0.5976 for the copier_pnl fixture (published: -0.598)
report.contaminated   # True
report.verdict        # Verdict.REFUSED
report.certify().require()   # raises RefusedError
```

A second, independent instrument runs alongside the correlation: `sign_consistency`
splits the distances at the median and refuses if the near-half and far-half mean
effects have opposite signs. **On the real data that instrument is the only thing
that refuses `roi`**: its r is `+0.4285`, just under the 0.5 bar, so the
correlation check does not fire. One instrument is not a guard, it is a guess with
a threshold attached — and here is the case that proves it.

Thresholds: `r_threshold` (default 0.5), `min_splits` (default 5),
`min_distinct_distances` (default 3). Fewer splits than required is a **failure**,
not a skip. The guard is binary: there is no `SUSPECT` band, because you cannot
subtract the contaminated part when you do not know its magnitude.

---

### 2. Outlier domination

**The failure it caught.** A strategy won **9 of 12** independent windows — and
was not an edge:

```
mean excess   = -138.7
median excess =  +37.0        # opposite signs
```

Nine wins out of twelve sounds like a result. The three losses were large enough
to invert the mean. The win-count and the dollar total tell opposite stories, and
the dollar total is the one that reaches your P&L.

**A second failure.** A strategy's in-sample **top 10% of trades produced 121% of
net PnL** — remove the best decile and it is a loser. A second, illustrative
15m-shaped case uses a top-10% share of **1.64** (`ILLUSTRATIVE`: the magnitude is
the narrative's, not a persisted per-observation series; what the archive does
corroborate is that the effect lives in ~4 of 17 weeks).

The denominator is **net** PnL, and that is not a detail — it is the whole reason
the number can exceed 1.0. A share of *gross* profit is bounded above by 1.0 by
definition, so "121% of gross" is not a large number, it is a contradiction. Net
PnL sums every trade including the losers, so it is smaller than the winnings and
may be negative: if the top decile earns 4570 and the rest loses 793, net is 3777
and the share is 121%. The reading that produces — *strip out the best 10% and
what remains is a loser of 793* — is the one the guard is built on.

```python
from honest_backtest.guards.outliers import ConcentrationGuard

guard = ConcentrationGuard(top_fraction=0.10, tail_threshold=1.0)

windows = guard.check_windows(window_excesses, win_count=9)
windows.mean_excess, windows.median_excess   # (-138.7, 37.0)
windows.signs_disagree                        # True
windows.verdict                               # Verdict.REFUSED

trades = guard.check_trades(trade_pnls)
trades.top_share                              # 1.21
trades.share_excluding_tail                   # -793.14   <- a loser without the tail
```

Note what does **not** rescue either result: a higher win count. Passing
`win_count=12` changes nothing. The win rate is precisely the statistic that lied.

The `tail_threshold` default is exactly `1.0`, not a round 0.5 or 0.8. It is the
sharpest available line and it is arithmetic rather than taste: a **net**-PnL
share of 1.0 means the top decile produced the entire net PnL, so the remaining
90% nets to zero or worse. Anything above 1.0 is strictly worse, and is only
expressible because the denominator can be small or negative.
A lower threshold would be a judgement call; this one is an identity.

---

### 3. Window independence

**The failure it caught.** A walk-forward design reported **4 splits**. All four
shared the same end date. The forward windows were strictly nested — each
contained the previous one's data. The number of pairwise-independent windows was
**zero**.

The report said "0 of 4 negative". That reads as four confirmations. It is one
observation, repeated four times, with a shrinking start date. The effective
sample was **one**.

The fix extracted **12 genuinely disjoint 30-day windows** from the same 365-day
panel. Note the inversion: the number went *up*, from 4 to 12, because the 4 were
never 4.

```python
from honest_backtest.guards.windows import WindowGuard, WindowPlan

broken = WindowPlan(windows=nested_splits, label="walk_forward", claimed=4)
WindowGuard(min_independent=2).run(broken).independent_count   # 0
WindowGuard(min_independent=2).run(broken).verdict             # Verdict.REFUSED

fixed = WindowPlan.tiled(date(2024,1,1), date(2024,12,31), length_days=30)
WindowGuard(min_independent=2).run(fixed).independent_count    # 11
WindowGuard(min_independent=2).run(fixed).verdict              # Verdict.CERTIFIED
```

`independent_count` counts **additional replications beyond the first**: a plan
of 12 disjoint windows reports 11, because the twelfth window is the eleventh
replication of the first. Saying "12" would be technically true of a maximum
disjoint subset and completely misleading about the evidence. `len(plan)` is the
window count; `plan.max_disjoint()` is the subset size.

Two plans are provided because they fail differently: `WindowPlan.from_spec`
parses a textual plan (including an `x4` repeat shorthand that expresses the
nested failure in one line), and `WindowPlan.tiled` builds a back-to-back tiling
where independence holds by construction.

---

### 4. Benchmark-eligibility asymmetry

**The failure it caught.** A code defect with a statistical symptom. The cohort
filter excluded stale and dormant subjects. The benchmark filter did not.

Dormant subjects have a flat 0% forward return. Including them drags the
benchmark toward zero, and a cohort of active subjects then looks skilful against
a benchmark that is half asleep. On the fixture this manufactured **+0.6% of
apparent excess return** that does not exist.

Nothing in the output looked wrong. The spread was positive, the t-stat was
respectable, and the only symptom was statistical — the worst kind, because a
statistical symptom invites tuning rather than a fix.

```python
from honest_backtest.guards.universe import Selection, UniverseGuard, require_shared_predicate

guard = UniverseGuard(require_identical_object=True)
report = guard.run(
    Selection(name="cohort",    predicate=eligible,    selected=cohort_members),
    Selection(name="benchmark", predicate=cohort_only, selected=bench_members),
)
report.same_object   # False -- two different filters
report.verdict       # Verdict.REFUSED
```

`predicate_fingerprint` hashes a predicate's source **and its closure state**. Two
closures built by the same factory have identical source text and behave
differently; hashing source alone would call them identical, reintroducing the
exact bug one level down.

The test that matters is `tests/test_universe.py::test_divergent_predicates_are_caught`.
A guard against divergence that is never tested against divergence is decoration.

---

### 5. Multiple-testing accounting

**The failure it caught.** One study evaluated **341 configurations**. At
α = 0.05 that implies

```
341 × 0.05 = 17.05
```

expected false positives, and the study's nominal positives — p-values sitting in
the 0.01–0.05 band — sat right at that rate. A second study ran **60
configurations** and reported one positive, inside a family where ~3 are
expected.

Neither study lied. Both reported a p-value that was true for the single test and
meaningless for the family. The fix is not a better p-value; it is counting how
many times you looked.

```python
from honest_backtest.guards.multiplicity import ExperimentCounter

counter = ExperimentCounter(alpha=0.05, correction="bonferroni")
for params in grid:
    counter.record(f"{params}")          # the census must be observed, not declared
    p = evaluate(params)

report = counter.report(claimed_p=best_p, n_nominal_positives=n_positive)
report.expected_false_positives   # 17.05
report.adjusted_p                 # 1.0  -- 0.03 * 341, capped
report.survives_correction        # False
report.verdict                    # Verdict.REFUSED
```

Both standard corrections are available. Bonferroni is the default: it is
assumption-free and it is the more conservative of the two, and this library's job
is to make the refusal easy, not to find the most favourable defensible
correction. `known_limitations` rides on every report, because the correction is
never stronger than its assumptions.

The counter is stateful on purpose: the honest family size is the number of
configurations that *were actually run*, which is only knowable if something
watched them run. Passing `n_experiments=341` directly is supported and the report
records that the family size was **declared rather than observed** — a distinction
that is not cosmetic, because a declared family size is exactly the number an
author is tempted to trim.

---

### 6. Structural data traps

**Three failures it caught.**

**(a) Spliced metrics.** A series table stitched two different measurements
end-to-end: a 365-day trailing-cumulative metric and a 30-day rolling-window
metric. Both were named "return". Differencing across the splice fabricated a
**−24,046 pp** "daily return". The arithmetic was correct; the input was two
different quantities wearing one column name.

**(b) Zero-padding before inception.** Series were padded with zeros back to a
common start date. A portfolio 11 days old returned 365 points. The padding is
*zero*, so it drags any measured average toward zero — a flattering direction for
a long-only book.

**(c) Left-edge timestamp bug.** A 15-minute bar labelled `t0` spans
`[t0, t0 + 15m)`. Code that assumed a forward bar starts at `t0 + 1m` produced a
**185 bps** price error. Not a rounding difference — a different bar.

```python
from datetime import datetime, timedelta
from honest_backtest.guards.series import (
    detect_splice, truncate_leading_padding, check_contiguous,
    left_edge_window, forward_bar_offset,
)

detect_splice(spliced_values, threshold=25.0).jump
# -24046.0   <- the fabricated "daily return", detected at a 57,125x local-scale ratio

truncate_leading_padding(padded, padding_value=0.0)
# ([...11 real points...], 354)   <- 354 points never existed

left_edge_window(datetime(2024,3,1,9,30), timedelta(minutes=15))
# (09:30, 09:45)   <- the bar covers a 15-minute interval, not an instant

forward_bar_offset(datetime(2024,3,1,9,30), timedelta(minutes=15),
                   assumed_offset=timedelta(minutes=1))
# (09:45, 9333.3)  <- 9,333 bps of timing error
```

The splice detector cannot know that a column holds two metrics — nothing in the
data says so. What it can do is notice a **level discontinuity inconsistent with
the local variation**. On the fixture the fabricated step is −24,046 pp against
neighbouring steps of order 0.1–2 pp: not an outlier, a different population.

Two design notes worth stating:

- The comparison is against the **local** variation, not the global. A
  legitimately volatile series should not be flagged for being volatile. A
  global-robust-z backstop (`z_threshold`) catches a jump sitting inside a
  uniformly quiet stretch, which no local comparison can see.
- A series that is *flat except for a few steps* has no usable scale at all —
  median, MAD and standard deviation are all zero or dominated by the steps. This
  is not a degenerate input to skip; it is the clearest possible splice. The
  detector reports it directly rather than returning "cannot evaluate".

---

### 7. Block bootstrap confidence intervals

**The failure it caught, in the author's own prior work.** A naive trade-level
confidence interval **promoted a false positive to a strategy**:

```
CI = [-0.021, +0.781]        on 378 trades
```

The interval excludes zero by a hair. It came from **4 symbols in a one-month
artifact**. A trade-level bootstrap over that data treats 378 trades as 378
independent draws, when they are really a handful of weekly regimes sharing one
month of one market. The effective sample is far closer to 4 than to 378, and the
interval that pretends otherwise is not conservative — it is wrong in the
direction of enthusiasm.

```python
from honest_backtest.stats.bootstrap import block_bootstrap_ci

result = block_bootstrap_ci(
    per_trade_values,
    block_dates=per_trade_dates,     # preferred: calendar weeks
    anchor="monday",                 # the standard
    min_blocks=10,
)
result.n_blocks           # 4    <- the effective sample size, not 378
result.low, result.high   # [+0.063, +0.739]  <- much wider than the naive interval
result.verdict            # Verdict.SUSPECT
result.naive_comparison
# 'interval excludes zero, but rests on 4 independent block(s) (minimum 10)
#  and must not be reported'
```

**There is no way to get the interval without the block count.** They are the same
object. That is the design.

The verdict on a low block count is `SUSPECT` rather than `REFUSED`, deliberately.
The point of the guard is to *show* you the interval that a naive method would have
reported, next to the number that makes it meaningless. A flat refusal would hide
the evidence that teaches the lesson.

Supplying neither `block_dates` nor `block_size` raises. There is no safe default
block structure, and choosing one silently is exactly the mistake this function
exists to prevent.

**Permutation null.** For shape and ordering tests — "do the winners cluster", "is
the drawdown early" — shuffling values freely destroys the block structure and
produces a null that is *too wide*, i.e. a test too easy to pass.
`permutation_null` shuffles **within** blocks, preserving each block's total and
membership while randomising the arrangement.

---

## A full worked example: a result being refused

Everything in this example **passes a significance test**. What kills it is the
guards.

```python
from datetime import date
from honest_backtest.guards.windows import WindowPlan
from honest_backtest.plans import Window
from honest_backtest.report import Config, HonestyReport, ResultSet

# Twelve real splits from the archive. Effect decays with distance -- the
# signature of a label that leaks the future. Apparent spread +0.1344,
# significant at p < 0.001. (fixtures.COPIER_PNL carries these rows and their
# provenance; this is the same data spelled out.)
result = ResultSet(
    name="the_convincing_result",
    split_effects=(0.0881, 0.1023, 0.0802, 0.0134, 0.2468, 0.0111,
                   0.0979, 0.1057, 0.1972, 0.1191, 0.2072, 0.3435),
    split_distances_days=(362.0, 332.0, 302.0, 272.0, 242.0, 212.0,
                          182.0, 152.0, 122.0, 92.0, 62.0, 32.0),

    # Twelve windows, nine of which "won".
    window_excesses=(41.0, 41.0, 52.0, 29.0, 44.0, 33.0, 61.0, 25.0, 48.0,
                     -1534.0, -380.0, -124.0),
    win_count=9,

    # The walk-forward as designed: four splits, one shared end date.
    window_plan=WindowPlan(
        windows=tuple(
            Window(start=s, end=date(2024, 7, 1), label=f"split{i+1}")
            for i, s in enumerate((date(2024,1,1), date(2024,2,1),
                                   date(2024,3,1), date(2024,4,1)))
        ),
        label="walk_forward",
        claimed=4,
    ),
)

report = HonestyReport.run(result, config=Config(assert_no_unguarded_construction=True))
print(report.explanation())
```

Raw output (pasted verbatim from running the block above -- not hand-written):

```
the_convincing_result: REFUSED
  [FAIL] LOOKAHEAD_DISTANCE_DECAY: effect is contaminated by look-ahead: decays with distance, r = -0.598 (|r| >= 0.5) across 12 splits
  [FAIL] CONCENTRATION_MIXED_SIGNS: MIXED / OUTLIER-DRIVEN: mean excess -138.7 and median excess +37.0 have opposite signs; win count 9/12 does not override this -- one or two windows dominate the total in the opposite direction
  [FAIL] WINDOWS_FULLY_NESTED: all 4 splits share the same end date (2024-07-01); the forward windows are strictly nested and the count of pairwise-independent windows is 0, below the required 2. An effective sample of 0 cannot be read as 4 confirmations
  guards not run (no inputs supplied): universe, multiplicity, series
  guards run: lookahead, concentration, windows
```

Now try to use it:

```python
report.require_certified()
```

```
RefusedError: result is REFUSED, not CERTIFIED: effect is contaminated by
look-ahead: decays with distance, r = -0.598 (|r| >= 0.5) across 12 splits;
MIXED / OUTLIER-DRIVEN: mean excess -138.7 and median excess +37.0 have
opposite signs; ... ; all 4 splits share the same end date (2024-07-01); the
forward windows are strictly nested and the count of pairwise-independent
windows is 0, below the required 2. ...
```

Note the `r = -0.598` and `across 12 splits`: that is the *unrounded*
correlation `-0.597561` recomputed from the twelve real per-split archive rows
and formatted to three decimals. The example in this section inlines the same
rows that `fixtures.COPIER_PNL` carries; if you run `examples/lookahead.py` you
will see the full-precision `-0.5976` next to the published `-0.598`.

Run it yourself:

```bash
python examples/refused_report.py
```

**And the negative direction.** The same pipeline, the same thresholds, a clean
input:

```bash
python examples/clean_control.py
```

```
clean_control: CERTIFIED
  guards run: lookahead, concentration, windows, universe, series
  look-ahead r            : -0.306
  contaminated            : False
  independent windows     : 11
  top-decile share        : 0.114
  cohort/benchmark same   : True

  verdict                 : CERTIFIED
  blocking findings       : ()
  -> CERTIFIED. require_certified() did not raise.
```

A library that rejects everything is not a validator. The guards discriminate.

---

## Command line

```bash
honest-backtest check result.json            # 0 CERTIFIED, 1 SUSPECT, 2 REFUSED, 3 usage error
honest-backtest check result.json --json     # full machine-readable report
honest-backtest check --example              # the built-in contaminated fixture
honest-backtest lookahead                    # one guard, one command
honest-backtest series --json
```

Exit codes are ordered by severity, so a CI job can gate on it:

```bash
honest-backtest check result.json || alert "this result is not reportable"
```

Note that `SUSPECT` is **not** success: it exits 1, because a result you may not
report as a finding is not a passing build.

```
$ honest-backtest check --example
copier_pnl + nine_of_twelve + nested walk-forward (measured fixtures): REFUSED
  [FAIL] LOOKAHEAD_DISTANCE_DECAY: effect is contaminated by look-ahead: decays with distance, r = -0.598 (|r| >= 0.5) across 12 splits
  [FAIL] CONCENTRATION_MIXED_SIGNS: MIXED / OUTLIER-DRIVEN: mean excess -138.7 and median excess +37.0 have opposite signs; win count 9/12 does not override this -- one or two windows dominate the total in the opposite direction
  [FAIL] CONCENTRATION_TAIL_DOMINANCE: top 10% of observations produce 121% of net PnL (threshold 1.00); excluding the tail the result is -793.1
  [FAIL] WINDOWS_FULLY_NESTED: all 4 splits share the same end date (2024-07-01); the forward windows are strictly nested and the count of pairwise-independent windows is 0, below the required 2. An effective sample of 0 cannot be read as 4 confirmations
  [FAIL] SERIES_SPLICE_DETECTED: level discontinuity at index 119 -> 120: step of -24,046.0 is 57,125x the local scale (0.421); a single step this large against the surrounding variation is the signature of two different metrics spliced end-to-end, and differencing across it produces a fabricated value
  guards not run (no inputs supplied): universe, multiplicity
  guards run: lookahead, concentration, windows, series

5 blocking finding(s); guards run: lookahead, concentration, windows, series
```

Note the six failures: all six of the measured numbers above, reproduced in one
command. `--json` emits the same report with the raw statistics attached:

---

## What this does NOT do

Read this section before you trust anything above.

- **It does not generate strategies.** There is no alpha here, no signal, no
  model. It is a set of instruments for interrogating work you already did.
- **It does not fetch data.** No network access anywhere in the library or its
  tests, by design and by test.
- **It does not tell you what to trade.** It produces verdicts, not positions.
- **It cannot detect every possible form of self-deception.** Specifically, and
  most importantly:
  - **It cannot detect a hypothesis that was never pre-registered.** If you
    looked at the data, formed a theory, and then tested it on the same data, no
    guard here can see that. The multiplicity counter counts the configurations
    *you told it about*, and it cannot see the ones you tried and never recorded.
    This is the largest hole in the library and no amount of code closes it.
  - **It cannot fix a bad dataset.** Spliced metrics, zero-padding and broken
    timestamps are detected in the *shapes* the guards know about. A dataset
    wrong in a novel way will pass. The guards are detectors, not proofs.
  - **It cannot tell you a result is real.** `CERTIFIED` means "no guard found a
    reason to refuse", which is not the same as "this is true". It is a floor,
    not a ceiling.
  - **It cannot see a bad comparison you did not describe.** The universe guard
    checks that *the two selections you gave it* share a predicate. If the right
    benchmark is missing from your result set entirely, that is invisible here.
- **It cannot rescue a result.** There is no "apply correction and continue"
  path. A refused result stays refused.

---

## Dependencies

**Zero runtime dependencies**, and that is a deliberate choice rather than a
purist one.

The guards operate on hundreds of numbers — per-split effects, per-window
excesses, per-trade PnLs. numpy's advantage appears at six or seven orders of
magnitude more data than that, and it does not exist at all for the operations
that matter here: a covariance-free Pearson correlation over 8 points, a median
absolute deviation over 200 differences, a bootstrap over blocks.

What a dependency would cost is concrete: a heavier install, an ABI surface to
maintain, and a fixed seed that behaves differently across numpy versions —
which would break the one property this library cannot compromise on, that a
`CERTIFIED`/`REFUSED` verdict is reproducible bit for bit.

`numpy` and `pandas` are never imported. `pytest` is the only development
dependency. If you have the data in a DataFrame, pass `df["col"].tolist()`.

---

## Known limitations

Beyond the section above:

1. **Thresholds are calibrated, not derived.** The defaults (r = 0.5, tail = 1.0,
   10 blocks, α = 0.05) are the values that fire on the measured fixtures and
   leave clean controls alone. They are not the output of a power analysis.
2. **The splice detector finds the largest discontinuity.** A table spliced at
   three points reports one, and the ratio for the others is not surfaced. Run it
   on segments if you suspect multiple joins.
3. **`independent_count` is a geometric count, not a statistical one.** Two
   windows that do not overlap in time can still share a market regime. The guard
   is a lower bound on the problem, not a solution to it.
4. **The multiplicity corrections assume the family size is fixed in advance.**
   If you chose how many configurations to run *after* seeing results, no
   correction restores validity. Neither Bonferroni nor Šidák is exact under
   arbitrary positive dependence.
5. **`SUSPECT` is not enforced.** `report.require_certified()` raises on `SUSPECT`
   and on `REFUSED`. But a caller who reads `report.verdict` directly can choose
   to treat `SUSPECT` as a pass. The library makes the safe path easy; it cannot
   make the unsafe path impossible, because you can always print a number.
6. **The bypass audit is a lint, not a sandbox.** It parses caller source for
   hand-forged `Certification` constructions. It will not defeat `exec`, and it is
   not trying to; it is trying to defeat a future version of you. Concretely: a
   `Certification` is a frozen dataclass, and a frozen dataclass can be
   constructed. `Certification(verdict=Verdict.CERTIFIED).require()` succeeds. It
   will not match the *provenance* of a real audit, and
   `assert_no_unguarded_construction=True` will refuse to run alongside source
   that does it — but the type system cannot stop you from writing that line.
   Nothing can make the unsafe path impossible, because you can always print a
   number.
7. **`certify()` on an individual report is not a composite verdict.** A single
   guard can only speak for itself. Only `HonestyReport` sees all of them.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). The short version: **a new guard must
arrive with the false positive it caught**, and every guard needs a test in the
negative direction too.

## License

[MIT](LICENSE).
