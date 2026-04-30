from __future__ import annotations

import argparse
import os
import re
import shutil
import webbrowser
from dataclasses import dataclass, replace
from datetime import datetime
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from market_scanner.markets import MARKETS, _fetch_sp500_tickers, _nasdaq100_static_meta
from market_scanner.models import MarketDefinition, ScanSettings
from market_scanner.pipeline import enrich_metadata_frame, write_html, write_markdown


ROOT_DIR = Path(".")
DATA_DIR = ROOT_DIR / "data"
ANALYSIS_DIR = ROOT_DIR / "analysis"
REPORT_DIR = ROOT_DIR / "reports"
SITE_DIR = ROOT_DIR / "site"
SITE_ARCHIVE_DIR = SITE_DIR / "archive"
SITE_ASSET_DIR = SITE_DIR / "assets"

_SPECIAL_PREFIXES: dict[str, tuple[str, str, str]] = {
    "us": ("Data", "Analysis", "Report"),
    "nasdaq100": ("Data_Nasdaq100", "Analysis_Nasdaq100", "Report_Nasdaq100"),
    "sp500": ("Data_Sp500", "Analysis_Sp500", "Report_Sp500"),
    "kospi": ("Data_Kospi", "Analysis_Kospi", "Report_Kospi"),
    "kosdaq": ("Data_Kosdaq", "Analysis_Kosdaq", "Report_Kosdaq"),
}

_ROOT_PAGES = [
    ("nasdaq100", "NASDAQ 100", "나스닥100 기술 대형주", "nasdaq100"),
    ("sp500", "S&P 500", "S&P 500 대형주 500종", "sp500"),
    ("dow30", "Dow 30", "미국 블루칩 30종", "dow30"),
    ("kospi", "KOSPI", "코스피 대형주 시장", "kospi"),
    ("kosdaq", "KOSDAQ", "코스닥 성장주 시장", "kosdaq"),
    ("global-indices", "글로벌 지수", "주요 글로벌 지수 동향", "indices"),
    ("theme-proxies", "테마 ETF", "테마별 강세·약세 현황", "themes"),
    ("commodities", "원자재", "원자재 선물 동향", "commodities"),
]

_DOW30_SYMBOLS = {
    "MMM", "AXP", "AMGN", "AMZN", "AAPL", "BA", "CAT", "CVX", "CSCO", "KO",
    "DIS", "GS", "HD", "HON", "IBM", "JNJ", "JPM", "MCD", "MRK", "MSFT",
    "NVDA", "NKE", "PG", "CRM", "SHW", "TRV", "UNH", "VZ", "V", "WMT",
}


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


def _dates_for_prefix(prefix: str, directory: Path = ROOT_DIR) -> list[str]:
    pattern = re.compile(rf"^{re.escape(prefix)}_(\d{{8}})\.(csv|md|html)$")
    dates: list[str] = []
    for path in directory.glob(f"{prefix}_*.*"):
        match = pattern.match(path.name)
        if match:
            dates.append(match.group(1))
    return dates


def _latest_date_for_prefix(prefix: str, directory: Path = ROOT_DIR) -> str | None:
    dates = _dates_for_prefix(prefix, directory)
    return max(dates) if dates else None


def _first_existing_path(*paths: Path) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return None


def _csv_path_for_date(prefix: str, date_str: str) -> Path:
    data_path = DATA_DIR / f"{prefix}_{date_str}.csv"
    if data_path.exists():
        return data_path
    return ROOT_DIR / f"{prefix}_{date_str}.csv"


def _csv_has_columns(path: Path) -> bool:
    if not path.exists() or path.stat().st_size <= 5:
        return False
    try:
        frame = pd.read_csv(path, encoding="utf-8-sig", nrows=1)
    except (pd.errors.EmptyDataError, OSError, UnicodeDecodeError):
        return False
    return bool(list(frame.columns))


def _latest_market_artifacts(market_key: str) -> tuple[str, Path, Path, Path | None] | None:
    csv_prefix, md_prefix, html_prefix = _prefixes_for_market(market_key)
    candidate_dates = sorted(
        set(_dates_for_prefix(html_prefix, REPORT_DIR))
        | set(_dates_for_prefix(html_prefix))
        | set(_dates_for_prefix(csv_prefix, DATA_DIR))
        | set(_dates_for_prefix(csv_prefix)),
        reverse=True,
    )
    for date_str in candidate_dates:
        csv_path = _csv_path_for_date(csv_prefix, date_str)
        if not _csv_has_columns(csv_path):
            continue
        md_path = _first_existing_path(
            ANALYSIS_DIR / f"{md_prefix}_{date_str}.md",
            ROOT_DIR / f"{md_prefix}_{date_str}.md",
        ) or ANALYSIS_DIR / f"{md_prefix}_{date_str}.md"
        html_path = _first_existing_path(
            REPORT_DIR / f"{html_prefix}_{date_str}.html",
            ROOT_DIR / f"{html_prefix}_{date_str}.html",
        )
        return date_str, csv_path, md_path, html_path
    return None


def _ensure_site_dirs() -> None:
    if SITE_DIR.exists():
        shutil.rmtree(SITE_DIR)
    SITE_DIR.mkdir(parents=True, exist_ok=True)
    SITE_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    SITE_ASSET_DIR.mkdir(parents=True, exist_ok=True)
    (SITE_DIR / ".nojekyll").write_text("", encoding="utf-8")


def _load_frame(csv_path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(csv_path, encoding="utf-8-sig")
    except pd.errors.EmptyDataError as exc:
        raise ValueError(f"CSV has no columns: {csv_path}") from exc


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


def _updated_at_text() -> str:
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M:%S KST")


def _inject_report_updated_at(html: str) -> str:
    if 'class="report-updated"' in html:
        return html
    updated = f'<p class="report-updated">갱신시간: {escape(_updated_at_text())}</p>'
    pattern = re.compile(r"(<h1>.*?</h1>\s*<p[^>]*>.*?</p>)", re.DOTALL)
    return pattern.sub(rf"\1\n    {updated}", html, count=1)


def _inject_site_shell(html: str, active_slug: str, depth: int) -> str:
    html = _inject_report_updated_at(html)
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


def _pct(value: float | None, digits: int = 0) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value):.{digits}f}%"


def _avg_number(frame: pd.DataFrame, column: str) -> float | None:
    if frame.empty or column not in frame.columns:
        return None
    series = pd.to_numeric(frame[column], errors="coerce").dropna()
    if series.empty:
        return None
    return float(series.mean())


def _market_frame_for_slug(
    pages: list[BuiltPage],
    overview_frames: dict[str, pd.DataFrame],
    key: str,
    slug: str,
) -> pd.DataFrame:
    page = next((item for item in pages if item.key == key or item.slug == slug), None)
    if page:
        return page.frame
    return overview_frames.get(key, pd.DataFrame())


