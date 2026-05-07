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
    condition TEXT NOT NULL DEFAULT 'Near Mint',
    language TEXT NOT NULL DEFAULT 'English',
    finish TEXT NOT NULL DEFAULT 'Non-Foil',
    currency TEXT NOT NULL,
    price NUMERIC(12, 2),
    captured_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_price_snapshots_card_time
ON price_snapshots(scryfall_id, captured_at);

CREATE INDEX IF NOT EXISTS idx_price_snapshots_entry_time
ON price_snapshots(entry_id, captured_at);

CREATE INDEX IF NOT EXISTS idx_price_snapshots_entry_latest
ON price_snapshots(entry_id, captured_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_price_snapshots_entry_first
ON price_snapshots(entry_id, captured_at ASC, id ASC);
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
    finish: str
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
class HistoryPage:
    rows: list[HistoryPoint]
    total_count: int


@dataclass(frozen=True)
class ValueHistoryPoint:
    captured_at: datetime
    total_value: Decimal | None
    currency: str | None


@dataclass(frozen=True)
class ReportPage:
    rows: list[ReportRow]
    total_count: int
    total_value: Decimal | None
    currency: str | None


@dataclass(frozen=True)
class TrackedCard:
    id: str
    scryfall_id: str
    request: CardRequest
    currency: str
    latest_captured_at: datetime


@dataclass(frozen=True)
class CollectionStats:
    cards: int
    tracked_entries: int
    snapshots: int


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
                    INSERT INTO price_snapshots (entry_id, scryfall_id, tracked_name, quantity, condition, language, finish, currency, price, captured_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        snapshot_entry_id,
                        price.scryfall_id,
                        request.name,
                        request.quantity,
                        request.condition,
                        request.language,
                        request.finish,
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

    def latest_rows(
        self,
        *,
        limit: int | None = None,
        offset: int = 0,
        search: str = "",
        sort: str = "name",
        direction: str = "asc",
    ) -> list[ReportRow]:
        return self.latest_page(limit=limit, offset=offset, search=search, sort=sort, direction=direction).rows

    def latest_page(
        self,
        *,
        limit: int | None = None,
        offset: int = 0,
        search: str = "",
        sort: str = "name",
        direction: str = "asc",
    ) -> ReportPage:
        order_by = report_page_order_by(sort, direction)
        filter_sql = ""
        parameters: list[Any] = []
        if search:
            filter_sql = """
                WHERE c.name ILIKE %s
                   OR c.set_code ILIKE %s
                   OR c.collector_number ILIKE %s
            """
            pattern = f"%{search}%"
            parameters.extend([pattern, pattern, pattern])
        page_sql = ""
        if limit is not None:
            page_sql = "LIMIT %s OFFSET %s"
            parameters.extend([limit, max(offset, 0)])
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    WITH bounds AS (
                        SELECT entry_id, MIN(id) AS first_id, MAX(id) AS latest_id
                        FROM price_snapshots
                        GROUP BY entry_id
                    ),
                    filtered AS (
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
                            latest.finish,
                            latest.currency,
                            latest.price AS latest_price,
                            latest.captured_at AS latest_captured_at,
                            first.price AS first_price,
                            first.captured_at AS first_captured_at,
                            latest.price * latest.quantity AS total_price_sort,
                            latest.price - first.price AS change_sort
                        FROM bounds
                        JOIN price_snapshots latest ON latest.id = bounds.latest_id
                        JOIN price_snapshots first ON first.id = bounds.first_id
                        JOIN cards c ON c.scryfall_id = latest.scryfall_id
                        {filter_sql}
                    ),
                    summary AS (
                        SELECT
                            COUNT(*) AS summary_total_count,
                            SUM(latest_price * quantity) AS summary_total_value,
                            CASE WHEN COUNT(DISTINCT currency) = 1 THEN MIN(currency) ELSE NULL END AS summary_currency
                        FROM filtered
                    ),
                    page AS (
                        SELECT *
                        FROM filtered
                        ORDER BY {order_by}
                        {page_sql}
                    )
                    SELECT page.*, summary.summary_total_count, summary.summary_total_value, summary.summary_currency
                    FROM summary
                    LEFT JOIN page ON TRUE
                    """,
                    parameters,
                )
                result_rows = [dict(row) for row in cursor.fetchall()]
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        summary = result_rows[0] if result_rows else {}
        return ReportPage(
            rows=[row_to_report(row) for row in result_rows if row.get("id") is not None],
            total_count=int(summary.get("summary_total_count") or 0),
            total_value=decimal_or_none(summary.get("summary_total_value")),
            currency=summary.get("summary_currency"),
        )

    def collection_stats(self) -> CollectionStats:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM cards) AS cards,
                    (SELECT COUNT(DISTINCT entry_id) FROM price_snapshots) AS tracked_entries,
                    (SELECT COUNT(*) FROM price_snapshots) AS snapshots
                """
            )
            rows = cursor.fetchall()
        self.connection.commit()
        values = dict(rows[0]) if rows else {}
        return CollectionStats(
            cards=int(values.get("cards") or 0),
            tracked_entries=int(values.get("tracked_entries") or 0),
            snapshots=int(values.get("snapshots") or 0),
        )

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

    def history_rows_for_entry(self, entry_id: str) -> list[HistoryPoint]:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT captured_at, price, currency
                FROM price_snapshots
                WHERE entry_id = %s
                ORDER BY captured_at ASC, id ASC
                """,
                (entry_id,),
            )
            rows = [
                HistoryPoint(
                    captured_at=values["captured_at"],
                    price=decimal_or_none(values["price"]),
                    currency=values["currency"],
                )
                for values in (dict(row) for row in cursor.fetchall())
            ]
        self.connection.commit()
        return rows

    def history_page_for_entry(self, entry_id: str, *, limit: int | None = None, offset: int = 0) -> HistoryPage:
        parameters: list[Any] = [entry_id]
        page_sql = ""
        if limit is not None:
            page_sql = "LIMIT %s OFFSET %s"
            parameters.extend([limit, max(offset, 0)])
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*) AS total_count
                FROM price_snapshots
                WHERE entry_id = %s
                """,
                (entry_id,),
            )
            summary_rows = cursor.fetchall()
            cursor.execute(
                f"""
                WITH selected AS (
                    SELECT captured_at, price, currency, id
                    FROM price_snapshots
                    WHERE entry_id = %s
                    ORDER BY captured_at DESC, id DESC
                    {page_sql}
                )
                SELECT captured_at, price, currency
                FROM selected
                ORDER BY captured_at ASC, id ASC
                """,
                parameters,
            )
            rows = [
                HistoryPoint(
                    captured_at=values["captured_at"],
                    price=decimal_or_none(values["price"]),
                    currency=values["currency"],
                )
                for values in (dict(row) for row in cursor.fetchall())
            ]
        self.connection.commit()
        summary = dict(summary_rows[0]) if summary_rows else {}
        return HistoryPage(rows=rows, total_count=int(summary.get("total_count") or len(rows)))

    def value_history_rows(self) -> list[ValueHistoryPoint]:
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(
                    """
                    WITH bounds AS (
                        SELECT entry_id, MIN(id) AS first_id, MAX(id) AS latest_id
                        FROM price_snapshots
                        GROUP BY entry_id
                    ),
                    pairs AS (
                        SELECT
                            first.captured_at AS first_captured_at,
                            first.quantity AS first_quantity,
                            first.currency AS first_currency,
                            first.price AS first_price,
                            latest.captured_at AS latest_captured_at,
                            latest.quantity AS latest_quantity,
                            latest.currency AS latest_currency,
                            latest.price AS latest_price
                        FROM bounds
                        JOIN price_snapshots first ON first.id = bounds.first_id
                        JOIN price_snapshots latest ON latest.id = bounds.latest_id
                    ),
                    value_points AS (
                        SELECT
                            MIN(first_captured_at) AS captured_at,
                            SUM(first_price * first_quantity) AS total_value,
                            CASE WHEN COUNT(DISTINCT first_currency) = 1 THEN MIN(first_currency) ELSE NULL END AS currency
                        FROM pairs
                        UNION
                        SELECT
                            MAX(latest_captured_at) AS captured_at,
                            SUM(latest_price * latest_quantity) AS total_value,
                            CASE WHEN COUNT(DISTINCT latest_currency) = 1 THEN MIN(latest_currency) ELSE NULL END AS currency
                        FROM pairs
                    )
                    SELECT
                        captured_at,
                        total_value,
                        currency
                    FROM value_points
                    WHERE captured_at IS NOT NULL
                    ORDER BY value_points.captured_at ASC
                    """
                )
                rows = [
                    ValueHistoryPoint(
                        captured_at=values["captured_at"],
                        total_value=decimal_or_none(values["total_value"]),
                        currency=values["currency"],
                    )
                    for values in (dict(row) for row in cursor.fetchall())
                ]
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return rows

    def stale_tracked_cards(self, older_than: datetime) -> list[TrackedCard]:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                WITH latest AS (
                    SELECT DISTINCT ON (entry_id)
                        entry_id, scryfall_id, tracked_name, quantity, condition, language, finish, currency, captured_at
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
                    latest.finish,
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
                        entry_id, scryfall_id, tracked_name, quantity, condition, language, finish, currency, captured_at
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
                    latest.finish,
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
                cursor.execute("ALTER TABLE price_snapshots ADD COLUMN IF NOT EXISTS condition TEXT NOT NULL DEFAULT 'Near Mint'")
                cursor.execute("ALTER TABLE price_snapshots ADD COLUMN IF NOT EXISTS language TEXT NOT NULL DEFAULT 'English'")
                cursor.execute("ALTER TABLE price_snapshots ADD COLUMN IF NOT EXISTS finish TEXT NOT NULL DEFAULT 'Non-Foil'")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_price_snapshots_entry_latest ON price_snapshots(entry_id, captured_at DESC, id DESC)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_price_snapshots_entry_first ON price_snapshots(entry_id, captured_at ASC, id ASC)")
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
        finish=values["finish"],
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
            finish=values["finish"],
        ),
        currency=values["currency"].lower(),
        latest_captured_at=values["latest_captured_at"],
    )


