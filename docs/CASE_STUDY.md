# Where a Green Test Suite Lied

A case study in falsifying your own quantitative system.

---

## The one-sentence version

Tests establish that code satisfies a specified contract. They cannot establish that you
specified the right contract. This project failed, repeatedly, in the gap between those two
statements.

**The suite never lied about the contracts it tested. I had asked it the wrong questions.**

These failures survived code review, linting, type checking, and 254 unit tests because the
missing contracts concerned integration, upstream semantics, data provenance, or statistical
structure rather than component behaviour.

Different failure classes needed different evidence, and pretending otherwise would be its own
overclaim. Dimensional analysis alone settles a unit mismatch: `min(bundle_count, dollars)` is
incoherent on inspection and needs no experiment. Reading an exception hierarchy settles
whether `except APIError` catches a 404. But the failures whose contracts depended on the
outside world -- what a field means, whether a filter is honoured, whether a price is
executable, whether a row is an independent observation -- were only ever settled by probing
the real system and auditing the real data. Code inspection found some of these; for the rest
it was indispensable.

At its worst moment the repository had **254 passing tests, clean lint, clean types, and an
arbitrage engine that could not fetch a single market.** It had also produced a +20.5%
simulated return using an entry price that had never been demonstrated to be executable.

---

## What the project was supposed to be

Two systems sharing a repository:

1. **An arbitrage detection engine.** Poll Polymarket's Gamma API, find binary markets where
   `YES + NO < 0.99`, and paper-trade the spread. The premise: one outcome must win, so a
   bundle of both sides redeems for exactly $1 — making the payoff deterministic under the
   model, though "guaranteed" would assume away fills, fees, and legging risk.
2. **A calibration research pipeline.** Collect resolved markets, ask whether market prices
   predict outcomes accurately, and look for categories where the crowd is systematically
   wrong.

The roadmap ran: calibration curve → find systematic bias → model it → paper trade → real
capital. Six stages.

The project reached stage two. Stage two returned a negative result. This document is about
how that was established, because the process turned out to be more valuable than the
finding would have been.

---

## Part 1 — Four bugs the test suite could not see

The engine ran cleanly. It logged normally, served Prometheus metrics, passed its Docker
health check, and never crashed. It also fetched **zero markets on every cycle, forever.**

### The composition root discarded its own dependency

The entry point opened an HTTP client correctly, with `async with`, and handed it to the
application. Then `startup()` overwrote it:

```python
async with PolymarketClient(...) as client:
    app.api_client = client          # correctly entered
    await app.startup()              # ...which replaces it

# inside startup():
self.api_client = PolymarketClient(...)   # never entered, no session
```

Every request raised `RuntimeError("Client not initialized")`. A broad `except Exception`
caught it, logged `market_fetch_failed`, and returned an empty list. The cycle reported
`no_markets_to_analyze` and slept.

Every component was individually correct and individually tested. Nothing tested the wiring
between them. The 254-test suite never called `startup()`.

### Timezone-aware data met a timezone-naive comparison

```
end_date parsed as: datetime(2099, 1, 1, tzinfo=TzInfo(0))
is_expired RAISES TypeError: can't compare offset-naive and offset-aware datetimes
```

Gamma returns dates with a `Z` suffix, so Pydantic parses them timezone-aware. The model
compared against `datetime.now()`, which is naive. Python refuses.

This fired on *every real market*. It fired on *no test fixture*, because every fixture used
`datetime.now() + timedelta(...)` — naive by construction. The fixtures had quietly encoded
a data shape the API never produces.

### A configurable threshold that reached the filter but not the arithmetic

The strategy filtered markets using its configured threshold. Profit was computed from a
hardcoded constant. Set a looser threshold and a market would pass the filter, receive zero
profit, then fail a validator requiring positive profit — an unhandled `ValidationError`.

### An error handler that discarded the work it was protecting

This one only became visible *after* fixing the first. Gamma caps pagination at offset 2100
and returns HTTP 422. The exception propagated past the parsing block entirely:

