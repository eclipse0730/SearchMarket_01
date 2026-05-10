from __future__ import annotations

from datetime import datetime
from html import escape
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from market_scanner.models import MarketDefinition, ScanSettings
from market_scanner.reports._common import _safe_number, enrich_metadata_frame


TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"


# ── 템플릿 로드 ───────────────────────────────────────────────────────────────

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


# ── 상단 카드 / 탭 / 헤더 ─────────────────────────────────────────────────────

def _summary_cards_html(frame: pd.DataFrame, settings: ScanSettings) -> str:
    card_classes = ["text-info", "text-warning", "text-danger", "text-primary", "text-success", "text-secondary"]
    cards: list[str] = []
    for index, period in enumerate(settings.ma_periods):
        count = int(frame[f"near_{period}"].sum()) if not frame.empty and f"near_{period}" in frame.columns else 0
        tone = card_classes[index % len(card_classes)]
        cards.append(
            "<div class='col-6 col-md-3'><div class='card text-center p-3 stat-card'>"
            f"<div class='text-secondary small'>MA{period} 근접</div>"
            f"<h2 class='{tone}'>{count}</h2>"
            f"<div class='text-secondary small'>+/- {settings.threshold_pct:.0f}% 이내</div>"
            "</div></div>"
        )

    if len(settings.ma_periods) > 1 and not frame.empty:
        near_cols = [f"near_{p}" for p in settings.ma_periods if f"near_{p}" in frame.columns]
        if near_cols:
            multi_count = int((frame[near_cols].sum(axis=1) >= 2).sum())
            cards.append(
                "<div class='col-6 col-md-3'><div class='card text-center p-3 stat-card'>"
                "<div class='text-secondary small'>복수 MA 수렴</div>"
                f"<h2 class='{card_classes[len(settings.ma_periods) % len(card_classes)]}'>{multi_count}</h2>"
                "<div class='text-secondary small'>2개 이상</div>"
                "</div></div>"
            )
    return "".join(cards)


def _tab_nav_html(settings: ScanSettings) -> str:
    items = ['<li class="nav-item"><a class="nav-link active" href="#" data-tab="all">전체</a></li>']
    for period in settings.ma_periods:
        items.append(
            f'<li class="nav-item"><a class="nav-link" href="#" data-tab="ma{period}">MA{period}</a></li>'
        )
    if len(settings.ma_periods) > 1:
        items.append('<li class="nav-item"><a class="nav-link" href="#" data-tab="multi">복수MA</a></li>')
    return "".join(items)


def _table_headers_html(market: MarketDefinition) -> str:
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
        "<th>근접</th>",
    ]
    return "".join(headers)


# ── 차트/패널용 집계 ──────────────────────────────────────────────────────────

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
    return (
        grouped.index.tolist(),
        [int(v) for v in grouped["bull"].tolist()],
        [int(v) for v in grouped["neu"].tolist()],
        [int(v) for v in grouped["bear"].tolist()],
    )


def _rsi_chart_data(frame: pd.DataFrame) -> tuple[list[str], list[int]]:
    labels = ["<25", "25-30", "30-35", "35-40", "40-45", "45-50",
              "50-55", "55-60", "60-65", "65-70", "70-75", "75+"]
    if frame.empty or "rsi" not in frame.columns:
        return labels, [0] * len(labels)
    bins = [-float("inf"), 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, float("inf")]
    rsi_values = pd.to_numeric(frame["rsi"], errors="coerce").dropna()
    if rsi_values.empty:
        return labels, [0] * len(labels)
    categories = pd.cut(rsi_values, bins=bins, labels=labels, right=False)
    counts = categories.value_counts(sort=False)
    return labels, [int(counts.get(label, 0)) for label in labels]


# ── 패널 기본값 (외부 호출 없이 빈 패널) ──────────────────────────────────────
# VIX(yfinance)와 뉴스(DB) 로딩은 v2에서 site_builder 책임으로 분리.
# 개별 market 리포트는 빈 패널로 렌더하고, 사이트 빌더가 원하면 데이터를 주입한다.

def _empty_fear_panel() -> dict[str, object]:
    return {
        "available": False,
        "symbol": "^VIX",
        "label": "Unavailable",
        "level": None,
        "avg20": None,
        "avg60": None,
        "vs20Pct": None,
        "vsLabel": "20D 대비",
        "trend": "unknown",
        "note": "VIX 패널은 site_builder 단계에서 주입됩니다.",
    }


def _empty_news_panel() -> dict[str, object]:
    return {
        "available": False,
        "title": "뉴스 브리핑",
        "subtitle": "뉴스 패널은 site_builder 단계에서 주입됩니다.",
        "note": "개별 시장 리포트는 외부 호출과 뉴스 DB 조회를 하지 않습니다.",
        "items": [],
    }


# ── 테이블 데이터 빌더 (scan_results + daily_indicators) ───────────────────────

