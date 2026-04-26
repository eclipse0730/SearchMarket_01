from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, replace
from datetime import datetime
from html import escape
from pathlib import Path

import pandas as pd

from market_scanner.markets import MARKETS, _fetch_sp500_tickers, _us_static_meta
from market_scanner.models import MarketDefinition, ScanSettings
from market_scanner.pipeline import write_html, write_markdown


ROOT_DIR = Path(".")
SITE_DIR = ROOT_DIR / "site"
SITE_ARCHIVE_DIR = SITE_DIR / "archive"
SITE_ASSET_DIR = SITE_DIR / "assets"

_SPECIAL_PREFIXES: dict[str, tuple[str, str, str]] = {
    "us": ("Data", "Analysis", "Report"),
    "kospi": ("Data_Kospi", "Analysis_Kospi", "Report_Kospi"),
    "kosdaq": ("Data_Kosdaq", "Analysis_Kosdaq", "Report_Kosdaq"),
}

_ROOT_PAGES = [
    ("nasdaq100", "NASDAQ 100", "나스닥100 기술 대형주", "nasdaq100"),
    ("sp500", "S&P 500", "S&P 500 대형주 500종", "sp500"),
    ("kospi", "KOSPI", "코스피 대형주 시장", "kospi"),
    ("kosdaq", "KOSDAQ", "코스닥 성장주 시장", "kosdaq"),
    ("global-indices", "글로벌 지수", "주요 글로벌 지수 동향", "indices"),
    ("theme-proxies", "테마 ETF", "테마별 강세·약세 현황", "themes"),
    ("commodities", "원자재", "원자재 선물 동향", "commodities"),
]


@dataclass
class BuiltPage:
    key: str
    slug: str
    title: str
    description: str
    date_str: str
    frame: pd.DataFrame
    page_path: Path
    archive_path: Path


def _prefixes_for_market(market_key: str) -> tuple[str, str, str]:
    if market_key in _SPECIAL_PREFIXES:
        return _SPECIAL_PREFIXES[market_key]
    label = market_key.title().replace("-", "")
    return f"Data_{label}", f"Analysis_{label}", f"Report_{label}"


def _latest_date_for_prefix(prefix: str) -> str | None:
    pattern = re.compile(rf"^{re.escape(prefix)}_(\d{{8}})\.(csv|md|html)$")
    dates: list[str] = []
    for path in ROOT_DIR.glob(f"{prefix}_*.*"):
        match = pattern.match(path.name)
        if match:
            dates.append(match.group(1))
    return max(dates) if dates else None


def _latest_market_artifacts(market_key: str) -> tuple[str, Path, Path, Path] | None:
    csv_prefix, md_prefix, html_prefix = _prefixes_for_market(market_key)
    date_str = _latest_date_for_prefix(html_prefix) or _latest_date_for_prefix(csv_prefix)
    if not date_str:
        return None
    csv_path = ROOT_DIR / f"{csv_prefix}_{date_str}.csv"
    md_path = ROOT_DIR / f"{md_prefix}_{date_str}.md"
    html_path = ROOT_DIR / f"{html_prefix}_{date_str}.html"
    if not csv_path.exists() or not html_path.exists():
        return None
    return date_str, csv_path, md_path, html_path


def _ensure_site_dirs() -> None:
    if SITE_DIR.exists():
        shutil.rmtree(SITE_DIR)
    SITE_DIR.mkdir(parents=True, exist_ok=True)
    SITE_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    SITE_ASSET_DIR.mkdir(parents=True, exist_ok=True)
    (SITE_DIR / ".nojekyll").write_text("", encoding="utf-8")


def _load_frame(csv_path: Path) -> pd.DataFrame:
    return pd.read_csv(csv_path, encoding="utf-8-sig")


