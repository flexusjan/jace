from __future__ import annotations

import csv
import re
from io import StringIO
from pathlib import Path

from .models import CardRequest

DEFAULT_CONDITION = "Near Mint"
DEFAULT_LANGUAGE = "English"
DEFAULT_FINISH = "Non-Foil"
CONDITION_ALIASES = {
    "near mint": "Near Mint",
    "near_mint": "Near Mint",
    "nm": "Near Mint",
    "lightly played": "Lightly Played",
    "lightly_played": "Lightly Played",
    "lp": "Lightly Played",
    "moderately played": "Moderately Played",
    "moderately_played": "Moderately Played",
    "mp": "Moderately Played",
    "heavily played": "Heavily Played",
    "heavily_played": "Heavily Played",
    "hp": "Heavily Played",
    "damaged": "Damaged",
    "dmg": "Damaged",
}
FINISH_ALIASES = {
    "nonfoil": "Non-Foil",
    "non-foil": "Non-Foil",
    "normal": "Non-Foil",
    "regular": "Non-Foil",
    "foil": "Foil",
    "f": "Foil",
    "*f*": "Foil",
    "etched": "Etched",
    "e": "Etched",
    "*e*": "Etched",
}

SET_SUFFIX_RE = re.compile(r"^(?:(?P<qty>\d+)x?\s+)?(?P<name>.+?)\s+\[(?P<set>[A-Za-z0-9]{2,8})\]\s*$")
ARENA_EXPORT_RE = re.compile(r"^(?:(?P<qty>\d+)x?\s+)?(?P<name>.+?)(?:\s+\((?P<set>[A-Za-z0-9]{2,8})\)\s+(?P<num>[A-Za-z0-9-]+)(?P<trailing>.*)?)?\s*$")


def parse_card_line(line: str) -> CardRequest | None:
    raw = line.strip()
    if not raw or raw.startswith("#"):
        return None

    match = SET_SUFFIX_RE.match(raw)
    if match:
        quantity = int(match.group("qty") or "1")
        return CardRequest(quantity=quantity, name=match.group("name").strip(), set_code=match.group("set").lower())

    match = ARENA_EXPORT_RE.match(raw)
    if not match:
        raise ValueError(f"Cannot parse card line: {line!r}")

    quantity = int(match.group("qty") or "1")
    name = match.group("name").strip()
    set_code = match.group("set").lower() if match.group("set") else None
    collector_number = match.group("num") if match.group("num") else None
    finish = finish_from_text(match.group("trailing") or "")
    return CardRequest(quantity=quantity, name=name, set_code=set_code, collector_number=collector_number, finish=finish)


def parse_card_file(path: Path) -> list[CardRequest]:
    return parse_card_text(path.read_text(encoding="utf-8"), source=str(path))


def parse_card_text(text: str, source: str = "input") -> list[CardRequest]:
    requests: list[CardRequest] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        try:
            request = parse_card_line(line)
        except ValueError as exc:
            raise ValueError(f"{source}:{line_number}: {exc}") from exc
        if request is not None:
            requests.append(request)
    return requests


def parse_card_csv(text: str, source: str = "csv") -> list[CardRequest]:
    reader = csv.DictReader(StringIO(text))
    if not reader.fieldnames:
        raise ValueError(f"{source}: CSV header is required")

    fields = {field.lower().strip(): field for field in reader.fieldnames if field}
    name_field = field_name(fields, "name", "card name")
    count_field = field_name(fields, "count", "quantity", "qty")
    set_field = field_name(fields, "edition", "set", "set code")
    number_field = field_name(fields, "collector number", "collector_number", "number")
    condition_field = field_name(fields, "condition")
    language_field = field_name(fields, "language")
    finish_field = field_name(fields, "finish", "foil", "is foil", "is_foil")
    if not name_field:
        raise ValueError(f"{source}: CSV must contain a Name column")

    requests: list[CardRequest] = []
    for line_number, row in enumerate(reader, start=2):
        name = (row.get(name_field) or "").strip()
        if not name:
            continue
        quantity = parse_quantity(row.get(count_field) if count_field else None, source, line_number)
        set_code = (row.get(set_field) or "").strip().lower() if set_field else None
        collector_number = (row.get(number_field) or "").strip() if number_field else None
        condition = normalize_condition(row.get(condition_field) if condition_field else None)
        language = normalize_language(row.get(language_field) if language_field else None)
        finish = normalize_finish(row.get(finish_field) if finish_field else None)
        requests.append(
            CardRequest(
                quantity=quantity,
                name=name,
                set_code=set_code or None,
                collector_number=collector_number or None,
                condition=condition,
                language=language,
                finish=finish,
            )
        )
    return requests


def field_name(fields: dict[str, str], *names: str) -> str | None:
    for name in names:
        field = fields.get(name)
        if field:
            return field
    return None


def parse_quantity(value: str | None, source: str, line_number: int) -> int:
    if value is None or not value.strip():
        return 1
    try:
        quantity = int(value)
    except ValueError as exc:
        raise ValueError(f"{source}:{line_number}: invalid quantity {value!r}") from exc
    if quantity < 1:
        raise ValueError(f"{source}:{line_number}: quantity must be at least 1")
    return quantity


def normalize_condition(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw:
        return DEFAULT_CONDITION
    return CONDITION_ALIASES.get(raw.lower(), raw)


def normalize_language(value: str | None) -> str:
    raw = (value or "").strip()
    return raw or DEFAULT_LANGUAGE


def normalize_finish(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw:
        return DEFAULT_FINISH
    lowered = raw.lower()
    if lowered in {"true", "yes", "1"}:
        return "Foil"
    if lowered in {"false", "no", "0"}:
        return "Non-Foil"
    return FINISH_ALIASES.get(lowered, raw)


def finish_from_text(value: str) -> str:
    raw = value.strip()
    if not raw:
        return DEFAULT_FINISH
    tokens = re.findall(r"\*[A-Za-z]+\*|[A-Za-z-]+", raw)
    for token in tokens:
        finish = FINISH_ALIASES.get(token.lower())
        if finish in {"Foil", "Etched"}:
            return finish
    return DEFAULT_FINISH
