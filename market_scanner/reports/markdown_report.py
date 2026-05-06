from __future__ import annotations

from pathlib import Path

import pandas as pd

from market_scanner.analysis.screener import add_scores
from market_scanner.models import MarketDefinition, ScanSettings
from market_scanner.reports._common import enrich_metadata_frame


_TREND_BADGE: dict[str, tuple[str, str]] = {
    "Strong Uptrend":   ("badge-strong-up",   "⬆⬆"),
    "Uptrend":          ("badge-up",           "⬆"),
    "Neutral":          ("badge-neutral",      "→"),
    "Downtrend":        ("badge-down",         "⬇"),
    "Strong Downtrend": ("badge-strong-down",  "⬇⬇"),
}


def _trend_badge_html(trend: str | None) -> str:
    if not trend:
        return "-"
    cls, arrow = _TREND_BADGE.get(str(trend), ("badge-neutral", "→"))
    return f'<span class="badge {cls}" title="{trend}">{arrow}</span>'


def _summary_lines_rich(
    frame: pd.DataFrame,
    market: MarketDefinition,
    settings: ScanSettings,
    date_str: str,
) -> list[str]:
    frame = frame.copy()
    near_cols_for_score = [f"near_{period}" for period in settings.ma_periods]
    if "near_count" not in frame.columns and set(near_cols_for_score).issubset(frame.columns):
        frame["near_count"] = frame[near_cols_for_score].sum(axis=1)
    score_columns = {"chart_score", "technical_score", "fundamental_score", "theme_score", "flow_score", "composite_score"}
    if not score_columns.issubset(frame.columns):
        frame = add_scores(frame, settings)
    if "macd_state" not in frame.columns:
        frame["macd_state"] = "Unknown"
    if "candle_type" not in frame.columns:
        frame["candle_type"] = "Unknown"

    def fmt_num(value, digits: int = 1, suffix: str = "") -> str:
        if value is None or pd.isna(value):
            return "-"
        return f"{float(value):.{digits}f}{suffix}"

    def fmt_price(value) -> str:
        if value is None or pd.isna(value):
            return "-"
        return f"{market.currency_symbol}{float(value):,.{market.price_decimals}f}"

    def ma_tag(row: pd.Series) -> str:
        parts: list[str] = []
        for period in settings.ma_periods:
            if bool(row.get(f"near_{period}", False)):
                diff = row.get(f"diff_{period}")
                if pd.notna(diff):
                    parts.append(f"MA{period} {float(diff):+.1f}%")
        return " / ".join(parts) if parts else "-"

    def candle_text(row: pd.Series) -> str:
        candle = str(row.get("candle_type") or "-")
        if candle == "Unknown":
            candle = "-"
        body = row.get("candle_body_pct")
        gap = row.get("gap_pct")
        parts = [candle]
        if pd.notna(body):
            parts.append(f"몸통 {float(body):+.1f}%")
        if pd.notna(gap):
            parts.append(f"갭 {float(gap):+.1f}%")
        return " / ".join(parts)

    def table_header() -> list[str]:
        return [
            "| 심볼 | 종목명 | 종합 | 차트 | 기술 | 재무 | 추세 | 현재가 | 등락 | 캔들 | RSI | MA 위치 |",
            "|---|---|---:|---:|---:|---:|:---:|---:|---:|---|---:|---|",
        ]

    def table_row(row: pd.Series) -> str:
        return (
            f"| {row.get('display_symbol', '-')}"
            f" | {str(row.get('name_local', '-'))[:18]}"
            f" | {fmt_num(row.get('composite_score'), 0)}"
            f" | {fmt_num(row.get('chart_score'), 0)}"
            f" | {fmt_num(row.get('technical_score'), 0)}"
            f" | {fmt_num(row.get('fundamental_score'), 0)}"
            f" | {_trend_badge_html(row.get('trend'))}"
            f" | {fmt_price(row.get('price'))}"
            f" | {fmt_num(row.get('change_pct'), 2, '%')}"
            f" | {candle_text(row)}"
            f" | {fmt_num(row.get('rsi'), 0)}"
            f" | {ma_tag(row)} |"
        )

    def section_table(lines: list[str], section_df: pd.DataFrame, limit: int | None = None) -> None:
        if section_df.empty:
            lines.append("_해당 종목 없음_")
            lines.append("")
            return
        lines.extend(table_header())
        view = section_df.head(limit) if limit else section_df
        for _, row in view.iterrows():
            lines.append(table_row(row))
        lines.append("")

    def describe_pick(row: pd.Series) -> str:
        reasons: list[str] = []
        near_count = int(row.get("near_count", 0) or 0)
        rsi_value = row.get("rsi")
        upside = row.get("upside_pct")
        pe_value = row.get("trailing_pe")
        from_high = row.get("from_high_pct")
        trend = row.get("trend", "-")
        macd_state = row.get("macd_state")
        candle_type = row.get("candle_type")
        composite = row.get("composite_score")

        if pd.notna(composite):
            reasons.append(
                f"종합 {fmt_num(composite, 0)}점"
                f"(차트 {fmt_num(row.get('chart_score'), 0)}, 기술 {fmt_num(row.get('technical_score'), 0)}, 재무 {fmt_num(row.get('fundamental_score'), 0)})"
            )

        # 1순위: 추세 방향 (방향성이 핵심)
        trend_score = int(row.get("trend_score") or 0)
        if trend_score >= 4:
            reasons.append(f"추세 양호({trend}), MA 배열·기울기 확인")
        elif trend_score == 3:
            reasons.append(f"추세 중립({trend}), 방향성 선택 대기 구간")
        else:
            reasons.append(f"추세 약세({trend}), 반등 여부 확인 필요")

        # 2순위: MA 위치 (필터 통과 맥락)
        if near_count >= 3:
            reasons.append(f"3개 MA 수렴, {ma_tag(row)} 압축 구간")
        elif near_count >= 2:
            reasons.append(f"2개 MA 수렴, {ma_tag(row)} 지지·저항 겹침")
        else:
            reasons.append(f"{ma_tag(row)} 단일 기준선 테스트")

        # 3순위: RSI 타이밍
        if pd.notna(rsi_value):
            r = float(rsi_value)
            rsi_text = f"RSI {fmt_num(rsi_value, 0)}"
            if r >= 70:
                reasons.append(f"{rsi_text} 과열 구간, 추격 매수 주의")
            elif r < 35:
                reasons.append(f"{rsi_text} 극단 과매도, 반등 확인 후 접근")
            elif r < 45:
                reasons.append(f"{rsi_text} 과매도 회복 시도 구간")
            elif r <= 60:
                reasons.append(f"{rsi_text} 부담 없는 진입 구간")

        if macd_state in {"Bullish", "Positive", "Improving"}:
            reasons.append(f"MACD {macd_state}")

        if candle_type in {"Strong Bullish", "Bullish Reversal", "Long Lower Doji"}:
            reasons.append(f"캔들 {candle_type}")
        elif candle_type in {"Bearish Rejection", "Strong Bearish", "Long Upper Doji"}:
            reasons.append(f"캔들 {candle_type}, 단기 매물 확인 필요")

        # 4순위: 업사이드·PER·낙폭
        if pd.notna(upside):
            u = float(upside)
            if u < 0:
                reasons.append(f"업사이드 {fmt_num(upside, 1, '%')} (목표가 하향, 주의)")
            elif u >= 20:
                reasons.append(f"애널리스트 업사이드 {fmt_num(upside, 1, '%')}")

        if pd.notna(pe_value) and 0 < float(pe_value) < 15:
            reasons.append(f"PER {fmt_num(pe_value, 1)} 저평가 구간")

        if pd.notna(from_high) and float(from_high) <= -20:
            reasons.append(f"52주 고점 대비 {fmt_num(from_high, 1, '%')}, 반등 여지")

        return f"- **{row.get('display_symbol')} {row.get('name_local')}**: {' / '.join(reasons[:4])}."

    def sector_commentary(section_df: pd.DataFrame) -> list[str]:
        comments: list[str] = []
        sector_counts = section_df["sector"].fillna("Unknown").value_counts()
        total_count = len(section_df)
        if total_count == 0:
            return comments

        for sector, count in sector_counts.head(3).items():
            sector_df = section_df[section_df["sector"].fillna("Unknown") == sector]
            ratio = count / total_count * 100
            avg_rsi = sector_df["rsi"].dropna().mean()
            avg_upside = sector_df["upside_pct"].dropna().mean()
            leader_symbol = "-"
            if "composite_score" in sector_df.columns and not sector_df.empty:
                leader = sector_df.sort_values("composite_score", ascending=False).iloc[0]
                leader_symbol = str(leader.get("display_symbol", "-"))
            comments.append(
                "- "
                f"**{sector}**: 근접 종목 {int(count)}개({ratio:.1f}%), "
                f"평균 RSI {fmt_num(avg_rsi, 0)}, 평균 업사이드 {fmt_num(avg_upside, 1, '%')}, "
                f"상위 후보는 {leader_symbol}."
            )

        top_ratio = sector_counts.iloc[0] / total_count * 100
        if top_ratio >= 30:
            comments.append(
                f"- 상위 섹터 비중이 {top_ratio:.1f}%로 높아 이번 스캔은 특정 섹터 쏠림이 비교적 강합니다."
            )
        else:
            comments.append(
                f"- 상위 섹터 비중이 {top_ratio:.1f}% 수준이라 섹터 쏠림은 과도하지 않은 편입니다."
            )
        return comments

    lines = [
        f"# {market.label} 시장 스캐너 분석 리포트",
        "",
        f"**기준일:** {date_str}  ",
        f"**유니버스:** {market.label} ({len(frame)}개 종목)  ",
        f"**스코어링:** 차트 30% + 기술지표 25% + 재무 20% + 테마 15% + 모멘텀 10%",
        "",
        "---",
        "",
    ]

    if frame.empty:
        lines.append("데이터가 없습니다.")
        return lines

    near_cols = [f"near_{period}" for period in settings.ma_periods]
    near_any = frame[frame[near_cols].any(axis=1)].copy()
    near_multi = frame[frame["near_count"] >= 2].copy()

    lines.extend(["## 시장 총평", "", "| 구분 | 값 |", "|---|---:|"])
    for period in settings.ma_periods:
        lines.append(f"| MA{period} 근접 | **{int(frame[f'near_{period}'].sum())}개** |")
    lines.append(f"| 2개 이상 동시 근접 | **{len(near_multi)}개** |")
    lines.extend(["", "---", ""])

    total_near = len(near_any)
    total_universe = len(frame)
    near_ratio = (total_near / total_universe * 100) if total_universe else 0.0
    multi_ratio = (len(near_multi) / total_near * 100) if total_near else 0.0
    oversold_count = int((near_any["rsi"].notna() & (near_any["rsi"] < 40)).sum())
    hot_count = int((near_any["rsi"].notna() & (near_any["rsi"] >= 70)).sum())
    avg_rsi = near_any["rsi"].dropna().mean()
    avg_upside = near_any["upside_pct"].dropna().mean()
    avg_from_high = near_any["from_high_pct"].dropna().mean()
    avg_score = frame["composite_score"].dropna().mean() if "composite_score" in frame.columns else None
    avg_chart = frame["chart_score"].dropna().mean() if "chart_score" in frame.columns else None
    avg_technical = frame["technical_score"].dropna().mean() if "technical_score" in frame.columns else None
    avg_fundamental = frame["fundamental_score"].dropna().mean() if "fundamental_score" in frame.columns else None
    trend_counts = near_any["trend"].fillna("Unknown").value_counts()
    dominant_trend = trend_counts.index[0] if not trend_counts.empty else "Unknown"

    lines.extend(
        [
            "## 핵심 해석",
            "",
            f"- 전체 평균 종합점수는 **{fmt_num(avg_score, 0)}점**입니다. 세부 평균은 차트 **{fmt_num(avg_chart, 0)}**, 기술 **{fmt_num(avg_technical, 0)}**, 재무 **{fmt_num(avg_fundamental, 0)}**입니다.",
            f"- 이동평균선 근접 종목은 전체 {total_universe}개 중 {total_near}개로, 스캔 유니버스의 **{near_ratio:.1f}%** 입니다. 복수 MA 근접 비중은 **{multi_ratio:.1f}%** 입니다.",
            f"- 근접 종목 평균 RSI는 **{fmt_num(avg_rsi, 0)}**, 과매도 후보는 **{oversold_count}개**, 과열 경고 구간은 **{hot_count}개** 입니다.",
            f"- 근접 종목 평균 업사이드는 **{fmt_num(avg_upside, 1, '%')}**, 52주 고점 대비 평균 괴리는 **{fmt_num(avg_from_high, 1, '%')}** 입니다.",
            f"- 근접 종목의 대표 추세는 **{dominant_trend}** 입니다. 추세, 기술지표, 재무/테마/모멘텀 점수를 같이 보며 후보를 선별합니다.",
            "",
            "---",
            "",
        ]
    )

    ranked = frame.sort_values(["composite_score", "near_count"], ascending=[False, False]).head(10)
    lines.extend(
        [
            "## 1. 오늘의 핵심 후보",
            "",
            "> 복합 스코어링(차트·기술·재무·테마·모멘텀)을 반영한 전체 유니버스 상위 후보입니다.",
            "",
        ]
    )
    section_table(lines, ranked)
    for _, row in ranked.iterrows():
        lines.append(describe_pick(row))
    lines.extend(["", "---", ""])

    oversold = near_any[
        near_any["rsi"].notna()
        & (near_any["rsi"] < 40)
        & (near_any["trend"] != "Strong Downtrend")
    ].sort_values(["technical_score", "rsi"], ascending=[False, True])
    pullback = near_any[
        near_any["trend_score"].fillna(0).ge(3)
        & near_any["rsi"].notna()
        & near_any["rsi"].between(30, 55)
    ].sort_values(["composite_score", "chart_score"], ascending=[False, False])
    lines.extend(
        [
            "## 2. 전략별 후보",
            "",
            "### A. 상승추세 눌림 포착",
            "",
            "> 추세가 유지되면서 이동평균선 근처로 눌린 종목입니다. PRD의 Pullback in Uptrend 관점입니다.",
            "",
        ]
    )
    section_table(lines, pullback, limit=10)
    if not pullback.empty:
        best = pullback.iloc[0]
        lines.append(
            f"- 눌림목 관점의 선두는 **{best.get('display_symbol')}** 로, "
            f"종합 {fmt_num(best.get('composite_score'), 0)}점과 {ma_tag(best)}가 함께 보입니다."
        )
        lines.append("")

    lines.extend(
        [
            "### B. 과매도 반등 후보",
            "",
            "> RSI 40 미만이면서 이동평균선에 근접해 있는 종목입니다. Strong Downtrend 종목은 제외합니다.",
            "",
        ]
    )
    section_table(lines, oversold, limit=8)
    if not oversold.empty:
        best = oversold.iloc[0]
        lines.append(
            f"- 가장 강한 과매도 후보는 **{best.get('display_symbol')}** 로, RSI {fmt_num(best.get('rsi'), 0)}에서 "
            f"{ma_tag(best)} 구간을 시험 중입니다."
        )
        lines.append("")

    lines.extend(
        [
            "### C. 복수 MA 수렴 구간",
            "",
            "> 단기, 중기, 장기 평균선이 가격 근처로 모인 종목입니다.",
            "",
        ]
    )
    near_multi_sorted = near_multi.sort_values(["near_count", "composite_score"], ascending=[False, False])
    section_table(lines, near_multi_sorted, limit=10)
    if not near_multi_sorted.empty:
        leader = near_multi_sorted.iloc[0]
        lines.append(
            f"- 복수 MA 수렴의 중심 후보는 **{leader.get('display_symbol')}** 이며, "
            f"{ma_tag(leader)} 구간에서 방향성 선택을 앞둔 모습입니다."
        )
        lines.append("")

    growth = near_any[
        near_any["upside_pct"].notna()
        & (near_any["upside_pct"] >= 20)
        & (near_any["rsi"].isna() | (near_any["rsi"] < 65))
    ].sort_values(["flow_score", "upside_pct"], ascending=[False, False])
    lines.extend(
        [
            "### D. 가격 흐름·업사이드 개선 구간",
            "",
            "> 업사이드 20% 이상 + RSI 65 미만 종목입니다. 가격/거래량 기반 모멘텀 점수와 목표가 여력을 함께 봅니다.",
            "",
        ]
    )
    section_table(lines, growth, limit=10)
    if not growth.empty:
        leader = growth.iloc[0]
        lines.append(
            f"- 성장 기대 구간의 선두는 **{leader.get('display_symbol')}** 로, "
            f"업사이드 {fmt_num(leader.get('upside_pct'), 1, '%')}와 {ma_tag(leader)}가 함께 보입니다."
        )
        lines.append("")

    macd_improving = near_any[
        near_any["macd_state"].isin(["Bullish", "Positive", "Improving"])
    ].sort_values(["technical_score", "composite_score"], ascending=[False, False])
    lines.extend(
        [
            "### E. MACD 개선 후보",
            "",
            "> MACD 히스토그램이 우호적이거나 개선 중인 종목입니다.",
            "",
        ]
    )
    section_table(lines, macd_improving, limit=8)
    if not macd_improving.empty:
        leader = macd_improving.iloc[0]
        lines.append(
            f"- MACD 개선 후보의 선두는 **{leader.get('display_symbol')}** 로, "
            f"MACD 상태는 {leader.get('macd_state')}이고 기술점수는 {fmt_num(leader.get('technical_score'), 0)}점입니다."
        )
        lines.append("")
    lines.extend(["---", ""])

    lines.extend(["## 3. 섹터 분포", ""])
    sector_counts = near_any["sector"].fillna("Unknown").value_counts()
    lines.extend(["| 섹터 | 근접 종목 수 | 비중 |", "|---|---:|---:|"])
    for sector, count in sector_counts.items():
        ratio = (count / len(near_any) * 100) if len(near_any) else 0
        lines.append(f"| {sector} | {int(count)} | {ratio:.1f}% |")
    lines.append("")
    lines.extend(sector_commentary(near_any))
    lines.extend(["", "---", ""])

    hot = near_any[near_any["rsi"].notna() & (near_any["rsi"] >= 70)].sort_values("rsi", ascending=False)
    lines.extend(
        [
            "## 4. 주의 종목",
            "",
            "> RSI 70 이상인데 이동평균선 근처에 있는 경우 단기 과열일 수 있습니다.",
            "",
        ]
    )
    section_table(lines, hot, limit=8)
    if not hot.empty:
        leader = hot.iloc[0]
        lines.append(
            f"- 단기 과열 경계선의 상단은 **{leader.get('display_symbol')}** 이며, "
            f"RSI {fmt_num(leader.get('rsi'), 0)}에서 추격 매수는 신중할 필요가 있습니다."
        )
        lines.append("")
    lines.extend(["---", ""])

    lines.extend(["## 5. 전체 근접 종목 목록", ""])
    for period in settings.ma_periods:
        near_df = frame[frame[f"near_{period}"]].copy()
        diff_col = f"diff_{period}"
        if diff_col not in near_df.columns:
            lines.extend([f"### MA{period} 근접", "", "_기준 컬럼이 없어 목록을 생략했습니다._", ""])
            continue
        near_df["_abs_diff"] = near_df[diff_col].abs()
        near_df = near_df.sort_values("_abs_diff")
        lines.extend([f"### MA{period} 근접 ({len(near_df)}개)", ""])
        section_table(lines, near_df)

    lines.append("*본 리포트는 스캐너 데이터와 규칙 기반 점수로 생성되었으며 투자 조언이 아닙니다. 투자 판단은 본인 책임 하에 이루어져야 합니다.*")
    return lines


def write_markdown(frame: pd.DataFrame, market: MarketDefinition, settings: ScanSettings, date_str: str, path: Path) -> str:
    frame = enrich_metadata_frame(frame, market)
    text = "\n".join(_summary_lines_rich(frame, market, settings, date_str))
    path.write_text(text, encoding="utf-8")
    return text
