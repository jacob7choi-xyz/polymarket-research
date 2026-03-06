"""Fetch YES token price history from the Polymarket CLOB API."""

from datetime import datetime
import json
import time

import httpx
import structlog

from research.pipeline.storage import (
    get_connection,
    get_unfetched_markets,
    mark_price_history_fetched,
    upsert_price_history,
)

logger = structlog.get_logger()

CLOB_API_URL = "https://clob.polymarket.com/prices-history"
RATE_LIMIT_DELAY = 0.5
MAX_RETRIES = 5


def _parse_closed_at_timestamp(closed_at: str | None) -> float | None:
    """Parse a closed_at ISO string to a Unix timestamp."""
    if not closed_at:
        return None
    try:
        dt = datetime.fromisoformat(closed_at.replace("Z", "+00:00"))
        return dt.timestamp()
    except ValueError:
        return None


def _extract_final_price(
    history: list[dict[str, float]], closed_at_ts: float | None
) -> float | None:
    """Get the last price entry before the closed_at timestamp.

    If closed_at is unavailable, returns the very last price in the history.
    """
    if not history:
        return None

    if closed_at_ts is None:
        return history[-1].get("p")

    # History entries have "t" (timestamp) and "p" (price)
    candidates = [entry for entry in history if entry.get("t", 0) <= closed_at_ts]
    if not candidates:
        # Fall back to first entry if all are after close
        return history[0].get("p")

    return candidates[-1].get("p")


def _fetch_price_history(client: httpx.Client, token_id: str) -> list[dict[str, float]]:
    """Fetch price history for a token with retry and backoff."""
    params = {
        "market": token_id,
        "interval": "1m",
        "fidelity": "60",
    }

    for attempt in range(MAX_RETRIES):
        try:
            response = client.get(CLOB_API_URL, params=params)

            if response.status_code in (429, 503):
                wait = RATE_LIMIT_DELAY * (2**attempt)
                logger.warning(
                    "rate_limited",
                    status=response.status_code,
                    retry_in=wait,
                    attempt=attempt + 1,
                )
                time.sleep(wait)
                continue

            response.raise_for_status()
            data = response.json()

            # API returns {"history": [...]} or just a list
            if isinstance(data, dict):
                history: list[dict[str, float]] = data.get("history", [])
                return history
            if isinstance(data, list):
                return data
            return []

        except (httpx.TimeoutException, httpx.RemoteProtocolError) as exc:
            wait = RATE_LIMIT_DELAY * (2**attempt)
            logger.warning(
                "transient_error",
                error=str(exc),
                retry_in=wait,
                attempt=attempt + 1,
            )
            time.sleep(wait)
            continue

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.warning("token_not_found", token_id=token_id)
                return []
            logger.error("http_error", status=e.response.status_code, token_id=token_id)
            raise

    logger.error("max_retries_exceeded", token_id=token_id)
    return []


def _get_yes_token_id(market: dict[str, str | None]) -> str | None:
    """Extract the YES token CLOB ID from a market row.

    The first clobTokenId corresponds to the YES outcome.
    clob_token_ids is stored as a JSON string in the database.
    """
    clob_ids_raw = market.get("clob_token_ids")
    if not clob_ids_raw:
        return None
    try:
        clob_ids: list[str] = json.loads(clob_ids_raw)
        if clob_ids:
            return clob_ids[0]
    except (json.JSONDecodeError, TypeError):
        return None
    return None


def fetch_all_prices() -> None:
    """Fetch price history for all markets that haven't been fetched yet."""
    conn = get_connection()
    unfetched = get_unfetched_markets(conn)

    logger.info("starting_price_fetch", unfetched_count=len(unfetched))

    client = httpx.Client(timeout=30.0)
    processed = 0

    try:
        for market in unfetched:
            market_id = market["market_id"]

            token_id = _get_yes_token_id(market)
            if token_id is None:
                logger.warning("no_token_id", market_id=market_id)
                mark_price_history_fetched(conn, market_id, None)
                conn.commit()
                processed += 1
                time.sleep(RATE_LIMIT_DELAY)
                continue

            history = _fetch_price_history(client, token_id)

            closed_at_ts = _parse_closed_at_timestamp(market.get("closed_at"))

            if history:
                price_rows = [
                    {"timestamp": int(entry.get("t", 0)), "price": entry.get("p", 0.0)}
                    for entry in history
                ]
                upsert_price_history(conn, market_id, price_rows)
                final_price = _extract_final_price(history, closed_at_ts)
            else:
                final_price = None

            mark_price_history_fetched(conn, market_id, final_price)
            conn.commit()

            processed += 1
            if processed % 100 == 0:
                logger.info("progress", markets_processed=processed, total=len(unfetched))

            time.sleep(RATE_LIMIT_DELAY)
    finally:
        client.close()
        conn.close()

    logger.info("price_fetch_done", total_processed=processed)


if __name__ == "__main__":
    fetch_all_prices()
