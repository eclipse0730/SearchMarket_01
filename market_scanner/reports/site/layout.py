"""사이트 공통 HTML 레이아웃과 포맷팅 헬퍼.

모든 페이지는 render_page() 로 HTML 문자열을 만든다. CSS는 한 곳에 모아 두고
페이지마다 같은 헤더/풋터를 공유한다.
"""
from __future__ import annotations

import json
from datetime import datetime
from functools import lru_cache
from html import escape
from pathlib import Path
from urllib.parse import quote_plus


SITE_TITLE = "SearchMarket"
SITE_TAGLINE = "Daily Market Scan"

# 상단 네비게이션 항목: (nav_key, 표시명, href_suffix, dropdown_items)
# href_suffix 는 prefix + suffix 로 최종 URL을 조합한다.
_NAV_ITEMS: list[tuple[str, str, str, tuple[tuple[str, str, str], ...]]] = [
    (
        "us-all",
        "US종합",
        "markets/us-all/index.html",
        (
            ("us", "나스닥", "markets/us/index.html"),
            ("nasdaq100", "NASDAQ100", "markets/nasdaq100/index.html"),
            ("sp500", "S&P500", "markets/sp500/index.html"),
            ("dow30", "다우존스30", "markets/dow30/index.html"),
        ),
    ),
    (
        "kr-all",
        "KR종합",
        "markets/kr-all/index.html",
        (
            ("kospi", "KOSPI", "markets/kospi/index.html"),
            ("kospi200", "KOSPI200", "markets/kospi200/index.html"),
            ("kosdaq", "KOSDAQ", "markets/kosdaq/index.html"),
            ("kosdaq150", "KOSDAQ150", "markets/kosdaq150/index.html"),
        ),
    ),
    ("admin", "관리", "admin/index.html", ()),
]


_CACHE_PATH = Path(__file__).resolve().parents[2] / "assets" / "investing_url_cache.json"


@lru_cache(maxsize=1)
def _investing_cache() -> dict[str, str]:
    if not _CACHE_PATH.exists():
        return {}
    try:
        return json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def quote_url(symbol: str) -> str:
    """종목 심볼 → kr.investing.com 상세 URL (캐시 히트 시) 또는 검색 URL (미스 시)."""
    cached = _investing_cache().get(symbol)
    if cached:
        return cached.replace("www.investing.com", "kr.investing.com", 1)
    normalized = symbol.replace(".KS", "").replace(".KQ", "").replace("=F", "")
    return f"https://kr.investing.com/search?q={quote_plus(normalized)}"


# 페이지 깊이별 상대 경로 prefix (..(/..)*). 메인=0, 시장=2, 섹터=4.
def rel_prefix(depth: int) -> str:
    return "" if depth == 0 else "../" * depth


