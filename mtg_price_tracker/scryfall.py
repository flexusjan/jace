from __future__ import annotations

import json
import time
from decimal import Decimal
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .models import CardPrice, CardRequest

BASE_URL = "https://api.scryfall.com"
USER_AGENT = "jace-the-price-tracker/0.1.0"


class ScryfallError(RuntimeError):
    pass


class ScryfallClient:
    def __init__(self, base_url: str = BASE_URL, timeout: float = 20.0, pause_seconds: float = 0.11) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.pause_seconds = pause_seconds

    def fetch_card_price(self, card: CardRequest, currency: str = "eur") -> CardPrice:
        data = self._get_card(card)
        prices = data.get("prices") or {}
        normalized_currency = currency.lower()
        raw_price = prices.get(normalized_currency)
        price = Decimal(raw_price) if raw_price else None

        return CardPrice(
            scryfall_id=data["id"],
            name=data["name"],
            set_code=data["set"],
            collector_number=data["collector_number"],
            currency=normalized_currency.upper(),
            price=price,
            source_url=data["scryfall_uri"],
        )

    def _get_card(self, card: CardRequest) -> dict:
        if card.set_code and card.collector_number:
            path = f"/cards/{card.set_code}/{card.collector_number}"
            return self._request(path)

        query = f'!"{card.name}"'
        if card.set_code:
            query += f" set:{card.set_code}"
        return self._request("/cards/search", {"q": query, "unique": "prints"})["data"][0]

    def _request(self, path: str, params: dict[str, str] | None = None) -> dict:
        url = f"{self.base_url}{path}"
        if params:
            url = f"{url}?{urlencode(params)}"
        request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ScryfallError(f"Scryfall returned HTTP {exc.code} for {url}: {detail}") from exc
        except URLError as exc:
            raise ScryfallError(f"Could not reach Scryfall at {url}: {exc.reason}") from exc
        finally:
            time.sleep(self.pause_seconds)

        return json.loads(payload)
