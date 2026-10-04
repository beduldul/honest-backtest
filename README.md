[![CI](https://github.com/beduldul/honest-backtest/actions/workflows/ci.yml/badge.svg)](https://github.com/beduldul/honest-backtest/actions/workflows/ci.yml)
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
  - [8. Evidence presence](#8-evidence-presence)
  - [9. Shared selection predicates](#9-shared-selection-predicates)
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
library carries a provenance label, and the library checks it:

| label | means |
|---|---|
| `MEASURED` | the per-observation rows are the research archive's own, transcribed |
| `MEASURED_DESIGN` | the *design* is the archive's; the per-observation values are not |
| `DERIVED` | the statistic is measured, and the series is solved from it |
| `ILLUSTRATIVE` | the numbers demonstrate a mechanism; they are not a finding |

`fixtures.provenance()` audits the lot, recomputing each `MEASURED` fixture's
claimed statistic from its own rows and failing any that no longer reproduces
it. A library about not overstating your evidence does not get to overstate its
own.

The nineteen fixtures, by label:

| fixture | label | quantity |
|---|---|---|
| `copier_pnl` | `MEASURED` | spread +0.1344, r = −0.598 |
| `roi` | `MEASURED` | spread +1.0190, r = +0.43 |
| `zero_padded_inception` | `MEASURED` | 11-day-old portfolio with 365 points |
| `left_edge_bar` | `MEASURED` | 15m bar at t0 read as starting t0+1m |
| `pypi_scan_503` | `MEASURED` | five 503s recorded as `exists: false` |
| `pypi_three_state_corrected` | `MEASURED` | 15 present / 8 absent / 2 unknown |
| `nested_four_split` | `MEASURED_DESIGN` | 4 splits, one shared end date, 0 independent |
| `disjoint_twelve` | `MEASURED_DESIGN` | 12 disjoint 30-day windows from a 365-day panel |
| `nested_four_split_asymmetry` | `MEASURED_DESIGN` | retracted "POSITIVE 4/4 splits" |
| `top_decile_121` | `DERIVED` | top 10% of trades = 121% of net PnL |
| `multiplicity_341` | `DERIVED` | 341 configurations, 17.05 expected false positives |
| `nine_of_twelve` | `ILLUSTRATIVE` | mean −138.7, median +37.0, 9/12 wins |
| `top_decile_164` | `ILLUSTRATIVE` | top-10% share = 1.64 |
| `spliced_metrics` | `ILLUSTRATIVE` | 365D cumulative spliced to 30D rolling |
| `trade_level_false_positive` | `ILLUSTRATIVE` | CI [−0.021, +0.781] on 378 trades, 4 symbols |
| `multiplicity_60` | `ILLUSTRATIVE` | 60 configurations, 1 positive, ~3 expected |
| `code_search_null_without_control` | `ILLUSTRATIVE` | control queries not persisted; 4 → 10–18 |
| `dormant_zero_forward_returns` | `ILLUSTRATIVE` | the zero-mass heuristic's inputs |
| `clean_control` | `ILLUSTRATIVE` | a genuinely clean control |

Note the two the 2026-09-28 episode added on opposite sides of the line. The
**broken** scan and the **corrected** scan are both `MEASURED`: they are real
artifacts of the same probe run twice, and the broken one is worth keeping
*because* it is wrong. The code-search control queries, by contrast, are
`ILLUSTRATIVE` — the narrative records them but no captured output survives on
disk, so they are labelled rather than borrowing the credibility of the two
neighbouring measured fixtures.

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

### 8. Evidence presence

**Two failures it caught, both from the same day.**

**(a) An error read as an absence.** A package-availability scan wrote every
non-200 response down in one shape:

```json
{"exists": false, "code": 503}
```

HTTP **503 (Service Unavailable / rate-limited)** is not **404 (Not Found)**.
Five names in that scan — `pbo`, `cscv`, `overfit`, `probabilistic-sharpe`,
`backtest-overfit` — came back 503 and were recorded as absent, and the claim
that followed ("the non-200 names are absent") was therefore *reproduced by
accident* rather than verified. Re-run the same day with a three-state
classifier, **`overfit` was PRESENT on PyPI**, and the corrected run reported no
503s at all — because it classified a non-404 as `UNKNOWN` and backed off
instead of concluding. One package that was reported missing had been there the
whole time.

**(b) A zero read as "nobody does this".** A code-search tool returned **zero
results** for a query, and the zero became "there is no prior art". Control
queries proved the tool was broken: `lang:python "def sharpe_ratio"` returned 0
— and so did `numba`, which returned 1. A term present in thousands of
repositories returned one match. The decider number moved from a false **4** to
**10–18** once the zeros were discarded.

```python
from honest_backtest.guards.evidence import EvidenceGuard, Observation

guard = EvidenceGuard(negative_claim="non-200 means the package is absent")
report = guard.run(
    [Observation("pbo", "503"), Observation("cscv", "503"), Observation("overfit", "503")],
    claimed_absent=["pbo", "cscv", "overfit"],
)
report.verdict        # Verdict.REFUSED
report.n_absent       # 0    <- not one of those three resolved the question
report.n_unknown      # 3    <- 503 is 'I could not reach it'
```

Three classes, and the boundary between them is the entire subject of the guard:

| class | means | requires |
|---|---|---|
| `PRESENT` | the object was returned | any successful status |
| `ABSENT` | the question was *resolved* and the answer is no | an explicit not-found signal (`404`, `410`, `ENOENT`) |
| `UNKNOWN` | the instrument did not resolve the question | **everything else, including every code nobody named** |

The classification is a table (`DEFAULT_CODE_CLASSES`), not an if-chain, so the
boundary is readable in one place. **429 / 503 / timeout / connection-reset are
`UNKNOWN`, never `ABSENT`**, and an unnamed code defaults to `UNKNOWN` — the
default direction of the mistake is deliberately the harmless one, because
calling a present object unknown costs you a lead while calling an unreachable
object absent costs you a false conclusion.

**Nothing here is HTTP-specific.** The HTTP codes are examples from the recorded
failure, not an assumption about the source. `code_classes=` reclassifies for
GraphQL (HTTP 200 with `data: null`), a JSON body field (`{"found": false}`), a
filesystem (`ENOENT` vs `EACCES`), or anything else; `unknown_codes=` forces
codes to `UNKNOWN` for a source that lies about them.

A second instrument runs alongside: **a null result with no positive control**.
If the instrument returned nothing anywhere in the set, and no known-positive
input demonstrates it can return something, the null is not evidence. That is
failure (b) exactly, and it is **blocking by default** — not only when a
`negative_claim` is asserted. An earlier draft failed only on an asserted claim
and merely warned otherwise, which meant the *default* configuration certified a
scan in which nothing had been resolved. That is the recorded failure produced
by the defaults, and it was fixed.

The control cuts both ways, and both directions are findings. A control that
returns the configured success code (`known_positive_code`, default `200`)
demonstrates the instrument works. A control on a **known-positive input
returning anything else** demonstrates the instrument is *broken* — stronger
evidence than having no control at all. That is the `numba` → 1 case, and it is
reported as a failed control rather than quietly discarded.

The report always prints the **conclusive fraction** (share of observations the
instrument actually resolved). A set that is 90% `UNKNOWN` says almost nothing
however clean the rest of it looks, and this is the reader's only warning.

An **absence is a claim that requires support**, and the guard checks that
direction too: a subject declared absent with no observation behind it, or with
a `PRESENT` observation contradicting it, is refused. Checking only the
`UNKNOWN` direction would have left the module's own premise unenforced.

---

### 9. Shared selection predicates

**The failure it caught.** A walk-forward evaluation compared a cohort against a
benchmark. The cohort excluded stale and dormant subjects. The benchmark did not.
Dormant subjects have a flat **0%** forward return — fake data, not a flat
performance — which drags the benchmark toward zero and makes any active cohort
look skilful. It produced a reported **"POSITIVE 4/4 splits"**, retracted once
the two sides were routed through one shared predicate. On the real retraction
table the benchmark mean is positive in **all four** splits while the cohort mean
runs between −330 and −1136.

The violating code carried a comment stating the very principle it broke: *"its
flat stretch would be counted as a genuine 0% return."*

```python
from honest_backtest.guards.comparison import ComparisonGuard, Population, Predicate

report = ComparisonGuard().run(
    Population("cohort",    Predicate("eligible_as_of",
        ("history_days >= 30", "not stale", "not frozen as of split_ts")), 3151),
    Population("benchmark", Predicate("benchmark_filter", ("history_days >= 30",)), 3151),
)
report.same_clauses            # False
report.asymmetric_filtering    # False -- a *different* rule, not a missing one
report.verdict                 # Verdict.REFUSED
```

**This guard is honest about what it cannot do**, and that is why it is shaped
this way. It cannot recover a selection rule from the selected values: two
populations of the same size with the same mean can have been produced by any
two filters, and a purely numerical check would be a guess dressed as an
inference. So it **requires the caller to declare its predicates** and refuses
when the declarations differ. A declaration is diffable, reviewable, and
pinnable in a test. **A guard that cannot be fooled is worth more than one that
guesses.**

It detects four kinds of divergence:

- **different clauses** — the recorded failure;
- **one side filtered, the other not** — a distinct case, since an empty
  predicate is not a *different* rule, it is the *absence* of one;
- **identical clauses under different names** — identical today is not the same
  as one shared rule, and the next edit to one will not touch the other;
- **different clause order**, *where the caller declares order observable*. For
  a streaming filter chain it is; for a set intersection it is not, and claiming
  a divergence from unobservable order would be inventing evidence.

`report.py` goes one step further: pass `comparison_predicate=` and each side's
declaration is compared against that third, independent statement of the rule
the run claims to have used. "We both did X" cannot then be asserted about a run
whose stated rule was Y.

**The secondary instrument, and its status.** One symptom *is* visible
numerically: when one population carries a large mass of exactly-zero forward
returns and the other does not, that is consistent with dormant subjects being
left in. It is a **heuristic, not proof** — it cannot distinguish "the benchmark
is half asleep" from "this cohort genuinely had a quiet period", because it has
the numbers and the rule that made them is not in the numbers. It therefore
**can never refuse** a comparison: only a declaration can do that.

It is not invisible either, and the distinction is worth stating precisely. The
finding is `WARN` at `INFO` severity, so `PredicateAuditReport.verdict` — which
reads `Severity` — is untouched by it. But the aggregate `HonestyReport` maps any
`WARN` to `SUSPECT`, reading `Status` rather than `Severity`. A zero-mass symptom
alone leaves the guard's own report `CERTIFIED` while downgrading the composite
to `SUSPECT`. An earlier draft's docstring claimed the heuristic "cannot move the
verdict" at all, which was false about the composite; it can downgrade, it just
cannot refuse.

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
honest-backtest evidence                     # the 503-recorded-as-404 scan
honest-backtest comparison                   # the cohort/benchmark asymmetry
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
  guards not run (no inputs supplied): universe, multiplicity, evidence, comparison
  guards run: lookahead, concentration, windows, series

5 blocking finding(s); guards run: lookahead, concentration, windows, series
```

Note the five failures: all five of the measured numbers above, reproduced in
one command. (`refused_report.py` extends the same payload with the evidence and
comparison guards, and prints six.) `--json` emits the same report with the raw
statistics attached:

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
    The comparison guard extends this to populations you cannot fingerprint, but
    it only checks the declarations it is handed: it cannot tell whether a
    declared predicate is the one that actually ran.
  - **It cannot tell you why an instrument failed.** The evidence guard knows
    that a 503 is not a 404. It does not know whether a `404` from your specific
    API means "not there" or "the routing layer is misconfigured", and it will
    read a labeled `404` as absence.
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
8. **The evidence guard is only as good as the codes it is given.** It
   classifies strings against a table, so a source that reports an outage as
   `404` will still be read as `ABSENT` — the guard cannot see the HTTP
   transport, only the code the caller hands it. `unknown_codes=` exists for
   exactly this and must be used when you know a source lies. The guard's
   protection is that an *unnamed* code defaults to `UNKNOWN`; it is not
   protection against a source that names its failure `404` on purpose.
9. **The comparison guard reads declarations, not data.** It cannot recover a
   selection rule from the values that rule produced, and it does not try. Two
   sides that declare matching predicates pass even if the populations they
   carry were in fact assembled some other way — the declaration is the evidence,
   and a false declaration is outside what any of this can catch. What it *can*
   do is make the declaration explicit, diffable, and costly to change silently.
   The numeric zero-mass symptom is explicitly a heuristic and cannot refuse
   anything.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). The short version: **a new guard must
arrive with the false positive it caught**, and every guard needs a test in the
negative direction too.

## License

[MIT](LICENSE).
