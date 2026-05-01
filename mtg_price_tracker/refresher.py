from __future__ import annotations

import threading
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from .importer import import_cards
from .scryfall import ScryfallClient
from .storage import PriceStore, TrackedCard


DEFAULT_REFRESH_INTERVAL_SECONDS = 60 * 60


@dataclass
class RefreshStatus:
    running: bool = False
    last_started_at: datetime | None = None
    last_finished_at: datetime | None = None
    next_run_at: datetime | None = None
    refreshed: int = 0
    error: str | None = None


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

        refreshed = 0
        error = None
        try:
            refreshed = refresh_prices(self.database_url, self.interval_seconds, force=force)
        except Exception as exc:
            error = str(exc)
            print(f"PRICE REFRESH FAILED: {exc}")
        finished_at = datetime.now(timezone.utc)
        with self._lock:
            self._status.running = False
            self._status.last_finished_at = finished_at
            self._status.next_run_at = finished_at + timedelta(seconds=self.interval_seconds)
            self._status.refreshed = refreshed
            self._status.error = error


def refresh_stale_prices(database_url: str | None, stale_after_seconds: int = DEFAULT_REFRESH_INTERVAL_SECONDS) -> int:
    return refresh_prices(database_url, stale_after_seconds, force=False)


def refresh_prices(database_url: str | None, stale_after_seconds: int = DEFAULT_REFRESH_INTERVAL_SECONDS, force: bool = False) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=stale_after_seconds)
    store = PriceStore(database_url, initialize_schema=False)
    try:
        cards = store.tracked_cards() if force else store.stale_tracked_cards(cutoff)
        if not cards:
            return 0
        return refresh_cards(store, cards)
    finally:
        store.close()


def refresh_cards(store: PriceStore, tracked_cards: list[TrackedCard]) -> int:
    refreshed = 0
    scryfall = ScryfallClient()
    by_currency: dict[str, list[TrackedCard]] = defaultdict(list)
    for tracked in tracked_cards:
        by_currency[tracked.currency].append(tracked)

    for currency, cards in by_currency.items():
        pairs = [(tracked.request, tracked.scryfall_id) for tracked in cards]
        results = scryfall.fetch_card_prices_by_id(pairs, currency)
        by_request = {id(request): (price, error) for request, price, error in results}

        def progress(update: dict) -> None:
            failures = [asdict(failure) for failure in update["failures"]]
            if failures:
                print(f"PRICE REFRESH PROGRESS {update['processed']}/{update['started']}: {failures[-1]}")

        # Save through the normal importer path when the batch lookup had to fall back
        # to per-card behavior; otherwise persist the already-fetched prices directly.
        if len(results) != len(cards):
            result = import_cards([tracked.request for tracked in cards], store, currency, client=scryfall, progress=progress)
            refreshed += result.imported
            continue

        for tracked in cards:
            price, error = by_request.get(id(tracked.request), (None, RuntimeError("card not refreshed")))
            if error is not None or price is None:
                print(f"PRICE REFRESH FAILED {tracked.request.name}: {error or 'card not found'}")
                continue
            store.save_snapshot(tracked.request, price, entry_id=tracked.id)
            refreshed += 1

    return refreshed


def iso_or_none(value: datetime | None) -> str | None:
    return value.isoformat(timespec="seconds") if value is not None else None


def refresh_status_payload(status: RefreshStatus, interval_seconds: int) -> dict[str, Any]:
    return {
        "running": status.running,
        "last_started_at": iso_or_none(status.last_started_at),
        "last_finished_at": iso_or_none(status.last_finished_at),
        "next_run_at": iso_or_none(status.next_run_at),
        "refreshed": status.refreshed,
        "error": status.error,
        "interval_seconds": interval_seconds,
    }
