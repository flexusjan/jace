from __future__ import annotations

import json
from dataclasses import asdict
from decimal import Decimal
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .storage import HistoryPoint, PriceStore, ReportRow

STATIC_DIR = Path(__file__).with_name("static")


class PriceTrackerHandler(BaseHTTPRequestHandler):
    store: PriceStore

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
            self._send_json(cards_payload(self.store.latest_rows(), self.store.history_rows()))
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"{self.address_string()} - {format % args}")

    def _send_file(self, path: Path, content_type: str) -> None:
        body = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: Any) -> None:
        body = json.dumps(payload, default=json_default).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve(host: str, port: int, database_url: str | None) -> int:
    store = PriceStore(database_url)
    handler = type("ConfiguredPriceTrackerHandler", (PriceTrackerHandler,), {"store": store})
    server = HTTPServer((host, port), handler)
    print(f"Serving MTG price tracker on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
        store.close()
    return 0


def cards_payload(rows: list[ReportRow], history: dict[str, list[HistoryPoint]]) -> dict[str, Any]:
    return {
        "cards": [
            {
                **asdict(row),
                "latest_price": decimal_to_string(row.latest_price),
                "first_price": decimal_to_string(row.first_price),
                "change": decimal_to_string(price_change(row)),
                "latest_captured_at": row.latest_captured_at.isoformat(timespec="seconds"),
                "first_captured_at": row.first_captured_at.isoformat(timespec="seconds"),
                "history": [
                    {
                        "captured_at": point.captured_at.isoformat(timespec="seconds"),
                        "price": decimal_to_string(point.price),
                        "currency": point.currency,
                    }
                    for point in history.get(row.name, [])
                ],
            }
            for row in rows
        ]
    }


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
