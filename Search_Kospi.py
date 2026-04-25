#!/usr/bin/env python3
"""
Search_Kospi.py — 코스피 이동평균선 근접 종목 스캐너
코스피 주요 종목을 대상으로 60 / 120 / 240일 이동평균선 근접 종목을 스캔합니다.
"""

import os, sys, time, io, argparse
from datetime import datetime

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf-8-sig"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd
import yfinance as yf

# ═══════════════════════════════════════════════════════════
# 설정
# ═══════════════════════════════════════════════════════════

THRESHOLD_PCT = 2.0
MA_PERIODS    = [60, 120, 240]
PREFIX        = "Kospi"   # 출력 파일명 prefix

# ═══════════════════════════════════════════════════════════
# 섹터 영문 → 한국어 (yfinance sector 필드)
# ═══════════════════════════════════════════════════════════

SECTOR_KO = {
    "Financial Services":       "금융 서비스",
    "Healthcare":               "헬스케어",
    "Technology":               "기술",
    "Consumer Cyclical":        "경기 소비재",
    "Consumer Defensive":       "필수 소비재",
    "Industrials":              "산업재",
    "Communication Services":   "커뮤니케이션 서비스",
    "Real Estate":              "부동산·리츠",
    "Utilities":                "유틸리티",
    "Energy":                   "에너지",
    "Basic Materials":          "원자재",
}

# ═══════════════════════════════════════════════════════════
# 주요 코스피 종목 정보
# (티커: (영문명, 한국명, 섹터KR, 설명))
# ═══════════════════════════════════════════════════════════

