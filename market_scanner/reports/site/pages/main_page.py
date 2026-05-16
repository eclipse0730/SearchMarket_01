"""메인 페이지 렌더링.

매크로 지표(금리·환율·변동성·크립토)와 글로벌 지수·원자재 틱커를 표시한다.
시장/종목 섹션은 overview_page 로 분리됐다.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from html import escape

from market_scanner.reports.site import layout
from market_scanner.reports.site.data import DailyMacroItem, MacroPriceSeries, MacroQuote, MainPageData


# display_symbol → CSS border-color (차트 라인 색상)
_SERIES_COLORS: dict[str, str] = {
    # 글로벌 지수 — 미국 파랑, 유럽 초록, 아시아 노랑/오렌지/빨강
    "DJI":      "#4f9dde",
    "GSPC":     "#62c7ff",
    "IXIC":     "#00bfff",
    "NDX":      "#1fa8f0",
    "RUT":      "#87ceeb",
    "VIX":      "#ff69b4",
    "FTSE":     "#32cd32",
    "GDAXI":    "#00e676",
    "FCHI":     "#66bb6a",
    "STOXX50E": "#26a69a",
    "N225":     "#ffd740",
    "KS11":     "#ff8f00",
    "KQ11":     "#ffab40",
    "HSI":      "#ef5350",
    "SSE":      "#e53935",
    "CSI300":   "#ff7043",
    "TWII":     "#ab47bc",
    "BSESN":    "#ec407a",
    "NSEI":     "#ba68c8",
    "AXJO":     "#26c6da",
    "BVSP":     "#a1887f",
    "STI":      "#78909c",
    # 원자재 — 귀금속 금/은, 에너지 빨강, 농산물 초록/갈색
    "GC":       "#ffd700",
    "SI":       "#c0c0c0",
    "PL":       "#e0dcc8",
    "PA":       "#a4b8c4",
    "CL":       "#c62828",
    "BZ":       "#b71c1c",
    "NG":       "#ff6d00",
    "HG":       "#b87333",
    "ALI":      "#90a4ae",
    "ZC":       "#c8e6c9",
    "ZS":       "#8bc34a",
    "ZW":       "#f4a460",
    "KC":       "#8d6e63",
    "SB":       "#ffe0b2",
    # 섹터 ETF — 사용자 요청 색상 참고
    "XLRE":     "#ef5350",  # 리츠 — 빨강
    "VNQ":      "#e53935",  # 리츠 보조 — 진빨강
    "XLB":      "#ff8f00",  # 소재 — 주황
    "XLE":      "#c62828",  # 에너지 — 진빨강
    "XLF":      "#ffd740",  # 금융 — 금색
    "XLK":      "#4f9dde",  # 기술 — 파랑
    "XLV":      "#32cd32",  # 헬스케어 — 초록
    "XLY":      "#ff6d00",  # 경기소비재 — 주황
    "XLP":      "#66bb6a",  # 필수소비재 — 연초록
    "XLI":      "#87ceeb",  # 산업재 — 하늘색
    "XLU":      "#9370db",  # 유틸리티 — 보라
    "XLC":      "#26c6da",  # 통신 — 청록
}


# indicator_code → (표시명, 소수점 자리수, 단위 suffix)
_MACRO_META: dict[str, tuple[str, int, str]] = {
    # 금리
    "SOFR":               ("SOFR",          2, "%"),
    "US_FFR":             ("Fed Fund Rate",  2, "%"),
    "US_2Y":              ("미국 2년금리",   2, "%"),
    "US_10Y":             ("미국 10년금리",  2, "%"),
    "US_30Y":             ("미국 30년금리",  2, "%"),
    "US_SPREAD_2S10S":    ("2s10s 스프레드", 2, "%"),
    "US_SPREAD_3M10Y":    ("3M10Y 스프레드", 2, "%"),
    # 신용 스프레드
    "HY_OAS":             ("HY OAS",        2, "bp"),
    "IG_OAS":             ("IG OAS",        2, "bp"),
    # 유동성
    "FED_RRP":            ("Fed RRP",       0, "B$"),
    "FED_BS":             ("Fed B/S",       0, "M$"),
    # 환율
    "USDKRW":             ("USD/KRW",       2, ""),
    "USDKRW_FRED":        ("USD/KRW (FRED)",2, ""),
    "EURUSD":             ("EUR/USD",       4, ""),
    "USDJPY":             ("USD/JPY",       2, ""),
    "USDCNY":             ("USD/CNY",       4, ""),
    "DXY":                ("달러인덱스",    2, ""),
    # 변동성·심리
    "VIX":                ("VIX",           2, ""),
    "VVIX":               ("VVIX",          2, ""),
    # 크립토
    "BTC_USD":            ("BTC",           0, "$"),
    "ETH_USD":            ("ETH",           0, "$"),
    "CRYPTO_TOTAL_MCAP":  ("크립토 총 시총",0, "$"),
    "CRYPTO_FNG":         ("공포·탐욕",     0, ""),
}

# 표시 그룹 순서
_GROUPS: list[tuple[str, list[str]]] = [
    ("금리", ["SOFR", "US_FFR", "US_2Y", "US_10Y", "US_30Y"]),
    ("스프레드", ["US_SPREAD_2S10S", "US_SPREAD_3M10Y", "HY_OAS", "IG_OAS"]),
    ("유동성", ["FED_RRP", "FED_BS"]),
    ("환율", ["USDKRW", "EURUSD", "USDJPY", "USDCNY", "DXY"]),
    ("변동성·심리", ["VIX", "VVIX"]),
    ("크립토", ["BTC_USD", "ETH_USD", "CRYPTO_TOTAL_MCAP", "CRYPTO_FNG"]),
]


def _fmt_macro_value(item: DailyMacroItem) -> str:
    meta = _MACRO_META.get(item.indicator_code)
    if meta is None:
        return f"{item.value:,.2f}"
    _, decimals, suffix = meta
    val_str = f"{item.value:,.{decimals}f}"
    return f"{val_str} {suffix}".strip() if suffix else val_str


def _daily_macro_section(items: list[DailyMacroItem]) -> str:
    if not items:
        return ""
    by_code = {it.indicator_code: it for it in items}

    groups_html: list[str] = []
    for group_label, codes in _GROUPS:
        cells: list[str] = []
        for code in codes:
            item = by_code.get(code)
            if item is None:
                continue
            meta = _MACRO_META.get(code)
            display_name = meta[0] if meta else code
            chg_class = layout.change_class(item.change_pct)
            val_str = _fmt_macro_value(item)
            chg_str = layout.fmt_pct(item.change_pct) if item.change_pct is not None else "—"
            cells.append(f"""<div class="macro-cell">
  <div class="sym">{escape(code)}</div>
  <div class="name" title="{escape(display_name)}">{escape(display_name)}</div>
  <div class="px">{escape(val_str)}</div>
  <div class="chg {chg_class}">{escape(chg_str)}</div>