CSS = """
:root {
  --bg: #07101c;
  --panel: rgba(14, 26, 42, .82);
  --panel-2: rgba(17, 31, 50, .92);
  --border: rgba(148, 163, 184, .18);
  --text: #e6edf3;
  --muted: #8fa3ba;
  --up: #16c784;
  --down: #ea3943;
  --flat: #8b95a5;
  --accent: #62c7ff;
  --accent-dim: #1f6feb;
}
* { box-sizing: border-box; }
html { min-height: 100%; background: #050a12; }
body { margin: 0; padding: 0; min-height: 100vh;
  background:
    radial-gradient(circle at 10% -10%, rgba(98, 199, 255, .18), transparent 28%),
    radial-gradient(circle at 98% 0, rgba(216, 169, 74, .12), transparent 24%),
    linear-gradient(180deg, #081321, #050a12 74%);
  color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans KR", Roboto, sans-serif;
  font-size: clamp(0.8125rem, 0.78rem + 0.16vw, 0.875rem); line-height: 1.5; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
header.site {
  border-bottom: 0.0625rem solid var(--border);
  padding: clamp(0.75rem, 0.55rem + 0.55vw, 0.875rem) clamp(0.9rem, 0.45rem + 1.5vw, 1.5rem);
  background: rgba(5, 10, 18, .72); backdrop-filter: blur(0.875rem);
  display: flex; align-items: center; justify-content: flex-start; flex-wrap: wrap; gap: clamp(0.5rem, 1vw, 0.75rem);
  position: sticky; top: 0; z-index: 20;
}
.site-left { display: flex; align-items: center; flex-wrap: wrap; gap: clamp(0.75rem, 1.4vw, 1.125rem); }
header.site .brand { color: var(--text); text-decoration: none; }
header.site .brand:hover { color: var(--accent); text-decoration: none; }
header.site .title { font-size: clamp(1rem, 0.9rem + 0.4vw, 1.125rem); font-weight: 700; }
header.site .tagline { color: var(--muted); font-size: clamp(0.75rem, 0.72rem + 0.14vw, 0.8125rem); }
header.site nav { display: flex; flex-wrap: wrap; gap: 0.25rem; align-items: center; }
.nav-item { position: relative; }
.nav-link { display: inline-flex; align-items: center; gap: 0.375rem; padding: 0.375rem 0.625rem; border-radius: 0.375rem; color: var(--muted); font-size: clamp(0.75rem, 0.72rem + 0.14vw, 0.8125rem); }
.nav-link:hover { color: var(--text); text-decoration: none; background: var(--panel-2); }
.nav-link.nav-active { color: var(--text); font-weight: 600; background: var(--panel-2); }
.nav-caret { color: var(--muted); font-size: 0.625rem; }
.nav-menu {
  display: none; position: absolute; left: 0; top: 100%; min-width: 10.625rem;
  padding: 0.4375rem; border: 0.0625rem solid var(--border); border-radius: 0.5rem;
  background: rgba(8, 19, 33, .98); box-shadow: 0 1rem 2.25rem rgba(0, 0, 0, .28);
}
.nav-item:hover .nav-menu, .nav-item:focus-within .nav-menu { display: grid; gap: 0.125rem; }
.nav-menu a { display: block; padding: 0.4375rem 0.5625rem; border-radius: 0.375rem; color: #cbd5e1; font-size: 0.75rem; }
.nav-menu a:hover, .nav-menu a.nav-active { color: var(--text); background: var(--panel-2); text-decoration: none; }
main { width: min(76%, calc(100% - clamp(1.5rem, 4vw, 2rem))); margin: 0 auto; padding: clamp(1rem, 2.4vw, 1.5rem) 0; }
main.main-wide { width: min(70%, calc(100% - clamp(1.5rem, 4vw, 2rem))); }
section.block { margin-bottom: clamp(1.5rem, 3vw, 2rem); }
section.block > h2 { font-size: clamp(0.95rem, 0.88rem + 0.25vw, 1rem); font-weight: 600; margin: 0 0 0.75rem 0;
  border-left: 0.1875rem solid var(--accent); padding-left: 0.625rem; }
section.block > .sub { color: var(--muted); font-size: 0.75rem; margin-bottom: 0.75rem; }

/* 시장 카드 그리드 */
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 16.25rem), 1fr));
  gap: 0.75rem; }
.card { background: var(--panel); border: 0.0625rem solid var(--border);
  border-radius: 0.5rem; padding: 0.875rem 1rem; }
.summary-card { width: min(42%, 100%); }
.card-link { display: block; color: var(--text); text-decoration: none;
  transition: border-color 0.15s, transform 0.15s; }
.card-link:hover { border-color: var(--accent); text-decoration: none; transform: translateY(-0.0625rem); }
.card .name { font-weight: 600; font-size: 0.9375rem; margin-bottom: 0.25rem; }
.card .meta { color: var(--muted); font-size: 0.6875rem; margin-bottom: 0.625rem; }
.card .row { display: flex; justify-content: space-between; font-size: 0.75rem;
  padding: 0.1875rem 0; border-bottom: 0.0625rem dashed var(--border); }
.card .row:last-child { border-bottom: none; }
.card .row .k { color: var(--muted); }
.card .row .v { font-variant-numeric: tabular-nums; }
.card .breadth { margin-top: 0.5rem; height: 0.375rem; border-radius: 0.1875rem;
  background: var(--down); overflow: hidden; position: relative; }
.card .breadth > span { display: block; height: 100%; background: var(--up); }
.card .pill { display: inline-block; padding: 0.125rem 0.5rem; border-radius: 999rem;
  font-size: 0.6875rem; font-weight: 500; background: var(--panel-2); color: var(--muted); }
.pill.bull { color: #fff; background: var(--up); }
.pill.bear { color: #fff; background: var(--down); }
.pill.flat { color: #fff; background: var(--flat); }
.pill.risk-elevated { color: #fff; background: var(--down); }
.pill.risk-normal { color: var(--muted); background: var(--panel-2); }

/* 테이블 */
table.t { width: 100%; border-collapse: collapse; font-size: 0.75rem; }
table.t th, table.t td { padding: 0.4375rem 0.625rem; border-bottom: 0.0625rem solid var(--border);
  text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
table.t th { color: var(--muted); font-weight: 500; text-align: right; background: var(--panel); }
table.t th.l, table.t td.l { text-align: left; }
table.t tr:hover td { background: var(--panel-2); }
.table-scroll {
  width: 100%; overflow-x: auto; -webkit-overflow-scrolling: touch;
  scrollbar-width: thin; scrollbar-color: rgba(148,163,184,.3) transparent;
}
.table-scroll table.t { min-width: 42rem; }
.wl-table-scroll table.t { min-width: 24rem; }
.empty-cell { text-align: center; padding: 0.625rem; }
.up { color: var(--up); }
.down { color: var(--down); }
.flat { color: var(--flat); }

/* 메인 핵심 지표 */
.market-pulse {
  margin-bottom: clamp(1.25rem, 2.8vw, 1.75rem); padding: clamp(1rem, 2.5vw, 1.375rem);
  border: 0.0625rem solid rgba(148, 163, 184, .2); border-radius: 0.5rem;
  background: linear-gradient(135deg, rgba(14, 26, 42, .96), rgba(18, 24, 38, .92));
  box-shadow: 0 1.25rem 3.125rem rgba(0, 0, 0, .22);
}
.pulse-head { display: flex; align-items: flex-end; justify-content: space-between; gap: clamp(0.75rem, 1.8vw, 1.125rem); margin-bottom: clamp(0.9rem, 2vw, 1.125rem); }
.eyebrow { color: #9cc9ff; font-size: 0.6875rem; font-weight: 700; letter-spacing: 0; margin-bottom: 0.1875rem; }
.pulse-head h1 { margin: 0; font-size: clamp(1.25rem, 1rem + 1vw, 1.625rem); line-height: 1.15; }
.pulse-note { max-width: min(38%, 28rem); color: var(--muted); font-size: 0.75rem; text-align: right; }
.top-indicator-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 12.5rem), 1fr)); gap: clamp(0.5rem, 1vw, 0.625rem); }
.top-indicator-card {
  min-height: clamp(6.5rem, 12vw, 7.375rem); display: flex; flex-direction: column; justify-content: space-between;
  padding: clamp(0.75rem, 1.5vw, 0.875rem); border: 0.0625rem solid var(--border); border-radius: 0.5rem;
  background: rgba(7, 16, 28, .72);
}
.top-indicator-card:hover { border-color: rgba(98, 199, 255, .5); }
.tic-head { display: flex; align-items: center; justify-content: space-between; gap: 0.5rem; min-width: 0; }
.tic-label { color: var(--text); font-weight: 700; font-size: clamp(0.75rem, 0.72rem + 0.16vw, 0.8125rem); }
.tic-group {
  color: #d7b56d; background: rgba(216, 169, 74, .12); border: 0.0625rem solid rgba(216, 169, 74, .22);
  border-radius: 999rem; padding: 0.0625rem 0.4375rem; font-size: 0.625rem; white-space: nowrap;
}
.tic-main { display: flex; align-items: baseline; justify-content: space-between; gap: 0.5rem; min-width: 0; margin: 0.625rem 0 0.5625rem; }
.tic-value { min-width: 0; font-size: clamp(1.15rem, 0.85rem + 1.05vw, 1.5rem); line-height: 1; font-weight: 750; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.tic-change { flex: 0 0 auto; font-size: 0.8125rem; font-weight: 700; font-variant-numeric: tabular-nums; }
.tic-asof {
  min-width: 0; color: var(--muted); font-size: 0.625rem; line-height: 1.25;
  text-align: left; overflow-wrap: anywhere;
}

/* 매크로 패널 */
.macro-grid { display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 9.6875rem), 1fr));
  gap: clamp(0.5rem, 1vw, 0.5625rem); }
.macro-cell { background: var(--panel); border: 0.0625rem solid var(--border);
  border-radius: 0.5rem; padding: clamp(0.625rem, 1.2vw, 0.75rem); }
.macro-card-head { display: flex; align-items: baseline; justify-content: space-between; gap: 0.5rem; margin-bottom: 0.25rem; min-width: 0; }
.macro-cell .sym { flex: 0 0 auto; color: var(--muted); font-size: 0.6875rem; }
.macro-cell .name { min-width: 0; font-size: 0.75rem;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.macro-value-row { display: flex; align-items: baseline; justify-content: space-between; gap: 0.5rem; min-width: 0; }
.macro-cell .metric-value { min-width: 0; font-size: 0.875rem; font-weight: 600; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.macro-cell .chg { flex: 0 0 auto; font-size: 0.75rem; font-variant-numeric: tabular-nums; }
.macro-summary { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 9.0625rem), 1fr)); gap: clamp(0.5rem, 1vw, 0.5625rem); margin: 0.75rem 0 1rem; }
.macro-chip { border: 0.0625rem solid var(--border); border-radius: 0.5rem; padding: 0.625rem 0.6875rem; background: rgba(255,255,255,.02); }
.chip-label { color: var(--muted); font-size: 0.6875rem; margin-bottom: 0.3125rem; }
.chip-main { font-size: 1rem; font-weight: 750; margin-bottom: 0.1875rem; }
.chip-note { color: var(--muted); font-size: 0.6875rem; line-height: 1.35; }
.kr-macro-group-grid {
  display: grid; grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: clamp(0.875rem, 2vw, 1.25rem);
}
.kr-macro-group-grid .sector-group { margin-bottom: 0; min-width: 0; }
.macro-status { flex: 0 0 auto; border-radius: 999rem; padding: 0.0625rem 0.4375rem; font-size: 0.625rem; font-weight: 700; }
.status-ok { border-color: rgba(64, 196, 142, .36); background: rgba(64, 196, 142, .11); color: #79d6ad; }
.status-neutral { border-color: rgba(160, 169, 184, .32); background: rgba(160, 169, 184, .10); color: #b8c0cc; }
.status-warn { border-color: rgba(227, 177, 82, .36); background: rgba(227, 177, 82, .12); color: #e8c579; }
.status-risk { border-color: rgba(224, 91, 95, .38); background: rgba(224, 91, 95, .12); color: #ee8f91; }
.macro-context { color: var(--muted); font-size: 0.625rem; margin-top: 0.4375rem; }
.macro-note { color: var(--text); font-size: 0.6875rem; line-height: 1.35; margin-top: 0.25rem; }

/* 섹터 히트맵 */
.sector-group { margin-bottom: 1rem; }
.sector-group .gname { color: var(--muted); font-size: 0.75rem; margin-bottom: 0.375rem; }
.sector-compare-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: clamp(1.25rem, 2.6vw, 1.75rem); }
.sector-compare-panel { min-width: 0; }
.sector-compare-panel .gname { color: var(--muted); font-size: 0.75rem; margin-bottom: 0.375rem; }
.sector-theme-summary-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 11rem), 1fr));
  gap: 0.5rem;
}
.sector-theme-card {
  min-height: 8.25rem; padding: 0.75rem; border-radius: 0.5rem;
  border: 0.0625rem solid rgba(255,255,255,.1); color: #f7fbff;
}
.sector-theme-card-head { display: flex; justify-content: space-between; gap: 0.625rem; align-items: flex-start; }
.sector-theme-title { color: #fff; font-size: 0.875rem; font-weight: 900; line-height: 1.2; }
.sector-theme-change {
  color: #fff; font-size: 1rem; font-weight: 900; font-variant-numeric: tabular-nums;
  white-space: nowrap; text-shadow: 0 0.0625rem 0.125rem rgba(0,0,0,.32);
}
.sector-theme-meta { color: rgba(255,255,255,.72); font-size: 0.6875rem; margin-top: 0.25rem; }
.sector-theme-pair {
  display: grid; grid-template-columns: auto minmax(0, 1fr) auto;
  gap: 0.375rem; align-items: center; margin-top: 0.5rem;
  color: rgba(255,255,255,.78); font-size: 0.6875rem;
}
.sector-theme-pair b { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #fff; font-weight: 700; }
.sector-theme-pair em {
  color: #fff; font-style: normal; font-weight: 900; font-variant-numeric: tabular-nums;
  text-shadow: 0 0.0625rem 0.125rem rgba(0,0,0,.32);
}
.sector-heatmap { display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 8.75rem), 1fr));
  gap: 0.375rem; }
.sector-tile { padding: 0.625rem; border-radius: 0.75rem; border: 0.0625rem solid rgba(255,255,255,.08);
  background: var(--panel); color: #f7fbff; min-height: 4.75rem; }
.sector-tile:hover { border-color: rgba(255,255,255,.32); }
.sector-tile .s { font-size: 0.8125rem; line-height: 1.15; font-weight: 800;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sector-tile .m { color: rgba(255,255,255,.76); font-size: 0.6875rem; margin-top: 0.5rem;
  display: flex; justify-content: space-between; gap: 0.5rem; font-variant-numeric: tabular-nums; }
.sector-tile .m span:last-child { color: #fff; font-size: 0.875rem; font-weight: 900; }

footer.site { border-top: 0.0625rem solid var(--border); margin-top: 1.5rem;
  padding: 1rem 1.5rem; color: var(--muted); font-size: 0.75rem; text-align: center; }

/* 종합 시장 점수 히어로 */
.score-hero { display: flex; align-items: center; gap: clamp(1rem, 3vw, 2rem); flex-wrap: wrap;
  background: var(--panel); border: 0.0625rem solid var(--border);
  border-radius: 0.5rem; padding: clamp(1rem, 2.4vw, 1.5rem); }
.score-panel-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: clamp(0.75rem, 1.8vw, 1rem); }
.score-market-panel { background: var(--panel); border: 0.0625rem solid var(--border);
  border-radius: 0.5rem; padding: clamp(0.875rem, 2vw, 1.125rem); min-width: 0; }
.score-panel-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 1rem; margin-bottom: 0.875rem; }
.score-market-name { font-size: 0.9375rem; font-weight: 700; }
.score-market-meta { color: var(--muted); font-size: 0.6875rem; margin-top: 0.1875rem; }
.sh-score { text-align: center; min-width: 5.625rem; }
.sh-value { font-size: clamp(2.25rem, 1.45rem + 2.6vw, 3rem); font-weight: 700; font-variant-numeric: tabular-nums; line-height: 1; }
.sh-label { color: var(--muted); font-size: 0.75rem; margin-top: 0.25rem; }
.pulse-grid { display: flex; gap: 0.625rem; flex-wrap: wrap; flex: 1; }
.pulse-card { background: var(--panel-2); border: 0.0625rem solid var(--border);
  border-radius: 0.375rem; padding: 0.625rem 0.875rem; min-width: 5.625rem; }
.pc-label { color: var(--muted); font-size: 0.6875rem; margin-bottom: 0.25rem; }
.pc-value { font-size: clamp(1rem, 0.85rem + 0.5vw, 1.125rem); font-weight: 600; font-variant-numeric: tabular-nums; }
.score-hero .score-neutral { color: var(--text); }

/* 섹터 타일 링크 */
a.sector-tile-link { display: block; color: var(--text); text-decoration: none;
  transition: border-color 0.15s, transform 0.15s; }
a.sector-tile-link:hover { border-color: var(--accent); transform: translateY(-0.0625rem); text-decoration: none; }

/* 워치리스트 패널 */
.watchlist-grid { display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 20rem), 1fr)); gap: 0.875rem; }
.wl-panel { background: var(--panel); border: 0.0625rem solid var(--border);
  border-radius: 0.5rem; overflow: hidden; }
.wl-head { padding: 0.625rem 0.875rem; border-bottom: 0.0625rem solid var(--border); }
.wl-title { font-weight: 600; font-size: 0.875rem; margin-right: 0.5rem; }
.wl-desc { color: var(--muted); font-size: 0.6875rem; }
.wl-panel table.t th, .wl-panel table.t td { padding: 0.3125rem 0.625rem; }

/* 시계열 차트 */
.macro-chart-wrap {
  margin-bottom: clamp(1rem, 2vw, 1.25rem); padding: clamp(0.625rem, 1.8vw, 0.875rem); border: 0.0625rem solid var(--border);
  border-radius: 0.5rem; background: rgba(7, 16, 28, .58);
}
.chart-body { display: flex; align-items: flex-start; gap: clamp(0.625rem, 1.5vw, 0.875rem); }
.chart-main { flex: 1 1 auto; max-width: none; min-width: 0; }
.chart-controls { display: flex; align-items: center; flex-wrap: wrap; gap: 0.5rem; margin-bottom: 0.625rem; }
.chart-tabs { display: flex; gap: 0.375rem; flex-wrap: wrap; }
.ct-tab {
  padding: 0.3125rem clamp(0.6rem, 1.5vw, 0.875rem); border-radius: 0.3125rem; border: 0.0625rem solid var(--border);
  background: var(--panel); color: var(--muted); font-size: 0.75rem; cursor: pointer; }
.ct-tab:hover { color: var(--text); border-color: var(--accent); }
.ct-tab.ct-tab-active { background: var(--accent-dim); color: #fff; border-color: var(--accent-dim); }
.chart-daterange { display: flex; align-items: center; gap: 0.375rem; margin-left: auto; }
.cdr-label { color: var(--muted); font-size: 0.75rem; }
.cdr-sep { color: var(--muted); font-size: 0.8125rem; }
.ct-date-input {
  background: var(--panel); border: 0.0625rem solid var(--border); border-radius: 0.25rem;
  color: var(--text); font-size: 0.75rem; padding: 0.25rem 0.4375rem; cursor: pointer;
  color-scheme: dark; }
.ct-date-input:focus { outline: none; border-color: var(--accent); }
.chart-canvas-wrap {
  overflow-x: auto; overflow-y: hidden;
  -webkit-overflow-scrolling: touch;
  margin-bottom: 0.5rem; padding: 0.5rem 0;
  scrollbar-width: thin; scrollbar-color: rgba(148,163,184,.3) transparent; }
.chart-toggle-panel { padding: 0.375rem 0 0.75rem; }
.chart-group-tabs { display: flex; flex-wrap: wrap; gap: 0.375rem; margin-bottom: 0.5625rem; }
.cg-tab {
  padding: 0.3125rem 0.625rem; border-radius: 0.3125rem; border: 0.0625rem solid var(--border);
  background: var(--panel); color: var(--muted); font-size: 0.75rem; cursor: pointer; }
.cg-tab:hover { color: var(--text); border-color: var(--accent); }
.cg-tab.cl-hidden { opacity: 0.42; }
.cg-tab.cl-partial { opacity: 0.72; }
.chart-legend { display: flex; flex-wrap: wrap; gap: 0.3125rem; padding: 0.375rem 0 0.75rem; }
.chart-card-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 9.6875rem), 1fr)); gap: clamp(0.5rem, 1vw, 0.5625rem); padding: 0; }
.cl-item {
  padding: 0.125rem 0.5625rem 0.125rem 0.375rem; border-radius: 0.25rem; border-left: 0.1875rem solid;
  background: var(--panel); font-size: 0.6875rem; color: var(--text); cursor: pointer;
  user-select: none; transition: opacity 0.15s; }
.cl-item:hover { background: var(--panel-2); }
.cl-item.cl-hidden { opacity: 0.3; }
.cl-item.cl-all { border-left-color: var(--accent); font-weight: 600; }
.cl-item.cl-partial { opacity: 0.62; }
.chart-toggle-card {
  width: 100%; min-width: 0; text-align: left; color: var(--text); font: inherit;
  cursor: pointer; border-left: 0.1875rem solid var(--series-color, var(--accent)); }
.chart-toggle-card:hover { background: var(--panel-2); border-color: var(--border); border-left-color: var(--series-color, var(--accent)); }
.chart-toggle-card.cl-hidden { opacity: 0.36; }

@media (max-width: 47.5rem) {
  main, main.main-wide { width: calc(100% - 1.5rem); padding: 1rem 0; }
  .market-pulse { padding: 1rem; }
  .summary-card { width: 100%; }
  .cards { grid-template-columns: 1fr; }
  .card .row { gap: 0.75rem; }
  .card .row .v { text-align: right; }
  .score-panel-grid { grid-template-columns: 1fr; }
  .score-panel-head { align-items: center; }
  .score-market-panel .pulse-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .sector-compare-grid { grid-template-columns: 1fr; }
  .kr-macro-group-grid { grid-template-columns: 1fr; }
  .sector-theme-summary-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .sector-heatmap { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  table.t { font-size: 0.6875rem; }
  table.t th, table.t td { padding: 0.375rem 0.5rem; }
  .pulse-head { align-items: flex-start; flex-direction: column; }
  .pulse-note { max-width: none; text-align: left; }
  .top-indicator-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .tic-main { align-items: flex-start; flex-direction: column; gap: 0.25rem; }
  .tic-asof { white-space: normal; }
  .chart-body { display: block; }
  .chart-main { max-width: none; }
  .chart-controls { align-items: stretch; }
  .chart-daterange { margin-left: 0; width: 100%; flex-wrap: wrap; }
  .ct-date-input { flex: 1 1 8.5rem; min-width: 0; }
}

@media (max-width: 26.25rem) {
  .top-indicator-grid { grid-template-columns: 1fr; }
  .sector-theme-summary-grid { grid-template-columns: 1fr; }
  .sector-heatmap { grid-template-columns: 1fr; }
}
"""