TICKER_INFO: dict[str, tuple[str, str, str, str]] = {
    # ── 삼성 계열 ──────────────────────────────────────────
    "005930.KS": ("Samsung Electronics",          "삼성전자",       "반도체·전자",      "메모리·시스템반도체·스마트폰·가전"),
    "006400.KS": ("Samsung SDI",                  "삼성SDI",        "배터리",           "전기차 배터리·ESS"),
    "009150.KS": ("Samsung Electro-Mechanics",    "삼성전기",       "전자부품",         "MLCC·카메라모듈·반도체 패키지기판"),
    "018260.KS": ("Samsung SDS",                  "삼성SDS",        "IT서비스",         "삼성그룹 IT서비스·물류 BPO"),
    "028260.KS": ("Samsung C&T",                  "삼성물산",       "지주·건설",        "삼성그룹 지주 역할, 건설·상사"),
    "032830.KS": ("Samsung Life Insurance",        "삼성생명",       "보험",             "국내 1위 생명보험"),
    "000810.KS": ("Samsung Fire & Marine",         "삼성화재",       "보험",             "국내 1위 손해보험"),
    "010140.KS": ("Samsung Heavy Industries",      "삼성중공업",     "조선",             "삼성 계열 조선사"),

    # ── SK 계열 ────────────────────────────────────────────
    "000660.KS": ("SK Hynix",                     "SK하이닉스",     "반도체",           "D램·낸드플래시 메모리 세계 2위"),
    "096770.KS": ("SK Innovation",                "SK이노베이션",   "에너지·화학",      "정유·화학·배터리 소재"),
    "034730.KS": ("SK Inc.",                       "SK",             "지주사",           "SK그룹 지주, ICT·에너지·바이오"),
    "017670.KS": ("SK Telecom",                   "SK텔레콤",       "통신",             "국내 1위 이동통신"),
    # "003600.KS": SK케미칼 — yfinance 데이터 없음 (상장폐지/재편)

    # ── LG 계열 ────────────────────────────────────────────
    "051910.KS": ("LG Chem",                      "LG화학",         "화학·배터리",      "배터리 분사 후 석유화학·첨단소재"),
    "373220.KS": ("LG Energy Solution",            "LG에너지솔루션", "배터리",           "전기차 배터리 세계 2위"),
    "066570.KS": ("LG Electronics",               "LG전자",         "전자·가전",        "가전·TV·차량부품·B2B"),
    "003550.KS": ("LG Corporation",               "LG",             "지주사",           "LG그룹 지주회사"),
    "032640.KS": ("LG Uplus",                     "LG유플러스",     "통신",             "이동통신·초고속인터넷·IPTV"),

    # ── 현대차 계열 ────────────────────────────────────────
    "005380.KS": ("Hyundai Motor",                "현대자동차",     "자동차",           "국내 1위 완성차, 전기차 전환 중"),
    "000270.KS": ("Kia Corporation",              "기아",           "자동차",           "현대차 계열 완성차, 글로벌 디자인"),
    "012330.KS": ("Hyundai Mobis",                "현대모비스",     "자동차부품",       "현대·기아 핵심 부품 계열사"),
    "001450.KS": ("Hyundai Marine & Fire",         "현대해상",       "보험",             "현대차 계열 손해보험"),

    # ── 바이오·제약 ────────────────────────────────────────
    "068270.KS": ("Celltrion",                    "셀트리온",       "바이오",           "항체 바이오시밀러 세계 1위"),
    "207940.KS": ("Samsung Biologics",            "삼성바이오로직스","바이오·CMO",      "글로벌 바이오 CDMO"),
    "000100.KS": ("Yuhan Corporation",            "유한양행",       "제약",             "국내 대형 제약사, 레이저티닙 개발"),
    "128940.KS": ("Hanmi Pharmaceutical",         "한미약품",       "제약",             "국내 제약 R&D 선도, 신약 수출"),
    "006280.KS": ("Green Cross Holdings",          "GC녹십자",       "제약·혈액제제",    "혈액제제 1위, 백신"),

    # ── IT·인터넷·플랫폼 ───────────────────────────────────
    "035420.KS": ("NAVER Corporation",            "NAVER",          "인터넷·플랫폼",    "국내 1위 검색 포털·클라우드"),
    "035720.KS": ("Kakao Corp.",                  "카카오",         "인터넷·플랫폼",    "카카오톡 기반 플랫폼·핀테크"),

    # ── 게임 ───────────────────────────────────────────────
    "036570.KS": ("NCsoft Corporation",           "엔씨소프트",     "게임",             "리니지·블레이드&소울 MMORPG"),
    "251270.KS": ("Netmarble",                    "넷마블",         "게임",             "모바일 게임 글로벌 퍼블리셔"),
    "293490.KS": ("Krafton",                      "크래프톤",       "게임",             "배틀그라운드(PUBG) 개발사"),

    # ── 엔터테인먼트 ───────────────────────────────────────
    "352820.KS": ("HYBE Co.",                     "하이브",         "엔터테인먼트",     "BTS 소속 K-POP 최대 기획사"),
    "041510.KS": ("SM Entertainment",             "SM엔터테인먼트", "엔터테인먼트",     "EXO·aespa K-POP 기획사"),
    "035900.KS": ("JYP Entertainment",            "JYP엔터테인먼트","엔터테인먼트",     "TWICE·Stray Kids K-POP 기획사"),
    "122870.KS": ("YG Entertainment",             "YG엔터테인먼트", "엔터테인먼트",     "BLACKPINK·BIGBANG K-POP 기획사"),

    # ── 금융 ───────────────────────────────────────────────
    "055550.KS": ("Shinhan Financial Group",      "신한지주",       "금융지주",         "신한은행 계열 종합금융그룹"),
    "105560.KS": ("KB Financial Group",           "KB금융",         "금융지주",         "국민은행 계열 종합금융그룹"),
    "086790.KS": ("Hana Financial Group",         "하나금융지주",   "금융지주",         "하나은행 계열 종합금융그룹"),
    "316140.KS": ("Woori Financial Group",        "우리금융지주",   "금융지주",         "우리은행 계열 종합금융그룹"),
    "024110.KS": ("Industrial Bank of Korea",     "기업은행",       "은행",             "중소기업 전문 국책은행"),
    "016360.KS": ("Samsung Securities",           "삼성증권",       "증권",             "삼성그룹 계열 대형 증권사"),
    "006800.KS": ("Mirae Asset Securities",       "미래에셋증권",   "증권",             "국내 1위 증권사, 해외 진출"),
    "047050.KS": ("Korea Investment Holdings",    "한국금융지주",   "금융지주",         "한국투자증권 계열 금융지주"),

    # ── 철강·소재 ──────────────────────────────────────────
    "005490.KS": ("POSCO Holdings",               "POSCO홀딩스",    "철강·소재",        "국내 1위 철강, 이차전지 소재"),
    "004020.KS": ("Hyundai Steel",                "현대제철",       "철강",             "현대차 계열 철강, 전기로·고로"),
    "010130.KS": ("Korea Zinc",                   "고려아연",       "비철금속",         "아연 세계 1위 제련·이차전지 소재"),

    # ── 화학 ───────────────────────────────────────────────
    "011170.KS": ("Lotte Chemical",               "롯데케미칼",     "화학",             "기초화학·첨단소재"),
    "011780.KS": ("Kumho Petrochem",              "금호석유",       "화학",             "합성고무·합성수지 전문"),

    # ── 조선 ───────────────────────────────────────────────
    "042660.KS": ("Hanwha Ocean",                 "한화오션",       "조선",             "전 대우조선해양, 잠수함·LNG선"),
    "009540.KS": ("HD Hyundai Heavy Industries",  "HD현대중공업",   "조선",             "세계 1위 조선사 계열"),

    # ── 건설 ───────────────────────────────────────────────
    "000720.KS": ("Hyundai E&C",                  "현대건설",       "건설",             "국내 1위 건설사"),
    "006360.KS": ("GS Engineering & Construction","GS건설",         "건설",             "GS그룹 건설 계열사"),

    # ── 방산 ───────────────────────────────────────────────
    "047810.KS": ("Korea Aerospace Industries",   "한국항공우주",   "항공우주·방산",    "국산 전투기(KF-21)·헬기 제조"),
    "079550.KS": ("LIG Nex1",                     "LIG넥스원",      "방산",             "미사일·레이더 방산 전문"),
    "272210.KS": ("Hanwha Systems",               "한화시스템",     "방산·IT",          "방산 전자·ICT 서비스"),
    "000150.KS": ("Doosan Corporation",           "두산",           "지주·방산",        "두산그룹 지주, 로봇·방산"),
    "034020.KS": ("Doosan Enerbility",            "두산에너빌리티", "에너지기계",       "원자력·가스터빈 발전설비"),

    # ── 통신 ───────────────────────────────────────────────
    "030200.KS": ("KT Corporation",               "KT",             "통신",             "유선·무선통신, IPTV, 클라우드"),

    # ── 정유·에너지 ────────────────────────────────────────
    "010950.KS": ("S-Oil",                        "S-Oil",          "정유",             "국내 3위 정유, 아람코 계열"),

    # ── 유틸리티 ───────────────────────────────────────────
    "015760.KS": ("Korea Electric Power (KEPCO)", "한국전력",       "유틸리티",         "국내 전력 공급 독점 공기업"),

    # ── 유통·소비재 ────────────────────────────────────────
    "139480.KS": ("E-MART",                       "이마트",         "유통",             "국내 1위 할인마트"),
    "001040.KS": ("CJ Corporation",               "CJ",             "지주사",           "식품·물류·바이오·엔터 지주"),
    "097950.KS": ("CJ CheilJedang",               "CJ제일제당",     "식품·바이오",      "식품 1위·바이오 아미노산 세계 1위"),
    "000080.KS": ("Hite Jinro",                   "하이트진로",     "식품·음료",        "소주 1위(참이슬)·맥주(테라)"),
    "021240.KS": ("Coway",                        "코웨이",         "가전·렌탈",        "정수기·공기청정기 렌탈 1위"),
    "033780.KS": ("KT&G",                         "KT&G",           "담배·건강기능식품","국내 1위 담배, 인삼공사 계열"),
    "007070.KS": ("GS Retail",                    "GS리테일",       "유통",             "GS25 편의점·홈쇼핑"),
    "282330.KS": ("BGF Retail",                   "BGF리테일",      "유통",             "CU 편의점 운영"),

    # ── 항공·해운·물류 ─────────────────────────────────────
    "003490.KS": ("Korean Air Lines",             "대한항공",       "항공",             "국내 1위 항공사, 아시아나 합병"),
    "011200.KS": ("HMM",                          "HMM",            "해운",             "국내 1위 컨테이너 해운"),
    "011040.KS": ("CJ Logistics",                 "CJ대한통운",     "물류",             "국내 1위 택배·물류"),

    # ── 타이어·자동차부품 ──────────────────────────────────
    "161390.KS": ("Hankook Tire & Tech",          "한국타이어앤테크놀로지","타이어",    "국내 1위 타이어 제조"),

    # ── 한화 계열 ──────────────────────────────────────────
    "088350.KS": ("Hanwha Life Insurance",        "한화생명",       "보험",             "한화그룹 생명보험 계열사"),
}

KOSPI_TICKERS = list(dict.fromkeys(TICKER_INFO.keys()))


# ═══════════════════════════════════════════════════════════
# KRX 동적 로드 (코스피200 구성종목)
# ═══════════════════════════════════════════════════════════

def load_krx_kospi200() -> list[str]:
    """KRX에서 코스피200 구성종목 로드 (실패시 빈 리스트 반환)"""
    import requests
    try:
        url = "https://www.krx.co.kr/comm/bldAttendant/getJsonData.cmd"
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; stock-scanner/1.0)",
            "Referer":    "https://www.krx.co.kr/",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        payload = {
            "bld":              "dbms/MDC/STAT/standard/MDCSTAT00601",
            "mktId":            "STK",
            "idxIndMidclssCd":  "02",        # 코스피200
            "trdDd":            datetime.today().strftime("%Y%m%d"),
            "money":            "1",
            "csvxls_isNo":      "false",
        }
        resp = requests.post(url, headers=headers, data=payload, timeout=15)
        rows = resp.json().get("OutBlock_1", [])
        tickers = []
        for row in rows:
            code = row.get("ISU_SRT_CD", "").strip()
            if code and len(code) == 6 and code.isdigit():
                tickers.append(code + ".KS")
        if tickers:
            print(f"  KRX 코스피200 로드: {len(tickers)}개 종목")
            return tickers
    except Exception as e:
        print(f"  KRX 로드 실패 ({type(e).__name__}) - 정적 리스트 사용")
    return []


