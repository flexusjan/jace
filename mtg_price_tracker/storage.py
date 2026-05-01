from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

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
    id BIGSERIAL PRIMARY KEY,
    scryfall_id TEXT NOT NULL REFERENCES cards(scryfall_id),
    tracked_name TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    currency TEXT NOT NULL,
    price NUMERIC(12, 2),
    captured_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_price_snapshots_card_time
ON price_snapshots(scryfall_id, captured_at);
"""


@dataclass(frozen=True)
class ReportRow:
    name: str
    set_code: str
    collector_number: str
    source_url: str
    quantity: int
    currency: str
    latest_price: Decimal | None
    latest_captured_at: datetime
    first_price: Decimal | None
    first_captured_at: datetime


@dataclass(frozen=True)
class HistoryPoint:
    captured_at: datetime
    price: Decimal | None
    currency: str


class PriceStore:
    def __init__(self, database_url: str | None = None, connection: Any | None = None) -> None:
        self.database_url = database_url or os.environ.get("DATABASE_URL")
        self.connection = connection or self._connect(self.database_url)
        self._initialize_schema()

    def close(self) -> None:
        self.connection.close()

    def save_snapshot(self, request: CardRequest, price: CardPrice, captured_at: datetime | None = None) -> None:
        timestamp = captured_at or datetime.now(timezone.utc)
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO cards (scryfall_id, name, set_code, collector_number, source_url)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (scryfall_id) DO UPDATE SET
                        name = excluded.name,
                        set_code = excluded.set_code,
                        collector_number = excluded.collector_number,
                        source_url = excluded.source_url
                    """,
                    (price.scryfall_id, price.name, price.set_code, price.collector_number, price.source_url),
                )
                cursor.execute(
                    """
                    INSERT INTO price_snapshots (scryfall_id, tracked_name, quantity, currency, price, captured_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        price.scryfall_id,
                        request.name,
                        request.quantity,
                        price.currency,
                        price.price,
                        timestamp,
                    ),
                )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def latest_rows(self) -> list[ReportRow]:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                WITH latest AS (
                    SELECT DISTINCT ON (scryfall_id)
                        scryfall_id, quantity, currency, price, captured_at
                    FROM price_snapshots
                    ORDER BY scryfall_id, captured_at DESC, id DESC
                ),
                first AS (
                    SELECT DISTINCT ON (scryfall_id)
                        scryfall_id, price, captured_at
                    FROM price_snapshots
                    ORDER BY scryfall_id, captured_at ASC, id ASC
                )
                SELECT
                    c.name,
                    c.set_code,
                    c.collector_number,
                    c.source_url,
                    latest.quantity,
                    latest.currency,
                    latest.price AS latest_price,
                    latest.captured_at AS latest_captured_at,
                    first.price AS first_price,
                    first.captured_at AS first_captured_at
                FROM latest
                JOIN cards c ON c.scryfall_id = latest.scryfall_id
                LEFT JOIN first ON first.scryfall_id = latest.scryfall_id
                ORDER BY c.name COLLATE "C"
                """
            )
            return [row_to_report(row) for row in cursor.fetchall()]

    def history_rows(self) -> dict[str, list[HistoryPoint]]:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    c.name,
                    ps.captured_at,
                    ps.price,
                    ps.currency
                FROM price_snapshots ps
                JOIN cards c ON c.scryfall_id = ps.scryfall_id
                ORDER BY c.name COLLATE "C", ps.captured_at ASC, ps.id ASC
                """
            )
            history: dict[str, list[HistoryPoint]] = {}
            for row in cursor.fetchall():
                values = dict(row)
                history.setdefault(values["name"], []).append(
                    HistoryPoint(
                        captured_at=values["captured_at"],
                        price=decimal_or_none(values["price"]),
                        currency=values["currency"],
                    )
                )
            return history

    def _initialize_schema(self) -> None:
        try:
            with self.connection.cursor() as cursor:
                for statement in schema_statements():
                    cursor.execute(statement)
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    @staticmethod
    def _connect(database_url: str | None) -> Any:
        if not database_url:
            raise ValueError("DATABASE_URL must be set for Postgres storage")
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("Install the project dependencies to use Postgres storage: psycopg[binary]") from exc
        return psycopg.connect(database_url, row_factory=dict_row)


def row_to_report(row: Any) -> ReportRow:
    values = dict(row)
    return ReportRow(
        name=values["name"],
        set_code=values["set_code"],
        collector_number=values["collector_number"],
        source_url=values["source_url"],
        quantity=values["quantity"],
        currency=values["currency"],
        latest_price=decimal_or_none(values["latest_price"]),
        latest_captured_at=values["latest_captured_at"],
        first_price=decimal_or_none(values["first_price"]),
        first_captured_at=values["first_captured_at"],
    )


def schema_statements() -> list[str]:
    return [statement.strip() for statement in SCHEMA.split(";") if statement.strip()]


def decimal_or_none(value: Any) -> Decimal | None:
    return Decimal(str(value)) if value is not None else None