def _row_payload(row: pd.Series, market: MarketDefinition, settings: ScanSettings) -> dict[str, object]:
    symbol = str(row.get("symbol", ""))
    setup_tags = row.get("setup_tags") if isinstance(row.get("setup_tags"), list) else []
    risk_flags = row.get("risk_flags") if isinstance(row.get("risk_flags"), list) else []

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
        "upside": _upside_pct(row),
        # scan_results 점수 (스크리너 결과 그대로)
        "rank": _safe_number(row.get("rank_no"), 0),
        "score": _safe_number(row.get("composite_score"), 1),
        "chartScore": _safe_number(row.get("chart_score"), 1),
        "technicalScore": _safe_number(row.get("technical_score"), 1),
        "fundamentalScore": _safe_number(row.get("fundamental_score"), 1),
        "themeScore": _safe_number(row.get("theme_score"), 1),
        "flowScore": _safe_number(row.get("flow_score"), 1),
        # 전략별 점수 (summary_payload 에서 펼친 값)
        "pullbackScore": _safe_number(row.get("pullback_score"), 1),
        "breakoutScore": _safe_number(row.get("breakout_score"), 1),
        "boxBreakoutScore": _safe_number(row.get("box_breakout_score"), 1),
        "trendQualityScore": _safe_number(row.get("trend_quality_score"), 1),
        "reversalScore": _safe_number(row.get("reversal_score"), 1),
        "overboughtScore": _safe_number(row.get("overbought_score"), 1),
        "riskScore": _safe_number(row.get("risk_score"), 1),
        # 셋업 라벨 / 태그 (스크리너가 결정)
        "setupLabel": row.get("setup_label") or "",
        "signalTags": list(setup_tags),
        "riskFlags": list(risk_flags),
        "macdState": row.get("macd_state") or "",
        "bollingerWidth": _safe_number(row.get("bollinger_width_pct"), 2),
        "bollingerPercentB": _safe_number(row.get("bollinger_percent_b"), 3),
        "trend": row.get("trend") or "",
        "trendScore": int(row.get("trend_score") or 0),
    }
    # MA 근접 / 이격 (탭 필터·설정용)
    near_count = 0
    for period in settings.ma_periods:
        is_near = bool(row.get(f"near_{period}", False))
        payload[f"near_{period}"] = is_near
        payload[f"diff_{period}"] = _safe_number(row.get(f"diff_{period}"), 2)
        if is_near:
            near_count += 1
    payload["nearCount"] = near_count
    return payload


def _upside_pct(row: pd.Series) -> float | None:
    """price 와 target_price 로 upside_pct 산출 (없으면 None)."""
    price = row.get("price")
    target = row.get("target_price")
    if price is None or target is None or pd.isna(price) or pd.isna(target):
        return None
    try:
        price_f = float(price)
        target_f = float(target)
    except (TypeError, ValueError):
        return None
    if price_f <= 0:
        return None
    return round((target_f - price_f) / price_f * 100, 1)


def _table_data(frame: pd.DataFrame, market: MarketDefinition, settings: ScanSettings) -> list[dict[str, object]]:
    return [_row_payload(row, market, settings) for _, row in frame.iterrows()]


# ── 공개 API ──────────────────────────────────────────────────────────────────

def write_html(
    frame: pd.DataFrame,
    market: MarketDefinition,
    settings: ScanSettings,
    date_str: str,
    markdown_text: str,
    path: Path,
    *,
    fear_panel: dict[str, object] | None = None,
    news_panel: dict[str, object] | None = None,
) -> None:
    """scan_results + daily_indicators 기반 HTML 리포트 생성.

    fear_panel / news_panel 은 site_builder 가 주입할 수 있는 옵션 데이터.
    개별 market 리포트는 빈 패널로 렌더한다 (외부 호출 없음).
    """
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
            "SUMMARY_CARDS": _summary_cards_html(frame, settings),
            "TAB_NAV": _tab_nav_html(settings),
            "TABLE_HEADERS": _table_headers_html(market),
            "CURRENCY_JSON": _json_script(market.currency_symbol),
            "PERIODS_JSON": _json_script(list(settings.ma_periods)),
            "DATA_JSON": _json_script(_table_data(frame, market, settings)),
            "SECTOR_LABELS_JSON": _json_script(sector_labels),
            "SECTOR_BULL_JSON": _json_script(sector_bull),
            "SECTOR_NEU_JSON": _json_script(sector_neu),
            "SECTOR_BEAR_JSON": _json_script(sector_bear),
            "RSI_LABELS_JSON": _json_script(rsi_labels),
            "RSI_VALUES_JSON": _json_script(rsi_values),
            "FEAR_JSON": _json_script(fear_panel or _empty_fear_panel()),
            "NEWS_JSON": _json_script(news_panel or _empty_news_panel()),
            "ANALYSIS_MD_JSON": _json_script(markdown_text or ""),
            "REPORT_EMPTY_TEXT": escape(
                "분석 마크다운이 비어 있습니다. screener를 먼저 실행한 뒤 render 단계를 다시 수행하세요."
            ),
        }
    )
    path.write_text(html, encoding="utf-8")