def build_all_tickers() -> list[str]:
    """정적 TICKER_INFO + KRX 동적 로드, 중복 제거"""
    static = list(TICKER_INFO.keys())
    dynamic = load_krx_kospi200()
    all_t = list(dict.fromkeys(static + dynamic))
    print(f"  스캔 대상: 총 {len(all_t)}개 종목 (정적 {len(static)} + 추가 {len(all_t) - len(static)})")
    return all_t


# ═══════════════════════════════════════════════════════════
# 보조 계산 함수
# ═══════════════════════════════════════════════════════════

def calc_rsi(close: pd.Series, period: int = 14) -> float | None:
    if len(close) < period + 1:
        return None
    delta = close.diff().dropna()
    gain  = delta.clip(lower=0)
    loss  = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean().iloc[-1]
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean().iloc[-1]
    if avg_loss == 0:
        return 100.0
    return round(100 - 100 / (1 + avg_gain / avg_loss), 1)


def fetch_ticker_data(ticker: str) -> dict | None:
    try:
        t    = yf.Ticker(ticker)
        hist = t.history(period="2y")
        if hist.empty or len(hist) < max(MA_PERIODS) + 10:
            return None
        close = hist["Close"]
        price = round(float(close.iloc[-1]))

        # 이동평균
        ma_vals = {}
        for p in MA_PERIODS:
            if len(close) >= p:
                ma_vals[p] = round(float(close.rolling(p).mean().iloc[-1]))

        if not ma_vals:
            return None

        # 근접 여부
        ma_diff  = {p: round((price - v) / v * 100, 2) for p, v in ma_vals.items()}
        ma_close = {p: "O" if abs(d) <= THRESHOLD_PCT else "" for p, d in ma_diff.items()}

        # 종목 정보
        if ticker in TICKER_INFO:
            en_name, kr_name, sector_kr, desc = TICKER_INFO[ticker]
        else:
            info    = t.info
            en_name = info.get("longName") or info.get("shortName") or ticker
            kr_name = en_name[:20]
            sector_en = info.get("sector", "")
            sector_kr = SECTOR_KO.get(sector_en, sector_en or "-")
            desc    = (info.get("longBusinessSummary") or "")[:80]

        # 보조지표
        try:
            info = t.info
        except Exception:
            info = {}

        rsi      = calc_rsi(close)
        high_52  = round(float(close.tail(252).max()))
        low_52   = round(float(close.tail(252).min()))
        from_high = round((price - high_52) / high_52 * 100, 1) if high_52 else None

        vol_today = float(hist["Volume"].iloc[-1])
        vol_avg20 = float(hist["Volume"].tail(20).mean())
        vol_ratio = round(vol_today / vol_avg20, 2) if vol_avg20 else None

        per        = info.get("trailingPE")
        target_raw = info.get("targetMeanPrice")
        target     = round(float(target_raw)) if target_raw else None
        upside     = round((target - price) / price * 100, 1) if target and price else None

        row: dict = {
            "티커":    ticker.replace(".KS", ""),
            "영문명":  en_name[:25],
            "한국명":  kr_name,
            "테마/섹터": sector_kr,
            "설명":    desc,
            "현재가(₩)": price,
            "RSI(14)": rsi,
            "52주고가(₩)": high_52,
            "52주저가(₩)": low_52,
            "52주고점대비(%)": from_high,
            "거래량비율(전일/20일평균)": vol_ratio,
            "PER(후행)": round(float(per), 1) if per else None,
            "목표주가(₩)": target,
            "업사이드(%)": upside,
        }
        for p in MA_PERIODS:
            row[f"MA{p}(₩)"]   = ma_vals.get(p)
            row[f"MA{p}차이(%)"] = ma_diff.get(p)
            row[f"MA{p}근접"]   = ma_close.get(p, "")

        # 추세 판단 (0–5점)
        ts = 0
        if price > ma_vals.get(60, price):               ts += 1
        if ma_vals.get(60, 0) > ma_vals.get(120, 0) > 0: ts += 1
        if ma_vals.get(120, 0) > ma_vals.get(240, 0) > 0: ts += 1
        for win in [60, 120]:
            ma_s = close.rolling(win).mean().dropna()
            if len(ma_s) >= 21 and float(ma_s.iloc[-1]) > float(ma_s.iloc[-21]):
                ts += 1
        trend_map = {5: "강상승", 4: "상승", 3: "중립", 2: "하락", 1: "강하락", 0: "강하락"}
        row["추세"]    = trend_map[min(ts, 5)]
        row["추세점수"] = ts

        return row

    except Exception:
        return None


# ═══════════════════════════════════════════════════════════
# 채점 & 분석 헬퍼
# ═══════════════════════════════════════════════════════════

def _score_row(r: pd.Series) -> float:
    ma_cols = [f"MA{p}근접" for p in MA_PERIODS]
    conv = sum(1 for c in ma_cols if str(r.get(c, "")) == "O")
    score = conv * 12

    rsi = r.get("RSI(14)")
    if rsi is not None:
        if rsi < 35:
            score += 15
        elif rsi < 45:
            score += 10
        elif rsi < 55:
            score += 5

    upside = r.get("업사이드(%)")
    if upside is not None:
        if upside >= 20:
            score += 20
        elif upside >= 12:
            score += 12
        elif upside >= 6:
            score += 6

    per = r.get("PER(후행)")
    if per is not None and 0 < per < 15:
        score += 8

    for p in MA_PERIODS:
        d = r.get(f"MA{p}차이(%)")
        if d is not None and str(r.get(f"MA{p}근접", "")) == "O":
            score += max(0, THRESHOLD_PCT - abs(d))

    return round(score, 2)


def _ma_tag(r: pd.Series) -> str:
    parts = []
    for p in MA_PERIODS:
        d = r.get(f"MA{p}차이(%)")
        if d is not None and str(r.get(f"MA{p}근접", "")) == "O":
            parts.append(f"MA{p} {'+' if d >= 0 else ''}{d:.1f}%")
    return " / ".join(parts) if parts else "-"


def _rsi_label(rsi) -> str:
    if rsi is None:
        return "-"
    if rsi < 30:
        return "과매도"
    if rsi < 40:
        return "약세"
    if rsi < 60:
        return "중립"
    if rsi < 70:
        return "강세"
    return "과매열"


def _table_header() -> tuple[str, str]:
    return (
        "| 티커 | 종목명 | 추세 | 현재가(₩) | RSI | 52주고점% | 업사이드% | PER | MA 위치 |",
        "|---|---|:---:|---:|---:|---:|---:|---:|---|",
    )


