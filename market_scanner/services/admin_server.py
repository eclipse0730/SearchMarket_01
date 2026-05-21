from __future__ import annotations

import errno
import html
import json
import os
import subprocess
import sys
import threading
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from market_scanner.storage.connection import connect


ALLOWED_MARKETS = {"us", "kr"}
ALLOWED_FLOW_MARKETS = {"kr", "kospi", "kosdaq"}
ALLOWED_ACTIONS = {"refresh", "price", "indicators", "screen", "flows", "retry-price"}
REPO_ROOT = Path(__file__).parents[2]


@dataclass
class Job:
    job_id: str
    command: list[str]
    metadata: dict[str, str] = field(default_factory=dict)
    status: str = "running"
    output: str = ""
    exit_code: int | None = None
    started_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    finished_at: datetime | None = None


@dataclass
class AdminState:
    database_url: str | None = None
    jobs: dict[str, Job] = field(default_factory=dict)


def _fmt_yyyymmdd(value: date) -> str:
    return value.strftime("%Y%m%d")


def _parse_json(value: Any) -> Any:
    if value is None:
        return {}
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return {}


def _recent_dates(conn, days: int = 7) -> list[date]:
    row = conn.execute(
        """
        SELECT MAX(d) FROM (
            SELECT MAX(trade_date) AS d FROM daily_prices
            UNION ALL SELECT MAX(trade_date) FROM daily_indicators
            UNION ALL SELECT MAX(trade_date) FROM scan_results
            UNION ALL SELECT MAX(trade_date) FROM daily_investor_flows
            UNION ALL SELECT MAX(trade_date) FROM collection_runs
        ) x
        """
    ).fetchone()
    anchor = row[0] if row and row[0] else date.today()
    return [anchor - timedelta(days=i) for i in range(days)]


def _count_map(conn, table: str, dates: list[date]) -> dict[tuple[date, str], int]:
    if table == "daily_prices":
        sql = """
            SELECT dp.trade_date, i.market_key, COUNT(*)
            FROM daily_prices dp
            JOIN instruments i ON i.instrument_id = dp.instrument_id
            WHERE dp.trade_date = ANY(%s)
            GROUP BY dp.trade_date, i.market_key
        """
    elif table == "daily_indicators":
        sql = """
            SELECT di.trade_date, i.market_key, COUNT(*)
            FROM daily_indicators di
            JOIN instruments i ON i.instrument_id = di.instrument_id
            WHERE di.trade_date = ANY(%s)
            GROUP BY di.trade_date, i.market_key
        """
    elif table == "scan_results":
        sql = """
            SELECT trade_date, market_key, COUNT(*)
            FROM scan_results
            WHERE trade_date = ANY(%s)
            GROUP BY trade_date, market_key
        """
    elif table == "daily_investor_flows":
        sql = """
            SELECT f.trade_date, i.market_key, COUNT(*)
            FROM daily_investor_flows f
            JOIN instruments i ON i.instrument_id = f.instrument_id
            WHERE f.trade_date = ANY(%s)
            GROUP BY f.trade_date, i.market_key
        """
    else:
        raise ValueError(f"Unsupported table: {table}")
    return {(row[0], row[1]): int(row[2] or 0) for row in conn.execute(sql, (dates,)).fetchall()}


