import sys
import io
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

THRESHOLD_PCT = 2.0
MA_PERIODS = [60, 120, 240]

# NASDAQ 100 수동 메타데이터 (영문명, 한국명, 테마, 한줄 설명)
# 이 딕셔너리에 없는 S&P 500 종목은 Yahoo Finance info에서 자동 취득
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


# ── S&P 500 로드 ──────────────────────────────────────────────

def load_sp500_tickers() -> list[str]:
    """위키피디아에서 S&P 500 구성 종목 티커를 가져옵니다."""
    try:
        import requests
        url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        # pd.read_html 기본 UA는 Wikipedia가 차단 → requests로 직접 요청
        headers = {"User-Agent": "Mozilla/5.0 (compatible; stock-scanner/1.0)"}
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        table = pd.read_html(io.StringIO(resp.text))[0]
        # Yahoo Finance는 '.'를 '-'로 표기 (예: BRK.B → BRK-B)
        tickers = table["Symbol"].str.replace(".", "-", regex=False).tolist()
        print(f"  S&P 500 종목 {len(tickers)}개 로드 완료")
        return tickers
    except Exception as e:
        print(f"  S&P 500 목록 로드 실패: {e}")
        return []


def build_all_tickers() -> list[str]:
    """NASDAQ 100 + S&P 500 합산, 중복 제거 (NASDAQ100 순서 우선)"""
    sp500 = load_sp500_tickers()
    combined = list(NASDAQ100_TICKERS)
    seen = set(combined)
    for ticker in sp500:
        if ticker not in seen:
            combined.append(ticker)
            seen.add(ticker)
    return combined


# ── 보조 지표 계산 ────────────────────────────────────────────

def calc_rsi(close: pd.Series, period: int = 14) -> float | None:
    """Wilder's smoothing 방식 RSI"""
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


# ── 티커 데이터 수집 ─────────────────────────────────────────

def fetch_ticker_data(ticker: str) -> dict | None:
    try:
        end   = datetime.today()
        start = end - timedelta(days=420)   # 240 거래일 확보용

        t  = yf.Ticker(ticker)
        df = t.history(start=start, end=end)

        if df.empty or len(df) < 20:
            return None

        close  = df["Close"]
        volume = df["Volume"]
        current_price = float(close.iloc[-1])

        # ① RSI(14)
        rsi = calc_rsi(close)

        # ② 52주 고가/저가 (최근 252 거래일)
        n = min(252, len(close))
        w52_high = float(close.iloc[-n:].max())
        w52_low  = float(close.iloc[-n:].min())
        from_w52_high = round((current_price - w52_high) / w52_high * 100, 1)

        # ③ 거래량 비율 (전일 vs 20일 평균)
        vol_last  = float(volume.iloc[-1])
        vol_avg20 = float(volume.iloc[-21:-1].mean()) if len(volume) >= 21 else float(volume.mean())
        vol_ratio = round(vol_last / vol_avg20, 2) if vol_avg20 > 0 else None

        # ④ 메타데이터 + 재무지표 (info 한 번만 호출)
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
                kr_name = ticker          # 한국명 없음 → 티커로 표시
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

        # 표시용 이름: 한국명이 있으면 한국명, 없으면 영문명 앞부분
        display_name = kr_name if kr_name != ticker else en_name[:18]

        # ⑤ 이동평균선 (60 / 120 / 240일)
        result = {
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


# ── 출력 ─────────────────────────────────────────────────────

def _f(v, fmt_str: str, none: str = "   -") -> str:
    return fmt_str.format(v) if v is not None else none


def print_ma_table(rows: list[dict], period: int):
    key_diff = f"diff{period}"
    near = [r for r in rows if r[key_diff] is not None and abs(r[key_diff]) <= THRESHOLD_PCT]
    near.sort(key=lambda x: abs(x[key_diff]))

    if not near:
        print(f"\n  [ {period}일선 근접 — 없음 ]")
        return

    W = 110
    print(f"\n  [ {period}일 이동평균선 근접 — {len(near)}개 ]")
    print(f"  {'티커':<7}  {'종목명':<20}  {'현재가':>8}  {'MA차이%':>7}  "
          f"{'RSI':>5}  {'52주고점%':>8}  {'거래량비':>7}  {'PER':>6}  {'업사이드%':>9}")
    print("  " + "-" * W)

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


# ── 메인 ─────────────────────────────────────────────────────

def main():
    SEP = "=" * 110
    print(SEP)
    print(f"  S&P 500 + NASDAQ 100 | 이동평균선 근접 종목 스캔 + 보조 지표")
    print(f"  기준: 60 / 120 / 240일선 각각 ±{THRESHOLD_PCT}% 이내")
    print(f"  기준일: {datetime.today().strftime('%Y-%m-%d')}")
    print(f"  보조 지표: RSI(14) · 52주고점대비% · 거래량비율 · PER · 목표주가 업사이드%")
    print(SEP)

    all_tickers = build_all_tickers()
    total = len(all_tickers)
    sp500_only = total - len(NASDAQ100_TICKERS)
    print(f"  총 {total}개 종목 스캔 시작  "
          f"(NASDAQ 100: {len(NASDAQ100_TICKERS)}개  |  S&P 500 추가: {sp500_only}개)")

    all_data: list[dict] = []

    for i, ticker in enumerate(all_tickers, 1):
        print(f"  ({i:>3}/{total}) {ticker:<7} 조회 중...", end="\r")
        data = fetch_ticker_data(ticker)
        if data:
            all_data.append(data)

    print(" " * 70, end="\r")

    if not all_data:
        print("  데이터를 가져올 수 없습니다.")
        return

    for period in MA_PERIODS:
        print_ma_table(all_data, period)

    # ── CSV 저장 ──────────────────────────────────────────────
    rows_csv = []
    for r in all_data:
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
        rows_csv.append(row)

    df_csv = pd.DataFrame(rows_csv)
    base = f"ma_near_{datetime.today().strftime('%Y%m%d')}"
    output_file = base + ".csv"
    for suffix in ["", "_1", "_2", "_3"]:
        candidate = f"{base}{suffix}.csv"
        try:
            df_csv.to_csv(candidate, index=False, encoding="utf-8-sig")
            output_file = candidate
            break
        except PermissionError:
            continue

    print(f"\n  결과 저장: {output_file}  ({len(all_data)}개 종목)")
    print(SEP)


if __name__ == "__main__":
    main()