def _market_stats(frame: pd.DataFrame) -> dict[str, float | int | str | None]:
    total = len(frame)
    if total == 0:
        return {
            "total": 0,
            "up_count": 0,
            "down_count": 0,
            "neutral_count": 0,
            "breadth": None,
            "avg_rsi": None,
            "near_count": 0,
            "near_ratio": None,
            "overbought_count": 0,
            "oversold_count": 0,
            "dominant_trend": "-",
        }

    trend_col = frame["trend"] if "trend" in frame.columns else pd.Series(dtype=str)
    up_count = int(trend_col.isin(["Strong Uptrend", "Uptrend"]).sum())
    down_count = int(trend_col.isin(["Strong Downtrend", "Downtrend"]).sum())
    neutral_count = total - up_count - down_count
    directional = up_count + down_count
    near = _near_count(frame)
    rsi = pd.to_numeric(frame.get("rsi", pd.Series(dtype=float)), errors="coerce")
    trend_counts = trend_col.fillna("Unknown").value_counts()

    return {
        "total": total,
        "up_count": up_count,
        "down_count": down_count,
        "neutral_count": neutral_count,
        "breadth": (up_count / directional * 100) if directional else None,
        "avg_rsi": float(rsi.dropna().mean()) if not rsi.dropna().empty else None,
        "near_count": near,
        "near_ratio": near / total * 100,
        "overbought_count": int(rsi.ge(70).sum()),
        "oversold_count": int(rsi.lt(35).sum()),
        "dominant_trend": str(trend_counts.index[0]) if not trend_counts.empty else "-",
    }


def _combined_frame(frames: list[pd.DataFrame]) -> pd.DataFrame:
    valid = [frame for frame in frames if not frame.empty]
    if not valid:
        return pd.DataFrame()
    combined = pd.concat(valid, ignore_index=True, sort=False)
    if "symbol" in combined.columns:
        combined = combined.drop_duplicates(subset=["symbol"], keep="first")
    return combined


def _safe_pct_value(value: object, fallback: float = 50.0) -> float:
    if value is None or pd.isna(value):
        return fallback
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _regime_label(stock_stats: dict[str, float | int | str | None], macro_stats: dict[str, float | int | str | None]) -> tuple[str, str]:
    stock_breadth = stock_stats.get("breadth")
    macro_breadth = macro_stats.get("breadth")
    avg_rsi = stock_stats.get("avg_rsi")

    stock_value = float(stock_breadth) if stock_breadth is not None else 50.0
    macro_value = float(macro_breadth) if macro_breadth is not None else 50.0
    rsi_value = float(avg_rsi) if avg_rsi is not None else 50.0

    if stock_value >= 58 and macro_value >= 52 and rsi_value < 68:
        return "Risk-On", "주식 강세 비율과 매크로 프록시가 함께 우호적인 구간입니다."
    if stock_value <= 42 or macro_value <= 38:
        return "Risk-Off", "강세 종목 비율이 약해 방어적 해석이 필요한 구간입니다."
    if rsi_value >= 65:
        return "Heated", "평균 RSI가 높아 추격 매수보다 속도 조절 확인이 유리합니다."
    return "Balanced", "뚜렷한 한쪽 쏠림보다 시장별 선별이 중요한 중립 구간입니다."


def _overall_market_score(
    stock_stats: dict[str, float | int | str | None],
    macro_stats: dict[str, float | int | str | None],
    avg_change: float | None,
) -> tuple[int, str, str, str]:
    stock_breadth = _safe_pct_value(stock_stats.get("breadth"))
    macro_breadth = _safe_pct_value(macro_stats.get("breadth"))
    avg_rsi = _safe_pct_value(stock_stats.get("avg_rsi"))
    rsi_balance = _clamp(100 - abs(avg_rsi - 52) * 3.2)
    change_score = _clamp(50 + (float(avg_change or 0.0) * 12))
    score = round(stock_breadth * 0.36 + macro_breadth * 0.24 + rsi_balance * 0.22 + change_score * 0.18)

    if score >= 65:
        return int(score), "강세 우위", "주식 체력과 매크로 흐름이 함께 버티는 구간입니다.", "green"
    if score <= 42:
        return int(score), "방어 필요", "강세 종목 비율과 위험자산 흐름이 약해진 구간입니다.", "red"
    return int(score), "중립 관찰", "방향성은 열려 있지만 시장별 선별이 더 중요한 구간입니다.", "gold"


def _pulse_card(title: str, value: str, subtitle: str, tone: str = "info") -> str:
    return (
        f'<div class="pulse-card tone-{tone}">'
        f'<span>{escape(title)}</span>'
        f'<strong>{escape(value)}</strong>'
        f'<p>{escape(subtitle)}</p>'
        '</div>'
    )


def _regime_display_label(regime: str) -> str:
    return {
        "Risk-On": "위험 선호",
        "Risk-Off": "위험 회피",
        "Heated": "과열",
        "Balanced": "중립",
    }.get(regime, regime)


def _market_change_rank(items: list[tuple[str, pd.DataFrame]]) -> tuple[tuple[str, float] | None, tuple[str, float] | None]:
    ranked: list[tuple[str, float]] = []
    for title, frame in items:
        change = _avg_change(frame)
        if change is not None:
            ranked.append((title, change))
    if not ranked:
        return None, None
    ranked.sort(key=lambda item: item[1], reverse=True)
    return ranked[0], ranked[-1]


def _macro_risk_label(macro_stats: dict[str, float | int | str | None], macro_change: float | None) -> tuple[str, str, str]:
    breadth = _safe_pct_value(macro_stats.get("breadth"))
    change = float(macro_change or 0.0)
    if breadth >= 58 and change >= 0:
        return "완화", "green", f"매크로 강세 비율 {_pct(breadth)}, 평균 등락 {change:+.2f}%"
    if breadth <= 42 or change <= -0.45:
        return "위험 확대", "red", f"매크로 강세 비율 {_pct(breadth)}, 평균 등락 {change:+.2f}%"
    return "중립", "gold", f"매크로 강세 비율 {_pct(breadth)}, 평균 등락 {change:+.2f}%"


def _top_candidate_card(frame: pd.DataFrame) -> tuple[str, str, str]:
    if frame.empty or "symbol" not in frame.columns:
        return "-", "데이터가 충분하지 않습니다.", "gold"

    working = frame.copy()
    for column in ("composite_score", "trend_score", "change_pct", "rsi", "volume_ratio"):
        working[column] = pd.to_numeric(working.get(column, pd.Series(dtype=float)), errors="coerce")

    if "composite_score" in working.columns and working["composite_score"].notna().any():
        selected = working.sort_values(["composite_score", "change_pct"], ascending=[False, False], na_position="last")
    else:
        selected = working.sort_values(["trend_score", "change_pct"], ascending=[False, False], na_position="last")

    row = selected.iloc[0]
    symbol = str(row.get("display_symbol") or row.get("symbol") or "-")
    name = _display_name(row)
    change = row.get("change_pct")
    rsi = row.get("rsi")
    detail = f"{name[:18]}"
    if pd.notna(change):
        detail += f" · 등락 {float(change):+.2f}%"
    if pd.notna(rsi):
        detail += f" · RSI {float(rsi):.1f}"
    tone = "green" if pd.notna(change) and float(change) >= 0 else "red" if pd.notna(change) else "gold"
    return symbol, detail, tone