def _copy_text_file(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")


def _relative_href(target_slug: str, depth: int) -> str:
    prefix = "../" * depth
    if target_slug == "home":
        return f"{prefix}index.html" if depth > 0 else "index.html"
    return f"{prefix}{target_slug}/index.html"


def _site_nav(active_slug: str, depth: int) -> str:
    links: list[str] = []
    for _, title, _, slug in _ROOT_PAGES:
        href = _relative_href(slug, depth)
        cls = "site-nav-link active" if slug == active_slug else "site-nav-link"
        links.append(f'<a class="{cls}" href="{href}">{escape(title)}</a>')

    return (
        '<div class="site-shell">'
        '<style>'
        ':root{color-scheme:dark;}'
        'body{margin:0;background:#07111f;color:#dbe7f5;}'
        '.site-shell{position:sticky;top:0;z-index:30;background:rgba(7,17,31,.92);backdrop-filter:blur(14px);'
        'border-bottom:1px solid rgba(148,163,184,.18);padding:12px 18px;}'
        '.site-nav{display:flex;gap:10px;flex-wrap:wrap;align-items:center;max-width:1400px;margin:0 auto;}'
        '.site-brand{font:700 15px/1.2 Segoe UI,sans-serif;color:#f8fafc;text-decoration:none;margin-right:10px;}'
        '.site-nav-link{font:600 13px/1.2 Segoe UI,sans-serif;color:#94a3b8;text-decoration:none;padding:8px 12px;'
        'border-radius:999px;background:rgba(15,23,42,.55);border:1px solid rgba(148,163,184,.12);}'
        '.site-nav-link.active{color:#08111c;background:#8ec5ff;border-color:#8ec5ff;}'
        '</style>'
        '<div class="site-nav">'
        f'<a class="site-brand" href="{_relative_href("home", depth)}">Market Scanner</a>'
        + "".join(links) +
        "</div></div>"
    )


def _inject_site_shell(html: str, active_slug: str, depth: int) -> str:
    nav = _site_nav(active_slug, depth)
    if "<body>" in html:
        return html.replace("<body>", f"<body>{nav}", 1)
    return nav + html


def _format_date(date_str: str) -> str:
    try:
        return datetime.strptime(date_str, "%Y%m%d").strftime("%Y-%m-%d")
    except ValueError:
        return date_str


def _stat_number(frame: pd.DataFrame, column: str) -> str:
    if frame.empty or column not in frame.columns:
        return "-"
    series = pd.to_numeric(frame[column], errors="coerce").dropna()
    if series.empty:
        return "-"
    return f"{series.mean():.1f}"


def _near_count(frame: pd.DataFrame) -> int:
    if frame.empty:
        return 0
    if "near_count" in frame.columns:
        return int(pd.to_numeric(frame["near_count"], errors="coerce").fillna(0).gt(0).sum())
    near_cols = [column for column in frame.columns if column.startswith("near_")]
    if not near_cols:
        return 0
    return int(frame[near_cols].fillna(False).any(axis=1).sum())


_TREND_COLORS: dict[str, str] = {
    "Strong Uptrend":   "#22d3ee",
    "Uptrend":          "#4ade80",
    "Neutral":          "#94a3b8",
    "Downtrend":        "#f87171",
    "Strong Downtrend": "#ef4444",
}

_TREND_ARROWS: dict[str, str] = {
    "Strong Uptrend":   "⬆⬆",
    "Uptrend":          "⬆",
    "Neutral":          "→",
    "Downtrend":        "⬇",
    "Strong Downtrend": "⬇⬇",
}


def _overview_panel_html(frame: pd.DataFrame, title: str, subtitle: str = "") -> str:
    if frame.empty:
        return (
            '<div class="panel"><div class="panel-head">'
            f'<h3>{escape(title)}</h3></div>'
            '<p class="muted">데이터가 없습니다. 스캔 후 배포하면 표시됩니다.</p></div>'
        )

    working = frame.copy()
    for col in ("trend_score", "rsi", "from_high_pct"):
        working[col] = pd.to_numeric(working.get(col, pd.Series(dtype=float)), errors="coerce")

    sorted_df = working.sort_values("trend_score", ascending=False, na_position="last").head(12)

    trend_col = working["trend"] if "trend" in working.columns else pd.Series(dtype=str)
    up_count = int(trend_col.isin(["Strong Uptrend", "Uptrend"]).sum())
    dn_count = int(trend_col.isin(["Strong Downtrend", "Downtrend"]).sum())
    neu_count = len(working) - up_count - dn_count

    rows_html: list[str] = []
    for _, row in sorted_df.iterrows():
        symbol = escape(str(row.get("display_symbol") or row.get("symbol") or "-"))
        name = escape(str(row.get("name_local") or row.get("name_en") or "")[:18])
        trend = str(row.get("trend") or "")
        color = _TREND_COLORS.get(trend, "#94a3b8")
        arrow = _TREND_ARROWS.get(trend, "→")
        rsi = row.get("rsi")
        from_high = row.get("from_high_pct")
        rsi_str = f"{rsi:.0f}" if pd.notna(rsi) else "-"
        fh_str = f"{from_high:+.1f}%" if pd.notna(from_high) else "-"
        fh_color = (
            "#4ade80" if pd.notna(from_high) and float(from_high) >= -5
            else "#f87171" if pd.notna(from_high) and float(from_high) <= -20
            else "#94a3b8"
        )
        rows_html.append(
            f'<tr>'
            f'<td class="ov-sym">{symbol}</td>'
            f'<td class="ov-name">{name}</td>'
            f'<td class="ov-trend" style="color:{color}">{arrow}</td>'
            f'<td class="ov-num">{escape(rsi_str)}</td>'
            f'<td class="ov-num" style="color:{fh_color}">{escape(fh_str)}</td>'
            f'</tr>'
        )

    subtitle_html = f'<p class="panel-sub">{escape(subtitle)}</p>' if subtitle else ""
    return (
        '<div class="panel">'
        '<div class="panel-head">'
        f'<h3>{escape(title)}</h3>'
        '<div class="sentiment">'
        f'<span class="sent-up">▲{up_count}</span>'
        f'<span class="sent-neu">─{neu_count}</span>'
        f'<span class="sent-dn">▼{dn_count}</span>'
        '</div></div>'
        + subtitle_html
        + '<table class="ov-table">'
        '<thead><tr><th>종목</th><th>이름</th><th>추세</th><th>RSI</th><th>고점대비</th></tr></thead>'
        '<tbody>' + "".join(rows_html) + '</tbody>'
        '</table></div>'
    )


def _build_home_page(pages: list[BuiltPage], overview_frames: dict[str, pd.DataFrame]) -> None:
    cards: list[str] = []
    for key, title, description, slug in _ROOT_PAGES:
        page = next((item for item in pages if item.key == key or item.slug == slug), None)
        if not page:
            cards.append(
                "<a class='market-card disabled'>"
                f"<div class='eyebrow'>{escape(title)}</div>"
                "<h2>준비 중</h2>"
                f"<p>{escape(description)}</p>"
                "</a>"
            )
            continue

        cards.append(
            f"<a class='market-card' href='{page.slug}/index.html'>"
            f"<div class='eyebrow'>{escape(title)}</div>"
            f"<h2>{len(page.frame):,}개</h2>"
            f"<p>{escape(description)}</p>"
            "<dl>"
            f"<div><dt>갱신일</dt><dd>{escape(_format_date(page.date_str))}</dd></div>"
            f"<div><dt>MA 근접</dt><dd>{_near_count(page.frame)}</dd></div>"
            f"<div><dt>평균 RSI</dt><dd>{escape(_stat_number(page.frame, 'rsi'))}</dd></div>"
            "</dl>"
            "</a>"
        )

    indices_panel = _overview_panel_html(
        overview_frames.get("global-indices", pd.DataFrame()),
        "글로벌 지수",
        "주요 지수 추세 강도 순 정렬",
    )
    themes_panel = _overview_panel_html(
        overview_frames.get("theme-proxies", pd.DataFrame()),
        "테마 ETF",
        "테마별 강세·약세 현황",
    )
    commodities_panel = _overview_panel_html(
        overview_frames.get("commodities", pd.DataFrame()),
        "원자재",
        "원자재 선물 추세 동향",
    )

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>이동평균선 스캐너</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg: #06101d;
      --panel: rgba(10, 24, 41, 0.88);
      --border: rgba(148, 163, 184, 0.16);
      --text: #e2e8f0;
      --muted: #93a4b8;
      --accent: #8ec5ff;
      --accent-2: #f7b267;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Segoe UI", "Malgun Gothic", sans-serif;
      color: var(--text);
      background:
        radial-gradient(circle at top left, rgba(56, 189, 248, 0.18), transparent 28%),
        radial-gradient(circle at top right, rgba(251, 191, 36, 0.14), transparent 22%),
        linear-gradient(180deg, #07111f, #040a13 70%);
      min-height: 100vh;
    }}
    .wrap {{ max-width: 1360px; margin: 0 auto; padding: 32px 20px 72px; }}
    .hero {{ margin: 24px 0 28px; }}
    .eyebrow {{
      display: inline-flex;
      padding: 6px 12px;
      border-radius: 999px;
      background: rgba(142, 197, 255, 0.14);
      color: var(--accent);
      font-size: 12px;
      font-weight: 700;
      letter-spacing: .08em;
      text-transform: uppercase;
    }}
    h1 {{ font-size: clamp(32px, 5vw, 56px); line-height: 1.1; margin: 16px 0 12px; }}
    .lead {{ max-width: 860px; color: var(--muted); font-size: 17px; line-height: 1.7; }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 16px;
      margin-top: 28px;
    }}
    .market-card, .panel {{
      border: 1px solid var(--border);
      border-radius: 24px;
      background: var(--panel);
      box-shadow: 0 28px 80px rgba(0, 0, 0, 0.24);
    }}
    .market-card {{
      color: inherit;
      text-decoration: none;
      padding: 22px;
      transition: transform .18s ease, border-color .18s ease;
    }}
    .market-card:hover {{ transform: translateY(-2px); border-color: rgba(142, 197, 255, 0.38); }}
    .market-card.disabled {{ opacity: .55; pointer-events: none; }}
    .market-card h2 {{ margin: 14px 0 10px; font-size: 28px; }}
    .market-card p {{ margin: 0 0 16px; color: var(--muted); min-height: 40px; font-size: 14px; }}
    .market-card dl {{
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 10px;
      margin: 0;
    }}
    .market-card dt {{
      color: var(--muted);
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: .06em;
      margin-bottom: 4px;
    }}
    .market-card dd {{ margin: 0; font-weight: 700; font-size: 15px; }}
    .section-title {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: end;
      margin: 44px 0 18px;
    }}
    .section-title h2 {{ margin: 0; font-size: 24px; }}
    .section-title p {{ margin: 0; color: var(--muted); font-size: 14px; }}
    .overview-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
      gap: 16px;
    }}
    .panel {{ padding: 22px; }}
    .panel-head {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 14px;
    }}
    .panel-head h3 {{ margin: 0; font-size: 17px; }}
    .panel-sub {{ margin: -8px 0 12px; color: var(--muted); font-size: 12px; }}
    .muted {{ color: var(--muted); }}
    .sentiment {{ display: flex; gap: 10px; }}
    .sent-up  {{ color: #4ade80; font-weight: 700; font-size: 13px; }}
    .sent-neu {{ color: #94a3b8; font-weight: 700; font-size: 13px; }}
    .sent-dn  {{ color: #f87171; font-weight: 700; font-size: 13px; }}
    .ov-table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    .ov-table thead th {{
      font-size: 10px;
      text-transform: uppercase;
      letter-spacing: .06em;
      color: var(--muted);
      padding: 4px 6px;
      text-align: left;
      border-bottom: 1px solid rgba(148, 163, 184, 0.14);
    }}
    .ov-table tbody td {{
      padding: 7px 6px;
      border-bottom: 1px solid rgba(148, 163, 184, 0.06);
      vertical-align: middle;
    }}
    .ov-table tbody tr:last-child td {{ border-bottom: 0; }}
    .ov-sym  {{ font-weight: 700; white-space: nowrap; }}
    .ov-name {{ color: var(--muted); font-size: 12px; }}
    .ov-trend {{ text-align: center; font-size: 15px; }}
    .ov-num  {{ text-align: right; }}
    @media (max-width: 720px) {{
      .market-card dl {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  {_site_nav("home", 0)}
  <div class="wrap">
    <section class="hero">
      <div class="eyebrow">GitHub Pages · 매일 자동 갱신</div>
      <h1>이동평균선 스캐너</h1>
      <p class="lead">
        코스피 · 코스닥 · 미국 주요 지수를 매일 자동으로 스캔해
        60 / 120 / 240일 이동평균선 근접 종목을 추려냅니다.
        글로벌 지수 · 테마 ETF · 원자재 동향도 한눈에 확인하세요.
      </p>
    </section>

    <section>
      <div class="section-title">
        <h2>마켓</h2>
        <p>최신 스캔 결과 기준</p>
      </div>
      <div class="grid">
        {"".join(cards)}
      </div>
    </section>

    <section>
      <div class="section-title">
        <h2>시장 개요</h2>
        <p>글로벌 지수 · 테마 · 원자재 — 각 스캔 완료 후 자동으로 표시됩니다</p>
      </div>
      <div class="overview-grid">
        {indices_panel}
        {themes_panel}
        {commodities_panel}
      </div>
    </section>
  </div>
</body>
</html>
"""
    (SITE_DIR / "index.html").write_text(html, encoding="utf-8")


def _write_placeholder_page(slug: str, title: str, description: str) -> None:
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{escape(title)}</title>
  <style>
    :root {{ color-scheme: dark; }}
    body {{
      margin: 0;
      min-height: 100vh;
      background:
        radial-gradient(circle at top left, rgba(56, 189, 248, 0.18), transparent 26%),
        linear-gradient(180deg, #07111f, #040a13 70%);
      color: #e2e8f0;
      font-family: "Segoe UI", sans-serif;
    }}
    .wrap {{ max-width: 900px; margin: 0 auto; padding: 56px 20px; }}
    .panel {{
      margin-top: 28px;
      padding: 28px;
      border-radius: 24px;
      background: rgba(10, 24, 41, 0.88);
      border: 1px solid rgba(148, 163, 184, 0.16);
      box-shadow: 0 28px 80px rgba(0, 0, 0, 0.24);
    }}
    h1 {{ margin: 0 0 12px; font-size: clamp(32px, 5vw, 52px); }}
    p {{ color: #93a4b8; line-height: 1.7; }}
    a {{
      color: #8ec5ff;
      text-decoration: none;
      font-weight: 700;
    }}
  </style>
</head>
<body>
  {_site_nav(slug, 1)}
  <div class="wrap">
    <div class="panel">
      <h1>{escape(title)}</h1>
      <p>{escape(description)}</p>
      <p>This page will populate automatically after the next successful scan and Pages deployment.</p>
      <p><a href="../">Back to the main dashboard</a></p>
    </div>
  </div>
</body>
</html>
"""
    page_path = SITE_DIR / slug / "index.html"
    page_path.parent.mkdir(parents=True, exist_ok=True)
    page_path.write_text(html, encoding="utf-8")


def _archive_copy(html_text: str, date_str: str, slug: str) -> Path:
    archive_path = SITE_ARCHIVE_DIR / date_str / slug / "index.html"
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    archive_path.write_text(html_text, encoding="utf-8")
    return archive_path


def _copy_existing_report(
    market_key: str,
    slug: str,
    title: str,
    description: str,
    date_str: str,
    frame: pd.DataFrame,
    report_path: Path,
) -> BuiltPage:
    source_html = report_path.read_text(encoding="utf-8")
    html_text = _inject_site_shell(source_html, slug, 1)
    page_path = SITE_DIR / slug / "index.html"
    page_path.parent.mkdir(parents=True, exist_ok=True)
    page_path.write_text(html_text, encoding="utf-8")
    archive_path = _archive_copy(_inject_site_shell(source_html, slug, 3), date_str, slug)
    return BuiltPage(market_key, slug, title, description, date_str, frame, page_path, archive_path)


def _render_filtered_report(
    market: MarketDefinition,
    frame: pd.DataFrame,
    slug: str,
    title: str,
    description: str,
    date_str: str,
) -> BuiltPage:
    page_dir = SITE_DIR / slug
    page_dir.mkdir(parents=True, exist_ok=True)
    settings = ScanSettings(output_dir=page_dir)
    md_path = page_dir / "analysis.md"
    html_path = page_dir / "index.html"
    markdown_text = write_markdown(frame, market, settings, date_str, md_path)
    write_html(frame, market, settings, date_str, markdown_text, html_path)
    generated_html = html_path.read_text(encoding="utf-8")
    html_text = _inject_site_shell(generated_html, slug, 1)
    html_path.write_text(html_text, encoding="utf-8")
    archive_path = _archive_copy(_inject_site_shell(generated_html, slug, 3), date_str, slug)
    return BuiltPage(market.key, slug, title, description, date_str, frame, html_path, archive_path)


def _build_market_page(market_key: str, title: str, description: str, slug: str) -> BuiltPage | None:
    artifacts = _latest_market_artifacts(market_key)
    if not artifacts:
        return None
    date_str, csv_path, _, html_path = artifacts
    frame = _load_frame(csv_path)
    return _copy_existing_report(market_key, slug, title, description, date_str, frame, html_path)


def _latest_csv_for_market(market_key: str) -> tuple[str, Path] | None:
    csv_prefix, _, _ = _prefixes_for_market(market_key)
    date_str = _latest_date_for_prefix(csv_prefix)
    if not date_str:
        return None
    csv_path = ROOT_DIR / f"{csv_prefix}_{date_str}.csv"
    return (date_str, csv_path) if csv_path.exists() else None


def _build_derived_us_pages(source_page: BuiltPage) -> list[BuiltPage]:
    pages: list[BuiltPage] = []
    source_frame = source_page.frame.copy()
    source_market = MARKETS["us"]

    nasdaq_members = set(_us_static_meta().keys())
    nasdaq_frame = source_frame[source_frame["symbol"].astype(str).isin(nasdaq_members)].copy()
    if not nasdaq_frame.empty:
        nasdaq_market = replace(source_market, key="nasdaq100", label="NASDAQ 100", output_prefix="nasdaq100")
        pages.append(
            _render_filtered_report(
                nasdaq_market,
                nasdaq_frame,
                "nasdaq100",
                "NASDAQ 100",
                "Derived from the combined US scan",
                source_page.date_str,
            )
        )

    sp500_members = set(_fetch_sp500_tickers())
    sp500_frame = source_frame[source_frame["symbol"].astype(str).isin(sp500_members)].copy()
    if not sp500_frame.empty:
        sp500_market = replace(source_market, key="sp500", label="S&P 500", output_prefix="sp500")
        pages.append(
            _render_filtered_report(
                sp500_market,
                sp500_frame,
                "sp500",
                "S&P 500",
                "Derived from the combined US scan",
                source_page.date_str,
            )
        )

    return pages


_OVERVIEW_ONLY_MARKETS = {"global-indices", "theme-proxies", "commodities"}


def build_site() -> list[BuiltPage]:
    _ensure_site_dirs()
    built_pages: list[BuiltPage] = []
    overview_frames: dict[str, pd.DataFrame] = {}

    # Load us data in memory only (not written to site) to derive nasdaq100/sp500
    us_artifacts = _latest_market_artifacts("us")
    if us_artifacts:
        us_date_str, us_csv_path, _, us_html_path = us_artifacts
        us_frame = _load_frame(us_csv_path)
        us_source = BuiltPage("us", "us", "US Market", "", us_date_str, us_frame, us_html_path, us_html_path)
        derived = _build_derived_us_pages(us_source)
        built_pages.extend(derived)
        for p in derived:
            overview_frames[p.key] = p.frame

    for market_key, title, description, slug in _ROOT_PAGES:
        if market_key in {"nasdaq100", "sp500", "us"}:
            continue
        page = _build_market_page(market_key, title, description, slug)
        if page:
            built_pages.append(page)
            overview_frames[market_key] = page.frame
        elif market_key in _OVERVIEW_ONLY_MARKETS:
            csv_info = _latest_csv_for_market(market_key)
            if csv_info:
                overview_frames[market_key] = _load_frame(csv_info[1])

    _build_home_page(built_pages, overview_frames)
    built_keys = {page.key for page in built_pages}
    built_slugs = {page.slug for page in built_pages}
    for key, title, description, slug in _ROOT_PAGES:
        if key not in built_keys and slug not in built_slugs:
            _write_placeholder_page(slug, title, description)
    return built_pages


def main() -> None:
    pages = build_site()
    if not pages:
        raise SystemExit("No reports were found. Generate at least one market report before building the site.")
    print(f"Built {len(pages)} site pages under {SITE_DIR}")


if __name__ == "__main__":
    main()
