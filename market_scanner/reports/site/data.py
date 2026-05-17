"""페이지 생성에 필요한 DB 조회 모듈.

기존 render.py 와는 별개로, 메인/시장/전략 페이지가 공통으로 쓰는 조회만 모음.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from psycopg import sql


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
    collected_at: datetime | None = None


@dataclass
class DailyMacroItem:
    """daily_macro 테이블의 지표 한 행 (금리·환율·변동성 등)."""

    indicator_code: str
    trade_date: date
    value: float
    prev_value: float | None
    change_pct: float | None
    collected_at: datetime | None = None


@dataclass
class MacroPriceSeries:
    """global-indices / commodities / sector-etfs 종목의 가격 시계열 (정규화)."""

    market_key: str
    symbol: str
    display_symbol: str
    name_en: str | None
    dates: list[str]          # ISO date strings
    values: list[float | None]  # DB close_price 원본값 (JS에서 from 날짜 기준 재정규화)


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
    """메인 페이지 데이터. 매크로 지표와 글로벌 틱커 중심."""

    generated_at: date
    macro_quotes: list[MacroQuote] = field(default_factory=list)
    daily_macro_items: list[DailyMacroItem] = field(default_factory=list)
    macro_price_series: list[MacroPriceSeries] = field(default_factory=list)
    fx_strength_series: list[MacroPriceSeries] = field(default_factory=list)


@dataclass
class OverviewPageData:
    """US종합·KR종합 페이지 데이터. 히트맵·리더십·Top종목·워치리스트."""

    nav_key: str
    label: str
    generated_at: date
    market_cards: list[MarketCard] = field(default_factory=list)
    top_stocks: list[TopStock] = field(default_factory=list)
    sector_cells: list[SectorCell] = field(default_factory=list)
    watchlist_stocks: list[WatchlistStock] = field(default_factory=list)
    sector_etf_quotes: list[MacroQuote] = field(default_factory=list)
    sector_etf_price_series: list[MacroPriceSeries] = field(default_factory=list)
    daily_macro_items: list[DailyMacroItem] = field(default_factory=list)
    macro_history: dict[str, list[float]] = field(default_factory=dict)


@dataclass
class AdminColumn:
    """관리 페이지의 테이블 컬럼 메타데이터."""

    name: str
    data_type: str
    nullable: bool


@dataclass
class AdminTable:
    """관리 페이지의 테이블 한 칸."""

    name: str
    count: int
    order_column: str | None
    columns: list[AdminColumn] = field(default_factory=list)
    preview_columns: list[str] = field(default_factory=list)
    rows: list[list[object]] = field(default_factory=list)


@dataclass
class AdminCoverageRow:
    """운영 점검용 최신 적재/계산 커버리지 행."""

    dataset: str
    market_key: str | None
    universe_key: str | None
    source_provider: str | None
    trade_date: date | None
    row_count: int
    instrument_count: int | None
    target_count: int | None
    coverage_pct: float | None
    last_updated: datetime | None
    extra_value: float | None = None


@dataclass
class AdminRunRow:
    """최근 collection_runs 상태 행."""

    run_type: str
    market_key: str | None
    universe_key: str | None
    trade_date: date | None
    source_provider: str | None
    status: str
    requested_count: int
    success_count: int
    failed_count: int
    skipped_count: int
    started_at: datetime | None
    finished_at: datetime | None


@dataclass
class AdminPageData:
    """관리 페이지에 필요한 DB 테이블 스냅샷."""

    generated_at: datetime
    preview_limit: int
    prices: list[AdminCoverageRow] = field(default_factory=list)
    indicators: list[AdminCoverageRow] = field(default_factory=list)
    scans: list[AdminCoverageRow] = field(default_factory=list)
    macro: list[AdminCoverageRow] = field(default_factory=list)
    runs: list[AdminRunRow] = field(default_factory=list)
    tables: list[AdminTable] = field(default_factory=list)


# 시장 페이지에서 다룰 전략 키와 라벨. scan_results 컬럼명과 1:1.
STRATEGY_KEYS: tuple[tuple[str, str], ...] = (
    ("pullback_score", "이평선 눌림"),
    ("breakout_score", "신고가/고점 돌파"),
    ("box_breakout_score", "박스권 돌파"),
    ("reversal_score", "과매도 반등"),
    ("trend_quality_score", "추세 품질"),
)

UNIVERSE_DETAIL_PAGES: dict[str, tuple[str, str]] = {
    "nasdaq100": ("us", "NASDAQ100"),
    "sp500": ("us", "S&P500"),
    "dow30": ("us", "다우존스30"),
    "kospi": ("kr", "KOSPI"),
    "kosdaq": ("kr", "KOSDAQ"),
    "kospi200": ("kr", "KOSPI200"),
    "kosdaq150": ("kr", "KOSDAQ150"),
}

HIDDEN_ADMIN_COLUMNS: dict[str, set[str]] = {
    "collection_runs": {"run_id"},
    "daily_indicators": set(),
    "daily_macro": set(),
    "daily_prices": set(),
    "generated_reports": set(),
    "instrument_fundamentals": set(),
    "instrument_news": set(),
    "instruments": set(),
    "market_snapshots": set(),
    "markets": set(),
    "news_items": set(),
    "scan_results": set(),
    "sector_snapshots": set(),
    "universe_definitions": set(),
    "universe_memberships": set(),
}

INSTRUMENT_JOIN_ADMIN_TABLES: set[str] = {
    "daily_indicators",
    "daily_prices",
    "instrument_fundamentals",
    "instrument_news",
    "scan_results",
    "universe_memberships",
}

MACRO_SERIES_FALLBACKS: dict[str, tuple[str, str, str | None]] = {
    "SP500": ("global-indices", "GSPC", "S&P 500"),
    "NASDAQ100": ("global-indices", "NDX", "NASDAQ 100"),
    "KOSPI": ("global-indices", "KS11", "코스피"),
    "KOSDAQ": ("global-indices", "KQ11", "코스닥"),
    "VIX": ("global-indices", "VIX", "VIX"),
    "WTI": ("commodities", "CL", "WTI 원유"),
    "GOLD": ("commodities", "GC", "금"),
    "SILVER": ("commodities", "SI", "은"),
    "NATGAS": ("commodities", "NG", "천연가스"),
    "COPPER": ("commodities", "HG", "구리"),
}

FX_STRENGTH_SOURCES: tuple[tuple[str, str, str, bool], ...] = (
    ("DXY", "DXY", "달러인덱스", False),
    ("USDKRW", "KRW", "원화", True),
    ("EURUSD", "EUR", "유로", False),
    ("USDJPY", "JPY", "엔", True),
    ("USDCNY", "CNH", "위안", True),
    ("GBPUSD", "GBP", "파운드", False),
    ("AUDUSD", "AUD", "호주달러", False),
    ("NZDUSD", "NZD", "뉴질랜드달러", False),
    ("USDCAD", "CAD", "캐나다달러", True),
    ("USDCHF", "CHF", "스위스프랑", True),
    ("USDSGD", "SGD", "싱가포르달러", True),
    ("USDSEK", "SEK", "스웨덴크로나", True),
    ("USDNOK", "NOK", "노르웨이크로네", True),
    ("USDMXN", "MXN", "멕시코페소", True),
)


@dataclass
class MarketDetailData:
    """시장 서브페이지 한 장에 필요한 데이터."""

    market_key: str
    nav_key: str
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


def _admin_cell_value(value: object) -> object:
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, default=str)
    else:
        text = str(value)
    return text if len(text) <= 600 else text[:597] + "..."


def _admin_order_column(column_names: set[str]) -> str | None:
    for candidate in (
        "updated_at",
        "created_at",
        "collected_at",
        "calculated_at",
        "started_at",
        "published_at",
        "generated_at",
        "trade_date",
        "as_of_date",
        "instrument_id",
        "market_key",
    ):
        if candidate in column_names:
            return candidate
    return None


def _admin_preview_query(
    table_name: str,
    column_names: set[str],
    order_column: str | None,
) -> sql.Composed:
    if table_name in INSTRUMENT_JOIN_ADMIN_TABLES and "instrument_id" in column_names:
        order_clause = (
            sql.SQL(" ORDER BY t.{} DESC NULLS LAST").format(sql.Identifier(order_column))
            if order_column
            else sql.SQL("")
        )
        return sql.SQL(
            "SELECT i.name_local, i.symbol, t.* FROM {} t "
            "LEFT JOIN instruments i ON i.instrument_id = t.instrument_id{} LIMIT %s"
        ).format(sql.Identifier(table_name), order_clause)
    order_clause = (
        sql.SQL(" ORDER BY {} DESC NULLS LAST").format(sql.Identifier(order_column))
        if order_column
        else sql.SQL("")
    )
    return sql.SQL("SELECT * FROM {}{} LIMIT %s").format(
        sql.Identifier(table_name),
        order_clause,
    )


def _coverage_pct(instrument_count: int | None, target_count: int | None) -> float | None:
    if not instrument_count or not target_count:
        return None
    return instrument_count / target_count * 100.0


def load_admin_price_coverage(conn) -> list[AdminCoverageRow]:
    rows = conn.execute(
        """
        WITH current_members AS (
            SELECT ud.market_key, um.universe_key, um.instrument_id
            FROM universe_memberships um
            JOIN universe_definitions ud ON ud.universe_key = um.universe_key
            WHERE um.effective_to IS NULL
        ),
        targets AS (
            SELECT market_key, universe_key, count(*)::int AS target_count
            FROM current_members
            GROUP BY market_key, universe_key
        ),
        latest AS (
            SELECT cm.market_key, cm.universe_key, dp.source_provider, max(dp.trade_date) AS trade_date
            FROM current_members cm
            JOIN daily_prices dp ON dp.instrument_id = cm.instrument_id
            GROUP BY cm.market_key, cm.universe_key, dp.source_provider
        )
        SELECT
            l.market_key,
            l.universe_key,
            l.source_provider,
            l.trade_date,
            count(*)::int AS row_count,
            count(DISTINCT dp.instrument_id)::int AS instrument_count,
            t.target_count,
            max(dp.collected_at) AS last_updated
        FROM latest l
        JOIN current_members cm
          ON cm.market_key = l.market_key
         AND cm.universe_key = l.universe_key
        JOIN daily_prices dp
          ON dp.instrument_id = cm.instrument_id
         AND dp.trade_date = l.trade_date
         AND dp.source_provider = l.source_provider
        JOIN targets t
          ON t.market_key = l.market_key
         AND t.universe_key = l.universe_key
        GROUP BY l.market_key, l.universe_key, l.source_provider, l.trade_date, t.target_count
        ORDER BY l.market_key, l.universe_key, l.source_provider
        """
    ).fetchall()
    return [
        AdminCoverageRow(
            dataset="daily_prices",
            market_key=row[0],
            universe_key=row[1],
            source_provider=row[2],
            trade_date=row[3],
            row_count=int(row[4] or 0),
            instrument_count=int(row[5] or 0),
            target_count=int(row[6] or 0),
            coverage_pct=_coverage_pct(int(row[5] or 0), int(row[6] or 0)),
            last_updated=row[7],
        )
        for row in rows
    ]


def load_admin_indicator_coverage(conn) -> list[AdminCoverageRow]:
    rows = conn.execute(
        """
        WITH current_members AS (
            SELECT ud.market_key, um.universe_key, um.instrument_id
            FROM universe_memberships um
            JOIN universe_definitions ud ON ud.universe_key = um.universe_key
            WHERE um.effective_to IS NULL
        ),
        targets AS (
            SELECT market_key, universe_key, count(*)::int AS target_count
            FROM current_members
            GROUP BY market_key, universe_key
        ),
        latest AS (
            SELECT cm.market_key, cm.universe_key, di.price_source_provider, max(di.trade_date) AS trade_date
            FROM current_members cm
            JOIN daily_indicators di ON di.instrument_id = cm.instrument_id
            GROUP BY cm.market_key, cm.universe_key, di.price_source_provider
        )
        SELECT
            l.market_key,
            l.universe_key,
            l.price_source_provider,
            l.trade_date,
            count(*)::int AS row_count,
            count(DISTINCT di.instrument_id)::int AS instrument_count,
            t.target_count,
            max(di.calculated_at) AS last_updated
        FROM latest l
        JOIN current_members cm
          ON cm.market_key = l.market_key
         AND cm.universe_key = l.universe_key
        JOIN daily_indicators di
          ON di.instrument_id = cm.instrument_id
         AND di.trade_date = l.trade_date
         AND di.price_source_provider = l.price_source_provider
        JOIN targets t
          ON t.market_key = l.market_key
         AND t.universe_key = l.universe_key
        GROUP BY l.market_key, l.universe_key, l.price_source_provider, l.trade_date, t.target_count
        ORDER BY l.market_key, l.universe_key, l.price_source_provider
        """
    ).fetchall()
    return [
        AdminCoverageRow(
            dataset="daily_indicators",
            market_key=row[0],
            universe_key=row[1],
            source_provider=row[2],
            trade_date=row[3],
            row_count=int(row[4] or 0),
            instrument_count=int(row[5] or 0),
            target_count=int(row[6] or 0),
            coverage_pct=_coverage_pct(int(row[5] or 0), int(row[6] or 0)),
            last_updated=row[7],
        )
        for row in rows
    ]


def load_admin_scan_coverage(conn) -> list[AdminCoverageRow]:
    rows = conn.execute(
        """
        WITH current_targets AS (
            SELECT universe_key, count(*)::int AS target_count
            FROM universe_memberships
            WHERE effective_to IS NULL
            GROUP BY universe_key
        ),
        latest AS (
            SELECT market_key, universe_key, max(trade_date) AS trade_date
            FROM scan_results
            GROUP BY market_key, universe_key
        )
        SELECT
            l.market_key,
            l.universe_key,
            l.trade_date,
            count(*)::int AS row_count,
            count(DISTINCT sr.instrument_id)::int AS instrument_count,
            ct.target_count,
            max(sr.created_at) AS last_updated,
            avg(sr.composite_score)::float AS avg_score
        FROM latest l
        JOIN scan_results sr
          ON sr.market_key = l.market_key
         AND sr.universe_key IS NOT DISTINCT FROM l.universe_key
         AND sr.trade_date = l.trade_date
        LEFT JOIN current_targets ct ON ct.universe_key = l.universe_key
        GROUP BY l.market_key, l.universe_key, l.trade_date, ct.target_count
        ORDER BY l.market_key, l.universe_key
        """
    ).fetchall()
    return [
        AdminCoverageRow(
            dataset="scan_results",
            market_key=row[0],
            universe_key=row[1],
            source_provider=None,
            trade_date=row[2],
            row_count=int(row[3] or 0),
            instrument_count=int(row[4] or 0),
            target_count=int(row[5]) if row[5] is not None else None,
            coverage_pct=_coverage_pct(int(row[4] or 0), int(row[5]) if row[5] is not None else None),
            last_updated=row[6],
            extra_value=_to_float(row[7]),
        )
        for row in rows
    ]


def load_admin_macro_coverage(conn) -> list[AdminCoverageRow]:
    rows = conn.execute(
        """
        WITH latest AS (
            SELECT source_provider, max(trade_date) AS trade_date
            FROM daily_macro
            GROUP BY source_provider
        )
        SELECT
            l.source_provider,
            l.trade_date,
            count(*)::int AS row_count,
            max(dm.collected_at) AS last_updated
        FROM latest l
        JOIN daily_macro dm
          ON dm.source_provider = l.source_provider
         AND dm.trade_date = l.trade_date
        GROUP BY l.source_provider, l.trade_date
        ORDER BY l.source_provider
        """
    ).fetchall()
    return [
        AdminCoverageRow(
            dataset="daily_macro",
            market_key=None,
            universe_key=None,
            source_provider=row[0],
            trade_date=row[1],
            row_count=int(row[2] or 0),
            instrument_count=None,
            target_count=None,
            coverage_pct=None,
            last_updated=row[3],
        )
        for row in rows
    ]


def load_admin_recent_runs(conn, limit: int = 20) -> list[AdminRunRow]:
    rows = conn.execute(
        """
        SELECT
            run_type, market_key, universe_key, trade_date, source_provider, status,
            requested_count, success_count, failed_count, skipped_count,
            started_at, finished_at
        FROM collection_runs
        ORDER BY started_at DESC
        LIMIT %s
        """,
        (limit,),
    ).fetchall()
    return [
        AdminRunRow(
            run_type=row[0],
            market_key=row[1],
            universe_key=row[2],
            trade_date=row[3],
            source_provider=row[4],
            status=row[5],
            requested_count=int(row[6] or 0),
            success_count=int(row[7] or 0),
            failed_count=int(row[8] or 0),
            skipped_count=int(row[9] or 0),
            started_at=row[10],
            finished_at=row[11],
        )
        for row in rows
    ]


def load_admin_page_data(conn, limit: int = 50) -> AdminPageData:
    """PostgreSQL public 스키마의 테이블 메타데이터와 최근 샘플 행을 읽는다."""
    table_rows = conn.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_type = 'BASE TABLE'
        ORDER BY table_name
        """
    ).fetchall()

    tables: list[AdminTable] = []
    for table_row in table_rows:
        table_name = table_row[0]
        column_meta_rows = conn.execute(
            """
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = %s
            ORDER BY ordinal_position
            """,
            (table_name,),
        ).fetchall()
        column_names = {row[0] for row in column_meta_rows}
        order_column = _admin_order_column(column_names)
        hidden_columns = HIDDEN_ADMIN_COLUMNS.get(table_name, set())
        count = int(
            conn.execute(
                sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table_name))
            ).fetchone()[0]
        )

        preview_cursor = conn.execute(_admin_preview_query(table_name, column_names, order_column), (limit,))
        all_preview_columns = [
            description.name if hasattr(description, "name") else description[0]
            for description in preview_cursor.description or []
        ]
        visible_indexes = [
            index
            for index, column in enumerate(all_preview_columns)
            if column not in hidden_columns
        ]
        preview_columns = [all_preview_columns[index] for index in visible_indexes]
        rows = [
            [_admin_cell_value(row[index]) for index in visible_indexes]
            for row in preview_cursor.fetchall()
        ]
        joined_columns = (
            [
                AdminColumn(name="name_local", data_type="text", nullable=True),
                AdminColumn(name="symbol", data_type="text", nullable=True),
            ]
            if table_name in INSTRUMENT_JOIN_ADMIN_TABLES and "instrument_id" in column_names
            else []
        )
        visible_columns = [
            column for column in joined_columns
            if column.name not in hidden_columns
        ] + [
            AdminColumn(name=row[0], data_type=row[1], nullable=row[2] == "YES")
            for row in column_meta_rows
            if row[0] not in hidden_columns
        ]

        tables.append(
            AdminTable(
                name=table_name,
                count=count,
                order_column=order_column,
                columns=visible_columns,
                preview_columns=preview_columns,
                rows=rows,
            )
        )

    return AdminPageData(
        generated_at=datetime.now(),
        preview_limit=limit,
        prices=load_admin_price_coverage(conn),
        indicators=load_admin_indicator_coverage(conn),
        scans=load_admin_scan_coverage(conn),
        macro=load_admin_macro_coverage(conn),
        runs=load_admin_recent_runs(conn),
        tables=tables,
    )