```
raw_markets_fetched: 2100
market_fetch_failed: HTTP 422 offset too large
markets returned:    0
```

Two thousand one hundred markets fetched successfully, then thrown away by the handler meant
to make failures survivable.

**The pattern:** a green suite tells you your components behave as you wrote them. It says
nothing about whether the system does what you think. Three of these four surfaced the first
time a real cycle ran against the live API; the threshold mismatch was reproduced from a
constructed case once its shape was suspected. None was visible from the suite.

---

## Part 2 — The strategy could never have worked

With the engine finally functional, the obvious question: how many opportunities does it
find?

```
n=343 live tradeable markets
min=1.0000   median=1.0000   max=1.0000
markets with YES + NO < 0.99:  0
```

Across 343 sampled live tradeable markets, `outcomePrices` summed to **exactly 1.0000 in
every case**. What produces that is not established here — "normalized" would be a claim
about upstream construction, and the whole point of this document is not to infer mechanism
from behaviour. What *is* established is narrower and sufficient: whatever the upstream
construction, the condition `YES + NO < 0.99` was unreachable from the observed feed. Not
rare, not competed away — unreachable.

Zero opportunities is the correct answer. The engine is right and the premise was wrong.

An executable static-arbitrage claim would require something stronger than a pair of quoted
prices summing below 1: sufficient CLOB ask depth on both legs such that total acquisition
cost — including applicable fees and execution effects — sits below the bundle's terminal
redemption value, at a quantity you can actually fill. Two best asks summing to 0.995 proves
nothing if the size is one share, the next level crosses $1, fees consume the spread, or the
legs don't fill together.

The distinction between a reference price and an executable price turned out to matter twice
more before this project was done.

---

## Part 3 — A +17pp signal that dissolved under scrutiny

The research pipeline reported per-category calibration bias. Weather markets looked
dramatically overpriced: **+17.2 percentage points**, tight confidence interval, n=368.

Three hypotheses were tested and the first two were wrong.

**Hypothesis 1: look-ahead in the price extraction.** The snapshot extractor selected the
tick nearest a target timestamp — `ORDER BY ABS(timestamp - target)` — which reaches
*forward* in time whenever the later tick is closer. Audit:

```
46.1% of 24h snapshots selected a tick recorded AFTER the nominal target
```

A real defect, and unacceptable for a backtest. Rebuilding every snapshot causally
(`timestamp <= target`) moved the estimate from `-0.0490` to `-0.0495`. **It explained
nothing.**

**Hypothesis 2: cross-horizon cohort selection.** Also wrong, and wrong in an instructive
way — the same artifact existed within a single horizon.

**Hypothesis 3: the markets were not independent observations.**

```
Chicago, March 5 — four separate "markets", one thermometer:
  highest temp between 40-41°F   p=0.104  NO
  highest temp between 42-43°F   p=0.100  NO
  highest temp between 44-45°F   p=0.345  NO
  highest temp between 46-47°F   p=0.380  NO
```

These are rungs of one mutually exclusive ladder. Reconstructing all 348 ladders:

```
unfiltered:     mean sum(price)=0.983   mean sum(outcome)=0.782
band-filtered:  mean sum(price)=0.504   mean sum(outcome)=0.210
the [0.05, 0.95] filter DISCARDED THE WINNING RUNG in 227/348 ladders (65.2%)

contract-weighted, band-filtered:  +0.1718
contract-weighted, no band filter: +0.0390
```

The analysis filtered prices to `[0.05, 0.95]` to exclude near-certain markets. On a ladder,
that deletes the favourite — the rung that actually won — and keeps the losers. Averaging
`price - outcome` over a cohort composed of losers manufactures positive bias.

That accounts for 77% of the signal. The residual reconciles too:

```
(0.983 - 0.782) / 5.17 rungs = +0.0389        observed residual: +0.0390
```

