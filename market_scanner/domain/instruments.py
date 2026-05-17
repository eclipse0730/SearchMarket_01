from __future__ import annotations

from typing import Any

from market_scanner.domain.market_policy import home_market_key
from market_scanner.models import MarketDefinition


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def classify_asset_type(row: Any, market_key: str) -> str:
    home_key = home_market_key(market_key)
    if home_key in {"global-indices"}:
        return "index"
    if home_key in {"commodities"}:
        return "commodity"
    if home_key in {"sector-etfs"}:
        return "etf"

    name = (_clean_text(row.get("name_local")) or _clean_text(row.get("name_en")) or "").upper()
    symbol = (_clean_text(row.get("symbol")) or "").upper()
    if "ETN" in name:
        return "etn"
    if "ETF" in name or name.startswith(("KODEX", "TIGER", "ACE", "RISE", "SOL", "KOSEF", "KBSTAR")):
        return "etf"
    if "리츠" in name or "REIT" in name:
        return "reit"
    if "스팩" in name or "SPAC" in name:
        return "spac"
    if symbol.endswith(("5.KS", "7.KS", "9.KS")) and ("우" in name or "PREFERRED" in name):
        return "preferred_stock"
    if "우" in name and home_key in {"kr"}:
        return "preferred_stock"
    return "common_stock"


def display_symbol_for_row(row: Any, market: MarketDefinition) -> str | None:
    display_symbol = _clean_text(row.get("display_symbol"))
    symbol = _clean_text(row.get("symbol"))
    if symbol and home_market_key(market.key) in {"kr"}:
        code = symbol.replace(".KS", "").replace(".KQ", "")
        return code.zfill(6) if code.isdigit() else (display_symbol or code)
    return display_symbol or symbol


def source_rank(source_provider: str | None) -> int:
    source = (source_provider or "").lower()
    if source == "manual":
        return 10
    if source == "static":
        return 20
    if source in {"fdr", "naver", "yfinance"}:
        return 60
    if source == "csv":
        return 80
    return 100
