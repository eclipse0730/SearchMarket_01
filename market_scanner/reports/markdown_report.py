from __future__ import annotations

from pathlib import Path

import pandas as pd

from market_scanner.models import MarketDefinition, ScanSettings
from market_scanner.reports._common import enrich_metadata_frame


# ── 포맷 헬퍼 ─────────────────────────────────────────────────────────────────

_TREND_BADGE: dict[str, tuple[str, str]] = {
    "Strong Uptrend":   ("badge-strong-up",   "⬆⬆"),
    "Uptrend":          ("badge-up",          "⬆"),
    "Neutral":          ("badge-neutral",     "→"),
    "Downtrend":        ("badge-down",        "⬇"),
    "Strong Downtrend": ("badge-strong-down", "⬇⬇"),
}


def _trend_badge_html(trend: object) -> str:
    if not trend:
        return "-"
    cls, arrow = _TREND_BADGE.get(str(trend), ("badge-neutral", "→"))
    return f'<span class="badge {cls}" title="{trend}">{arrow}</span>'


def _fmt_num(value, digits: int = 1, suffix: str = "") -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value):.{digits}f}{suffix}"


def _fmt_price(value, market: MarketDefinition) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{market.currency_symbol}{float(value):,.{market.price_decimals}f}"


def _tags_text(tags: object, limit: int = 4) -> str:
    if not isinstance(tags, list) or not tags:
        return "-"
    return " ".join(f"`{t}`" for t in tags[:limit])


# ── 셋업별 섹션 정의 ──────────────────────────────────────────────────────────
# (제목, 정렬용 strategy score 컬럼, setup_label 매칭 텍스트)
# screener.py 의 score_setup_label() 결과와 동기화 필요.
_SETUP_SECTIONS: tuple[tuple[str, str, str], ...] = (
    ("이평선 눌림",       "pullback_score",        "이평선 눌림"),
    ("신고가 / 고점 돌파", "breakout_score",        "신고가/고점 돌파"),
    ("박스권 돌파",        "box_breakout_score",    "박스권 돌파"),
    ("과매도 반등",        "reversal_score",        "과매도 반등"),
    ("추세 우량",          "trend_quality_score",   "추세 우량"),
)


# ── 테이블 렌더링 ─────────────────────────────────────────────────────────────

def _table_header() -> list[str]:
    return [
        "| 순위 | 심볼 | 종목명 | 종합 | 셋업 | 신호 | 추세 | 현재가 | 등락 | RSI |",
        "|---:|---|---|---:|---|---|:---:|---:|---:|---:|",
    ]


def _table_row(row: pd.Series, market: MarketDefinition) -> str:
    rank = row.get("rank_no")
    rank_text = str(int(rank)) if pd.notna(rank) else "-"
    return (
        f"| {rank_text}"
        f" | {row.get('display_symbol', '-')}"
        f" | {str(row.get('name_local') or '-')[:18]}"
        f" | {_fmt_num(row.get('composite_score'), 1)}"
        f" | {row.get('setup_label') or '-'}"
        f" | {_tags_text(row.get('setup_tags'))}"
        f" | {_trend_badge_html(row.get('trend'))}"
        f" | {_fmt_price(row.get('price'), market)}"
        f" | {_fmt_num(row.get('change_pct'), 2, '%')}"
        f" | {_fmt_num(row.get('rsi'), 0)} |"
    )


def _section_table(
    lines: list[str],
    section: pd.DataFrame,
    market: MarketDefinition,
    limit: int | None = None,
) -> None:
    if section.empty:
        lines.extend(["_해당 종목 없음_", ""])
        return
    lines.extend(_table_header())
    view = section.head(limit) if limit else section
    for _, row in view.iterrows():
        lines.append(_table_row(row, market))
    lines.append("")


# ── 섹션 빌더 ─────────────────────────────────────────────────────────────────

def _market_summary(frame: pd.DataFrame) -> list[str]:
    avg_score = frame["composite_score"].dropna().mean() if "composite_score" in frame.columns else None
    avg_rsi = frame["rsi"].dropna().mean() if "rsi" in frame.columns else None
    change = pd.to_numeric(frame.get("change_pct", pd.Series(dtype=float)), errors="coerce")
    avg_change = change.dropna().mean()
    advance = int((change > 0).sum())
    decline = int((change < 0).sum())
    unchanged = int(((change == 0) & change.notna()).sum())
    risk_count = int(frame["risk_flags"].apply(lambda x: bool(x)).sum()) if "risk_flags" in frame.columns else 0
    trend_counts = (
        frame["trend"].fillna("Unknown").value_counts() if "trend" in frame.columns else pd.Series(dtype=int)
    )
    dominant_trend = trend_counts.index[0] if not trend_counts.empty else "Unknown"

    lines = [
        "## 시장 총평",
        "",
        "| 지표 | 값 |",
        "|---|---:|",
        f"| 평균 종합점수 | **{_fmt_num(avg_score, 1)}** |",
        f"| 평균 RSI | **{_fmt_num(avg_rsi, 0)}** |",
        f"| 상승 / 하락 / 보합 | {advance} / {decline} / {unchanged} |",
        f"| 평균 등락 | {_fmt_num(avg_change, 2, '%')} |",
        f"| 우세 추세 | {dominant_trend} |",
        f"| 리스크 태그 종목 | **{risk_count}개** |",
        "",
    ]
    return lines