Prices summed to 0.983 while observed outcomes summed to only 0.782, which shows the
reconstructed ladders were **incomplete** — roughly 22% contain no winning rung at all. The
collection process did apply a $10,000 minimum-volume rule, but because the frozen dataset
never preserved authoritative group membership, the cause of each individual missing rung
cannot be reconstructed from it. Incompleteness is established; its precise cause is not.

Either way it is an accounting hole rather than a forecasting error, and within the 348
reconstructed ladders it numerically accounts for the residual.

**Scope matters here.** What is established is that *within the reconstructed sample*, the
entire observed +17pp row-level effect is numerically accounted for by band selection plus
incomplete ladder representation. That falsifies the claim that the figure represented
genuine calibration bias. It does not establish that Weather markets are well calibrated —
the ladders were reconstructed from a templated question string rather than from authoritative
group identity, so this rejects the old estimate without producing a trustworthy new one.

---

## Part 4 — The surviving finding was not what its label said

Politics showed calibration bias of `-0.0490`, CI `[-0.0939, -0.0033]`. Statistically
significant, direction consistent, and it survived causal re-extraction unchanged.

Then the cohort was read rather than counted:

```
Politics in-band cohort, n=323, decomposed:
  "say"/phrase-bingo markets     n=223   -0.0529  [-0.1080,+0.0032]     69% of cohort
  post-count / rating ladders    n= 40   +0.0882  [-0.0374,+0.2060]     12%
  everything else                n= 60   -0.1259  [-0.2252,-0.0290] ***  19%
  ALL (the headline)             n=323   -0.0490  [-0.0941,-0.0037] ***
```

Sixty-nine percent of "political market underconfidence" is *"Will Trump say 'Sleepy Joe'
this week?"* and *"Will Keir Starmer say 'Mr. Speaker' 15+ times during PMQs?"*

These are politically themed, so the sharper problem is not that they are non-political but
that the cohort is overwhelmingly one narrow speech-event subtype rather than a broad sample
of political forecasting questions. "Political markets are underconfident" is not a claim this
cohort can support. And decomposed, no subgroup robustly carries
the headline: the 69% majority is not individually significant, the ladder subgroup points
the *opposite* direction, and the only significant slice is a 60-market residual that is
itself a post-hoc cut.

The band filter roughly doubles the effect (`-0.0238` unfiltered → `-0.0490` filtered). The
price band was chosen after a wider band failed to reach significance. Contracts share
underlying events, so 323 rows are nowhere near 323 independent observations.

**And the reported +20.5% return was never a backtest.** Its entry price is a book midpoint.
You cannot transact at the midpoint; you cross the ask. It has no demonstrated fill, no
holdout period, an unvalidated fee model, and a maximum-drawdown figure computed against
peak cumulative P&L rather than an equity curve — which is why it exceeds 100% and means
nothing.

---

## Part 5 — Then the API lied too

Correcting the analysis required knowing which markets belong to the same ladder. Polymarket
exposes this as a first-party field, so the obvious move is to query by it:

```
GET /markets?negRiskMarketID=0xd01be44ad11d16b26b...
HTTP 200
returned 25 markets
actually carrying that negRiskMarketID: 0 of 25

  new-rhianna-album-before-gta-vi-926
  will-jesus-christ-return-before-gta-vi-665
  will-bitcoin-hit-1m-before-gta-vi-872-424
```

The filter is silently ignored. Success status, well-formed payload, twenty-five entirely
unrelated markets. Had group membership been built on that call, every "event-aware"
recalculation would have been noise wearing the costume of rigor.

The same session found `interval=1m` returning **zero** history points for a five-month-old
market while an explicit `startTs`/`endTs` query returned data fine — a silent empty that
would have produced thousands of rows marked "fetched" with nothing in them.

**Upstream success is not upstream correctness.** HTTP 200 means the server answered, not
that it answered the question you asked.

---

## Part 6 — The same mistake, made by the author of this document

After cataloguing every failure above, settlement was added to the paper trader so positions
could close and realize P&L. It settled when a market passed its end date:

```python
resolves_at = market.end_date
```