def _latest_refresh_runs(conn) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT run_id, market_key, universe_key, trade_date, status,
               started_at, finished_at, params
        FROM collection_runs
        WHERE run_type = 'universe'
        ORDER BY started_at DESC
        LIMIT 20
        """
    ).fetchall()
    result = []
    for row in rows:
        params = _parse_json(row[7])
        comparison = params.get("comparison") if isinstance(params, dict) else {}
        samples = params.get("samples") if isinstance(params, dict) else {}
        result.append(
            {
                "run_id": str(row[0]),
                "market_key": row[1],
                "universe_key": row[2],
                "trade_date": row[3],
                "status": row[4],
                "started_at": row[5],
                "finished_at": row[6],
                "comparison": comparison or {},
                "samples": samples or {},
            }
        )
    return result


def _latest_runs(conn) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT run_id, run_type, market_key, universe_key, trade_date, source_provider,
               status, requested_count, success_count, failed_count, skipped_count,
               started_at, finished_at, params, error_samples, notes
        FROM collection_runs
        ORDER BY started_at DESC
        LIMIT 10
        """
    ).fetchall()
    result = []
    for row in rows:
        samples = _parse_json(row[14])
        result.append(
            {
                "run_id": str(row[0]),
                "run_type": row[1],
                "market_key": row[2],
                "universe_key": row[3],
                "trade_date": row[4],
                "source_provider": row[5],
                "status": row[6],
                "requested_count": int(row[7] or 0),
                "success_count": int(row[8] or 0),
                "failed_count": int(row[9] or 0),
                "skipped_count": int(row[10] or 0),
                "started_at": row[11],
                "finished_at": row[12],
                "params": _parse_json(row[13]),
                "error_samples": samples if isinstance(samples, list) else [],
                "notes": row[15],
            }
        )
    return result


def _symbol_from_sample(value: Any) -> str | None:
    if isinstance(value, dict):
        value = value.get("symbol") or value.get("ticker")
    if not value:
        return None
    return str(value).strip() or None


def _collect_sample_symbols(values: Any, symbols: set[str]) -> None:
    if isinstance(values, dict):
        symbol = _symbol_from_sample(values)
        if symbol:
            symbols.add(symbol)
        for value in values.values():
            if isinstance(value, (dict, list)):
                _collect_sample_symbols(value, symbols)
    elif isinstance(values, list):
        for item in values:
            symbol = _symbol_from_sample(item)
            if symbol:
                symbols.add(symbol)
            elif isinstance(item, (dict, list)):
                _collect_sample_symbols(item, symbols)
    else:
        symbol = _symbol_from_sample(values)
        if symbol:
            symbols.add(symbol)


def _instrument_names(conn, refresh_runs: list[dict[str, Any]], runs: list[dict[str, Any]]) -> dict[str, str]:
    symbols: set[str] = set()
    for run in refresh_runs:
        _collect_sample_symbols(run.get("samples"), symbols)
    for run in runs:
        _collect_sample_symbols(run.get("error_samples"), symbols)
    if not symbols:
        return {}
    rows = conn.execute(
        """
        SELECT symbol, COALESCE(NULLIF(name_local, ''), NULLIF(name_en, ''), NULLIF(display_symbol, ''), symbol)
        FROM instruments
        WHERE symbol = ANY(%s)
        """,
        (sorted(symbols),),
    ).fetchall()
    return {str(row[0]): str(row[1]) for row in rows}


def _workflow_files() -> list[dict[str, Any]]:
    workflow_dir = REPO_ROOT / ".github" / "workflows"
    if not workflow_dir.exists():
        return []
    result = []
    for path in sorted(workflow_dir.glob("*.yml")):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        name = ""
        triggers: list[str] = []
        for line in lines:
            stripped = line.strip()
            if not name and stripped.startswith("name:"):
                name = stripped.split(":", 1)[1].strip().strip("\"'")
            if stripped in {"workflow_dispatch:", "schedule:", "push:", "pull_request:"}:
                triggers.append(stripped.rstrip(":"))
            elif "cron:" in stripped:
                triggers.append(stripped)
        result.append(
            {
                "path": str(path.relative_to(REPO_ROOT)),
                "name": name or path.stem,
                "triggers": ", ".join(triggers[:6]) or "-",
                "modified": path.stat().st_mtime,
            }
        )
    return result