def load_macro_price_series(conn) -> list[MacroPriceSeries]:
    """global-indices / commodities / sector-etfs 의 전체 종가 시계열.

    DB에 있는 가장 이른 날짜부터 최신까지 모두 로드하고 첫 유효 종가를 100으로 정규화해 반환한다.
    """
    from collections import defaultdict

    rows = conn.execute(
        """
        SELECT DISTINCT ON (i.instrument_id, dp.trade_date)
            i.market_key,
            i.symbol,
            COALESCE(i.display_symbol, i.symbol) AS display_symbol,
            i.name_en,
            dp.trade_date,
            dp.close_price
        FROM instruments i
        JOIN daily_prices dp ON dp.instrument_id = i.instrument_id
        WHERE i.market_key IN ('global-indices', 'commodities', 'sector-etfs')
          AND i.is_active = TRUE
        ORDER BY i.instrument_id, dp.trade_date, dp.source_provider
        """,
    ).fetchall()

    grouped: dict[tuple, list[tuple[str, float | None]]] = defaultdict(list)
    for r in rows:
        key = (r[0], r[1], r[2], r[3])
        grouped[key].append((r[4].isoformat(), _to_float(r[5])))

    result: list[MacroPriceSeries] = []
    for (market_key, symbol, display_symbol, name_en), points in grouped.items():
        points.sort(key=lambda x: x[0])
        if not any(v is not None for _, v in points):
            continue
        result.append(MacroPriceSeries(
            market_key=market_key,
            symbol=symbol,
            display_symbol=display_symbol,
            name_en=name_en,
            dates=[d for d, _ in points],
            values=[round(v, 4) if v is not None else None for _, v in points],
        ))
    existing = {(item.market_key, item.display_symbol) for item in result}

    macro_rows = conn.execute(
        """
        SELECT indicator_code, trade_date, value
        FROM daily_macro
        WHERE indicator_code = ANY(%s)
        ORDER BY indicator_code, trade_date
        """,
        (list(MACRO_SERIES_FALLBACKS),),
    ).fetchall()

    macro_grouped: dict[str, list[tuple[str, float | None]]] = defaultdict(list)
    for code, trade_date, value in macro_rows:
        macro_grouped[code].append((trade_date.isoformat(), _to_float(value)))

    for code, points in macro_grouped.items():
        market_key, display_symbol, name_en = MACRO_SERIES_FALLBACKS[code]
        if (market_key, display_symbol) in existing:
            continue
        if not any(v is not None for _, v in points):
            continue
        result.append(MacroPriceSeries(
            market_key=market_key,
            symbol=code,
            display_symbol=display_symbol,
            name_en=name_en,
            dates=[d for d, _ in points],
            values=[round(v, 4) if v is not None else None for _, v in points],
        ))
    return result


