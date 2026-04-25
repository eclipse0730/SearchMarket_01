"""
Search60.py — S&P 500 + NASDAQ 100 이동평균선 근접 종목 스캐너

사용법:
  python Search60.py                   # 전체 실행 (1→2→3단계)
  python Search60.py --stage 1         # 스캔 및 CSV 저장만
  python Search60.py --stage 2         # 분석 리포트 생성만
  python Search60.py --stage 3         # 번역 저장만
  python Search60.py --date 20260424   # 특정 날짜 파일 대상
  python Search60.py --setup-scheduler # Windows 작업 스케줄러 등록
"""

import sys, io, os, time, argparse
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

try:
    from deep_translator import GoogleTranslator as _GT
    _HAS_TRANSLATOR = True
except ImportError:
    _HAS_TRANSLATOR = False

# ── 설정 ─────────────────────────────────────────────────────
THRESHOLD_PCT = 2.0
MA_PERIODS    = [60, 120, 240]

SECTOR_KO = {
    "Financial Services":     "금융 서비스",
    "Healthcare":             "헬스케어",
    "Technology":             "기술",
    "Consumer Cyclical":      "경기 소비재",
    "Consumer Defensive":     "필수 소비재",
    "Industrials":            "산업재",
    "Communication Services": "커뮤니케이션 서비스",
    "Real Estate":            "부동산·리츠",
    "Utilities":              "유틸리티",
    "Energy":                 "에너지",
    "Basic Materials":        "원자재",
}

