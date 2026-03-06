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
