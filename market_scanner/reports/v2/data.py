"""v2 페이지 생성에 필요한 DB 조회 모듈.

기존 render.py 와는 별개로, 메인/시장/전략 페이지가 공통으로 쓰는 조회만 모음.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass
class MarketCard:
    """메인 페이지의 시장 카드 한 칸."""

    market_key: str
    label: str
    trade_date: date
    universe_key: str
    total_count: int
    advance_count: int
    decline_count: int
    unchanged_count: int
    avg_change_pct: float | None
    avg_rsi14: float | None
    market_score: float | None
    regime: str | None
    risk_level: str | None
    bullish_breadth_pct: float | None


@dataclass
class TopStock:
    """Top 종목 행."""

    market_key: str
    market_label: str
    rank_no: int | None
    symbol: str
    display_symbol: str
    name_local: str | None
    sector: str | None
    composite_score: float | None
    change_pct: float | None
    close_price: float | None
    rsi14: float | None
    setup_label: str | None


@dataclass
class SectorCell:
    """섹터 히트맵 한 칸."""

    market_key: str
    sector: str
    instrument_count: int
    avg_change_pct: float | None
    avg_composite_score: float | None


@dataclass
class MacroQuote:
    """글로벌 매크로 한 행 (지수, 원자재)."""

    market_key: str
    symbol: str
    display_symbol: str
    name_local: str | None
    close_price: float | None
    change_pct: float | None
    trade_date: date


@dataclass
class WatchlistStock:
    """워치리스트 패널용 종목 행."""

    panel_key: str
    symbol: str
    display_symbol: str
    name_local: str | None
    market_key: str
    market_label: str
    trend_score: float | None
    rsi: float | None
    change_pct: float | None
    volume_ratio: float | None
    diff_60: float | None
    diff_120: float | None
    diff_240: float | None
    price: float | None
    composite_score: float | None


@dataclass
class MainPageData:
    """메인 페이지에 필요한 모든 데이터."""

    generated_at: date
    market_cards: list[MarketCard] = field(default_factory=list)
    top_stocks: list[TopStock] = field(default_factory=list)
    sector_cells: list[SectorCell] = field(default_factory=list)
    macro_quotes: list[MacroQuote] = field(default_factory=list)
    watchlist_stocks: list[WatchlistStock] = field(default_factory=list)


# 시장 페이지에서 다룰 전략 키와 라벨. scan_results 컬럼명과 1:1.
STRATEGY_KEYS: tuple[tuple[str, str], ...] = (
    ("pullback_score", "이평선 눌림"),
    ("breakout_score", "신고가/고점 돌파"),
    ("box_breakout_score", "박스권 돌파"),
    ("reversal_score", "과매도 반등"),
    ("trend_quality_score", "추세 품질"),
)


@dataclass
class MarketDetailData:
    """시장 서브페이지 한 장에 필요한 데이터."""

    market_key: str
    label: str
    summary: MarketCard | None
    sectors: list[SectorCell] = field(default_factory=list)
    top_stocks: list[TopStock] = field(default_factory=list)
    # strategy_score_col -> top rows (각 상위 N)
    strategy_top: dict[str, list[TopStock]] = field(default_factory=dict)
    # MA 근접 종목 수: {"60": N, "120": N, "240": N}
    ma_near_counts: dict[str, int] = field(default_factory=dict)


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def load_market_cards(conn) -> list[MarketCard]:
    """활성 시장의 최신 market_snapshots 카드.

    같은 market에서 universe가 여러 개면 market_key == universe_key 인 행을 우선,
    없으면 trade_date 최신/total_count 최대인 행을 고른다.
    """
    rows = conn.execute(
        """
        WITH latest AS (
            SELECT
                ms.*,
                m.label AS market_label,
                ROW_NUMBER() OVER (
                    PARTITION BY ms.market_key
                    ORDER BY
                        ms.trade_date DESC,
                        CASE WHEN ms.universe_key = ms.market_key THEN 0 ELSE 1 END,
                        ms.total_count DESC
                ) AS rn
            FROM market_snapshots ms
            JOIN markets m ON m.market_key = ms.market_key
            WHERE m.is_active = TRUE
        )
        SELECT
            market_key, market_label, trade_date, universe_key,
            total_count, advance_count, decline_count, unchanged_count,
            avg_change_pct, avg_rsi14, market_score,
            regime, risk_level, bullish_breadth_pct
        FROM latest
        WHERE rn = 1
        ORDER BY market_key
        """
    ).fetchall()

    return [
        MarketCard(
            market_key=r[0],
            label=r[1],
            trade_date=r[2],
            universe_key=r[3],
            total_count=r[4] or 0,
            advance_count=r[5] or 0,
            decline_count=r[6] or 0,
            unchanged_count=r[7] or 0,
            avg_change_pct=_to_float(r[8]),
            avg_rsi14=_to_float(r[9]),
            market_score=_to_float(r[10]),
            regime=r[11],
            risk_level=r[12],
            bullish_breadth_pct=_to_float(r[13]),
        )
        for r in rows
    ]


def load_top_stocks(conn, limit: int = 30) -> list[TopStock]:
    """시장 통합 composite_score 상위 N. 가장 최신 trade_date 기준.

    market_key 별로 최신 trade_date 의 scan_results 에서 가져온 뒤,
    composite_score 내림차순으로 정렬. 같은 (instrument, trade_date) 에 여러
    run 결과가 있으면 가장 최근 created_at 행만 사용한다.
    """
    rows = conn.execute(
        """
        WITH latest_dates AS (
            SELECT market_key, MAX(trade_date) AS trade_date
            FROM scan_results
            GROUP BY market_key
        ),
        dedup AS (
            SELECT DISTINCT ON (sr.instrument_id, sr.trade_date)
                sr.instrument_id, sr.trade_date, sr.market_key,
                sr.rank_no, sr.composite_score, sr.change_pct,
                sr.close_price, sr.rsi14, sr.setup_label
            FROM scan_results sr
            JOIN latest_dates ld
              ON ld.market_key = sr.market_key
             AND ld.trade_date = sr.trade_date
            ORDER BY sr.instrument_id, sr.trade_date, sr.created_at DESC
        )
        SELECT
            d.market_key,
            m.label AS market_label,
            d.rank_no,
            i.symbol,
            COALESCE(i.display_symbol, i.symbol) AS display_symbol,
            i.name_local,
            i.sector,
            d.composite_score,
            d.change_pct,
            d.close_price,
            d.rsi14,
            d.setup_label
        FROM dedup d
        JOIN instruments i ON i.instrument_id = d.instrument_id
        JOIN markets m ON m.market_key = d.market_key
        WHERE m.is_active = TRUE
          AND d.composite_score IS NOT NULL
        ORDER BY d.composite_score DESC
        LIMIT %s
        """,
        (limit,),
    ).fetchall()

    return [
        TopStock(
            market_key=r[0],
            market_label=r[1],
            rank_no=r[2],
            symbol=r[3],
            display_symbol=r[4],
            name_local=r[5],
            sector=r[6],
            composite_score=_to_float(r[7]),
            change_pct=_to_float(r[8]),
            close_price=_to_float(r[9]),
            rsi14=_to_float(r[10]),
            setup_label=r[11],
        )
        for r in rows
    ]


def load_sector_cells(conn, per_market_top: int = 10) -> list[SectorCell]:
    """시장별 sector_snapshots 상위 N (instrument_count 기준)."""
    rows = conn.execute(
        """
        WITH ranked AS (
            SELECT
                ss.market_key,
                ss.sector,
                ss.instrument_count,
                ss.avg_change_pct,
                ss.avg_composite_score,
                ROW_NUMBER() OVER (
                    PARTITION BY ss.market_key
                    ORDER BY ss.instrument_count DESC
                ) AS rn
            FROM sector_snapshots ss
            JOIN markets m ON m.market_key = ss.market_key
            WHERE m.is_active = TRUE
              AND (ss.market_key, ss.trade_date) IN (
                  SELECT market_key, MAX(trade_date)
                  FROM sector_snapshots
                  GROUP BY market_key
              )
              AND ss.universe_key = ss.market_key
              AND ss.sector IS NOT NULL
              AND ss.sector <> ''
        )
        SELECT market_key, sector, instrument_count, avg_change_pct, avg_composite_score
        FROM ranked
        WHERE rn <= %s
        ORDER BY market_key, rn
        """,
        (per_market_top,),
    ).fetchall()

    return [
        SectorCell(
            market_key=r[0],
            sector=r[1],
            instrument_count=r[2] or 0,
            avg_change_pct=_to_float(r[3]),
            avg_composite_score=_to_float(r[4]),
        )
        for r in rows
    ]


def load_macro_quotes(conn) -> list[MacroQuote]:
    """global-indices, commodities 의 최신 daily_prices.

    이 시장들은 scan_results 가 없으므로 daily_prices 에서 직접 가져오고,
    전일 종가로 등락률을 계산한다.
    """
    rows = conn.execute(
        """
        WITH latest AS (
            SELECT
                i.instrument_id,
                i.market_key,
                i.symbol,
                COALESCE(i.display_symbol, i.symbol) AS display_symbol,
                i.name_local,
                MAX(dp.trade_date) AS trade_date
            FROM instruments i
            JOIN daily_prices dp ON dp.instrument_id = i.instrument_id
            WHERE i.market_key IN ('global-indices', 'commodities')
              AND i.is_active = TRUE
            GROUP BY i.instrument_id, i.market_key, i.symbol, i.display_symbol, i.name_local
        ),
        with_close AS (
            SELECT
                l.market_key, l.symbol, l.display_symbol, l.name_local, l.trade_date,
                (
                    SELECT close_price FROM daily_prices
                    WHERE instrument_id = l.instrument_id AND trade_date = l.trade_date
                    ORDER BY source_provider LIMIT 1
                ) AS close_price,
                (
                    SELECT close_price FROM daily_prices
                    WHERE instrument_id = l.instrument_id AND trade_date < l.trade_date
                    ORDER BY trade_date DESC, source_provider LIMIT 1
                ) AS prev_close
            FROM latest l
        )
        SELECT
            market_key, symbol, display_symbol, name_local, close_price,
            CASE
                WHEN prev_close IS NULL OR prev_close = 0 THEN NULL
                ELSE (close_price - prev_close) / prev_close * 100.0
            END AS change_pct,
            trade_date
        FROM with_close
        WHERE close_price IS NOT NULL
        ORDER BY market_key, symbol
        """
    ).fetchall()

    return [
        MacroQuote(
            market_key=r[0],
            symbol=r[1],
            display_symbol=r[2],
            name_local=r[3],
            close_price=_to_float(r[4]),
            change_pct=_to_float(r[5]),
            trade_date=r[6],
        )
        for r in rows
    ]


def load_watchlist_stocks(conn, per_panel: int = 5) -> list[WatchlistStock]:
    """6개 워치리스트 패널용 종목을 한 번에 로드."""
    rows = conn.execute(
        """
        WITH latest_dates AS (
            SELECT market_key, MAX(trade_date) AS trade_date
            FROM scan_results GROUP BY market_key
        )
        SELECT DISTINCT ON (sr.instrument_id)
            i.symbol,
            COALESCE(i.display_symbol, i.symbol),
            i.name_local,
            sr.market_key,
            m.label,
            di.trend_score,
            di.rsi14,
            COALESCE(di.change_pct, sr.change_pct),
            di.volume_ratio,
            di.diff_60_pct,
            di.diff_120_pct,
            di.diff_240_pct,
            COALESCE(sr.close_price, dp.close_price),
            sr.composite_score,
            sr.pullback_score,
            sr.reversal_score
        FROM scan_results sr
        JOIN latest_dates ld
            ON ld.market_key = sr.market_key
           AND ld.trade_date = sr.trade_date
        JOIN instruments i ON i.instrument_id = sr.instrument_id
        JOIN markets m ON m.market_key = sr.market_key
        LEFT JOIN daily_indicators di
            ON di.instrument_id = sr.instrument_id
           AND di.trade_date = sr.trade_date
        LEFT JOIN LATERAL (
            SELECT close_price FROM daily_prices
            WHERE instrument_id = sr.instrument_id AND trade_date = sr.trade_date
            ORDER BY source_provider LIMIT 1
        ) dp ON TRUE
        WHERE m.is_active = TRUE
        ORDER BY sr.instrument_id, sr.created_at DESC
        """
    ).fetchall()

    pool: list[dict] = [
        {
            "symbol": r[0], "display_symbol": r[1], "name_local": r[2],
            "market_key": r[3], "market_label": r[4],
            "trend_score": _to_float(r[5]), "rsi": _to_float(r[6]),
            "change_pct": _to_float(r[7]), "volume_ratio": _to_float(r[8]),
            "diff_60": _to_float(r[9]), "diff_120": _to_float(r[10]),
            "diff_240": _to_float(r[11]), "price": _to_float(r[12]),
            "composite_score": _to_float(r[13]),
            "_pullback": _to_float(r[14]), "_reversal": _to_float(r[15]),
        }
        for r in rows
    ]

    def _make(panel_key: str, items: list[dict]) -> list[WatchlistStock]:
        return [
            WatchlistStock(
                panel_key=panel_key,
                symbol=d["symbol"], display_symbol=d["display_symbol"],
                name_local=d["name_local"], market_key=d["market_key"],
                market_label=d["market_label"], trend_score=d["trend_score"],
                rsi=d["rsi"], change_pct=d["change_pct"],
                volume_ratio=d["volume_ratio"], diff_60=d["diff_60"],
                diff_120=d["diff_120"], diff_240=d["diff_240"],
                price=d["price"], composite_score=d["composite_score"],
            )
            for d in items[:per_panel]
        ]

    result: list[WatchlistStock] = []
    result.extend(_make("momentum",
        sorted([d for d in pool if d["composite_score"] is not None],
               key=lambda d: d["composite_score"], reverse=True)))
    result.extend(_make("pullback",
        sorted([d for d in pool if d["_pullback"] is not None],
               key=lambda d: d["_pullback"], reverse=True)))
    result.extend(_make("oversold",
        sorted([d for d in pool if d["rsi"] is not None and d["rsi"] < 40],
               key=lambda d: d["_reversal"] or 0, reverse=True)))
    result.extend(_make("overbought",
        sorted([d for d in pool if d["rsi"] is not None and d["rsi"] > 65],
               key=lambda d: d["rsi"], reverse=True)))
    result.extend(_make("turnaround",
        sorted([d for d in pool if d["change_pct"] is not None],
               key=lambda d: d["change_pct"], reverse=True)))
    result.extend(_make("volume_surge",
        sorted([d for d in pool if d["volume_ratio"] is not None],
               key=lambda d: d["volume_ratio"], reverse=True)))
    return result


def load_main_page_data(conn, top_n: int = 30, sector_per_market: int = 10) -> MainPageData:
    """메인 페이지에 필요한 섹션 한 번에 로드."""
    cards = load_market_cards(conn)
    generated_at = max((c.trade_date for c in cards), default=date.today())
    return MainPageData(
        generated_at=generated_at,
        market_cards=cards,
        top_stocks=load_top_stocks(conn, top_n),
        sector_cells=load_sector_cells(conn, sector_per_market),
        macro_quotes=load_macro_quotes(conn),
        watchlist_stocks=load_watchlist_stocks(conn),
    )


def load_market_summary(conn, market_key: str) -> MarketCard | None:
    """단일 시장의 최신 market_snapshots → MarketCard. 없으면 None."""
    row = conn.execute(
        """
        SELECT
            ms.market_key, m.label, ms.trade_date, ms.universe_key,
            ms.total_count, ms.advance_count, ms.decline_count, ms.unchanged_count,
            ms.avg_change_pct, ms.avg_rsi14, ms.market_score,
            ms.regime, ms.risk_level, ms.bullish_breadth_pct
        FROM market_snapshots ms
        JOIN markets m ON m.market_key = ms.market_key
        WHERE ms.market_key = %s
        ORDER BY
            ms.trade_date DESC,
            CASE WHEN ms.universe_key = ms.market_key THEN 0 ELSE 1 END,
            ms.total_count DESC
        LIMIT 1
        """,
        (market_key,),
    ).fetchone()
    if not row:
        return None
    return MarketCard(
        market_key=row[0],
        label=row[1],
        trade_date=row[2],
        universe_key=row[3],
        total_count=row[4] or 0,
        advance_count=row[5] or 0,
        decline_count=row[6] or 0,
        unchanged_count=row[7] or 0,
        avg_change_pct=_to_float(row[8]),
        avg_rsi14=_to_float(row[9]),
        market_score=_to_float(row[10]),
        regime=row[11],
        risk_level=row[12],
        bullish_breadth_pct=_to_float(row[13]),
    )


def load_market_sectors(conn, market_key: str) -> list[SectorCell]:
    """해당 시장의 최신 sector_snapshots 전부."""
    rows = conn.execute(
        """
        SELECT sector, instrument_count, avg_change_pct, avg_composite_score
        FROM sector_snapshots
        WHERE market_key = %s
          AND universe_key = market_key
          AND trade_date = (
              SELECT MAX(trade_date) FROM sector_snapshots
              WHERE market_key = %s AND universe_key = market_key
          )
          AND sector IS NOT NULL
          AND sector <> ''
        ORDER BY instrument_count DESC
        """,
        (market_key, market_key),
    ).fetchall()
    return [
        SectorCell(
            market_key=market_key,
            sector=r[0],
            instrument_count=r[1] or 0,
            avg_change_pct=_to_float(r[2]),
            avg_composite_score=_to_float(r[3]),
        )
        for r in rows
    ]


def load_market_top_stocks(conn, market_key: str, limit: int = 50) -> list[TopStock]:
    """해당 시장의 composite_score 상위 N."""
    rows = conn.execute(
        """
        WITH latest AS (
            SELECT MAX(trade_date) AS trade_date FROM scan_results WHERE market_key = %s
        ),
        dedup AS (
            SELECT DISTINCT ON (sr.instrument_id, sr.trade_date)
                sr.instrument_id, sr.rank_no, sr.composite_score, sr.change_pct,
                sr.close_price, sr.rsi14, sr.setup_label
            FROM scan_results sr, latest l
            WHERE sr.market_key = %s AND sr.trade_date = l.trade_date
            ORDER BY sr.instrument_id, sr.trade_date, sr.created_at DESC
        )
        SELECT
            %s::TEXT,
            m.label,
            d.rank_no,
            i.symbol,
            COALESCE(i.display_symbol, i.symbol),
            i.name_local,
            i.sector,
            d.composite_score,
            d.change_pct,
            d.close_price,
            d.rsi14,
            d.setup_label
        FROM dedup d
        JOIN instruments i ON i.instrument_id = d.instrument_id
        JOIN markets m ON m.market_key = %s
        WHERE d.composite_score IS NOT NULL
        ORDER BY d.composite_score DESC
        LIMIT %s
        """,
        (market_key, market_key, market_key, market_key, limit),
    ).fetchall()
    return [
        TopStock(
            market_key=r[0],
            market_label=r[1],
            rank_no=r[2],
            symbol=r[3],
            display_symbol=r[4],
            name_local=r[5],
            sector=r[6],
            composite_score=_to_float(r[7]),
            change_pct=_to_float(r[8]),
            close_price=_to_float(r[9]),
            rsi14=_to_float(r[10]),
            setup_label=r[11],
        )
        for r in rows
    ]


def load_market_strategy_top(
    conn, market_key: str, score_column: str, limit: int = 5
) -> list[TopStock]:
    """전략 점수 컬럼 상위 N. score_column 은 STRATEGY_KEYS 중 하나여야 한다."""
    valid = {key for key, _ in STRATEGY_KEYS}
    if score_column not in valid:
        raise ValueError(f"Unknown strategy score column: {score_column}")

    # f-string 으로 컬럼명 삽입 — 화이트리스트 검증 후라 안전.
    sql = f"""
        WITH latest AS (
            SELECT MAX(trade_date) AS trade_date FROM scan_results WHERE market_key = %s
        ),
        dedup AS (
            SELECT DISTINCT ON (sr.instrument_id, sr.trade_date)
                sr.instrument_id, sr.rank_no, sr.composite_score, sr.change_pct,
                sr.close_price, sr.rsi14, sr.setup_label, sr.{score_column} AS score
            FROM scan_results sr, latest l
            WHERE sr.market_key = %s AND sr.trade_date = l.trade_date
            ORDER BY sr.instrument_id, sr.trade_date, sr.created_at DESC
        )
        SELECT
            %s::TEXT, m.label, d.rank_no, i.symbol,
            COALESCE(i.display_symbol, i.symbol),
            i.name_local, i.sector,
            d.score AS strategy_score,
            d.change_pct, d.close_price, d.rsi14, d.setup_label
        FROM dedup d
        JOIN instruments i ON i.instrument_id = d.instrument_id
        JOIN markets m ON m.market_key = %s
        WHERE d.score IS NOT NULL
        ORDER BY d.score DESC
        LIMIT %s
    """
    rows = conn.execute(sql, (market_key, market_key, market_key, market_key, limit)).fetchall()
    # 전략 점수는 composite_score 자리에 담아 표시 (UI 가 단일 점수 컬럼만 쓰므로 재사용)
    return [
        TopStock(
            market_key=r[0],
            market_label=r[1],
            rank_no=r[2],
            symbol=r[3],
            display_symbol=r[4],
            name_local=r[5],
            sector=r[6],
            composite_score=_to_float(r[7]),
            change_pct=_to_float(r[8]),
            close_price=_to_float(r[9]),
            rsi14=_to_float(r[10]),
            setup_label=r[11],
        )
        for r in rows
    ]


def load_ma_near_counts(conn, market_key: str, threshold_pct: float = 5.0) -> dict[str, int]:
    """MA 근접 종목 수 (60/120/240일, ±threshold_pct% 이내)."""
    row = conn.execute(
        """
        WITH latest AS (
            SELECT MAX(trade_date) AS trade_date FROM scan_results WHERE market_key = %s
        )
        SELECT
            COUNT(CASE WHEN ABS(di.diff_60_pct)  <= %s THEN 1 END),
            COUNT(CASE WHEN ABS(di.diff_120_pct) <= %s THEN 1 END),
            COUNT(CASE WHEN ABS(di.diff_240_pct) <= %s THEN 1 END)
        FROM scan_results sr
        JOIN daily_indicators di
            ON di.instrument_id = sr.instrument_id
           AND di.trade_date = sr.trade_date
        WHERE sr.market_key = %s
          AND sr.trade_date = (SELECT trade_date FROM latest)
        """,
        (market_key, threshold_pct, threshold_pct, threshold_pct, market_key),
    ).fetchone()
    if not row:
        return {"60": 0, "120": 0, "240": 0}
    return {"60": row[0] or 0, "120": row[1] or 0, "240": row[2] or 0}


def load_market_detail_data(
    conn,
    market_key: str,
    *,
    top_n: int = 50,
    strategy_n: int = 5,
) -> MarketDetailData:
    """시장 서브페이지에 필요한 데이터 한 번에 로드."""
    summary = load_market_summary(conn, market_key)
    label = summary.label if summary else market_key
    return MarketDetailData(
        market_key=market_key,
        label=label,
        summary=summary,
        sectors=load_market_sectors(conn, market_key),
        top_stocks=load_market_top_stocks(conn, market_key, top_n),
        strategy_top={
            col: load_market_strategy_top(conn, market_key, col, strategy_n)
            for col, _ in STRATEGY_KEYS
        },
        ma_near_counts=load_ma_near_counts(conn, market_key),
    )


@dataclass
class SectorDetailData:
    """섹터 서브페이지에 필요한 데이터."""

    market_key: str
    market_label: str
    sector: str
    trade_date: date | None
    instrument_count: int
    avg_change_pct: float | None
    avg_composite_score: float | None
    top_stocks: list[TopStock] = field(default_factory=list)
    strategy_top: dict[str, list[TopStock]] = field(default_factory=dict)


def sector_slug(sector: str) -> str:
    """섹터 이름을 파일시스템/URL-safe 디렉터리 이름으로 변환."""
    slug = sector.strip()
    for ch in r'\/:*?"<>|':
        slug = slug.replace(ch, "-")
    return slug or "unknown"


def load_sector_top_stocks(conn, market_key: str, sector: str, limit: int = 30) -> list[TopStock]:
    """섹터 내 composite_score 상위 종목."""
    rows = conn.execute(
        """
        WITH latest AS (
            SELECT MAX(trade_date) AS trade_date FROM scan_results WHERE market_key = %s
        ),
        dedup AS (
            SELECT DISTINCT ON (sr.instrument_id)
                sr.instrument_id, sr.rank_no, sr.composite_score, sr.change_pct,
                sr.close_price, sr.rsi14, sr.setup_label
            FROM scan_results sr
            CROSS JOIN latest l
            WHERE sr.market_key = %s AND sr.trade_date = l.trade_date
            ORDER BY sr.instrument_id, sr.trade_date, sr.created_at DESC
        )
        SELECT
            %s::TEXT, m.label, d.rank_no, i.symbol,
            COALESCE(i.display_symbol, i.symbol),
            i.name_local, i.sector,
            d.composite_score, d.change_pct, d.close_price, d.rsi14, d.setup_label
        FROM dedup d
        JOIN instruments i ON i.instrument_id = d.instrument_id
        JOIN markets m ON m.market_key = %s
        WHERE i.sector = %s AND d.composite_score IS NOT NULL
        ORDER BY d.composite_score DESC
        LIMIT %s
        """,
        (market_key, market_key, market_key, market_key, sector, limit),
    ).fetchall()
    return [
        TopStock(
            market_key=r[0], market_label=r[1], rank_no=r[2], symbol=r[3],
            display_symbol=r[4], name_local=r[5], sector=r[6],
            composite_score=_to_float(r[7]), change_pct=_to_float(r[8]),
            close_price=_to_float(r[9]), rsi14=_to_float(r[10]), setup_label=r[11],
        )
        for r in rows
    ]


def load_sector_strategy_top(
    conn, market_key: str, sector: str, score_column: str, limit: int = 5
) -> list[TopStock]:
    """섹터 내 전략 점수 컬럼 상위 N."""
    valid = {key for key, _ in STRATEGY_KEYS}
    if score_column not in valid:
        raise ValueError(f"Unknown strategy score column: {score_column}")
    sql = f"""
        WITH latest AS (
            SELECT MAX(trade_date) AS trade_date FROM scan_results WHERE market_key = %s
        ),
        dedup AS (
            SELECT DISTINCT ON (sr.instrument_id)
                sr.instrument_id, sr.rank_no, sr.composite_score, sr.change_pct,
                sr.close_price, sr.rsi14, sr.setup_label, sr.{score_column} AS score
            FROM scan_results sr
            CROSS JOIN latest l
            WHERE sr.market_key = %s AND sr.trade_date = l.trade_date
            ORDER BY sr.instrument_id, sr.trade_date, sr.created_at DESC
        )
        SELECT
            %s::TEXT, m.label, d.rank_no, i.symbol,
            COALESCE(i.display_symbol, i.symbol),
            i.name_local, i.sector,
            d.score, d.change_pct, d.close_price, d.rsi14, d.setup_label
        FROM dedup d
        JOIN instruments i ON i.instrument_id = d.instrument_id
        JOIN markets m ON m.market_key = %s
        WHERE i.sector = %s AND d.score IS NOT NULL
        ORDER BY d.score DESC
        LIMIT %s
    """
    rows = conn.execute(
        sql, (market_key, market_key, market_key, market_key, sector, limit)
    ).fetchall()
    return [
        TopStock(
            market_key=r[0], market_label=r[1], rank_no=r[2], symbol=r[3],
            display_symbol=r[4], name_local=r[5], sector=r[6],
            composite_score=_to_float(r[7]), change_pct=_to_float(r[8]),
            close_price=_to_float(r[9]), rsi14=_to_float(r[10]), setup_label=r[11],
        )
        for r in rows
    ]


def load_sector_detail_data(
    conn, market_key: str, sector: str, *, top_n: int = 30, strategy_n: int = 5
) -> SectorDetailData:
    """섹터 서브페이지에 필요한 데이터 한 번에 로드."""
    snap = conn.execute(
        """
        SELECT ss.instrument_count, ss.avg_change_pct, ss.avg_composite_score,
               ss.trade_date, m.label
        FROM sector_snapshots ss
        JOIN markets m ON m.market_key = ss.market_key
        WHERE ss.market_key = %s AND ss.sector = %s AND ss.universe_key = ss.market_key
        ORDER BY ss.trade_date DESC
        LIMIT 1
        """,
        (market_key, sector),
    ).fetchone()
    return SectorDetailData(
        market_key=market_key,
        market_label=snap[4] if snap else market_key,
        sector=sector,
        trade_date=snap[3] if snap else None,
        instrument_count=snap[0] or 0 if snap else 0,
        avg_change_pct=_to_float(snap[1]) if snap else None,
        avg_composite_score=_to_float(snap[2]) if snap else None,
        top_stocks=load_sector_top_stocks(conn, market_key, sector, top_n),
        strategy_top={
            col: load_sector_strategy_top(conn, market_key, sector, col, strategy_n)
            for col, _ in STRATEGY_KEYS
        },
    )


def list_buildable_markets(conn) -> list[str]:
    """market_snapshots 또는 scan_results 가 하나라도 있는 활성 시장 키."""
    rows = conn.execute(
        """
        SELECT DISTINCT m.market_key
        FROM markets m
        WHERE m.is_active = TRUE
          AND (
            EXISTS (SELECT 1 FROM market_snapshots ms WHERE ms.market_key = m.market_key)
            OR EXISTS (SELECT 1 FROM scan_results sr WHERE sr.market_key = m.market_key)
          )
        ORDER BY m.market_key
        """
    ).fetchall()
    return [r[0] for r in rows]
