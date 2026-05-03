from __future__ import annotations

import threading
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from .config import DEFAULT_REFRESH_INTERVAL_SECONDS
from .importer import import_cards
from .logs import log
from .scryfall import ScryfallClient
from .storage import CollectionStats, PriceStore, TrackedCard


@dataclass
class RefreshStatus:
    running: bool = False
    last_started_at: datetime | None = None
    last_finished_at: datetime | None = None
    next_run_at: datetime | None = None
    total: int = 0
    processed: int = 0
    refreshed: int = 0
    failed: int = 0
    error: str | None = None


RefreshProgressCallback = Callable[[dict[str, int]], None]


class PriceRefreshScheduler:
    def __init__(
        self,
        database_url: str | None,
        interval_seconds: int = DEFAULT_REFRESH_INTERVAL_SECONDS,
    ) -> None:
        self.database_url = database_url
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._refresh_thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._status = RefreshStatus(next_run_at=datetime.now(timezone.utc))

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="price-refresh", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        if self._refresh_thread is not None:
            self._refresh_thread.join(timeout=5.0)

    def status(self) -> dict[str, Any]:
        with self._lock:
            return refresh_status_payload(self._status, self.interval_seconds)

    def refresh_now(self) -> tuple[bool, dict[str, Any]]:
        with self._lock:
            if self._status.running:
                return False, refresh_status_payload(self._status, self.interval_seconds)
            self._status.running = True
            self._status.last_started_at = datetime.now(timezone.utc)
            self._status.error = None
            self._status.next_run_at = None
            self._status.total = 0
            self._status.processed = 0
            self._status.refreshed = 0
            self._status.failed = 0
            payload = refresh_status_payload(self._status, self.interval_seconds)

        self._refresh_thread = threading.Thread(target=self._run_refresh, args=(True,), name="price-refresh-now", daemon=True)
        self._refresh_thread.start()
        return True, payload

    def _run(self) -> None:
        while not self._stop.is_set():
            self._run_refresh(force=False)
            self._stop.wait(self.interval_seconds)

    def _run_refresh(self, force: bool) -> None:
        with self._lock:
            if self._status.running and self._status.last_started_at is not None and not force:
                return
            if not self._status.running:
                self._status.running = True
                self._status.last_started_at = datetime.now(timezone.utc)
                self._status.error = None
                self._status.next_run_at = None
                self._status.total = 0
                self._status.processed = 0
                self._status.refreshed = 0
                self._status.failed = 0

        refreshed = 0
        error = None
        mode = "manual" if force else "scheduled"
        log(f"PRICE REFRESH STARTED mode={mode}")
        try:
            refreshed = refresh_prices(
                self.database_url,
                self.interval_seconds,
                force=force,
                progress=self._update_progress,
            )
        except Exception as exc:
            error = str(exc)
            log(f"PRICE REFRESH FAILED mode={mode}: {exc}", level="ERROR")
        finished_at = datetime.now(timezone.utc)
        with self._lock:
            total = self._status.total
            processed = self._status.processed
            failed = self._status.failed
            self._status.running = False
            self._status.last_finished_at = finished_at
            self._status.next_run_at = finished_at + timedelta(seconds=self.interval_seconds)
            self._status.refreshed = refreshed
            self._status.error = error
        status = "failed" if error is not None else "ok"
        level = "ERROR" if error is not None else "INFO"
        collection_stats = refresh_collection_stats_log(self.database_url)
        log(
            f"PRICE REFRESH COMPLETED mode={mode} status={status} total={total} processed={processed} "
            f"refreshed={refreshed} failed={failed} {collection_stats}",
            level=level,
        )

    def _update_progress(self, progress: dict[str, int]) -> None:
        with self._lock:
            self._status.total = progress["total"]
            self._status.processed = progress["processed"]
            self._status.refreshed = progress["refreshed"]
            self._status.failed = progress["failed"]


def refresh_stale_prices(database_url: str | None, stale_after_seconds: int = DEFAULT_REFRESH_INTERVAL_SECONDS) -> int:
    return refresh_prices(database_url, stale_after_seconds, force=False)


