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

    if hasattr(scryfall, "fetch_card_prices"):
        for started, card in enumerate(requests, start=1):
            if progress:
                progress(
                    {
                        "started": started,
                        "processed": started - 1,
                        "imported": imported,
                        "failures": failures,
                        "current_card": card.name,
                    }
                )

        for processed, (card, price, error) in enumerate(scryfall.fetch_card_prices(requests, currency), start=1):
            if error is not None or price is None:
                failure = ImportFailure(name=card.name, error=str(error or "card not found"))
                failures.append(failure)
                print(f"IMPORT FAILED {card.name}: {failure.error}")
            else:
                store.save_snapshot(card, price)
                imported += 1

            if progress:
                progress(
                    {
                        "started": len(requests),
                        "processed": processed,
                        "imported": imported,
                        "failures": failures,
                        "current_card": card.name,
                    }
                )

        return ImportResult(total=len(requests), processed=len(requests), imported=imported, failures=failures)

    for started, card in enumerate(requests, start=1):
        if progress:
            progress(
                {
                    "started": started,
                    "processed": started - 1,
                    "imported": imported,
                    "failures": failures,
                    "current_card": card.name,
                }
            )
        try:
            price = scryfall.fetch_card_price(card, currency)
        except (ScryfallError, KeyError, IndexError, ValueError) as exc:
            failure = ImportFailure(name=card.name, error=str(exc))
            failures.append(failure)
            print(f"IMPORT FAILED {card.name}: {failure.error}")
            if progress:
                progress(
                    {
                        "started": started,
                        "processed": started,
                        "imported": imported,
                        "failures": failures,
                        "current_card": card.name,
                    }
                )
            continue

        store.save_snapshot(card, price)
        imported += 1
        if progress:
            progress(
                {
                    "started": started,
                    "processed": started,
                    "imported": imported,
                    "failures": failures,
                    "current_card": card.name,
                }
            )

    return ImportResult(total=len(requests), processed=len(requests), imported=imported, failures=failures)
