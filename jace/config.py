from __future__ import annotations

import os
from dataclasses import dataclass


DEFAULT_CURRENCY = "eur"
DEFAULT_WEB_HOST = "0.0.0.0"
DEFAULT_WEB_PORT = 8180
DEFAULT_REFRESH_INTERVAL_SECONDS = 60 * 60
DEFAULT_SCRYFALL_BASE_URL = "https://api.scryfall.com"
DEFAULT_SCRYFALL_BULK_SIZE = 75
DEFAULT_SCRYFALL_REQUEST_INTERVAL_SECONDS = 0.12
DEFAULT_SCRYFALL_COLLECTION_REQUEST_INTERVAL_SECONDS = 0.55
DEFAULT_SCRYFALL_TIMEOUT_SECONDS = 20.0
DEFAULT_IMAGE_FETCH_TIMEOUT_SECONDS = 20.0
DEFAULT_MAX_REQUEST_BODY_BYTES = 1024 * 1024
DEFAULT_MAX_IMPORT_CARDS = 1000
DEFAULT_MAX_IMPORT_JOBS = 4
DEFAULT_MAX_IMAGE_BYTES = 10 * 1024 * 1024
DEFAULT_DARK_THEME = True

SUPPORTED_CURRENCIES = {"eur", "usd", "tix"}


@dataclass(frozen=True)
class AppConfig:
    default_currency: str = DEFAULT_CURRENCY
    web_host: str = DEFAULT_WEB_HOST
    web_port: int = DEFAULT_WEB_PORT
    refresh_interval_seconds: int = DEFAULT_REFRESH_INTERVAL_SECONDS
    scryfall_base_url: str = DEFAULT_SCRYFALL_BASE_URL
    scryfall_bulk_size: int = DEFAULT_SCRYFALL_BULK_SIZE
    scryfall_request_interval_seconds: float = DEFAULT_SCRYFALL_REQUEST_INTERVAL_SECONDS
    scryfall_collection_request_interval_seconds: float = DEFAULT_SCRYFALL_COLLECTION_REQUEST_INTERVAL_SECONDS
    scryfall_timeout_seconds: float = DEFAULT_SCRYFALL_TIMEOUT_SECONDS
    image_fetch_timeout_seconds: float = DEFAULT_IMAGE_FETCH_TIMEOUT_SECONDS
    auth_username: str | None = None
    auth_password: str | None = None
    max_request_body_bytes: int = DEFAULT_MAX_REQUEST_BODY_BYTES
    max_import_cards: int = DEFAULT_MAX_IMPORT_CARDS
    max_import_jobs: int = DEFAULT_MAX_IMPORT_JOBS
    max_image_bytes: int = DEFAULT_MAX_IMAGE_BYTES
    dark_theme: bool = DEFAULT_DARK_THEME


def app_config() -> AppConfig:
    default_currency = env_currency("JACE_DEFAULT_CURRENCY", DEFAULT_CURRENCY)
    auth_username = env_optional_str("JACE_AUTH_USERNAME")
    auth_password = env_optional_str("JACE_AUTH_PASSWORD")
    if bool(auth_username) != bool(auth_password):
        raise ValueError("JACE_AUTH_USERNAME and JACE_AUTH_PASSWORD must be set together")
    return AppConfig(
        default_currency=default_currency,
        web_host=env_str("JACE_WEB_HOST", DEFAULT_WEB_HOST),
        web_port=env_int("JACE_WEB_PORT", DEFAULT_WEB_PORT, minimum=1, maximum=65535),
        refresh_interval_seconds=env_int("JACE_REFRESH_INTERVAL_SECONDS", DEFAULT_REFRESH_INTERVAL_SECONDS, minimum=1),
        scryfall_base_url=env_str("JACE_SCRYFALL_BASE_URL", DEFAULT_SCRYFALL_BASE_URL),
        scryfall_bulk_size=env_int("JACE_SCRYFALL_BULK_SIZE", DEFAULT_SCRYFALL_BULK_SIZE, minimum=1, maximum=75),
        scryfall_request_interval_seconds=env_float(
            "JACE_SCRYFALL_REQUEST_INTERVAL_SECONDS",
            DEFAULT_SCRYFALL_REQUEST_INTERVAL_SECONDS,
            minimum=0.0,
        ),
        scryfall_collection_request_interval_seconds=env_float(
            "JACE_SCRYFALL_COLLECTION_REQUEST_INTERVAL_SECONDS",
            DEFAULT_SCRYFALL_COLLECTION_REQUEST_INTERVAL_SECONDS,
            minimum=0.0,
        ),
        scryfall_timeout_seconds=env_float("JACE_SCRYFALL_TIMEOUT_SECONDS", DEFAULT_SCRYFALL_TIMEOUT_SECONDS, minimum=0.1),
        image_fetch_timeout_seconds=env_float("JACE_IMAGE_FETCH_TIMEOUT_SECONDS", DEFAULT_IMAGE_FETCH_TIMEOUT_SECONDS, minimum=0.1),
        auth_username=auth_username,
        auth_password=auth_password,
        max_request_body_bytes=env_int("JACE_MAX_REQUEST_BODY_BYTES", DEFAULT_MAX_REQUEST_BODY_BYTES, minimum=1024),
        max_import_cards=env_int("JACE_MAX_IMPORT_CARDS", DEFAULT_MAX_IMPORT_CARDS, minimum=1),
        max_import_jobs=env_int("JACE_MAX_IMPORT_JOBS", DEFAULT_MAX_IMPORT_JOBS, minimum=1),
        max_image_bytes=env_int("JACE_MAX_IMAGE_BYTES", DEFAULT_MAX_IMAGE_BYTES, minimum=1024),
        dark_theme=env_bool("JACE_DARK_THEME", DEFAULT_DARK_THEME),
    )


def env_str(name: str, default: str) -> str:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    return value.strip()


def env_optional_str(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return None
    return value.strip()


def env_currency(name: str, default: str) -> str:
    value = env_str(name, default).lower()
    if value not in SUPPORTED_CURRENCIES:
        raise ValueError(f"{name} must be one of {', '.join(sorted(SUPPORTED_CURRENCIES))}")
    return value


def env_int(name: str, default: int, *, minimum: int | None = None, maximum: int | None = None) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        value = default
    else:
        try:
            value = int(raw)
        except ValueError as exc:
            raise ValueError(f"{name} must be an integer") from exc
    validate_range(name, value, minimum=minimum, maximum=maximum)
    return value


def env_float(name: str, default: float, *, minimum: float | None = None, maximum: float | None = None) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        value = default
    else:
        try:
            value = float(raw)
        except ValueError as exc:
            raise ValueError(f"{name} must be a number") from exc
    validate_range(name, value, minimum=minimum, maximum=maximum)
    return value


def env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false")


def validate_range(name: str, value: int | float, *, minimum: int | float | None, maximum: int | float | None) -> None:
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} must be at most {maximum}")
