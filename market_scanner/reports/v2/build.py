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
from html import escape
from pathlib import Path

from psycopg.types.json import Jsonb

from market_scanner.config.markets import MARKETS
from market_scanner.models import ScanSettings
from market_scanner.reports._common import enrich_metadata_frame
from market_scanner.reports.html_report import write_html
from market_scanner.reports.markdown_report import write_markdown
from market_scanner.reports.render import _load_render_frame
from market_scanner.reports.v2 import data, layout
from market_scanner.reports.v2.pages import main_page, market_page, sector_page
from market_scanner.storage.connection import connect

_DEFAULT_SETTINGS = ScanSettings(output_dir=Path("."))


SITE_V2_DIR = Path("site") / "v2"

_V2_NAV_CSS = """
<style>
.v2-nav-hdr{border-bottom:1px solid #2a313c;padding:12px 24px;background:#161b22;
  display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px;
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans KR",Roboto,sans-serif;}
.v2-nav-hdr .vt{font-size:17px;font-weight:600;color:#e6edf3;}
.v2-nav-hdr .vg{color:#8b95a5;font-size:13px;}
.v2-nav-hdr nav{display:flex;flex-wrap:wrap;gap:2px;align-items:center;}
.v2-nav-hdr nav a{padding:4px 10px;border-radius:6px;color:#8b95a5;font-size:13px;text-decoration:none;}
.v2-nav-hdr nav a:hover{color:#e6edf3;background:#1c2330;text-decoration:none;}
.v2-nav-hdr nav a.na{color:#e6edf3;font-weight:600;background:#1c2330;}
</style>"""


def _v2_nav_html(nav_active: str, depth: int) -> str:
    prefix = layout.rel_prefix(depth)
    links = "".join(
        f'<a href="{escape(prefix + href)}"'
        f'{" class=\"na\"" if key == nav_active else ""}>{escape(label)}</a>'
        for key, label, href in layout._NAV_ITEMS
    )
    return (
        _V2_NAV_CSS
        + f'\n<header class="v2-nav-hdr">'
        f'<div><span class="vt">SearchMarket</span>'
        f'<span class="vg"> · Daily Market Scan</span></div>'
        f"<nav>{links}</nav></header>"
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


def build_sector(conn, market_key: str, sector: str) -> Path:
    detail = data.load_sector_detail_data(conn, market_key, sector)
    html = sector_page.render(detail)
    slug = data.sector_slug(sector)
    path = SITE_V2_DIR / "markets" / market_key / "sectors" / slug / "index.html"
    _write_html(path, html)
    print(f"  v2 sector[{market_key}/{slug}]: {path}")
    return path


def build_market(conn, market_key: str) -> Path:
    detail = data.load_market_detail_data(conn, market_key)
    trade_date = detail.summary.trade_date if detail.summary else None
    path = SITE_V2_DIR / "markets" / market_key / "index.html"

    # Use v1-style rich page when market definition exists and data is available
    if trade_date and market_key in MARKETS:
        market_def = MARKETS[market_key]
        print(f"  loading {market_key} frame...")
        frame = _load_render_frame(conn, market_key, trade_date)
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
                path, v2_nav=_v2_nav_html(market_key, depth=2), skip_enrich=True,
            )
            print(f"  v2 market[{market_key}]: {path} (v1-style, {len(frame)} rows)")
        else:
            html = market_page.render(detail)
            _write_html(path, html)
            print(f"  v2 market[{market_key}]: {path} (simple)")
    else:
        html = market_page.render(detail)
        _write_html(path, html)
        print(f"  v2 market[{market_key}]: {path} (simple)")

    strategy_counts = {k: len(v) for k, v in detail.strategy_top.items()}
    content = path.read_text(encoding="utf-8") if path.exists() else ""
    _log_generated_report(
        conn,
        market_key=market_key,
        trade_date=trade_date,
        report_type="site_page",
        file_path=path,
        content=content,
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
    p_market = sub.add_parser("market", help="Build a single market page (+ its sectors).")
    p_market.add_argument("market_key", help="Market key (e.g. kospi, kosdaq, us).")
    p_sector = sub.add_parser("sector", help="Build a single sector page.")
    p_sector.add_argument("market_key")
    p_sector.add_argument("sector", help="Sector name (e.g. 전기전자).")
    sub.add_parser("all", help="Build main + every buildable market page + sectors.")

    args = parser.parse_args()
    with connect(args.database_url) as conn:
        primary_path: Path | None = None
        if args.command == "main":
            primary_path = build_main(conn)
        elif args.command == "market":
            primary_path = build_market(conn, args.market_key)
        elif args.command == "sector":
            primary_path = build_sector(conn, args.market_key, args.sector)
        elif args.command == "all":
            primary_path = build_main(conn)
            for market_key in data.list_buildable_markets(conn):
                build_market(conn, market_key)

    if primary_path is not None and not args.no_open:
        webbrowser.open(primary_path.resolve().as_uri())


if __name__ == "__main__":
    main()
