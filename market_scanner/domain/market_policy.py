from __future__ import annotations


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