# ── NASDAQ 100 메타데이터 ─────────────────────────────────────
TICKER_INFO: dict[str, tuple[str, str, str, str]] = {
    "AAPL":  ("Apple Inc.",                    "애플",               "소비자 전자기기",      "아이폰·맥·서비스 생태계"),
    "MSFT":  ("Microsoft Corp.",               "마이크로소프트",      "소프트웨어·클라우드",  "윈도우·Azure·Office 365"),
    "NVDA":  ("NVIDIA Corp.",                  "엔비디아",           "반도체·AI",           "GPU·데이터센터·AI 가속기"),
    "AMZN":  ("Amazon.com Inc.",               "아마존",             "이커머스·클라우드",    "온라인 쇼핑·AWS 클라우드"),
    "META":  ("Meta Platforms Inc.",           "메타 플랫폼스",      "소셜 미디어",         "페이스북·인스타그램·왓츠앱"),
    "GOOGL": ("Alphabet Inc. (A)",             "알파벳(구글) A",     "인터넷·광고",         "구글 검색·YouTube·GCP"),
    "GOOG":  ("Alphabet Inc. (C)",             "알파벳(구글) C",     "인터넷·광고",         "구글 검색·YouTube·GCP"),
    "TSLA":  ("Tesla Inc.",                    "테슬라",             "전기차·에너지",        "전기차·에너지 저장·자율주행"),
    "AVGO":  ("Broadcom Inc.",                 "브로드컴",           "반도체",              "네트워크·스토리지·AI 맞춤칩"),
    "COST":  ("Costco Wholesale Corp.",        "코스트코",           "유통·소매",           "창고형 멤버십 할인마트"),
    "NFLX":  ("Netflix Inc.",                  "넷플릭스",           "스트리밍·미디어",      "글로벌 OTT 동영상 스트리밍"),
    "ASML":  ("ASML Holding NV",               "ASML",              "반도체 장비",         "EUV 노광 장비 독점 공급"),
    "AMD":   ("Advanced Micro Devices",        "AMD",               "반도체",              "CPU·GPU·AI 가속기"),
    "PEP":   ("PepsiCo Inc.",                  "펩시코",             "식음료",              "펩시·게토레이·프리토레이 스낵"),
    "LIN":   ("Linde plc",                     "린데",               "산업용 가스",         "산소·질소·수소 등 산업 가스"),
    "QCOM":  ("Qualcomm Inc.",                 "퀄컴",               "반도체·통신",         "모바일 AP·5G 모뎀 칩"),
    "ADBE":  ("Adobe Inc.",                    "어도비",             "소프트웨어",           "포토샵·Acrobat·Creative Cloud"),
    "INTU":  ("Intuit Inc.",                   "인튜이트",           "금융 소프트웨어",      "TurboTax·QuickBooks·Mint"),
    "AMAT":  ("Applied Materials Inc.",        "어플라이드 머티리얼즈", "반도체 장비",        "반도체 식각·증착 장비"),
    "TXN":   ("Texas Instruments Inc.",        "텍사스 인스트루먼츠", "반도체",              "아날로그·임베디드 반도체"),
    "MU":    ("Micron Technology Inc.",        "마이크론 테크놀로지", "반도체·메모리",        "DRAM·NAND 플래시 메모리"),
    "ISRG":  ("Intuitive Surgical Inc.",       "인튜이티브 서지컬",  "의료기기",             "다빈치 수술 로봇 시스템"),
    "BKNG":  ("Booking Holdings Inc.",         "부킹 홀딩스",        "여행·OTA",            "부킹닷컴·프라이스라인·카약"),
    "LRCX":  ("Lam Research Corp.",            "램 리서치",          "반도체 장비",         "반도체 식각·증착 장비"),
    "SBUX":  ("Starbucks Corp.",               "스타벅스",           "외식·음료",           "글로벌 커피 프랜차이즈"),
    "ADP":   ("Automatic Data Processing",     "ADP",               "HR·급여 소프트웨어",   "기업 급여·인사 아웃소싱"),
    "ADI":   ("Analog Devices Inc.",           "아날로그 디바이시스", "반도체",              "아날로그·혼성신호 반도체"),
    "GILD":  ("Gilead Sciences Inc.",          "길리어드 사이언시스", "바이오·제약",          "HIV·간염·항암제"),
    "VRTX":  ("Vertex Pharmaceuticals",        "버텍스 파마슈티컬스", "바이오·제약",          "낭성섬유증 치료제"),
    "MDLZ":  ("Mondelez International",        "몬델리즈",           "식품",                "오레오·리츠·토블레로네"),
    "REGN":  ("Regeneron Pharmaceuticals",     "리제네론",           "바이오·제약",          "아일리아·두필루맙 항체 치료제"),
    "PANW":  ("Palo Alto Networks Inc.",       "팔로 알토 네트웍스", "사이버보안",            "차세대 방화벽·클라우드 보안"),
    "SNPS":  ("Synopsys Inc.",                 "시놉시스",           "EDA 소프트웨어",       "반도체 설계 자동화(EDA) 툴"),
    "CDNS":  ("Cadence Design Systems",        "캐던스 디자인",      "EDA 소프트웨어",        "반도체 설계 자동화(EDA) 툴"),
    "KLAC":  ("KLA Corporation",               "KLA",               "반도체 장비",          "반도체 공정 검사·계측 장비"),
    "CSX":   ("CSX Corporation",               "CSX",               "철도·물류",            "미국 동부 화물 철도 운영"),
    "MELI":  ("MercadoLibre Inc.",             "메르카도리브레",     "이커머스·핀테크",        "중남미 최대 전자상거래·결제"),
    "PYPL":  ("PayPal Holdings Inc.",          "페이팔",             "핀테크·결제",          "온라인 결제·Venmo"),
    "ABNB":  ("Airbnb Inc.",                   "에어비앤비",         "여행·숙박 플랫폼",      "글로벌 숙박 공유 플랫폼"),
    "CRWD":  ("CrowdStrike Holdings Inc.",     "크라우드스트라이크",  "사이버보안",            "클라우드 기반 엔드포인트 보안"),
    "MRVL":  ("Marvell Technology Inc.",       "마벨 테크놀로지",    "반도체",               "데이터센터·5G 반도체"),
    "ORLY":  ("O'Reilly Automotive Inc.",      "오라일리 오토모티브", "자동차 부품 소매",     "자동차 부품·액세서리 소매"),
    "MAR":   ("Marriott International",        "매리어트 인터내셔널", "호텔·숙박",            "글로벌 호텔 체인"),
    "FTNT":  ("Fortinet Inc.",                 "포티넷",             "사이버보안",           "FortiGate 네트워크 보안"),
    "MNST":  ("Monster Beverage Corp.",        "몬스터 비버리지",    "음료",                 "에너지 음료 브랜드"),
    "PCAR":  ("PACCAR Inc.",                   "PACCAR",            "상용차·트럭",           "Kenworth·Peterbilt 트럭"),
    "KDP":   ("Keurig Dr Pepper Inc.",         "큐리그 닥터페퍼",   "음료",                  "커피 캡슐·닥터페퍼 음료"),
    "CEG":   ("Constellation Energy Corp.",    "컨스텔레이션 에너지", "원자력·전력",          "미국 최대 원자력 발전 운영"),
    "CTAS":  ("Cintas Corporation",            "신타스",             "기업 서비스",          "유니폼 렌탈·시설 관리"),
    "ROST":  ("Ross Stores Inc.",              "로스 스토어스",      "유통·소매",            "오프프라이스 의류·생활용품"),
    "CHTR":  ("Charter Communications",        "차터 커뮤니케이션스", "통신·케이블",          "케이블 TV·인터넷 서비스"),
    "DXCM":  ("DexCom Inc.",                   "덱스컴",             "의료기기",             "연속혈당측정기(CGM) 시스템"),
    "WDAY":  ("Workday Inc.",                  "워크데이",           "기업용 소프트웨어",     "클라우드 HR·재무 관리"),
    "ODFL":  ("Old Dominion Freight Line",     "올드 도미니언 프레이트", "물류·운송",         "미국 LTL 화물 운송"),
    "AEP":   ("American Electric Power",       "아메리칸 일렉트릭 파워", "전력·유틸리티",     "미국 중부·남부 전력 공급"),
    "PAYX":  ("Paychex Inc.",                  "페이첵스",           "HR·급여 소프트웨어",   "중소기업 HR·급여 서비스"),
    "FAST":  ("Fastenal Company",              "패스트널",           "산업 유통",            "볼트·너트 등 산업 소모품 유통"),
    "GEHC":  ("GE HealthCare Technologies",    "GE 헬스케어",        "의료기기",             "MRI·CT 등 의료 영상 장비"),
    "EXC":   ("Exelon Corporation",            "엑셀론",             "전력·유틸리티",        "미국 북동부·중서부 전력 공급"),
    "IDXX":  ("IDEXX Laboratories Inc.",       "IDEXX 래버러토리즈", "동물 진단",            "반려동물 진단·검사 장비"),
    "XEL":   ("Xcel Energy Inc.",              "엑셀 에너지",        "전력·유틸리티",        "미국 중부 전력·가스 공급"),
    "TEAM":  ("Atlassian Corporation",         "아틀라시안",         "협업 소프트웨어",       "Jira·Confluence 협업 툴"),
    "FANG":  ("Diamondback Energy Inc.",       "다이아몬드백 에너지", "에너지·석유",          "퍼미안 분지 원유 개발·생산"),
    "BKR":   ("Baker Hughes Company",          "베이커 휴즈",        "에너지 서비스",         "유전 굴착·서비스·LNG 설비"),
    "VRSK":  ("Verisk Analytics Inc.",         "버리스크 애널리틱스", "데이터·분석",          "보험·에너지 산업 데이터 분석"),
    "BIIB":  ("Biogen Inc.",                   "바이오젠",           "바이오·제약",          "알츠하이머·MS 신경계 치료제"),
    "NXPI":  ("NXP Semiconductors NV",         "NXP 세미컨덕터즈",  "반도체",               "자동차·IoT 반도체"),
    "ZS":    ("Zscaler Inc.",                  "지스케일러",         "사이버보안",            "제로트러스트 클라우드 보안"),
    "DLTR":  ("Dollar Tree Inc.",              "달러 트리",          "유통·소매",            "균일가 소매점 체인"),
    "ANSS":  ("ANSYS Inc.",                    "앤시스",             "시뮬레이션 소프트웨어", "엔지니어링 CAE 시뮬레이션"),
    "TTWO":  ("Take-Two Interactive",          "테이크-투 인터랙티브", "게임",               "GTA·NBA 2K 등 게임 퍼블리셔"),
    "CPRT":  ("Copart Inc.",                   "코파트",             "자동차 경매",          "폐차·중고차 온라인 경매 플랫폼"),
    "ON":    ("ON Semiconductor Corp.",        "ON 세미컨덕터",      "반도체",               "전력·전기차용 SiC 반도체"),
    "CCEP":  ("Coca-Cola Europacific Partners","코카콜라 유로퍼시픽", "음료",                "코카콜라 유럽·아태 병입·유통"),
    "ILMN":  ("Illumina Inc.",                 "일루미나",           "유전체 분석",          "유전자 염기서열 분석(NGS) 장비"),
    "GFS":   ("GlobalFoundries Inc.",          "글로벌파운드리스",   "반도체 파운드리",       "반도체 위탁생산(파운드리)"),
    "CDW":   ("CDW Corporation",               "CDW",               "IT 유통·솔루션",       "기업용 IT 제품·솔루션 유통"),
    "DDOG":  ("Datadog Inc.",                  "데이터독",           "클라우드 모니터링",     "클라우드 인프라·앱 모니터링"),
    "WBD":   ("Warner Bros. Discovery Inc.",   "워너브라더스 디스커버리", "미디어·엔터테인먼트", "HBO·CNN·Warner Bros."),
    "SMCI":  ("Super Micro Computer Inc.",     "슈퍼마이크로",       "AI 서버",              "AI·데이터센터용 고성능 서버"),
    "EA":    ("Electronic Arts Inc.",          "일렉트로닉 아츠",   "게임",                  "EA Sports·FIFA·Madden"),
    "LULU":  ("Lululemon Athletica Inc.",      "룰루레몬",           "의류·스포츠웨어",      "프리미엄 요가·운동복 브랜드"),
    "KHC":   ("Kraft Heinz Company",           "크래프트 하인즈",   "식품",                  "케첩·마카로니치즈 등 포장 식품"),
    "MRNA":  ("Moderna Inc.",                  "모더나",             "바이오·제약",          "mRNA 기반 백신·치료제"),
    "SIRI":  ("SiriusXM Holdings Inc.",        "시리우스XM",         "위성 라디오·미디어",    "위성 라디오·팟캐스트 플랫폼"),
    "RIVN":  ("Rivian Automotive Inc.",        "리비안",             "전기차",               "전기 픽업트럭·SUV 제조"),
    "LCID":  ("Lucid Group Inc.",              "루시드 그룹",        "전기차",               "프리미엄 전기 세단 제조"),
    "ZM":    ("Zoom Video Communications",     "줌 비디오",          "화상회의·협업",         "클라우드 화상회의 플랫폼"),
    "OKTA":  ("Okta Inc.",                     "옥타",               "사이버보안·ID 관리",    "클라우드 ID·접근 관리(IAM)"),
    "ALGN":  ("Align Technology Inc.",         "얼라인 테크놀로지",  "의료기기",              "인비절라인 투명 치아교정기"),
    "ENPH":  ("Enphase Energy Inc.",           "엔페이즈 에너지",   "태양광·에너지",          "마이크로인버터·가정용 에너지"),
    "MTCH":  ("Match Group Inc.",              "매치 그룹",          "소셜·데이팅",           "틴더·OkCupid 등 데이팅 앱"),
    "NCLH":  ("Norwegian Cruise Line",         "노르웨이지안 크루즈", "여행·크루즈",           "크루즈 여행 운항"),
    "EXPE":  ("Expedia Group Inc.",            "익스피디아",         "여행·OTA",             "온라인 여행 예약 플랫폼"),
    "PCVX":  ("Vaxcyte Inc.",                  "박스사이트",         "바이오·제약",           "폐렴구균 백신 개발"),
    "FWONK": ("Formula One Group",             "포뮬러 원 그룹",    "스포츠·미디어",          "F1 레이싱 미디어 권리"),
    "ARM":   ("Arm Holdings plc",              "ARM 홀딩스",         "반도체 IP",            "모바일·IoT 프로세서 아키텍처"),
    "APP":   ("Applovin Corporation",          "앱러빈",             "모바일 광고·AI",        "AI 기반 모바일 광고 플랫폼"),
    "MDB":   ("MongoDB Inc.",                  "몽고DB",             "데이터베이스",          "클라우드 NoSQL 데이터베이스"),
}