def _load_dashboard(database_url: str | None) -> dict[str, Any]:
    with connect(database_url) as conn:
        dates = _recent_dates(conn)
        refresh_runs = _latest_refresh_runs(conn)
        runs = _latest_runs(conn)
        return {
            "dates": dates,
            "prices": _count_map(conn, "daily_prices", dates),
            "indicators": _count_map(conn, "daily_indicators", dates),
            "scan_results": _count_map(conn, "scan_results", dates),
            "flows": _count_map(conn, "daily_investor_flows", dates),
            "refresh_runs": refresh_runs,
            "runs": runs,
            "instrument_names": _instrument_names(conn, refresh_runs, runs),
            "workflows": _workflow_files(),
        }


def _button(action: str, label: str, **values: str) -> str:
    inputs = [f'<input type="hidden" name="action" value="{html.escape(action)}">']
    data_attrs = [f'data-action="{html.escape(action)}"']
    for key, value in values.items():
        inputs.append(f'<input type="hidden" name="{html.escape(key)}" value="{html.escape(value)}">')
        data_attrs.append(f'data-{html.escape(key)}="{html.escape(value)}"')
    return (
        f'<form method="post" action="/run" class="inline-form" {" ".join(data_attrs)}>'
        + "".join(inputs)
        + f'<button type="submit">{html.escape(label)}</button><span class="mini-progress" aria-hidden="true"></span></form>'
    )


def _coverage_section(title: str, action: str, dates: list[date], counts: dict[tuple[date, str], int]) -> str:
    rows = []
    for d in dates:
        date_text = _fmt_yyyymmdd(d)
        us_count = counts.get((d, "us"), 0)
        kr_count = counts.get((d, "kr"), 0)
        rows.append(
            "<tr>"
            f"<td>{date_text}</td>"
            f"<td>{us_count:,}</td>"
            f"<td>{_button(action, 'US 수집', market='us', date=date_text)}</td>"
            f"<td>{kr_count:,}</td>"
            f"<td>{_button(action, 'KR 수집', market='kr', date=date_text)}</td>"
            "</tr>"
        )
    return (
        f"<section><h2>{html.escape(title)}</h2>"
        "<table><thead><tr><th>date</th><th>US</th><th></th><th>KR</th><th></th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></section>"
    )


def _kr_coverage_section(title: str, action: str, dates: list[date], counts: dict[tuple[date, str], int]) -> str:
    rows = []
    for d in dates:
        date_text = _fmt_yyyymmdd(d)
        kr_count = counts.get((d, "kr"), 0)
        rows.append(
            "<tr>"
            f"<td>{date_text}</td>"
            f"<td>{kr_count:,}</td>"
            f"<td>{_button(action, 'KR 수집', market='kr', date=date_text)}</td>"
            "</tr>"
        )
    return (
        f"<section><h2>{html.escape(title)}</h2>"
        "<table><thead><tr><th>date</th><th>KR</th><th></th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></section>"
    )


def _format_symbol(value: Any, instrument_names: dict[str, str]) -> str:
    symbol = _symbol_from_sample(value)
    if not symbol:
        return str(value)
    name = instrument_names.get(symbol)
    if name and name != symbol:
        return f"{symbol} · {name}"
    return symbol


def _sample_list(values: Any, instrument_names: dict[str, str]) -> str:
    if not values:
        return ""
    if isinstance(values, list):
        texts = []
        for item in values[:10]:
            texts.append(_format_symbol(item, instrument_names))
        return ", ".join(html.escape(text) for text in texts)
    return html.escape(_format_symbol(values, instrument_names))


