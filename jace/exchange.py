from __future__ import annotations

import json
import threading
from decimal import Decimal, ROUND_HALF_UP
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from . import APP_USER_AGENT

BASE_URL = "https://api.frankfurter.dev/v2"
FIAT_CURRENCIES = {"eur", "usd"}


class ExchangeRateError(RuntimeError):
    pass


class ExchangeRateClient:
    def __init__(self, base_url: str = BASE_URL, timeout: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._rates: dict[tuple[str, str], Decimal] = {}
        self._lock = threading.Lock()

    def convert(self, amount: Decimal, source_currency: str, target_currency: str) -> Decimal:
        source = source_currency.lower()
        target = target_currency.lower()
        if source == target:
            return amount
        if source not in FIAT_CURRENCIES or target not in FIAT_CURRENCIES:
            raise ExchangeRateError(f"Cannot convert {source_currency.upper()} to {target_currency.upper()}")
        return (amount * self.rate(source, target)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def rate(self, source_currency: str, target_currency: str) -> Decimal:
        source = source_currency.upper()
        target = target_currency.upper()
        key = (source, target)
        with self._lock:
            cached = self._rates.get(key)
        if cached is not None:
            return cached

        url = f"{self.base_url}/rate/{quote(source, safe='')}/{quote(target, safe='')}"
        request = Request(url, headers={"User-Agent": APP_USER_AGENT, "Accept": "application/json"})
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ExchangeRateError(f"Exchange rate API returned HTTP {exc.code} for {url}: {detail}") from exc
        except URLError as exc:
            raise ExchangeRateError(f"Could not reach exchange rate API at {url}: {exc.reason}") from exc

        rate = rate_from_payload(payload, source, target)
        with self._lock:
            self._rates[key] = rate
        return rate


def rate_from_payload(payload: object, source: str, target: str) -> Decimal:
    if isinstance(payload, list):
        for item in payload:
            if not isinstance(item, dict):
                continue
            if str(item.get("base", "")).upper() == source and str(item.get("quote", "")).upper() == target:
                return Decimal(str(item["rate"]))
    if isinstance(payload, dict):
        rate = payload.get("rate")
        if rate is not None:
            return Decimal(str(rate))
    raise ExchangeRateError(f"Exchange rate response did not include {source}/{target}")


default_exchange_client = ExchangeRateClient()
