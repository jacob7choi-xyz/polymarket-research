"""Infer market categories from question text using keyword matching."""

import re
import sqlite3

from research.pipeline.storage import get_connection

CATEGORY_KEYWORDS: list[tuple[str, list[str]]] = [
    (
        "Sports",
        [
            " win ",
            "FC ",
            " vs ",
            "vs.",
            "match",
            "tournament",
            "championship",
            "league",
            "cup",
            "goal",
            "score",
            "playoff",
            "season",
            "NFL",
            "NBA",
            "MLB",
            "NHL",
            "UEFA",
            "FIFA",
        ],
    ),
    (
        "Crypto",
        [
            "Bitcoin",
            "BTC",
            "Ethereum",
            "ETH",
            "Solana",
            "SOL",
            "XRP",
            "crypto",
            "token",
            "price of",
        ],
    ),
    (
        "Weather",
        [
            "temperature",
            "rainfall",
            "hurricane",
            "earthquake",
            "weather",
        ],
    ),
    (
        "Politics",
        [
            "President",
            "Prime Minister",
            "election",
            "Trump",
            "Congress",
            "Senate",
            "vote",
            "party",
            "minister",
            "government",
        ],
    ),
    (
        "AI/Tech",
        [
            "GPT",
            "Claude",
            "Grok",
            "AI",
            "released by",
            "model",
            "OpenAI",
            "Anthropic",
        ],
    ),
]


def infer_category(question: str) -> str:
    """Return the first matching category for a question, or 'Other'."""
    for category, keywords in CATEGORY_KEYWORDS:
        for kw in keywords:
            if re.search(re.escape(kw), question, re.IGNORECASE):
                return category
    return "Other"


def main() -> None:
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT market_id, question FROM markets").fetchall()
    conn.row_factory = None

    counts: dict[str, int] = {}
    for row in rows:
        cat = infer_category(row["question"])
        counts[cat] = counts.get(cat, 0) + 1
        conn.execute(
            "UPDATE markets SET category = ? WHERE market_id = ?",
            (cat, row["market_id"]),
        )
    conn.commit()
    conn.close()

    print(f"Categorized {len(rows)} markets:\n")
    for cat, count in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {cat:<12} {count:>5}")


if __name__ == "__main__":
    main()