def schema_statements() -> list[str]:
    return [statement.strip() for statement in SCHEMA.split(";") if statement.strip()]


def report_page_order_by(sort: str, direction: str) -> str:
    sort_columns = {
        "name": ['name COLLATE "C"'],
        "set": ['set_code COLLATE "C"', 'collector_number COLLATE "C"'],
        "quantity": "quantity",
        "condition": 'condition COLLATE "C"',
        "language": 'language COLLATE "C"',
        "finish": 'finish COLLATE "C"',
        "latest_price": "latest_price",
        "total_price": "total_price_sort",
        "change": "change_sort",
        "latest_captured_at": "latest_captured_at",
    }
    primary = sort_columns.get(sort, sort_columns["name"])
    sql_direction = "DESC" if direction == "desc" else "ASC"
    nulls = "NULLS LAST"
    primary_columns = primary if isinstance(primary, list) else [primary]
    primary_order = ", ".join(f"{column} {sql_direction} {nulls}" for column in primary_columns)
    tie_breaker = 'name COLLATE "C" ASC, set_code COLLATE "C" ASC, collector_number COLLATE "C" ASC, condition COLLATE "C" ASC, language COLLATE "C" ASC, finish COLLATE "C" ASC'
    return f"{primary_order}, {tie_breaker}"


def decimal_or_none(value: Any) -> Decimal | None:
    return Decimal(str(value)) if value is not None else None
