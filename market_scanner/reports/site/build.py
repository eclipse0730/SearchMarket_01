"""정적 사이트 빌더 CLI.

사용:
    python -m market_scanner.reports.site.build main
    python -m market_scanner.reports.site.build admin
    python -m market_scanner.reports.site.build market kospi
    python -m market_scanner.reports.site.build all
"""
from __future__ import annotations

import argparse
import hashlib
import webbrowser
from dataclasses import replace
from datetime import date
from pathlib import Path

from psycopg.types.json import Jsonb

from market_scanner.config.markets import MARKETS
from market_scanner.models import ScanSettings
from market_scanner.reports._common import enrich_metadata_frame
from market_scanner.reports.html_report import write_html
from market_scanner.reports.markdown_report import write_markdown
from market_scanner.reports.render import _load_render_frame
from market_scanner.reports.site import data, layout
from market_scanner.reports.site.pages import admin_page, main_page, market_page, overview_page, sector_page
from market_scanner.storage.connection import connect

_DEFAULT_SETTINGS = ScanSettings(output_dir=Path("."))


SITE_DIR = Path("site")

_NAV_CSS = """
<style>
.site-nav-hdr{border-bottom:1px solid rgba(148,163,184,.18);padding:12px 24px;background:rgba(5,10,18,.72);
  display:flex;align-items:center;justify-content:flex-start;flex-wrap:wrap;gap:18px;
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans KR",Roboto,sans-serif;position:sticky;top:0;z-index:20;
  backdrop-filter:blur(14px);}
.site-nav-hdr .brand{color:#e6edf3;text-decoration:none;}
.site-nav-hdr .brand:hover{color:#62c7ff;text-decoration:none;}
.site-nav-hdr .vt{font-size:17px;font-weight:700;color:inherit;}
.site-nav-hdr .vg{color:#8fa3ba;font-size:13px;}
.site-nav-hdr nav{display:flex;flex-wrap:wrap;gap:4px;align-items:center;}
.site-nav-hdr .nav-item{position:relative;}
.site-nav-hdr .nav-link{display:inline-flex;align-items:center;gap:6px;padding:6px 10px;border-radius:6px;color:#8fa3ba;font-size:13px;text-decoration:none;}
.site-nav-hdr .nav-link:hover{color:#e6edf3;background:rgba(17,31,50,.92);text-decoration:none;}
.site-nav-hdr .nav-link.na{color:#e6edf3;font-weight:600;background:rgba(17,31,50,.92);}
.site-nav-hdr .nav-caret{color:#8fa3ba;font-size:10px;}
.site-nav-hdr .nav-menu{display:none;position:absolute;left:0;top:100%;min-width:170px;padding:7px;
  border:1px solid rgba(148,163,184,.18);border-radius:8px;background:rgba(8,19,33,.98);box-shadow:0 16px 36px rgba(0,0,0,.28);}
.site-nav-hdr .nav-item:hover .nav-menu,.site-nav-hdr .nav-item:focus-within .nav-menu{display:grid;gap:2px;}
.site-nav-hdr .nav-menu a{display:block;padding:7px 9px;border-radius:6px;color:#cbd5e1;font-size:12px;text-decoration:none;}
.site-nav-hdr .nav-menu a:hover,.site-nav-hdr .nav-menu a.na{color:#e6edf3;background:rgba(17,31,50,.92);}
</style>"""


def _nav_html(nav_active: str, depth: int) -> str:
    prefix = layout.rel_prefix(depth)
    return (
        _NAV_CSS
        + f'\n<header class="site-nav-hdr">'
        f'<a class="brand" href="{prefix}index.html"><span class="vt">SearchMarket</span>'
        f'<span class="vg"> · Daily Market Scan</span></a>'
        f"<nav>{layout.nav_links_html(depth, nav_active, active_class='na')}</nav></header>"
    )


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
    path = SITE_DIR / "index.html"
    _write_html(path, html)
    print(f"  main: {path}")

    _log_generated_report(
        conn,
        market_key=None,
        trade_date=page_data.generated_at,
        report_type="site_page",
        file_path=path,
        content=html,
        metadata={
            "page": "main",
            "version": "1",
            "macro_item_count": len(page_data.daily_macro_items),
            "macro_quote_count": len(page_data.macro_quotes),
        },
    )
    conn.commit()
    return path


