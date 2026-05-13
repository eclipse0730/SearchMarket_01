"""v2 사이트 공통 HTML 레이아웃과 포맷팅 헬퍼.

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

# 상단 네비게이션 항목: (nav_key, 표시명, href_suffix)
# href_suffix 는 prefix + suffix 로 최종 URL을 조합한다.
_NAV_ITEMS: list[tuple[str, str, str]] = [
    ("home",           "홈",       "index.html"),
    ("us",             "나스닥",   "markets/us/index.html"),
    ("kospi",          "KOSPI",    "markets/kospi/index.html"),
    ("kosdaq",         "KOSDAQ",   "markets/kosdaq/index.html"),
    ("global-indices", "글로벌지수", "markets/global-indices/index.html"),
    ("sector-etfs",    "섹터ETF",  "markets/sector-etfs/index.html"),
    ("commodities",    "원자재",   "markets/commodities/index.html"),
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
  --bg: #0e1117;
  --panel: #161b22;
  --panel-2: #1c2330;
  --border: #2a313c;
  --text: #e6edf3;
  --muted: #8b95a5;
  --up: #16c784;
  --down: #ea3943;
  --flat: #8b95a5;
  --accent: #58a6ff;
  --accent-dim: #1f6feb;
}
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; background: var(--bg); color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans KR", Roboto, sans-serif;
  font-size: 14px; line-height: 1.5; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
header.site {
  border-bottom: 1px solid var(--border);
  padding: 18px 24px; background: var(--panel);
  display: flex; align-items: baseline; justify-content: space-between; flex-wrap: wrap; gap: 12px;
}
header.site .title { font-size: 18px; font-weight: 600; }
header.site .tagline { color: var(--muted); font-size: 13px; }
header.site nav { display: flex; flex-wrap: wrap; gap: 2px; align-items: center; }
header.site nav a { padding: 4px 10px; border-radius: 6px; color: var(--muted); font-size: 13px; }
header.site nav a:hover { color: var(--text); text-decoration: none; background: var(--panel-2); }
header.site nav a.nav-active { color: var(--text); font-weight: 600; background: var(--panel-2); }
main { max-width: 1280px; margin: 0 auto; padding: 24px; }
section.block { margin-bottom: 32px; }
section.block > h2 { font-size: 16px; font-weight: 600; margin: 0 0 12px 0;
  border-left: 3px solid var(--accent); padding-left: 10px; }
section.block > .sub { color: var(--muted); font-size: 12px; margin-bottom: 12px; }

/* 시장 카드 그리드 */
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 12px; }
.card { background: var(--panel); border: 1px solid var(--border);
  border-radius: 8px; padding: 14px 16px; }
.card-link { display: block; color: var(--text); text-decoration: none;
  transition: border-color 0.15s, transform 0.15s; }
.card-link:hover { border-color: var(--accent); text-decoration: none; transform: translateY(-1px); }
.card .name { font-weight: 600; font-size: 15px; margin-bottom: 4px; }
.card .meta { color: var(--muted); font-size: 11px; margin-bottom: 10px; }
.card .row { display: flex; justify-content: space-between; font-size: 12px;
  padding: 3px 0; border-bottom: 1px dashed var(--border); }
.card .row:last-child { border-bottom: none; }
.card .row .k { color: var(--muted); }
.card .row .v { font-variant-numeric: tabular-nums; }
.card .breadth { margin-top: 8px; height: 6px; border-radius: 3px;
  background: var(--down); overflow: hidden; position: relative; }
.card .breadth > span { display: block; height: 100%; background: var(--up); }
.card .pill { display: inline-block; padding: 2px 8px; border-radius: 999px;
  font-size: 11px; font-weight: 500; background: var(--panel-2); color: var(--muted); }
.pill.bull { color: #fff; background: var(--up); }
.pill.bear { color: #fff; background: var(--down); }
.pill.flat { color: #fff; background: var(--flat); }
.pill.risk-elevated { color: #fff; background: var(--down); }
.pill.risk-normal { color: var(--muted); background: var(--panel-2); }

/* 테이블 */
table.t { width: 100%; border-collapse: collapse; font-size: 12px; }
table.t th, table.t td { padding: 7px 10px; border-bottom: 1px solid var(--border);
  text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
table.t th { color: var(--muted); font-weight: 500; text-align: right; background: var(--panel); }
table.t th.l, table.t td.l { text-align: left; }
table.t tr:hover td { background: var(--panel-2); }
.up { color: var(--up); }
.down { color: var(--down); }
.flat { color: var(--flat); }

/* 매크로 패널 */
.macro-grid { display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 8px; }
.macro-cell { background: var(--panel); border: 1px solid var(--border);
  border-radius: 6px; padding: 10px 12px; }
.macro-cell .sym { color: var(--muted); font-size: 11px; }
.macro-cell .name { font-size: 12px; margin-bottom: 4px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.macro-cell .px { font-size: 14px; font-weight: 600; font-variant-numeric: tabular-nums; }
.macro-cell .chg { font-size: 12px; font-variant-numeric: tabular-nums; }

/* 섹터 히트맵 */
.sector-group { margin-bottom: 16px; }
.sector-group .gname { color: var(--muted); font-size: 12px; margin-bottom: 6px; }
.sector-heatmap { display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 6px; }
.sector-tile { padding: 8px 10px; border-radius: 4px; border: 1px solid var(--border);
  background: var(--panel); }
.sector-tile .s { font-size: 12px; font-weight: 500;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sector-tile .m { color: var(--muted); font-size: 11px;
  display: flex; justify-content: space-between; font-variant-numeric: tabular-nums; }

footer.site { border-top: 1px solid var(--border); margin-top: 24px;
  padding: 16px 24px; color: var(--muted); font-size: 12px; text-align: center; }

/* 종합 시장 점수 히어로 */
.score-hero { display: flex; align-items: center; gap: 32px; flex-wrap: wrap;
  background: var(--panel); border: 1px solid var(--border);
  border-radius: 8px; padding: 20px 24px; }
.sh-score { text-align: center; min-width: 90px; }
.sh-value { font-size: 48px; font-weight: 700; font-variant-numeric: tabular-nums; line-height: 1; }
.sh-label { color: var(--muted); font-size: 12px; margin-top: 4px; }
.pulse-grid { display: flex; gap: 10px; flex-wrap: wrap; flex: 1; }
.pulse-card { background: var(--panel-2); border: 1px solid var(--border);
  border-radius: 6px; padding: 10px 14px; min-width: 90px; }
.pc-label { color: var(--muted); font-size: 11px; margin-bottom: 4px; }
.pc-value { font-size: 18px; font-weight: 600; font-variant-numeric: tabular-nums; }

/* 섹터 타일 링크 */
a.sector-tile-link { display: block; color: var(--text); text-decoration: none;
  transition: border-color 0.15s, transform 0.15s; }
a.sector-tile-link:hover { border-color: var(--accent); transform: translateY(-1px); text-decoration: none; }

/* 워치리스트 패널 */
.watchlist-grid { display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 14px; }
.wl-panel { background: var(--panel); border: 1px solid var(--border);
  border-radius: 8px; overflow: hidden; }
.wl-head { padding: 10px 14px; border-bottom: 1px solid var(--border); }
.wl-title { font-weight: 600; font-size: 14px; margin-right: 8px; }
.wl-desc { color: var(--muted); font-size: 11px; }
.wl-panel table.t th, .wl-panel table.t td { padding: 5px 10px; }
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


def render_page(
    *,
    title: str,
    depth: int,
    body_html: str,
    nav_active: str | None = None,
    generated_at: datetime | None = None,
) -> str:
    """공통 헤더/푸터로 감싼 HTML 페이지 문자열."""
    prefix = rel_prefix(depth)
    nav_html = "".join(
        f'<a href="{escape(prefix + href)}"'
        f'{" class=\"nav-active\"" if key == nav_active else ""}>{escape(label)}</a>'
        for key, label, href in _NAV_ITEMS
    )
    ts = (generated_at or datetime.now()).strftime("%Y-%m-%d %H:%M")
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)} · {escape(SITE_TITLE)}</title>
<style>{CSS}</style>
</head>
<body>
<header class="site">
  <div>
    <span class="title">{escape(SITE_TITLE)}</span>
    <span class="tagline"> · {escape(SITE_TAGLINE)}</span>
  </div>
  <nav>{nav_html}</nav>
</header>
<main>
{body_html}
</main>
<footer class="site">
  Generated {escape(ts)} · SearchMarket v2
</footer>
</body>
</html>
"""