A field named for a fact the data does not contain. Measured:

```
32-market sample of recently closed markets:
  every observed closedTime fell AFTER its endDate
  median +0.8 hours, maximum +11.7 hours
```

The end date is when a market becomes *eligible* for resolution. Resolution happens later,
through an oracle process with an intermediate `"proposed"` state. Settling on the end date
would have credited capital up to twelve hours before the position was redeemable —
manufacturing liquidity that inflates capacity for every subsequent trade.

Two further bugs surfaced in the fix, both found by running it rather than reading it:

- The handler caught `APIError`, but `MarketNotFoundError` descends from
  `DataValidationError`. One delisted market would have aborted settlement for every other
  open position. The exception hierarchy had been documented earlier in the same project.
- The list and single-market endpoints **contradict each other**. Same market, same moment:
  `closed=True, umaResolutionStatus="resolved"` from one, `closed=False,
  umaResolutionStatus="proposed"` from the other.

Settlement now requires an explicit typed `ResolutionStatus.RESOLVED`, with `UNRESOLVED` and
`UNKNOWN` both leaving the position open. One assumption remains: that Gamma's `"resolved"`
status implies the position is redeemable. It excludes the earlier `"proposed"` state, which is
directionally safer, but the mapping itself has been reasoned about rather than demonstrated.
It is isolated to a single method and recorded in the README as open — the typed enum is where
proof is *assumed*, not where it is established.

**This is the most useful part of the project.** Knowing the failure mode in detail did not
prevent committing it. What caught it was an outside reviewer asking what a field name was
based on, and the answer being a measurement rather than an argument.

---

## The invalidated assumptions

Each was established by measurement, not inspection.

| Assumption | How it was tested | Verdict |
|---|---|---|
| Gamma prices can reveal executable arbitrage | 343 live markets characterized | **Rejected** — YES+NO summed to exactly 1.0000 in every sampled case, making the condition unreachable from that feed |
| Crypto markets are systematically overconfident | Bootstrap CI, volume weighting, monthly splits, quintiles | **Rejected** — +0.0104, CI [-0.0267, +0.0475] |
| The nearest historical tick is causally valid | Signed timestamp audit | **Rejected** — 46.1% select a post-target tick |
| Look-ahead explains the politics result | Causal re-extraction of every snapshot | **Rejected** — moved -0.0490 → -0.0495 |
| Weather's +17pp is real calibration error | 348 ladders reconstructed from question text | **Rejected as a calibration claim** — within the reconstructed sample, band selection plus incomplete ladder representation numerically account for the effect. Does not establish Weather is well calibrated |
| "Politics" is a broad political-forecasting cohort | Cohort composition audit | **Rejected** — 69% is one narrow speech-event subtype |
| `[0.05, 0.95]` is neutral data cleaning | Filtered vs unfiltered | **Rejected** — it is a selection operator on predictions |
| One database row is one observation | Group identity probe | **Rejected** — rows are rungs of shared structures |
| `negRiskMarketID` filters server-side | Live API probe | **Rejected** — HTTP 200, 0 of 25 records match |
| `interval=1m` retrieves old history | Re-fetch at 5 months | **Rejected** — returns zero; explicit bounds work |
| `end_date` is when a market resolves | 32-market close-lag measurement | **Rejected** — 100% of observed closes came later |
| `except APIError` catches a 404 | Exception MRO check | **Rejected** — `MarketNotFoundError` is a `DataValidationError` |
| The historical price is an executable fill | Compared against midpoint, book sides, last trade | **Unsupported** — tight-spread probes were consistent with midpoint behaviour, but the reference price was never demonstrated transactable, and wide spreads were untested |
| ROADMAP's 1h result (n=2,523) | Re-ran the same query | **Retracted** — yields 18; provenance insufficient to reconstruct |

Note the second-order entries. Several of these reject not the original hypothesis but the
*explanation offered for why the hypothesis failed*. Being wrong twice about the same number,
in different directions, is what eventually produced the mechanism.

---

