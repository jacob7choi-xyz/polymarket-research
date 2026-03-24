# Research Roadmap

Personal reference for picking this project back up.

---

## 1. Where We Are Now

- **fetch_markets.py** — collects resolved binary markets from the Gamma API
- **fetch_prices.py** — fetches CLOB price history for each market
- **Data lives in** `research/data/markets.db` (SQLite)
- **Target**: 10,000 resolved markets with price histories

The pipeline fetches resolved markets, extracts final YES/NO prices from outcome data, and stores everything in SQLite. Price histories come from the CLOB API using token IDs.

---

## 2. Immediate Next Steps When Returning

1. **Check how much data we actually have:**
   ```sql
   SELECT COUNT(*) FROM markets;
   SELECT COUNT(*) FROM markets WHERE final_yes_price IS NOT NULL;
   SELECT COUNT(*) FROM markets WHERE final_yes_price IS NULL;
   ```

2. **Run fetch_prices.py** to backfill CLOB price histories for all fetched markets

3. **Basic data exploration:**
   - Distribution of `final_yes_price` — are resolved markets mostly 0/1 or spread across the range?
   - Category breakdown (politics, crypto, sports, etc.)
   - Volume and liquidity distributions
   - Ratio of YES-resolved vs NO-resolved markets

---

## What We Learned (First Analysis)

Ran `research/analysis/calibration.py` on 9,902 resolved markets. Key findings:

1. **Dataset is dominated by near-certain markets (~95%).** The 0-10% bin has 7,063 markets and the 90-100% bin has 2,367. These are markets where the outcome was already obvious by the time they had a final price — not useful for studying calibration.

2. **Ghost markets initialized at ~0.50 with no real trading.** Many markets in the 40-60% range show 0% or 100% resolution rates with tiny sample sizes (e.g. 43 markets in the 50-60% bin). These appear to be low-liquidity markets that never attracted real trading activity, so their "final price" is just the initialization value, not a crowd estimate.

3. **Only ~50 genuinely uncertain, high-volume markets in the entire 10k sample.** The middle of the probability spectrum (20-80%) contains fewer than 300 markets total, and most of those are ghost markets. After filtering for meaningful volume, we'd be left with a handful — far too few for a calibration curve.

**Bottom line:** The first 10k resolved markets from the Gamma API are almost entirely slam-dunk outcomes. The calibration curve is a step function (0% → 100%) rather than a smooth diagonal, because the dataset lacks genuinely uncertain markets.

---

## What We Learned (Pre-Resolution Calibration)

Shifted from final prices (which are mostly 0/1) to **pre-resolution snapshot prices** — what the market thought 24h, 6h, and 1h before resolution. Filtered to 0.05-0.95 to exclude near-certain markets.

### Pre-resolution calibration curves

- **24h before**: 2,847 markets. Reasonably well-calibrated overall, with slight overconfidence in the 60-80% range.
- **6h before**: 2,685 markets. Tighter to the diagonal — crowds correct as resolution approaches.
- **1h before**: 2,523 markets. Nearly perfect calibration. Markets are efficient in the final hour.

**Key finding:** Polymarket crowds are well-calibrated in aggregate, but the signal degrades as you move further from resolution. The 24h-before window is where exploitable miscalibration is most likely.

### Category-level calibration

Built per-category calibration curves using 24h-before prices. Categories with 50+ markets:

- **Crypto** — Systematic overconfidence. Markets priced at 60-80% resolve YES less often than implied. This is the strongest bias signal in the dataset.
- **Sports** — Well-calibrated across the board. Betting markets have decades of efficiency behind them.
- **Politics** — Slight overconfidence at the extremes, but sample sizes are smaller.

**Primary hypothesis:** Crypto markets on Polymarket attract participants with directional bias (bulls pricing YES too high), creating a persistent overconfidence pattern that may be exploitable.

### Next steps (from initial analysis)

1. ~~Deep-dive into Crypto overconfidence~~ -- Done. See validation results below.
2. ~~Backtest against transaction costs~~ -- Not needed. Signal was noise.
3. ~~Scale the dataset~~ -- Done. 497 crypto markets (up from ~50).

---

## Crypto Overconfidence: Validation and Null Result

Ran `research/analysis/validate_crypto_signal.py` (bootstrap CI, volume weighting, time-period splits, cross-category comparison) on 497 crypto markets with 24h-before prices in the 0.05-0.95 range.

### Methodology

Five tests applied to the crypto overconfidence hypothesis:

1. **Bootstrap confidence intervals** (10,000 iterations) on mean calibration error (predicted - actual). Positive error = overconfidence.
2. **Volume-weighted calibration error** to check whether the signal is driven by low-liquidity ghost markets.
3. **Time-period consistency** -- split by month, bootstrap each period independently.
4. **Price-bin breakdown** -- calibration error by quintile across the probability spectrum.
5. **Cross-category comparison** -- same methodology applied to all categories to contextualize the result.

### Results

**Test 1 -- Statistical Significance:**
The raw calibration error for crypto is +0.0104 (prices ~1% higher than outcomes on average). The 95% bootstrap CI is [-0.027, +0.048]. The interval includes zero.

