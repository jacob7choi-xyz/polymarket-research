# Research Data Pipeline

Calibration dataset pipeline for prediction market probability modeling. Fetches historical resolved binary markets from Polymarket and their price histories for offline analysis.

This pipeline is completely standalone — it does not import from `src/polymarket_arbitrage/`.

## Setup

Requires `httpx` and `structlog` (already in project dependencies).

## Usage

Run from the project root:

```bash
# Step 1: Fetch all resolved binary markets from Gamma API
python -m research.pipeline.fetch_markets

# Step 2: Fetch YES token price history for each market from CLOB API
python -m research.pipeline.fetch_prices
```

Step 1 is resumable — progress is checkpointed to `research/data/checkpoint.json`. If interrupted, re-run to continue from where it left off.

Step 2 fetches price history only for markets not yet processed (idempotent).

## Data Schema

### `markets` table

| Column | Type | Description |
|---|---|---|
| market_id | TEXT PK | Gamma API market ID |
| question | TEXT | Market question |
| category | TEXT | Market category (nullable) |
| created_at | TEXT | ISO timestamp of creation |
| closed_at | TEXT | ISO timestamp of closure (nullable) |
| volume_usd | REAL | Total volume traded |
| resolved_yes | INTEGER | 1=YES won, 0=NO won, NULL=ambiguous/voided |
| final_yes_price | REAL | Last YES price before close (nullable) |
| price_history_fetched | INTEGER | 0/1 flag for resumability |
| fetched_at | TEXT | When this row was ingested |

### `price_history` table

| Column | Type | Description |
|---|---|---|
| market_id | TEXT FK | References markets.market_id |
| timestamp | INTEGER | Unix timestamp |
| price | REAL | YES token price at that time |

## Known Limitations

- **CLOB API gaps**: Some markets have no price history available (token not found, or history endpoint returns empty). These are marked with `final_yes_price = NULL`.
- **Aggregation bias**: The `fidelity=60` parameter returns minute-level data aggregated by the API. The "final price" is the last available data point before `closed_at`, which may not reflect the true last trade.
- **Rate limiting**: Both APIs are called at ~1 req/sec. Full dataset fetch takes several hours.
- **Token ID lookup**: Price fetching requires a separate API call per market to resolve CLOB token IDs, doubling the number of requests in step 2.