def _refresh_section(runs: list[dict[str, Any]], instrument_names: dict[str, str]) -> str:
    rows = []
    for run in runs:
        comparison = run["comparison"]
        samples = run["samples"]
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(run['started_at']))}</td>"
            f"<td>{html.escape(str(run['universe_key'] or run['market_key']))}</td>"
            f"<td>{html.escape(str(run['status']))}</td>"
            f"<td>{comparison.get('previous_count', 0):,}</td>"
            f"<td>{comparison.get('fetched_count', 0):,}</td>"
            f"<td>{comparison.get('added_count', 0):,}<br><small>{_sample_list(samples.get('added_symbols'), instrument_names)}</small></td>"
            f"<td>{comparison.get('removed_count', 0):,}<br><small>{_sample_list(samples.get('removed_symbols'), instrument_names)}</small></td>"
            f"<td>{comparison.get('rank_changed_count', 0):,}</td>"
            "</tr>"
        )
    return (
        "<section><h2>Refresh 변경 이력</h2>"
        "<div class=\"toolbar\">"
        f"{_button('refresh', 'Refresh US', market='us')}"
        f"{_button('refresh', 'Refresh KR', market='kr')}"
        "</div>"
        "<table><thead><tr><th>started</th><th>universe</th><th>status</th>"
        "<th>previous</th><th>fetched</th><th>added</th><th>removed</th><th>rank changed</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></section>"
    )


def _runs_section(runs: list[dict[str, Any]], instrument_names: dict[str, str]) -> str:
    rows = []
    for run in runs:
        sample_text = ", ".join(
            html.escape(_format_symbol(item, instrument_names) if _symbol_from_sample(item) else str(item.get("reason", item)))
            if isinstance(item, dict)
            else html.escape(_format_symbol(item, instrument_names))
            for item in run["error_samples"][:15]
        )
        retry = ""
        if run["run_type"] == "prices" and run["failed_count"] > 0 and run["market_key"]:
            retry = _button("retry-price", "실패 재시도", market=str(run["market_key"]), run_id=run["run_id"])
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(run['started_at']))}</td>"
            f"<td>{html.escape(str(run['run_type']))}</td>"
            f"<td>{html.escape(str(run['market_key'] or ''))}</td>"
            f"<td>{html.escape(str(run['universe_key'] or ''))}</td>"
            f"<td>{html.escape(str(run['trade_date'] or ''))}</td>"
            f"<td><span class=\"status {html.escape(str(run['status']))}\">{html.escape(str(run['status']))}</span></td>"
            f"<td>{run['requested_count']:,}</td>"
            f"<td>{run['success_count']:,}</td>"
            f"<td>{run['failed_count']:,}<br><small>{sample_text}</small></td>"
            f"<td>{run['skipped_count']:,}</td>"
            f"<td>{retry}</td>"
            "</tr>"
        )
    return (
        "<section><h2>collection_runs Log Data</h2>"
        "<p class=\"note\">최신 10개만 표시합니다.</p>"
        "<div class=\"table-scroll\">"
        "<table><thead><tr><th>started</th><th>type</th><th>market</th><th>universe</th>"
        "<th>date</th><th>status</th><th>requested</th><th>success</th><th>failed / samples</th><th>skipped</th><th></th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div></section>"
    )


def _workflows_section(workflows: list[dict[str, Any]]) -> str:
    rows = []
    for workflow in workflows:
        rows.append(
            "<tr>"
            f"<td><code>{html.escape(workflow['path'])}</code></td>"
            f"<td>{html.escape(workflow['name'])}</td>"
            f"<td>{html.escape(workflow['triggers'])}</td>"
            "</tr>"
        )
    if not rows:
        rows.append("<tr><td colspan=\"3\">workflow 파일이 없습니다.</td></tr>")
    return (
        "<section><h2>GitHub Actions YML 현황</h2>"
        "<p class=\"note\">현재 페이지에서는 workflow 파일을 조회만 합니다. 수정/실행 관리는 커밋, 권한, 실패 복구 절차가 필요해서 별도 승인 흐름으로 두는 편이 안전합니다.</p>"
        "<table><thead><tr><th>file</th><th>name</th><th>triggers</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></section>"
    )