def _table_row(r: pd.Series) -> str:
    ticker  = r.get("티커", "")
    name    = r.get("한국명", "")[:14]
    trend   = r.get("추세", "-")
    price   = r.get("현재가(₩)")
    rsi     = r.get("RSI(14)")
    fhigh   = r.get("52주고점대비(%)")
    upside  = r.get("업사이드(%)")
    per     = r.get("PER(후행)")

    trend_icon = {"강상승": "↑↑", "상승": "↑", "중립": "→", "하락": "↓", "강하락": "↓↓"}.get(str(trend), "-")

    def fmt_i(v, suffix=""):
        return f"{int(v):,}{suffix}" if v is not None else "-"
    def fmt_f(v, suffix=""):
        return f"{v:+.1f}{suffix}" if v is not None else "-"
    def fmt_per(v):
        return f"{v:.1f}" if v is not None else "-"

    return (
        f"| {ticker:<6} | {name:<14} | {trend_icon} {trend} "
        f"| ₩{fmt_i(price)} "
        f"| {int(rsi) if rsi is not None else '-':>4} "
        f"| {fmt_f(fhigh, '%'):>7} "
        f"| {fmt_f(upside, '%'):>8} "
        f"| {fmt_per(per):>6} "
        f"| {_ma_tag(r)} |"
    )


# ═══════════════════════════════════════════════════════════
# 1단계: 스캔
# ═══════════════════════════════════════════════════════════

def stage1_scan(today: str) -> tuple[list[dict], pd.DataFrame, str]:
    csv_path = f"Data_{PREFIX}_{today}.csv"
    print(f"\n  [1단계] 코스피 종목 스캔 시작: {today}")
    print("=" * 90)

    tickers = build_all_tickers()
    total   = len(tickers)
    results = []

    for i, ticker in enumerate(tickers, 1):
        row = fetch_ticker_data(ticker)
        if row:
            results.append(row)
        pct = len(results)
        print(f"  진행: {i}/{total}  근접 {pct}개\r", end="")
        time.sleep(0.05)

    print()

    if not results:
        print("  결과 없음.")
        return [], pd.DataFrame(), csv_path

    df = pd.DataFrame(results)
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")

    ma_near_counts = {p: int(df[f"MA{p}근접"].eq("O").sum()) for p in MA_PERIODS}
    print(f"\n  스캔 완료: {len(df)}개 종목")
    for p, cnt in ma_near_counts.items():
        print(f"    MA{p} 근접: {cnt}개")
    print(f"  저장: {csv_path}")
    return results, df, csv_path


# ═══════════════════════════════════════════════════════════
# 2단계: 분석 리포트 생성
# ═══════════════════════════════════════════════════════════

def stage2_analysis(df: pd.DataFrame, today: str) -> str:
    md_path = f"Analysis_{PREFIX}_{today}.md"
    print(f"\n  [2단계] 분석 리포트 생성: {md_path}")

    df = df.copy()
    df["_score"] = df.apply(_score_row, axis=1)

    ma_cols    = [f"MA{p}근접" for p in MA_PERIODS]
    near_any   = df[df[ma_cols].eq("O").any(axis=1)]
    near_multi = df[df[ma_cols].eq("O").sum(axis=1) >= 2]

    md: list[str] = []

    def add(*lines: str):
        if not lines:
            md.append("")
        else:
            md.extend(lines)

    date_str = f"{today[:4]}-{today[4:6]}-{today[6:]}"
    add(f"# 코스피 이동평균선 근접 종목 분석 리포트")
    add(f"**기준일:** {date_str}  ")
    add(f"**스캔 유니버스:** 코스피 주요 종목 (총 {len(df)}개)  ")
    add(f"**기준:** {' / '.join(str(p) for p in MA_PERIODS)}일 이동평균선 ±{THRESHOLD_PCT}% 이내")
    add("", "---", "")

    # 요약
    add("## 요약", "")
    add("| 구분 | 종목 수 |", "|---|---:|")
    for p in MA_PERIODS:
        cnt = int(df[f"MA{p}근접"].eq("O").sum())
        add(f"| {p}일선 근접 | **{cnt}개** |")
    add(f"| 2개 이상 이평선 동시 근접 | **{len(near_multi)}개** |")
    add("", "---", "")

    # 1. 핵심 추천
    add("## 1. 핵심 추천 종목 (종합 점수 상위)", "")
    add("> 복수 이평선 수렴 · RSI · 업사이드 · PER을 종합 채점한 결과입니다.", "")
    top10 = near_any.nlargest(10, "_score")
    add(*_table_header())
    for _, r in top10.iterrows():
        add(_table_row(r))
    add("")
    for _, r in top10.iterrows():
        add(f"- **{r['티커']} {r['한국명']}** — {_ma_tag(r)} / RSI {r['RSI(14)']} ({_rsi_label(r['RSI(14)'])}) / 업사이드 {r['업사이드(%)']:+.1f}%" if r['업사이드(%)'] is not None else f"- **{r['티커']} {r['한국명']}** — {_ma_tag(r)} / RSI {r['RSI(14)']}")
    add("", "---", "")

    # 2. 테마별 분석
    add("## 2. 테마별 분석", "")

    # A. 역발상
    oversold = near_any[near_any["RSI(14)"].notna() & (near_any["RSI(14)"] < 40)].nlargest(10, "업사이드(%)")
    if not oversold.empty:
        add("### A. 역발상 매수 — RSI 과매도 + 이평선 지지", "")
        add("> RSI 40 미만인데 이동평균선 위에서 지지 받는 종목. 단기 반등 가능성.", "")
        add(*_table_header())
        for _, r in oversold.iterrows():
            add(_table_row(r))
        add("")

    # B. 이평선 수렴
    add("### B. 이평선 수렴 — 2개 이상 MA 동시 근접", "")
    add("> 단기·중기·장기 이평선이 한 가격대에 겹치는 구간. 방향 돌파 시 강한 추세.", "")
    add(*_table_header())
    for _, r in near_multi.nlargest(10, "_score").iterrows():
        add(_table_row(r))
    add("")

    # C. 성장주 (업사이드 20%+)
    growth = near_any[near_any["업사이드(%)"].notna() & (near_any["업사이드(%)"] >= 20)].nlargest(10, "업사이드(%)")
    if not growth.empty:
        add("### C. 성장주 — 애널리스트 업사이드 20%+ + MA 근접", "")
        add("> 기관 컨센서스 목표가 대비 현재가 괴리가 큰 종목.", "")
        add(*_table_header())
        for _, r in growth.iterrows():
            add(_table_row(r))
        add("")

    # D. 가치주 (PER ≤ 15)
    value = near_any[near_any["PER(후행)"].notna() & (near_any["PER(후행)"] > 0) & (near_any["PER(후행)"] <= 15)].nlargest(10, "_score")
    if not value.empty:
        add("### D. 가치주 — PER 15 이하 + MA 근접", "")
        add("> 실적 대비 주가가 낮은 종목이 이평선 지지 구간에 위치.", "")
        add(*_table_header())
        for _, r in value.iterrows():
            add(_table_row(r))
        add("")

    add("---", "")

    # 3. 섹터 분석
    add("## 3. 섹터 분석", "")
    sector_cnt = near_any["테마/섹터"].value_counts()
    add("| 섹터 | 근접 종목 수 | 비중 |", "|---|---:|---:|")
    for sec, cnt in sector_cnt.items():
        pct = cnt / len(near_any) * 100 if len(near_any) > 0 else 0
        add(f"| {sec} | {cnt}개 | {pct:.1f}% |")
    add("")
    if not sector_cnt.empty:
        top_sec = sector_cnt.index[0]
        add(f"> **{top_sec}** 섹터가 {sector_cnt.iloc[0]}개로 가장 많이 집중.")
    add("", "---", "")

    # 4. 주의 종목
    add("## 4. 주의 종목 — RSI 과열 (70+) + MA 저항", "")
    add("> RSI 70 이상인데 이평선 근처에 위치 = 저항선에서 눌릴 가능성. 신규 매수 주의.", "")
    overbought = near_any[near_any["RSI(14)"].notna() & (near_any["RSI(14)"] >= 70)]
    if overbought.empty:
        add("> 현재 해당 종목 없음.")
    else:
        add(*_table_header())
        for _, r in overbought.iterrows():
            add(_table_row(r))
    add("", "---", "")

    # 5. 전체 목록
    for p in MA_PERIODS:
        near_p = df[df[f"MA{p}근접"].eq("O")].sort_values(f"MA{p}차이(%)", key=abs)
        add(f"## 5-{MA_PERIODS.index(p)+1}. MA{p} 근접 전체 목록 ({len(near_p)}개)", "")
        if not near_p.empty:
            add(*_table_header())
            for _, r in near_p.iterrows():
                add(_table_row(r))
        add("")

    md_text = "\n".join(md)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_text)

    print(f"  [2단계 완료] {md_path} 생성 완료")
    return md_path


