from __future__ import annotations

import argparse
import csv
import sys
from decimal import Decimal
from pathlib import Path

from .parser import parse_card_file
from .scryfall import ScryfallClient, ScryfallError
from .storage import PriceStore, ReportRow


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mtg-price-tracker")
    parser.add_argument("--database-url", help="Postgres connection URL. Defaults to DATABASE_URL.")

    subparsers = parser.add_subparsers(dest="command", required=True)

    track = subparsers.add_parser("track", help="Fetch current prices and store a snapshot")
    track.add_argument("--database-url", default=argparse.SUPPRESS, help="Postgres connection URL")
    track.add_argument("cards", type=Path, help="Text file with card names")
    track.add_argument("--currency", default="eur", choices=["eur", "usd", "tix"], help="Scryfall price currency")

    report = subparsers.add_parser("report", help="Print latest prices and change since first snapshot")
    report.add_argument("--database-url", default=argparse.SUPPRESS, help="Postgres connection URL")
    report.add_argument("--format", choices=["table", "csv"], default="table")

    web = subparsers.add_parser("web", help="Start the browser frontend")
    web.add_argument("--database-url", default=argparse.SUPPRESS, help="Postgres connection URL")
    web.add_argument("--host", default="0.0.0.0", help="Bind host")
    web.add_argument("--port", type=int, default=8000, help="Bind port")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "web":
        from .web import serve

        return serve(args.host, args.port, args.database_url)

    store = PriceStore(args.database_url)
    try:
        if args.command == "track":
            return track(args, store)
        if args.command == "report":
            return report(args, store)
    finally:
        store.close()
    return 1


def track(args: argparse.Namespace, store: PriceStore) -> int:
    requests = parse_card_file(args.cards)
    client = ScryfallClient()
    failures = 0

    for card in requests:
        try:
            price = client.fetch_card_price(card, args.currency)
        except (ScryfallError, KeyError, IndexError) as exc:
            print(f"ERROR {card.name}: {exc}", file=sys.stderr)
            failures += 1
            continue
        store.save_snapshot(card, price)
        shown_price = f"{price.price} {price.currency}" if price.price is not None else f"n/a {price.currency}"
        print(f"tracked {card.quantity}x {price.name} [{price.set_code}] {shown_price}")

    return 1 if failures else 0


def report(args: argparse.Namespace, store: PriceStore) -> int:
    rows = store.latest_rows()
    if args.format == "csv":
        writer = csv.writer(sys.stdout)
        writer.writerow(["name", "set", "number", "quantity", "currency", "latest", "first", "change", "latest_at"])
        for row in rows:
            writer.writerow(_report_values(row))
        return 0

    print("Name | Set | Qty | Latest | First | Change | Captured")
    print("-" * 78)
    for row in rows:
        name, set_code, number, quantity, currency, latest, first, change, latest_at = _report_values(row)
        latest_display = _money(latest, currency)
        first_display = _money(first, currency)
        change_display = _money(change, currency, signed=True)
        print(f"{name} ({set_code} #{number}) | {quantity} | {latest_display} | {first_display} | {change_display} | {latest_at}")
    return 0


def _report_values(row: ReportRow) -> tuple[str, str, str, int, str, Decimal | None, Decimal | None, Decimal | None, str]:
    latest = row.latest_price
    first = row.first_price
    change = latest - first if latest is not None and first is not None else None
    return (
        row.name,
        row.set_code,
        row.collector_number,
        row.quantity,
        row.currency,
        latest,
        first,
        change,
        row.latest_captured_at.isoformat(timespec="seconds"),
    )


def _money(value: Decimal | None, currency: str, signed: bool = False) -> str:
    if value is None:
        return "n/a"
    prefix = "+" if signed and value > 0 else ""
    return f"{prefix}{value} {currency}"


if __name__ == "__main__":
    raise SystemExit(main())