NASDAQ100_TICKERS = list(dict.fromkeys(TICKER_INFO.keys()))


# ═══════════════════════════════════════════════════════════
# 데이터 수집 헬퍼
# ═══════════════════════════════════════════════════════════

def load_sp500_tickers() -> list[str]:
    try:
        import requests
        url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        headers = {"User-Agent": "Mozilla/5.0 (compatible; stock-scanner/1.0)"}
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        table = pd.read_html(io.StringIO(resp.text))[0]
        tickers = table["Symbol"].str.replace(".", "-", regex=False).tolist()
        print(f"  S&P 500 종목 {len(tickers)}개 로드 완료")
        return tickers
    except Exception as e:
        print(f"  S&P 500 목록 로드 실패: {e}")
        return []


def build_all_tickers() -> list[str]:
    sp500 = load_sp500_tickers()
    combined = list(NASDAQ100_TICKERS)
    seen = set(combined)
    for t in sp500:
        if t not in seen:
            combined.append(t)
            seen.add(t)
    return combined


def calc_rsi(close: pd.Series, period: int = 14) -> float | None:
    if len(close) < period + 1:
        return None
    delta = close.diff(1)
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    last_loss = float(avg_loss.iloc[-1])
    if last_loss == 0:
        return 100.0
    rs = float(avg_gain.iloc[-1]) / last_loss
    return round(100 - (100 / (1 + rs)), 1)


def fetch_ticker_data(ticker: str) -> dict | None:
    try:
        end   = datetime.today()
        start = end - timedelta(days=420)

        t  = yf.Ticker(ticker)
        df = t.history(start=start, end=end)

        if df.empty or len(df) < 20:
            return None

        close  = df["Close"]
        volume = df["Volume"]
        current_price = float(close.iloc[-1])

        rsi = calc_rsi(close)

        n = min(252, len(close))
        w52_high = float(close.iloc[-n:].max())
        w52_low  = float(close.iloc[-n:].min())
        from_w52_high = round((current_price - w52_high) / w52_high * 100, 1)

        vol_last  = float(volume.iloc[-1])
        vol_avg20 = float(volume.iloc[-21:-1].mean()) if len(volume) >= 21 else float(volume.mean())
        vol_ratio = round(vol_last / vol_avg20, 2) if vol_avg20 > 0 else None

        en_name = ticker
        kr_name = ticker
        theme   = "—"
        desc    = "—"
        per     = None
        target_price = None
        upside_pct   = None

        try:
            info = t.info
            if ticker in TICKER_INFO:
                en_name, kr_name, theme, desc = TICKER_INFO[ticker]
            else:
                en_name = info.get("longName", ticker) or ticker
                kr_name = ticker
                theme   = info.get("sector", "—") or "—"
                summary = info.get("longBusinessSummary", "") or ""
                desc    = summary[:60].rstrip() if summary else "—"

            v = info.get("trailingPE")
            per = round(float(v), 1) if v else None
            v = info.get("targetMeanPrice")
            if v:
                target_price = round(float(v), 2)
                upside_pct   = round((target_price - current_price) / current_price * 100, 1)
        except Exception:
            if ticker in TICKER_INFO:
                en_name, kr_name, theme, desc = TICKER_INFO[ticker]

        display_name = kr_name if kr_name != ticker else en_name[:18]

        result: dict = {
            "ticker":        ticker,
            "en_name":       en_name,
            "kr_name":       kr_name,
            "display_name":  display_name,
            "theme":         theme,
            "desc":          desc,
            "price":         round(current_price, 2),
            "rsi":           rsi,
            "w52_high":      round(w52_high, 2),
            "w52_low":       round(w52_low, 2),
            "from_w52_high": from_w52_high,
            "vol_ratio":     vol_ratio,
            "per":           per,
            "target_price":  target_price,
            "upside_pct":    upside_pct,
        }

        for period in MA_PERIODS:
            if len(close) < period:
                result[f"ma{period}"]   = None
                result[f"diff{period}"] = None
            else:
                ma_val = float(close.rolling(window=period).mean().iloc[-1])
                diff   = (current_price - ma_val) / ma_val * 100
                result[f"ma{period}"]   = round(ma_val, 2)
                result[f"diff{period}"] = round(diff, 2)

        return result

    except Exception as e:
        print(f"  [{ticker}] 오류: {e}")
        return None


# ── 콘솔 출력 ─────────────────────────────────────────────

def _f(v, fmt_str: str, none: str = "   -") -> str:
    return fmt_str.format(v) if v is not None else none


