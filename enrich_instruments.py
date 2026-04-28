"""
instruments.json 데이터 보강 스크립트

- description == "No description" 항목 → yfinance로 설명 보충
- name_en == 티커 심볼 그대로인 항목 → yfinance로 영문명 보충
- sector == "Unknown" 항목 → yfinance로 섹터 보충
- source == "manual" 항목은 건드리지 않음

실행: python enrich_instruments.py
옵션:
  --dry-run     실제 저장 없이 변경 예정 내역만 출력
  --limit N     최대 N개 항목만 처리 (테스트용)
  --market KEY  특정 시장만 처리 (us / kospi / kosdaq / ...)
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import yfinance as yf

INSTRUMENTS_PATH = Path("market_scanner/assets/instruments.json")

SECTOR_KO: dict[str, str] = {
    "Financial Services":     "금융 서비스",
    "Healthcare":             "헬스케어",
    "Technology":             "기술",
    "Consumer Cyclical":      "경기 소비재",
    "Consumer Defensive":     "필수 소비재",
    "Industrials":            "산업재",
    "Communication Services": "커뮤니케이션 서비스",
    "Real Estate":            "부동산·리츠",
    "Utilities":              "유틸리티",
    "Energy":                 "에너지",
    "Basic Materials":        "원자재",
}

PLACEHOLDER_VALUES = {"", "-", "nan", "none", "no description", "n/a", "unknown"}


def _is_placeholder(value: object) -> bool:
    return str(value).strip().lower() in PLACEHOLDER_VALUES


def _has_hangul(value: object) -> bool:
    return any("가" <= c <= "힣" for c in str(value))


def _is_ticker_as_name(name: str, symbol: str) -> bool:
    """name_en이 티커 심볼 그대로 들어간 경우"""
    normalized = symbol.strip().upper()
    display = normalized.replace(".KS", "").replace(".KQ", "")
    return name.strip().upper() in {normalized, display}


def _needs_enrichment(symbol: str, entry: dict) -> dict[str, bool]:
    name_en = entry.get("name_en", "")
    description = entry.get("description", "")
    sector = entry.get("sector", "")
    market_key = entry.get("market_key", "")

    needs = {
        # 티커 그대로거나, 한국어가 들어간 name_en (kospi/kosdaq 포함 — yfinance longName으로 교체)
        "name_en": _is_ticker_as_name(name_en, symbol) or _has_hangul(name_en),
        "description": _is_placeholder(description),
        "sector": _is_placeholder(sector),
    }
    return needs


def _fetch_yfinance(symbol: str) -> dict:
    try:
        info = yf.Ticker(symbol).info
        if not isinstance(info, dict):
            return {}
        return info
    except Exception:
        return {}


def _translate_sector(sector_raw: str, market_key: str) -> str:
    if market_key in {"kospi", "kosdaq"}:
        return SECTOR_KO.get(sector_raw, sector_raw)
    return SECTOR_KO.get(sector_raw, sector_raw)


def enrich(
    dry_run: bool = False,
    limit: int | None = None,
    market_filter: str | None = None,
) -> None:
    payload: dict[str, dict] = json.loads(INSTRUMENTS_PATH.read_text(encoding="utf-8"))

    targets = [
        (sym, entry)
        for sym, entry in payload.items()
        if entry.get("source") != "manual"
        and (market_filter is None or entry.get("market_key") == market_filter)
        and any(_needs_enrichment(sym, entry).values())
    ]

    print(f"보강 대상: {len(targets)}개 항목 (전체 {len(payload)}개 중)")
    if limit:
        targets = targets[:limit]
        print(f"  → --limit {limit} 적용: {len(targets)}개만 처리")

    changed = 0
    for idx, (symbol, entry) in enumerate(targets, 1):
        needs = _needs_enrichment(symbol, entry)
        market_key = entry.get("market_key", "")
        print(f"  [{idx:>4}/{len(targets)}] {symbol:<16} ", end="", flush=True)

        info = _fetch_yfinance(symbol)
        if not info:
            print("⚠ yfinance 응답 없음")
            time.sleep(0.3)
            continue

        updates: dict[str, str] = {}

        # name_en 보강 — longName 우선, 영문 후보만 사용
        if needs["name_en"]:
            long_name = str(info.get("longName") or "").strip()
            short_name = str(info.get("shortName") or "").strip()
            # 영문명 후보 선택: 한글 없고, 티커 그대로도 아닌 것
            for candidate in (long_name, short_name):
                if (
                    candidate
                    and not _has_hangul(candidate)
                    and not _is_ticker_as_name(candidate, symbol)
                    and not _is_placeholder(candidate)
                ):
                    updates["name_en"] = candidate
                    break

        # description 보강
        if needs["description"]:
            summary = str(info.get("longBusinessSummary") or "").strip()
            if summary:
                updates["description"] = summary[:160]

        # sector 보강
        if needs["sector"]:
            sector_raw = str(info.get("sector") or "").strip()
            if sector_raw and not _is_placeholder(sector_raw):
                updates["sector"] = _translate_sector(sector_raw, market_key)

        if updates:
            changed += 1
            parts = [f"{k}={repr(v[:40])}" for k, v in updates.items()]
            print(f"✓ {', '.join(parts)}")
            if not dry_run:
                payload[symbol].update(updates)
        else:
            print("- 개선 불가 (yfinance 데이터 없음)")

        time.sleep(0.2)

    print(f"\n완료: {changed}/{len(targets)}개 항목 업데이트됨")

    if not dry_run and changed > 0:
        INSTRUMENTS_PATH.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"저장 완료: {INSTRUMENTS_PATH}")
    elif dry_run:
        print("(dry-run 모드 — 파일 저장 안 함)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="instruments.json 데이터 보강")
    parser.add_argument("--dry-run", action="store_true", help="저장 없이 미리보기만")
    parser.add_argument("--limit", type=int, default=None, help="최대 처리 개수")
    parser.add_argument("--market", type=str, default=None, help="시장 필터 (us/kospi/kosdaq/...)")
    args = parser.parse_args()

    enrich(dry_run=args.dry_run, limit=args.limit, market_filter=args.market)