def load_fx_strength_series(conn) -> list[MacroPriceSeries]:
    """daily_macro 환율을 통화 강약 시계열로 변환한다.

    값은 원시 환율이 아니라 USD 대비 각 통화의 방향을 맞춘 값이다.
    예: USDKRW, USDJPY처럼 USD가 앞에 있는 페어는 역수로 바꿔
    차트에서 위로 갈수록 KRW/JPY 강세가 되도록 한다.
    """
    from collections import defaultdict

    source_by_code = {code: (display_symbol, name, invert) for code, display_symbol, name, invert in FX_STRENGTH_SOURCES}
    rows = conn.execute(
        """
        SELECT indicator_code, trade_date, value
        FROM daily_macro
        WHERE indicator_code = ANY(%s)
        ORDER BY indicator_code, trade_date
        """,
        (list(source_by_code),),
    ).fetchall()

    grouped: dict[str, list[tuple[str, float | None]]] = defaultdict(list)
    for code, trade_date, value in rows:
        display_symbol, _, invert = source_by_code[code]
        raw_value = _to_float(value)
        strength_value = None
        if raw_value is not None:
            strength_value = (1 / raw_value) if invert and raw_value != 0 else raw_value
        grouped[code].append((trade_date.isoformat(), strength_value))

    result: list[MacroPriceSeries] = []
    for code, points in grouped.items():
        display_symbol, name, _ = source_by_code[code]
        points.sort(key=lambda x: x[0])
        if not any(v is not None for _, v in points):
            continue
        result.append(MacroPriceSeries(
            market_key="fx-strength",
            symbol=code,
            display_symbol=display_symbol,
            name_en=name,
            dates=[d for d, _ in points],
            values=[round(v, 8) if v is not None else None for _, v in points],
        ))
    return result