def refresh_prices(
    database_url: str | None,
    stale_after_seconds: int = DEFAULT_REFRESH_INTERVAL_SECONDS,
    force: bool = False,
    progress: RefreshProgressCallback | None = None,
) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=stale_after_seconds)
    store = PriceStore(database_url, initialize_schema=False)
    try:
        cards = store.tracked_cards() if force else store.stale_tracked_cards(cutoff)
        if not cards:
            report_refresh_progress(progress, total=0, processed=0, refreshed=0, failed=0)
            return 0
        return refresh_cards(store, cards, progress=progress)
    finally:
        store.close()


def refresh_cards(
    store: PriceStore,
    tracked_cards: list[TrackedCard],
    progress: RefreshProgressCallback | None = None,
) -> int:
    refreshed = 0
    processed = 0
    failed = 0
    total = len(tracked_cards)
    scryfall = ScryfallClient()
    by_currency: dict[str, list[TrackedCard]] = defaultdict(list)
    for tracked in tracked_cards:
        by_currency[tracked.currency].append(tracked)

    report_refresh_progress(progress, total=total, processed=processed, refreshed=refreshed, failed=failed)
    for currency, cards in by_currency.items():
        pairs = [(tracked.request, tracked.scryfall_id) for tracked in cards]
        results = scryfall.fetch_card_prices_by_id(pairs, currency)
        by_request = {id(request): (price, error) for request, price, error in results}

        def log_import_progress(update: dict) -> None:
            failures = [asdict(failure) for failure in update["failures"]]
            if failures:
                log(f"PRICE REFRESH PROGRESS {update['processed']}/{update['started']}: {failures[-1]}", level="WARNING")

        # Save through the normal importer path when the batch lookup had to fall back
        # to per-card behavior; otherwise persist the already-fetched prices directly.
        if len(results) != len(cards):
            def import_progress(update: dict[str, Any]) -> None:
                report_refresh_progress(
                    progress,
                    total=total,
                    processed=processed + update["processed"],
                    refreshed=refreshed + update["imported"],
                    failed=failed + len(update["failures"]),
                )

            result = import_cards(
                [tracked.request for tracked in cards],
                store,
                currency,
                client=scryfall,
                progress=lambda update: (log_import_progress(update), import_progress(update)),
            )
            refreshed += result.imported
            processed += result.processed
            failed += len(result.failures)
            report_refresh_progress(progress, total=total, processed=processed, refreshed=refreshed, failed=failed)
            continue

        for tracked in cards:
            price, error = by_request.get(id(tracked.request), (None, RuntimeError("card not refreshed")))
            processed += 1
            if error is not None or price is None:
                log(f"PRICE REFRESH FAILED {tracked.request.name}: {error or 'card not found'}", level="ERROR")
                failed += 1
                report_refresh_progress(progress, total=total, processed=processed, refreshed=refreshed, failed=failed)
                continue
            store.save_snapshot(tracked.request, price, entry_id=tracked.id)
            refreshed += 1
            report_refresh_progress(progress, total=total, processed=processed, refreshed=refreshed, failed=failed)

    return refreshed


def report_refresh_progress(
    progress: RefreshProgressCallback | None,
    *,
    total: int,
    processed: int,
    refreshed: int,
    failed: int,
) -> None:
    if progress:
        progress({"total": total, "processed": processed, "refreshed": refreshed, "failed": failed})


def iso_or_none(value: datetime | None) -> str | None:
    return value.isoformat(timespec="seconds") if value is not None else None


def refresh_status_payload(status: RefreshStatus, interval_seconds: int) -> dict[str, Any]:
    return {
        "running": status.running,
        "last_started_at": iso_or_none(status.last_started_at),
        "last_finished_at": iso_or_none(status.last_finished_at),
        "next_run_at": iso_or_none(status.next_run_at),
        "total": status.total,
        "processed": status.processed,
        "refreshed": status.refreshed,
        "failed": status.failed,
        "error": status.error,
        "interval_seconds": interval_seconds,
    }


def refresh_collection_stats_log(database_url: str | None) -> str:
    try:
        store = PriceStore(database_url, initialize_schema=False)
        try:
            return format_collection_stats(store.collection_stats())
        finally:
            store.close()
    except Exception as exc:
        return f"collection_stats_error={exc}"


def format_collection_stats(stats: CollectionStats) -> str:
    return f"cards={stats.cards} tracked_entries={stats.tracked_entries} snapshots={stats.snapshots}"
