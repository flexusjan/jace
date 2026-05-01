from __future__ import annotations

import os
import uuid
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
    source_url TEXT NOT NULL,
    image_url TEXT,
    image_content_type TEXT,
    image_data BYTEA
);

CREATE TABLE IF NOT EXISTS price_snapshots (
    id BIGSERIAL PRIMARY KEY,
    entry_id TEXT NOT NULL,
    scryfall_id TEXT NOT NULL REFERENCES cards(scryfall_id),
    tracked_name TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    condition TEXT NOT NULL DEFAULT 'NM',
    language TEXT NOT NULL DEFAULT 'English',
    currency TEXT NOT NULL,
    price NUMERIC(12, 2),
    captured_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_price_snapshots_card_time
ON price_snapshots(scryfall_id, captured_at);

CREATE INDEX IF NOT EXISTS idx_price_snapshots_entry_time
ON price_snapshots(entry_id, captured_at);
"""


@dataclass(frozen=True)
class ReportRow:
    id: str
    scryfall_id: str
    name: str
    set_code: str
    collector_number: str
    source_url: str
    has_cached_image: bool
    has_image_url: bool
    quantity: int
    condition: str
    language: str
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


@dataclass(frozen=True)
class TrackedCard:
    id: str
    scryfall_id: str
    request: CardRequest
    currency: str
    latest_captured_at: datetime


class PriceStore:
    def __init__(self, database_url: str | None = None, connection: Any | None = None, initialize_schema: bool = True) -> None:
        self.database_url = database_url or os.environ.get("DATABASE_URL")
        self.connection = connection or self._connect(self.database_url)
        if initialize_schema:
            self._initialize_schema()

    def close(self) -> None:
        self.connection.close()

    def save_snapshot(
        self,
        request: CardRequest,
        price: CardPrice,
        captured_at: datetime | None = None,
        entry_id: str | None = None,
    ) -> str:
        timestamp = captured_at or datetime.now(timezone.utc)
        snapshot_entry_id = entry_id or uuid.uuid4().hex
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO cards (scryfall_id, name, set_code, collector_number, source_url, image_url)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (scryfall_id) DO UPDATE SET
                        name = excluded.name,
                        set_code = excluded.set_code,
                        collector_number = excluded.collector_number,
                        source_url = excluded.source_url,
                        image_url = COALESCE(excluded.image_url, cards.image_url),
                        image_content_type = CASE
                            WHEN excluded.image_url IS DISTINCT FROM cards.image_url THEN NULL
                            ELSE cards.image_content_type
                        END,
                        image_data = CASE
                            WHEN excluded.image_url IS DISTINCT FROM cards.image_url THEN NULL
                            ELSE cards.image_data
                        END
                    """,
                    (
                        price.scryfall_id,
                        price.name,
                        price.set_code,
                        price.collector_number,
                        price.source_url,
                        price.image_url,
                    ),
                )
                cursor.execute(
                    """
                    INSERT INTO price_snapshots (entry_id, scryfall_id, tracked_name, quantity, condition, language, currency, price, captured_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        snapshot_entry_id,
                        price.scryfall_id,
                        request.name,
                        request.quantity,
                        request.condition,
                        request.language,
                        price.currency,
                        price.price,
                        timestamp,
                    ),
                )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return snapshot_entry_id

    def latest_rows(self) -> list[ReportRow]:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                WITH latest AS (
                    SELECT DISTINCT ON (entry_id)
                        entry_id, scryfall_id, quantity, condition, language, currency, price, captured_at
                    FROM price_snapshots
                    ORDER BY entry_id, captured_at DESC, id DESC
                ),
                first AS (
                    SELECT DISTINCT ON (entry_id)
                        entry_id, price, captured_at
                    FROM price_snapshots
                    ORDER BY entry_id, captured_at ASC, id ASC
                )
                SELECT
                    latest.entry_id AS id,
                    c.scryfall_id,
                    c.name,
                    c.set_code,
                    c.collector_number,
                    c.source_url,
                    c.image_data IS NOT NULL AS has_cached_image,
                    c.image_url IS NOT NULL AS has_image_url,
                    latest.quantity,
                    latest.condition,
                    latest.language,
                    latest.currency,
                    latest.price AS latest_price,
                    latest.captured_at AS latest_captured_at,
                    first.price AS first_price,
                    first.captured_at AS first_captured_at
                FROM latest
                JOIN cards c ON c.scryfall_id = latest.scryfall_id
                LEFT JOIN first ON first.entry_id = latest.entry_id
                ORDER BY c.name COLLATE "C", c.set_code COLLATE "C", c.collector_number COLLATE "C", latest.condition COLLATE "C", latest.language COLLATE "C"
                """
            )
            rows = [row_to_report(row) for row in cursor.fetchall()]
        self.connection.commit()
        return rows

    def image_info(self, scryfall_id: str) -> dict[str, Any] | None:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT image_url, image_content_type, image_data
                FROM cards
                WHERE scryfall_id = %s
                """,
                (scryfall_id,),
            )
            rows = cursor.fetchall()
        self.connection.commit()
        if not rows:
            return None
        return dict(rows[0])

    def save_image(self, scryfall_id: str, content_type: str, data: bytes) -> None:
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE cards
                    SET image_content_type = %s, image_data = %s
                    WHERE scryfall_id = %s
                    """,
                    (content_type, data, scryfall_id),
                )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def update_card_artwork(self, scryfall_id: str, image_url: str) -> None:
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE cards
                    SET image_url = %s,
                        image_content_type = NULL,
                        image_data = NULL
                    WHERE scryfall_id = %s
                    """,
                    (image_url, scryfall_id),
                )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def delete_cards(self, scryfall_ids: list[str]) -> int:
        if not scryfall_ids:
            return 0
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(
                    """
                    DELETE FROM price_snapshots
                    WHERE scryfall_id = ANY(%s)
                    """,
                    (scryfall_ids,),
                )
                cursor.execute(
                    """
                    DELETE FROM cards
                    WHERE scryfall_id = ANY(%s)
                    """,
                    (scryfall_ids,),
                )
                deleted = cursor.rowcount
            self.connection.commit()
            return int(deleted or 0)
        except Exception:
            self.connection.rollback()
            raise

    def delete_tracked_cards(self, entry_ids: list[str]) -> int:
        if not entry_ids:
            return 0
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT COUNT(DISTINCT entry_id) AS deleted
                    FROM price_snapshots
                    WHERE entry_id = ANY(%s)
                    """,
                    (entry_ids,),
                )
                rows = cursor.fetchall()
                deleted = int(dict(rows[0])["deleted"]) if rows else 0
                cursor.execute(
                    """
                    DELETE FROM price_snapshots
                    WHERE entry_id = ANY(%s)
                    """,
                    (entry_ids,),
                )
                cursor.execute(
                    """
                    DELETE FROM cards c
                    WHERE NOT EXISTS (
                        SELECT 1
                        FROM price_snapshots ps
                        WHERE ps.scryfall_id = c.scryfall_id
                    )
                    """,
                )
            self.connection.commit()
            return deleted
        except Exception:
            self.connection.rollback()
            raise

    def history_rows(self) -> dict[str, list[HistoryPoint]]:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    ps.entry_id,
                    ps.captured_at,
                    ps.price,
                    ps.currency
                FROM price_snapshots ps
                JOIN cards c ON c.scryfall_id = ps.scryfall_id
                ORDER BY c.name COLLATE "C", c.set_code COLLATE "C", c.collector_number COLLATE "C", ps.condition COLLATE "C", ps.language COLLATE "C", ps.captured_at ASC, ps.id ASC
                """
            )
            history: dict[str, list[HistoryPoint]] = {}
            for row in cursor.fetchall():
                values = dict(row)
                history.setdefault(values["entry_id"], []).append(
                    HistoryPoint(
                        captured_at=values["captured_at"],
                        price=decimal_or_none(values["price"]),
                        currency=values["currency"],
                    )
                )
        self.connection.commit()
        return history

    def stale_tracked_cards(self, older_than: datetime) -> list[TrackedCard]:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                WITH latest AS (
                    SELECT DISTINCT ON (entry_id)
                        entry_id, scryfall_id, tracked_name, quantity, condition, language, currency, captured_at
                    FROM price_snapshots
                    ORDER BY entry_id, captured_at DESC, id DESC
                )
                SELECT
                    latest.entry_id AS id,
                    c.scryfall_id,
                    c.name,
                    c.set_code,
                    c.collector_number,
                    latest.tracked_name,
                    latest.quantity,
                    latest.condition,
                    latest.language,
                    latest.currency,
                    latest.captured_at AS latest_captured_at
                FROM latest
                JOIN cards c ON c.scryfall_id = latest.scryfall_id
                WHERE latest.captured_at < %s
                ORDER BY latest.captured_at ASC, c.name COLLATE "C"
                """,
                (older_than,),
            )
            rows = [row_to_tracked_card(row) for row in cursor.fetchall()]
        self.connection.commit()
        return rows

    def tracked_cards(self) -> list[TrackedCard]:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                WITH latest AS (
                    SELECT DISTINCT ON (entry_id)
                        entry_id, scryfall_id, tracked_name, quantity, condition, language, currency, captured_at
                    FROM price_snapshots
                    ORDER BY entry_id, captured_at DESC, id DESC
                )
                SELECT
                    latest.entry_id AS id,
                    c.scryfall_id,
                    c.name,
                    c.set_code,
                    c.collector_number,
                    latest.tracked_name,
                    latest.quantity,
                    latest.condition,
                    latest.language,
                    latest.currency,
                    latest.captured_at AS latest_captured_at
                FROM latest
                JOIN cards c ON c.scryfall_id = latest.scryfall_id
                ORDER BY c.name COLLATE "C", c.set_code COLLATE "C", c.collector_number COLLATE "C"
                """
            )
            rows = [row_to_tracked_card(row) for row in cursor.fetchall()]
        self.connection.commit()
        return rows

    def _initialize_schema(self) -> None:
        try:
            with self.connection.cursor() as cursor:
                for statement in schema_statements():
                    cursor.execute(statement)
                cursor.execute("ALTER TABLE cards ADD COLUMN IF NOT EXISTS image_url TEXT")
                cursor.execute("ALTER TABLE cards ADD COLUMN IF NOT EXISTS image_content_type TEXT")
                cursor.execute("ALTER TABLE cards ADD COLUMN IF NOT EXISTS image_data BYTEA")
                cursor.execute("ALTER TABLE price_snapshots ADD COLUMN IF NOT EXISTS entry_id TEXT")
                cursor.execute("UPDATE price_snapshots SET entry_id = id::text WHERE entry_id IS NULL")
                cursor.execute("ALTER TABLE price_snapshots ALTER COLUMN entry_id SET NOT NULL")
                cursor.execute("ALTER TABLE price_snapshots ADD COLUMN IF NOT EXISTS condition TEXT NOT NULL DEFAULT 'NM'")
                cursor.execute("ALTER TABLE price_snapshots ADD COLUMN IF NOT EXISTS language TEXT NOT NULL DEFAULT 'English'")
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
        id=values["id"],
        scryfall_id=values["scryfall_id"],
        name=values["name"],
        set_code=values["set_code"],
        collector_number=values["collector_number"],
        source_url=values["source_url"],
        has_cached_image=bool(values.get("has_cached_image")),
        has_image_url=bool(values.get("has_image_url")),
        quantity=values["quantity"],
        condition=values["condition"],
        language=values["language"],
        currency=values["currency"],
        latest_price=decimal_or_none(values["latest_price"]),
        latest_captured_at=values["latest_captured_at"],
        first_price=decimal_or_none(values["first_price"]),
        first_captured_at=values["first_captured_at"],
    )


def row_to_tracked_card(row: Any) -> TrackedCard:
    values = dict(row)
    return TrackedCard(
        id=values["id"],
        scryfall_id=values["scryfall_id"],
        request=CardRequest(
            quantity=values["quantity"],
            name=values["tracked_name"] or values["name"],
            set_code=values["set_code"],
            collector_number=values["collector_number"],
            condition=values["condition"],
            language=values["language"],
        ),
        currency=values["currency"].lower(),
        latest_captured_at=values["latest_captured_at"],
    )


def schema_statements() -> list[str]:
    return [statement.strip() for statement in SCHEMA.split(";") if statement.strip()]


def decimal_or_none(value: Any) -> Decimal | None:
    return Decimal(str(value)) if value is not None else None