# ═══════════════════════════════════════════════════════════
# 4단계: HTML 인터랙티브 대시보드
# ═══════════════════════════════════════════════════════════

def stage4_html(df: pd.DataFrame, today: str) -> str:
    import json

    html_path = f"Report_{PREFIX}_{today}.html"
    print(f"\n  [4단계] HTML 대시보드 생성: {html_path}")

    ma_cols_present = [c for c in [f"MA{p}근접" for p in MA_PERIODS] if c in df.columns]
    near_counts = {p: int(df[f"MA{p}근접"].eq("O").sum()) if f"MA{p}근접" in df.columns else 0
                   for p in MA_PERIODS}
    multi_mask    = df[ma_cols_present].eq("O").sum(axis=1) >= 2 if ma_cols_present else pd.Series(False, index=df.index)
    near_any_mask = df[ma_cols_present].eq("O").any(axis=1)      if ma_cols_present else pd.Series(False, index=df.index)
    near_multi = int(multi_mask.sum())
    total = len(df)

    near_df = df[near_any_mask] if near_any_mask.any() else df
    sector_counts = near_df["테마/섹터"].value_counts().head(12) if "테마/섹터" in df.columns else pd.Series(dtype=int)
    sector_labels_json = json.dumps(sector_counts.index.tolist(), ensure_ascii=False)
    sector_values_json = json.dumps([int(v) for v in sector_counts.values])

    rsi_bin_edges  = [0, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 101]
    rsi_bin_labels = ["<20","20-25","25-30","30-35","35-40","40-45","45-50","50-55","55-60","60-65","65-70","70-75","75-80","80+"]
    rsi_series = df["RSI(14)"].dropna() if "RSI(14)" in df.columns else pd.Series(dtype=float)
    rsi_counts_vals = [int(((rsi_series >= lo) & (rsi_series < hi)).sum())
                       for lo, hi in zip(rsi_bin_edges[:-1], rsi_bin_edges[1:])]
    rsi_labels_json = json.dumps(rsi_bin_labels)
    rsi_values_json = json.dumps(rsi_counts_vals)

    def safe(v, default=None):
        if v is None:
            return default
        try:
            if pd.isna(v):
                return default
        except Exception:
            pass
        return v

    records = []
    for _, r in df.iterrows():
        records.append({
            "ticker":   str(safe(r.get("티커"), "")),
            "kr_name":  str(safe(r.get("한국명"), "")),
            "en_name":  str(safe(r.get("영문명"), "")),
            "sector":   str(safe(r.get("테마/섹터"), "")),
            "desc":     str(safe(r.get("설명"), "")),
            "price":    safe(r.get("현재가(₩)")),
            "rsi":      safe(r.get("RSI(14)")),
            "fromHigh": safe(r.get("52주고점대비(%)")),
            "volRatio": safe(r.get("거래량비율(전일/20일평균)")),
            "per":      safe(r.get("PER(후행)")),
            "upside":   safe(r.get("업사이드(%)")),
            "diff60":   safe(r.get("MA60차이(%)")),
            "diff120":  safe(r.get("MA120차이(%)")),
            "diff240":  safe(r.get("MA240차이(%)")),
            "near60":     str(safe(r.get("MA60근접"),  "")) == "O",
            "near120":    str(safe(r.get("MA120근접"), "")) == "O",
            "near240":    str(safe(r.get("MA240근접"), "")) == "O",
            "trend":      str(safe(r.get("추세"),   "")),
            "trendScore": safe(r.get("추세점수")),
        })

    data_json    = json.dumps(records, ensure_ascii=False)
    date_str     = f"{today[:4]}-{today[4:6]}-{today[6:]}"

    analysis_path = f"Analysis_{PREFIX}_{today}.md"
    analysis_md   = ""
    if os.path.exists(analysis_path):
        with open(analysis_path, encoding="utf-8") as f:
            analysis_md = f.read()
    analysis_json = json.dumps(analysis_md, ensure_ascii=False)

    near60_s  = str(near_counts.get(60,  0))
    near120_s = str(near_counts.get(120, 0))
    near240_s = str(near_counts.get(240, 0))

    template = (
        '<!DOCTYPE html>\n'
        '<html lang="ko">\n'
        '<head>\n'
        '<meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        '<title>코스피 MA Scanner — ###DATE###</title>\n'
        '<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">\n'
        '<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>\n'
        '<script src="https://cdn.jsdelivr.net/npm/marked@9.1.6/marked.min.js"></script>\n'
        '<style>\n'
        'body{background:#0d1117;color:#c9d1d9;font-family:"Segoe UI",sans-serif}\n'
        '.card{background:#161b22;border:1px solid #30363d}\n'
        '.card-footer{background:#21262d;border-color:#30363d}\n'
        '.nav-tabs .nav-link{color:#8b949e;border-color:transparent}\n'
        '.nav-tabs .nav-link.active{background:#21262d;color:#58a6ff;border-color:#30363d #30363d #21262d}\n'
        'table{border-collapse:collapse;width:100%}\n'
        'td,th{border:1px solid #30363d;padding:5px 8px;font-size:.8rem;white-space:nowrap}\n'
        'tbody td{color:#ffffff}\n'
        'thead th{background:#21262d;color:#8b949e;cursor:pointer;user-select:none}\n'
        'thead th:hover{color:#58a6ff}\n'
        'tbody tr:hover{background:#1c2128}\n'
        '.rsi-green{color:#3fb950;font-weight:700}\n'
        '.rsi-red{color:#f85149;font-weight:700}\n'
        '.up-green{color:#3fb950}\n'
        '.up-red{color:#f85149}\n'
        '.per-green{color:#3fb950}\n'
        '.per-red{color:#f85149}\n'
        '.ma-warn{color:#e3b341}\n'
        '.ticker-link{color:#58a6ff;text-decoration:none;font-weight:700}\n'
        '.ticker-link:hover{text-decoration:underline}\n'
        '.stat-card h2{font-size:2rem;font-weight:700;margin:0}\n'
        '.th-sorted{color:#58a6ff}\n'
        'input[type=text],select{background:#21262d;border:1px solid #30363d;color:#c9d1d9;padding:5px 10px;border-radius:4px}\n'
        'input[type=text]:focus,select:focus{outline:none;border-color:#58a6ff}\n'
        '.md-content{color:#c9d1d9}\n'
        '.md-content h1{color:#e6edf3;font-size:1.3rem;border-bottom:1px solid #30363d;padding-bottom:.4rem;margin:1.4rem 0 .8rem}\n'
        '.md-content h2{color:#58a6ff;font-size:1.1rem;border-bottom:1px solid #30363d;padding-bottom:.3rem;margin:1.8rem 0 .7rem;scroll-margin-top:10px}\n'
        '.md-content h3{color:#e3b341;font-size:.95rem;margin:1.2rem 0 .5rem}\n'
        '.md-content table{width:100%;border-collapse:collapse;margin:.6rem 0;font-size:.8rem}\n'
        '.md-content table th{background:#21262d;color:#8b949e;padding:5px 8px;border:1px solid #30363d}\n'
        '.md-content table td{padding:5px 8px;border:1px solid #30363d;color:#ffffff}\n'
        '.md-content table tr:hover{background:#1c2128}\n'
        '.md-content blockquote{border-left:3px solid #58a6ff;background:#1c2128;margin:.6rem 0;padding:.5rem 1rem;border-radius:0 4px 4px 0}\n'
        '.md-content blockquote p{margin:0;color:#8b949e;font-size:.85rem}\n'
        '.md-content hr{border-color:#30363d;margin:1.2rem 0}\n'
        '.md-content p,.md-content li{color:#c9d1d9;margin:.3rem 0}\n'
        '.md-content strong{color:#e6edf3}\n'
        '.report-nav-btn{display:inline-block;padding:4px 12px;margin:0 4px 6px 0;border:1px solid #30363d;border-radius:4px;font-size:.8rem;text-decoration:none}\n'
        '.report-nav-btn:hover{border-color:#58a6ff;color:#58a6ff}\n'
        '.report-nav-btn.top{color:#58a6ff;border-color:#58a6ff}\n'
        '.report-nav-btn.theme{color:#e3b341;border-color:#e3b341}\n'
        '.report-nav-btn.sector{color:#3fb950;border-color:#3fb950}\n'
        '.report-nav-btn.warn{color:#f85149;border-color:#f85149}\n'
        '</style>\n'
        '</head>\n'
        '<body>\n'
        '<div class="container-fluid py-3">\n'
        '<div class="d-flex align-items-baseline mb-3 gap-3">\n'
        '  <h4 class="mb-0 text-white">\U0001f4c8 코스피 MA Scanner</h4>\n'
        '  <small class="text-secondary">###DATE### &nbsp;|&nbsp; ###TOTAL### 종목 스캔</small>\n'
        '</div>\n'
        '<div class="row g-2 mb-3">\n'
        '  <div class="col-6 col-md-3"><div class="card text-center p-3 stat-card">\n'
        '    <div class="text-secondary small">MA60 근접</div><h2 class="text-info">###NEAR60###</h2><div class="text-secondary small">±2% 이내</div>\n'
        '  </div></div>\n'
        '  <div class="col-6 col-md-3"><div class="card text-center p-3 stat-card">\n'
        '    <div class="text-secondary small">MA120 근접</div><h2 class="text-warning">###NEAR120###</h2><div class="text-secondary small">±2% 이내</div>\n'
        '  </div></div>\n'
        '  <div class="col-6 col-md-3"><div class="card text-center p-3 stat-card">\n'
        '    <div class="text-secondary small">MA240 근접</div><h2 class="text-danger">###NEAR240###</h2><div class="text-secondary small">±2% 이내</div>\n'
        '  </div></div>\n'
        '  <div class="col-6 col-md-3"><div class="card text-center p-3 stat-card">\n'
        '    <div class="text-secondary small">복수 MA 수렴</div><h2 class="text-success">###NEAR_MULTI###</h2><div class="text-secondary small">2개 이상</div>\n'
        '  </div></div>\n'
        '</div>\n'
        '<div class="row g-2 mb-3">\n'
        '  <div class="col-md-7"><div class="card p-3" style="height:230px">\n'
        '    <div class="text-secondary small mb-1">섹터별 근접 종목 분포</div>\n'
        '    <canvas id="sectorChart"></canvas>\n'
        '  </div></div>\n'
        '  <div class="col-md-5"><div class="card p-3" style="height:230px">\n'
        '    <div class="text-secondary small mb-1">RSI 분포</div>\n'
        '    <canvas id="rsiChart"></canvas>\n'
        '  </div></div>\n'
        '</div>\n'
        '<div id="filterBar" class="d-flex gap-2 mb-2 flex-wrap align-items-center">\n'
        '  <input type="text" id="searchBox" placeholder="티커/종목명 검색..." style="width:190px" oninput="applyFilter()">\n'
        '  <select id="sectorFilter" onchange="applyFilter()"><option value="">전체 섹터</option></select>\n'
        '  <select id="rsiFilter" onchange="applyFilter()">\n'
        '    <option value="">전체 RSI</option>\n'
        '    <option value="low">RSI &lt; 35 (과매도)</option>\n'
        '    <option value="high">RSI &gt; 65 (과매열)</option>\n'
        '    <option value="mid">35 ≤ RSI ≤ 65 (중립)</option>\n'
        '  </select>\n'
        '  <select id="trendFilter" onchange="applyFilter()">\n'
        '    <option value="">전체 추세</option>\n'
        '    <option value="강상승">↑↑ 강상승</option>\n'
        '    <option value="상승">↑ 상승</option>\n'
        '    <option value="중립">→ 중립</option>\n'
        '    <option value="하락">↓ 하락</option>\n'
        '    <option value="강하락">↓↓ 강하락</option>\n'
        '  </select>\n'
        '  <span class="text-secondary small ms-auto" id="rowCount"></span>\n'
        '</div>\n'
        '<ul class="nav nav-tabs mb-0" id="mainTabs">\n'
        '  <li class="nav-item"><a class="nav-link active" href="#" data-tab="all">전체</a></li>\n'
        '  <li class="nav-item"><a class="nav-link" href="#" data-tab="ma60">MA60</a></li>\n'
        '  <li class="nav-item"><a class="nav-link" href="#" data-tab="ma120">MA120</a></li>\n'
        '  <li class="nav-item"><a class="nav-link" href="#" data-tab="ma240">MA240</a></li>\n'
        '  <li class="nav-item"><a class="nav-link" href="#" data-tab="multi">복수MA</a></li>\n'
        '  <li class="nav-item ms-auto"><a class="nav-link" href="#" data-tab="report" style="color:#e3b341">\U0001f4ca 분석 리포트</a></li>\n'
        '</ul>\n'
        '<div id="tableSection">\n'
        '<div class="card" style="border-top-left-radius:0">\n'
        '  <div class="p-0" style="overflow-x:auto">\n'
        '    <table id="mainTable">\n'
        '      <thead><tr>\n'
        '        <th data-col="ticker">티커</th>\n'
        '        <th data-col="kr_name">종목명</th>\n'
        '        <th data-col="sector">섹터</th>\n'
        '        <th data-col="trendScore">추세</th>\n'
        '        <th data-col="price">현재가(₩)</th>\n'
        '        <th data-col="rsi">RSI</th>\n'
        '        <th data-col="fromHigh">52주고점대비</th>\n'
        '        <th data-col="volRatio">거래량비율</th>\n'
        '        <th data-col="per">PER</th>\n'
        '        <th data-col="upside">업사이드</th>\n'
        '        <th data-col="diff60">MA60차이%</th>\n'
        '        <th data-col="diff120">MA120차이%</th>\n'
        '        <th data-col="diff240">MA240차이%</th>\n'
        '        <th>근접</th>\n'
        '      </tr></thead>\n'
        '      <tbody id="tableBody"></tbody>\n'
        '    </table>\n'
        '  </div>\n'
        '  <div class="card-footer text-secondary small py-1" id="rowCount2"></div>\n'
        '</div>\n'
        '</div>\n'
        '<div id="reportSection" style="display:none">\n'
        '  <div class="mb-3">\n'
        '    <a class="report-nav-btn top" href="#sec-top">⭐ 핵심 추천</a>\n'
        '    <a class="report-nav-btn theme" href="#sec-theme">\U0001f50d 테마별 분석</a>\n'
        '    <a class="report-nav-btn sector" href="#sec-sector">\U0001f4ca 섹터 분석</a>\n'
        '    <a class="report-nav-btn warn" href="#sec-warn">⚠️ 주의 종목</a>\n'
        '  </div>\n'
        '  <div id="mdContent" class="md-content"></div>\n'
        '</div>\n'
        '</div>\n'
        '<script>\n'
        'const DATA=###DATA_JSON###;\n'
        'const SECTOR_LABELS=###SECTOR_LABELS###;\n'
        'const SECTOR_VALUES=###SECTOR_VALUES###;\n'
        'const RSI_LABELS=###RSI_LABELS###;\n'
        'const RSI_VALUES=###RSI_VALUES###;\n'
        'const ANALYSIS_MD=###ANALYSIS_JSON###;\n'
        'let currentTab="all",sortCol="ticker",sortAsc=true,reportRendered=false;\n'
        'const sectorSet=[...new Set(DATA.map(d=>d.sector).filter(Boolean))].sort();\n'
        'const sf=document.getElementById("sectorFilter");\n'
        'sectorSet.forEach(s=>{const o=document.createElement("option");o.value=s;o.textContent=s;sf.appendChild(o);});\n'
        'new Chart(document.getElementById("sectorChart"),{\n'
        '  type:"bar",data:{labels:SECTOR_LABELS,datasets:[{data:SECTOR_VALUES,backgroundColor:"#58a6ff66",borderColor:"#58a6ff",borderWidth:1}]},\n'
        '  options:{indexAxis:"y",plugins:{legend:{display:false}},scales:{x:{ticks:{color:"#8b949e"},grid:{color:"#30363d"}},y:{ticks:{color:"#c9d1d9",font:{size:10}},grid:{color:"#30363d"}}},maintainAspectRatio:false}\n'
        '});\n'
        'const rsiColors=RSI_LABELS.map((_,i)=>i<=3?"#3fb95066":i>=10?"#f8514966":"#58a6ff66");\n'
        'new Chart(document.getElementById("rsiChart"),{\n'
        '  type:"bar",data:{labels:RSI_LABELS,datasets:[{data:RSI_VALUES,backgroundColor:rsiColors,borderColor:rsiColors.map(c=>c.replace("66","ff")),borderWidth:1}]},\n'
        '  options:{plugins:{legend:{display:false}},scales:{x:{ticks:{color:"#8b949e",font:{size:9}},grid:{color:"#30363d"}},y:{ticks:{color:"#8b949e"},grid:{color:"#30363d"}}},maintainAspectRatio:false}\n'
        '});\n'
        'document.getElementById("mainTabs").addEventListener("click",e=>{\n'
        '  const a=e.target.closest("a[data-tab]");if(!a)return;e.preventDefault();\n'
        '  document.querySelectorAll("#mainTabs .nav-link").forEach(l=>l.classList.remove("active"));\n'
        '  a.classList.add("active");currentTab=a.dataset.tab;\n'
        '  const isReport=(currentTab==="report");\n'
        '  document.getElementById("filterBar").style.display=isReport?"none":"";\n'
        '  document.getElementById("tableSection").style.display=isReport?"none":"";\n'
        '  document.getElementById("reportSection").style.display=isReport?"":"none";\n'
        '  if(isReport)renderReport();else applyFilter();\n'
        '});\n'
        'function renderReport(){\n'
        '  if(reportRendered)return;reportRendered=true;\n'
        '  const el=document.getElementById("mdContent");\n'
        '  if(!ANALYSIS_MD){el.innerHTML=\'<p class="text-secondary py-3">분석 파일이 없습니다.</p>\';return;}\n'
        '  el.innerHTML=marked.parse(ANALYSIS_MD);\n'
        '  el.querySelectorAll("h2").forEach(h=>{\n'
        '    const t=h.textContent;\n'
        '    if(t.includes("핵심"))h.id="sec-top";\n'
        '    else if(t.includes("테마"))h.id="sec-theme";\n'
        '    else if(t.includes("섹터"))h.id="sec-sector";\n'
        '    else if(t.includes("주의"))h.id="sec-warn";\n'
        '  });\n'
        '}\n'
        'document.getElementById("mainTable").querySelector("thead").addEventListener("click",e=>{\n'
        '  const th=e.target.closest("th[data-col]");if(!th)return;\n'
        '  const col=th.dataset.col;\n'
        '  if(sortCol===col)sortAsc=!sortAsc;else{sortCol=col;sortAsc=true;}\n'
        '  document.querySelectorAll("thead th").forEach(t=>t.classList.remove("th-sorted"));\n'
        '  th.classList.add("th-sorted");renderFilter();\n'
        '});\n'
        'function fmt(v,dec=0,suf=""){if(v==null)return"-";return Number(v).toFixed(dec).replace(/\\B(?=(\\d{3})+(?!\\d))/g,",")+suf;}\n'
        'function trendCell(t){\n'
        '  const icons={"강상승":"↑↑","상승":"↑","중립":"→","하락":"↓","강하락":"↓↓"};\n'
        '  const colors={"강상승":"#3fb950","상승":"#7ee787","중립":"#e3b341","하락":"#ffa198","강하락":"#f85149"};\n'
        '  if(!t)return"-";\n'
        '  return `<span style="color:${colors[t]||"#c9d1d9"};font-weight:700">${icons[t]||""} ${t}</span>`;\n'
        '}\n'
        'function rsiCell(v){if(v==null)return"-";const n=+v,c=n<35?"rsi-green":n>65?"rsi-red":"";return `<span class="${c}">${n.toFixed(1)}</span>`;}\n'
        'function upCell(v){if(v==null)return"-";const n=+v,c=n>=20?"up-green":n<0?"up-red":"";return `<span class="${c}">${n.toFixed(1)}%</span>`;}\n'
        'function perCell(v){if(v==null)return"-";const n=+v,c=n<15?"per-green":n>40?"per-red":"";return `<span class="${c}">${n.toFixed(1)}</span>`;}\n'
        'function diffCell(v){if(v==null)return"-";const n=+v,c=Math.abs(n)<=2?"ma-warn":"";return `<span class="${c}">${n>=0?"+":""}${n.toFixed(2)}%</span>`;}\n'
        'function badges(d){let b="";if(d.near60)b+=\'<span class="badge bg-info text-dark me-1" style="font-size:.65rem">60</span>\';if(d.near120)b+=\'<span class="badge bg-warning text-dark me-1" style="font-size:.65rem">120</span>\';if(d.near240)b+=\'<span class="badge bg-danger me-1" style="font-size:.65rem">240</span>\';return b||"-";}\n'
        'function applyFilter(){renderFilter();}\n'
        'function renderFilter(){\n'
        '  const search=document.getElementById("searchBox").value.toLowerCase();\n'
        '  const sector=document.getElementById("sectorFilter").value;\n'
        '  const rsiF=document.getElementById("rsiFilter").value;\n'
        '  let rows=DATA.filter(d=>{\n'
        '    if(currentTab==="ma60"&&!d.near60)return false;\n'
        '    if(currentTab==="ma120"&&!d.near120)return false;\n'
        '    if(currentTab==="ma240"&&!d.near240)return false;\n'
        '    if(currentTab==="multi"&&(d.near60+d.near120+d.near240)<2)return false;\n'
        '    if(search&&!(d.ticker.toLowerCase().includes(search)||d.kr_name.toLowerCase().includes(search)))return false;\n'
        '    if(sector&&d.sector!==sector)return false;\n'
        '    if(rsiF==="low"&&!(d.rsi!=null&&d.rsi<35))return false;\n'
        '    if(rsiF==="high"&&!(d.rsi!=null&&d.rsi>65))return false;\n'
        '    if(rsiF==="mid"&&!(d.rsi!=null&&d.rsi>=35&&d.rsi<=65))return false;\n'
        '    const tf=document.getElementById("trendFilter").value;\n'
        '    if(tf&&d.trend!==tf)return false;\n'
        '    return true;\n'
        '  });\n'
        '  rows.sort((a,b)=>{\n'
        '    let va=a[sortCol],vb=b[sortCol];\n'
        '    if(va==null)va=sortAsc?Infinity:-Infinity;\n'
        '    if(vb==null)vb=sortAsc?Infinity:-Infinity;\n'
        '    if(typeof va==="string")return sortAsc?va.localeCompare(vb,"ko"):vb.localeCompare(va,"ko");\n'
        '    return sortAsc?va-vb:vb-va;\n'
        '  });\n'
        '  document.getElementById("tableBody").innerHTML=rows.map(d=>`\n'
        '    <tr>\n'
        '      <td><a href="https://finance.naver.com/item/main.naver?code=${d.ticker}" target="_blank" class="ticker-link">${d.ticker}</a></td>\n'
        '      <td title="${d.en_name}&#10;${d.desc}">${d.kr_name}</td>\n'
        '      <td>${d.sector||"-"}</td>\n'
        '      <td>${trendCell(d.trend)}</td>\n'
        '      <td>₩${fmt(d.price,0)}</td>\n'
        '      <td>${rsiCell(d.rsi)}</td>\n'
        '      <td>${fmt(d.fromHigh,1,"%")}</td>\n'
        '      <td>${fmt(d.volRatio,2,"x")}</td>\n'
        '      <td>${perCell(d.per)}</td>\n'
        '      <td>${upCell(d.upside)}</td>\n'
        '      <td>${diffCell(d.diff60)}</td>\n'
        '      <td>${diffCell(d.diff120)}</td>\n'
        '      <td>${diffCell(d.diff240)}</td>\n'
        '      <td>${badges(d)}</td>\n'
        '    </tr>`).join("");\n'
        '  const msg=`${rows.length}개 표시 / 전체 ${DATA.length}개`;\n'
        '  document.getElementById("rowCount").textContent=msg;\n'
        '  document.getElementById("rowCount2").textContent=msg;\n'
        '}\n'
        'renderFilter();\n'
        '</script>\n'
        '</body>\n'
        '</html>\n'
    )

    html = template
    html = html.replace("###DATE###",          date_str)
    html = html.replace("###TOTAL###",         str(total))
    html = html.replace("###NEAR60###",        near60_s)
    html = html.replace("###NEAR120###",       near120_s)
    html = html.replace("###NEAR240###",       near240_s)
    html = html.replace("###NEAR_MULTI###",    str(near_multi))
    html = html.replace("###DATA_JSON###",     data_json)
    html = html.replace("###SECTOR_LABELS###", sector_labels_json)
    html = html.replace("###SECTOR_VALUES###", sector_values_json)
    html = html.replace("###RSI_LABELS###",    rsi_labels_json)
    html = html.replace("###RSI_VALUES###",    rsi_values_json)
    html = html.replace("###ANALYSIS_JSON###", analysis_json)

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"  [4단계 완료] {html_path} 생성 완료")
    return html_path