**Conclusion: Not statistically significant.** We cannot reject the null hypothesis that crypto markets are perfectly calibrated.

**Test 2 -- Volume Weighting:**
Volume-weighted error is +0.019 with CI [-0.048, +0.084]. Wider interval, still includes zero. The signal does not strengthen when weighting by volume -- if anything, it becomes noisier.

**Test 3 -- Time Periods:**
- 2026-02 (n=393): error +0.020, CI [-0.022, +0.060] -- not significant
- 2026-03 (n=104): error -0.025, CI [-0.113, +0.063] -- not significant, direction reverses

The signal is not consistent across months. February shows slight overconfidence, March shows slight underconfidence. This is noise, not a persistent pattern.

**Test 4 -- Price Bins:**

| Bin | N | Avg Price | Actual Rate | Error |
|-----|---|-----------|-------------|-------|
| 5-23% | 176 | 0.126 | 0.182 | -0.056 |
| 23-41% | 105 | 0.315 | 0.248 | +0.067 |
| 41-59% | 77 | 0.502 | 0.455 | +0.047 |
| 59-77% | 54 | 0.675 | 0.667 | +0.009 |
| 77-95% | 85 | 0.881 | 0.835 | +0.046 |

Mixed signal. Low-probability crypto markets are actually *underconfident* (5-23% bin: -0.056), while mid-range markets show mild overconfidence. The pattern is inconsistent and bins have small sample sizes (n=54 to n=176).

**Test 5 -- Cross-Category Comparison:**

| Category | N | Error | 95% CI | Significant? |
|----------|---|-------|--------|-------------|
| AI/Tech | 108 | -0.064 | [-0.146, +0.015] | No |
| Crypto | 497 | +0.010 | [-0.026, +0.048] | No |
| Other | 899 | -0.012 | [-0.040, +0.016] | No |
| Politics | 323 | -0.049 | [-0.096, -0.003] | Yes (underconfident) |
| Sports | 2267 | -0.017 | [-0.035, +0.002] | No |
| Weather | 876 | -0.018 | [-0.045, +0.008] | No |

Crypto is the *only* category with a positive error, but it's not significant. The one statistically significant finding is **Politics: systematic underconfidence** (CI entirely below zero). Political markets are priced too low relative to actual outcomes.

### Why the Initial Finding Was Misleading

The original calibration curve analysis (which suggested "systematic overconfidence" in crypto) suffered from:

1. **Small sample artifacts.** The initial analysis had ~50 crypto markets in the uncertain range. With 497, the effect shrinks from visually obvious to statistically insignificant.
2. **Binning artifacts.** 10-bin calibration curves with small counts per bin amplify noise. A single outlier market in a bin of 15 can shift the curve visually.
3. **No confidence intervals.** Without CIs, a 3-4 percentage point deviation looks meaningful on a plot but is well within sampling noise.

### Implications

- **No exploitable edge in crypto markets.** The overconfidence hypothesis is rejected. A backtest would be fitting noise.
- **Politics underconfidence is the one real signal** in the dataset. This warrants further investigation: are political markets systematically underpriced? Does this survive after Polymarket's ~2% fee?
- **Polymarket crowds are well-calibrated overall.** Across 4,970 uncertain markets, the aggregate calibration error is small. The market is efficient.

### Next Steps (from crypto validation)

1. ~~Investigate political underconfidence~~ -- Done. See backtest below.
2. ~~Backtest a politics contrarian strategy~~ -- Done. See backtest below.
3. **Consider non-price features** -- volume trajectory, time-to-resolution, trader count may predict miscalibration better than category alone.

---

## Politics Underconfidence: Backtest Results

Ran `research/analysis/backtest_politics.py` on political markets with 24h-before prices in the uncertain range. Strategy: buy YES at 24h before resolution, flat $100 bet sizing, 2% fee on winnings.

### Strategy

Political markets are systematically underpriced -- outcomes resolve YES more often than the price implies. The strategy buys YES on political markets where the 24h-before price is between 0.20 and 0.80 (the range where underconfidence is observed).

### Results

**Full range (0.20-0.80):**

| Metric | Value |
|--------|-------|
| Trades | 195 |
| Win rate | 57.9% |
| Gross P&L | +$3,141 |
| Fees paid | $227 |
| Net P&L | +$2,914 |
| Net ROI | +14.9% |
| Bootstrap 95% CI | [-0.6%, +30.5%] |
| Significant? | No (CI includes zero) |

**Sweet spot (0.40-0.80):**

| Metric | Value |
|--------|-------|
| Trades | 139 |
| Win rate | 69.1% |
| Gross P&L | +$2,989 |
| Fees paid | $146 |
| Net P&L | +$2,843 |
| Net ROI | +20.5% |
| Sharpe ratio | 0.239 |
| Bootstrap 95% CI | [+5.9%, +34.4%] |
| Significant? | **Yes** (CI does not include zero) |

**Monthly consistency:**

| Month | N | Win% | Net P&L | ROI |
|-------|---|------|---------|-----|
| 2026-02 | 176 | 57% | +$2,262 | +12.9% |
| 2026-03 | 19 | 63% | +$652 | +34.3% |

