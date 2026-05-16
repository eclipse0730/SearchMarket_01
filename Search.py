from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from market_scanner.analysis.indicators import run_compute as compute_indicators
from market_scanner.analysis.screener import run_screen
from market_scanner.collectors.fundamentals import run_fetch as fetch_fundamentals
from market_scanner.collectors.prices import run_fetch as fetch_prices
from market_scanner.collectors.prices import run_retry as retry_prices
from market_scanner.config.markets import MARKETS
from market_scanner.domain.market_policy import home_market_key
from market_scanner.models import ScanSettings
from market_scanner.pipeline import (
    run_analysis_stage,
    run_news_stage,
    run_scan_stage_with_settings,
)
from market_scanner.services.instrument_names import run_fetch_name
from market_scanner.services.universe_refresh import refresh_master
from market_scanner.storage.diagnostics import table_counts
from market_scanner.storage.schema import init_db


def _today() -> str:
    return datetime.today().strftime("%Y%m%d")


def _scope(market_key: str, universe_key: str | None) -> tuple[str, str | None, str]:
    scan_market_key = home_market_key(market_key)
    effective_universe = universe_key or (market_key if market_key != scan_market_key else None)
    path_key = effective_universe or scan_market_key
    return scan_market_key, effective_universe, path_key


def _add_market(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("market", choices=sorted(MARKETS), help="Market key.")


def _add_universe(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--universe", default=None, help="Optional universe filter.")


def _add_date_range(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--date", default=None, help="Trade date YYYYMMDD.")
    parser.add_argument("--from", dest="date_from", default=None, help="Start date YYYYMMDD.")
    parser.add_argument("--to", dest="date_to", default=None, help="End date YYYYMMDD.")


def _add_database_url(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--database-url", default=None, help="Override DATABASE_URL.")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Thin command controller for the Search60 DB pipeline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  uv run python Search.py init\n"
            "  uv run python Search.py refresh us --universe sp500\n"
            "  uv run python Search.py price us --workers 1\n"
            "  uv run python Search.py scan us --universe sp500\n"
            "  uv run python Search.py all kospi --universe kospi200\n"
            "  uv run python Search.py site --no-open\n"
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    init_p = sub.add_parser("init", help="Initialize database schema/reference data.")
    _add_database_url(init_p)

    refresh_p = sub.add_parser("refresh", help="Refresh instruments and universe memberships.")
    refresh_p.add_argument("market", nargs="?", choices=sorted(MARKETS), help="Market key. Omit to refresh defaults.")
    _add_universe(refresh_p)
    refresh_p.add_argument("--date", default=None, help="Refresh date YYYYMMDD.")
    refresh_p.add_argument("--reset", action="store_true", help="Rewrite the selected universe membership.")
    _add_database_url(refresh_p)

    price_p = sub.add_parser("price", help="Collect daily prices.")
    _add_market(price_p)
    _add_date_range(price_p)
    price_p.add_argument("--limit", type=int, default=None)
    price_p.add_argument("--workers", type=int, default=1)
    price_p.add_argument("--force", action="store_true")
    _add_database_url(price_p)

    retry_price_p = sub.add_parser("retry-price", help="Retry failed price collection.")
    _add_market(retry_price_p)
    retry_price_p.add_argument("--run-id", type=int, default=None)
    _add_database_url(retry_price_p)

    fundamentals_p = sub.add_parser("fundamentals", help="Collect fundamentals.")
    _add_market(fundamentals_p)
    fundamentals_p.add_argument("--date", default=None, help="Trade date YYYYMMDD.")
    fundamentals_p.add_argument("--all", action="store_true", dest="fetch_all")
    fundamentals_p.add_argument("--stale-days", type=int, default=7)
    fundamentals_p.add_argument("--limit", type=int, default=None)
    fundamentals_p.add_argument("--workers", type=int, default=2)
    fundamentals_p.add_argument("--source", choices=["auto", "yahoo", "naver", "fdr"], default="auto")
    _add_database_url(fundamentals_p)

    indicators_p = sub.add_parser("indicators", help="Compute daily indicators.")
    _add_market(indicators_p)
    _add_date_range(indicators_p)
    indicators_p.add_argument("--limit", type=int, default=None)
    _add_database_url(indicators_p)

    screen_p = sub.add_parser("screen", help="Rank instruments and store scan results.")
    _add_market(screen_p)
    _add_universe(screen_p)
    screen_p.add_argument("--date", default=None, help="Trade date YYYYMMDD.")
    _add_database_url(screen_p)

    scan_p = sub.add_parser("scan", help="Run price -> indicators -> screen.")
    _add_market(scan_p)
    _add_universe(scan_p)
    scan_p.add_argument("--date", default=_today(), help="Trade date YYYYMMDD.")
    scan_p.add_argument("--limit", type=int, default=None)
    scan_p.add_argument("--workers", type=int, default=1)

    analyze_p = sub.add_parser("analyze", aliases=["render"], help="Render markdown report from scan results.")
    _add_market(analyze_p)
    _add_universe(analyze_p)
    analyze_p.add_argument("--date", default=_today(), help="Report date YYYYMMDD.")

    news_p = sub.add_parser("news", help="Collect news cache.")
    _add_market(news_p)
    _add_universe(news_p)
    news_p.add_argument("--date", default=_today(), help="Trade date YYYYMMDD.")
    news_p.add_argument("--symbols", type=int, default=50, help="Max symbols.")
    news_p.add_argument("--items", type=int, default=3, help="Max items per symbol.")
    news_p.add_argument("--workers", type=int, default=4)
    news_p.add_argument("--provider", choices=["all", "auto", "finnhub", "rss"], default="all")

    macro_p = sub.add_parser("macro", help="Collect macro indicators (rates, FX, commodities, crypto).")
    _add_date_range(macro_p)
    macro_p.add_argument("--days-back", type=int, default=90, help="Lookback days when an indicator has no history.")
    _add_database_url(macro_p)

    counts_p = sub.add_parser("counts", help="Print core table row counts.")
    _add_database_url(counts_p)

    names_p = sub.add_parser("names", help="Fetch Korean instrument names and sectors.")
    names_p.add_argument("market", choices=["kospi", "kosdaq"])
    names_p.add_argument("--all", action="store_true", dest="fetch_all")
    names_p.add_argument("--limit", type=int, default=None)
    names_p.add_argument("--delay", type=float, default=0.3)
    _add_database_url(names_p)

    site_p = sub.add_parser("site", help="Build the static site.")
    site_open = site_p.add_mutually_exclusive_group()
    site_open.add_argument("--open", dest="open_browser", action="store_true")
    site_open.add_argument("--no-open", dest="open_browser", action="store_false")
    site_p.set_defaults(open_browser=None)

    site_v2_p = sub.add_parser("site-v2", help="Build v2 static site pages.")
    site_v2_p.add_argument("target", choices=["main", "market", "sector", "admin", "all"])
    site_v2_p.add_argument("market", nargs="?")
    site_v2_p.add_argument("sector", nargs="?")
    site_v2_p.add_argument("--no-open", action="store_true")
    _add_database_url(site_v2_p)

    all_p = sub.add_parser("all", help="Run scan and then render markdown report.")
    _add_market(all_p)
    _add_universe(all_p)
    all_p.add_argument("--date", default=_today(), help="Trade date YYYYMMDD.")
    all_p.add_argument("--limit", type=int, default=None)
    all_p.add_argument("--workers", type=int, default=1)

    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    try:
        if args.command == "init":
            init_db(args.database_url)
            return

        if args.command == "refresh":
            refresh_master(args.market, args.universe, args.date, args.database_url, reset=args.reset)
            return

        if args.command == "price":
            fetch_prices(
                args.market,
                date_str=args.date,
                database_url=args.database_url,
                limit=args.limit,
                workers=max(1, args.workers),
                date_from=args.date_from,
                date_to=args.date_to,
                force=args.force,
            )
            return

        if args.command == "retry-price":
            retry_prices(args.market, run_id=args.run_id, database_url=args.database_url)
            return

        if args.command == "fundamentals":
            fetch_fundamentals(
                args.market,
                date_str=args.date or _today(),
                stale_only=not args.fetch_all,
                stale_days=args.stale_days,
                database_url=args.database_url,
                limit=args.limit,
                workers=max(1, args.workers),
                source=args.source,
            )
            return

        if args.command == "indicators":
            compute_indicators(args.market, args.date, args.database_url, args.limit, args.date_from, args.date_to)
            return

        if args.command == "screen":
            run_screen(args.market, date_str=args.date, universe_key=args.universe, database_url=args.database_url)
            return

        if args.command in {"scan", "all"}:
            market_key, _, path_key = _scope(args.market, args.universe)
            _, frame, _ = run_scan_stage_with_settings(
                market_key,
                args.date,
                ScanSettings(output_dir=Path("."), max_workers=max(1, args.workers), symbol_limit=args.limit),
                path_key=path_key,
            )
            if args.command == "all":
                run_analysis_stage(market_key, args.date, frame, path_key=path_key)
            return

        if args.command in {"analyze", "render"}:
            market_key, _, path_key = _scope(args.market, args.universe)
            run_analysis_stage(market_key, args.date, path_key=path_key)
            return

        if args.command == "news":
            market_key, _, path_key = _scope(args.market, args.universe)
            count = run_news_stage(
                market_key,
                args.date,
                path_key=path_key,
                max_symbols=max(0, args.symbols),
                items_per_symbol=max(1, args.items),
                max_workers=max(1, args.workers),
                provider=args.provider,
            )
            print(f"  news stored: {count} items")
            return

        if args.command == "macro":
            from market_scanner.collectors.macro import run_fetch as fetch_macro

            fetch_macro(
                date_str=args.date_to or args.date,
                date_from=args.date_from,
                database_url=args.database_url,
                days_back=args.days_back,
            )
            return

        if args.command == "counts":
            for table, count in table_counts(args.database_url).items():
                print(f"{table}: {count}")
            return

        if args.command == "names":
            run_fetch_name(
                args.market,
                stale_only=not args.fetch_all,
                limit=args.limit,
                database_url=args.database_url,
                delay=args.delay,
            )
            return

        if args.command == "site":
            from market_scanner.reports.site_builder import (
                SITE_DIR,
                _open_site_index,
                _should_open_browser_by_default,
                build_site,
            )

            pages = build_site()
            if not pages:
                raise ValueError("No reports were found. Generate at least one market report before building the site.")
            print(f"Built {len(pages)} site pages under {SITE_DIR}")
            open_browser = args.open_browser
            if open_browser is None:
                open_browser = _should_open_browser_by_default()
            if open_browser:
                _open_site_index()
            return

        if args.command == "site-v2":
            from market_scanner.reports.v2 import build as v2_build
            from market_scanner.reports.v2 import data as v2_data
            from market_scanner.storage.connection import connect

            with connect(args.database_url) as conn:
                primary_path = None
                if args.target == "main":
                    primary_path = v2_build.build_main(conn)
                elif args.target == "admin":
                    primary_path = v2_build.build_admin(conn)
                elif args.target == "market":
                    if not args.market:
                        raise ValueError("site-v2 market requires a market key")
                    if args.market == "us-all":
                        primary_path = v2_build.build_us_all(conn)
                    elif args.market == "kr-all":
                        primary_path = v2_build.build_kr_all(conn)
                    elif args.market in v2_data.UNIVERSE_DETAIL_PAGES:
                        primary_path = v2_build.build_universe_market(conn, args.market)
                    else:
                        primary_path = v2_build.build_market(conn, args.market)
                elif args.target == "sector":
                    if not args.market or not args.sector:
                        raise ValueError("site-v2 sector requires a market key and sector name")
                    primary_path = v2_build.build_sector(conn, args.market, args.sector)
                elif args.target == "all":
                    primary_path = v2_build.build_main(conn)
                    v2_build.build_admin(conn)
                    v2_build.build_us_all(conn)
                    v2_build.build_kr_all(conn)
                    for universe_key in v2_data.UNIVERSE_DETAIL_PAGES:
                        v2_build.build_universe_market(conn, universe_key)
                    for market_key in v2_data.list_buildable_markets(conn):
                        v2_build.build_market(conn, market_key)

            if primary_path is not None and not args.no_open:
                import webbrowser

                webbrowser.open(primary_path.resolve().as_uri())
            return

        parser.error(f"unsupported command: {args.command}")
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
