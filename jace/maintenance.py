from __future__ import annotations

from dataclasses import dataclass

from .logs import log
from .models import CardRequest
from .scryfall import ScryfallClient, card_image_url
from .storage import PriceStore


@dataclass(frozen=True)
class ArtworkRefreshResult:
    updated: int
    failed: int


def refresh_artwork_urls(store: PriceStore, client: ScryfallClient | None = None) -> ArtworkRefreshResult:
    scryfall = client or ScryfallClient()
    rows = store.latest_rows()
    updated = 0
    failed = 0

    for row in rows:
        request = CardRequest(
            quantity=row.quantity,
            name=row.name,
            set_code=row.set_code,
            collector_number=row.collector_number,
            condition=row.condition,
            language=row.language,
        )
        try:
            data = scryfall.fetch_card(request)
            image_url = card_image_url(data)
            if not image_url:
                failed += 1
                log(f"ARTWORK FAILED {row.name}: no image URL", level="ERROR")
                continue
            store.update_card_artwork(row.scryfall_id, image_url)
            updated += 1
        except Exception as exc:
            failed += 1
            log(f"ARTWORK FAILED {row.name}: {exc}", level="ERROR")

    return ArtworkRefreshResult(updated=updated, failed=failed)
