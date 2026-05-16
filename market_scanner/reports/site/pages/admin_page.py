"""관리 페이지 (site/admin/index.html)."""
from __future__ import annotations

from html import escape

from market_scanner.reports.site import layout
from market_scanner.reports.site.data import AdminCoverageRow, AdminPageData, AdminRunRow, AdminTable


def _date_text(value: object) -> str:
    return "—" if value is None else str(value)[:10]


def _datetime_text(value: object) -> str:
    if value is None:
        return "—"
    return str(value).replace("T", " ")[:19]


def _pct_text(value: float | None) -> str:
    return "—" if value is None else f"{value:.1f}%"


def _coverage_class(value: float | None) -> str:
    if value is None:
        return "flat"
    if value >= 95:
        return "up"
    if value >= 80:
        return "warn"
    return "down"


def _latest_date(rows: list[AdminCoverageRow]) -> str:
    dates = [row.trade_date for row in rows if row.trade_date is not None]
    return _date_text(max(dates)) if dates else "—"


def _status_class(status: str) -> str:
    if status == "success":
        return "up"
    if status == "partial":
        return "warn"
    if status in {"failed", "cancelled"}:
        return "down"
    return "flat"


def _summary_section(data: AdminPageData) -> str:
    failed_runs = sum(1 for row in data.runs if row.status in {"failed", "partial", "cancelled"})
    return f"""
<section class="block">
  <h2>데이터 운영 상태</h2>
  <div class="sub">최신 거래일 기준 적재/계산/스크리닝 커버리지입니다. 원본 테이블 브라우저는 아래에 유지합니다.</div>
  <div class="admin-stats">
    <div class="admin-stat"><span>가격 최신일</span><strong>{escape(_latest_date(data.prices))}</strong><em>{len(data.prices):,} universe/source</em></div>
    <div class="admin-stat"><span>지표 최신일</span><strong>{escape(_latest_date(data.indicators))}</strong><em>{len(data.indicators):,} universe/source</em></div>
    <div class="admin-stat"><span>스크리닝 최신일</span><strong>{escape(_latest_date(data.scans))}</strong><em>{len(data.scans):,} market/universe</em></div>
    <div class="admin-stat"><span>최근 실행 이상</span><strong>{failed_runs:,}</strong><em>최근 {len(data.runs):,}개 run 기준</em></div>
  </div>
</section>"""


def _coverage_table(rows: list[AdminCoverageRow], *, title: str, extra_label: str | None = None) -> str:
    if not rows:
        return ""
    extra_head = f"<th>{escape(extra_label)}</th>" if extra_label else ""
    body_rows = []
    for row in rows:
        coverage_class = _coverage_class(row.coverage_pct)
        extra_cell = f"<td>{layout.fmt_num(row.extra_value, 1)}</td>" if extra_label else ""
        instrument_text = f"{row.instrument_count:,}" if row.instrument_count is not None else "—"
        target_text = f"{row.target_count:,}" if row.target_count is not None else "—"
        body_rows.append(
            "<tr>"
            f'<td class="l">{escape(row.market_key or "—")}</td>'
            f'<td class="l">{escape(row.universe_key or "—")}</td>'
            f'<td class="l">{escape(row.source_provider or "—")}</td>'
            f"<td>{escape(_date_text(row.trade_date))}</td>"
            f"<td>{row.row_count:,}</td>"
            f"<td>{instrument_text}</td>"
            f"<td>{target_text}</td>"
            f'<td class="{coverage_class}">{escape(_pct_text(row.coverage_pct))}</td>'
            f"{extra_cell}"
            f"<td>{escape(_datetime_text(row.last_updated))}</td>"
            "</tr>"
        )
    return f"""
<section class="admin-panel">
  <h3>{escape(title)}</h3>
  <div class="admin-table-wrap compact">
    <table class="admin-preview">
      <thead><tr><th class="l">market</th><th class="l">universe</th><th class="l">source</th><th>latest date</th><th>rows</th><th>symbols</th><th>target</th><th>coverage</th>{extra_head}<th>updated</th></tr></thead>
      <tbody>{''.join(body_rows)}</tbody>
    </table>
  </div>
</section>"""


