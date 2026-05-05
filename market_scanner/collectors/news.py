from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import json
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf


NEWS_CACHE_PATH = Path(__file__).resolve().parent.parent / "assets" / "news_cache.json"


def _selected_symbols(frame: pd.DataFrame, max_symbols: int) -> list[str]:
    if frame.empty or "symbol" not in frame.columns or max_symbols <= 0:
        return []
    working = frame.copy()
    if "composite_score" in working.columns:
        working["composite_score"] = pd.to_numeric(working["composite_score"], errors="coerce")
        working = working.sort_values("composite_score", ascending=False, na_position="last")
    symbols = working["symbol"].dropna().astype(str).drop_duplicates().head(max_symbols)
    return symbols.tolist()


def _nested_value(data: dict[str, Any], *keys: str) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _published_at_text(value: Any) -> str:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, ZoneInfo("UTC")).astimezone(ZoneInfo("Asia/Seoul")).strftime(
            "%Y-%m-%d %H:%M:%S KST"
        )
    if value is None:
        return ""
    return str(value)


def _normalize_news_item(symbol: str, item: dict[str, Any]) -> dict[str, object] | None:
    content = item.get("content") if isinstance(item.get("content"), dict) else {}
    title = item.get("title") or content.get("title")
    url = (
        item.get("link")
        or item.get("url")
        or _nested_value(content, "canonicalUrl", "url")
        or _nested_value(content, "clickThroughUrl", "url")
    )
    if not title or not url:
        return None

    publisher = (
        item.get("publisher")
        or item.get("source")
        or _nested_value(content, "provider", "displayName")
        or _nested_value(content, "provider", "name")
        or ""
    )
    summary = item.get("summary") or content.get("summary") or content.get("description") or ""
    published_at = item.get("providerPublishTime") or item.get("publishedAt") or item.get("pubDate") or content.get("pubDate")
    return {
        "ticker": symbol,
        "title": str(title),
        "publisher": str(publisher),
        "summary": str(summary),
        "url": str(url),
        "sentiment": "neutral",
        "publishedAt": _published_at_text(published_at),
    }


def _fetch_symbol_news(symbol: str, items_per_symbol: int) -> list[dict[str, object]]:
    try:
        raw_items = yf.Ticker(symbol).news or []
    except Exception:
        return []

    items: list[dict[str, object]] = []
    seen: set[str] = set()
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        item = _normalize_news_item(symbol, raw)
        if not item:
            continue
        key = str(item.get("url") or item.get("title") or "")
        if key in seen:
            continue
        seen.add(key)
        items.append(item)
        if len(items) >= items_per_symbol:
            break
    return items


def _read_cache() -> dict[str, object]:
    if not NEWS_CACHE_PATH.exists():
        return {}
    try:
        payload = json.loads(NEWS_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_cache(date_str: str, market_key: str, items: list[dict[str, object]]) -> None:
    payload = _read_cache()
    dated = payload.get(date_str)
    if not isinstance(dated, dict):
        dated = {}
    dated[market_key] = items
    dated["_meta"] = {
        "updatedAt": datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M:%S KST"),
        "source": "yfinance.Ticker.news",
    }
    payload[date_str] = dated
    NEWS_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    NEWS_CACHE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def collect_news_cache(
    frame: pd.DataFrame,
    market_key: str,
    date_str: str,
    *,
    max_symbols: int = 50,
    items_per_symbol: int = 3,
    max_workers: int = 4,
) -> tuple[int, Path]:
    symbols = _selected_symbols(frame, max_symbols)
    if not symbols:
        _write_cache(date_str, market_key, [])
        return 0, NEWS_CACHE_PATH

    worker_count = max(1, min(max_workers, len(symbols)))
    collected: list[dict[str, object]] = []
    print(f"[news] {market_key}: {len(symbols)} symbols, {worker_count} workers")
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        future_map = {executor.submit(_fetch_symbol_news, symbol, max(1, items_per_symbol)): symbol for symbol in symbols}
        for index, future in enumerate(as_completed(future_map), start=1):
            symbol = future_map[future]
            print(f"  {index:>3}/{len(symbols)} {symbol:<12} news", end="\r")
            try:
                collected.extend(future.result())
            except Exception:
                continue
    print(" " * 72, end="\r")

    unique: list[dict[str, object]] = []
    seen: set[str] = set()
    for item in collected:
        key = str(item.get("url") or item.get("title") or "")
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)

    _write_cache(date_str, market_key, unique)
    print(f"[news] completed: {len(unique)} items")
    return len(unique), NEWS_CACHE_PATH
