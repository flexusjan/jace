from __future__ import annotations

import json
import threading
import time
from decimal import Decimal
from typing import Iterator, Protocol, TypeVar
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from . import APP_USER_AGENT
from .config import (
    DEFAULT_SCRYFALL_BASE_URL,
    DEFAULT_SCRYFALL_BULK_SIZE,
    DEFAULT_SCRYFALL_COLLECTION_REQUEST_INTERVAL_SECONDS,
    DEFAULT_SCRYFALL_REQUEST_INTERVAL_SECONDS,
    app_config,
)
from .exchange import ExchangeRateError, default_exchange_client
from .models import CardPrice, CardRequest

BASE_URL = DEFAULT_SCRYFALL_BASE_URL
COLLECTION_BATCH_SIZE = DEFAULT_SCRYFALL_BULK_SIZE
DEFAULT_REQUEST_INTERVAL_SECONDS = DEFAULT_SCRYFALL_REQUEST_INTERVAL_SECONDS
COLLECTION_REQUEST_INTERVAL_SECONDS = DEFAULT_SCRYFALL_COLLECTION_REQUEST_INTERVAL_SECONDS

_RATE_LIMIT_LOCK = threading.Lock()
_LAST_REQUEST_AT = 0.0
T = TypeVar("T")


class ScryfallError(RuntimeError):
    pass


CardPriceResult = tuple[CardRequest, CardPrice | None, Exception | None]


class CurrencyConverter(Protocol):
    def convert(self, amount: Decimal, source_currency: str, target_currency: str) -> Decimal:
        pass


class ScryfallClient:
    def __init__(
        self,
        base_url: str | None = None,
        timeout: float | None = None,
        pause_seconds: float | None = None,
        collection_pause_seconds: float | None = None,
        collection_batch_size: int | None = None,
    ) -> None:
        config = app_config()
        self.base_url = (base_url or config.scryfall_base_url).rstrip("/")
        self.timeout = timeout if timeout is not None else config.scryfall_timeout_seconds
        self.pause_seconds = pause_seconds if pause_seconds is not None else config.scryfall_request_interval_seconds
        self.collection_pause_seconds = (
            collection_pause_seconds if collection_pause_seconds is not None else config.scryfall_collection_request_interval_seconds
        )
        self.collection_batch_size = collection_batch_size if collection_batch_size is not None else config.scryfall_bulk_size

    def fetch_card_price(self, card: CardRequest, currency: str = "eur") -> CardPrice:
        data = self._get_card(card)
        return card_price_from_data(data, currency, card.finish)

    def fetch_card_prices(self, cards: list[CardRequest], currency: str = "eur") -> list[CardPriceResult]:
        results: list[CardPriceResult] = []
        for batch_results in self.fetch_card_price_batches(cards, currency):
            results.extend(batch_results)
        return results

    def fetch_card_price_batches(self, cards: list[CardRequest], currency: str = "eur") -> Iterator[list[CardPriceResult]]:
        for batch in chunks(cards, self.collection_batch_size):
            batch_results: list[CardPriceResult] = []
            try:
                data = match_collection_data(batch, self._get_card_collection(batch))
            except ScryfallError:
                yield self._fetch_card_prices_individually(batch, currency)
                continue

            # Scryfall's collection response can include not_found entries and does not need to be trusted
            # as input-ordered. Fall back to single lookups when we cannot match every card unambiguously.
            if data is None:
                yield self._fetch_card_prices_individually(batch, currency)
                continue

            for card, card_data in zip(batch, data):
                try:
                    batch_results.append((card, card_price_from_data(card_data, currency, card.finish), None))
                except (KeyError, ValueError, ExchangeRateError) as exc:
                    batch_results.append((card, None, exc))
            yield batch_results

    def fetch_card_prices_by_id(
        self,
        cards: list[tuple[CardRequest, str]],
        currency: str = "eur",
    ) -> list[CardPriceResult]:
        results: list[CardPriceResult] = []
        for batch in chunks(cards, self.collection_batch_size):
            try:
                response_data = self._request(
                    "/cards/collection",
                    method="POST",
                    body={"identifiers": [{"id": scryfall_id} for _, scryfall_id in batch]},
                    pause_seconds=self.collection_pause_seconds,
                ).get("data", [])
            except ScryfallError:
                results.extend(self._fetch_card_prices_individually([card for card, _ in batch], currency))
                continue

            data = match_collection_data_by_id(batch, response_data)
            if data is None:
                results.extend(self._fetch_card_prices_individually([card for card, _ in batch], currency))
                continue

            for (card, _), card_data in zip(batch, data):
                try:
                    results.append((card, card_price_from_data(card_data, currency, card.finish), None))
                except (KeyError, ValueError, ExchangeRateError) as exc:
                    results.append((card, None, exc))
        return results

    def _fetch_card_prices_individually(
        self,
        cards: list[CardRequest],
        currency: str,
    ) -> list[CardPriceResult]:
        results: list[CardPriceResult] = []
        for card in cards:
            try:
                results.append((card, self.fetch_card_price(card, currency), None))
            except (ScryfallError, KeyError, IndexError, ValueError) as exc:
                results.append((card, None, exc))
        return results

    def _get_card_collection(self, cards: list[CardRequest]) -> list[dict]:
        response = self._request(
            "/cards/collection",
            method="POST",
            body={"identifiers": [collection_identifier(card) for card in cards]},
            pause_seconds=self.collection_pause_seconds,
        )
        return response.get("data", [])

    def fetch_card(self, card: CardRequest) -> dict:
        return self._get_card(card)

    def _get_card(self, card: CardRequest) -> dict:
        if card.set_code and card.collector_number:
            return self._request(scryfall_card_path(card.set_code, card.collector_number))

        query = f'!"{card.name}"'
        if card.set_code:
            query += f" set:{card.set_code}"
        return self._request("/cards/search", {"q": query, "unique": "prints"})["data"][0]

    def _request(
        self,
        path: str,
        params: dict[str, str] | None = None,
        method: str = "GET",
        body: dict | None = None,
        pause_seconds: float | None = None,
    ) -> dict:
        url = f"{self.base_url}{path}"
        if params:
            url = f"{url}?{urlencode(params)}"
        headers = {"User-Agent": APP_USER_AGENT, "Accept": "application/json;q=0.9,*/*;q=0.8"}
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode("utf-8")

        for attempt in range(2):
            wait_for_scryfall_slot(pause_seconds or self.pause_seconds)
            request = Request(url, data=data, headers=headers, method=method)
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    payload = response.read().decode("utf-8")
                return json.loads(payload)
            except HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                if exc.code == 429 and attempt == 0:
                    retry_after = retry_after_seconds(exc)
                    time.sleep(retry_after if retry_after is not None else 60.0)
                    continue
                raise ScryfallError(f"Scryfall returned HTTP {exc.code} for {url}: {detail}") from exc
            except URLError as exc:
                raise ScryfallError(f"Could not reach Scryfall at {url}: {exc.reason}") from exc

        raise ScryfallError(f"Scryfall request failed for {url}")