def build_admin(conn) -> Path:
    page_data = data.load_admin_page_data(conn)
    html = admin_page.render(page_data)
    path = SITE_DIR / "admin" / "index.html"
    _write_html(path, html)
    print(f"  admin: {path}")

    _log_generated_report(
        conn,
        market_key=None,
        trade_date=page_data.generated_at.date(),
        report_type="site_page",
        file_path=path,
        content=html,
        metadata={
            "page": "admin",
            "version": "1",
            "table_count": len(page_data.tables),
            "preview_limit": page_data.preview_limit,
        },
    )
    conn.commit()
    return path


def build_us_all(conn) -> Path:
    page_data = data.load_us_all_data(conn)
    html = overview_page.render(page_data)
    path = SITE_DIR / "markets" / "us-all" / "index.html"
    _write_html(path, html)
    print(f"  us-all: {path}")

    _log_generated_report(
        conn,
        market_key=None,
        trade_date=page_data.generated_at,
        report_type="site_page",
        file_path=path,
        content=html,
        metadata={
            "page": "us-all",
            "version": "1",
            "market_count": len(page_data.market_cards),
            "top_stock_count": len(page_data.top_stocks),
            "sector_cell_count": len(page_data.sector_cells),
        },
    )
    conn.commit()
    return path


def build_kr_all(conn) -> Path:
    page_data = data.load_kr_all_data(conn)
    html = overview_page.render(page_data)
    path = SITE_DIR / "markets" / "kr-all" / "index.html"
    _write_html(path, html)
    print(f"  kr-all: {path}")

    _log_generated_report(
        conn,
        market_key=None,
        trade_date=page_data.generated_at,
        report_type="site_page",
        file_path=path,
        content=html,
        metadata={
            "page": "kr-all",
            "version": "1",
            "market_count": len(page_data.market_cards),
            "top_stock_count": len(page_data.top_stocks),
            "sector_cell_count": len(page_data.sector_cells),
        },
    )
    conn.commit()
    return path


def build_sector(conn, market_key: str, sector: str) -> Path:
    detail = data.load_sector_detail_data(conn, market_key, sector)
    html = sector_page.render(detail)
    slug = data.sector_slug(sector)
    path = SITE_DIR / "markets" / market_key / "sectors" / slug / "index.html"
    _write_html(path, html)
    print(f"  sector[{market_key}/{slug}]: {path}")
    return path


def build_market(conn, market_key: str, universe_key: str | None = None, label: str | None = None) -> Path:
    path_key = universe_key or market_key
    source_universe_key = market_key if universe_key else path_key
    detail = data.load_market_detail_data(
        conn,
        market_key,
        universe_key=universe_key,
        label=label,
        nav_key=path_key,
    )
    trade_date = (
        _latest_scan_date(conn, market_key, source_universe_key)
        if universe_key
        else detail.summary.trade_date if detail.summary else _latest_scan_date(conn, market_key, source_universe_key)
    )
    path = SITE_DIR / "markets" / path_key / "index.html"

    # Use v1-style rich page when market definition exists and data is available
    if trade_date and market_key in MARKETS:
        market_def = replace(MARKETS[market_key], label=label or MARKETS[market_key].label)
        print(f"  loading {path_key} frame...")
        frame = _load_render_frame(conn, market_key, trade_date, None)
        if universe_key:
            frame = _filter_frame_by_universe_membership(conn, frame, universe_key)
        if not frame.empty:
            print(f"  enriching {len(frame)} rows...")
            frame = enrich_metadata_frame(frame, market_def)
            date_str = trade_date.strftime("%Y%m%d")
            path.parent.mkdir(parents=True, exist_ok=True)
            md_path = path.parent / "analysis.md"
            print(f"  writing markdown...")
            markdown = write_markdown(
                frame, market_def, _DEFAULT_SETTINGS, date_str, md_path, skip_enrich=True,
            )
            print(f"  writing html...")
            write_html(
                frame, market_def, _DEFAULT_SETTINGS, date_str, markdown,
                path, site_nav=_nav_html(path_key, depth=2), skip_enrich=True,
            )
            print(f"  market[{path_key}]: {path} (v1-style, {len(frame)} rows)")
        else:
            html = market_page.render(detail)
            _write_html(path, html)
            print(f"  market[{path_key}]: {path} (simple)")
    else:
        html = market_page.render(detail)
        _write_html(path, html)
        print(f"  market[{path_key}]: {path} (simple)")

    strategy_counts = {k: len(v) for k, v in detail.strategy_top.items()}
    content = path.read_text(encoding="utf-8") if path.exists() else ""
    _log_generated_report(
        conn,
        market_key=market_key,
        trade_date=trade_date or date.today(),
        report_type="site_page",
        file_path=path,
        content=content,
        metadata={
            "page": "market",
            "version": "1",
            "market_key": market_key,
            "universe_key": universe_key,
            "sector_count": len(detail.sectors),
            "top_stock_count": len(detail.top_stocks),
            "strategy_top_counts": strategy_counts,
        },
    )
    conn.commit()
    return path


