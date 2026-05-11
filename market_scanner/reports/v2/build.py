"""v2 정적 사이트 빌더 CLI.

사용:
    python -m market_scanner.reports.v2.build main
    python -m market_scanner.reports.v2.build market kospi
    python -m market_scanner.reports.v2.build all
"""
from __future__ import annotations

import argparse
import hashlib
import webbrowser
from pathlib import Path

from psycopg.types.json import Jsonb

from market_scanner.reports.v2 import data
from market_scanner.reports.v2.pages import main_page, market_page
from market_scanner.storage.connection import connect


SITE_V2_DIR = Path("site") / "v2"


def _write_html(path: Path, html: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")


def _log_generated_report(
    conn,
    *,
    market_key: str | None,
    trade_date,
    report_type: str,
    file_path: Path,
    content: str,
    metadata: dict,
) -> None:
    conn.execute(
        """
        INSERT INTO generated_reports (
            market_key, trade_date, report_type, format,
            file_path, content_hash, metadata
        )
        VALUES (%s, %s, %s, 'html', %s, %s, %s)
        """,
        (
            market_key,
            trade_date,
            report_type,
            str(file_path),
            hashlib.sha256(content.encode("utf-8")).hexdigest(),
            Jsonb(metadata),
        ),
    )


def build_main(conn) -> Path:
    page_data = data.load_main_page_data(conn)
    html = main_page.render(page_data)
    path = SITE_V2_DIR / "index.html"
    _write_html(path, html)
    print(f"  v2 main: {path}")

    _log_generated_report(
        conn,
        market_key=None,
        trade_date=page_data.generated_at,
        report_type="site_page",
        file_path=path,
        content=html,
        metadata={
            "page": "main",
            "version": "v2",
            "market_count": len(page_data.market_cards),
            "top_stock_count": len(page_data.top_stocks),
            "sector_cell_count": len(page_data.sector_cells),
            "macro_quote_count": len(page_data.macro_quotes),
        },
    )
    conn.commit()
    return path


def build_market(conn, market_key: str) -> Path:
    detail = data.load_market_detail_data(conn, market_key)
    html = market_page.render(detail)
    path = SITE_V2_DIR / "markets" / market_key / "index.html"
    _write_html(path, html)
    print(f"  v2 market[{market_key}]: {path}")

    trade_date = detail.summary.trade_date if detail.summary else None
    strategy_counts = {k: len(v) for k, v in detail.strategy_top.items()}
    _log_generated_report(
        conn,
        market_key=market_key,
        trade_date=trade_date,
        report_type="site_page",
        file_path=path,
        content=html,
        metadata={
            "page": "market",
            "version": "v2",
            "market_key": market_key,
            "sector_count": len(detail.sectors),
            "top_stock_count": len(detail.top_stocks),
            "strategy_top_counts": strategy_counts,
        },
    )
    conn.commit()
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Build SearchMarket v2 static site.")
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--no-open", action="store_true",
                        help="Do not open the built page in the browser.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("main", help="Build main (overview) page only.")
    p_market = sub.add_parser("market", help="Build a single market page.")
    p_market.add_argument("market_key", help="Market key (e.g. kospi, kosdaq, us).")
    sub.add_parser("all", help="Build main + every buildable market page.")

    args = parser.parse_args()
    with connect(args.database_url) as conn:
        primary_path: Path | None = None
        if args.command == "main":
            primary_path = build_main(conn)
        elif args.command == "market":
            primary_path = build_market(conn, args.market_key)
        elif args.command == "all":
            primary_path = build_main(conn)
            for market_key in data.list_buildable_markets(conn):
                build_market(conn, market_key)

    if primary_path is not None and not args.no_open:
        webbrowser.open(primary_path.resolve().as_uri())


if __name__ == "__main__":
    main()