def _market_pulse_html(pages: list[BuiltPage], overview_frames: dict[str, pd.DataFrame]) -> str:
    stock_items = [
        ("Nasdaq 100", _market_frame_for_slug(pages, overview_frames, "nasdaq100", "nasdaq100")),
        ("S&P 500", _market_frame_for_slug(pages, overview_frames, "sp500", "sp500")),
        ("KOSPI", _market_frame_for_slug(pages, overview_frames, "kospi", "kospi")),
        ("KOSDAQ", _market_frame_for_slug(pages, overview_frames, "kosdaq", "kosdaq")),
    ]
    stock_frames = [frame for _, frame in stock_items]
    macro_frames = [
        overview_frames.get("global-indices", pd.DataFrame()),
        overview_frames.get("theme-proxies", pd.DataFrame()),
        overview_frames.get("commodities", pd.DataFrame()),
    ]
    stock_stats = _market_stats(_combined_frame(stock_frames))
    macro_stats = _market_stats(_combined_frame(macro_frames))
    best_market, worst_market = _market_change_rank(stock_items)
    health_subtitle = f"강세 {stock_stats['up_count']} / 약세 {stock_stats['down_count']}"
    if best_market and worst_market:
        health_subtitle = f"최강 {best_market[0]} {best_market[1]:+.2f}% · 최약 {worst_market[0]} {worst_market[1]:+.2f}%"

    macro_combined = _combined_frame(macro_frames)
    macro_label, macro_tone, macro_subtitle = _macro_risk_label(macro_stats, _avg_change(macro_combined))
    leading_sector, lagging_sector = _sector_extremes(_combined_frame(stock_frames + [overview_frames.get("theme-proxies", pd.DataFrame())]))
    candidate_symbol, candidate_detail, candidate_tone = _top_candidate_card(_combined_frame(stock_frames))

    cards = [
        _pulse_card("주식 시장 체력", _pct(stock_stats["breadth"]), health_subtitle, "green" if _safe_pct_value(stock_stats.get("breadth")) >= 55 else "red" if _safe_pct_value(stock_stats.get("breadth")) <= 45 else "gold"),
        _pulse_card("매크로 리스크", macro_label, macro_subtitle, macro_tone),
        _pulse_card("섹터·테마 히트맵", leading_sector, f"약세 축: {lagging_sector}", "blue"),
        _pulse_card("오늘의 핵심 후보", candidate_symbol, candidate_detail, candidate_tone),
    ]
    return "".join(cards)


def _market_snapshot_table_html(pages: list[BuiltPage], overview_frames: dict[str, pd.DataFrame]) -> str:
    rows: list[str] = []
    for key, title, _, slug in _ROOT_PAGES:
        frame = _market_frame_for_slug(pages, overview_frames, key, slug)
        if frame.empty:
            rows.append(
                f'<tr class="muted-row"><td>{escape(title)}</td><td colspan="5">데이터 대기 중</td></tr>'
            )
            continue

        stats = _market_stats(frame)
        breadth = stats["breadth"]
        breadth_value = float(breadth) if breadth is not None else 0.0
        avg_rsi = stats["avg_rsi"]
        rsi_text = f"{float(avg_rsi):.1f}" if avg_rsi is not None else "-"
        near_ratio = stats["near_ratio"]
        near_text = _pct(float(near_ratio), 1) if near_ratio is not None else "-"
        bar_width = max(4, min(100, breadth_value)) if breadth is not None else 0
        trend = str(stats["dominant_trend"] or "-")
        trend_color = _TREND_COLORS.get(trend, "#94a3b8")
        rows.append(
            "<tr>"
            f'<td><a href="{escape(slug)}/index.html">{escape(title)}</a></td>'
            f'<td class="num">{int(stats["total"] or 0):,}</td>'
            f'<td><div class="breadth"><span style="width:{bar_width:.0f}%"></span></div><b>{_pct(breadth_value)}</b></td>'
            f'<td class="num">{escape(rsi_text)}</td>'
            f'<td class="num">{escape(near_text)}</td>'
            f'<td style="color:{trend_color}">{escape(trend)}</td>'
            "</tr>"
        )

    return (
        '<div class="panel wide-panel">'
        '<div class="panel-head"><h3>시장별 스냅샷</h3><p class="panel-sub inline">강세 비율, RSI, MA 근접률을 한 줄로 비교합니다.</p></div>'
        '<table class="snapshot-table">'
        '<thead><tr><th>시장</th><th>종목</th><th>강세 비율</th><th>평균 RSI</th><th>MA 근접률</th><th>대표 추세</th></tr></thead>'
        '<tbody>'
        + "".join(rows)
        + '</tbody></table></div>'
    )


def _sector_leadership_html(pages: list[BuiltPage], overview_frames: dict[str, pd.DataFrame]) -> str:
    frames = [
        _market_frame_for_slug(pages, overview_frames, "nasdaq100", "nasdaq100"),
        _market_frame_for_slug(pages, overview_frames, "sp500", "sp500"),
        _market_frame_for_slug(pages, overview_frames, "kospi", "kospi"),
        _market_frame_for_slug(pages, overview_frames, "kosdaq", "kosdaq"),
        overview_frames.get("theme-proxies", pd.DataFrame()),
    ]
    combined = _combined_frame(frames)
    required = {"sector", "trend_score", "rsi"}
    if combined.empty or not required.issubset(combined.columns):
        return (
            '<div class="panel"><div class="panel-head"><h3>섹터 리더십</h3></div>'
            '<p class="muted">섹터 데이터가 부족합니다.</p></div>'
        )

    working = combined.copy()
    working["trend_score"] = pd.to_numeric(working["trend_score"], errors="coerce")
    working["rsi"] = pd.to_numeric(working["rsi"], errors="coerce")
    grouped = (
        working.dropna(subset=["sector"])
        .groupby("sector")
        .agg(count=("sector", "size"), avg_trend=("trend_score", "mean"), avg_rsi=("rsi", "mean"))
    )
    grouped = grouped[grouped["count"] >= 2].sort_values(["avg_trend", "count"], ascending=[False, False]).head(8)
    rows = []
    for sector, row in grouped.iterrows():
        rows.append(
            '<tr>'
            f'<td>{escape(str(sector))}</td>'
            f'<td class="num">{int(row["count"])}</td>'
            f'<td class="num">{float(row["avg_trend"]):.1f}</td>'
            f'<td class="num">{float(row["avg_rsi"]):.1f}</td>'
            '</tr>'
        )
    return (
        '<div class="panel">'
        '<div class="panel-head"><h3>섹터 리더십</h3></div>'
        '<p class="panel-sub">주식/테마 ETF에서 추세 점수가 높은 섹터입니다.</p>'
        '<table class="ov-table"><thead><tr><th>섹터</th><th>수</th><th>추세</th><th>RSI</th></tr></thead>'
        '<tbody>' + "".join(rows) + '</tbody></table></div>'
    )