def _describe_pick(row: pd.Series) -> str:
    parts: list[str] = []

    composite = row.get("composite_score")
    parts.append(f"종합 {_fmt_num(composite, 1)}")

    setup = row.get("setup_label")
    if setup and setup != "중립/관망":
        parts.append(str(setup))

    # 가장 강한 전략 점수 1개 강조
    strategy_scores = {
        "눌림": row.get("pullback_score"),
        "돌파": row.get("breakout_score"),
        "박스권": row.get("box_breakout_score"),
        "반등": row.get("reversal_score"),
        "추세품질": row.get("trend_quality_score"),
    }
    valid = [(name, val) for name, val in strategy_scores.items() if val is not None and not pd.isna(val)]
    if valid:
        top_name, top_val = max(valid, key=lambda kv: float(kv[1]))
        if float(top_val) >= 65:
            parts.append(f"{top_name} {_fmt_num(top_val, 0)}")

    rsi = row.get("rsi")
    if pd.notna(rsi):
        parts.append(f"RSI {_fmt_num(rsi, 0)}")

    risk = row.get("risk_flags")
    if isinstance(risk, list) and risk:
        parts.append(f"⚠ {' '.join(risk[:2])}")

    name = str(row.get("name_local") or row.get("name_en") or "")
    return f"- **{row.get('display_symbol', '-')} {name}** — {' / '.join(parts)}"


def _setup_section_frame(
    frame: pd.DataFrame, score_col: str, label_match: str, limit: int = 8
) -> pd.DataFrame:
    """주어진 전략 점수 상위 + 매칭되는 setup_label 우선 정렬."""
    if frame.empty or score_col not in frame.columns:
        return pd.DataFrame()
    work = frame.copy()
    score = pd.to_numeric(work[score_col], errors="coerce")
    work = work[score >= 50]  # 너무 낮은 점수는 노이즈
    if work.empty:
        return work
    work["_priority"] = (work["setup_label"] == label_match).astype(int)
    return (
        work.sort_values(["_priority", score_col], ascending=[False, False])
        .drop(columns="_priority")
        .head(limit)
    )


def _risk_section(frame: pd.DataFrame) -> pd.DataFrame:
    if "risk_flags" not in frame.columns:
        return pd.DataFrame()
    return frame[frame["risk_flags"].apply(lambda x: bool(x))].copy()