def print_ma_table(rows: list[dict], period: int):
    key_diff = f"diff{period}"
    near = [r for r in rows if r[key_diff] is not None and abs(r[key_diff]) <= THRESHOLD_PCT]
    near.sort(key=lambda x: abs(x[key_diff]))

    if not near:
        print(f"\n  [ {period}일선 근접 — 없음 ]")
        return

    print(f"\n  [ {period}일 이동평균선 근접 — {len(near)}개 ]")
    print(f"  {'티커':<7}  {'종목명':<20}  {'현재가':>8}  {'MA차이%':>7}  "
          f"{'RSI':>5}  {'52주고점%':>8}  {'거래량비':>7}  {'PER':>6}  {'업사이드%':>9}")
    print("  " + "-" * 110)

    for r in near:
        sign = "+" if r[key_diff] >= 0 else ""
        print(
            f"  {r['ticker']:<7}"
            f"  {r['display_name']:<20}"
            f"  {r['price']:>8.2f}"
            f"  {sign}{r[key_diff]:>6.2f}%"
            f"  {_f(r['rsi'],          '{:>5.1f}')}"
            f"  {_f(r['from_w52_high'],'{:>+7.1f}%')}"
            f"  {_f(r['vol_ratio'],    '{:>6.2f}x')}"
            f"  {_f(r['per'],          '{:>6.1f}')}"
            f"  {_f(r['upside_pct'],   '{:>+8.1f}%')}"
        )


# ═══════════════════════════════════════════════════════════
# STAGE 1 — 스캔 및 CSV 저장
# ═══════════════════════════════════════════════════════════

def _to_csv_row(r: dict) -> dict:
    row = {
        "티커":                     r["ticker"],
        "영문명":                   r["en_name"],
        "한국명":                   r["kr_name"],
        "테마/섹터":                r["theme"],
        "설명":                     r["desc"],
        "현재가($)":                r["price"],
        "RSI(14)":                  r["rsi"],
        "52주고가($)":              r["w52_high"],
        "52주저가($)":              r["w52_low"],
        "52주고점대비(%)":           r["from_w52_high"],
        "거래량비율(전일/20일평균)": r["vol_ratio"],
        "PER(후행)":                r["per"],
        "목표주가($)":              r["target_price"],
        "업사이드(%)":              r["upside_pct"],
    }
    for p in MA_PERIODS:
        row[f"MA{p}($)"]     = r[f"ma{p}"]
        row[f"MA{p}차이(%)"] = r[f"diff{p}"]
        row[f"MA{p}근접"]    = "O" if r[f"diff{p}"] is not None and abs(r[f"diff{p}"]) <= THRESHOLD_PCT else ""
    return row


def stage1_scan(today: str) -> tuple[list[dict], pd.DataFrame, str]:
    SEP = "=" * 110
    print(SEP)
    print(f"  [1단계] S&P 500 + NASDAQ 100 | 이동평균선 근접 종목 스캔")
    print(f"  기준: 60 / 120 / 240일선 각각 ±{THRESHOLD_PCT}% 이내  |  기준일: {today[:4]}-{today[4:6]}-{today[6:8]}")
    print(SEP)

    all_tickers = build_all_tickers()
    total = len(all_tickers)
    print(f"  총 {total}개 종목 스캔 (NASDAQ 100: {len(NASDAQ100_TICKERS)}개 | S&P 500 추가: {total - len(NASDAQ100_TICKERS)}개)\n")

    all_data: list[dict] = []
    for i, ticker in enumerate(all_tickers, 1):
        print(f"  ({i:>3}/{total}) {ticker:<7} 조회 중...", end="\r")
        data = fetch_ticker_data(ticker)
        if data:
            all_data.append(data)

    print(" " * 70, end="\r")

    if not all_data:
        print("  데이터를 가져올 수 없습니다.")
        return [], pd.DataFrame(), ""

    for period in MA_PERIODS:
        print_ma_table(all_data, period)

    rows_csv = [_to_csv_row(r) for r in all_data]
    df = pd.DataFrame(rows_csv)

    base = f"Data_{today}"
    csv_path = f"{base}.csv"
    for suffix in ["", "_1", "_2", "_3"]:
        candidate = f"{base}{suffix}.csv"
        try:
            df.to_csv(candidate, index=False, encoding="utf-8-sig")
            csv_path = candidate
            break
        except PermissionError:
            continue

    print(f"\n  [1단계 완료] {csv_path} ({len(all_data)}개 종목 저장)")
    print(SEP)
    return all_data, df, csv_path


# ═══════════════════════════════════════════════════════════
# STAGE 2 — 분석 리포트 생성
# ═══════════════════════════════════════════════════════════

def _fv(val, fmt: str, fb: str = "-") -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return fb
    return fmt.format(val)


def _score_row(r: pd.Series) -> float:
    score = 0.0
    near_cnt = sum(1 for p in MA_PERIODS if r.get(f"MA{p}근접") == "O")
    score += near_cnt * 12

    rsi = r.get("RSI(14)")
    if pd.notna(rsi):
        if 45 <= rsi <= 60:         score += 15
        elif 35 <= rsi < 45 or 60 < rsi <= 65: score += 10
        elif rsi < 35 or rsi > 65: score += 5

    upside = r.get("업사이드(%)")
    if pd.notna(upside):
        if upside > 25:   score += 20
        elif upside > 15: score += 12
        elif upside > 10: score += 6

    per = r.get("PER(후행)")
    if pd.notna(per) and 5 < per < 20:
        score += 8

    for p in MA_PERIODS:
        if r.get(f"MA{p}근접") == "O":
            diff = abs(r.get(f"MA{p}차이(%)", 2.0))
            score += max(0.0, (2.0 - diff) * 4)

    return score


def _ma_tag(r: pd.Series) -> str:
    parts = []
    for p in MA_PERIODS:
        if r.get(f"MA{p}근접") == "O":
            diff = r.get(f"MA{p}차이(%)", 0)
            parts.append(f"MA{p} {'+' if diff >= 0 else ''}{diff:.1f}%")
    return " / ".join(parts) or "-"


def _rsi_label(rsi) -> str:
    if pd.isna(rsi): return "-"
    if rsi < 30:   return f"{rsi:.0f} (극단적 과매도)"
    if rsi < 40:   return f"{rsi:.0f} (과매도)"
    if rsi < 50:   return f"{rsi:.0f} (약세)"
    if rsi < 60:   return f"{rsi:.0f} (중립)"
    if rsi < 70:   return f"{rsi:.0f} (강세)"
    return f"{rsi:.0f} (과열)"


