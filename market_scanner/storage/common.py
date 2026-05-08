from __future__ import annotations

from typing import Any

import pandas as pd


UNIVERSE_MARKET_ALIASES = {
    "nasdaq": "us",
    "nyse": "us",
    "amex": "us",
    "nasdaq100": "us",
    "sp500": "us",
    "kospi100": "kospi",
    "kospi200": "kospi",
    "kosdaq150": "kosdaq",
}


def home_market_key(market_key: str) -> str:
    if market_key in UNIVERSE_MARKET_ALIASES:
        return UNIVERSE_MARKET_ALIASES[market_key]
    return market_key


def default_asset_filter(market_key: str) -> list[str]:
    if market_key in {"global-indices"}:
        return ["index"]
    if market_key in {"commodities"}:
        return ["commodity"]
    return ["common_stock"]


def country_currency_for_market(market_key: str) -> tuple[str | None, str | None, str]:
    home_key = home_market_key(market_key)
    if home_key in {"kospi", "kosdaq"}:
        return "KR", "KRW", "Asia/Seoul"
    if home_key in {"us", "nasdaq100", "sp500"}:
        return "US", "USD", "America/New_York"
    return None, None, "Asia/Seoul"


def price_source_for_market(market_key: str) -> str:
    if home_market_key(market_key) in {"kospi", "kosdaq"}:
        return "fdr"
    return "yfinance"


def clean_value(value: Any) -> Any:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        return value.item()
    return value


def clean_text(value: Any) -> str | None:
    value = clean_value(value)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def clean_number(value: Any) -> float | None:
    value = clean_value(value)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def clean_int(value: Any) -> int | None:
    number = clean_number(value)
    return int(number) if number is not None else None


def clean_bool(value: Any) -> bool:
    value = clean_value(value)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def row_payload(row: pd.Series, columns: list[str]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for column in columns:
        if column in row:
            payload[column] = clean_value(row.get(column))
    return payload