def fmt_pct(value: float | None, decimals: int = 2) -> str:
    if value is None:
        return "—"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.{decimals}f}%"


def fmt_num(value: float | None, decimals: int = 2) -> str:
    if value is None:
        return "—"
    return f"{value:,.{decimals}f}"


def fmt_int(value: int | None) -> str:
    if value is None:
        return "—"
    return f"{value:,}"


def fmt_price(value: float | None, decimals: int = 2) -> str:
    if value is None:
        return "—"
    return f"{value:,.{decimals}f}"


def change_class(value: float | None) -> str:
    if value is None:
        return "flat"
    if value > 0:
        return "up"
    if value < 0:
        return "down"
    return "flat"


def regime_pill(regime: str | None) -> str:
    """regime 문자열 → CSS pill 클래스."""
    if not regime:
        return "flat"
    r = regime.lower()
    if "bull" in r or r in {"strong", "uptrend", "risk_on"}:
        return "bull"
    if "bear" in r or r in {"weak", "downtrend", "risk_off"}:
        return "bear"
    return "flat"


def risk_pill(risk_level: str | None) -> str:
    if not risk_level:
        return "risk-normal"
    if risk_level.lower() in {"elevated", "high", "extreme"}:
        return "risk-elevated"
    return "risk-normal"