</div>""")
        if not cells:
            continue
        groups_html.append(
            f'<div class="sector-group">'
            f'<div class="gname">{escape(group_label)}</div>'
            f'<div class="macro-grid">{"".join(cells)}</div>'
            f'</div>'
        )

    if not groups_html:
        return ""
    return f"""
<section class="block">
  <h2>매크로 지표</h2>
  <div class="sub">금리·환율·변동성·크립토 등 최신 거래일 값. 전일 대비 등락률.</div>
  {''.join(groups_html)}
</section>"""


def _macro_chart_html(series_list: list[MacroPriceSeries]) -> str:
    """글로벌 지수 · 원자재 · 섹터 ETF 시계열 Chart.js 라인 차트."""
    if not series_list:
        return ""

    _TAB_LABELS = {
        "global-indices": "글로벌 지수",
        "commodities": "원자재",
        "sector-etfs": "섹터 ETF",
    }
    _TAB_ORDER = ["global-indices", "sector-etfs", "commodities"]

    # 그룹별로 날짜(공통 x축)와 datasets 구성
    by_market: dict[str, list[MacroPriceSeries]] = defaultdict(list)
    for s in series_list:
        by_market[s.market_key].append(s)

    groups_data: dict[str, dict] = {}
    for market_key, group in by_market.items():
        all_dates = sorted({d for s in group for d in s.dates})
        datasets = []
        for s in group:
            date_to_val = dict(zip(s.dates, s.values))
            color = _SERIES_COLORS.get(s.display_symbol, "#62c7ff")
            datasets.append({
                "label": s.display_symbol,
                "data": [date_to_val.get(d) for d in all_dates],
                "borderColor": color,
                "backgroundColor": color + "1a",
                "pointRadius": 0,
                "borderWidth": 1.5,
                "tension": 0.2,
                "spanGaps": True,
            })
        groups_data[market_key] = {"dates": all_dates, "datasets": datasets}

    tab_order = [k for k in _TAB_ORDER if k in groups_data]
    if not tab_order:
        return ""

    first_tab = tab_order[0]
    tabs_html = "".join(
        f'<button class="ct-tab{" ct-tab-active" if k == first_tab else ""}" data-group="{escape(k)}">'
        f'{escape(_TAB_LABELS.get(k, k))}</button>'
        for k in tab_order
    )
    groups_json = json.dumps(groups_data, ensure_ascii=False)
    first_tab_js = json.dumps(first_tab)

    return f"""<div class="macro-chart-wrap">
  <div class="chart-tabs">{tabs_html}</div>
  <div class="chart-canvas-wrap"><canvas id="macro-line-chart"></canvas></div>
  <div class="chart-legend" id="macro-chart-legend"></div>
