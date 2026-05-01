from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .models import CardRequest
from .scryfall import ScryfallClient, ScryfallError
from .storage import PriceStore


@dataclass(frozen=True)
class ImportFailure:
    name: str
    error: str


@dataclass(frozen=True)
class ImportResult:
    total: int
    processed: int
    imported: int
    failures: list[ImportFailure]


ProgressCallback = Callable[[dict[str, Any]], None]


def _report_progress(
    progress: ProgressCallback | None,
    *,
    started: int,
    processed: int,
    imported: int,
    failures: list[ImportFailure],
    current_card: str | None,
) -> None:
    if progress:
        progress(
            {
                "started": started,
                "processed": processed,
                "imported": imported,
                "failures": failures,
                "current_card": current_card,
            }
        )


def _save_price_results(
    results: list[tuple[CardRequest, Any, Exception | None]],
    store: PriceStore,
    imported: int,
    failures: list[ImportFailure],
) -> int:
    for card, price, error in results:
        if error is not None or price is None:
            failure = ImportFailure(name=card.name, error=str(error or "card not found"))
            failures.append(failure)
            print(f"IMPORT FAILED {card.name}: {failure.error}")
        else:
            store.save_snapshot(card, price)
            imported += 1
    return imported


def import_cards(
    requests: list[CardRequest],
    store: PriceStore,
    currency: str = "eur",
    client: ScryfallClient | None = None,
    progress: ProgressCallback | None = None,
) -> ImportResult:
    scryfall = client or ScryfallClient()
    failures: list[ImportFailure] = []
    imported = 0

    if hasattr(scryfall, "fetch_card_price_batches"):
        started = 0
        processed = 0
        for batch_results in scryfall.fetch_card_price_batches(requests, currency):
            batch_size = len(batch_results)
            started += batch_size
            current_card = batch_results[0][0].name if batch_results else None
            _report_progress(
                progress,
                started=started,
                processed=processed,
                imported=imported,
                failures=failures,
                current_card=current_card,
            )
            imported = _save_price_results(batch_results, store, imported, failures)
            processed += batch_size
            _report_progress(
                progress,
                started=started,
                processed=processed,
                imported=imported,
                failures=failures,
                current_card=current_card,
            )

        return ImportResult(total=len(requests), processed=len(requests), imported=imported, failures=failures)

    if hasattr(scryfall, "fetch_card_prices"):
        for processed, (card, price, error) in enumerate(scryfall.fetch_card_prices(requests, currency), start=1):
            if error is not None or price is None:
                failure = ImportFailure(name=card.name, error=str(error or "card not found"))
                failures.append(failure)
                print(f"IMPORT FAILED {card.name}: {failure.error}")
            else:
                store.save_snapshot(card, price)
                imported += 1

            _report_progress(
                progress,
                started=len(requests),
                processed=processed,
                imported=imported,
                failures=failures,
                current_card=card.name,
            )

        return ImportResult(total=len(requests), processed=len(requests), imported=imported, failures=failures)

    for started, card in enumerate(requests, start=1):
        _report_progress(
            progress,
            started=started,
            processed=started - 1,
            imported=imported,
            failures=failures,
            current_card=card.name,
        )
        try:
            price = scryfall.fetch_card_price(card, currency)
        except (ScryfallError, KeyError, IndexError, ValueError) as exc:
            failure = ImportFailure(name=card.name, error=str(exc))
            failures.append(failure)
            print(f"IMPORT FAILED {card.name}: {failure.error}")
            _report_progress(
                progress,
                started=started,
                processed=started,
                imported=imported,
                failures=failures,
                current_card=card.name,
            )
            continue

        store.save_snapshot(card, price)
        imported += 1
        _report_progress(
            progress,
            started=started,
            processed=started,
            imported=imported,
            failures=failures,
            current_card=card.name,
        )

    return ImportResult(total=len(requests), processed=len(requests), imported=imported, failures=failures)