def _management_review_section() -> str:
    items = [
        ("flows", "KR 수급 데이터 집계를 추가했습니다. scan_result의 수급 점수 품질을 확인할 때 우선 관리 대상입니다."),
        ("fundamentals", "재무/밸류에이션 데이터는 stale-days 기준 관리가 필요합니다. 다음 단계에서 누락/오래된 종목 목록을 붙일 수 있습니다."),
        ("news", "scan_result 후보 종목 기반 수집이라 provider, symbols/items 제한, 실패 로그 중심 관리가 적합합니다."),
        ("macro", "시장 공통 지표라 날짜별 row count와 최근 갱신일 확인 중심으로 관리하면 됩니다."),
        ("workflows yml", "이번에는 조회만 추가했습니다. 웹 수정/실행은 GitHub 토큰 또는 git 커밋 정책을 정한 뒤 붙이는 것이 맞습니다."),
    ]
    rows = [
        f"<tr><td>{html.escape(name)}</td><td>{html.escape(note)}</td></tr>"
        for name, note in items
    ]
    return (
        "<section><h2>추가 관리 검토</h2>"
        "<table><thead><tr><th>대상</th><th>검토 결과</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></section>"
    )


def _format_elapsed(started_at: datetime, finished_at: datetime | None = None) -> str:
    end_at = finished_at or datetime.now()
    seconds = max(0, int((end_at - started_at).total_seconds()))
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def _job_progress(job: Job) -> str:
    if job.status == "running":
        return f"실행 중 · 경과 {_format_elapsed(job.started_at)} · 갱신 {job.updated_at.strftime('%H:%M:%S')}"
    if job.exit_code is None:
        return f"{job.status} · 경과 {_format_elapsed(job.started_at)}"
    return f"{job.status} · exit {job.exit_code} · 소요 {_format_elapsed(job.started_at, job.finished_at)}"


def _job_payload(job: Job) -> dict[str, Any]:
    return {
        "job_id": job.job_id,
        "short_id": job.job_id[:8],
        "action": job.metadata.get("action", ""),
        "market": job.metadata.get("market", ""),
        "date": job.metadata.get("date", ""),
        "run_id": job.metadata.get("run_id", ""),
        "status": job.status,
        "progress": _job_progress(job),
        "command": " ".join(job.command),
        "exit_code": job.exit_code,
        "output_tail": job.output[-2000:],
    }


def _jobs_payload(jobs: dict[str, Job]) -> dict[str, Any]:
    latest = list(jobs.values())[-10:][::-1]
    return {
        "has_running": any(job.status == "running" for job in jobs.values()),
        "jobs": [_job_payload(job) for job in latest],
    }


def _jobs_section(jobs: dict[str, Job]) -> str:
    rows = []
    for job in _jobs_payload(jobs)["jobs"]:
        rows.append(
            "<tr>"
            f"<td>{html.escape(job['short_id'])}</td>"
            f"<td><span class=\"status {html.escape(job['status'])}\">{html.escape(job['status'])}</span></td>"
            f"<td>{html.escape(job['progress'])}</td>"
            f"<td><code>{html.escape(job['command'])}</code></td>"
            f"<td>{'' if job['exit_code'] is None else job['exit_code']}</td>"
            f"<td><pre>{html.escape(job['output_tail'])}</pre></td>"
            "</tr>"
        )
    return (
        "<section id=\"jobs\"><h2>실행 작업</h2>"
        "<p class=\"note\">최신 10개 작업만 표시합니다. 실행 중에는 JSON으로 2초마다 갱신됩니다.</p>"
        "<div class=\"table-scroll jobs-scroll\">"
        "<table><thead><tr><th>job</th><th>status</th><th>progress</th><th>command</th><th>exit</th><th>tail output</th></tr></thead>"
        f"<tbody id=\"jobs-body\">{''.join(rows)}</tbody></table></div></section>"
    )