def _avg_change(frame: pd.DataFrame) -> float | None:
    return _avg_number(frame, "change_pct")


def _top_sector_text(frame: pd.DataFrame) -> str:
    leading, _ = _sector_extremes(frame)
    return leading


def _sector_extremes(frame: pd.DataFrame) -> tuple[str, str]:
    if frame.empty or "sector" not in frame.columns:
        return "-", "-"
    working = frame.copy()
    working["trend_score"] = pd.to_numeric(working.get("trend_score", pd.Series(dtype=float)), errors="coerce")
    working["change_pct"] = pd.to_numeric(working.get("change_pct", pd.Series(dtype=float)), errors="coerce")
    grouped = (
        working.dropna(subset=["sector"])
        .groupby("sector")
        .agg(count=("sector", "size"), avg_trend=("trend_score", "mean"), avg_change=("change_pct", "mean"))
    )
    grouped = grouped[grouped["count"] >= 2]
    if grouped.empty:
        return "-", "-"
    leading = grouped.sort_values(["avg_trend", "avg_change", "count"], ascending=[False, False, False])
    lagging = grouped.sort_values(["avg_trend", "avg_change", "count"], ascending=[True, True, False])
    return str(leading.index[0])[:24], str(lagging.index[0])[:24]


def _display_name(row: pd.Series) -> str:
    return str(row.get("name_local") or row.get("name_en") or row.get("display_symbol") or row.get("symbol") or "-")


