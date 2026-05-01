from __future__ import annotations

import re
from pathlib import Path

from .models import CardRequest

SET_SUFFIX_RE = re.compile(r"^(?P<name>.+?)\s+\[(?P<set>[A-Za-z0-9]{2,8})\]\s*$")
ARENA_EXPORT_RE = re.compile(
    r"^(?:(?P<qty>\d+)x?\s+)?(?P<name>.+?)(?:\s+\((?P<set>[A-Za-z0-9]{2,8})\)\s+(?P<num>[A-Za-z0-9-]+))?\s*$"
)


def parse_card_line(line: str) -> CardRequest | None:
    raw = line.strip()
    if not raw or raw.startswith("#"):
        return None

    match = SET_SUFFIX_RE.match(raw)
    if match:
        return CardRequest(quantity=1, name=match.group("name").strip(), set_code=match.group("set").lower())

    match = ARENA_EXPORT_RE.match(raw)
    if not match:
        raise ValueError(f"Cannot parse card line: {line!r}")

    quantity = int(match.group("qty") or "1")
    name = match.group("name").strip()
    set_code = match.group("set").lower() if match.group("set") else None
    collector_number = match.group("num") if match.group("num") else None
    return CardRequest(quantity=quantity, name=name, set_code=set_code, collector_number=collector_number)


def parse_card_file(path: Path) -> list[CardRequest]:
    requests: list[CardRequest] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        try:
            request = parse_card_line(line)
        except ValueError as exc:
            raise ValueError(f"{path}:{line_number}: {exc}") from exc
        if request is not None:
            requests.append(request)
    return requests