def _latest_scan_date(conn, market_key: str, universe_key: str):
    row = conn.execute(
        """
        SELECT MAX(trade_date)
        FROM scan_results
        WHERE market_key = %s AND universe_key = %s
        """,
        (market_key, universe_key),
    ).fetchone()
    return row[0] if row else None


def _filter_frame_by_universe_membership(conn, frame, universe_key: str):
    if frame.empty:
        return frame
    rows = conn.execute(
        """
        SELECT i.symbol
        FROM universe_memberships um
        JOIN instruments i ON i.instrument_id = um.instrument_id
        WHERE um.universe_key = %s
          AND um.effective_to IS NULL
        """,
        (universe_key,),
    ).fetchall()
    symbols = {row[0] for row in rows}
    if not symbols:
        return frame.iloc[0:0].copy()

    filtered = frame[frame["symbol"].isin(symbols)].copy()
    if "rank_no" in filtered.columns:
        filtered["rank_no"] = range(1, len(filtered) + 1)
    return filtered


def build_universe_market(conn, universe_key: str) -> Path:
    market_key, label = data.UNIVERSE_DETAIL_PAGES[universe_key]
    return build_market(conn, market_key, universe_key=universe_key, label=label)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build SearchMarket static site.")
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--no-open", action="store_true",
                        help="Do not open the built page in the browser.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("main", help="Build main (overview) page only.")
    sub.add_parser("admin", help="Build database table admin page only.")
    p_market = sub.add_parser("market", help="Build a single market page (+ its sectors).")
    p_market.add_argument("market_key", help="Market key or universe key (e.g. kospi, sp500).")
    p_sector = sub.add_parser("sector", help="Build a single sector page.")
    p_sector.add_argument("market_key")
    p_sector.add_argument("sector", help="Sector name (e.g. 전기전자).")
    sub.add_parser("all", help="Build main + every buildable market page + sectors.")

    args = parser.parse_args()
    with connect(args.database_url) as conn:
        primary_path: Path | None = None
        if args.command == "main":
            primary_path = build_main(conn)
        elif args.command == "admin":
            primary_path = build_admin(conn)
        elif args.command == "market":
            if args.market_key in data.UNIVERSE_DETAIL_PAGES:
                primary_path = build_universe_market(conn, args.market_key)
            else:
                primary_path = build_market(conn, args.market_key)
        elif args.command == "sector":
            primary_path = build_sector(conn, args.market_key, args.sector)
        elif args.command == "all":
            primary_path = build_main(conn)
            build_admin(conn)
            build_us_all(conn)
            build_kr_all(conn)
            for universe_key in data.UNIVERSE_DETAIL_PAGES:
                build_universe_market(conn, universe_key)
            for market_key in data.list_buildable_markets(conn):
                build_market(conn, market_key)

    if primary_path is not None and not args.no_open:
        webbrowser.open(primary_path.resolve().as_uri())


if __name__ == "__main__":
    main()