def _preview_combined_frame(pages: list[BuiltPage], overview_frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    built_keys = {page.key for page in pages}
    title_by_key = {key: title for key, title, _, _ in _ROOT_PAGES}
    slug_by_key = {key: slug for key, _, _, slug in _ROOT_PAGES}

    for page in pages:
        frame = page.frame.copy()
        frame["_source_key"] = page.key
        frame["_source_title"] = title_by_key.get(page.key, page.title)
        frame["_source_slug"] = page.slug
        frames.append(frame)

    for key, frame in overview_frames.items():
        if key in built_keys or frame.empty:
            continue
        working = frame.copy()
        working["_source_key"] = key
        working["_source_title"] = title_by_key.get(key, key)
        working["_source_slug"] = slug_by_key.get(key, key)
        frames.append(working)

    return _combined_frame(frames)


def _preview_market_cards_html(
    pages: list[BuiltPage],
    overview_frames: dict[str, pd.DataFrame],
    *,
    depth: int = 1,
) -> str:
    cards: list[str] = []
    prefix = "../" * depth
    for key, title, description, slug in _ROOT_PAGES:
        frame = _market_frame_for_slug(pages, overview_frames, key, slug)
        if frame.empty:
            cards.append(
                '<article class="v2-market muted">'
                f'<div><span>{escape(title)}</span><strong>대기</strong></div>'
                f'<p>{escape(description)}</p>'
                '</article>'
            )
            continue

        stats = _market_stats(frame)
        avg_rsi = stats["avg_rsi"]
        avg_rsi_text = f"{float(avg_rsi):.1f}" if avg_rsi is not None else "-"
        breadth = float(stats["breadth"]) if stats.get("breadth") is not None else 0.0
        breadth_width = max(3, min(100, breadth)) if stats.get("breadth") is not None else 0
        change = _avg_change(frame)
        change_text = f"{change:+.2f}%" if change is not None else "-"
        change_cls = "up" if change is not None and change >= 0 else "down" if change is not None else "neutral"
        leading_sector, lagging_sector = _sector_extremes(frame)
        cards.append(
            f'<a class="v2-market" href="{prefix}{escape(slug)}/index.html">'
            f'<div><span>{escape(title)}</span><strong>{int(stats["total"] or 0):,}</strong></div>'
            f'<p>{escape(description)}</p>'
            '<dl>'
            f'<div class="wide"><dt>강세 비율</dt><dd><b>{escape(_pct(stats["breadth"]))}</b><i class="breadth-mini"><em style="width:{breadth_width:.0f}%"></em></i></dd></div>'
            f'<div><dt>RSI</dt><dd>{escape(avg_rsi_text)}</dd></div>'
            f'<div><dt>평균 등락</dt><dd class="{change_cls}">{escape(change_text)}</dd></div>'
            f'<div><dt>리딩 섹터</dt><dd>{escape(leading_sector)}</dd></div>'
            f'<div><dt>하락 섹터</dt><dd>{escape(lagging_sector)}</dd></div>'
            '</dl>'
            '</a>'
        )
    return "".join(cards)


def _market_for_source_key(source_key: object) -> MarketDefinition | None:
    key = str(source_key or "")
    if key == "dow30":
        key = "sp500"
    return MARKETS.get(key)


def _format_price_value(value: object, currency_symbol: str = "", decimals: int = 2) -> str:
    if value is None or pd.isna(value):
        return "-"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    if decimals <= 0:
        text = f"{number:,.0f}"
    else:
        text = f"{number:,.{decimals}f}"
    return f"{currency_symbol}{text}"


def _watchlist_quote_url(row: pd.Series, depth: int) -> str:
    symbol = str(row.get("symbol") or "")
    market = _market_for_source_key(row.get("_source_key"))
    if symbol and market is not None:
        return market.quote_url_builder(symbol)
    prefix = "../" * depth
    slug = str(row.get("_source_slug") or "index")
    return f"{prefix}{slug}/index.html"


def _watchlist_price_text(row: pd.Series) -> str:
    market = _market_for_source_key(row.get("_source_key"))
    if market is None:
        return _format_price_value(row.get("price"))
    return _format_price_value(row.get("price"), market.currency_symbol, market.price_decimals)


def _rsi_class(value: object) -> str:
    if value is None or pd.isna(value):
        return "neutral"
    rsi = float(value)
    if rsi >= 70:
        return "rsi-hot"
    if rsi <= 35:
        return "rsi-cold"
    return "neutral"


def _closest_ma_label(row: pd.Series) -> str:
    candidates: list[tuple[int, float]] = []
    for period in (60, 120, 240):
        value = row.get(f"diff_{period}")
        if pd.notna(value):
            candidates.append((period, float(value)))
    if not candidates:
        return "-"
    period, diff = min(candidates, key=lambda item: abs(item[1]))
    return f"MA{period} {diff:+.1f}%"


def _trend_arrow_html(trend: object) -> str:
    trend_text = str(trend or "")
    color = _TREND_COLORS.get(trend_text, "#94a3b8")
    arrow = _TREND_ARROWS.get(trend_text, "→")
    return f'<span class="trend-arrow" title="{escape(trend_text or "-")}" style="color:{color}">{escape(arrow)}</span>'


def _watchlist_rows(frame: pd.DataFrame, mode: str, limit: int = 8, depth: int = 1) -> str:
    if frame.empty or "symbol" not in frame.columns:
        return '<tr><td colspan="7" class="muted">데이터가 없습니다.</td></tr>'

    working = frame.copy()
    for column in (
        "trend_score",
        "rsi",
        "near_count",
        "from_high_pct",
        "change_pct",
        "diff_60",
        "diff_120",
        "diff_240",
        "price",
        "volume_ratio",
    ):
        working[column] = pd.to_numeric(working.get(column, pd.Series(dtype=float)), errors="coerce")

    if mode == "momentum":
        selected = working.sort_values(["trend_score", "change_pct"], ascending=[False, False], na_position="last")
    elif mode == "pullback":
        diff_cols = [column for column in ("diff_60", "diff_120", "diff_240") if column in working.columns]
        working["_closest_ma"] = working[diff_cols].abs().min(axis=1) if diff_cols else pd.NA
        selected = working[
            working["trend_score"].fillna(0).ge(3) & working["_closest_ma"].notna()
        ].sort_values(["_closest_ma", "trend_score"], ascending=[True, False], na_position="last")
    elif mode == "oversold":
        selected = working[working["rsi"].notna()].sort_values(["rsi", "trend_score"], ascending=[True, False])
    elif mode == "heated":
        selected = working[working["rsi"].notna()].sort_values(["rsi", "from_high_pct"], ascending=[False, False])
    elif mode == "weak-spike":
        selected = working[
            working["change_pct"].notna() & working["trend_score"].fillna(0).le(3)
        ].sort_values(["change_pct", "volume_ratio"], ascending=[False, False], na_position="last")
    elif mode == "volume":
        selected = working[
            working["volume_ratio"].notna()
        ].sort_values(["volume_ratio", "change_pct"], ascending=[False, False], na_position="last")
    else:
        selected = working

    rows: list[str] = []
    for _, row in selected.head(limit).iterrows():
        symbol = str(row.get("display_symbol") or row.get("symbol") or "-")
        market = str(row.get("_source_title") or "-")
        quote_url = _watchlist_quote_url(row, depth)
        change = row.get("change_pct")
        change_text = f"{float(change):+.2f}%" if pd.notna(change) else "-"
        change_cls = "up" if pd.notna(change) and float(change) >= 0 else "down" if pd.notna(change) else "neutral"
        rsi = row.get("rsi")
        rsi_text = f"{float(rsi):.1f}" if pd.notna(rsi) else "-"
        volume = row.get("volume_ratio")
        volume_text = f"{float(volume):.2f}x" if pd.notna(volume) else "-"
        rows.append(
            '<tr>'
            f'<td><a href="{escape(quote_url)}" target="_blank" rel="noopener noreferrer">{escape(symbol)}</a><small>{escape(_display_name(row)[:22])}</small></td>'
            f'<td>{escape(market)}</td>'
            f'<td>{escape(_watchlist_price_text(row))}</td>'
            f'<td class="{change_cls}">{escape(change_text)}</td>'
            f'<td class="{_rsi_class(rsi)}">{escape(rsi_text)}</td>'
            f'<td>{_trend_arrow_html(row.get("trend"))}</td>'
            f'<td>{escape(volume_text)}</td>'
            '</tr>'
        )
    return "".join(rows) if rows else '<tr><td colspan="7" class="muted">조건에 맞는 데이터가 없습니다.</td></tr>'


def _watchlist_panel(title: str, subtitle: str, rows: str) -> str:
    return (
        '<section class="v2-panel">'
        '<div class="v2-panel-head">'
        f'<h3>{escape(title)}</h3>'
        f'<p>{escape(subtitle)}</p>'
        '</div>'
        '<table class="v2-watch"><thead><tr><th>종목</th><th>시장</th><th>종가</th><th>등락</th><th>RSI</th><th>추세</th><th>거래량</th></tr></thead>'
        f'<tbody>{rows}</tbody></table>'
        '</section>'
    )


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
    pulse_cards = _market_pulse_html(pages, overview_frames)
    snapshot_table = _market_snapshot_table_html(pages, overview_frames)
    sector_leadership = _sector_leadership_html(pages, overview_frames)

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Market Scanner</title>
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
      --good: #4ade80;
      --bad: #f87171;
      --warn: #f7b267;
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
    .pulse-grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 14px;
      margin: 28px 0 8px;
    }}
    .pulse-card {{
      position: relative;
      overflow: hidden;
      min-height: 154px;
      padding: 20px;
      border-radius: 26px;
      border: 1px solid rgba(148, 163, 184, 0.16);
      background:
        linear-gradient(145deg, rgba(12, 28, 48, 0.96), rgba(7, 17, 31, 0.9)),
        radial-gradient(circle at top right, rgba(142, 197, 255, .16), transparent 40%);
      box-shadow: 0 28px 80px rgba(0, 0, 0, 0.26);
    }}
    .pulse-card::after {{
      content: "";
      position: absolute;
      inset: auto -32px -42px auto;
      width: 112px;
      height: 112px;
      border-radius: 999px;
      background: rgba(142, 197, 255, .16);
      filter: blur(2px);
    }}
    .pulse-card span {{
      display: block;
      color: var(--muted);
      font-size: 11px;
      font-weight: 800;
      letter-spacing: .11em;
      text-transform: uppercase;
    }}
    .pulse-card strong {{
      display: block;
      margin: 16px 0 10px;
      font-size: clamp(26px, 4vw, 38px);
      line-height: 1;
    }}
    .pulse-card p {{
      position: relative;
      z-index: 1;
      margin: 0;
      color: #b8c6d7;
      font-size: 13px;
      line-height: 1.55;
    }}
    .tone-green strong {{ color: var(--good); }}
    .tone-red strong {{ color: var(--bad); }}
    .tone-blue strong {{ color: var(--accent); }}
    .tone-gold strong {{ color: var(--warn); }}
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
    .insight-grid {{
      display: grid;
      grid-template-columns: minmax(0, 1.6fr) minmax(320px, .8fr);
      gap: 16px;
    }}
    .panel {{ padding: 22px; }}
    .wide-panel {{ min-width: 0; }}
    .panel-head {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 14px;
    }}
    .panel-head h3 {{ margin: 0; font-size: 17px; }}
    .panel-sub {{ margin: -8px 0 12px; color: var(--muted); font-size: 12px; }}
    .panel-sub.inline {{ margin: 0; text-align: right; }}
    .muted {{ color: var(--muted); }}
    .muted-row td {{ color: var(--muted); }}
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
    .snapshot-table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    .snapshot-table th {{
      padding: 8px 8px;
      color: var(--muted);
      border-bottom: 1px solid rgba(148, 163, 184, 0.14);
      font-size: 10px;
      text-align: left;
      text-transform: uppercase;
      letter-spacing: .06em;
    }}
    .snapshot-table td {{
      padding: 11px 8px;
      border-bottom: 1px solid rgba(148, 163, 184, 0.07);
      vertical-align: middle;
    }}
    .snapshot-table tbody tr:last-child td {{ border-bottom: 0; }}
    .snapshot-table a {{ color: #e2e8f0; font-weight: 800; text-decoration: none; }}
    .snapshot-table a:hover {{ color: var(--accent); }}
    .snapshot-table .num, .ov-table .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
    .breadth {{
      display: inline-block;
      width: 46px;
      height: 4px;
      margin-right: 9px;
      overflow: hidden;
      border-radius: 999px;
      background: rgba(148, 163, 184, 0.16);
      vertical-align: middle;
    }}
    .breadth span {{
      display: block;
      height: 100%;
      border-radius: inherit;
      background: #7dd3fc;
    }}
    @media (max-width: 720px) {{
      .market-card dl {{ grid-template-columns: 1fr; }}
      .panel-head {{ align-items: flex-start; flex-direction: column; }}
      .panel-sub.inline {{ text-align: left; }}
    }}
    @media (max-width: 980px) {{
      .pulse-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .insight-grid {{ grid-template-columns: 1fr; }}
    }}
    @media (max-width: 560px) {{
      .pulse-grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  {_site_nav("home", 0)}
  <div class="wrap">
    <section class="hero">
      <div class="eyebrow">GitHub Pages · 매일 자동 갱신</div>
      <h1>Market Scanner</h1>
      <p class="lead">
        코스피 · 코스닥 · 미국 주요 지수를 매일 자동으로 스캔해
        60 / 120 / 240일 이동평균선 근접 종목을 추려냅니다.
        글로벌 지수 · 테마 ETF · 원자재 동향도 한눈에 확인하세요.
      </p>
      <div class="pulse-grid">
        {pulse_cards}
      </div>
    </section>

    <section>
      <div class="section-title">
        <h2>통합 브리핑</h2>
        <p>시장 간 강도와 과열·과매도 신호를 압축한 요약입니다</p>
      </div>
      <div class="insight-grid">
        {snapshot_table}
        {sector_leadership}
      </div>
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


def _build_home_preview_page(
    pages: list[BuiltPage],
    overview_frames: dict[str, pd.DataFrame],
    *,
    page_path: Path | None = None,
    depth: int = 1,
    preview: bool = True,
) -> None:
    combined = _preview_combined_frame(pages, overview_frames)
    stock_frames = [
        _market_frame_for_slug(pages, overview_frames, "nasdaq100", "nasdaq100"),
        _market_frame_for_slug(pages, overview_frames, "sp500", "sp500"),
        _market_frame_for_slug(pages, overview_frames, "kospi", "kospi"),
        _market_frame_for_slug(pages, overview_frames, "kosdaq", "kosdaq"),
    ]
    macro_frames = [
        overview_frames.get("global-indices", pd.DataFrame()),
        overview_frames.get("theme-proxies", pd.DataFrame()),
        overview_frames.get("commodities", pd.DataFrame()),
    ]
    stock_stats = _market_stats(_combined_frame(stock_frames))
    macro_stats = _market_stats(_combined_frame(macro_frames))
    stock_breadth = float(stock_stats["breadth"]) if stock_stats.get("breadth") is not None else 0.0
    macro_breadth = float(macro_stats["breadth"]) if macro_stats.get("breadth") is not None else 0.0
    avg_change = _avg_change(combined)
    avg_change_text = f"{avg_change:+.2f}%" if avg_change is not None else "-"
    overall_score, overall_label, overall_note, overall_tone = _overall_market_score(stock_stats, macro_stats, avg_change)
    market_cards = _preview_market_cards_html(pages, overview_frames, depth=depth)
    watchlists = [
        _watchlist_panel("강한 모멘텀", "추세 점수와 당일 등락이 함께 강한 후보", _watchlist_rows(combined, "momentum", depth=depth)),
        _watchlist_panel("이동평균 눌림목", "강한 추세 안에서 이동평균선에 가까운 후보", _watchlist_rows(combined, "pullback", depth=depth)),
        _watchlist_panel("과매도 반등", "RSI가 낮아 반등 관찰이 필요한 후보", _watchlist_rows(combined, "oversold", depth=depth)),
        _watchlist_panel("과열 주의", "RSI 과열과 고점 근접을 함께 보는 위험 후보", _watchlist_rows(combined, "heated", depth=depth)),
        _watchlist_panel("약세 추세 급등", "약하거나 횡보 중인 추세에서 상승률이 튀는 후보", _watchlist_rows(combined, "weak-spike", depth=depth)),
        _watchlist_panel("거래량 급증", "평균 대비 거래량이 크게 늘어난 후보", _watchlist_rows(combined, "volume", depth=depth)),
    ]
    generated_at = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M:%S KST")
    page_title = "Market Scanner Preview" if preview else "Market Scanner"
    eyebrow_text = "종합 시장 점수 미리보기" if preview else "종합 시장 점수"
    nav_html = _site_nav("home", depth)
    preview_bar = (
        '<div class="preview-bar">'
        f'<span>홈 v2 미리보기 - 생성 {escape(generated_at)}</span>'
        '<a href="../index.html">메인으로 돌아가기</a>'
        '</div>'
        if preview
        else (
            '<div class="preview-bar">'
            f'<span>Market Scanner - 생성 {escape(generated_at)}</span>'
            '<span>최신 대시보드</span>'
            '</div>'
        )
    )

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{escape(page_title)}</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg: #060d17;
      --panel: rgba(11, 23, 38, .88);
      --panel-2: rgba(15, 31, 50, .76);
      --line: rgba(148, 163, 184, .16);
      --line-strong: rgba(148, 163, 184, .28);
      --text: #e6edf3;
      --muted: #92a4b8;
      --accent: #7dd3fc;
      --good: #4ade80;
      --bad: #f87171;
      --warn: #f7b267;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      background:
        radial-gradient(circle at 12% -8%, rgba(125, 211, 252, .16), transparent 30%),
        radial-gradient(circle at 92% 2%, rgba(247, 178, 103, .12), transparent 26%),
        linear-gradient(180deg, #07111f, #040811 72%);
      color: var(--text);
      font-family: "Segoe UI", "Malgun Gothic", sans-serif;
    }}
    .wrap {{ max-width: 1480px; margin: 0 auto; padding: 28px 18px 72px; }}
    .preview-bar {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: center;
      padding: 10px 0 22px;
      color: var(--muted);
      font-size: 12px;
    }}
    .preview-bar a {{ color: var(--accent); text-decoration: none; font-weight: 800; }}
    .hero-v2 {{
      display: grid;
      grid-template-columns: minmax(0, 1.05fr) minmax(360px, .95fr);
      gap: 18px;
      align-items: stretch;
      margin-bottom: 18px;
    }}
    .hero-copy, .v2-panel, .v2-market {{
      border: 1px solid var(--line);
      background: var(--panel);
      box-shadow: 0 28px 80px rgba(0, 0, 0, .24);
    }}
    .hero-copy {{ padding: 28px; border-radius: 22px; }}
    .eyebrow {{
      display: inline-flex;
      padding: 5px 10px;
      border-radius: 999px;
      background: rgba(125, 211, 252, .11);
      color: var(--accent);
      font-size: 11px;
      font-weight: 900;
      letter-spacing: .1em;
      text-transform: uppercase;
    }}
    h1 {{ margin: 14px 0 12px; font-size: clamp(32px, 5vw, 58px); line-height: 1.05; }}
    .lead {{ margin: 0; max-width: 760px; color: #b9c8d8; font-size: 16px; line-height: 1.7; }}
    .score-state {{ color: var(--muted); font-size: 24px; font-weight: 900; }}
    .score-state.tone-green {{ color: var(--good); }}
    .score-state.tone-red {{ color: var(--bad); }}
    .score-state.tone-gold {{ color: var(--warn); }}
    .regime {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
      margin-top: 24px;
    }}
    .regime div {{ padding: 14px; border: 1px solid var(--line); border-radius: 14px; background: rgba(6, 14, 25, .56); }}
    .regime span {{ display: block; color: var(--muted); font-size: 11px; font-weight: 900; text-transform: uppercase; }}
    .regime strong {{ display: block; margin-top: 8px; font-size: 24px; }}
    .pulse-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }}
    .pulse-card {{
      min-height: 150px;
      padding: 18px;
      border: 1px solid var(--line);
      border-radius: 18px;
      background: var(--panel-2);
    }}
    .pulse-card span {{ color: var(--muted); font-size: 11px; font-weight: 900; letter-spacing: .08em; text-transform: uppercase; }}
    .pulse-card strong {{ display: block; margin: 14px 0 8px; font-size: 30px; line-height: 1; }}
    .pulse-card p {{ margin: 0; color: #b9c8d8; font-size: 13px; line-height: 1.5; }}
    .tone-green strong, .up {{ color: var(--good); }}
    .tone-red strong, .down {{ color: var(--bad); }}
    .neutral {{ color: var(--muted); }}
    .tone-blue strong {{ color: var(--accent); }}
    .tone-gold strong {{ color: var(--warn); }}
    .section-head {{ display: flex; justify-content: space-between; align-items: end; gap: 16px; margin: 30px 0 14px; }}
    .section-head h2 {{ margin: 0; font-size: 23px; }}
    .section-head p {{ margin: 0; color: var(--muted); font-size: 13px; }}
    .market-grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }}
    .v2-market {{
      display: block;
      min-height: 214px;
      padding: 18px;
      border-radius: 18px;
      color: inherit;
      text-decoration: none;
    }}
    .v2-market:hover {{ border-color: rgba(125, 211, 252, .45); transform: translateY(-1px); }}
    .v2-market.muted {{ opacity: .58; }}
    .v2-market > div {{ display: flex; justify-content: space-between; gap: 12px; align-items: start; }}
    .v2-market span {{ color: var(--accent); font-size: 26px; line-height: 1; font-weight: 900; }}
    .v2-market strong {{ font-size: 12px; line-height: 1; }}
    .v2-market p {{ min-height: 38px; margin: 14px 0 14px; color: var(--muted); font-size: 13px; line-height: 1.45; }}
    .v2-market dl {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 9px; margin: 0; }}
    .v2-market .wide {{ grid-column: 1 / -1; }}
    .v2-market dt {{ color: var(--muted); font-size: 10px; font-weight: 900; text-transform: uppercase; }}
    .v2-market dd {{ margin: 3px 0 0; font-weight: 900; font-size: 14px; }}
    .v2-market dd b {{ display: inline-block; min-width: 46px; font: inherit; }}
    .breadth-mini {{
      display: inline-block;
      width: 50%;
      max-width: 110px;
      height: 4px;
      margin-left: 8px;
      overflow: hidden;
      border-radius: 999px;
      background: rgba(148, 163, 184, .16);
      vertical-align: middle;
    }}
    .breadth-mini em {{
      display: block;
      height: 100%;
      border-radius: inherit;
      background: #7dd3fc;
    }}
    .watch-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }}
    .v2-panel {{ padding: 18px; border-radius: 18px; min-width: 0; }}
    .v2-panel-head {{ display: flex; justify-content: space-between; gap: 12px; align-items: start; margin-bottom: 12px; }}
    .v2-panel h3 {{ margin: 0; font-size: 17px; }}
    .v2-panel p {{ margin: 2px 0 0; color: var(--muted); font-size: 12px; text-align: right; }}
    .v2-watch {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
    .v2-watch th {{ color: var(--muted); font-size: 10px; text-transform: uppercase; letter-spacing: .05em; text-align: left; padding: 7px 6px; border-bottom: 1px solid var(--line); }}
    .v2-watch td {{ padding: 9px 6px; border-bottom: 1px solid rgba(148, 163, 184, .08); vertical-align: top; }}
    .v2-watch tr:last-child td {{ border-bottom: 0; }}
    .v2-watch a {{ display: block; color: #e6edf3; font-weight: 900; text-decoration: none; }}
    .v2-watch a:hover {{ color: var(--accent); }}
    .v2-watch small {{ display: block; margin-top: 3px; color: var(--muted); font-size: 11px; }}
    .trend-arrow {{ font-weight: 900; font-size: 15px; white-space: nowrap; }}
    .rsi-hot {{ color: var(--bad); font-weight: 900; }}
    .rsi-cold {{ color: var(--accent); font-weight: 900; }}
    .muted {{ color: var(--muted); }}
    @media (max-width: 1120px) {{
      .hero-v2, .watch-grid {{ grid-template-columns: 1fr; }}
      .market-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    }}
    @media (max-width: 620px) {{
      .pulse-grid, .market-grid, .regime {{ grid-template-columns: 1fr; }}
      .section-head, .v2-panel-head, .preview-bar {{ align-items: flex-start; flex-direction: column; }}
      .v2-panel p {{ text-align: left; }}
    }}
  </style>
</head>
<body>
  {nav_html}
  <main class="wrap">
    {preview_bar}

    <section class="hero-v2">
      <div class="hero-copy">
        <div class="eyebrow">{escape(eyebrow_text)}</div>
        <h1>{overall_score}점 <span class="score-state tone-{escape(overall_tone)}">{escape(overall_label)}</span></h1>
        <p class="lead">{escape(overall_note)} 주식 강세 비율은 {stock_breadth:.0f}%, 매크로 강세 비율은 {macro_breadth:.0f}%이며 전체 평균 등락률은 {escape(avg_change_text)}입니다.</p>
        <div class="regime">
          <div><span>주식 시장 체력</span><strong>{escape(_pct(stock_stats["breadth"]))}</strong></div>
          <div><span>매크로 강도</span><strong>{escape(_pct(macro_stats["breadth"]))}</strong></div>
          <div><span>전체 평균 등락</span><strong>{escape(avg_change_text)}</strong></div>
        </div>
      </div>
      <div class="pulse-grid">
        {_market_pulse_html(pages, overview_frames)}
      </div>
    </section>

    <section>
      <div class="section-head">
        <h2>시장별 상태</h2>
        <p>강세 비율, RSI, MA 근접, 평균 등락률을 한 카드에서 확인합니다.</p>
      </div>
      <div class="market-grid">
        {market_cards}
      </div>
    </section>

    <section>
      <div class="section-head">
        <h2>오늘의 관찰 종목</h2>
        <p>전체 시장 데이터를 네 가지 관찰 관점으로 재정렬한 샘플입니다.</p>
      </div>
      <div class="watch-grid">
        {"".join(watchlists)}
      </div>
    </section>
  </main>
</body>
</html>
"""
    if page_path is None:
        page_path = SITE_DIR / "preview-home" / "index.html"
    page_path.parent.mkdir(parents=True, exist_ok=True)
    page_path.write_text(html, encoding="utf-8")


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


def _render_filtered_report(
    market: MarketDefinition,
    frame: pd.DataFrame,
    slug: str,
    title: str,
    description: str,
    date_str: str,
) -> BuiltPage:
    frame = enrich_metadata_frame(frame, market)
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
    date_str, csv_path, _, _ = artifacts
    frame = _load_frame(csv_path)
    # Re-render site pages from CSV so all markets pick up the current report template.
    return _render_filtered_report(MARKETS[market_key], frame, slug, title, description, date_str)


def _latest_csv_for_market(market_key: str) -> tuple[str, Path] | None:
    csv_prefix, _, _ = _prefixes_for_market(market_key)
    candidate_dates = sorted(
        set(_dates_for_prefix(csv_prefix, DATA_DIR)) | set(_dates_for_prefix(csv_prefix)),
        reverse=True,
    )
    for date_str in candidate_dates:
        csv_path = _csv_path_for_date(csv_prefix, date_str)
        if _csv_has_columns(csv_path):
            return date_str, csv_path
    return None


def _build_derived_us_pages(source_page: BuiltPage, include_keys: set[str] | None = None) -> list[BuiltPage]:
    pages: list[BuiltPage] = []
    source_frame = source_page.frame.copy()
    source_market = MARKETS["us"]

    include_keys = include_keys or {"nasdaq100", "sp500", "dow30"}

    nasdaq_members = set(_nasdaq100_static_meta().keys())
    nasdaq_frame = source_frame[source_frame["symbol"].astype(str).isin(nasdaq_members)].copy()
    if "nasdaq100" in include_keys and not nasdaq_frame.empty:
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
    if "sp500" in include_keys and not sp500_frame.empty:
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

    dow30_frame = source_frame[source_frame["symbol"].astype(str).isin(_DOW30_SYMBOLS)].copy()
    if "dow30" in include_keys and not dow30_frame.empty:
        dow30_market = replace(source_market, key="dow30", label="Dow 30", output_prefix="dow30")
        pages.append(
            _render_filtered_report(
                dow30_market,
                dow30_frame,
                "dow30",
                "Dow 30",
                "Derived from the combined US scan",
                source_page.date_str,
            )
        )

    return pages


def _build_dow30_from_page(source_page: BuiltPage) -> BuiltPage | None:
    source_frame = source_page.frame.copy()
    dow30_frame = source_frame[source_frame["symbol"].astype(str).isin(_DOW30_SYMBOLS)].copy()
    if dow30_frame.empty:
        return None
    source_market = MARKETS.get(source_page.key, MARKETS.get("sp500", MARKETS["us"]))
    dow30_market = replace(source_market, key="dow30", label="Dow 30", output_prefix="dow30")
    return _render_filtered_report(
        dow30_market,
        dow30_frame,
        "dow30",
        "Dow 30",
        f"Derived from the {source_page.title} scan",
        source_page.date_str,
    )


_OVERVIEW_ONLY_MARKETS = {"global-indices", "theme-proxies", "commodities"}


def build_site() -> list[BuiltPage]:
    _ensure_site_dirs()
    built_pages: list[BuiltPage] = []
    overview_frames: dict[str, pd.DataFrame] = {}

    for market_key, title, description, slug in _ROOT_PAGES:
        if market_key == "dow30":
            continue
        if market_key not in MARKETS and market_key not in _OVERVIEW_ONLY_MARKETS:
            continue
        page = _build_market_page(market_key, title, description, slug)
        if page:
            built_pages.append(page)
            overview_frames[market_key] = page.frame
        elif market_key in _OVERVIEW_ONLY_MARKETS:
            csv_info = _latest_csv_for_market(market_key)
            if csv_info:
                overview_frames[market_key] = _load_frame(csv_info[1])

    built_keys = {page.key for page in built_pages}
    if "dow30" not in built_keys:
        sp500_page = next((page for page in built_pages if page.key == "sp500"), None)
        if sp500_page is not None:
            dow30_page = _build_dow30_from_page(sp500_page)
            if dow30_page is not None:
                built_pages.append(dow30_page)
                overview_frames[dow30_page.key] = dow30_page.frame
                built_keys.add("dow30")

    missing_derived = {"nasdaq100", "sp500", "dow30"} - built_keys
    # Legacy fallback: old combined US CSV can still derive pages until standalone CSVs exist.
    us_artifacts = _latest_market_artifacts("us")
    if missing_derived and us_artifacts:
        us_date_str, us_csv_path, _, us_html_path = us_artifacts
        us_frame = _load_frame(us_csv_path)
        us_source_path = us_html_path or us_csv_path
        us_source = BuiltPage("us", "us", "US Market", "", us_date_str, us_frame, us_source_path, us_source_path)
        derived = _build_derived_us_pages(us_source, missing_derived)
        built_pages.extend(derived)
        for p in derived:
            overview_frames[p.key] = p.frame

    _build_home_preview_page(
        built_pages,
        overview_frames,
        page_path=SITE_DIR / "index.html",
        depth=0,
        preview=False,
    )
    _build_home_preview_page(built_pages, overview_frames)
    built_keys = {page.key for page in built_pages}
    built_slugs = {page.slug for page in built_pages}
    for key, title, description, slug in _ROOT_PAGES:
        if key not in built_keys and slug not in built_slugs:
            _write_placeholder_page(slug, title, description)
    return built_pages


def _should_open_browser_by_default() -> bool:
    ci_value = os.environ.get("CI", "").lower()
    return ci_value not in {"1", "true", "yes"} and os.environ.get("GITHUB_ACTIONS") != "true"


def _open_site_index() -> None:
    index_path = (SITE_DIR / "index.html").resolve()
    url = index_path.as_uri()
    if webbrowser.open(url):
        print(f"Opened {url}")
    else:
        print(f"Built site index: {index_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the static Market Scanner site.")
    open_group = parser.add_mutually_exclusive_group()
    open_group.add_argument(
        "--open",
        dest="open_browser",
        action="store_true",
        help="Open site/index.html in the default browser after building.",
    )
    open_group.add_argument(
        "--no-open",
        dest="open_browser",
        action="store_false",
        help="Build the site without opening a browser.",
    )
    parser.set_defaults(open_browser=None)
    args = parser.parse_args()

    pages = build_site()
    if not pages:
        raise SystemExit("No reports were found. Generate at least one market report before building the site.")
    print(f"Built {len(pages)} site pages under {SITE_DIR}")
    open_browser = args.open_browser
    if open_browser is None:
        open_browser = _should_open_browser_by_default()
    if open_browser:
        _open_site_index()


if __name__ == "__main__":
    main()
