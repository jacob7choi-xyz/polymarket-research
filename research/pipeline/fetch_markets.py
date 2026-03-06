"""Fetch resolved binary markets from the Polymarket Gamma API."""

import argparse
from datetime import UTC, datetime
import json
import time

import httpx
import structlog

from research.pipeline.checkpoint import load_checkpoint, save_checkpoint
from research.pipeline.storage import get_connection, upsert_market

logger = structlog.get_logger()

GAMMA_API_URL = "https://gamma-api.polymarket.com/markets"
PAGE_SIZE = 100
MIN_CREATED_AT = "2022-01-01"
RATE_LIMIT_DELAY = 1.0
MAX_RETRIES = 5


def _parse_resolved_yes(outcome_prices_raw: str) -> bool | None:
    """Parse resolution from outcomePrices JSON string.

    ["1","0"] -> True (YES resolved), ["0","1"] -> False (NO resolved),
    anything else -> None (ambiguous/voided).
    """
    try:
        prices = json.loads(outcome_prices_raw)
    except (json.JSONDecodeError, TypeError):
        return None

    if prices == ["1", "0"]:
        return True
    if prices == ["0", "1"]:
        return False
    return None


def _parse_outcomes(outcomes_raw: str) -> list[str] | None:
    """Parse outcomes JSON string, returning None on failure."""
    try:
        result: list[str] = json.loads(outcomes_raw)
        return result
    except (json.JSONDecodeError, TypeError):
        return None


def _is_valid_market(market: dict) -> bool:
    """Check if a market meets our filter criteria."""
    created_at = market.get("createdAt", "")
    if created_at < MIN_CREATED_AT:
        return False

    if market.get("umaResolutionStatus") != "resolved":
        return False

    outcomes = _parse_outcomes(market.get("outcomes", "[]"))
    if outcomes != ["Yes", "No"]:
        return False

    return True


def _extract_market(market: dict) -> dict:
    """Extract relevant fields from a raw Gamma API market."""
    resolved_yes = _parse_resolved_yes(market.get("outcomePrices", "[]"))
    resolved_yes_int: int | None = None
    if resolved_yes is True:
        resolved_yes_int = 1
    elif resolved_yes is False:
        resolved_yes_int = 0

    clob_token_ids_raw = market.get("clobTokenIds", "[]")
    try:
        clob_token_ids: list[str] = json.loads(clob_token_ids_raw)
    except (json.JSONDecodeError, TypeError):
        clob_token_ids = []

    return {
        "market_id": str(market["id"]),
        "question": market.get("question", ""),
        "category": market.get("category"),
        "created_at": market.get("createdAt", ""),
        "closed_at": market.get("closedTime"),
        "volume_usd": float(market.get("volumeNum", 0) or 0),
        "resolved_yes": resolved_yes_int,
        "clob_token_ids": json.dumps(clob_token_ids),
        "fetched_at": datetime.now(UTC).isoformat(),
    }


def _fetch_page(client: httpx.Client, offset: int, min_volume: int = 0) -> list[dict]:
    """Fetch a single page from the Gamma API with retry and backoff."""
    params: dict[str, str | int] = {
        "closed": "true",
        "limit": PAGE_SIZE,
        "offset": offset,
        "order": "closedTime",
        "ascending": "false",
    }
    if min_volume > 0:
        params["volume_num_min"] = min_volume

    for attempt in range(MAX_RETRIES):
        try:
            response = client.get(GAMMA_API_URL, params=params)

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
            result: list[dict] = response.json()
            return result

        except httpx.TimeoutException:
            wait = RATE_LIMIT_DELAY * (2**attempt)
            logger.warning("timeout", retry_in=wait, attempt=attempt + 1)
            time.sleep(wait)
            continue

        except httpx.HTTPStatusError as e:
            logger.error("http_error", status=e.response.status_code, offset=offset)
            raise

    raise RuntimeError(f"Failed to fetch page at offset {offset} after {MAX_RETRIES} retries")


def fetch_all_markets(max_markets: int | None = None, min_volume: int = 0) -> None:
    """Fetch resolved binary markets and store them in SQLite."""
    checkpoint = load_checkpoint()
    suffix = f"_v{min_volume}" if min_volume > 0 else ""
    offset_key = f"market_fetch_offset{suffix}"
    total_key = f"market_fetch_total{suffix}"
    offset = checkpoint.get(offset_key, 0)
    total_stored = checkpoint.get(total_key, 0)

    logger.info(
        "starting_market_fetch",
        resume_offset=offset,
        previously_stored=total_stored,
        min_volume=min_volume,
    )

    conn = get_connection()
    client = httpx.Client(timeout=30.0)

    try:
        while True:
            page = _fetch_page(client, offset, min_volume=min_volume)

            if not page:
                logger.info("fetch_complete", total_markets=total_stored)
                break

            for market in page:
                if max_markets is not None and total_stored >= max_markets:
                    break

                if _is_valid_market(market):
                    extracted = _extract_market(market)
                    upsert_market(conn, extracted)
                    total_stored += 1

                    if total_stored % 100 == 0:
                        logger.info("progress", markets_stored=total_stored, offset=offset)

            if max_markets is not None and total_stored >= max_markets:
                logger.info("max_markets_reached", total_markets=total_stored)
                break

            conn.commit()
            offset += PAGE_SIZE
            save_checkpoint({offset_key: offset, total_key: total_stored})

            time.sleep(RATE_LIMIT_DELAY)
    finally:
        client.close()
        conn.close()

    logger.info("market_fetch_done", total=total_stored)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch resolved binary markets from Polymarket")
    parser.add_argument(
        "--max-markets", type=int, default=None, help="Stop after storing this many markets"
    )
    parser.add_argument(
        "--min-volume", type=int, default=10000, help="Minimum volume (USD) filter (default: 10000)"
    )
    args = parser.parse_args()
    fetch_all_markets(max_markets=args.max_markets, min_volume=args.min_volume)
