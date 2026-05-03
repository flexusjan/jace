from __future__ import annotations

import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from . import APP_USER_AGENT
from .models import CardRequest
from .parser import normalize_condition, normalize_finish, normalize_language

BASE_URL = "https://api2.moxfield.com"


class MoxfieldError(RuntimeError):
    pass


class MoxfieldClient:
    def __init__(self, base_url: str = BASE_URL, timeout: float = 20.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def fetch_deck_cards(self, url: str) -> list[CardRequest]:
        deck_id = extract_deck_id(url)
        deck = self._request(f"/v3/decks/all/{deck_id}")
        cards = cards_from_deck(deck)
        if not cards:
            raise MoxfieldError("Moxfield deck did not contain any cards")
        return cards

    def _request(self, path: str) -> dict:
        url = f"{self.base_url}{path}"
        request = Request(
            url,
            headers={
                "User-Agent": APP_USER_AGENT,
                "Accept": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise MoxfieldError(f"Moxfield returned HTTP {exc.code} for {url}: {detail}") from exc
        except URLError as exc:
            raise MoxfieldError(f"Could not reach Moxfield at {url}: {exc.reason}") from exc
        return json.loads(payload)


def extract_deck_id(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.netloc and not moxfield_host_allowed(parsed.hostname):
        raise MoxfieldError("Only Moxfield deck URLs are supported")

    path = parsed.path if parsed.netloc else url.strip()
    match = re.search(r"(?:^|/)decks/([^/?#]+)", path)
    deck_id = match.group(1) if match else path.rstrip("/").split("/")[-1]
    if not deck_id:
        raise MoxfieldError("Could not find a Moxfield deck id in the URL")
    return deck_id


def moxfield_host_allowed(host: str | None) -> bool:
    normalized = (host or "").casefold()
    return normalized == "moxfield.com" or normalized.endswith(".moxfield.com")


def cards_from_deck(deck: dict) -> list[CardRequest]:
    cards: list[CardRequest] = []
    boards = deck.get("boards")
    if isinstance(boards, dict):
        for board_name in ("commanders", "companions", "mainboard", "sideboard"):
            cards.extend(cards_from_board(boards.get(board_name)))

    for board_name in ("commanders", "companions", "mainboard", "sideboard"):
        cards.extend(cards_from_legacy_board(deck.get(board_name)))

    return merge_requests(cards)


def cards_from_board(board: object) -> list[CardRequest]:
    if not isinstance(board, dict):
        return []
    return cards_from_card_map(board.get("cards"))


def cards_from_legacy_board(board: object) -> list[CardRequest]:
    return cards_from_card_map(board)


def cards_from_card_map(card_map: object) -> list[CardRequest]:
    if not isinstance(card_map, dict):
        return []

    cards: list[CardRequest] = []
    for fallback_name, entry in card_map.items():
        request = request_from_moxfield_entry(str(fallback_name), entry)
        if request is not None:
            cards.append(request)
    return cards


def request_from_moxfield_entry(fallback_name: str, entry: object) -> CardRequest | None:
    if not isinstance(entry, dict):
        return None

    card = entry.get("card") if isinstance(entry.get("card"), dict) else entry
    name = card.get("name") or fallback_name
    if not name:
        return None

    try:
        quantity = int(entry.get("quantity") or card.get("quantity") or 1)
    except (TypeError, ValueError) as exc:
        raise MoxfieldError(f"Invalid quantity for {name}") from exc
    if quantity < 1:
        raise MoxfieldError(f"Invalid quantity for {name}")

    set_code = card.get("set") or card.get("setCode")
    collector_number = card.get("cn") or card.get("collectorNumber")
    condition = entry.get("condition") or card.get("condition")
    language = entry.get("language") or card.get("language") or "English"
    finish = entry.get("finish") or card.get("finish")
    if finish is None:
        finish = entry.get("foil") or entry.get("isFoil") or card.get("foil") or card.get("isFoil")
    return CardRequest(
        quantity=quantity,
        name=str(name),
        set_code=str(set_code).lower() if set_code else None,
        collector_number=str(collector_number) if collector_number else None,
        condition=normalize_condition(str(condition) if condition is not None else None),
        language=normalize_language(str(language) if language is not None else None),
        finish=normalize_finish(str(finish) if finish is not None else None),
    )


def merge_requests(requests: list[CardRequest]) -> list[CardRequest]:
    merged: dict[tuple[str, str | None, str | None, str, str, str], CardRequest] = {}
    for request in requests:
        key = (request.name, request.set_code, request.collector_number, request.condition, request.language, request.finish)
        existing = merged.get(key)
        if existing is None:
            merged[key] = request
            continue
        merged[key] = CardRequest(
            quantity=existing.quantity + request.quantity,
            name=existing.name,
            set_code=existing.set_code,
            collector_number=existing.collector_number,
            condition=existing.condition,
            language=existing.language,
            finish=existing.finish,
        )
    return list(merged.values())