## What the engineering fixes actually were

The bugs were symptoms. The table below separates **what actually changed** from **the durable
design lesson**, because conflating those two is the same error this document is about — a
principle stated as though it were shipped.

| Defect | What changed now | Durable design lesson |
|---|---|---|
| Composition root discarded the client | Client injected and owned by the caller; `startup()` fails fast without one | A component must not construct a dependency whose lifecycle a caller already owns |
| Resilience built but never invoked | Limiter, retry and breaker applied inside the client | Protection belongs at the boundary, not at each call site that must remember it |
| Breaker counted a routine 422 | Only dependency faults count toward the breaker | Retryability and breaker-worthiness are separate axes |
| Read path mutated schema on connect | Enforced read-only accessor (`mode=ro` + `query_only`); migration only at an explicit entry point | Reading evidence must not confer authority to alter it |
| Metadata refresh erased derived columns | **Containment only** — v1 frozen and all writer paths revoked. Stage-owned tables were *not* built | A corrected lineage needs storage owned per pipeline stage, so an upstream refresh cannot reach downstream state |
| Realized P&L permanently zero | Settlement wired into the cycle, gated on typed resolution status | A capability with no caller is not a feature |
| `capital_deployed` conflated with gains | Sum of open cost bases; ledger reconciles exactly in `Decimal` | Derive quantities from their definition, not from a subtraction that happens to agree |
| Financial units ambiguous | `position_size` → `bundle_quantity` in the ledger, with a dimensional test. **The producer still mixes units** — see below | Units belong in the type or the name, because coincidentally similar magnitudes hide the error |
| Findings not attributable to a dataset | Dataset frozen, content-hashed, write-protected through four layers | Preserve the corpus that produced a claim before correcting the claim |

The suite grew from 254 to 326 tests. That number is not the point. Every added test exists
because a specific contract was discovered to be missing — the ordering was *find the
failure, then encode the contract*, never *add tests until confident*.

**One of those fixes is incomplete, and finding that while writing this document is itself
on-theme.** The ledger now has explicit units, but the calculation that *produces* the
quantity still does not:

```python
liquidity_limit = market.liquidity * MAX_POSITION_PCT_OF_LIQUIDITY   # dollars
position_size   = min(max_position_size, liquidity_limit)            # bundles vs dollars
```

A bundle count is capped by a dollar amount. The two agree numerically while a bundle costs
about $1, which is why it never surfaced as a wrong answer. Fixing it properly means sizing
in capital and dividing by bundle unit cost — a redesign of the sizing rule, not a rename.
It is recorded rather than rushed, because "the numbers currently agree" is exactly the
reasoning this project spent its entire length learning to distrust.

---

## What I would do differently

**Verify semantics before building on them.** Almost every defect traces to a field or
endpoint whose meaning was assumed from its name. `end_date`, `outcomePrices`,
`umaResolutionStatus`, `negRiskMarketID`, `interval=1m` — each was plausible and each was
narrower than assumed. The cheap habit that prevents this is one probe per load-bearing
field, before code depends on it.

**Make one fixture match production exactly.** The timezone bug survived 254 tests because
every fixture was hand-built. One fixture carrying a real API payload would have caught it
immediately.

**Define the statistical unit before computing statistics.** The Weather artifact was not a
calculation error; the arithmetic was correct throughout. The dataset counted database rows
and the analysis assumed independent forecasting problems, and nothing in the code recorded
that those differ.

**Treat preprocessing as part of the estimand.** `[0.05, 0.95]` was introduced as data
cleaning and behaved as a selection operator that doubled one effect and manufactured another
outright.

**Separate hardening from new behaviour.** Wiring pre-existing resilience components was
bounded cleanup and went smoothly. Adding settlement introduced a new lifecycle state
machine and immediately required deciding what resolution means, which truth source is
authoritative, and when capital is claimable. Same session, same enthusiasm, completely
different risk profile.

---

## Where the project actually stands