def _table_header() -> list[str]:
    return [
        "| 티커 | 종목명 | 현재가 | RSI | 52주고점% | 업사이드% | PER | MA 위치 |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]


def _table_row(r: pd.Series) -> str:
    name = str(r.get("display_name", r.get("티커", "")))[:18]
    return (
        f"| {r.get('티커', ''):<6} "
        f"| {name:<18} "
        f"| ${_fv(r.get('현재가($)'), '{:.2f}'):>8} "
        f"| {_fv(r.get('RSI(14)'), '{:.0f}'):>4} "
        f"| {_fv(r.get('52주고점대비(%)'), '{:+.1f}%'):>7} "
        f"| {_fv(r.get('업사이드(%)'), '{:+.1f}%'):>7} "
        f"| {_fv(r.get('PER(후행)'), '{:.1f}'):>6} "
        f"| {_ma_tag(r)} |"
    )


def stage2_analysis(df: pd.DataFrame, today: str) -> str:
    print("\n  [2단계] 분석 리포트 생성 중...")

    df = df.copy()
    df["display_name"] = df.apply(
        lambda r: r["한국명"] if r["한국명"] != r["티커"]
        else (r["영문명"][:18] if pd.notna(r.get("영문명")) else r["티커"]),
        axis=1,
    )

    df["_score"] = df.apply(_score_row, axis=1)

    near60     = df[df["MA60근접"].eq("O")]
    near120    = df[df["MA120근접"].eq("O")]
    near240    = df[df["MA240근접"].eq("O")]
    near_any   = df[df["MA60근접"].eq("O") | df["MA120근접"].eq("O") | df["MA240근접"].eq("O")]
    near_multi = df[
        (df["MA60근접"].eq("O").astype(int) +
         df["MA120근접"].eq("O").astype(int) +
         df["MA240근접"].eq("O").astype(int)) >= 2
    ]

    top10 = near_any.nlargest(10, "_score")

    date_str = f"{today[:4]}-{today[4:6]}-{today[6:8]}"
    md: list[str] = []

    def add(*lines: str):
        if not lines:
            md.append("")
        else:
            md.extend(lines)

    # ── 헤더
    add(f"# 이동평균선 근접 종목 분석 리포트")
    add(f"**기준일:** {date_str}  ")
    add(f"**스캔 유니버스:** S&P 500 + NASDAQ 100 (총 {len(df)}개 종목)  ")
    add(f"**기준:** 60 / 120 / 240일 이동평균선 ±{THRESHOLD_PCT}% 이내")
    add()
    add("---")
    add()

    # ── 요약
    add("## 요약")
    add()
    add("| 구분 | 종목 수 |")
    add("|---|---:|")
    add(f"| 60일선 근접 | **{len(near60)}개** |")
    add(f"| 120일선 근접 | **{len(near120)}개** |")
    add(f"| 240일선 근접 | **{len(near240)}개** |")
    add(f"| 2개 이상 이평선 동시 근접 | **{len(near_multi)}개** |")
    add()
    add("---")
    add()

    # ── 핵심 추천
    add("## 1. 핵심 추천 종목 (종합 점수 상위)")
    add()
    add("> 복수 이평선 수렴 · RSI 품질 · 애널리스트 업사이드 · PER을 종합 채점한 결과입니다.")
    add()
    add(*_table_header())
    for _, r in top10.iterrows():
        add(_table_row(r))
    add()

    # 각 종목 한 줄 코멘트
    for _, r in top10.iterrows():
        parts = []
        parts.append(_ma_tag(r))
        rsi = r.get("RSI(14)")
        if pd.notna(rsi):
            parts.append(f"RSI {_rsi_label(rsi)}")
        upside = r.get("업사이드(%)")
        if pd.notna(upside):
            parts.append(f"업사이드 {upside:+.1f}%")
        name = r.get("display_name", r.get("티커", ""))
        add(f"- **{r.get('티커')} {name}** — {' / '.join(parts)}")
    add()
    add("---")
    add()

    # ── 테마별 분석
    add("## 2. 테마별 분석")
    add()

    # A. 역발상 (RSI < 40 + near MA)
    add("### A. 역발상 매수 — RSI 과매도 + 이평선 지지")
    add()
    add("> RSI 40 미만인데 이동평균선 위에서 지지 받는 종목. 단기 반등 가능성이 높으나 분할 진입 권장.")
    add()
    oversold = near_any[near_any["RSI(14)"] < 40].sort_values("RSI(14)")
    if oversold.empty:
        add("_해당 종목 없음_")
    else:
        add(*_table_header())
        for _, r in oversold.head(8).iterrows():
            add(_table_row(r))
    add()

    # B. 이평선 수렴 (2+ MAs)
    add("### B. 이평선 수렴 — 2개 이상 MA 동시 근접")
    add()
    add("> 단기·중기·장기 이평선이 한 가격대에 겹치는 구간. 방향 돌파 시 강한 추세가 나타남.")
    add()
    multi_sorted = near_multi.copy()
    multi_sorted["_near_cnt"] = (
        multi_sorted["MA60근접"].eq("O").astype(int) +
        multi_sorted["MA120근접"].eq("O").astype(int) +
        multi_sorted["MA240근접"].eq("O").astype(int)
    )
    multi_sorted = multi_sorted.sort_values(["_near_cnt", "_score"], ascending=[False, False])
    add(*_table_header())
    for _, r in multi_sorted.head(10).iterrows():
        add(_table_row(r))
    add()

    # C. 성장 (업사이드 > 20%)
    add("### C. 성장주 — 애널리스트 업사이드 20%+ + MA 근접")
    add()
    add("> 기관 컨센서스 목표가 대비 현재가 괴리가 큰 종목. 시장이 저평가 중이라는 신호.")
    add()
    growth = near_any[near_any["업사이드(%)"] > 20].sort_values("업사이드(%)", ascending=False)
    if growth.empty:
        add("_해당 종목 없음_")
    else:
        add(*_table_header())
        for _, r in growth.head(10).iterrows():
            add(_table_row(r))
    add()

    # D. 가치주 (PER < 15)
    add("### D. 가치주 — PER 15 이하 + MA 근접")
    add()
    add("> 실적 대비 주가가 낮은 종목이 이평선 지지 구간에 위치.")
    add()
    value = near_any[(near_any["PER(후행)"] > 0) & (near_any["PER(후행)"] < 15)].sort_values("PER(후행)")
    if value.empty:
        add("_해당 종목 없음_")
    else:
        add(*_table_header())
        for _, r in value.head(8).iterrows():
            add(_table_row(r))
    add()
    add("---")
    add()

    # ── 섹터 분석
    add("## 3. 섹터 분석")
    add()
    sector_cnt = near_any["테마/섹터"].value_counts()
    total_near = len(near_any)
    add("| 섹터 | 근접 종목 수 | 비중 |")
    add("|---|---:|---:|")
    for sector, cnt in sector_cnt.items():
        pct = cnt / total_near * 100
        add(f"| {sector} | {cnt}개 | {pct:.1f}% |")
    add()

    # 집중 섹터 코멘트
    top_sector = sector_cnt.index[0] if len(sector_cnt) > 0 else ""
    top_cnt    = sector_cnt.iloc[0] if len(sector_cnt) > 0 else 0
    if top_sector:
        add(f"> **{top_sector}** 섹터가 {top_cnt}개로 가장 많이 집중됨 — 섹터 로테이션 또는 테마 수혜 신호 가능성.")
    add()
    add("---")
    add()

    # ── 주의 종목
    add("## 4. 주의 종목 — RSI 과열 (70+) + MA 저항")
    add()
    add("> RSI 70 이상인데 이평선 근처에 위치 = 저항선에서 눌릴 가능성. 신규 매수 주의.")
    add()
    hot = near_any[near_any["RSI(14)"] >= 70].sort_values("RSI(14)", ascending=False)
    if hot.empty:
        add("_해당 종목 없음 (현재 과열 종목 없음)_")
    else:
        add(*_table_header())
        for _, r in hot.head(5).iterrows():
            add(_table_row(r))
    add()
    add("---")
    add()

    # ── 전체 목록
    add("## 5. 전체 근접 종목 목록")
    add()
    for period, near_df in [(60, near60), (120, near120), (240, near240)]:
        add(f"### {period}일선 근접 ({len(near_df)}개)")
        add()
        near_sorted = near_df.copy()
        near_sorted["_abs"] = near_sorted[f"MA{period}차이(%)"].abs()
        near_sorted = near_sorted.sort_values("_abs")
        add(*_table_header())
        for _, r in near_sorted.iterrows():
            add(_table_row(r))
        add()

    add("---")
    add()
    add("*본 리포트는 Yahoo Finance 공개 데이터 기반 자동 생성 문서입니다. 투자 권유가 아닙니다.*")

    md_path = f"Result_{today}.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md))

    print(f"  [2단계 완료] {md_path}")
    return md_path


# ═══════════════════════════════════════════════════════════
# STAGE 3 — 한국어 번역 저장
# ═══════════════════════════════════════════════════════════

def _translate_list(texts: list[str], label: str) -> list[str]:
    results = list(texts)
    total = len(texts)
    for i, text in enumerate(texts):
        if not text or str(text) in ("—", "nan", ""):
            continue
        try:
            translated = _GT(source="en", target="ko").translate(str(text))
            if translated:
                results[i] = translated
        except Exception:
            pass
        if (i + 1) % 5 == 0 or i == total - 1:
            print(f"  {label} 번역 중... {i+1}/{total}", end="\r")
        time.sleep(0.15)
    print(f"  {label} 번역 완료 ({total}건)" + " " * 20)
    return results


def stage3_translate(csv_path: str) -> None:
    print(f"\n  [3단계] 번역 저장 시작: {csv_path}")

    df = pd.read_csv(csv_path, encoding="utf-8-sig")

    # 섹터 정적 번역 (API 불필요)
    df["테마/섹터"] = df["테마/섹터"].map(lambda x: SECTOR_KO.get(str(x), x) if pd.notna(x) else x)

    mask = df["한국명"] == df["티커"]
    needs = df[mask].copy()

    if needs.empty:
        df.to_csv(csv_path, index=False, encoding="utf-8-sig")
        print(f"  [3단계 완료] 섹터 번역만 적용 (번역 대상 종목 없음)")
        return

    if not _HAS_TRANSLATOR:
        df.to_csv(csv_path, index=False, encoding="utf-8-sig")
        print("  [3단계] deep-translator 미설치 — 섹터 번역만 적용")
        print("  설치: uv pip install deep-translator")
        return

    print(f"  번역 대상: {len(needs)}개 종목")

    names_kr = _translate_list(needs["영문명"].tolist(), "회사명")
    descs_kr  = _translate_list(needs["설명"].tolist(),   "설명")

    df.loc[mask, "한국명"] = names_kr
    df.loc[mask, "설명"]   = descs_kr

    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    print(f"  [3단계 완료] {csv_path} 번역 저장 완료")


# ═══════════════════════════════════════════════════════════
# 4단계: HTML 인터랙티브 대시보드 생성
# ═══════════════════════════════════════════════════════════

def stage4_html(df: pd.DataFrame, today: str) -> str:
    import json

    html_path = f"Report_{today}.html"
    print(f"\n  [4단계] HTML 대시보드 생성: {html_path}")

    ma_cols_present = [c for c in ["MA60근접", "MA120근접", "MA240근접"] if c in df.columns]
    near60  = int(df["MA60근접"].eq("O").sum())  if "MA60근접"  in df.columns else 0
    near120 = int(df["MA120근접"].eq("O").sum()) if "MA120근접" in df.columns else 0
    near240 = int(df["MA240근접"].eq("O").sum()) if "MA240근접" in df.columns else 0
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
            "en_name":  str(safe(r.get("영문명"), "")),
            "kr_name":  str(safe(r.get("한국명"), "")),
            "sector":   str(safe(r.get("테마/섹터"), "")),
            "desc":     str(safe(r.get("설명"), "")),
            "price":    safe(r.get("현재가($)")),
            "rsi":      safe(r.get("RSI(14)")),
            "fromHigh": safe(r.get("52주고점대비(%)")),
            "volRatio": safe(r.get("거래량비율(전일/20일평균)")),
            "per":      safe(r.get("PER(후행)")),
            "upside":   safe(r.get("업사이드(%)")),
            "diff60":   safe(r.get("MA60차이(%)")),
            "diff120":  safe(r.get("MA120차이(%)")),
            "diff240":  safe(r.get("MA240차이(%)")),
            "near60":   str(safe(r.get("MA60근접"),  "")) == "O",
            "near120":  str(safe(r.get("MA120근접"), "")) == "O",
            "near240":  str(safe(r.get("MA240근접"), "")) == "O",
        })

    data_json = json.dumps(records, ensure_ascii=False)
    date_str  = f"{today[:4]}-{today[4:6]}-{today[6:]}"

    template = (
        '<!DOCTYPE html>\n'
        '<html lang="ko">\n'
        '<head>\n'
        '<meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        '<title>Stock Scanner — ###DATE###</title>\n'
        '<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">\n'
        '<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>\n'
        '<style>\n'
        'body{background:#0d1117;color:#c9d1d9;font-family:"Segoe UI",sans-serif}\n'
        '.card{background:#161b22;border:1px solid #30363d}\n'
        '.card-header,.card-footer{background:#21262d;border-color:#30363d}\n'
        '.nav-tabs .nav-link{color:#8b949e;border-color:transparent}\n'
        '.nav-tabs .nav-link.active{background:#21262d;color:#58a6ff;border-color:#30363d #30363d #21262d}\n'
        'table{border-collapse:collapse;width:100%}\n'
        'td,th{border:1px solid #30363d;padding:5px 8px;font-size:.8rem;white-space:nowrap}\n'
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
        'input[type=text],select{background:#21262d;border:1px solid #30363d;color:#c9d1d9;'
        'padding:5px 10px;border-radius:4px}\n'
        'input[type=text]:focus,select:focus{outline:none;border-color:#58a6ff}\n'
        '</style>\n'
        '</head>\n'
        '<body>\n'
        '<div class="container-fluid py-3">\n'
        '\n'
        '<div class="d-flex align-items-baseline mb-3 gap-3">\n'
        '  <h4 class="mb-0 text-white">\U0001f4c8 Stock MA Scanner</h4>\n'
        '  <small class="text-secondary">###DATE### &nbsp;|&nbsp; S&amp;P500 + NASDAQ100 &nbsp;|&nbsp; ###TOTAL### 종목</small>\n'
        '</div>\n'
        '\n'
        '<!-- Summary Cards -->\n'
        '<div class="row g-2 mb-3">\n'
        '  <div class="col-6 col-md-3"><div class="card text-center p-3 stat-card">\n'
        '    <div class="text-secondary small">MA60 근접</div>\n'
        '    <h2 class="text-info">###NEAR60###</h2>\n'
        '    <div class="text-secondary small">±2% 이내</div>\n'
        '  </div></div>\n'
        '  <div class="col-6 col-md-3"><div class="card text-center p-3 stat-card">\n'
        '    <div class="text-secondary small">MA120 근접</div>\n'
        '    <h2 class="text-warning">###NEAR120###</h2>\n'
        '    <div class="text-secondary small">±2% 이내</div>\n'
        '  </div></div>\n'
        '  <div class="col-6 col-md-3"><div class="card text-center p-3 stat-card">\n'
        '    <div class="text-secondary small">MA240 근접</div>\n'
        '    <h2 class="text-danger">###NEAR240###</h2>\n'
        '    <div class="text-secondary small">±2% 이내</div>\n'
        '  </div></div>\n'
        '  <div class="col-6 col-md-3"><div class="card text-center p-3 stat-card">\n'
        '    <div class="text-secondary small">복수 MA 수렴</div>\n'
        '    <h2 class="text-success">###NEAR_MULTI###</h2>\n'
        '    <div class="text-secondary small">2개 이상</div>\n'
        '  </div></div>\n'
        '</div>\n'
        '\n'
        '<!-- Charts -->\n'
        '<div class="row g-2 mb-3">\n'
        '  <div class="col-md-7"><div class="card p-3" style="height:230px">\n'
        '    <div class="text-secondary small mb-1">섹터별 근접 종목 분포 (MA 근접 종목 기준)</div>\n'
        '    <canvas id="sectorChart"></canvas>\n'
        '  </div></div>\n'
        '  <div class="col-md-5"><div class="card p-3" style="height:230px">\n'
        '    <div class="text-secondary small mb-1">RSI 분포 (전체 종목)</div>\n'
        '    <canvas id="rsiChart"></canvas>\n'
        '  </div></div>\n'
        '</div>\n'
        '\n'
        '<!-- Filters -->\n'
        '<div class="d-flex gap-2 mb-2 flex-wrap align-items-center">\n'
        '  <input type="text" id="searchBox" placeholder="티커/종목명 검색..." style="width:190px" oninput="applyFilter()">\n'
        '  <select id="sectorFilter" onchange="applyFilter()"><option value="">전체 섹터</option></select>\n'
        '  <select id="rsiFilter" onchange="applyFilter()">\n'
        '    <option value="">전체 RSI</option>\n'
        '    <option value="low">RSI &lt; 35 (과매도)</option>\n'
        '    <option value="high">RSI &gt; 65 (과매열)</option>\n'
        '    <option value="mid">35 ≤ RSI ≤ 65 (중립)</option>\n'
        '  </select>\n'
        '  <span class="text-secondary small ms-auto" id="rowCount"></span>\n'
        '</div>\n'
        '\n'
        '<!-- Tabs -->\n'
        '<ul class="nav nav-tabs mb-0" id="mainTabs">\n'
        '  <li class="nav-item"><a class="nav-link active" href="#" data-tab="all">전체</a></li>\n'
        '  <li class="nav-item"><a class="nav-link" href="#" data-tab="ma60">MA60</a></li>\n'
        '  <li class="nav-item"><a class="nav-link" href="#" data-tab="ma120">MA120</a></li>\n'
        '  <li class="nav-item"><a class="nav-link" href="#" data-tab="ma240">MA240</a></li>\n'
        '  <li class="nav-item"><a class="nav-link" href="#" data-tab="multi">복수MA</a></li>\n'
        '</ul>\n'
        '\n'
        '<!-- Table -->\n'
        '<div class="card" style="border-top-left-radius:0">\n'
        '  <div class="p-0" style="overflow-x:auto">\n'
        '    <table id="mainTable">\n'
        '      <thead><tr>\n'
        '        <th data-col="ticker">티커</th>\n'
        '        <th data-col="kr_name">종목명</th>\n'
        '        <th data-col="sector">섹터</th>\n'
        '        <th data-col="price">현재ga($)</th>\n'
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
        '\n'
        '</div>\n'
        '<script>\n'
        'const DATA=###DATA_JSON###;\n'
        'const SECTOR_LABELS=###SECTOR_LABELS###;\n'
        'const SECTOR_VALUES=###SECTOR_VALUES###;\n'
        'const RSI_LABELS=###RSI_LABELS###;\n'
        'const RSI_VALUES=###RSI_VALUES###;\n'
        '\n'
        'let currentTab="all",sortCol="ticker",sortAsc=true;\n'
        '\n'
        'const sectorSet=[...new Set(DATA.map(d=>d.sector).filter(Boolean))].sort();\n'
        'const sf=document.getElementById("sectorFilter");\n'
        'sectorSet.forEach(s=>{const o=document.createElement("option");o.value=s;o.textContent=s;sf.appendChild(o);});\n'
        '\n'
        'new Chart(document.getElementById("sectorChart"),{\n'
        '  type:"bar",\n'
        '  data:{labels:SECTOR_LABELS,datasets:[{data:SECTOR_VALUES,backgroundColor:"#58a6ff66",borderColor:"#58a6ff",borderWidth:1}]},\n'
        '  options:{indexAxis:"y",plugins:{legend:{display:false}},\n'
        '    scales:{x:{ticks:{color:"#8b949e"},grid:{color:"#30363d"}},\n'
        '            y:{ticks:{color:"#c9d1d9",font:{size:10}},grid:{color:"#30363d"}}},\n'
        '    maintainAspectRatio:false}\n'
        '});\n'
        '\n'
        'const rsiColors=RSI_LABELS.map((_,i)=>i<=3?"#3fb95066":i>=10?"#f8514966":"#58a6ff66");\n'
        'new Chart(document.getElementById("rsiChart"),{\n'
        '  type:"bar",\n'
        '  data:{labels:RSI_LABELS,datasets:[{data:RSI_VALUES,backgroundColor:rsiColors,\n'
        '    borderColor:rsiColors.map(c=>c.replace("66","ff")),borderWidth:1}]},\n'
        '  options:{plugins:{legend:{display:false}},\n'
        '    scales:{x:{ticks:{color:"#8b949e",font:{size:9}},grid:{color:"#30363d"}},\n'
        '            y:{ticks:{color:"#8b949e"},grid:{color:"#30363d"}}},\n'
        '    maintainAspectRatio:false}\n'
        '});\n'
        '\n'
        'document.getElementById("mainTabs").addEventListener("click",e=>{\n'
        '  const a=e.target.closest("a[data-tab]");\n'
        '  if(!a)return;\n'
        '  e.preventDefault();\n'
        '  document.querySelectorAll("#mainTabs .nav-link").forEach(l=>l.classList.remove("active"));\n'
        '  a.classList.add("active");\n'
        '  currentTab=a.dataset.tab;\n'
        '  applyFilter();\n'
        '});\n'
        '\n'
        'document.getElementById("mainTable").querySelector("thead").addEventListener("click",e=>{\n'
        '  const th=e.target.closest("th[data-col]");\n'
        '  if(!th)return;\n'
        '  const col=th.dataset.col;\n'
        '  if(sortCol===col)sortAsc=!sortAsc;\n'
        '  else{sortCol=col;sortAsc=true;}\n'
        '  document.querySelectorAll("thead th").forEach(t=>t.classList.remove("th-sorted"));\n'
        '  th.classList.add("th-sorted");\n'
        '  renderFilter();\n'
        '});\n'
        '\n'
        'function fmt(v,dec=2,suf=""){if(v==null)return"-";return Number(v).toFixed(dec)+suf;}\n'
        'function rsiCell(v){if(v==null)return"-";const n=+v,c=n<35?"rsi-green":n>65?"rsi-red":"";return `<span class="${c}">${n.toFixed(1)}</span>`;}\n'
        'function upCell(v){if(v==null)return"-";const n=+v,c=n>=20?"up-green":n<0?"up-red":"";return `<span class="${c}">${n.toFixed(1)}%</span>`;}\n'
        'function perCell(v){if(v==null)return"-";const n=+v,c=n<15?"per-green":n>40?"per-red":"";return `<span class="${c}">${n.toFixed(1)}</span>`;}\n'
        'function diffCell(v){if(v==null)return"-";const n=+v,c=Math.abs(n)<=2?"ma-warn":"";return `<span class="${c}">${n>=0?"+":""}${n.toFixed(2)}%</span>`;}\n'
        'function badges(d){let b="";if(d.near60)b+=\'<span class="badge bg-info text-dark me-1" style="font-size:.65rem">60</span>\';if(d.near120)b+=\'<span class="badge bg-warning text-dark me-1" style="font-size:.65rem">120</span>\';if(d.near240)b+=\'<span class="badge bg-danger me-1" style="font-size:.65rem">240</span>\';return b||"-";}\n'
        '\n'
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
        '    if(search&&!(d.ticker.toLowerCase().includes(search)||d.kr_name.toLowerCase().includes(search)||d.en_name.toLowerCase().includes(search)))return false;\n'
        '    if(sector&&d.sector!==sector)return false;\n'
        '    if(rsiF==="low"&&!(d.rsi!=null&&d.rsi<35))return false;\n'
        '    if(rsiF==="high"&&!(d.rsi!=null&&d.rsi>65))return false;\n'
        '    if(rsiF==="mid"&&!(d.rsi!=null&&d.rsi>=35&&d.rsi<=65))return false;\n'
        '    return true;\n'
        '  });\n'
        '  rows.sort((a,b)=>{\n'
        '    let va=a[sortCol],vb=b[sortCol];\n'
        '    if(va==null)va=sortAsc?Infinity:-Infinity;\n'
        '    if(vb==null)vb=sortAsc?Infinity:-Infinity;\n'
        '    if(typeof va==="string")return sortAsc?va.localeCompare(vb):vb.localeCompare(va);\n'
        '    return sortAsc?va-vb:vb-va;\n'
        '  });\n'
        '  const tbody=document.getElementById("tableBody");\n'
        '  tbody.innerHTML=rows.map(d=>`\n'
        '    <tr>\n'
        '      <td><a href="https://finance.yahoo.com/quote/${d.ticker}" target="_blank" class="ticker-link">${d.ticker}</a></td>\n'
        '      <td title="${d.en_name}\\n${d.desc}">${d.kr_name||d.en_name}</td>\n'
        '      <td>${d.sector||"-"}</td>\n'
        '      <td>$${fmt(d.price)}</td>\n'
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
        '\n'
        'renderFilter();\n'
        '</script>\n'
        '</body>\n'
        '</html>\n'
    )

    html = template
    html = html.replace("###DATE###",          date_str)
    html = html.replace("###TOTAL###",         str(total))
    html = html.replace("###NEAR60###",        str(near60))
    html = html.replace("###NEAR120###",       str(near120))
    html = html.replace("###NEAR240###",       str(near240))
    html = html.replace("###NEAR_MULTI###",    str(near_multi))
    html = html.replace("###DATA_JSON###",     data_json)
    html = html.replace("###SECTOR_LABELS###", sector_labels_json)
    html = html.replace("###SECTOR_VALUES###", sector_values_json)
    html = html.replace("###RSI_LABELS###",    rsi_labels_json)
    html = html.replace("###RSI_VALUES###",    rsi_values_json)

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"  [4단계 완료] {html_path} 생성 완료")
    return html_path