def load_daily_macro_items(conn) -> list[DailyMacroItem]:
    """daily_macro 테이블에서 각 indicator_code 의 최신 행을 반환."""
    rows = conn.execute(
        """
        SELECT DISTINCT ON (indicator_code)
            indicator_code, trade_date, value, prev_value, change_pct, collected_at
        FROM daily_macro
        ORDER BY indicator_code, trade_date DESC, collected_at DESC
        """
    ).fetchall()
    return [
        DailyMacroItem(
            indicator_code=r[0],
            trade_date=r[1],
            value=float(r[2]),
            prev_value=_to_float(r[3]),
            change_pct=_to_float(r[4]),
            collected_at=r[5],
        )
        for r in rows
    ]


def load_macro_history(conn) -> dict[str, list[float]]:
    """최근 1년 daily_macro 값. 매크로 해석의 위치 판단용."""
    from collections import defaultdict

    rows = conn.execute(
        """
        SELECT indicator_code, value
        FROM daily_macro
        WHERE trade_date >= CURRENT_DATE - INTERVAL '370 days'
        ORDER BY indicator_code, trade_date
        """
    ).fetchall()

    grouped: dict[str, list[float]] = defaultdict(list)
    for code, value in rows:
        value_float = _to_float(value)
        if value_float is not None:
            grouped[code].append(value_float)
    return dict(grouped)