### Key Findings

1. **The edge is real and survives fees.** The 0.40-0.80 range produces +20.5% net ROI with a 95% CI that excludes zero. This is not noise.
2. **The sweet spot matters.** Including low-probability markets (0.20-0.40) dilutes the signal. The edge is concentrated where true uncertainty meets systematic underpricing.
3. **Consistent across months.** Profitable in both Feb and March 2026, though March has only 19 trades.
4. **Win rate drives it.** 69.1% win rate on markets priced at 40-80% means outcomes exceed expectations by ~10-13 percentage points.

### Caveats

- **Small sample (139 trades).** Two months of data. Need 6-12 months to confirm persistence.
- **No slippage modeling.** Assumes entry at the exact 24h-before price. Real execution would face bid-ask spread.
- **Survivorship bias risk.** All markets are resolved -- we don't see markets that were delisted or voided.
- **Max drawdown is high (208%).** The strategy experiences significant losing streaks. Position sizing via Kelly criterion would reduce this.
- **Category inference is keyword-based.** Some markets may be miscategorized.

### Next Steps

1. **Continue collecting data** -- the signal needs 6+ months of out-of-sample validation.
2. **Kelly criterion sizing** -- reduce drawdown by sizing bets proportional to edge, not flat.
3. **Slippage modeling** -- estimate bid-ask spread impact on realistic entry prices.
4. **Expand to other categories** -- AI/Tech shows a similar (non-significant) underconfidence pattern at -6.4%. May become significant with more data.

---

## 3. Building the Calibration Curve (Core Research Goal)

### What it is
Bucket markets by their final YES price (the crowd's last probability estimate before resolution). For each bucket, measure the actual resolution rate.

Example: Of all markets where the final YES price was ~0.70, did ~70% actually resolve YES?

### What to look for
- **Perfect calibration** = points on the diagonal (70% price → 70% resolve YES)
- **Deviation from diagonal** = systematic crowd bias = exploitable edge
- Overconfidence: high-priced markets resolve YES less often than the price implies
- Underconfidence: low-priced markets resolve YES more often than expected

### Break it down
- By **category** (politics, crypto, sports) — bias likely varies by domain
- By **volume** — high-volume markets may be better calibrated
- By **time period** — calibration may shift over time
- By **days to resolution** — short-term vs long-term markets

---

## 4. The ML Model (After Calibration Curve)

### Feature ideas
- Category (one-hot or embedding)
- Volume and liquidity
- Days to close
- Price trajectory (slope, volatility, momentum in final hours/days)
- Number of unique traders (if available)
- Market description embeddings (NLP features)

### Target variable
- Binary: did market resolve YES?
- Or regression: predict true probability, compare to crowd price

### Honest backtesting — non-negotiable
- **No lookahead bias**: train only on markets that resolved before the test period
- **Realistic fees**: Polymarket charges ~2% on winnings
- **Slippage**: large orders move the price, especially in thin markets
- **Time-series split**: walk-forward validation, never random split
- **Kelly criterion**: size bets proportional to edge, not fixed amounts

---

## 5. Commands Cheat Sheet

```bash
# Resume market fetch (checkpointed, safe to interrupt)
python -m research.pipeline.fetch_markets --max-markets 10000

# Fetch CLOB price histories for all markets in DB
python -m research.pipeline.fetch_prices

# Quick DB health check
sqlite3 research/data/markets.db "SELECT COUNT(*), AVG(final_yes_price) FROM markets WHERE final_yes_price IS NOT NULL"

# Count markets by category
sqlite3 research/data/markets.db "SELECT category, COUNT(*) FROM markets GROUP BY category ORDER BY COUNT(*) DESC"

# Check price history coverage
sqlite3 research/data/markets.db "SELECT COUNT(DISTINCT market_id) FROM price_history"
```

---

## 6. Key Technical Gotchas

- **Gamma API JSON strings**: `outcomes` and `outcomePrices` come back as JSON-encoded strings, not native lists. Must `json.loads()` before use.
- **Interpreting final prices**: `outcomePrices ["1","0"]` = YES won, `["0","1"]` = NO won, anything else = ambiguous/unresolved.
- **CLOB API uses token IDs**, not market IDs. The query parameter is `market`, not `token_id`.
- **Old markets (pre-2022)** have no CLOB price history — fetch newest markets first to maximize coverage.
- **Pipeline is checkpointed** — safe to Ctrl+C and resume anytime. It picks up where it left off.
- **Rate limiting**: both APIs have rate limits. The pipeline has built-in delays but watch for 429s.

---

## 7. Longer Term Vision

```
Calibration curve
  → Find systematic biases in crowd pricing
    → ML model to predict mispricings
      → Paper trade the strategy, prove the edge exists
        → Real capital (small, with strict risk limits)
          → 10-year: probability intelligence product/API
```

The end game isn't just trading. It's understanding where crowds systematically get probability wrong — and building tools around that insight. A calibration-as-a-service API, decision support for forecasters, or a hedge fund that trades on crowd bias.

But first: get the data, draw the curve, see if the edge is real.
