from __future__ import annotations

import argparse

from market_scanner.config.markets import MARKETS
from market_scanner.services.instrument_master import load_master
from market_scanner.services.instrument_names import run_fetch_name
from market_scanner.services.universe_refresh import _default_refresh_market_keys, refresh_master
from market_scanner.storage.diagnostics import table_counts
from market_scanner.storage.schema import init_db


def main() -> None:
    parser = argparse.ArgumentParser(description="SearchMarket Postgres utilities.")
    parser.add_argument("--database-url", default=None, help="Postgres DATABASE_URL. Defaults to env or local Docker URL.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init", help="Apply schema and seed reference tables.")

    master_parser = subparsers.add_parser("load-master", help="Load assets/instruments.json into instruments.")
    master_parser.add_argument("--market", choices=sorted(MARKETS.keys()), help="Only load one market's instrument master.")

    refresh_parser = subparsers.add_parser("refresh-master", help="Refresh instruments and universe memberships from market loaders.")
    refresh_parser.add_argument("--market", help="Only refresh one base market, for example us, kospi, kosdaq.")
    refresh_parser.add_argument("--universe", help="Only refresh one universe membership, for example kospi200 or sp500.")
    refresh_parser.add_argument("--date", default=None, help="Membership effective date YYYYMMDD (default: today).")
    refresh_parser.add_argument(
        "--reset",
        action="store_true",
        help="Clear only universe_memberships in the requested scope before refreshing. Instruments, prices, scan results, news, reports, and run logs are retained.",
    )

    subparsers.add_parser("counts", help="Print core table row counts.")

    fetch_name_parser = subparsers.add_parser(
        "fetch-name",
        help="Fetch Korean instrument names and sectors from Naver Finance.",
    )
    fetch_name_parser.add_argument(
        "--market", required=True, choices=["kospi", "kosdaq"],
        help="Target market: kospi or kosdaq.",
    )
    fetch_name_parser.add_argument(
        "--all", action="store_true", dest="fetch_all",
        help="Update all active instruments instead of only missing or stale names/sectors.",
    )
    fetch_name_parser.add_argument(
        "--limit", type=int, default=None, help="Maximum number of instruments to process.",
    )
    fetch_name_parser.add_argument(
        "--delay", type=float, default=0.3, help="Delay between instrument requests in seconds.",
    )

    args = parser.parse_args()
    if args.command == "init":
        init_db(args.database_url)
        print("database initialized")
    elif args.command == "load-master":
        count = load_master(args.market, args.database_url)
        scope = args.market or "all markets"
        print(f"loaded instrument master for {scope}: {count}")
    elif args.command == "refresh-master":
        if args.market and args.market not in MARKETS:
            parser.error(f"unsupported market '{args.market}'. Supported markets: {', '.join(_default_refresh_market_keys())}")
        try:
            summaries = refresh_master(args.market, args.universe, args.date, args.database_url, reset=args.reset)
        except ValueError as exc:
            parser.error(str(exc))
        total_fetched = sum(summary["comparison"]["fetched_count"] for summary in summaries.values())
        total_mismatch = sum(summary["comparison"]["mismatch_count"] for summary in summaries.values())
        total_new_instruments = sum(summary["instrument_added_count"] for summary in summaries.values())
        failed = [u for u, s in summaries.items() if s["comparison"]["fetched_count"] == 0]
        status_str = f" FAILED={','.join(failed)}" if failed else ""
        print(
            "refresh-master completed: "
            f"universes={len(summaries)} fetched={total_fetched} "
            f"mismatch={total_mismatch} new_instruments={total_new_instruments}{status_str}"
        )
    elif args.command == "counts":
        for table, count in table_counts(args.database_url).items():
            print(f"{table}: {count}")
    elif args.command == "fetch-name":
        run_fetch_name(
            args.market,
            stale_only=not args.fetch_all,
            limit=args.limit,
            explicit_url=args.database_url,
            delay=args.delay,
        )


if __name__ == "__main__":
    main()