# ═══════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="코스피 이동평균선 근접 종목 스캐너")
    parser.add_argument("--stage", type=int, choices=[1, 2, 4],
                        help="특정 단계만 실행 (기본: 전체 / 3단계 없음)")
    parser.add_argument("--date",  default=datetime.today().strftime("%Y%m%d"),
                        help="대상 날짜 YYYYMMDD (기본: 오늘)")
    parser.add_argument("--force", action="store_true",
                        help="기존 CSV가 있어도 1단계 재실행")
    args = parser.parse_args()

    today    = args.date
    csv_path = f"Data_{PREFIX}_{today}.csv"
    run_all  = args.stage is None
    df       = None

    print("=" * 90)
    print(f"  코스피 MA Scanner  |  기준일: {today}  |  임계값: ±{THRESHOLD_PCT}%")
    print("=" * 90)

    if run_all or args.stage == 1:
        if os.path.exists(csv_path) and not args.force:
            print(f"  기존 파일 사용: {csv_path}  (재스캔: --force)")
            df = pd.read_csv(csv_path, encoding="utf-8-sig")
        else:
            _, df, csv_path = stage1_scan(today)
            if df is None or df.empty:
                return

    if run_all or args.stage == 2:
        if df is None:
            if not os.path.exists(csv_path):
                print(f"  오류: {csv_path} 없음. 먼저 1단계를 실행하세요.")
                return
            df = pd.read_csv(csv_path, encoding="utf-8-sig")
        stage2_analysis(df, today)

    if run_all or args.stage == 4:
        if df is None:
            if not os.path.exists(csv_path):
                print(f"  오류: {csv_path} 없음. 먼저 1단계를 실행하세요.")
                return
            df = pd.read_csv(csv_path, encoding="utf-8-sig")
        stage4_html(df, today)

    print(f"\n  완료. 출력 파일: Data_{PREFIX}_{today}.csv  |  Analysis_{PREFIX}_{today}.md  |  Report_{PREFIX}_{today}.html")
    print("=" * 90)


if __name__ == "__main__":
    main()
