from __future__ import annotations

import time

from market_scanner.domain.market_policy import home_market_key
from market_scanner.storage.connection import connect


def run_fetch_name(
    market_key: str,
    stale_only: bool = True,
    limit: int | None = None,
    database_url: str | None = None,
    delay: float = 0.3,
) -> None:
    """Fetch local Korean instrument names/sectors and update instruments."""
    from market_scanner.config.markets import clear_db_instrument_meta_cache, fetch_naver_item_meta

    base_key = home_market_key(market_key)
    symbol_suffix = ".KS" if market_key == "kospi" else ".KQ"
    market_label = "KOSPI" if market_key == "kospi" else "KOSDAQ"

    with connect(database_url) as conn:
        if stale_only:
            rows = conn.execute(
                """
                SELECT instrument_id, symbol, name_local, name_en, sector
                FROM instruments
                WHERE market_key = %s
                  AND symbol LIKE %s
                  AND is_active = TRUE
                  AND (
                      name_local IS NULL
                      OR name_local = symbol
                      OR name_local = display_symbol
                      OR sector = 'Unknown'
                      OR sector IS NULL
                  )
                ORDER BY symbol
                """,
                (base_key, f"%{symbol_suffix}"),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT instrument_id, symbol, name_local, name_en, sector
                FROM instruments
                WHERE market_key = %s AND symbol LIKE %s AND is_active = TRUE
                ORDER BY symbol
                """,
                (base_key, f"%{symbol_suffix}"),
            ).fetchall()

        if limit:
            rows = rows[:limit]

        total = len(rows)
        if not total:
            print(f"  fetch_name [{market_key}]: 업데이트 대상 없음 (이미 모두 채워져 있음)")
            return

        print(f"  fetch_name [{market_key}]: {total} 종목 처리 시작")

        success, failed, skipped = 0, 0, 0
        for instrument_id, symbol, curr_name, curr_name_en, curr_sector in rows:
            code = str(symbol).replace(symbol_suffix, "").strip().zfill(6)

            name, sector = fetch_naver_item_meta(code)

            if not name and not sector:
                failed += 1
                if failed <= 10:
                    print(f"    FAIL: {symbol} ({code})")
                time.sleep(delay)
                continue

            new_name_local = name or curr_name
            new_name_en = curr_name_en
            if name and (not curr_name_en or curr_name_en == symbol or curr_name_en == code):
                new_name_en = name
            new_sector = sector or curr_sector
            label = market_label
            new_desc = f"{new_name_local} ({label})" if new_name_local else None

            conn.execute(
                """
                UPDATE instruments
                SET name_local = %s,
                    name_en    = %s,
                    sector     = %s,
                    description = COALESCE(%s, description)
                WHERE instrument_id = %s
                """,
                (new_name_local, new_name_en, new_sector, new_desc, instrument_id),
            )
            success += 1

            if success % 100 == 0:
                print(f"    {success + failed}/{total} 완료 ...")

            time.sleep(delay)

        if success:
            clear_db_instrument_meta_cache()

        print(
            f"  fetch_name [{market_key}] 완료: "
            f"success={success}  failed={failed}  skipped={skipped}"
        )

