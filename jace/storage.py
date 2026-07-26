from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
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

CREATE TABLE IF NOT EXISTS tracked_entries (
    entry_id TEXT PRIMARY KEY,
    source TEXT NOT NULL DEFAULT 'manual',
    source_key TEXT,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    archived_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS collection_settings (
    id SMALLINT PRIMARY KEY CHECK (id = 1),
    mode TEXT NOT NULL DEFAULT 'manual',
    last_sync_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_price_snapshots_card_time
ON price_snapshots(scryfall_id, captured_at);

CREATE INDEX IF NOT EXISTS idx_price_snapshots_entry_time
ON price_snapshots(entry_id, captured_at);

CREATE INDEX IF NOT EXISTS idx_price_snapshots_entry_latest
ON price_snapshots(entry_id, captured_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_price_snapshots_entry_first
ON price_snapshots(entry_id, captured_at ASC, id ASC);

CREATE INDEX IF NOT EXISTS idx_price_snapshots_entry_id
ON price_snapshots(entry_id, id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_tracked_entries_moxfield_source_key
ON tracked_entries(source_key)
WHERE source = 'moxfield' AND source_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_tracked_entries_active
ON tracked_entries(active, source);
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
    sampled: bool = False


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


@dataclass(frozen=True)
class CollectionMode:
    mode: str
    last_sync_at: datetime | None


@dataclass(frozen=True)
class MoxfieldSyncResult:
    synced: int
    added: int
    updated: int
    reactivated: int
    archived: int


class PriceStore:
    def __init__(
        self,
        database_url: str | None = None,
        connection: Any | None = None,
        initialize_schema: bool = True,
    ) -> None:
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
        timestamp = captured_at or datetime.now(UTC)
        snapshot_entry_id = entry_id or uuid.uuid4().hex
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO tracked_entries (entry_id, source, active)
                    VALUES (%s, 'manual', TRUE)
                    ON CONFLICT (entry_id) DO NOTHING
                    """,
                    (snapshot_entry_id,),
                )
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

    def collection_mode(self) -> CollectionMode:
        with self.connection.cursor() as cursor:
            cursor.execute(
                "SELECT mode, last_sync_at FROM collection_settings WHERE id = 1"
            )
            rows = cursor.fetchall()
        self.connection.commit()
        values = dict(rows[0]) if rows else {"mode": "manual", "last_sync_at": None}
        return CollectionMode(
            mode=values["mode"], last_sync_at=values.get("last_sync_at")
        )

    def set_collection_mode(self, mode: str) -> CollectionMode:
        if mode not in {"manual", "moxfield"}:
            raise ValueError("Collection mode must be manual or moxfield")
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO collection_settings (id, mode)
                    VALUES (1, %s)
                    ON CONFLICT (id) DO UPDATE SET mode = excluded.mode
                    """,
                    (mode,),
                )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return self.collection_mode()

    def apply_moxfield_sync(
        self, resolved_cards: list[tuple[CardRequest, CardPrice]]
    ) -> MoxfieldSyncResult:
        if not resolved_cards:
            raise ValueError("Moxfield sync requires at least one resolved card")

        synced = added = updated = reactivated = 0
        seen_keys: list[str] = []
        timestamp = datetime.now(UTC)
        try:
            with self.connection.cursor() as cursor:
                for request, price in resolved_cards:
                    source_key = moxfield_source_key(price.scryfall_id, request)
                    seen_keys.append(source_key)
                    cursor.execute(
                        """
                        SELECT entry_id, active
                        FROM tracked_entries
                        WHERE source = 'moxfield' AND source_key = %s
                        """,
                        (source_key,),
                    )
                    rows = [dict(row) for row in cursor.fetchall()]
                    entry_id: str
                    if rows:
                        entry_id = rows[0]["entry_id"]
                        if not rows[0]["active"]:
                            reactivated += 1
                        else:
                            updated += 1
                        cursor.execute(
                            """
                            UPDATE tracked_entries
                            SET active = TRUE, archived_at = NULL
                            WHERE entry_id = %s
                            """,
                            (entry_id,),
                        )
                    else:
                        cursor.execute(
                            """
                            SELECT te.entry_id
                            FROM tracked_entries te
                            JOIN LATERAL (
                                SELECT scryfall_id, condition, language, finish
                                FROM price_snapshots
                                WHERE entry_id = te.entry_id
                                ORDER BY captured_at DESC, id DESC
                                LIMIT 1
                            ) latest ON TRUE
                            WHERE te.source = 'manual'
                              AND te.active
                              AND latest.scryfall_id = %s
                              AND latest.condition = %s
                              AND latest.language = %s
                              AND latest.finish = %s
                            ORDER BY te.entry_id
                            LIMIT 1
                            """,
                            (
                                price.scryfall_id,
                                request.condition,
                                request.language,
                                request.finish,
                            ),
                        )
                        manual_rows = [dict(row) for row in cursor.fetchall()]
                        if manual_rows:
                            entry_id = manual_rows[0]["entry_id"]
                            updated += 1
                            cursor.execute(
                                """
                                UPDATE tracked_entries
                                SET source = 'moxfield', source_key = %s, active = TRUE, archived_at = NULL
                                WHERE entry_id = %s
                                """,
                                (source_key, entry_id),
                            )
                        else:
                            entry_id = uuid.uuid4().hex
                            added += 1
                            cursor.execute(
                                """
                                INSERT INTO tracked_entries (entry_id, source, source_key, active)
                                VALUES (%s, 'moxfield', %s, TRUE)
                                """,
                                (entry_id, source_key),
                            )

                    self._save_snapshot_with_cursor(
                        cursor, request, price, timestamp, entry_id
                    )
                    synced += 1

                # The first successful sync makes Moxfield authoritative for the
                # previous manual collection too. Nothing is deleted: manual
                # entries not adopted above are merely archived.
                cursor.execute(
                    "UPDATE tracked_entries SET active = FALSE, archived_at = %s WHERE source = 'manual' AND active",
                    (timestamp,),
                )
                archived = int(cursor.rowcount or 0)
                cursor.execute(
                    """
                    UPDATE tracked_entries
                    SET active = FALSE, archived_at = %s
                    WHERE source = 'moxfield'
                      AND active
                      AND NOT (source_key = ANY(%s))
                    """,
                    (timestamp, seen_keys),
                )
                archived += int(cursor.rowcount or 0)
                cursor.execute(
                    """
                    INSERT INTO collection_settings (id, mode, last_sync_at)
                    VALUES (1, 'moxfield', %s)
                    ON CONFLICT (id) DO UPDATE SET mode = 'moxfield', last_sync_at = excluded.last_sync_at
                    """,
                    (timestamp,),
                )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return MoxfieldSyncResult(synced, added, updated, reactivated, archived)

    def _save_snapshot_with_cursor(
        self,
        cursor: Any,
        request: CardRequest,
        price: CardPrice,
        timestamp: datetime,
        entry_id: str,
    ) -> None:
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
                image_content_type = CASE WHEN excluded.image_url IS DISTINCT FROM cards.image_url THEN NULL ELSE cards.image_content_type END,
                image_data = CASE WHEN excluded.image_url IS DISTINCT FROM cards.image_url THEN NULL ELSE cards.image_data END
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
                entry_id,
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

    def latest_rows(
        self,
        *,
        limit: int | None = None,
        offset: int = 0,
        search: str = "",
        sort: str = "name",
        direction: str = "asc",
    ) -> list[ReportRow]:
        return self.latest_page(
            limit=limit, offset=offset, search=search, sort=sort, direction=direction
        ).rows

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
                        JOIN tracked_entries te ON te.entry_id = latest.entry_id AND te.active
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
            rows=[
                row_to_report(row) for row in result_rows if row.get("id") is not None
            ],
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
                    (SELECT COUNT(*) FROM tracked_entries WHERE active) AS tracked_entries,
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
                    UPDATE tracked_entries te
                    SET active = FALSE, archived_at = %s
                    WHERE te.active
                      AND EXISTS (
                        SELECT 1 FROM price_snapshots ps
                        WHERE ps.entry_id = te.entry_id AND ps.scryfall_id = ANY(%s)
                      )
                    """,
                    (datetime.now(UTC), scryfall_ids),
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
                    FROM tracked_entries
                    WHERE entry_id = ANY(%s) AND active
                    """,
                    (entry_ids,),
                )
                rows = cursor.fetchall()
                deleted = int(dict(rows[0])["deleted"]) if rows else 0
                cursor.execute(
                    """
                    UPDATE tracked_entries
                    SET active = FALSE, archived_at = %s
                    WHERE entry_id = ANY(%s) AND active
                    """,
                    (datetime.now(UTC), entry_ids),
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

    def history_page_for_entry(
        self, entry_id: str, *, limit: int | None = None, offset: int = 0
    ) -> HistoryPage:
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
        return HistoryPage(
            rows=rows, total_count=int(summary.get("total_count") or len(rows))
        )

    def history_sample_for_entry(
        self, entry_id: str, *, max_points: int = 500
    ) -> HistoryPage:
        sample_size = max(max_points, 2)
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                WITH numbered AS (
                    SELECT
                        captured_at,
                        price,
                        currency,
                        id,
                        ROW_NUMBER() OVER (ORDER BY captured_at ASC, id ASC) AS row_number,
                        COUNT(*) OVER () AS total_count
                    FROM price_snapshots
                    WHERE entry_id = %s
                ),
                bucketed AS (
                    SELECT
                        captured_at,
                        price,
                        currency,
                        id,
                        row_number,
                        total_count,
                        CASE
                            WHEN total_count <= %s THEN row_number
                            ELSE FLOOR(((row_number - 1)::numeric * (%s - 2)) / GREATEST(total_count - 2, 1))::integer
                        END AS bucket
                    FROM numbered
                ),
                picked AS (
                    SELECT DISTINCT ON (bucket)
                        captured_at,
                        price,
                        currency,
                        id,
                        total_count
                    FROM bucketed
                    WHERE total_count <= %s OR row_number < total_count
                    ORDER BY bucket, captured_at ASC, id ASC
                ),
                combined AS (
                    SELECT captured_at, price, currency, id, total_count
                    FROM picked
                    UNION
                    SELECT captured_at, price, currency, id, total_count
                    FROM bucketed
                    WHERE total_count > %s AND row_number = total_count
                )
                SELECT captured_at, price, currency, total_count
                FROM combined
                ORDER BY captured_at ASC, id ASC
                """,
                (entry_id, sample_size, sample_size, sample_size, sample_size),
            )
            result_rows = [dict(row) for row in cursor.fetchall()]
            rows = [
                HistoryPoint(
                    captured_at=values["captured_at"],
                    price=decimal_or_none(values["price"]),
                    currency=values["currency"],
                )
                for values in result_rows
            ]
        self.connection.commit()
        total_count = (
            int(result_rows[0].get("total_count") or len(rows)) if result_rows else 0
        )
        return HistoryPage(
            rows=rows, total_count=total_count, sampled=total_count > len(rows)
        )

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
                    JOIN tracked_entries te ON te.entry_id = latest.entry_id AND te.active
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
                JOIN tracked_entries te ON te.entry_id = latest.entry_id AND te.active
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
                JOIN tracked_entries te ON te.entry_id = latest.entry_id AND te.active
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
                cursor.execute(
                    "ALTER TABLE cards ADD COLUMN IF NOT EXISTS image_url TEXT"
                )
                cursor.execute(
                    "ALTER TABLE cards ADD COLUMN IF NOT EXISTS image_content_type TEXT"
                )
                cursor.execute(
                    "ALTER TABLE cards ADD COLUMN IF NOT EXISTS image_data BYTEA"
                )
                cursor.execute(
                    "ALTER TABLE price_snapshots ADD COLUMN IF NOT EXISTS entry_id TEXT"
                )
                cursor.execute(
                    "UPDATE price_snapshots SET entry_id = id::text WHERE entry_id IS NULL"
                )
                cursor.execute(
                    "ALTER TABLE price_snapshots ALTER COLUMN entry_id SET NOT NULL"
                )
                cursor.execute(
                    "ALTER TABLE price_snapshots ADD COLUMN IF NOT EXISTS condition TEXT NOT NULL DEFAULT 'Near Mint'"
                )
                cursor.execute(
                    "ALTER TABLE price_snapshots ADD COLUMN IF NOT EXISTS language TEXT NOT NULL DEFAULT 'English'"
                )
                cursor.execute(
                    "ALTER TABLE price_snapshots ADD COLUMN IF NOT EXISTS finish TEXT NOT NULL DEFAULT 'Non-Foil'"
                )
                cursor.execute(
                    """
                    INSERT INTO tracked_entries (entry_id, source, active)
                    SELECT DISTINCT entry_id, 'manual', TRUE
                    FROM price_snapshots
                    ON CONFLICT (entry_id) DO NOTHING
                    """
                )
                cursor.execute(
                    "INSERT INTO collection_settings (id, mode) VALUES (1, 'manual') ON CONFLICT (id) DO NOTHING"
                )
                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS idx_price_snapshots_entry_latest ON price_snapshots(entry_id, captured_at DESC, id DESC)"
                )
                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS idx_price_snapshots_entry_first ON price_snapshots(entry_id, captured_at ASC, id ASC)"
                )
                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS idx_price_snapshots_entry_id ON price_snapshots(entry_id, id)"
                )
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
            raise RuntimeError(
                "Install the project dependencies to use Postgres storage: psycopg[binary]"
            ) from exc
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
    # Validate sort parameter against whitelist
    primary = sort_columns.get(sort, sort_columns["name"])
    # Validate direction parameter - only allow ASC or DESC
    sql_direction = "DESC" if direction.upper() == "DESC" else "ASC"
    nulls = "NULLS LAST"
    primary_columns = primary if isinstance(primary, list) else [primary]
    primary_order = ", ".join(
        f"{column} {sql_direction} {nulls}" for column in primary_columns
    )
    tie_breaker = 'name COLLATE "C" ASC, set_code COLLATE "C" ASC, collector_number COLLATE "C" ASC, condition COLLATE "C" ASC, language COLLATE "C" ASC, finish COLLATE "C" ASC'
    return f"{primary_order}, {tie_breaker}"


def decimal_or_none(value: Any) -> Decimal | None:
    return Decimal(str(value)) if value is not None else None


def moxfield_source_key(scryfall_id: str, request: CardRequest) -> str:
    """Stable identity for one collection row, independent of its quantity."""
    return f"{scryfall_id}\x1f{request.condition.casefold()}\x1f{request.language.casefold()}\x1f{request.finish.casefold()}"