**No positive research claim from v1 currently meets the evidentiary standard applied in this
review.** Weather's estimate is invalidated as an artifact of the analysis. Politics fails
construct validity: it is measured on a cohort that is 69% one narrow speech-event
subtype rather than a broad sample of political forecasting questions. The crypto null
result stands at the aggregate level but has not been revalidated under event-aware
methodology — and a null can be manufactured by canceling subgroup biases just as easily as a
positive can.

**The engine works and finds nothing.** Correct behaviour on a feed whose prices sum to 1.

**The dataset is frozen.** Content-hashed, read-only, with a canonical copy outside the
repository and a document recording every assumption it invalidated. The original claims were
not rewritten into better-looking ones; they were preserved and annotated, and future work
requires a new data lineage.

**One assumption remains open**, documented in the README rather than hidden behind a type.

The deliverable was supposed to be an edge. What it produced instead is a system in which
every claim is tagged as measured, assumed, unsupported, or rejected — and a fairly complete
map of the ways a correct-looking program can be confidently wrong.

That is a worse trading result and a better engineering one.

---

## Appendix — provenance of the figures

Not all numbers above carry equal weight, and a document arguing about provenance should
not claim uniform provenance it does not have. `scripts/reconcile_case_study.py`
classifies every principal quantitative claim into one of four categories. It verifies the
dataset's SHA-256 against the freeze manifest before computing anything, so "recomputed
from frozen evidence" is literally true rather than true-because-the-bytes-happen-to-match.

Current output: **28 reproduced, 0 mismatched, 3 not rerun, 6 historical, 1
unreconcilable.**

**REPRODUCED (28)** — recomputed from the frozen dataset during a final audit, agreeing to
quoted precision. Every cohort size (9,922 markets / 2,091,101 price rows / 368 / 323 / 497
/ 18); the politics decomposition in full (n=223/40/60 with biases −0.0529 / +0.0882 /
−0.1259, the headline −0.0490, and −0.0238 with the band filter removed); the entire Weather
ladder analysis (348 ladders, mean size 5.17, price sum 0.983, outcome sum 0.782, 227
winner-dropping ladders = 65.2%, +0.1718 filtered, +0.0390 unfiltered, residual 0.0389); the
crypto null (+0.0104 and its bootstrap interval); and the 46.1% look-ahead rate, recomputed
over the full population of 9,922 rather than a sample.

One caveat inside this class: bootstrap confidence intervals reproduce to roughly ±0.0008
rather than exactly, because resampling depends on the order of RNG draws and this script's
call sequence differs from the original analysis script's. Point estimates and counts
reproduce exactly.

**NOT_RERUN (3)** — derivable from the frozen dataset, but not recomputed by this audit: the
+20.5% return calculation (reproducible via `research/analysis/backtest_politics.py`), the
causal re-extraction estimate −0.0495, and the politics subgroup confidence intervals.
"This script did not compute it" is not the same as "it cannot be computed," and conflating
those two was an earlier version of this appendix's own error.

**HISTORICAL (6)** — depended on an external service's state at a moment in time and cannot
be regenerated: the 343-market `YES + NO = 1.0000` characterisation, the 32-market close-lag
sample (median +0.8h, max +11.7h), the `negRiskMarketID` filter returning 0 of 25 matching
records, `interval=1m` returning zero points at five months, the list-versus-single endpoint
contradiction on market 3037521, and the CLOB midpoint comparison. A reader re-running these
today may see different values as the feed moves.

Their durability is genuinely weaker than the frozen corpus, and worth admitting plainly.
Most are recorded in commit messages (`170902c`, `637b819`, `a2ae4b9`) alongside the code
change each one motivated, which is a durable record but not a hashed artifact. Raw payloads
were not archived. A stricter version of this project would have captured them.

**UNRECONCILABLE (1)** — the ROADMAP's 1h cohort of n=2,523. The current dataset yields 18,
and the original derivation cannot be reconstructed. This is the one figure whose provenance
is insufficient to explain the discrepancy, which is precisely why it is retracted rather
than corrected.
