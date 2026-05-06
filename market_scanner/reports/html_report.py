from __future__ import annotations

from datetime import datetime
from html import escape
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

from market_scanner.collectors.news import NEWS_CACHE_PATH
from market_scanner.models import MarketDefinition, ScanSettings
from market_scanner.reports._common import _safe_number, enrich_metadata_frame


TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"


def _read_template(name: str) -> str:
    return (TEMPLATE_DIR / name).read_text(encoding="utf-8")


def _render_html_template(context: dict[str, str]) -> str:
    html_template = _read_template("report.html")
    for key, value in context.items():
        html_template = html_template.replace(f"###{key}###", value)
    return html_template


def _json_script(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def _updated_at_text() -> str:
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M:%S KST")


def _summary_cards_interactive_html(frame: pd.DataFrame, settings: ScanSettings) -> str:
    card_classes = ["text-info", "text-warning", "text-danger", "text-primary", "text-success", "text-secondary"]
    cards: list[str] = []
    for index, period in enumerate(settings.ma_periods):
        count = int(frame[f"near_{period}"].sum()) if not frame.empty else 0
        tone = card_classes[index % len(card_classes)]
        cards.append(
            "<div class='col-6 col-md-3'><div class='card text-center p-3 stat-card'>"
            f"<div class='text-secondary small'>MA{period} 근접</div>"
            f"<h2 class='{tone}'>{count}</h2>"
            f"<div class='text-secondary small'>+/- {settings.threshold_pct:.0f}% 이내</div>"
            "</div></div>"
        )

    if len(settings.ma_periods) > 1:
        multi_count = int((frame["near_count"] >= 2).sum()) if not frame.empty and "near_count" in frame.columns else 0
        cards.append(
            "<div class='col-6 col-md-3'><div class='card text-center p-3 stat-card'>"
            "<div class='text-secondary small'>복수 MA 수렴</div>"
            f"<h2 class='{card_classes[len(settings.ma_periods) % len(card_classes)]}'>{multi_count}</h2>"
            "<div class='text-secondary small'>2개 이상</div>"
            "</div></div>"
        )
    return "".join(cards)


def _interactive_tab_nav_html(settings: ScanSettings) -> str:
    items = ['<li class="nav-item"><a class="nav-link active" href="#" data-tab="all">전체</a></li>']
    for period in settings.ma_periods:
        items.append(
            f'<li class="nav-item"><a class="nav-link" href="#" data-tab="ma{period}">MA{period}</a></li>'
        )
    if len(settings.ma_periods) > 1:
        items.append('<li class="nav-item"><a class="nav-link" href="#" data-tab="multi">복수MA</a></li>')
    return "".join(items)


def _interactive_table_headers_html(settings: ScanSettings, market: MarketDefinition) -> str:
    currency = escape(market.currency_symbol)
    headers = [
        '<th data-col="ticker">티커</th>',
        '<th data-col="kr_name">종목명</th>',
        '<th data-col="sector">섹터</th>',
        '<th data-col="trend">추세</th>',
        f'<th data-col="price">현재가({currency})</th>',
        '<th data-col="changePct">등락률</th>',
        '<th data-col="candleType">캔들</th>',
        '<th data-col="rsi">RSI</th>',
        '<th data-col="fromHigh">52주고점%</th>',
        '<th data-col="volRatio">거래량비율</th>',
        '<th data-col="per">PER</th>',
        '<th data-col="upside">업사이드</th>',
    ]
    headers.append("<th>근접</th>")
    return "".join(headers)


def _sector_strength_data(frame: pd.DataFrame) -> tuple[list[str], list[int], list[int], list[int]]:
    if frame.empty or "sector" not in frame.columns or "trend" not in frame.columns:
        return [], [], [], []
    df = frame.copy()
    df["sector"] = df["sector"].fillna("Unknown")
    bull_trends = {"Strong Uptrend", "Uptrend"}
    bear_trends = {"Strong Downtrend", "Downtrend"}
    df["_cat"] = df["trend"].apply(
        lambda t: "bull" if t in bull_trends else ("bear" if t in bear_trends else "neu")
    )
    grouped = df.groupby("sector")["_cat"].value_counts().unstack(fill_value=0)
    for col in ("bull", "neu", "bear"):
        if col not in grouped.columns:
            grouped[col] = 0
    grouped["total"] = grouped["bull"] + grouped["neu"] + grouped["bear"]
    grouped = grouped[grouped["total"] >= 2]
    grouped["bull_ratio"] = grouped["bull"] / grouped["total"]
    grouped = grouped.sort_values("bull_ratio", ascending=True).tail(14)
    labels = grouped.index.tolist()
    return (
        labels,
        [int(v) for v in grouped["bull"].tolist()],
        [int(v) for v in grouped["neu"].tolist()],
        [int(v) for v in grouped["bear"].tolist()],
    )


def _rsi_chart_data(frame: pd.DataFrame) -> tuple[list[str], list[int]]:
    labels = ["<25", "25-30", "30-35", "35-40", "40-45", "45-50", "50-55", "55-60", "60-65", "65-70", "70-75", "75+"]
    if frame.empty or "rsi" not in frame.columns:
        return labels, [0] * len(labels)

    bins = [-float("inf"), 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, float("inf")]
    rsi_values = pd.to_numeric(frame["rsi"], errors="coerce").dropna()
    if rsi_values.empty:
        return labels, [0] * len(labels)

    categories = pd.cut(rsi_values, bins=bins, labels=labels, right=False)
    counts = categories.value_counts(sort=False)
    return labels, [int(counts.get(label, 0)) for label in labels]


def _fear_label_and_note(level: float) -> tuple[str, str]:
    if level < 15:
        return "Calm", "변동성은 낮은 편입니다. 추세가 유지되면 눌림목 선별에 유리합니다."
    if level < 20:
        return "Normal", "변동성은 정상권입니다. 개별 종목 신호 품질을 우선 확인합니다."
    if level < 30:
        return "Elevated", "변동성이 높아진 구간입니다. 포지션 크기와 손절 기준이 중요합니다."
    return "Stress", "시장 스트레스가 큰 구간입니다. 방어적 접근과 현금 비중 점검이 필요합니다."


def _fear_from_scan_data(frame: pd.DataFrame | None, date_str: str | None) -> dict[str, object] | None:
    sources: list[pd.DataFrame] = []
    if frame is not None and not frame.empty:
        sources.append(frame)

    for source in sources:
        if "symbol" not in source.columns:
            continue
        vix_rows = source[source["symbol"].astype(str) == "^VIX"]
        if vix_rows.empty:
            continue
        row = vix_rows.iloc[0]
        level = _safe_number(row.get("price"), 2)
        if level is None:
            continue
        change_pct = _safe_number(row.get("change_pct"), 1)
        label, note = _fear_label_and_note(level)
        return {
            "available": True,
            "symbol": "^VIX",
            "label": label,
            "level": level,
            "avg20": None,
            "avg60": None,
            "vs20Pct": change_pct,
            "vsLabel": "전일 대비",
            "trend": "rising" if change_pct is not None and change_pct > 0 else ("falling" if change_pct is not None and change_pct < 0 else "unknown"),
            "note": f"{note} VIX 값은 스캔 데이터 fallback에서 읽었습니다.",
        }
    return None


def _fear_panel_data(frame: pd.DataFrame | None = None, date_str: str | None = None) -> dict[str, object]:
    fallback = {
        "available": False,
        "symbol": "^VIX",
        "label": "Unavailable",
        "level": None,
        "avg20": None,
        "avg60": None,
        "vs20Pct": None,
        "vsLabel": "20D 대비",
        "trend": "unknown",
        "note": "VIX data could not be loaded in this environment.",
    }
    try:
        hist = yf.Ticker("^VIX").history(period="3mo")
    except Exception:
        return _fear_from_scan_data(frame, date_str) or fallback

    if hist.empty or "Close" not in hist.columns:
        return _fear_from_scan_data(frame, date_str) or fallback

    close = pd.to_numeric(hist["Close"], errors="coerce").dropna()
    if close.empty:
        return _fear_from_scan_data(frame, date_str) or fallback

    level = float(close.iloc[-1])
    avg20 = float(close.tail(20).mean()) if len(close) >= 20 else float(close.mean())
    avg60 = float(close.tail(60).mean()) if len(close) >= 60 else float(close.mean())
    lookback = float(close.iloc[-6]) if len(close) >= 6 else float(close.iloc[0])
    vs20 = ((level - avg20) / avg20 * 100) if avg20 else None

    label, note = _fear_label_and_note(level)

    return {
        "available": True,
        "symbol": "^VIX",
        "label": label,
        "level": round(level, 2),
        "avg20": round(avg20, 2),
        "avg60": round(avg60, 2),
        "vs20Pct": round(vs20, 1) if vs20 is not None else None,
        "vsLabel": "20D 대비",
        "trend": "rising" if level > lookback else "falling",
        "note": note,
    }


def _news_briefing_data(frame: pd.DataFrame, market: MarketDefinition, date_str: str) -> dict[str, object]:
    base = {
        "available": False,
        "title": "뉴스 브리핑",
        "subtitle": "US 밤새 뉴스 수집은 가능하지만, 현재는 뉴스 캐시가 없어서 표시할 항목이 없습니다.",
        "note": "권장 구조: 별도 news 수집 단계에서 yfinance news/RSS/뉴스 API 결과를 캐시하고, 리포트는 캐시만 읽습니다.",
        "items": [],
    }
    if not NEWS_CACHE_PATH.exists():
        return base
    try:
        payload = json.loads(NEWS_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return base

    raw_items: object = []
    if isinstance(payload, dict):
        dated = payload.get(date_str, payload)
        if isinstance(dated, dict):
            raw_items = dated.get(market.key)
            if raw_items is None and market.key in {"nasdaq100", "sp500", "dow30"}:
                raw_items = dated.get("us")
            if raw_items is None:
                raw_items = dated.get("items", [])
        elif isinstance(dated, list):
            raw_items = dated
    elif isinstance(payload, list):
        raw_items = payload

    if not isinstance(raw_items, list):
        return base

    symbols = set(frame.get("symbol", pd.Series(dtype=str)).astype(str).tolist())
    items: list[dict[str, object]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        ticker = str(item.get("ticker") or item.get("symbol") or "")
        if ticker and symbols and ticker not in symbols:
            continue
        items.append(
            {
                "ticker": ticker,
                "title": str(item.get("title") or ""),
                "publisher": str(item.get("publisher") or item.get("source") or ""),
                "summary": str(item.get("summary") or item.get("text") or ""),
                "url": str(item.get("url") or item.get("link") or ""),
                "sentiment": str(item.get("sentiment") or "neutral"),
                "publishedAt": str(item.get("publishedAt") or item.get("published_at") or ""),
            }
        )

    if not items:
        return base
    return {
        "available": True,
        "title": "뉴스 브리핑",
        "subtitle": f"{date_str} 기준 캐시된 뉴스 {len(items)}건",
        "note": "뉴스는 캐시 파일 기반으로 표시됩니다. 실시간 요청은 렌더링 안정성을 위해 피합니다.",
        "items": items[:80],
    }


def _interactive_table_data(frame: pd.DataFrame, market: MarketDefinition, settings: ScanSettings) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for _, row in frame.iterrows():
        symbol = str(row.get("symbol", ""))
        payload: dict[str, object] = {
            "ticker": symbol,
            "displayTicker": str(row.get("display_symbol", symbol)),
            "quoteUrl": market.quote_url_builder(symbol),
            "en_name": row.get("name_en"),
            "kr_name": row.get("name_local"),
            "sector": row.get("sector"),
            "desc": row.get("description"),
            "open": _safe_number(row.get("open"), market.price_decimals),
            "high": _safe_number(row.get("high"), market.price_decimals),
            "low": _safe_number(row.get("low"), market.price_decimals),
            "close": _safe_number(row.get("close"), market.price_decimals),
            "prevClose": _safe_number(row.get("prev_close"), market.price_decimals),
            "price": _safe_number(row.get("price"), market.price_decimals),
            "changePct": _safe_number(row.get("change_pct"), 2),
            "gapPct": _safe_number(row.get("gap_pct"), 2),
            "candleBodyPct": _safe_number(row.get("candle_body_pct"), 2),
            "candleRangePct": _safe_number(row.get("candle_range_pct"), 2),
            "upperShadowPct": _safe_number(row.get("upper_shadow_pct"), 2),
            "lowerShadowPct": _safe_number(row.get("lower_shadow_pct"), 2),
            "candleType": row.get("candle_type") or "",
            "rsi": _safe_number(row.get("rsi"), 1),
            "fromHigh": _safe_number(row.get("from_high_pct"), 1),
            "volRatio": _safe_number(row.get("volume_ratio"), 2),
            "per": _safe_number(row.get("trailing_pe"), 1),
            "pbr": _safe_number(row.get("price_to_book"), 2),
            "roe": _safe_number(row.get("return_on_equity"), 1),
            "revenueGrowth": _safe_number(row.get("revenue_growth"), 1),
            "marketCap": _safe_number(row.get("market_cap"), 0),
            "upside": _safe_number(row.get("upside_pct"), 1),
            "score": _safe_number(row.get("composite_score"), 1),
            "chartScore": _safe_number(row.get("chart_score"), 1),
            "technicalScore": _safe_number(row.get("technical_score"), 1),
            "fundamentalScore": _safe_number(row.get("fundamental_score"), 1),
            "themeScore": _safe_number(row.get("theme_score"), 1),
            "flowScore": _safe_number(row.get("flow_score"), 1),
            "momentumScore": _safe_number(row.get("momentum_score", row.get("flow_score")), 1),
            "macdState": row.get("macd_state") or "",
            "bollingerWidth": _safe_number(row.get("bollinger_width_pct"), 2),
            "bollingerPercentB": _safe_number(row.get("bollinger_percent_b"), 3),
            "trend": row.get("trend") or "",
            "trendScore": int(row.get("trend_score") or 0),
            "nearCount": int(row.get("near_count") or 0),
        }
        for period in settings.ma_periods:
            payload[f"diff_{period}"] = _safe_number(row.get(f"diff_{period}"), 2)
            payload[f"near_{period}"] = bool(row.get(f"near_{period}", False))
        rows.append(payload)
    return rows


def write_html(frame: pd.DataFrame, market: MarketDefinition, settings: ScanSettings, date_str: str, markdown_text: str, path: Path) -> None:
    frame = enrich_metadata_frame(frame, market)
    sector_labels, sector_bull, sector_neu, sector_bear = _sector_strength_data(frame)
    rsi_labels, rsi_values = _rsi_chart_data(frame)
    display_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}" if len(date_str) == 8 else date_str
    html = _render_html_template(
        {
            "TITLE": escape(f"{market.label} Report {date_str}"),
            "HEADING": escape(f"{market.label} MA Scanner"),
            "META": escape(f"{display_date} | {market.label} | {len(frame)} rows"),
            "UPDATED_AT": escape(_updated_at_text()),
            "STYLE": _read_template("report.css"),
            "SUMMARY_CARDS": _summary_cards_interactive_html(frame, settings),
            "TAB_NAV": _interactive_tab_nav_html(settings),
            "TABLE_HEADERS": _interactive_table_headers_html(settings, market),
            "CURRENCY_JSON": _json_script(market.currency_symbol),
            "PERIODS_JSON": _json_script(list(settings.ma_periods)),
            "DATA_JSON": _json_script(_interactive_table_data(frame, market, settings)),
            "SECTOR_LABELS_JSON": _json_script(sector_labels),
            "SECTOR_BULL_JSON": _json_script(sector_bull),
            "SECTOR_NEU_JSON": _json_script(sector_neu),
            "SECTOR_BEAR_JSON": _json_script(sector_bear),
            "RSI_LABELS_JSON": _json_script(rsi_labels),
            "RSI_VALUES_JSON": _json_script(rsi_values),
            "FEAR_JSON": _json_script(_fear_panel_data(frame, date_str)),
            "NEWS_JSON": _json_script(_news_briefing_data(frame, market, date_str)),
            "ANALYSIS_MD_JSON": _json_script(markdown_text or ""),
            "REPORT_EMPTY_TEXT": escape("No analysis markdown was found. Run the analyze stage or the full pipeline first."),
        }
    )
    path.write_text(html, encoding="utf-8")
