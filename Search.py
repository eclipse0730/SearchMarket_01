from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from market_scanner.compat import (
    compat_paths,
    ensure_csv_exists,
    load_frame,
    run_analysis_stage,
    run_news_stage,
    run_render_stage,
    run_scan_stage_with_settings,
    run_translate_stage,
    setup_scheduler,
)
from market_scanner.db import home_market_key, scan_symbols_for_scope
from market_scanner.markets import MARKETS
from market_scanner.models import ScanSettings

_TRANSLATABLE = {"us", "nasdaq100", "sp500"}


def main() -> None:
    market_choices = sorted(MARKETS.keys())
    recommended_markets = [
        "us",
        "kospi",
        "kosdaq",
        "global-indices",
        "commodities",
    ]

    # CLI 옵션은 이 진입점에 모아두고, 실제 파이프라인 작업은
    # 기존 산출물 경로 호환을 위해 market_scanner.compat에 위임합니다.
    parser = argparse.ArgumentParser(
        description="Multi-market moving-average scanner.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  uv run python Search.py --market us --universe sp500 --stage scan --limit 20\n"
            "  uv run python Search.py --market kospi\n"
            "  uv run python Search.py --market kospi --universe kospi200\n"
            "  uv run python Search.py --market kosdaq\n"
            "  uv run python Search.py --market kosdaq --universe kosdaq150 --stage scan --force\n"
            "  uv run python Search.py --market us --universe sp500 --stage news\n"
            "  uv run python Search.py --market us --universe sp500 --stage render\n"
            "  uv run python Search.py --market us  # DB instruments 기준 US 전체 스캔\n"
        ),
    )
    parser.add_argument(
        "--market",
        default="us",
        metavar="MARKET",
        help=f"Market to scan. Recommended: {', '.join(recommended_markets)}  (default: us)",
    )
    parser.add_argument(
        "--stage",
        choices=["scan", "analyze", "translate", "news", "render", "all"],
        default="all",
        help="Pipeline stage to run (default: all). 'news' is an opt-in cache collection stage.",
    )
    parser.add_argument(
        "--universe",
        default=None,
        help="Optional universe filter. Defaults to all active instruments in the market.",
    )
    parser.add_argument(
        "--date",
        default=datetime.today().strftime("%Y%m%d"),
        help="Output date YYYYMMDD (default: today).",
    )
    parser.add_argument("--force", action="store_true", help="Rescan even if CSV already exists.")
    parser.add_argument("--workers", type=int, default=8, help="Parallel workers for scan stage (default: 8).")
    parser.add_argument("--limit", type=int, default=None, help="Limit scan to the first N symbols for quick validation.")
    parser.add_argument("--news-symbols", type=int, default=50, help="Max symbols for news collection (default: 50).")
    parser.add_argument("--news-items", type=int, default=3, help="Max news items per symbol (default: 3).")
    parser.add_argument("--news-workers", type=int, default=4, help="Parallel workers for news stage (default: 4).")
    parser.add_argument(
        "--setup-scheduler",
        action="store_true",
        help="Register a daily Windows Task Scheduler entry.",
    )
    parser.add_argument("--time", default="08:05", help="Scheduler time HH:MM (default: 08:05).")
    args = parser.parse_args()
    if args.market not in MARKETS:
        parser.error(f"unsupported market '{args.market}'. Supported markets: {', '.join(market_choices)}")

    # 스케줄러 등록은 스캔 실행이 아니라 로컬 실행 환경 설정 작업입니다.
    if args.setup_scheduler:
        task_name = f"MarketScanner_{args.market.upper()}_Daily"
        setup_scheduler("Search.py", task_name, args.time)
        return

    market_key = args.market
    scan_market_key = home_market_key(market_key)
    requested_universe = args.universe or (market_key if market_key != scan_market_key else None)
    date_str = args.date
    path_key = requested_universe or scan_market_key
    paths = compat_paths(path_key, date_str)
    run_all = args.stage == "all"
    frame = None
    markdown = None
    completed: list[str] = []
    scan_symbols = None
    effective_universe = requested_universe

    # scan: 같은 날짜 CSV가 이미 있으면 재사용하고, 없거나 --force면 시장 데이터를 새로 수집합니다.
    if run_all or args.stage == "scan":
        existing_csv = None
        if not args.force:
            try:
                existing_csv = ensure_csv_exists(scan_market_key, date_str, path_key=path_key)
            except FileNotFoundError:
                existing_csv = None
        if existing_csv is not None:
            print(f"  scan skipped, reusing: {existing_csv}  (--force to refetch)")
            _, frame, _ = load_frame(scan_market_key, date_str, path_key=path_key)
        else:
            try:
                scan_symbols, effective_universe = scan_symbols_for_scope(scan_market_key, requested_universe)
                if scan_symbols:
                    scope = effective_universe or f"{scan_market_key}:all"
                    print(f"  scan scope: {scope} ({len(scan_symbols)} symbols from DB)")
                else:
                    print("  scan scope: DB returned no symbols, falling back to market universe loader")
                    scan_symbols = None
            except ValueError as exc:
                parser.error(str(exc))
            except Exception as exc:
                print(f"  scan scope: DB lookup failed ({exc}), falling back to market universe loader")
                scan_symbols = None
            _, frame, _ = run_scan_stage_with_settings(
                scan_market_key,
                date_str,
                ScanSettings(output_dir=Path("."), max_workers=max(1, args.workers), symbol_limit=args.limit),
                symbols=scan_symbols,
                path_key=path_key,
            )
        completed.append(str(paths["csv"]))

    # analyze: CSV를 읽어 요약 Markdown 리포트를 생성합니다.
    if run_all or args.stage == "analyze":
        ensure_csv_exists(scan_market_key, date_str, path_key=path_key)
        if frame is None:
            _, frame, _ = load_frame(scan_market_key, date_str, path_key=path_key)
        markdown, _ = run_analysis_stage(scan_market_key, date_str, frame, path_key=path_key)
        completed.append(str(paths["md"]))

    # translate: US 계열 시장의 종목명/설명 번역과 섹터 보정을 CSV에 반영합니다.
    if run_all or args.stage == "translate":
        if scan_market_key in _TRANSLATABLE:
            ensure_csv_exists(scan_market_key, date_str, path_key=path_key)
            if run_translate_stage(scan_market_key, date_str, path_key=path_key):
                print(f"  translated: {paths['csv']}")
            frame = None
            if str(paths["csv"]) not in completed:
                completed.append(str(paths["csv"]))
        else:
            print(f"  translate: not supported for '{market_key}', skipped.")

    # news: 외부 뉴스 요청이 느릴 수 있어 all에는 포함하지 않고 명시 실행할 때만 캐시를 갱신합니다.
    if args.stage == "news":
        ensure_csv_exists(scan_market_key, date_str, path_key=path_key)
        news_count, news_path = run_news_stage(
            scan_market_key,
            date_str,
            path_key=path_key,
            max_symbols=max(0, args.news_symbols),
            items_per_symbol=max(1, args.news_items),
            max_workers=max(1, args.news_workers),
        )
        print(f"  news cached: {news_count} items -> {news_path}")
        completed.append(str(news_path))

    # render: CSV와 선택적 Markdown 분석문을 합쳐 HTML 리포트를 생성합니다.
    if run_all or args.stage == "render":
        ensure_csv_exists(scan_market_key, date_str, path_key=path_key)
        if frame is None:
            _, frame, _ = load_frame(scan_market_key, date_str, path_key=path_key)
        if markdown is None and paths["md"].exists():
            markdown = paths["md"].read_text(encoding="utf-8")
        run_render_stage(scan_market_key, date_str, frame, markdown, path_key=path_key)
        completed.append(str(paths["html"]))

    scope_label = f"{scan_market_key}/{effective_universe}" if effective_universe else scan_market_key
    print(f"\n  done [{scope_label}]: {' | '.join(completed)}")


if __name__ == "__main__":
    main()