def card_price_from_data(
    data: dict,
    currency: str = "eur",
    finish: str = "Non-Foil",
    converter: CurrencyConverter = default_exchange_client,
) -> CardPrice:
    prices = data.get("prices") or {}
    normalized_currency = currency.lower()
    source_currency, raw_price = price_source(prices, normalized_currency, effective_finish(data, finish))
    price = price_from_source(raw_price, source_currency, normalized_currency, converter) if raw_price and source_currency else None

    return CardPrice(
        scryfall_id=data["id"],
        name=data["name"],
        set_code=data["set"],
        collector_number=data["collector_number"],
        currency=normalized_currency.upper(),
        price=price,
        source_url=data["scryfall_uri"],
        image_url=card_image_url(data),
    )


def effective_finish(data: dict, requested_finish: str) -> str:
    normalized_finish = normalize_finish(requested_finish)
    finishes = [normalize_finish(value) for value in data.get("finishes") or []]
    if normalized_finish == "Non-Foil" and len(finishes) == 1 and finishes[0] in {"Foil", "Etched"}:
        return finishes[0]
    return normalized_finish


def normalize_finish(value: object) -> str:
    normalized_value = str(value or "").strip().casefold().replace("_", "-")
    if normalized_value in {"foil", "f", "*f*"}:
        return "Foil"
    if normalized_value in {"etched", "e", "*e*"}:
        return "Etched"
    return "Non-Foil"


def price_source(prices: dict, currency: str, finish: str) -> tuple[str | None, str | None]:
    candidates = price_candidates(currency, finish)
    candidates.extend(fallback_price_candidates(currency, finish))
    seen: set[tuple[str, str]] = set()
    for source_currency, field in candidates:
        key = (source_currency, field)
        if key in seen:
            continue
        seen.add(key)
        raw_price = prices.get(field)
        if raw_price:
            return source_currency, raw_price
    return None, None