def _render_page(data: dict[str, Any], state: AdminState) -> bytes:
    body = (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<title>SearchMarket Data Admin</title>"
        "<style>"
        ":root{color-scheme:dark;--bg:#0d1117;--panel:#161b22;--panel2:#0f1720;--line:#30363d;--text:#e6edf3;--muted:#8b949e;--accent:#2f81f7;--good:#3fb950;--bad:#f85149}"
        "body{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;margin:0;background:var(--bg);color:var(--text)}"
        "header{background:#010409;border-bottom:1px solid var(--line);padding:18px 24px}main{padding:20px 24px;display:grid;gap:18px}"
        "section{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:16px;overflow:auto}"
        "h1{margin:0;font-size:22px}h2{margin:0 0 12px;font-size:16px}p.note{margin:0 0 12px;color:var(--muted);font-size:13px}"
        ".coverage-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}.coverage-grid section{min-width:0}.coverage-grid table{font-size:12px}"
        "table{border-collapse:collapse;width:100%;font-size:13px}th,td{border-bottom:1px solid var(--line);padding:8px 10px;text-align:left;vertical-align:top}"
        ".coverage-grid th,.coverage-grid td{padding:6px 8px}.table-scroll{max-height:380px;overflow:auto}.jobs-scroll{max-height:460px}.table-scroll th{position:sticky;top:0;z-index:1}"
        "th{background:var(--panel2);font-weight:600;color:#c9d1d9}tr:last-child td{border-bottom:0}"
        "button{border:1px solid #388bfd;background:#1f6feb;color:white;border-radius:6px;padding:4px 7px;line-height:1.2;white-space:nowrap;cursor:pointer}button:hover{background:var(--accent)}"
        ".inline-form{display:inline-flex;align-items:center;gap:8px;flex:0 0 auto}.toolbar{display:flex;gap:8px;margin-bottom:10px;flex-wrap:nowrap}.status.failed,.status.partial{color:var(--bad);font-weight:600}"
        ".mini-progress{display:none;width:76px;height:8px;border:1px solid rgba(255,255,255,.9);border-radius:999px;overflow:hidden;background:rgba(255,255,255,.18)}"
        ".mini-progress::before{content:\"\";display:block;width:44%;height:100%;border-radius:999px;background:#fff;animation:miniProgress 1s ease-in-out infinite}"
        ".inline-form[data-running=\"true\"] .mini-progress{display:inline-block}@keyframes miniProgress{0%{transform:translateX(-120%)}100%{transform:translateX(240%)}}"
        ".status.success{color:var(--good);font-weight:600}.status.running{color:#d29922;font-weight:600}small{color:var(--muted)}pre{white-space:pre-wrap;max-width:520px;margin:0;font-size:12px;color:#c9d1d9}"
        "code{font-size:12px;color:#a5d6ff}@media(max-width:1100px){.coverage-grid{grid-template-columns:1fr}}</style></head><body>"
        "<header><h1>SearchMarket Data Admin</h1></header><main>"
        "<div class=\"coverage-grid\">"
        + _coverage_section("price 최근 7일 집계", "price", data["dates"], data["prices"])
        + _coverage_section("indicator 최근 7일 집계", "indicators", data["dates"], data["indicators"])
        + _coverage_section("scan_result 최근 7일 집계", "screen", data["dates"], data["scan_results"])
        + _kr_coverage_section("flows 최근 7일 집계", "flows", data["dates"], data["flows"])
        + "</div>"
        + _refresh_section(data["refresh_runs"], data["instrument_names"])
        + _runs_section(data["runs"], data["instrument_names"])
        + _workflows_section(data["workflows"])
        + _management_review_section()
        + _jobs_section(state.jobs)
        + _jobs_script(state.jobs)
        + "</main></body></html>"
    )
    return body.encode("utf-8")


