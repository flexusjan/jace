from __future__ import annotations

import json
import base64
import binascii
import errno
import hmac
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
from urllib.parse import parse_qs, unquote, urlparse
from urllib.request import Request, urlopen

from . import APP_USER_AGENT
from .config import SUPPORTED_CURRENCIES, app_config
from .importer import ImportResult, import_cards
from .logs import log
from .models import CardRequest
from .moxfield import MoxfieldClient, MoxfieldError
from .parser import parse_card_csv, parse_card_text
from .refresher import PriceRefreshScheduler
from .scryfall import ScryfallError
from .storage import CollectionStats, HistoryPage, HistoryPoint, PriceStore, ReportRow, ValueHistoryPoint

STATIC_DIR = Path(__file__).with_name("static")
ALLOWED_IMAGE_HOST_SUFFIX = ".scryfall.io"
CLIENT_DISCONNECT_ERRORS = (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)
CLIENT_DISCONNECT_ERRNOS = {errno.EPIPE, errno.ECONNRESET, errno.ECONNABORTED}


class PriceTrackerHandler(BaseHTTPRequestHandler):
    store: PriceStore
    jobs: ImportJobs
    refresher: PriceRefreshScheduler

    def end_headers(self) -> None:
        self._send_security_headers()
        super().end_headers()

    def do_GET(self) -> None:
        if not self._authorized():
            self._send_auth_required()
            return
        path = urlparse(self.path).path
        if path == "/":
            self._send_index()
            return
        if path == "/app.css":
            self._send_file(STATIC_DIR / "app.css", "text/css; charset=utf-8")
            return
        if path == "/app.js":
            self._send_file(STATIC_DIR / "app.js", "application/javascript; charset=utf-8")
            return
        if path == "/favicon.svg":
            self._send_file(STATIC_DIR / "favicon.svg", "image/svg+xml")
            return
        if path == "/api/cards":
            params = parse_qs(urlparse(self.path).query)
            page = query_int(params, "page", 1, minimum=1)
            page_size = query_int(params, "page_size", 100, minimum=1, maximum=500)
            sort = query_str(params, "sort", "name")
            direction = query_str(params, "direction", "asc")
            search = query_str(params, "q", "")
            store = self._request_store()
            try:
                report = store.latest_page(
                    limit=page_size,
                    offset=(page - 1) * page_size,
                    search=search,
                    sort=sort,
                    direction=direction,
                )
            finally:
                self._close_request_store(store)
            log(
                "CARDS LISTED "
                f"page={page} page_size={page_size} q={search!r} sort={sort} direction={direction} "
                f"returned={len(report.rows)} total={report.total_count}"
            )
            self._send_json(cards_payload(report.rows, pagination=report_pagination_payload(report, page, page_size)))
            return
        if path.startswith("/api/cards/") and (path.endswith("/history") or path.endswith("/price-history")):
            suffix = "/price-history" if path.endswith("/price-history") else "/history"
            entry_id = unquote(path.removeprefix("/api/cards/").removesuffix(suffix))
            params = parse_qs(urlparse(self.path).query)
            store = self._request_store()
            try:
                if "page" in params or "page_size" in params or suffix == "/price-history":
                    page = query_int(params, "page", 1, minimum=1)
                    page_size = query_int(params, "page_size", 100, minimum=1, maximum=500)
                    history_page = store.history_page_for_entry(entry_id, limit=page_size, offset=(page - 1) * page_size)
                    self._send_json(card_history_payload(history_page.rows, pagination=history_pagination_payload(history_page, page, page_size)))
                else:
                    self._send_json(card_history_payload(store.history_rows_for_entry(entry_id)))
            finally:
                self._close_request_store(store)
            return
        if path in {"/api/value-history", "/api/collection/value-history"}:
            store = self._request_store()
            try:
                self._send_json(value_history_payload(store.value_history_rows()))
            finally:
                self._close_request_store(store)
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
        if not self._authorized():
            self._send_auth_required()
            return
        if not self._valid_mutation_origin():
            self._send_json({"error": "Invalid request origin"}, HTTPStatus.FORBIDDEN)
            return
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
        if not self._authorized():
            self._send_auth_required()
            return
        if not self._valid_mutation_origin():
            self._send_json({"error": "Invalid request origin"}, HTTPStatus.FORBIDDEN)
            return
        path = urlparse(self.path).path
        if path == "/api/cards":
            self._handle_delete_cards()
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def log_message(self, format: str, *args: Any) -> None:
        log(f"{self.address_string()} - {format % args}")

    def _handle_import(self) -> None:
        try:
            payload = self._read_json_body()
            requests = import_requests_from_payload(payload)
            if not requests:
                self._send_json({"error": "No cards found in import input"}, HTTPStatus.BAD_REQUEST)
                return
            max_cards = app_config().max_import_cards
            if len(requests) > max_cards:
                self._send_json({"error": f"Import can contain at most {max_cards} cards"}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
                return
            currency = str(payload.get("currency") or app_config().default_currency).lower()
            if currency not in SUPPORTED_CURRENCIES:
                self._send_json({"error": "Currency must be eur, usd, or tix"}, HTTPStatus.BAD_REQUEST)
                return
            job = self.jobs.create(requests, currency, self.store.database_url)
        except json.JSONDecodeError as exc:
            self._send_json({"error": f"Invalid JSON: {exc.msg}"}, HTTPStatus.BAD_REQUEST)
            return
        except RequestTooLargeError as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return
        except TooManyJobsError as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.TOO_MANY_REQUESTS)
            return
        except (ValueError, MoxfieldError, ScryfallError) as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return

        self._send_json(job, HTTPStatus.ACCEPTED)

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0:
            raise ValueError("Request body is required")
        max_length = app_config().max_request_body_bytes
        if length > max_length:
            raise RequestTooLargeError(f"Request body must be at most {max_length} bytes")
        body = self.rfile.read(length).decode("utf-8")
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise ValueError("JSON object is required")
        return payload

    def _authorized(self) -> bool:
        config = app_config()
        if not config.auth_username or not config.auth_password:
            return True
        credentials = basic_auth_credentials(self.headers.get("Authorization"))
        if credentials is None:
            return False
        username, password = credentials
        return hmac.compare_digest(username, config.auth_username) and hmac.compare_digest(password, config.auth_password)

    def _valid_mutation_origin(self) -> bool:
        config = app_config()
        if not config.auth_username or not config.auth_password:
            return True
        origin = self.headers.get("Origin")
        if origin:
            return request_origin_allowed(origin, self.headers.get("Host"))
        referer = self.headers.get("Referer")
        if referer:
            return request_origin_allowed(referer, self.headers.get("Host"))
        return False

    def _send_security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self'; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "object-src 'none'; "
            "base-uri 'none'; "
            "form-action 'self'; "
            "frame-ancestors 'none'",
        )

    def _send_auth_required(self) -> None:
        body = b"Authentication required\n"
        self._send_response(
            body,
            HTTPStatus.UNAUTHORIZED,
            (
                ("WWW-Authenticate", 'Basic realm="jace", charset="UTF-8"'),
                ("Content-Type", "text/plain; charset=utf-8"),
                ("Cache-Control", "no-store"),
            ),
        )

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
                log(f"CARDS DELETE tracking_ids requested={len(tracking_ids)} deleted={deleted} {collection_stats_log(self.store)}")
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
            log(f"CARDS DELETE scryfall_ids requested={len(scryfall_ids)} deleted={deleted} {collection_stats_log(self.store)}")
        except json.JSONDecodeError as exc:
            self._send_json({"error": f"Invalid JSON: {exc.msg}"}, HTTPStatus.BAD_REQUEST)
            return
        except RequestTooLargeError as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return
        except ValueError as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return

        self._send_json({"deleted": deleted})

    def _handle_card_image(self, scryfall_id: str) -> None:
        if not scryfall_id:
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        store = self._request_store()
        try:
            image = store.image_info(scryfall_id)
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
                store.save_image(scryfall_id, content_type, data)
        finally:
            self._close_request_store(store)

        self._send_response(
            data,
            HTTPStatus.OK,
            (("Content-Type", content_type), ("Cache-Control", "public, max-age=31536000, immutable")),
        )

    def _send_file(self, path: Path, content_type: str) -> None:
        body = path.read_bytes()
        self._send_response(body, HTTPStatus.OK, (("Content-Type", content_type),))

    def _send_index(self) -> None:
        body = rendered_index_html(app_config().dark_theme).encode("utf-8")
        self._send_response(body, HTTPStatus.OK, (("Content-Type", "text/html; charset=utf-8"),))

    def _send_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, default=json_default).encode("utf-8")
        self._send_response(body, status, (("Content-Type", "application/json; charset=utf-8"), ("Cache-Control", "no-store")))

    def _request_store(self) -> PriceStore:
        if self.store.database_url:
            return PriceStore(self.store.database_url, initialize_schema=False)
        return self.store

    def _close_request_store(self, store: PriceStore) -> None:
        if store is not self.store:
            store.close()

    def _send_response(self, body: bytes, status: HTTPStatus, headers: tuple[tuple[str, str], ...]) -> None:
        try:
            self.send_response(status)
            for name, value in headers:
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except OSError as exc:
            if isinstance(exc, CLIENT_DISCONNECT_ERRORS) or exc.errno in CLIENT_DISCONNECT_ERRNOS:
                return
            raise


