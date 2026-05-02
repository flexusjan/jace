from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict
from dataclasses import dataclass, field
from decimal import Decimal
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

from . import APP_USER_AGENT
from .config import SUPPORTED_CURRENCIES, app_config
from .importer import ImportResult, import_cards
from .models import CardRequest
from .moxfield import MoxfieldClient, MoxfieldError
from .parser import parse_card_csv, parse_card_text
from .refresher import PriceRefreshScheduler
from .scryfall import ScryfallError
from .storage import HistoryPoint, PriceStore, ReportRow

STATIC_DIR = Path(__file__).with_name("static")


class PriceTrackerHandler(BaseHTTPRequestHandler):
    store: PriceStore
    jobs: ImportJobs
    refresher: PriceRefreshScheduler

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            self._send_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
            return
        if path == "/app.css":
            self._send_file(STATIC_DIR / "app.css", "text/css; charset=utf-8")
            return
        if path == "/app.js":
            self._send_file(STATIC_DIR / "app.js", "application/javascript; charset=utf-8")
            return
        if path == "/api/cards":
            self._send_json(cards_payload(self.store.latest_rows()))
            return
        if path.startswith("/api/cards/") and path.endswith("/history"):
            entry_id = unquote(path.removeprefix("/api/cards/").removesuffix("/history"))
            self._send_json(card_history_payload(self.store.history_rows_for_entry(entry_id)))
            return
        if path == "/api/refresh-status":
            self._send_json(self.refresher.status())
            return
        if path.startswith("/api/import-jobs/"):
            self._send_json(self.jobs.payload(path.removeprefix("/api/import-jobs/")))
            return
        if path.startswith("/api/card-images/"):
            self._handle_card_image(unquote(path.removeprefix("/api/card-images/")))
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/import":
            self._handle_import()
            return
        if path == "/api/refresh":
            started, payload = self.refresher.refresh_now()
            self._send_json(payload, HTTPStatus.ACCEPTED if started else HTTPStatus.CONFLICT)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_DELETE(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/cards":
            self._handle_delete_cards()
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"{self.address_string()} - {format % args}")

    def _handle_import(self) -> None:
        try:
            payload = self._read_json_body()
            requests = import_requests_from_payload(payload)
            if not requests:
                self._send_json({"error": "No cards found in import input"}, HTTPStatus.BAD_REQUEST)
                return
            currency = str(payload.get("currency") or app_config().default_currency).lower()
            if currency not in SUPPORTED_CURRENCIES:
                self._send_json({"error": "Currency must be eur, usd, or tix"}, HTTPStatus.BAD_REQUEST)
                return
            job = self.jobs.create(requests, currency, self.store.database_url)
        except json.JSONDecodeError as exc:
            self._send_json({"error": f"Invalid JSON: {exc.msg}"}, HTTPStatus.BAD_REQUEST)
            return
        except (ValueError, MoxfieldError, ScryfallError) as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return

        self._send_json(job, HTTPStatus.ACCEPTED)

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0:
            raise ValueError("Request body is required")
        body = self.rfile.read(length).decode("utf-8")
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise ValueError("JSON object is required")
        return payload

    def _handle_delete_cards(self) -> None:
        try:
            payload = self._read_json_body()
            raw_ids = payload.get("tracking_ids")
            if raw_ids is not None:
                if not isinstance(raw_ids, list):
                    self._send_json({"error": "tracking_ids must be a list"}, HTTPStatus.BAD_REQUEST)
                    return
                tracking_ids = [str(value).strip() for value in raw_ids if str(value).strip()]
                if not tracking_ids:
                    self._send_json({"error": "No cards selected"}, HTTPStatus.BAD_REQUEST)
                    return
                deleted = self.store.delete_tracked_cards(tracking_ids)
                self._send_json({"deleted": deleted})
                return

            raw_ids = payload.get("scryfall_ids")
            if not isinstance(raw_ids, list):
                self._send_json({"error": "scryfall_ids must be a list"}, HTTPStatus.BAD_REQUEST)
                return
            scryfall_ids = [str(value).strip() for value in raw_ids if str(value).strip()]
            if not scryfall_ids:
                self._send_json({"error": "No cards selected"}, HTTPStatus.BAD_REQUEST)
                return
            deleted = self.store.delete_cards(scryfall_ids)
        except json.JSONDecodeError as exc:
            self._send_json({"error": f"Invalid JSON: {exc.msg}"}, HTTPStatus.BAD_REQUEST)
            return
        except ValueError as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return

        self._send_json({"deleted": deleted})

    def _handle_card_image(self, scryfall_id: str) -> None:
        if not scryfall_id:
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        image = self.store.image_info(scryfall_id)
        if image is None:
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        data = image.get("image_data")
        content_type = image.get("image_content_type") or "image/jpeg"
        if data is None:
            image_url = image.get("image_url")
            if not image_url:
                self.send_error(HTTPStatus.NOT_FOUND, "No image available for this card")
                return
            try:
                content_type, data = fetch_image(image_url)
            except ImageFetchError as exc:
                self.send_error(HTTPStatus.BAD_GATEWAY, str(exc))
                return
            self.store.save_image(scryfall_id, content_type, data)

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_file(self, path: Path, content_type: str) -> None:
        body = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, default=json_default).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve(host: str, port: int, database_url: str | None) -> int:
    config = app_config()
    store = PriceStore(database_url)
    jobs = ImportJobs()
    refresher = PriceRefreshScheduler(store.database_url, interval_seconds=config.refresh_interval_seconds)
    refresher.start()
    handler = type("ConfiguredPriceTrackerHandler", (PriceTrackerHandler,), {"store": store, "jobs": jobs, "refresher": refresher})
    server = ThreadingHTTPServer((host, port), handler)
    print(f"Serving MTG price tracker on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        refresher.stop()
        server.server_close()
        store.close()
    return 0


def cards_payload(rows: list[ReportRow], history: dict[str, list[HistoryPoint]] | None = None) -> dict[str, Any]:
    return {
        "cards": [
            {
                **asdict(row),
                "latest_price": decimal_to_string(row.latest_price),
                "first_price": decimal_to_string(row.first_price),
                "change": decimal_to_string(price_change(row)),
                "latest_captured_at": row.latest_captured_at.isoformat(timespec="seconds"),
                "first_captured_at": row.first_captured_at.isoformat(timespec="seconds"),
                **(
                    {
                        "history": [
                            {
                                "captured_at": point.captured_at.isoformat(timespec="seconds"),
                                "price": decimal_to_string(point.price),
                                "currency": point.currency,
                            }
                            for point in history.get(row.id, [])
                        ]
                    }
                    if history is not None
                    else {}
                ),
            }
            for row in rows
        ]
    }


def card_history_payload(history: list[HistoryPoint]) -> dict[str, Any]:
    return {
        "history": [
            {
                "captured_at": point.captured_at.isoformat(timespec="seconds"),
                "price": decimal_to_string(point.price),
                "currency": point.currency,
            }
            for point in history
        ]
    }


def import_requests_from_payload(payload: dict[str, Any]) -> list[CardRequest]:
    source = str(payload.get("source") or "text")
    if source == "moxfield":
        url = str(payload.get("url") or "").strip()
        if not url:
            raise ValueError("Moxfield URL is required")
        return MoxfieldClient().fetch_deck_cards(url)

    if source == "csv":
        text = str(payload.get("text") or "").strip()
        if not text:
            raise ValueError("CSV content is required")
        return parse_card_csv(text, source="frontend")

    if source != "text":
        raise ValueError("Import source must be text, csv, or moxfield")

    text = str(payload.get("text") or "").strip()
    if not text:
        raise ValueError("Card text is required")
    return parse_card_text(text, source="frontend")


def import_payload(result: ImportResult) -> dict[str, Any]:
    return {
        "total": result.total,
        "processed": result.processed,
        "imported": result.imported,
        "failed": len(result.failures),
        "failures": [asdict(failure) for failure in result.failures],
    }


@dataclass
class ImportJob:
    id: str
    total: int
    currency: str
    status: str = "queued"
    started: int = 0
    processed: int = 0
    imported: int = 0
    current_card: str | None = None
    failures: list[dict[str, str]] = field(default_factory=list)
    error: str | None = None


class ImportJobs:
    def __init__(self) -> None:
        self._jobs: dict[str, ImportJob] = {}
        self._lock = threading.Lock()

    def create(self, requests: list[CardRequest], currency: str, database_url: str | None) -> dict[str, Any]:
        job = ImportJob(id=uuid.uuid4().hex, total=len(requests), currency=currency)
        with self._lock:
            self._jobs[job.id] = job
        thread = threading.Thread(target=self._run, args=(job.id, requests, currency, database_url), daemon=True)
        thread.start()
        return self.payload(job.id)

    def payload(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return {"error": "Import job not found"}
            return asdict(job) | {"failed": len(job.failures)}

    def _run(self, job_id: str, requests: list[CardRequest], currency: str, database_url: str | None) -> None:
        self._update(job_id, status="running")
        store: PriceStore | None = None
        try:
            store = PriceStore(database_url, initialize_schema=False)
            result = import_cards(
                requests,
                store,
                currency,
                progress=lambda progress: self._update(
                    job_id,
                    started=progress["started"],
                    processed=progress["processed"],
                    imported=progress["imported"],
                    current_card=progress["current_card"],
                    failures=[asdict(failure) for failure in progress["failures"]],
                ),
            )
            self._update(
                job_id,
                status="done",
                started=result.processed,
                processed=result.processed,
                imported=result.imported,
                current_card=None,
                failures=[asdict(failure) for failure in result.failures],
            )
        except Exception as exc:
            print(f"IMPORT JOB FAILED {job_id}: {exc}")
            self._update(job_id, status="error", error=str(exc))
        finally:
            if store is not None:
                store.close()

    def _update(self, job_id: str, **changes: Any) -> None:
        with self._lock:
            job = self._jobs[job_id]
            for key, value in changes.items():
                setattr(job, key, value)


class ImageFetchError(RuntimeError):
    pass


def fetch_image(url: str) -> tuple[str, bytes]:
    config = app_config()
    request = Request(url, headers={"User-Agent": APP_USER_AGENT, "Accept": "image/*"})
    try:
        with urlopen(request, timeout=config.image_fetch_timeout_seconds) as response:
            content_type = response.headers.get_content_type() or "image/jpeg"
            return content_type, response.read()
    except HTTPError as exc:
        raise ImageFetchError(f"Scryfall image returned HTTP {exc.code}") from exc
    except URLError as exc:
        raise ImageFetchError(f"Could not fetch Scryfall image: {exc.reason}") from exc


def price_change(row: ReportRow) -> Decimal | None:
    if row.latest_price is None or row.first_price is None:
        return None
    return row.latest_price - row.first_price


def decimal_to_string(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def json_default(value: Any) -> str:
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")