def _macro_table(rows: list[AdminCoverageRow]) -> str:
    if not rows:
        return ""
    body = "".join(
        "<tr>"
        f'<td class="l">{escape(row.source_provider or "—")}</td>'
        f"<td>{escape(_date_text(row.trade_date))}</td>"
        f"<td>{row.row_count:,}</td>"
        f"<td>{escape(_datetime_text(row.last_updated))}</td>"
        "</tr>"
        for row in rows
    )
    return f"""
<section class="admin-panel">
  <h3>매크로 최신 데이터</h3>
  <div class="admin-table-wrap compact">
    <table class="admin-preview">
      <thead><tr><th class="l">source</th><th>latest date</th><th>rows</th><th>updated</th></tr></thead>
      <tbody>{body}</tbody>
    </table>
  </div>
</section>"""


def _runs_table(rows: list[AdminRunRow]) -> str:
    if not rows:
        return ""
    body = "".join(
        "<tr>"
        f'<td class="l">{escape(row.run_type)}</td>'
        f'<td class="l">{escape(row.market_key or "—")}</td>'
        f'<td class="l">{escape(row.universe_key or "—")}</td>'
        f"<td>{escape(_date_text(row.trade_date))}</td>"
        f'<td class="{_status_class(row.status)}">{escape(row.status)}</td>'
        f"<td>{row.requested_count:,}</td><td>{row.success_count:,}</td><td>{row.failed_count:,}</td><td>{row.skipped_count:,}</td>"
        f"<td>{escape(_datetime_text(row.started_at))}</td>"
        "</tr>"
        for row in rows
    )
    return f"""
<section class="admin-panel">
  <h3>최근 실행 상태</h3>
  <div class="admin-table-wrap compact">
    <table class="admin-preview">
      <thead><tr><th class="l">type</th><th class="l">market</th><th class="l">universe</th><th>date</th><th>status</th><th>req</th><th>ok</th><th>fail</th><th>skip</th><th>started</th></tr></thead>
      <tbody>{body}</tbody>
    </table>
  </div>
</section>"""


def _ops_section(data: AdminPageData) -> str:
    return (
        '<section class="admin-ops">'
        + _coverage_table(data.prices, title="가격 적재 커버리지")
        + _coverage_table(data.indicators, title="지표 계산 커버리지")
        + _coverage_table(data.scans, title="스크리닝 결과 커버리지", extra_label="avg score")
        + _macro_table(data.macro)
        + _runs_table(data.runs)
        + "</section>"
    )


def _table_nav(data: AdminPageData) -> str:
    if not data.tables:
        return ""
    links = "\n".join(
        f'<a href="#table-{index}"><span>{escape(table.name)}</span><em>{table.count:,}</em></a>'
        for index, table in enumerate(data.tables)
    )
    return f"""
<aside class="admin-nav">
  <div class="admin-nav-title">Tables</div>
  {links}
</aside>"""


def _columns_html(table: AdminTable) -> str:
    if not table.columns:
        return '<div class="admin-empty">컬럼이 없습니다.</div>'
    return "\n".join(
        f'<span class="admin-col">{escape(column.name)} <em>{escape(column.data_type)}</em></span>'
        for column in table.columns
    )


def _preview_table(table: AdminTable) -> str:
    if not table.preview_columns:
        return '<div class="admin-empty">표시할 컬럼이 없습니다.</div>'

    header = "".join(f"<th>{escape(column)}</th>" for column in table.preview_columns)
    if not table.rows:
        body = f'<tr><td colspan="{len(table.preview_columns)}" class="admin-empty-cell">표시할 데이터가 없습니다.</td></tr>'
    else:
        rows = []
        for row in table.rows:
            cells = "".join(
                f'<td title="{escape("" if value is None else str(value))}">{escape("" if value is None else str(value))}</td>'
                for value in row
            )
            rows.append(f"<tr>{cells}</tr>")
        body = "".join(rows)

    return f"""
<div class="admin-table-wrap">
  <table class="admin-preview">
    <thead><tr>{header}</tr></thead>
    <tbody>{body}</tbody>
  </table>
</div>"""


def _table_section(table: AdminTable, index: int) -> str:
    order_text = (
        f"최근 {table.order_column} 내림차순 기준"
        if table.order_column
        else "기본 조회 순서 기준"
    )
    return f"""
<details class="admin-table-card" id="table-{index}" {"open" if index == 0 else ""}>
  <summary>
    <span>{escape(table.name)}</span>
    <em>{table.count:,} rows · {escape(order_text)}</em>
  </summary>
  <div class="admin-columns">{_columns_html(table)}</div>
  {_preview_table(table)}
</details>"""