def _jobs_script(jobs: dict[str, Job]) -> str:
    initial_payload = (
        json.dumps(_jobs_payload(jobs), ensure_ascii=False)
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )
    return (
        f'<script type="application/json" id="initial-jobs">{initial_payload}</script>'
        + """
<script>
const adminInitialJobs = JSON.parse(document.getElementById("initial-jobs").textContent);
let adminHadRunningJob = false;
function adminEscape(value) {
  return String(value ?? "").replace(/[&<>"']/g, ch => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;"
  }[ch]));
}
function adminRenderJobs(jobs) {
  const body = document.getElementById("jobs-body");
  if (!body) return;
  body.innerHTML = jobs.map(job => `
    <tr>
      <td>${adminEscape(job.short_id)}</td>
      <td><span class="status ${adminEscape(job.status)}">${adminEscape(job.status)}</span></td>
      <td>${adminEscape(job.progress)}</td>
      <td><code>${adminEscape(job.command)}</code></td>
      <td>${job.exit_code == null ? "" : adminEscape(job.exit_code)}</td>
      <td><pre>${adminEscape(job.output_tail)}</pre></td>
    </tr>
  `).join("");
}
function adminJobMatchesForm(job, form) {
  const action = form.dataset.action || "";
  const market = form.dataset.market || "";
  const date = form.dataset.date || "";
  const runId = form.getAttribute("data-run_id") || "";
  if (!action || job.action !== action) return false;
  if (market && job.market !== market) return false;
  if (date && job.date !== date) return false;
  if (runId && job.run_id !== runId) return false;
  return true;
}
function adminRenderButtonProgress(jobs) {
  const runningJobs = jobs.filter(job => job.status === "running");
  document.querySelectorAll("form.inline-form").forEach(form => {
    const active = runningJobs.some(job => adminJobMatchesForm(job, form));
    form.dataset.running = active ? "true" : "false";
    form.dataset.submitting = active ? "true" : "false";
    const button = form.querySelector("button");
    if (button) button.disabled = active;
  });
}
function adminBindSubmitProgress() {
  document.querySelectorAll("form.inline-form").forEach(form => {
    form.addEventListener("submit", async event => {
      event.preventDefault();
      if (form.dataset.submitting === "true") return;
      form.dataset.submitting = "true";
      form.dataset.running = "true";
      const button = form.querySelector("button");
      if (button) button.disabled = true;
      try {
        const response = await fetch(form.action, {
          method: "POST",
          body: new URLSearchParams(new FormData(form)),
          headers: {"X-Requested-With": "fetch"},
          cache: "no-store"
        });
        if (!response.ok) throw new Error(`run failed: ${response.status}`);
        const data = await response.json();
        const jobs = data.jobs || [];
        adminRenderJobs(jobs);
        adminRenderButtonProgress(jobs);
        adminHadRunningJob = Boolean(data.has_running);
        window.setTimeout(adminPollJobs, 250);
      } catch (error) {
        form.dataset.running = "false";
        form.dataset.submitting = "false";
        if (button) button.disabled = false;
        window.alert("작업 시작 실패: " + error.message);
      }
    });
  });
}
async function adminPollJobs() {
  try {
    const response = await fetch("/api/jobs", {cache: "no-store"});
    if (!response.ok) return;
    const data = await response.json();
    const jobs = data.jobs || [];
    adminRenderJobs(jobs);
    adminRenderButtonProgress(jobs);
    if (data.has_running) {
      adminHadRunningJob = true;
      window.setTimeout(adminPollJobs, 2000);
    } else if (adminHadRunningJob) {
      window.location.reload();
    }
  } catch (error) {
    window.setTimeout(adminPollJobs, 5000);
  }
}
adminBindSubmitProgress();
adminRenderButtonProgress(adminInitialJobs.jobs || []);
adminHadRunningJob = Boolean(adminInitialJobs.has_running);
window.setTimeout(adminPollJobs, 500);
</script>
"""
    )


