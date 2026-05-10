from __future__ import annotations

import pandas as pd

from market_scanner.config.markets import display_strip_kr, has_hangul
from market_scanner.models import MarketDefinition


def _safe_number(value, digits: int | None = None) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(numeric):
        return None
    return round(numeric, digits) if digits is not None else numeric


def _clean_text(value: object) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _is_placeholder_text(value: object) -> bool:
    return _clean_text(value).lower() in {"", "-", "nan", "none", "unknown", "no description", "n/a"}


def _is_placeholder_name(value: object, symbol: str) -> bool:
    text = _clean_text(value)
    if _is_placeholder_text(text):
        return True
    normalized = symbol.strip().upper()
    display = normalized.replace(".KS", "").replace(".KQ", "")
    return text.upper() in {normalized, display}


def _looks_like_english_company_name(value: object, symbol: str) -> bool:
    text = _clean_text(value)
    if _is_placeholder_name(text, symbol) or has_hangul(text):
        return False
    if not any(char.isalpha() for char in text):
        return False
    upper = text.upper()
    company_markers = (
        " INC", " CORP", " CORPORATION", " CO.", " CO ", " LTD", " LIMITED",
        " HOLDINGS", " ENGINEERING", " CONSTRUCTION", " ELECTRONICS",
        " CHEMICAL", " INDUSTRIES", " FINANCIAL", " INSURANCE",
    )
    return " " in text or any(marker in upper for marker in company_markers)


def _display_symbol_name(row: pd.Series, symbol: str) -> str:
    display = _clean_text(row.get("display_symbol"))
    if symbol.endswith((".KS", ".KQ")):
        if display and display.isdigit():
            return display.zfill(6)
        return display_strip_kr(symbol)
    return display or display_strip_kr(symbol)


def enrich_metadata_frame(frame: pd.DataFrame, market: MarketDefinition) -> pd.DataFrame:
    if frame.empty or "symbol" not in frame.columns:
        return frame

    metadata = market.metadata_loader()
    if not metadata:
        return frame

    enriched = frame.copy()
    if "display_symbol" not in enriched.columns:
        enriched["display_symbol"] = ""
    else:
        enriched["display_symbol"] = enriched["display_symbol"].astype("object")
    for column in ("name_en", "name_local", "sector", "description"):
        if column not in enriched.columns:
            enriched[column] = ""
        else:
            enriched[column] = enriched[column].astype("object")

    for index, row in enriched.iterrows():
        symbol = _clean_text(row.get("symbol"))
        meta = metadata.get(symbol)
        if not symbol:
            continue

        if meta is not None:
            if _is_placeholder_name(row.get("name_en"), symbol) and not _is_placeholder_text(meta.name_en):
                enriched.at[index, "name_en"] = meta.name_en
            if _is_placeholder_name(row.get("name_local"), symbol) and not _is_placeholder_text(meta.name_local):
                enriched.at[index, "name_local"] = meta.name_local
            if _is_placeholder_text(row.get("sector")) and not _is_placeholder_text(meta.sector):
                enriched.at[index, "sector"] = meta.sector
            if _is_placeholder_text(row.get("description")) and not _is_placeholder_text(meta.description):
                enriched.at[index, "description"] = meta.description

        if market.key in {"kospi", "kosdaq"}:
            enriched.at[index, "display_symbol"] = _display_symbol_name(row, symbol)
            local_name = enriched.at[index, "name_local"]
            if _is_placeholder_name(local_name, symbol) or _looks_like_english_company_name(local_name, symbol):
                enriched.at[index, "name_local"] = _display_symbol_name(row, symbol)

    return enriched