def price_candidates(currency: str, finish: str) -> list[tuple[str, str]]:
    if finish == "Foil":
        if currency == "eur":
            return [("usd", "usd_foil"), ("eur", "eur_foil")]
        return [(currency, f"{currency}_foil")]
    if finish == "Etched":
        return [("usd", "usd_etched")]
    return [(currency, currency)]


def fallback_price_candidates(currency: str, finish: str) -> list[tuple[str, str]]:
    other_currency = "usd" if currency == "eur" else "eur" if currency == "usd" else None
    candidates: list[tuple[str, str]] = []
    if finish == "Foil":
        if currency != "eur" and other_currency:
            candidates.append((other_currency, f"{other_currency}_foil"))
        candidates.extend([(currency, currency)])
        if other_currency:
            candidates.append((other_currency, other_currency))
    elif finish == "Etched":
        candidates.extend([(currency, currency)])
        if other_currency:
            candidates.extend([(other_currency, other_currency), (other_currency, f"{other_currency}_foil")])
    else:
        if other_currency:
            candidates.append((other_currency, other_currency))
        candidates.extend([(currency, f"{currency}_foil")])
        if other_currency:
            candidates.append((other_currency, f"{other_currency}_foil"))
    return candidates


def price_from_source(
    raw_price: str,
    source_currency: str,
    target_currency: str,
    converter: CurrencyConverter,
) -> Decimal:
    price = Decimal(raw_price)
    if source_currency == target_currency:
        return price
    return converter.convert(price, source_currency, target_currency)


def collection_identifier(card: CardRequest) -> dict[str, str]:
    if card.set_code and card.collector_number:
        return {"set": card.set_code, "collector_number": card.collector_number}
    if card.set_code:
        return {"name": card.name, "set": card.set_code}
    return {"name": card.name}


def match_collection_data(cards: list[CardRequest], data: list[dict]) -> list[dict] | None:
    if len(data) != len(cards):
        return None

    remaining = list(data)
    matched: list[dict] = []
    for card in cards:
        index = next((idx for idx, candidate in enumerate(remaining) if card_matches_data(card, candidate)), None)
        if index is None:
            return None
        matched.append(remaining.pop(index))
    return matched


def match_collection_data_by_id(cards: list[tuple[CardRequest, str]], data: list[dict]) -> list[dict] | None:
    if len(data) != len(cards):
        return None

    by_id = {str(card_data.get("id")): card_data for card_data in data}
    matched: list[dict] = []
    for _, scryfall_id in cards:
        card_data = by_id.get(scryfall_id)
        if card_data is None:
            return None
        matched.append(card_data)
    return matched


def card_matches_data(card: CardRequest, data: dict) -> bool:
    if card.set_code and card.collector_number:
        return (
            normalized(data.get("set")) == normalized(card.set_code)
            and normalized(data.get("collector_number")) == normalized(card.collector_number)
        )
    if card.set_code:
        return normalized(data.get("set")) == normalized(card.set_code) and normalized(data.get("name")) == normalized(card.name)
    return normalized(data.get("name")) == normalized(card.name)


def normalized(value: object) -> str:
    return str(value or "").casefold()


def wait_for_scryfall_slot(interval_seconds: float) -> None:
    global _LAST_REQUEST_AT
    with _RATE_LIMIT_LOCK:
        now = time.monotonic()
        wait_seconds = _LAST_REQUEST_AT + interval_seconds - now
        if wait_seconds > 0:
            time.sleep(wait_seconds)
            now = time.monotonic()
        _LAST_REQUEST_AT = now


def retry_after_seconds(exc: HTTPError) -> float | None:
    value = exc.headers.get("Retry-After")
    if not value:
        return None
    try:
        return max(float(value), 0.0)
    except ValueError:
        return None


def chunks(items: list[T], size: int) -> list[list[T]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def scryfall_card_path(set_code: str, collector_number: str) -> str:
    return f"/cards/{quote(set_code, safe='')}/{quote(collector_number, safe='')}"


def card_image_url(data: dict) -> str | None:
    image_uris = data.get("image_uris")
    if isinstance(image_uris, dict):
        return image_uris.get("normal") or image_uris.get("large") or image_uris.get("small")

    faces = data.get("card_faces")
    if isinstance(faces, list):
        for face in faces:
            if not isinstance(face, dict):
                continue
            face_uris = face.get("image_uris")
            if isinstance(face_uris, dict):
                return face_uris.get("normal") or face_uris.get("large") or face_uris.get("small")
    return None
