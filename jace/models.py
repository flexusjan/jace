from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class CardRequest:
    quantity: int
    name: str
    set_code: str | None = None
    collector_number: str | None = None
    condition: str = "NM"
    language: str = "English"


@dataclass(frozen=True)
class CardPrice:
    scryfall_id: str
    name: str
    set_code: str
    collector_number: str
    currency: str
    price: Decimal | None
    source_url: str
    image_url: str | None = None