def _nav_active_class(
    key: str,
    children: tuple[tuple[str, str, str], ...],
    nav_active: str | None,
) -> str:
    child_keys = {child_key for child_key, _, _ in children}
    return " nav-active" if nav_active == key or nav_active in child_keys else ""


def nav_links_html(depth: int, nav_active: str | None, active_class: str = "nav-active") -> str:
    """상단 네비게이션 링크 HTML. 공통 페이지와 v1-style 상세 페이지가 함께 사용한다."""
    prefix = rel_prefix(depth)
    items: list[str] = []
    for key, label, href, children in _NAV_ITEMS:
        active = _nav_active_class(key, children, nav_active).strip()
        active_attr = f" {active_class}" if active else ""
        caret = ' <span class="nav-caret">▾</span>' if children else ""
        link = (
            f'<a class="nav-link{active_attr}" href="{escape(prefix + href)}">'
            f'{escape(label)}{caret}</a>'
        )
        if children:
            child_links: list[str] = []
            for child_key, child_label, child_href in children:
                child_active = f' class="{active_class}"' if child_key == nav_active else ""
                child_links.append(
                    f'<a href="{escape(prefix + child_href)}"{child_active}>'
                    f'{escape(child_label)}</a>'
                )
            menu = "".join(child_links)
            items.append(f'<div class="nav-item has-menu">{link}<div class="nav-menu">{menu}</div></div>')
        else:
            items.append(f'<div class="nav-item">{link}</div>')
    return "".join(items)


def site_header_html(depth: int, nav_active: str | None) -> str:
    prefix = rel_prefix(depth)
    return f"""
<header class="site">
  <div class="site-left">
    <a class="brand" href="{escape(prefix + "index.html")}">
      <span class="title">{escape(SITE_TITLE)}</span>
      <span class="tagline"> · {escape(SITE_TAGLINE)}</span>
    </a>
    <nav>{nav_links_html(depth, nav_active)}</nav>
  </div>
</header>"""


def render_page(
    *,
    title: str,
    depth: int,
    body_html: str,
    nav_active: str | None = None,
    generated_at: datetime | None = None,
    main_class: str | None = None,
) -> str:
    """공통 헤더/푸터로 감싼 HTML 페이지 문자열."""
    ts = (generated_at or datetime.now()).strftime("%Y-%m-%d %H:%M")
    main_attr = f' class="{escape(main_class)}"' if main_class else ""
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)} · {escape(SITE_TITLE)}</title>
<style>{CSS}</style>
</head>
<body>
{site_header_html(depth, nav_active)}
<main{main_attr}>
{body_html}
</main>
<footer class="site">
  Generated {escape(ts)} · SearchMarket
</footer>
</body>
</html>
"""
