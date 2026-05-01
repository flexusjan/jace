from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from .models import CardPrice, CardRequest


SCHEMA = """
CREATE TABLE IF NOT EXISTS cards (
    scryfall_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    set_code TEXT NOT NULL,
    collector_number TEXT NOT NULL,
    source_url TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS price_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scryfall_id TEXT NOT NULL REFERENCES cards(scryfall_id),
    tracked_name TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    currency TEXT NOT NULL,
    price TEXT,
    captured_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_price_snapshots_card_time
ON price_snapshots(scryfall_id, captured_at);
"""


class PriceStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)

    def close(self) -> None:
        self.connection.close()

    def save_snapshot(self, request: CardRequest, price: CardPrice, captured_at: datetime | None = None) -> None:
        timestamp = (captured_at or datetime.now(timezone.utc)).isoformat(timespec="seconds")
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO cards (scryfall_id, name, set_code, collector_number, source_url)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(scryfall_id) DO UPDATE SET
                    name = excluded.name,
                    set_code = excluded.set_code,
                    collector_number = excluded.collector_number,
                    source_url = excluded.source_url
                """,
                (price.scryfall_id, price.name, price.set_code, price.collector_number, price.source_url),
            )
            self.connection.execute(
                """
                INSERT INTO price_snapshots (scryfall_id, tracked_name, quantity, currency, price, captured_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    price.scryfall_id,
                    request.name,
                    request.quantity,
                    price.currency,
                    str(price.price) if price.price is not None else None,
                    timestamp,
                ),
            )

    def latest_rows(self) -> list[sqlite3.Row]:
        return self.connection.execute(
            """
            WITH latest AS (
                SELECT scryfall_id, max(captured_at) AS captured_at
                FROM price_snapshots
                GROUP BY scryfall_id
            ),
            first AS (
                SELECT scryfall_id, min(captured_at) AS captured_at
                FROM price_snapshots
                GROUP BY scryfall_id
            )
            SELECT
                c.name,
                c.set_code,
                c.collector_number,
                c.source_url,
                ps.quantity,
                ps.currency,
                ps.price AS latest_price,
                ps.captured_at AS latest_captured_at,
                fps.price AS first_price,
                fps.captured_at AS first_captured_at
            FROM latest
            JOIN price_snapshots ps ON ps.scryfall_id = latest.scryfall_id AND ps.captured_at = latest.captured_at
            JOIN cards c ON c.scryfall_id = ps.scryfall_id
            LEFT JOIN first ON first.scryfall_id = ps.scryfall_id
            LEFT JOIN price_snapshots fps ON fps.scryfall_id = first.scryfall_id AND fps.captured_at = first.captured_at
            ORDER BY c.name COLLATE NOCASE
            """
        ).fetchall()


def decimal_or_none(value: str | None) -> Decimal | None:
    return Decimal(value) if value is not None else None
