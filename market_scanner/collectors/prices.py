from __future__ import annotations

import argparse

from market_scanner.config.markets import MARKETS
from market_scanner.domain.market_policy import home_market_key


_DEFAULT_FETCH_WORKERS = 1


def _collector_for_market(market_key: str):
    if market_key in {"kr", "kospi", "kosdaq"} or home_market_key(market_key) in {"kospi", "kosdaq"}:
        from market_scanner.collectors import price_kr

        return price_kr

    from market_scanner.collectors import price_us

    return price_us


def run_fetch(
    market_key: str,
    date_str: str | None = None,
    database_url: str | None = None,
    limit: int | None = None,
    workers: int = _DEFAULT_FETCH_WORKERS,
    date_from: str | None = None,
    date_to: str | None = None,
    force: bool = False,
    symbols: list[str] | None = None,
) -> None:
    _collector_for_market(market_key).run_fetch(
        market_key,
        date_str=date_str,
        database_url=database_url,
        limit=limit,
        workers=workers,
        date_from=date_from,
        date_to=date_to,
        force=force,
        symbols=symbols,
    )


def run_retry(
    market_key: str,
    run_id: str | None = None,
    database_url: str | None = None,
) -> None:
    _collector_for_market(market_key).run_retry(market_key, run_id, database_url)


def main() -> None:
    parser = argparse.ArgumentParser(description="Daily OHLCV price collector.")
    parser.add_argument("--database-url", default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    fetch_p = sub.add_parser("fetch", help="Incremental daily price fetch.")
    fetch_p.add_argument("market_arg", nargs="?", choices=sorted(MARKETS), help="Market to fetch.")
    fetch_p.add_argument("--market", choices=sorted(MARKETS))
    fetch_p.add_argument("--date", default=None, help="Single target date YYYYMMDD. Alias for --from/--to.")
    fetch_p.add_argument("--from", dest="date_from", default=None, help="Start date YYYYMMDD (default: end date).")
    fetch_p.add_argument("--to", dest="date_to", default=None, help="End date YYYYMMDD (default: US previous day, KR today).")
    fetch_p.add_argument("--force", action="store_true", help="Refetch the full requested range even if prices already exist.")
    fetch_p.add_argument("--limit", type=int, default=None)
    fetch_p.add_argument("--workers", type=int, default=_DEFAULT_FETCH_WORKERS)

    retry_p = sub.add_parser("retry", help="Retry failed symbols from the last prices run.")
    retry_p.add_argument("market_arg", nargs="?", choices=sorted(MARKETS), help="Market to retry.")
    retry_p.add_argument("--market", choices=sorted(MARKETS))
    retry_p.add_argument("--run-id", default=None, help="Specific run_id to retry.")

    args = parser.parse_args()

    try:
        market_key = args.market or args.market_arg
        if not market_key:
            raise ValueError("market is required")
        if args.command == "fetch":
            run_fetch(
                market_key,
                args.date,
                args.database_url,
                args.limit,
                args.workers,
                args.date_from,
                args.date_to,
                args.force,
            )
        elif args.command == "retry":
            run_retry(market_key, args.run_id, args.database_url)
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
