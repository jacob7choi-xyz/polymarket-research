"""Extract pre-resolution prices (24h, 6h, 1h before close) from price_history."""

from datetime import datetime
import sqlite3

import structlog

from research.pipeline.storage import get_connection

logger = structlog.get_logger()

# Offsets in seconds
OFFSETS = {
    "price_24h_before": 24 * 3600,
    "price_6h_before": 6 * 3600,
    "price_1h_before": 1 * 3600,
}


def _parse_closed_at_ts(closed_at: str | None) -> float | None:
    if not closed_at:
        return None
    try:
        dt = datetime.fromisoformat(closed_at.replace("Z", "+00:00"))
        return dt.timestamp()
    except ValueError:
        return None


def _find_closest_price(conn: sqlite3.Connection, market_id: str, target_ts: float) -> float | None:
    """Find the price entry closest to target_ts for a given market."""
    row = conn.execute(
        """
        SELECT price FROM price_history
        WHERE market_id = ?
        ORDER BY ABS(timestamp - ?) ASC
        LIMIT 1
        """,
        (market_id, target_ts),
    ).fetchone()
    if row is None:
        return None
    result: float = row[0]
    return result


def extract_preresolution_prices() -> None:
    """For each market, extract prices at 24h, 6h, and 1h before close."""
    conn = get_connection()
    conn.row_factory = sqlite3.Row

    markets = conn.execute(
        """
        SELECT market_id, closed_at FROM markets
        WHERE price_history_fetched = 1 AND closed_at IS NOT NULL
        """
    ).fetchall()
    conn.row_factory = None

    logger.info("extracting_preresolution_prices", total_markets=len(markets))

    updated = 0
    for market in markets:
        market_id = market["market_id"]
        closed_at_ts = _parse_closed_at_ts(market["closed_at"])
        if closed_at_ts is None:
            continue

        prices = {}
        for col, offset_seconds in OFFSETS.items():
            target_ts = closed_at_ts - offset_seconds
            prices[col] = _find_closest_price(conn, market_id, target_ts)

        conn.execute(
            """
            UPDATE markets
            SET price_24h_before = ?, price_6h_before = ?, price_1h_before = ?
            WHERE market_id = ?
            """,
            (
                prices["price_24h_before"],
                prices["price_6h_before"],
                prices["price_1h_before"],
                market_id,
            ),
        )
        updated += 1

        if updated % 500 == 0:
            conn.commit()
            logger.info("progress", updated=updated)

    conn.commit()
    conn.close()
    logger.info("extraction_done", total_updated=updated)


if __name__ == "__main__":
    extract_preresolution_prices()