def serve(host: str, port: int, database_url: str | None) -> int:
    config = app_config()
    store = PriceStore(database_url)
    log(f"COLLECTION STARTUP {collection_stats_log(store)}")
    jobs = ImportJobs()
    refresher = PriceRefreshScheduler(store.database_url, interval_seconds=config.refresh_interval_seconds)
    refresher.start()
    handler = type("ConfiguredPriceTrackerHandler", (PriceTrackerHandler,), {"store": store, "jobs": jobs, "refresher": refresher})
    server = ThreadingHTTPServer((host, port), handler)
    log(f"Serving MTG price tracker on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        refresher.stop()
        server.server_close()
        store.close()
    return 0


def rendered_index_html(dark_theme: bool) -> str:
    theme = "dark" if dark_theme else "light"
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8").replace('data-theme="dark"', f'data-theme="{theme}"')


def cards_payload(
    rows: list[ReportRow],
    history: dict[str, list[HistoryPoint]] | None = None,
    pagination: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
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
    if pagination is not None:
        payload["pagination"] = pagination
    return payload


def report_pagination_payload(report: Any, page: int, page_size: int) -> dict[str, Any]:
    total_pages = max(1, (report.total_count + page_size - 1) // page_size)
    return {
        "page": min(page, total_pages),
        "page_size": page_size,
        "total_count": report.total_count,
        "total_pages": total_pages,
        "total_value": decimal_to_string(report.total_value),
        "currency": report.currency,
    }


def history_pagination_payload(history_page: HistoryPage, page: int, page_size: int) -> dict[str, Any]:
    total_pages = max(1, (history_page.total_count + page_size - 1) // page_size)
    return {
        "page": min(page, total_pages),
        "page_size": page_size,
        "total_count": history_page.total_count,
        "total_pages": total_pages,
    }


def query_str(params: dict[str, list[str]], name: str, default: str) -> str:
    values = params.get(name)
    return values[0].strip() if values and values[0].strip() else default


def query_int(params: dict[str, list[str]], name: str, default: int, *, minimum: int, maximum: int | None = None) -> int:
    values = params.get(name)
    if not values:
        return default
    try:
        value = int(values[0])
    except ValueError:
        return default
    if value < minimum:
        return minimum
    if maximum is not None and value > maximum:
        return maximum
    return value


def card_history_payload(history: list[HistoryPoint], pagination: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {
        "history": [
            {
                "captured_at": point.captured_at.isoformat(timespec="seconds"),
                "price": decimal_to_string(point.price),
                "currency": point.currency,
            }
            for point in history
        ]
    }
    if pagination is not None:
        payload["pagination"] = pagination
    return payload


def value_history_payload(history: list[ValueHistoryPoint]) -> dict[str, Any]:
    return {
        "history": [
            {
                "captured_at": point.captured_at.isoformat(timespec="seconds"),
                "total_value": decimal_to_string(point.total_value),
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


def basic_auth_credentials(header: str | None) -> tuple[str, str] | None:
    if not header:
        return None
    scheme, _, encoded = header.partition(" ")
    if scheme.lower() != "basic" or not encoded.strip():
        return None
    try:
        decoded = base64.b64decode(encoded.strip(), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return None
    username, separator, password = decoded.partition(":")
    if not separator:
        return None
    return username, password


def request_origin_allowed(value: str, host: str | None) -> bool:
    if not host:
        return False
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    return parsed.netloc.casefold() == host.casefold()


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
            running = sum(1 for current in self._jobs.values() if current.status in {"queued", "running"})
            max_jobs = app_config().max_import_jobs
            if running >= max_jobs:
                raise TooManyJobsError(f"At most {max_jobs} import jobs can run at once")
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
            log(f"IMPORT JOB STARTED {job_id} total={len(requests)} currency={currency}")
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
            log(
                f"IMPORT JOB COMPLETED {job_id} total={result.total} imported={result.imported} "
                f"failed={len(result.failures)} {collection_stats_log(store)}"
            )
        except Exception as exc:
            log(f"IMPORT JOB FAILED {job_id}: {exc}", level="ERROR")
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


class RequestTooLargeError(ValueError):
    pass


class TooManyJobsError(RuntimeError):
    pass


def fetch_image(url: str) -> tuple[str, bytes]:
    config = app_config()
    if not scryfall_image_url_allowed(url):
        raise ImageFetchError("Card image URL is not an allowed Scryfall HTTPS URL")
    request = Request(url, headers={"User-Agent": APP_USER_AGENT, "Accept": "image/*"})
    try:
        with urlopen(request, timeout=config.image_fetch_timeout_seconds) as response:
            content_type = response.headers.get_content_type() or "image/jpeg"
            if not content_type.startswith("image/"):
                raise ImageFetchError(f"Scryfall image returned unexpected content type {content_type}")
            content_length = response.headers.get("Content-Length")
            if content_length is not None and int(content_length) > config.max_image_bytes:
                raise ImageFetchError(f"Scryfall image exceeded {config.max_image_bytes} bytes")
            data = response.read(config.max_image_bytes + 1)
            if len(data) > config.max_image_bytes:
                raise ImageFetchError(f"Scryfall image exceeded {config.max_image_bytes} bytes")
            return content_type, data
    except HTTPError as exc:
        raise ImageFetchError(f"Scryfall image returned HTTP {exc.code}") from exc
    except URLError as exc:
        raise ImageFetchError(f"Could not fetch Scryfall image: {exc.reason}") from exc
    except ValueError as exc:
        raise ImageFetchError(f"Scryfall image returned invalid metadata: {exc}") from exc


def scryfall_image_url_allowed(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").casefold()
    return parsed.scheme == "https" and (host == "scryfall.io" or host.endswith(ALLOWED_IMAGE_HOST_SUFFIX))


def collection_stats_log(store: PriceStore) -> str:
    stats = store.collection_stats()
    return format_collection_stats(stats)


def format_collection_stats(stats: CollectionStats) -> str:
    return f"cards={stats.cards} tracked_entries={stats.tracked_entries} snapshots={stats.snapshots}"


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
