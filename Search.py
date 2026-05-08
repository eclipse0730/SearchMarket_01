from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from market_scanner.config.markets import MARKETS
from market_scanner.domain.market_policy import home_market_key
from market_scanner.models import ScanSettings
from market_scanner.pipeline import (
    run_analysis_stage,
    run_news_stage,
    run_render_stage,
    run_scan_stage_with_settings,
)

def setup_scheduler(script_name: str, task_name: str, run_time: str = "08:05") -> None:
    script = os.path.abspath(script_name)
    python = sys.executable
    cmd = (
        f'schtasks /create /tn "{task_name}" '
        f'/tr "\\"{python}\\" \\"{script}\\"" '
        f'/sc daily /st {run_time} /f'
    )
    try:
        subprocess.run(cmd, shell=True, check=True, capture_output=True)
        print(f"  scheduler set: daily {run_time}")
        print(f"  task: {task_name}")
    except subprocess.CalledProcessError as exc:
        print(f"  scheduler failed: {exc}")


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
    # market_scanner.pipeline 의 stage 함수들에 위임합니다.
    parser = argparse.ArgumentParser(
        description="Multi-market moving-average scanner.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  uv run python Search.py --market us --universe sp500 --stage scan --limit 20\n"
            "  uv run python Search.py --market kospi\n"
            "  uv run python Search.py --market kospi --universe kospi200\n"
            "  uv run python Search.py --market kosdaq\n"
            "  uv run python Search.py --market kosdaq --universe kosdaq150 --stage scan\n"
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
        choices=["scan", "analyze", "news", "render", "all"],
        default="all",
        help="Pipeline stage to run (default: all). 'news' is an opt-in DB collection stage.",
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
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="Reserved for parallel-capable stages (default: 8).",
    )
    parser.add_argument("--limit", type=int, default=None, help="Limit scan to the first N symbols for quick validation.")
    parser.add_argument("--news-symbols", type=int, default=50, help="Max symbols for news collection (default: 50).")
    parser.add_argument("--news-items", type=int, default=3, help="Max news items per symbol (default: 3).")
    parser.add_argument("--news-workers", type=int, default=4, help="Parallel workers for news stage (default: 4).")
    parser.add_argument(
        "--news-provider",
        choices=["all", "auto", "finnhub", "rss"],
        default="all",
        help="News provider for the news stage (default: all).",
    )
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
    run_all = args.stage == "all"
    frame = None
    completed: list[str] = []
    effective_universe = requested_universe

    # scan: v2 DB 파이프라인으로 가격 수집 -> 지표 계산 -> 스크리닝을 수행합니다.
    if run_all or args.stage == "scan":
        try:
            _, frame, _ = run_scan_stage_with_settings(
                scan_market_key,
                date_str,
                ScanSettings(output_dir=Path("."), max_workers=max(1, args.workers), symbol_limit=args.limit),
                path_key=path_key,
            )
        except ValueError as exc:
            parser.error(str(exc))
        completed.append("scan_results")

    # analyze: DB 기반 스크리닝 결과로 Markdown 요약을 생성합니다.
    if run_all or args.stage == "analyze":
        _, paths = run_analysis_stage(scan_market_key, date_str, frame, path_key=path_key)
        completed.append(str(paths["md"]))

    # news: 외부 뉴스 요청이 느릴 수 있어 all에는 포함하지 않고 명시 실행할 때만 DB에 저장합니다.
    if args.stage == "news":
        try:
            news_count = run_news_stage(
                scan_market_key,
                date_str,
                path_key=path_key,
                max_symbols=max(0, args.news_symbols),
                items_per_symbol=max(1, args.news_items),
                max_workers=max(1, args.news_workers),
                provider=args.news_provider,
            )
        except ValueError as exc:
            parser.error(str(exc))
        print(f"  news stored: {news_count} items")
        completed.append("news_items")

    # render: DB의 scan_results를 기준으로 Markdown과 HTML 리포트를 생성합니다.
    if run_all or args.stage == "render":
        paths = run_render_stage(scan_market_key, date_str, path_key=path_key)
        if str(paths["md"]) not in completed and paths["md"].exists():
            completed.append(str(paths["md"]))
        completed.append(str(paths["html"]))

    scope_label = f"{scan_market_key}/{effective_universe}" if effective_universe else scan_market_key
    print(f"\n  done [{scope_label}]: {' | '.join(completed)}")


if __name__ == "__main__":
    main()
