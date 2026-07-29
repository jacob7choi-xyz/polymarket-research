# Research dataset v1 -- FROZEN

**STATUS: FROZEN / EXPLORATORY / SUPERSEDED**

This dataset produced the original exploratory calibration findings recorded in
`research/ROADMAP.md`. It is preserved as immutable evidence of what generated those
claims. Its integrity anchor is `manifest.json` in this directory.

**Do not use this dataset for new confirmatory claims.** Do not modify it. Do not
migrate its schema. Any change produces a hash mismatch against the manifest, which is
the point.

- Database: 9,922 markets, 2,091,101 price-history rows, 115,777,536 bytes
- Resolution window: `closed_at` spans 2026-02-09 to 2026-03-06 (about four weeks)
- Creation window: `created_at` spans 2025-01-05 to 2026-03-05
- Canonical byte-for-byte copy stored outside the repository; path recorded in the manifest

The manifest's `analysis_output_sha256` covers an explicitly enumerated list of
artifacts (`ROADMAP.md` and the three calibration plots). It is not an exhaustive crawl
of every file the analysis ever produced.

## Retired entry points

These commands previously wrote to this dataset and now raise `FrozenDatasetError` by
design. They are retired against v1, not broken:

| Command | What it used to do |
|---|---|
| `python -m research.pipeline.fetch_markets` | Wrote market metadata; its `INSERT OR REPLACE` omitted the derived price columns, so a refresh erased CLOB enrichment |
| `python -m research.pipeline.fetch_prices` | Wrote price history and set `price_history_fetched` |
| `python -m research.analysis.infer_categories` | Wrote inferred `category` values |
| `python -m research.analysis.extract_preresolution_prices` | Wrote the `price_*_before` snapshot columns |

Read-only analysis (`calibration`, `validate_crypto_signal`, `backtest_politics`) still
runs against this dataset unchanged. Collecting again means creating a new dataset
version, not reviving these writers.

## Protection layers

| Layer | Control |
|---|---|
| Application | `get_connection()` raises `FrozenDatasetError` for protected paths, resolved so symlinks and relative spellings cannot bypass it. No override parameter exists |
| Connection | `open_readonly()` uses `mode=ro` plus `PRAGMA query_only`, runs no migrations, and refuses a missing file rather than creating an empty one |
| Filesystem | Working copy and canonical package are `chmod -w` |
| Detectability | Content hashes in `manifest.json`; any modification produces a mismatch |

Protection covers both the in-repo working copy and the off-repo canonical copy, the
latter derived from `canonical_copy_path` in the manifest rather than a hardcoded path.
Dataset versions following this archive/manifest convention are discovered at process
initialisation; the protected set is computed at import time and does not refresh within
a running process. A manifest that is present but uninterpretable causes storage
initialisation to fail rather than protecting one fewer path.

These controls make modification *detectable and inconvenient*, not cryptographically
impossible. The owner can change permissions; the guarantee is that any change produces
a hash mismatch against a manifest tracked in git.

## Why it is frozen rather than repaired

Several defects in this dataset are structural rather than incidental: they are baked
into how the data was collected, so they cannot be fixed in place. A corrected dataset
requires recollection under a new contract, not migration of this one.

## Known defects and invalidated assumptions

Each row was established by direct measurement against this database or the live API,
not by inspection alone.

| Assumption | How it was tested | Verdict |
|---|---|---|
| Gamma `outcomePrices` can reveal executable static arbitrage | Live characterisation of 343 tradeable markets | **Rejected** -- YES+NO summed to exactly 1.0000 in every case; the condition is unreachable from this feed |
| Crypto markets are systematically overconfident | Bootstrap CI, volume weighting, monthly split, price quintiles, cross-category | **Rejected** -- error +0.0104, 95% CI [-0.0267, +0.0475] |
| Nearest historical tick is a causally valid observation | Signed timestamp audit against raw `price_history` | **Rejected** -- 46.1% of 24h snapshots select a tick recorded *after* the nominal target |
| Look-ahead explains the Politics result | Causal re-extraction (`timestamp <= target`) | **Rejected** -- estimate moved from -0.0490 to -0.0495 |
| Weather's +17pp bias is real calibration error | Reconstruction of 348 exclusive ladders from templated question text | **Rejected** -- the `[0.05, 0.95]` filter discards the winning rung in 65.2% of reconstructed ladders; removing it collapses the bias to +3.9pp, which is in turn numerically accounted for *within the reconstructed sample* by incomplete ladder representation (mean price sum 0.983 vs outcome sum 0.782 over 5.17 rungs). Ladder identity was reconstructed heuristically, not from authoritative group membership |
| The `Politics` category represents homogeneous political markets | Cohort composition audit | **Rejected** -- 69% are speech-phrase novelty markets; 12% are count/rating ladders with the opposite sign |
| `[0.05, 0.95]` is neutral data cleaning | Filtered vs unfiltered comparison | **Rejected** -- it is a selection operator on predictions; Politics bias -0.0238 unfiltered vs -0.0490 filtered |
| One database row is one independent observation | Group identity probe (`negRisk`, `negRiskMarketID`) | **Rejected** -- contracts are frequently rungs of a shared exclusive structure |
| `negRiskMarketID` can be used as a server-side group filter | Live API probe | **Rejected** -- returns HTTP 200 with 0 of 25 records carrying the requested ID |
| `interval=1m` retrieves history for older markets | Re-fetch of a five-month-old token | **Rejected** -- returns zero points; explicit `startTs`/`endTs` returns 43 |
| The historical reference price is an executable fill | Live comparison against midpoint, book sides, last trade | **Unsupported** -- consistent with a midpoint on tight-spread markets, untested on wide spreads, and never demonstrated to be transactable |
| ROADMAP's 1h pre-resolution result (n=2,523) | Re-run of the same query in `calibration.py` | **Retracted** -- current database yields 18 qualifying observations; provenance insufficient to reconstruct the original figure |

## Collection-time censoring

Collection ran with a $10,000 minimum-volume inclusion rule (minimum stored
`volume_usd` is 10,003). Contracts below that threshold were outside the sampling
frame, so **exclusive-group completeness cannot be established from this dataset**.
This is not a claim that every group is incomplete, nor that any specific missing
outcome was absent because of its volume -- only that completeness is unverifiable
here. Partition-level analysis requires recollection without that rule.

## Status of the derived figures

The +20.46% figure reported for the Politics strategy is a **historical signal-return
calculation using non-executable reference prices**, not a backtest. It has no
demonstrated fill, no holdout period, a price band selected after seeing that a wider
band was not significant, an event-dependence structure that was never modelled, and a
reported maximum drawdown computed against peak cumulative P&L rather than an equity
curve, which is why that figure exceeds 100% and is uninterpretable.

No positive calibration anomaly in this dataset currently meets the standard required
for a substantive research claim.