def load_market_cards(conn, market_keys: list[str] | None = None) -> list[MarketCard]:
    """활성 시장의 최신 market_snapshots 카드.

    같은 market에서 universe가 여러 개면 market_key == universe_key 인 행을 우선,
    없으면 trade_date 최신/total_count 최대인 행을 고른다.
    market_keys 가 주어지면 해당 시장만 반환한다.
    """
    mk_filter = "AND ms.market_key = ANY(%s)" if market_keys is not None else ""
    mk_params = (market_keys,) if market_keys is not None else ()
    rows = conn.execute(
        f"""
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
            WHERE m.is_active = TRUE {mk_filter}
        )
        SELECT
            market_key, market_label, trade_date, universe_key,
            total_count, advance_count, decline_count, unchanged_count,
            avg_change_pct, avg_rsi14, market_score,
            regime, risk_level, bullish_breadth_pct
        FROM latest
        WHERE rn = 1
        ORDER BY market_key
        """,
        mk_params,
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


def load_top_stocks(
    conn, limit: int = 30, market_keys: list[str] | None = None
) -> list[TopStock]:
    """시장 통합 composite_score 상위 N. 가장 최신 trade_date 기준.

    market_keys 가 주어지면 해당 시장만 대상으로 한다.
    """
    mk_filter = "AND sr.market_key = ANY(%s)" if market_keys is not None else ""
    params = (*((market_keys,) if market_keys is not None else ()), limit)
    rows = conn.execute(
        f"""
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
            WHERE TRUE {mk_filter}
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
        params,
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


def load_sector_cells(
    conn,
    per_market_top: int = 10,
    market_keys: list[str] | None = None,
    universe_keys: list[str] | None = None,
) -> list[SectorCell]:
    """시장별 sector_snapshots 상위 N (instrument_count 기준).

    market_keys 가 주어지면 해당 시장만 반환한다.
    universe_keys 가 주어지면 해당 유니버스 스냅샷만 포함한다 (미제공 시 universe_key = market_key 필터).
    """
    mk_filter = "AND ss.market_key = ANY(%s)" if market_keys is not None else ""
    uk_filter = "AND ss.universe_key = ANY(%s)" if universe_keys is not None else "AND ss.universe_key = ss.market_key"
    args: list = []
    if market_keys is not None:
        args.append(market_keys)
    if universe_keys is not None:
        args.append(universe_keys)
    args.append(per_market_top)
    rows = conn.execute(
        f"""
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
            WHERE m.is_active = TRUE {mk_filter}
              AND (ss.market_key, ss.trade_date) IN (
                  SELECT market_key, MAX(trade_date)
                  FROM sector_snapshots
                  GROUP BY market_key
              )
              {uk_filter}
              AND ss.sector IS NOT NULL
              AND ss.sector <> ''
        )
        SELECT market_key, sector, instrument_count, avg_change_pct, avg_composite_score
        FROM ranked
        WHERE rn <= %s
        ORDER BY market_key, rn
        """,
        tuple(args),
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
    """global-indices, sector-etfs, commodities 의 최신 daily_prices.

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
            WHERE i.market_key IN ('global-indices', 'sector-etfs', 'commodities')
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
                ) AS prev_close,
                (
                    SELECT collected_at FROM daily_prices
                    WHERE instrument_id = l.instrument_id AND trade_date = l.trade_date
                    ORDER BY source_provider LIMIT 1
                ) AS collected_at
            FROM latest l
        )
        SELECT
            market_key, symbol, display_symbol, name_local, close_price,
            CASE
                WHEN prev_close IS NULL OR prev_close = 0 THEN NULL
                ELSE (close_price - prev_close) / prev_close * 100.0
            END AS change_pct,
            trade_date,
            collected_at
        FROM with_close
        WHERE close_price IS NOT NULL
        ORDER BY market_key, symbol
        """
    ).fetchall()

    result = [
        MacroQuote(
            market_key=r[0],
            symbol=r[1],
            display_symbol=r[2],
            name_local=r[3],
            close_price=_to_float(r[4]),
            change_pct=_to_float(r[5]),
            trade_date=r[6],
            collected_at=r[7],
        )
        for r in rows
    ]
    existing = {(item.market_key, item.display_symbol) for item in result}

    macro_rows = conn.execute(
        """
        SELECT DISTINCT ON (indicator_code)
            indicator_code, trade_date, value, change_pct, collected_at
        FROM daily_macro
        WHERE indicator_code = ANY(%s)
        ORDER BY indicator_code, trade_date DESC, collected_at DESC
        """,
        (list(MACRO_SERIES_FALLBACKS),),
    ).fetchall()
    for code, trade_date, value, change_pct, collected_at in macro_rows:
        market_key, display_symbol, name_local = MACRO_SERIES_FALLBACKS[code]
        if (market_key, display_symbol) in existing:
            continue
        result.append(MacroQuote(
            market_key=market_key,
            symbol=code,
            display_symbol=display_symbol,
            name_local=name_local,
            close_price=_to_float(value),
            change_pct=_to_float(change_pct),
            trade_date=trade_date,
            collected_at=collected_at,
        ))
    return result


def load_watchlist_stocks(
    conn, per_panel: int = 5, market_keys: list[str] | None = None
) -> list[WatchlistStock]:
    """6개 워치리스트 패널용 종목을 한 번에 로드.

    market_keys 가 주어지면 해당 시장만 대상으로 한다.
    """
    mk_filter = "AND sr.market_key = ANY(%s)" if market_keys is not None else ""
    mk_params = (market_keys,) if market_keys is not None else ()
    rows = conn.execute(
        f"""
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
        WHERE m.is_active = TRUE {mk_filter}
        ORDER BY sr.instrument_id, sr.created_at DESC
        """,
        mk_params,
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


def load_main_page_data(conn) -> MainPageData:
    """메인 페이지 데이터 로드. 매크로 지표와 글로벌 틱커만 포함."""
    macro_quotes = load_macro_quotes(conn)
    daily_macro_items = load_daily_macro_items(conn)
    macro_price_series = load_macro_price_series(conn)
    fx_strength_series = load_fx_strength_series(conn)
    generated_at = max(
        (q.trade_date for q in macro_quotes),
        default=date.today(),
    )
    return MainPageData(
        generated_at=generated_at,
        macro_quotes=macro_quotes,
        daily_macro_items=daily_macro_items,
        macro_price_series=macro_price_series,
        fx_strength_series=fx_strength_series,
    )


def load_overview_data(
    conn,
    market_keys: list[str],
    label: str,
    nav_key: str,
    *,
    top_n: int = 30,
    sector_per_market: int = 10,
    sector_universe_keys: list[str] | None = None,
) -> OverviewPageData:
    """US종합·KR종합 등 시장 묶음 개요 페이지 데이터."""
    cards = load_market_cards(conn, market_keys=market_keys)
    generated_at = max((c.trade_date for c in cards), default=date.today())
    return OverviewPageData(
        nav_key=nav_key,
        label=label,
        generated_at=generated_at,
        market_cards=cards,
        top_stocks=load_top_stocks(conn, top_n, market_keys=market_keys),
        sector_cells=load_sector_cells(conn, sector_per_market, market_keys=market_keys, universe_keys=sector_universe_keys),
        watchlist_stocks=load_watchlist_stocks(conn, market_keys=market_keys),
    )


def load_us_all_data(conn) -> OverviewPageData:
    """US종합 페이지 데이터 (us 시장)."""
    page = load_overview_data(conn, ["us"], "US종합", "us-all")
    page.daily_macro_items = load_daily_macro_items(conn)
    page.macro_history = load_macro_history(conn)
    page.sector_etf_quotes = [
        q for q in load_macro_quotes(conn)
        if q.market_key == "sector-etfs"
    ]
    page.sector_etf_price_series = [
        s for s in load_macro_price_series(conn)
        if s.market_key == "sector-etfs"
    ]
    if page.sector_etf_quotes:
        page.generated_at = max(page.generated_at, max(q.trade_date for q in page.sector_etf_quotes))
    return page


def load_kr_all_data(conn) -> OverviewPageData:
    """KR종합 페이지 데이터 (kr 시장, kospi + kosdaq 유니버스)."""
    return load_overview_data(
        conn, ["kr"], "KR종합", "kr-all",
        sector_universe_keys=["kospi", "kosdaq"],
    )


def load_market_summary(
    conn,
    market_key: str,
    universe_key: str | None = None,
    label: str | None = None,
) -> MarketCard | None:
    """단일 시장의 최신 market_snapshots → MarketCard. 없으면 None."""
    effective_universe = universe_key or market_key
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
          AND ms.universe_key = %s
        ORDER BY
            ms.trade_date DESC,
            ms.total_count DESC
        LIMIT 1
        """,
        (market_key, effective_universe),
    ).fetchone()
    if not row:
        return None
    return MarketCard(
        market_key=row[0],
        label=label or row[1],
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


def load_market_sectors(conn, market_key: str, universe_key: str | None = None) -> list[SectorCell]:
    """해당 시장의 최신 sector_snapshots 전부."""
    effective_universe = universe_key or market_key
    rows = conn.execute(
        """
        SELECT sector, instrument_count, avg_change_pct, avg_composite_score
        FROM sector_snapshots
        WHERE market_key = %s
          AND universe_key = %s
          AND trade_date = (
              SELECT MAX(trade_date) FROM sector_snapshots
              WHERE market_key = %s AND universe_key = %s
          )
          AND sector IS NOT NULL
          AND sector <> ''
        ORDER BY instrument_count DESC
        """,
        (market_key, effective_universe, market_key, effective_universe),
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


def load_market_top_stocks(
    conn,
    market_key: str,
    limit: int = 50,
    universe_key: str | None = None,
    label: str | None = None,
) -> list[TopStock]:
    """해당 시장의 composite_score 상위 N."""
    effective_universe = universe_key or market_key
    rows = conn.execute(
        """
        WITH latest AS (
            SELECT MAX(trade_date) AS trade_date
            FROM scan_results
            WHERE market_key = %s AND universe_key = %s
        ),
        dedup AS (
            SELECT DISTINCT ON (sr.instrument_id, sr.trade_date)
                sr.instrument_id, sr.rank_no, sr.composite_score, sr.change_pct,
                sr.close_price, sr.rsi14, sr.setup_label
            FROM scan_results sr, latest l
            WHERE sr.market_key = %s
              AND sr.universe_key = %s
              AND sr.trade_date = l.trade_date
            ORDER BY sr.instrument_id, sr.trade_date, sr.created_at DESC
        )
        SELECT
            %s::TEXT,
            %s::TEXT,
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
        WHERE d.composite_score IS NOT NULL
        ORDER BY d.composite_score DESC
        LIMIT %s
        """,
        (market_key, effective_universe, market_key, effective_universe, market_key, label or market_key, limit),
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
    conn,
    market_key: str,
    score_column: str,
    limit: int = 5,
    universe_key: str | None = None,
    label: str | None = None,
) -> list[TopStock]:
    """전략 점수 컬럼 상위 N. score_column 은 STRATEGY_KEYS 중 하나여야 한다."""
    valid = {key for key, _ in STRATEGY_KEYS}
    if score_column not in valid:
        raise ValueError(f"Unknown strategy score column: {score_column}")
    effective_universe = universe_key or market_key

    # f-string 으로 컬럼명 삽입 — 화이트리스트 검증 후라 안전.
    sql = f"""
        WITH latest AS (
            SELECT MAX(trade_date) AS trade_date
            FROM scan_results
            WHERE market_key = %s AND universe_key = %s
        ),
        dedup AS (
            SELECT DISTINCT ON (sr.instrument_id, sr.trade_date)
                sr.instrument_id, sr.rank_no, sr.composite_score, sr.change_pct,
                sr.close_price, sr.rsi14, sr.setup_label, sr.{score_column} AS score
            FROM scan_results sr, latest l
            WHERE sr.market_key = %s
              AND sr.universe_key = %s
              AND sr.trade_date = l.trade_date
            ORDER BY sr.instrument_id, sr.trade_date, sr.created_at DESC
        )
        SELECT
            %s::TEXT, %s::TEXT, d.rank_no, i.symbol,
            COALESCE(i.display_symbol, i.symbol),
            i.name_local, i.sector,
            d.score AS strategy_score,
            d.change_pct, d.close_price, d.rsi14, d.setup_label
        FROM dedup d
        JOIN instruments i ON i.instrument_id = d.instrument_id
        WHERE d.score IS NOT NULL
        ORDER BY d.score DESC
        LIMIT %s
    """
    rows = conn.execute(
        sql,
        (market_key, effective_universe, market_key, effective_universe, market_key, label or market_key, limit),
    ).fetchall()
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


def load_ma_near_counts(
    conn,
    market_key: str,
    threshold_pct: float = 5.0,
    universe_key: str | None = None,
) -> dict[str, int]:
    """MA 근접 종목 수 (60/120/240일, ±threshold_pct% 이내)."""
    effective_universe = universe_key or market_key
    row = conn.execute(
        """
        WITH latest AS (
            SELECT MAX(trade_date) AS trade_date
            FROM scan_results
            WHERE market_key = %s AND universe_key = %s
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
          AND sr.universe_key = %s
          AND sr.trade_date = (SELECT trade_date FROM latest)
        """,
        (
            market_key,
            effective_universe,
            threshold_pct,
            threshold_pct,
            threshold_pct,
            market_key,
            effective_universe,
        ),
    ).fetchone()
    if not row:
        return {"60": 0, "120": 0, "240": 0}
    return {"60": row[0] or 0, "120": row[1] or 0, "240": row[2] or 0}


def load_market_detail_data(
    conn,
    market_key: str,
    *,
    universe_key: str | None = None,
    label: str | None = None,
    nav_key: str | None = None,
    top_n: int = 50,
    strategy_n: int = 5,
) -> MarketDetailData:
    """시장 서브페이지에 필요한 데이터 한 번에 로드."""
    effective_universe = universe_key or market_key
    display_label = label or UNIVERSE_DETAIL_PAGES.get(effective_universe, ("", effective_universe))[1]
    summary = load_market_summary(conn, market_key, effective_universe, display_label)
    display_label = summary.label if summary else display_label
    return MarketDetailData(
        market_key=market_key,
        nav_key=nav_key or effective_universe,
        label=display_label,
        summary=summary,
        sectors=load_market_sectors(conn, market_key, effective_universe),
        top_stocks=load_market_top_stocks(conn, market_key, top_n, effective_universe, display_label),
        strategy_top={
            col: load_market_strategy_top(conn, market_key, col, strategy_n, effective_universe, display_label)
            for col, _ in STRATEGY_KEYS
        },
        ma_near_counts=load_ma_near_counts(conn, market_key, universe_key=effective_universe),
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
