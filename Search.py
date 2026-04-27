from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from market_scanner.compat import (
    compat_paths,
    ensure_csv_exists,
    load_frame,
    run_analysis_stage,
    run_render_stage,
    run_scan_stage_with_settings,
    run_translate_stage,
    setup_scheduler,
)
from market_scanner.markets import MARKETS
from market_scanner.models import ScanSettings

_TRANSLATABLE = {"us"}


def main() -> None:
    market_choices = sorted(MARKETS.keys())
    parser = argparse.ArgumentParser(
        description="Multi-market moving-average scanner.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python Search.py --market us\n"
            "  python Search.py --market kospi\n"
            "  python Search.py --market kosdaq\n"
            "  python Search.py --market us --stage scan --force\n"
            "  python Search.py --market us --stage render\n"
        ),
    )
    parser.add_argument(
        "--market",
        choices=market_choices,
        default="us",
        metavar="MARKET",
        help=f"Market to scan. Choices: {', '.join(market_choices)}  (default: us)",
    )
    parser.add_argument(
        "--stage",
        choices=["scan", "analyze", "translate", "render", "all"],
        default="all",
        help="Pipeline stage to run (default: all). 'translate' is a no-op for markets other than 'us'.",
    )
    parser.add_argument(
        "--date",
        default=datetime.today().strftime("%Y%m%d"),
        help="Output date YYYYMMDD (default: today).",
    )
    parser.add_argument("--force", action="store_true", help="Rescan even if CSV already exists.")
    parser.add_argument("--workers", type=int, default=8, help="Parallel workers for scan stage (default: 8).")
    parser.add_argument(
        "--setup-scheduler",
        action="store_true",
        help="Register a daily Windows Task Scheduler entry.",
    )
    parser.add_argument("--time", default="08:05", help="Scheduler time HH:MM (default: 08:05).")
    args = parser.parse_args()

    if args.setup_scheduler:
        task_name = f"MarketScanner_{args.market.upper()}_Daily"
        setup_scheduler("Search.py", task_name, args.time)
        return

    market_key = args.market
    date_str = args.date
    paths = compat_paths(market_key, date_str)
    run_all = args.stage == "all"
    frame = None
    markdown = None
    completed: list[str] = []

    if run_all or args.stage == "scan":
        existing_csv = None
        if not args.force:
            try:
                existing_csv = ensure_csv_exists(market_key, date_str)
            except FileNotFoundError:
                existing_csv = None
        if existing_csv is not None:
            print(f"  scan skipped, reusing: {existing_csv}  (--force to refetch)")
            _, frame, _ = load_frame(market_key, date_str)
        else:
            _, frame, _ = run_scan_stage_with_settings(
                market_key,
                date_str,
                ScanSettings(output_dir=Path("."), max_workers=max(1, args.workers)),
            )
        completed.append(str(paths["csv"]))

    if run_all or args.stage == "analyze":
        ensure_csv_exists(market_key, date_str)
        if frame is None:
            _, frame, _ = load_frame(market_key, date_str)
        markdown, _ = run_analysis_stage(market_key, date_str, frame)
        completed.append(str(paths["md"]))

    if run_all or args.stage == "translate":
        if market_key in _TRANSLATABLE:
            ensure_csv_exists(market_key, date_str)
            if run_translate_stage(market_key, date_str):
                print(f"  translated: {paths['csv']}")
            frame = None
            if str(paths["csv"]) not in completed:
                completed.append(str(paths["csv"]))
        else:
            print(f"  translate: not supported for '{market_key}', skipped.")

    if run_all or args.stage == "render":
        ensure_csv_exists(market_key, date_str)
        if frame is None:
            _, frame, _ = load_frame(market_key, date_str)
        if markdown is None and paths["md"].exists():
            markdown = paths["md"].read_text(encoding="utf-8")
        run_render_stage(market_key, date_str, frame, markdown)
        completed.append(str(paths["html"]))

    print(f"\n  done [{market_key}]: {' | '.join(completed)}")


if __name__ == "__main__":
    main()
