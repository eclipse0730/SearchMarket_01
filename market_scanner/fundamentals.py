from __future__ import annotations

import argparse
import time
from datetime import date, datetime
from typing import Any

import pandas as pd
from psycopg.types.json import Jsonb

from market_scanner.db import (
    connect,
    home_market_key,
    price_source_for_market,
    upsert_fundamentals,
)
from market_scanner.markets import MARKETS

_YF_RETRY = 2
_DEFAULT_WORKERS = 4


# ── yfinance info fetch ───────────────────────────────────────────────────────

def _fetch_yfinance_info(symbol: str) -> dict[str, Any]:
    try:
        import yfinance as yf
    except ImportError:
        return {}

    for attempt in range(_YF_RETRY):
        if attempt:
            time.sleep(attempt * 2)
        try:
            info = yf.Ticker(symbol).info
            if info and info.get("regularMarketPrice") is not None:
                return info
        except Exception:
            continue
    return {}


def _extract_fundamentals(info: dict[str, Any]) -> dict[str, Any]:
    def safe_float(key: str) -> float | None:
        val = info.get(key)
        if val is None:
            return None
        try:
            f = float(val)
            return None if pd.isna(f) else f
        except (TypeError, ValueError):
            return None

    roe_raw = safe_float("returnOnEquity")
    growth_raw = safe_float("revenueGrowth")
    return {
        "trailing_pe": safe_float("trailingPE"),
        "price_to_book": safe_float("priceToBook"),
        "return_on_equity": round(roe_raw * 100, 1) if roe_raw is not None else None,
        "revenue_growth": round(growth_raw * 100, 1) if growth_raw is not None else None,
        "market_cap": safe_float("marketCap"),
        "target_price": safe_float("targetMeanPrice"),
    }


# ── DB 조회 헬퍼 ──────────────────────────────────────────────────────────────

def _instruments_for_market(conn: Any, market_key: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT instrument_id, symbol
        FROM instruments
        WHERE market_key = %s AND is_active = TRUE
        ORDER BY symbol
        """,
        (home_market_key(market_key),),
    ).fetchall()
    return [{"instrument_id": row[0], "symbol": str(row[1])} for row in rows]


def _instruments_stale_fundamentals(
    conn: Any, market_key: str, stale_days: int = 7
) -> list[dict[str, Any]]:
    """fundamentals가 없거나 stale_days 이상 지난 종목."""
    rows = conn.execute(
        """
        SELECT i.instrument_id, i.symbol
        FROM instruments i
        LEFT JOIN (
            SELECT instrument_id, MAX(as_of_date) AS last_date
            FROM instrument_fundamentals
            GROUP BY instrument_id
        ) f ON f.instrument_id = i.instrument_id
        WHERE i.market_key = %s
          AND i.is_active = TRUE
          AND (f.last_date IS NULL OR f.last_date < CURRENT_DATE - %s)
        ORDER BY i.symbol
        """,
        (home_market_key(market_key), stale_days),
    ).fetchall()
    return [{"instrument_id": row[0], "symbol": str(row[1])} for row in rows]


# ── run ───────────────────────────────────────────────────────────────────────

def run_fetch(
    market_key: str,
    date_str: str | None = None,
    stale_only: bool = True,
    stale_days: int = 7,
    explicit_url: str | None = None,
    limit: int | None = None,
) -> None:
    trade_date = date.today() if not date_str else datetime.strptime(date_str, "%Y%m%d").date()
    source_provider = price_source_for_market(market_key)

    with connect(explicit_url) as conn:
        if stale_only:
            instruments = _instruments_stale_fundamentals(conn, market_key, stale_days)
        else:
            instruments = _instruments_for_market(conn, market_key)

        if limit:
            instruments = instruments[:limit]

        if not instruments:
            print(f"  fundamentals fetch [{market_key}]: no target instruments")
            return

        run_result = conn.execute(
            """
            INSERT INTO collection_runs (
                run_type, market_key, trade_date, source_provider, status, requested_count, params
            )
            VALUES ('fundamentals', %s, %s, 'yfinance', 'running', %s, %s)
            RETURNING run_id
            """,
            (
                home_market_key(market_key),
                trade_date,
                len(instruments),
                Jsonb({"mode": "fundamentals", "stale_only": stale_only, "stale_days": stale_days}),
            ),
        ).fetchone()
        run_id = str(run_result[0])

        print(f"  fundamentals fetch [{market_key}] {len(instruments)} symbols  run_id={run_id}")

        success, failed, skipped = 0, 0, 0
        error_samples: list[Any] = []

        for instr in instruments:
            instrument_id = instr["instrument_id"]
            symbol = instr["symbol"]

            info = _fetch_yfinance_info(symbol)
            if not info:
                failed += 1
                if len(error_samples) < 30:
                    error_samples.append({"symbol": symbol, "reason": "fetch_failed"})
                continue

            fundamentals = _extract_fundamentals(info)
            if all(v is None for v in fundamentals.values()):
                skipped += 1
                continue

            row = pd.Series(fundamentals)
            upsert_fundamentals(conn, instrument_id, trade_date, "yfinance", row, run_id)
            success += 1

            if success % 50 == 0:
                print(f"    {success}/{len(instruments)} ...")

        status = "success" if not failed else ("partial" if success else "failed")
        conn.execute(
            """
            UPDATE collection_runs
            SET status = %s, finished_at = now(),
                success_count = %s, failed_count = %s, skipped_count = %s,
                error_samples = %s
            WHERE run_id = %s
            """,
            (status, success, failed, skipped, Jsonb(error_samples), run_id),
        )
        print(
            f"  fundamentals fetch [{market_key}] done: "
            f"success={success} failed={failed} skipped={skipped} status={status}"
        )


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Weekly fundamentals collector (yfinance .info).")
    parser.add_argument("--database-url", default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    fetch_p = sub.add_parser("fetch", help="Fetch fundamentals for stale/missing instruments.")
    fetch_p.add_argument("--market", required=True, choices=sorted(MARKETS))
    fetch_p.add_argument("--date", default=None, help="as_of_date YYYYMMDD (default: today).")
    fetch_p.add_argument(
        "--all", action="store_true", dest="fetch_all",
        help="모든 종목을 대상으로 합니다 (기본: 7일 이상 지난 종목만).",
    )
    fetch_p.add_argument("--stale-days", type=int, default=7)
    fetch_p.add_argument("--limit", type=int, default=None)

    args = parser.parse_args()
    if args.command == "fetch":
        run_fetch(
            args.market,
            args.date,
            stale_only=not args.fetch_all,
            stale_days=args.stale_days,
            explicit_url=args.database_url,
            limit=args.limit,
        )


if __name__ == "__main__":
    main()