def _rsi_extreme_section(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if "rsi" not in frame.columns:
        return pd.DataFrame(), pd.DataFrame()
    rsi = pd.to_numeric(frame["rsi"], errors="coerce")
    return (
        frame[rsi < 30].sort_values("rsi", ascending=True).copy(),
        frame[rsi >= 70].sort_values("rsi", ascending=False).copy(),
    )


def _volume_surge_section(frame: pd.DataFrame, threshold: float = 2.0) -> pd.DataFrame:
    if "volume_ratio" not in frame.columns:
        return pd.DataFrame()
    vol = pd.to_numeric(frame["volume_ratio"], errors="coerce")
    return frame[vol >= threshold].sort_values("volume_ratio", ascending=False).copy()


def _near_52high_section(frame: pd.DataFrame, threshold: float = -5.0) -> pd.DataFrame:
    if "from_high_pct" not in frame.columns:
        return pd.DataFrame()
    fh = pd.to_numeric(frame["from_high_pct"], errors="coerce")
    return frame[fh >= threshold].sort_values("from_high_pct", ascending=False).copy()


def _macd_section(frame: pd.DataFrame) -> pd.DataFrame:
    if "macd_state" not in frame.columns:
        return pd.DataFrame()
    mask = frame["macd_state"].notna() & (frame["macd_state"].astype(str).str.strip() != "")
    return frame[mask].sort_values("composite_score", ascending=False).copy()


def _sector_summary(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "sector" not in frame.columns:
        return pd.DataFrame()
    work = frame.copy()
    work["sector"] = work["sector"].fillna("Unknown")
    grouped = work.groupby("sector").agg(
        count=("symbol", "size"),
        avg_change=("change_pct", "mean"),
        avg_rsi=("rsi", "mean"),
        avg_score=("composite_score", "mean"),
    )
    leaders = (
        work.sort_values("composite_score", ascending=False)
        .groupby("sector")
        .head(1)
        .set_index("sector")["display_symbol"]
    )
    grouped["leader"] = leaders
    return grouped.sort_values("avg_change", ascending=False)


# ── 본문 조립 ─────────────────────────────────────────────────────────────────

def _summary_lines(frame: pd.DataFrame, market: MarketDefinition, date_str: str) -> list[str]:
    lines: list[str] = [
        f"# {market.label} 시장 스캐너 분석 리포트",
        "",
        f"**기준일:** {date_str}  ",
        f"**유니버스:** {market.label} ({len(frame)}개 종목)  ",
        "**점수 출처:** scan_results (스크리너 결과 그대로 표시)",
        "",
        "---",
        "",
    ]
    if frame.empty:
        lines.append("스캔 결과가 없습니다. screener를 먼저 실행하세요.")
        return lines

    # 시장 총평
    lines.extend(_market_summary(frame))
    lines.extend(["---", ""])

    # 1. 핵심 후보
    top = frame.sort_values("composite_score", ascending=False).head(10)
    lines.extend([
        "## 1. 핵심 후보 Top 10",
        "",
        "> `composite_score` 상위. 셋업 라벨과 신호 태그는 스크리너에서 부여한 값입니다.",
        "",
    ])
    _section_table(lines, top, market)
    for _, row in top.iterrows():
        lines.append(_describe_pick(row))
    lines.extend(["", "---", ""])

    # 2. 셋업별 후보
    lines.extend([
        "## 2. 셋업별 후보",
        "",
        "> 스크리너의 전략별 점수와 셋업 라벨 기준 상위입니다. 각 셋업의 점수가 50 미만이면 해당 섹션에서 제외합니다.",
        "",
    ])
    for title, score_col, label_match in _SETUP_SECTIONS:
        section = _setup_section_frame(frame, score_col, label_match, limit=8)
        lines.extend([f"### {title}", ""])
        _section_table(lines, section, market)
    lines.extend(["---", ""])

    # 3. RSI 극단값
    oversold_df, overbought_df = _rsi_extreme_section(frame)
    lines.extend(["## 3. RSI 극단값", ""])
    lines.extend(["### 과매도 (RSI < 30)", ""])
    if oversold_df.empty:
        lines.extend(["_해당 종목 없음_", ""])
    else:
        lines.extend(["| 심볼 | 종목명 | RSI | 종합 | 추세 | 셋업 |", "|---|---|---:|---:|:---:|---|"])
        for _, row in oversold_df.head(10).iterrows():
            lines.append(
                f"| {row.get('display_symbol', '-')}"
                f" | {str(row.get('name_local') or '-')[:18]}"
                f" | {_fmt_num(row.get('rsi'), 0)}"
                f" | {_fmt_num(row.get('composite_score'), 1)}"
                f" | {_trend_badge_html(row.get('trend'))}"
                f" | {row.get('setup_label') or '-'} |"
            )
        lines.append("")
    lines.extend(["### 과열 (RSI ≥ 70)", ""])
    if overbought_df.empty:
        lines.extend(["_해당 종목 없음_", ""])
    else:
        lines.extend(["| 심볼 | 종목명 | RSI | 종합 | 추세 | 셋업 |", "|---|---|---:|---:|:---:|---|"])
        for _, row in overbought_df.head(10).iterrows():
            lines.append(
                f"| {row.get('display_symbol', '-')}"
                f" | {str(row.get('name_local') or '-')[:18]}"
                f" | {_fmt_num(row.get('rsi'), 0)}"
                f" | {_fmt_num(row.get('composite_score'), 1)}"
                f" | {_trend_badge_html(row.get('trend'))}"
                f" | {row.get('setup_label') or '-'} |"
            )
        lines.append("")
    lines.extend(["---", ""])

    # 4. 거래량 급등
    vol_df = _volume_surge_section(frame)
    lines.extend(["## 4. 거래량 급등 (≥ 2x)", ""])
    if vol_df.empty:
        lines.extend(["_해당 종목 없음_", ""])
    else:
        lines.extend(["| 심볼 | 종목명 | 거래량비율 | 종합 | 등락 | 추세 |", "|---|---|---:|---:|---:|:---:|"])
        for _, row in vol_df.head(15).iterrows():
            lines.append(
                f"| {row.get('display_symbol', '-')}"
                f" | {str(row.get('name_local') or '-')[:18]}"
                f" | {_fmt_num(row.get('volume_ratio'), 1)}x"
                f" | {_fmt_num(row.get('composite_score'), 1)}"
                f" | {_fmt_num(row.get('change_pct'), 2, '%')}"
                f" | {_trend_badge_html(row.get('trend'))} |"
            )
        lines.append("")
    lines.extend(["---", ""])

    # 5. 52주 고점 근접
    near52_df = _near_52high_section(frame)
    lines.extend(["## 5. 52주 고점 근접 (고점 대비 -5% 이내)", ""])
    if near52_df.empty:
        lines.extend(["_해당 종목 없음_", ""])
    else:
        lines.extend(["| 심볼 | 종목명 | 고점대비% | 종합 | RSI | 추세 |", "|---|---|---:|---:|---:|:---:|"])
        for _, row in near52_df.head(15).iterrows():
            lines.append(
                f"| {row.get('display_symbol', '-')}"
                f" | {str(row.get('name_local') or '-')[:18]}"
                f" | {_fmt_num(row.get('from_high_pct'), 1, '%')}"
                f" | {_fmt_num(row.get('composite_score'), 1)}"
                f" | {_fmt_num(row.get('rsi'), 0)}"
                f" | {_trend_badge_html(row.get('trend'))} |"
            )
        lines.append("")
    lines.extend(["---", ""])

    # 6. MACD 신호
    macd_df = _macd_section(frame)
    lines.extend(["## 6. MACD 신호", ""])
    if macd_df.empty:
        lines.extend(["_MACD 데이터 없음_", ""])
    else:
        lines.extend(["| 심볼 | 종목명 | MACD 상태 | 종합 | RSI | 추세 |", "|---|---|---|---:|---:|:---:|"])
        for _, row in macd_df.head(15).iterrows():
            lines.append(
                f"| {row.get('display_symbol', '-')}"
                f" | {str(row.get('name_local') or '-')[:18]}"
                f" | {row.get('macd_state') or '-'}"
                f" | {_fmt_num(row.get('composite_score'), 1)}"
                f" | {_fmt_num(row.get('rsi'), 0)}"
                f" | {_trend_badge_html(row.get('trend'))} |"
            )
        lines.append("")
    lines.extend(["---", ""])

    # 7. 리스크 / 과열
    lines.extend([
        "## 7. 리스크 / 과열 알림",
        "",
        "> 스크리너가 부여한 `risk_flags` 가 비어있지 않은 종목입니다.",
        "",
    ])
    risk_df = _risk_section(frame).sort_values("composite_score", ascending=False)
    if risk_df.empty:
        lines.extend(["_해당 종목 없음_", ""])
    else:
        lines.extend([
            "| 심볼 | 종목명 | 태그 | 종합 | RSI | 추세 |",
            "|---|---|---|---:|---:|:---:|",
        ])
        for _, row in risk_df.head(15).iterrows():
            lines.append(
                f"| {row.get('display_symbol', '-')}"
                f" | {str(row.get('name_local') or '-')[:18]}"
                f" | {_tags_text(row.get('risk_flags'))}"
                f" | {_fmt_num(row.get('composite_score'), 1)}"
                f" | {_fmt_num(row.get('rsi'), 0)}"
                f" | {_trend_badge_html(row.get('trend'))} |"
            )
        lines.append("")
    lines.extend(["---", ""])

    # 8. 섹터 요약
    lines.extend(["## 8. 섹터 요약", ""])
    sector_df = _sector_summary(frame)
    if sector_df.empty:
        lines.extend(["_데이터 없음_", ""])
    else:
        lines.extend([
            "| 섹터 | 종목수 | 평균 등락 | 평균 RSI | 평균 종합 | 리더 |",
            "|---|---:|---:|---:|---:|---|",
        ])
        for sector, agg in sector_df.iterrows():
            lines.append(
                f"| {sector}"
                f" | {int(agg['count'])}"
                f" | {_fmt_num(agg['avg_change'], 2, '%')}"
                f" | {_fmt_num(agg['avg_rsi'], 0)}"
                f" | {_fmt_num(agg['avg_score'], 1)}"
                f" | {agg.get('leader') or '-'} |"
            )
        lines.append("")

    lines.append(
        "*본 리포트는 `scan_results` 와 `daily_indicators` 데이터를 기반으로 자동 생성되며 투자 조언이 아닙니다.*"
    )
    return lines


def write_markdown(
    frame: pd.DataFrame,
    market: MarketDefinition,
    settings: ScanSettings,  # noqa: ARG001 — 시그니처 호환용 (재스코어링 안 함)
    date_str: str,
    path: Path,
    *,
    skip_enrich: bool = False,
) -> str:
    if not skip_enrich:
        frame = enrich_metadata_frame(frame, market)
    text = "\n".join(_summary_lines(frame, market, date_str))
    path.write_text(text, encoding="utf-8")
    return text