def _tables_section(data: AdminPageData) -> str:
    if not data.tables:
        return '<section class="block"><div class="admin-empty">DB 테이블이 없습니다.</div></section>'
    cards = "\n".join(_table_section(table, index) for index, table in enumerate(data.tables))
    return f"""
<section class="block raw-browser-title">
  <h2>원본 테이블 브라우저</h2>
  <div class="sub">테이블별 컬럼과 최근 샘플 행입니다. 운영 상태를 더 파고들 때 확인합니다.</div>
</section>
<section class="admin-layout">
  {_table_nav(data)}
  <div class="admin-tables">{cards}</div>
</section>"""


def render(data: AdminPageData) -> str:
    styles = """
<style>
main { max-width: 1760px; }
.admin-stats { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }
.admin-stat { background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 14px; }
.admin-stat span { display: block; color: var(--muted); font-size: 11px; margin-bottom: 6px; }
.admin-stat strong { display: block; font-size: 22px; font-variant-numeric: tabular-nums; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.admin-stat em { display: block; color: var(--muted); font-size: 11px; font-style: normal; margin-top: 4px; }
.admin-ops { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; margin-bottom: 30px; }
.admin-panel { min-width: 0; background: var(--panel); border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
.admin-panel h3 { margin: 0; padding: 12px 14px; font-size: 14px; border-bottom: 1px solid var(--border); }
.admin-table-wrap.compact { max-height: 360px; }
.admin-layout { display: grid; grid-template-columns: 260px minmax(0, 1fr); gap: 14px; align-items: start; }
.admin-nav { position: sticky; top: 14px; display: grid; gap: 6px; max-height: calc(100vh - 36px); overflow: auto; background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 10px; }
.admin-nav-title { color: var(--muted); font-size: 11px; padding: 2px 4px 6px; }
.admin-nav a { display: flex; justify-content: space-between; gap: 12px; padding: 7px 8px; border-radius: 6px; color: var(--text); text-decoration: none; font-size: 12px; }
.admin-nav a:hover { background: var(--panel-2); text-decoration: none; }
.admin-nav a span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.admin-nav a em { color: var(--muted); font-style: normal; font-variant-numeric: tabular-nums; }
.admin-tables { display: grid; gap: 12px; min-width: 0; }
.admin-table-card { background: var(--panel); border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
.admin-table-card summary { cursor: pointer; display: flex; justify-content: space-between; gap: 12px; padding: 13px 15px; list-style: none; }
.admin-table-card summary::-webkit-details-marker { display: none; }
.admin-table-card summary span { font-weight: 600; }
.admin-table-card summary em { color: var(--muted); font-size: 12px; font-style: normal; }
.admin-columns { display: flex; flex-wrap: wrap; gap: 6px; padding: 0 15px 13px; border-bottom: 1px solid var(--border); }
.admin-col { border: 1px solid var(--border); border-radius: 999px; padding: 4px 8px; color: #cbd5e1; font-size: 11px; }
.admin-col em { color: var(--muted); font-style: normal; }
.admin-table-wrap { overflow: auto; max-height: 520px; }
table.admin-preview { width: 100%; min-width: 860px; border-collapse: collapse; font-size: 12px; }
table.admin-preview th, table.admin-preview td { padding: 7px 9px; border-bottom: 1px solid var(--border); text-align: left; white-space: nowrap; }
table.admin-preview th { position: sticky; top: 0; background: var(--panel-2); color: var(--muted); z-index: 1; }
table.admin-preview td { max-width: 340px; overflow: hidden; text-overflow: ellipsis; color: #dbe7f5; }
table.admin-preview tr:hover td { background: var(--panel-2); }
.warn { color: #f7b267 !important; }
.admin-empty, .admin-empty-cell { color: var(--muted); padding: 20px; }
@media (max-width: 900px) {
  .admin-stats, .admin-ops, .admin-layout { grid-template-columns: 1fr; }
  .admin-nav { position: static; max-height: none; }
}
</style>"""
    body = styles + _summary_section(data) + _ops_section(data) + _tables_section(data)
    return layout.render_page(
        title="관리",
        depth=1,
        body_html=body,
        nav_active="admin",
        generated_at=data.generated_at,
    )