def _command_for_form(form: dict[str, list[str]]) -> list[str]:
    action = (form.get("action") or [""])[0]
    market = (form.get("market") or [""])[0]
    date_value = (form.get("date") or [""])[0]
    run_id = (form.get("run_id") or [""])[0]
    if action not in ALLOWED_ACTIONS:
        raise ValueError("unsupported action")
    if market and market not in ALLOWED_MARKETS and not (action == "flows" and market in ALLOWED_FLOW_MARKETS):
        raise ValueError("unsupported market")

    command = [sys.executable, "Search.py"]
    if action == "refresh":
        if not market:
            raise ValueError("market is required")
        command += ["refresh", market]
    elif action in {"price", "indicators"}:
        if not market or not date_value:
            raise ValueError("market and date are required")
        command += [action, market, "--date", date_value]
        if action == "price":
            command += ["--force"]
    elif action == "screen":
        if not market or not date_value:
            raise ValueError("market and date are required")
        command += ["screen", market, "--date", date_value]
    elif action == "flows":
        if not market or not date_value:
            raise ValueError("market and date are required")
        if market not in ALLOWED_FLOW_MARKETS:
            raise ValueError("unsupported flow market")
        command += ["flows", market, "--date", date_value, "--force"]
    elif action == "retry-price":
        if not market:
            raise ValueError("market is required")
        command += ["retry-price", market]
        if run_id:
            command += ["--run-id", run_id]
    return command


def _job_metadata_for_form(form: dict[str, list[str]]) -> dict[str, str]:
    return {
        "action": (form.get("action") or [""])[0],
        "market": (form.get("market") or [""])[0],
        "date": (form.get("date") or [""])[0],
        "run_id": (form.get("run_id") or [""])[0],
    }


def _start_job(state: AdminState, command: list[str], metadata: dict[str, str] | None = None) -> Job:
    job = Job(job_id=str(uuid.uuid4()), command=command, metadata=metadata or {})
    state.jobs[job.job_id] = job

    def run() -> None:
        try:
            job.output = "started\n"
            env = {**os.environ, "PYTHONUNBUFFERED": "1"}
            process = subprocess.Popen(
                command,
                cwd=REPO_ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                env=env,
            )
            if process.stdout:
                for line in process.stdout:
                    job.output = (job.output + line)[-8000:]
                    job.updated_at = datetime.now()
            job.exit_code = process.wait()
            job.updated_at = datetime.now()
            job.finished_at = job.updated_at
            job.status = "success" if job.exit_code == 0 else "failed"
        except Exception as exc:  # pragma: no cover - defensive server boundary
            job.exit_code = -1
            job.output = repr(exc)
            job.updated_at = datetime.now()
            job.finished_at = job.updated_at
            job.status = "failed"

    threading.Thread(target=run, daemon=True).start()
    return job


class AdminHandler(BaseHTTPRequestHandler):
    state: AdminState

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/jobs":
            self._send_json(_jobs_payload(self.state.jobs))
            return
        if path != "/":
            self.send_error(404)
            return
        data = _load_dashboard(self.state.database_url)
        body = _render_page(data, self.state)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/run":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length") or 0)
        form = parse_qs(self.rfile.read(length).decode("utf-8"))
        try:
            command = _command_for_form(form)
            job = _start_job(self.state, command, _job_metadata_for_form(form))
        except ValueError as exc:
            self.send_error(400, str(exc))
            return
        if self.headers.get("X-Requested-With") == "fetch":
            payload = _jobs_payload(self.state.jobs)
            payload["started_job"] = _job_payload(job)
            self._send_json(payload)
            return
        self.send_response(303)
        self.send_header("Location", "/")
        self.end_headers()

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"  admin {self.address_string()} - {fmt % args}")


def run_admin_server(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    database_url: str | None = None,
) -> None:
    state = AdminState(database_url=database_url)

    class Handler(AdminHandler):
        pass

    Handler.state = state
    try:
        server = ThreadingHTTPServer((host, port), Handler)
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE:
            raise SystemExit(
                f"admin server port is already in use: http://{host}:{port}\n"
                f"Use an existing browser tab or run with another port, for example: "
                f"uv run python Search.py admin --port {port + 1}"
            ) from exc
        raise
    print(f"  data admin: http://{host}:{port}")
    server.serve_forever()