# ═══════════════════════════════════════════════════════════
# 스케줄러 등록 (Windows 작업 스케줄러)
# ═══════════════════════════════════════════════════════════

def setup_scheduler(run_time: str = "08:05") -> None:
    import subprocess
    script = os.path.abspath(__file__)
    python = sys.executable
    task   = "StockScanner_Daily"

    cmd = (
        f'schtasks /create /tn "{task}" '
        f'/tr "\\"{python}\\" \\"{script}\\"" '
        f'/sc daily /st {run_time} /f'
    )
    try:
        subprocess.run(cmd, shell=True, check=True, capture_output=True)
        print(f"  등록 완료: 매일 {run_time} 자동 실행")
        print(f"  작업 이름: {task}")
        print(f"  확인: schtasks /query /tn \"{task}\"")
        print(f"  삭제: schtasks /delete /tn \"{task}\" /f")
    except subprocess.CalledProcessError as e:
        print(f"  등록 실패: {e}")
        print("  관리자 권한으로 실행하거나 수동으로 작업 스케줄러를 설정하세요.")


# ═══════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="S&P 500 + NASDAQ 100 이동평균선 근접 종목 스캐너"
    )
    parser.add_argument("--stage",  type=int, choices=[1, 2, 3, 4],
                        help="특정 단계만 실행 (기본: 전체)")
    parser.add_argument("--date",   default=datetime.today().strftime("%Y%m%d"),
                        help="대상 날짜 YYYYMMDD (기본: 오늘)")
    parser.add_argument("--force",  action="store_true",
                        help="기존 CSV가 있어도 1단계 재실행")
    parser.add_argument("--setup-scheduler", action="store_true",
                        help="Windows 작업 스케줄러에 매일 08:05 등록")
    parser.add_argument("--time",   default="08:05",
                        help="스케줄러 실행 시각 HH:MM (기본: 08:05)")
    args = parser.parse_args()

    if args.setup_scheduler:
        setup_scheduler(args.time)
        return

    today    = args.date
    csv_path = f"Data_{today}.csv"
    run_all  = args.stage is None
    df       = None

    # 1단계
    if run_all or args.stage == 1:
        if os.path.exists(csv_path) and not args.force:
            print(f"  기존 파일 사용: {csv_path}  (재스캔하려면 --force 옵션 추가)")
            df = pd.read_csv(csv_path, encoding="utf-8-sig")
        else:
            _, df, csv_path = stage1_scan(today)
            if df.empty:
                return

    # 2단계
    if run_all or args.stage == 2:
        if df is None:
            if not os.path.exists(csv_path):
                print(f"  오류: {csv_path} 파일이 없습니다. 먼저 1단계를 실행하세요.")
                return
            df = pd.read_csv(csv_path, encoding="utf-8-sig")
        stage2_analysis(df, today)

    # 3단계
    if run_all or args.stage == 3:
        if not os.path.exists(csv_path):
            print(f"  오류: {csv_path} 파일이 없습니다. 먼저 1단계를 실행하세요.")
            return
        stage3_translate(csv_path)

    # 4단계 (기본 실행 또는 --stage 4)
    if run_all or args.stage == 4:
        if df is None:
            if not os.path.exists(csv_path):
                print(f"  오류: {csv_path} 파일이 없습니다. 먼저 1단계를 실행하세요.")
                return
            df = pd.read_csv(csv_path, encoding="utf-8-sig")
        stage4_html(df, today)

    print(f"\n  완료. 출력 파일: Data_{today}.csv  |  Analysis_{today}.md  |  Report_{today}.html")
    print("=" * 110)


if __name__ == "__main__":
    main()