</div>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>
<script>
(function(){{
  const GROUPS={groups_json};
  let chart=null;
  function build(gk){{
    const g=GROUPS[gk]; if(!g) return;
    const ctx=document.getElementById('macro-line-chart').getContext('2d');
    if(chart) chart.destroy();
    chart=new Chart(ctx,{{
      type:'line',
      data:{{labels:g.dates,datasets:g.datasets}},
      options:{{
        responsive:true,maintainAspectRatio:false,
        interaction:{{mode:'index',intersect:false}},
        plugins:{{
          legend:{{display:false}},
          tooltip:{{
            backgroundColor:'rgba(8,19,33,.95)',
            borderColor:'rgba(148,163,184,.18)',borderWidth:1,
            titleColor:'#e6edf3',bodyColor:'#8fa3ba',padding:10,
            callbacks:{{
              label:function(c){{
                const v=c.parsed.y;
                if(v==null) return ' '+c.dataset.label+': —';
                const p=(v-100).toFixed(1);
                return ' '+c.dataset.label+': '+(p>=0?'+':'')+p+'%';
              }}
            }}
          }}
        }},
        scales:{{
          x:{{ticks:{{color:'#8fa3ba',maxTicksLimit:8,maxRotation:0}},grid:{{color:'rgba(148,163,184,.08)'}}}},
          y:{{
            ticks:{{color:'#8fa3ba',callback:function(v){{
              const p=(v-100).toFixed(0);return(p>=0?'+':'')+p+'%';
            }}}},
            grid:{{color:'rgba(148,163,184,.08)'}},
          }}
        }}
      }}
    }});
    const leg=document.getElementById('macro-chart-legend');
    leg.innerHTML=g.datasets.map(function(ds,i){{
      return '<span class="cl-item" data-idx="'+i+'" style="border-color:'+ds.borderColor+'">'+ds.label+'</span>';
    }}).join('');
    leg.querySelectorAll('.cl-item').forEach(function(el){{
      el.addEventListener('click',function(){{
        const idx=+el.dataset.idx;
        const m=chart.getDatasetMeta(idx);
        m.hidden=!m.hidden;
        el.classList.toggle('cl-hidden',m.hidden);
        chart.update();
      }});
    }});
  }}
  document.querySelectorAll('.ct-tab').forEach(function(btn){{
    btn.addEventListener('click',function(){{
      document.querySelectorAll('.ct-tab').forEach(function(b){{b.classList.remove('ct-tab-active');}});
      btn.classList.add('ct-tab-active');
      build(btn.dataset.group);
    }});
  }});
  build({first_tab_js});
}})();
</script>"""


def _macro_panel_section(quotes: list[MacroQuote], series_list: list[MacroPriceSeries]) -> str:
    if not quotes:
        return ""
    by_market: dict[str, list[MacroQuote]] = {}
    for q in quotes:
        by_market.setdefault(q.market_key, []).append(q)

    market_labels = {
        "global-indices": "글로벌 지수",
        "sector-etfs": "섹터 ETF",
        "commodities": "원자재",
    }

    groups_html: list[str] = []
    for market_key, items in by_market.items():
        cells = "\n".join(
            f"""<div class="macro-cell">
  <div class="sym">{escape(q.display_symbol)}</div>
  <div class="name" title="{escape(q.name_local or q.symbol)}">{escape(q.name_local or q.symbol)}</div>
  <div class="px">{layout.fmt_price(q.close_price)}</div>
  <div class="chg {layout.change_class(q.change_pct)}">{layout.fmt_pct(q.change_pct)}</div>
</div>"""
            for q in items
        )
        label = market_labels.get(market_key, market_key)
        groups_html.append(
            f'<div class="sector-group"><div class="gname">{escape(label)}</div>'
            f'<div class="macro-grid">{cells}</div></div>'
        )

    chart_html = _macro_chart_html(series_list)
    return f"""
<section class="block">
  <h2>글로벌 지수 · 원자재</h2>
  <div class="sub">시계열 차트: 기간 내 첫 거래일 종가 기준 상대 수익률. 범례 클릭으로 개별 라인 토글.</div>
  {chart_html}
  {''.join(groups_html)}
</section>"""


def render(data: MainPageData) -> str:
    body = "".join(
        section for section in (
            _daily_macro_section(data.daily_macro_items),
            _macro_panel_section(data.macro_quotes, data.macro_price_series),
        ) if section
    )
    if not body:
        body = (
            '<section class="block"><h2>데이터 없음</h2>'
            '<div class="sub">daily_macro / daily_prices 가 비어 있습니다. '
            '<code>Search.py macro</code> 와 <code>Search.py price global-indices</code> 를 먼저 실행하세요.</div></section>'
        )
    return layout.render_page(
        title="메인",
        depth=0,
        body_html=body,
        nav_active="home",
        generated_at=datetime.combine(data.generated_at, datetime.min.time()),
    )
