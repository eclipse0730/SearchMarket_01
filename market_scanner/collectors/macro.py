"""FRED, yfinance, CoinGecko, alternative.me, pykrx에서 매크로 지표를 수집해 daily_macro에 저장."""

from __future__ import annotations

import io
import os
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

from market_scanner.storage.connection import connect
from market_scanner.storage.macro import last_macro_date, upsert_daily_macro

_FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"
_KOFIA_MAIN = "https://freesis.kofia.or.kr/stat/main.do"
_CG_MARKET_CHART = "https://api.coingecko.com/api/v3/coins/{id}/market_chart"
_CG_GLOBAL = "https://api.coingecko.com/api/v3/global"
_FNG_URL = "https://api.alternative.me/fng/"
_TIMEOUT = 15

# 지표가 처음 수집될 때 얼마나 과거까지 소급할지
_DEFAULT_DAYS_BACK = 90

# ─── FRED 시리즈 목록 ─────────────────────────────────────────────────────────
# (FRED 시리즈 ID, indicator_code)
_FRED_SERIES: list[tuple[str, str]] = [
    # 금리
    ("SOFR",          "SOFR"),             # 무담보 익일물 금리
    ("DFF",           "US_FFR"),           # 연방기금 실효금리
    ("DGS2",          "US_2Y"),            # 미국 2년 국채 금리
    ("DGS10",         "US_10Y"),           # 미국 10년 국채 금리
    ("DGS30",         "US_30Y"),           # 미국 30년 국채 금리
    # 장단기 스프레드 (FRED가 직접 산출하는 시리즈)
    ("T10Y2Y",        "US_SPREAD_2S10S"),  # 10년 - 2년
    ("T10Y3M",        "US_SPREAD_3M10Y"), # 10년 - 3개월
    # 신용 스프레드 (ICE BofA 지수 기반, 일간)
    ("BAMLH0A0HYM2",  "HY_OAS"),           # 하이일드 OAS
    ("BAMLC0A0CM",    "IG_OAS"),           # 투자등급 OAS
    # 유동성
    ("RRPTTLD",       "FED_RRP"),          # 익일물 역레포 잔고 (일간)
    ("WALCL",         "FED_BS"),           # 연준 총자산 (주간·목요일 기준)
    # 환율 보조 소스 (1영업일 lag이 있어 yfinance를 우선 사용)
    ("DEXKOUS",       "USDKRW_FRED"),
    # Korea rates (FRED OECD/IMF monthly proxy series)
    ("IRLTLT01KRM156N", "KR_10Y"),
    ("IR3TIB01KRM156N", "KR_INTERBANK_3M"),
    ("IRSTCI01KRM156N", "KR_CALL_RATE"),
    ("INTDSRKRM193N", "KR_DISCOUNT_RATE"),
]

# ─── yfinance 심볼 목록 ───────────────────────────────────────────────────────
# 주요 주가지수: 메인 페이지 상단 핵심 지표용
_YF_INDICES: list[tuple[str, str]] = [
    ("^GSPC", "SP500"),
    ("^NDX", "NASDAQ100"),
    ("^KS11", "KOSPI"),
    ("^KQ11", "KOSDAQ"),
]

# 환율: DXY는 FRED에 없으므로 yfinance 전용
_YF_FX: list[tuple[str, str]] = [
    ("USDKRW=X", "USDKRW"),
    ("EURUSD=X", "EURUSD"),
    ("USDJPY=X", "USDJPY"),
    ("USDCNH=X", "USDCNY"),
    ("GBPUSD=X", "GBPUSD"),
    ("AUDUSD=X", "AUDUSD"),
    ("NZDUSD=X", "NZDUSD"),
    ("USDCAD=X", "USDCAD"),
    ("USDCHF=X", "USDCHF"),
    ("USDSGD=X", "USDSGD"),
    ("USDSEK=X", "USDSEK"),
    ("USDNOK=X", "USDNOK"),
    ("USDMXN=X", "USDMXN"),
    ("DX-Y.NYB", "DXY"),
]

# 원자재 선물: 월 롤오버 시 연속월물 교체로 spike가 생길 수 있음
_YF_COMMODITIES: list[tuple[str, str]] = [
    ("CL=F", "WTI"),
    ("GC=F", "GOLD"),
    ("SI=F", "SILVER"),
    ("NG=F", "NATGAS"),
    ("HG=F", "COPPER"),
]

# 시장 심리
_YF_SENTIMENT: list[tuple[str, str]] = [
    ("^VIX",   "VIX"),
    ("^VVIX",  "VVIX"),
    # CoinGecko market_chart는 유료 전환됨 → yfinance로 대체
    ("BTC-USD", "BTC_USD"),
    ("ETH-USD", "ETH_USD"),
]

_KRX_MARKETS: list[tuple[str, str]] = [
    ("KOSPI", "KR_KOSPI"),
    ("KOSDAQ", "KR_KOSDAQ"),
]

# ─── CoinGecko (무료 엔드포인트만 사용) ──────────────────────────────────────
# /coins/{id}/market_chart 는 유료 전환됨 → BTC/ETH는 yfinance 사용
_CG_COINS: list[tuple[str, str]] = [
    # 히스토리 수집 불가로 비워둠
]


# ─── 내부 유틸 ────────────────────────────────────────────────────────────────

def _load_dotenv() -> None:
    """프로젝트 루트의 .env 파일을 읽어 환경 변수가 없으면 채워준다.
    python-dotenv 의존성 없이 직접 파싱한다."""
    env_path = Path(__file__).parents[2] / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = val.strip()


def _fred_api_key() -> str | None:
    _load_dotenv()
    key = os.getenv("FRED_API_KEY")
    if not key or key.startswith("your_"):
        return None
    return key


def _start_date_for(
    conn,
    indicator_code: str,
    source_provider: str,
    end_date: date,
    days_back: int,
) -> date:
    """마지막 수집일의 다음 날을 반환. 수집 이력이 없으면 days_back 전부터 시작."""
    last = last_macro_date(conn, indicator_code, source_provider)
    if last is None:
        return end_date - timedelta(days=days_back)
    return last + timedelta(days=1)


# ─── 데이터 소스별 fetch ─────────────────────────────────────────────────────

def _fetch_fred(
    series_id: str,
    start_date: date,
    end_date: date,
    api_key: str,
) -> list[tuple[date, float]]:
    """FRED REST API에서 단일 시리즈의 (날짜, 값) 목록을 가져온다."""
    resp = requests.get(
        _FRED_BASE,
        params={
            "series_id": series_id,
            "api_key": api_key,
            "observation_start": start_date.isoformat(),
            "observation_end": end_date.isoformat(),
            "file_type": "json",
        },
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    rows: list[tuple[date, float]] = []
    for obs in resp.json().get("observations", []):
        val = obs.get("value", ".")
        if val == ".":  # FRED 결측값 표시
            continue
        try:
            rows.append((date.fromisoformat(obs["date"]), float(val)))
        except (KeyError, ValueError):
            continue
    return rows


def _fetch_yf_close(
    symbol: str,
    start_date: date,
    end_date: date,
) -> list[tuple[date, float]]:
    """yfinance에서 심볼의 일별 종가 목록을 가져온다."""
    try:
        import yfinance as yf
    except ImportError:
        return []
    try:
        # yfinance가 stdout/stderr에 경고를 출력하지 않도록 억제
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            hist = yf.Ticker(symbol).history(
                start=start_date.isoformat(),
                end=(end_date + timedelta(days=1)).isoformat(),
                auto_adjust=True,
                timeout=_TIMEOUT,
            )
    except Exception:
        return []
    if hist.empty:
        return []
    rows: list[tuple[date, float]] = []
    for idx, row in hist.iterrows():
        d = idx.date() if hasattr(idx, "date") else idx
        try:
            rows.append((d, float(row["Close"])))
        except (KeyError, TypeError, ValueError):
            continue
    return rows


def _fetch_cg_history(coin_id: str, days: int) -> list[tuple[date, float]]:
    """CoinGecko market_chart에서 코인의 일별 USD 종가를 가져온다.

    CoinGecko 무료 API는 days > 90 일 때만 일간 데이터를 반환하므로
    요청 일수를 최소 91로 올린다. 호출 결과는 start~end 범위로 필터링한다.
    """
    actual_days = max(days, 91)
    resp = requests.get(
        _CG_MARKET_CHART.format(id=coin_id),
        params={"vs_currency": "usd", "days": actual_days},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    rows: list[tuple[date, float]] = []
    seen: set[date] = set()
    for ts_ms, price in resp.json().get("prices", []):
        # 밀리초 UTC 타임스탬프 → date
        d = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).date()
        if d not in seen:
            seen.add(d)
            rows.append((d, float(price)))
    return rows


def _fetch_cg_total_mcap() -> float | None:
    """CoinGecko /global에서 전체 암호화폐 시가총액(USD)을 가져온다."""
    resp = requests.get(_CG_GLOBAL, timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp.json().get("data", {}).get("total_market_cap", {}).get("usd")


def _fetch_fear_greed(limit: int) -> list[tuple[date, float]]:
    """alternative.me에서 크립토 공포·탐욕 지수 시계열을 가져온다."""
    resp = requests.get(_FNG_URL, params={"limit": limit}, timeout=_TIMEOUT)
    resp.raise_for_status()
    rows: list[tuple[date, float]] = []
    for item in resp.json().get("data", []):
        try:
            d = datetime.fromtimestamp(int(item["timestamp"]), tz=timezone.utc).date()
            rows.append((d, float(item["value"])))
        except (KeyError, ValueError):
            continue
    return rows


def _date_range(start_date: date, end_date: date) -> list[date]:
    days = (end_date - start_date).days
    return [start_date + timedelta(days=i) for i in range(days + 1)]


def _to_date(value) -> date:
    return value.date() if hasattr(value, "date") else value


def _fetch_krx_market_investor_flows(
    market: str,
    prefix: str,
    start_date: date,
    end_date: date,
) -> dict[str, list[tuple[date, float]]]:
    """KOSPI/KOSDAQ 전체 투자자별 순매수 거래대금."""
    from pykrx import stock

    start = start_date.strftime("%Y%m%d")
    end = end_date.strftime("%Y%m%d")
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        frame = stock.get_market_trading_value_by_date(start, end, market, on="순매수")
    if frame.empty:
        return {}

    targets = {
        "기관합계": f"{prefix}_INSTITUTION_NET_BUY_VALUE",
        "외국인합계": f"{prefix}_FOREIGN_NET_BUY_VALUE",
    }
    results: dict[str, list[tuple[date, float]]] = {}
    for column, code in targets.items():
        if column not in frame.columns:
            continue
        rows: list[tuple[date, float]] = []
        for idx, value in frame[column].items():
            try:
                rows.append((_to_date(idx), float(value)))
            except (TypeError, ValueError):
                continue
        results[code] = rows
    return results


def _sum_column(frame, candidates: list[str]) -> float | None:
    if frame.empty:
        return None
    for column in candidates:
        if column in frame.columns:
            total = 0.0
            for value in frame[column]:
                text = str(value).replace(",", "").strip()
                if not text or text in {"-", "nan", "None"}:
                    continue
                try:
                    total += float(text)
                except ValueError:
                    continue
            return float(total)
    return None


def _fetch_krx_shorting_market(
    market: str,
    prefix: str,
    start_date: date,
    end_date: date,
) -> dict[str, list[tuple[date, float]]]:
    """KOSPI/KOSDAQ 전체 공매도 거래대금과 잔고금액."""
    from pykrx import stock

    short_value_rows: list[tuple[date, float]] = []
    balance_value_rows: list[tuple[date, float]] = []

    for d in _date_range(start_date, end_date):
        if d.weekday() >= 5:
            continue
        day = d.strftime("%Y%m%d")
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            value_frame = stock.get_shorting_value_by_ticker(day, market=market)
        short_value = _sum_column(value_frame, ["공매도", "공매도거래대금", "거래대금"])
        if short_value is not None:
            short_value_rows.append((d, short_value))

        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            balance_frame = stock.get_shorting_balance_by_ticker(day, market=market)
        balance_value = _sum_column(balance_frame, ["공매도금액", "잔고금액"])
        if balance_value is not None:
            balance_value_rows.append((d, balance_value))

    return {
        f"{prefix}_SHORT_SELL_VALUE": short_value_rows,
        f"{prefix}_SHORT_BALANCE_VALUE": balance_value_rows,
    }


def _parse_kofia_snapshot_date(text: str, end_date: date) -> date | None:
    try:
        raw_date = text.split("|", 1)[1].strip() if "|" in text else text.strip()
        month_text, day_text = raw_date.split("/", 1)
        d = date(end_date.year, int(month_text), int(day_text))
        if d > end_date:
            d = date(end_date.year - 1, int(month_text), int(day_text))
        return d
    except (IndexError, TypeError, ValueError):
        return None


def _parse_first_number(text: str) -> float | None:
    try:
        return float(text.split()[0].replace(",", ""))
    except (IndexError, TypeError, ValueError):
        return None


def _fetch_kofia_market_fund_snapshots(end_date: date) -> dict[str, list[tuple[date, float]]]:
    """FreeSIS 메인 최신 스냅샷에서 투자자예탁금/신용융자를 가져온다.

    FreeSIS는 메인 화면에 값을 백만원 단위로 노출한다. 히스토리 백필용 API가
    아니라서, 매일 실행하면서 최신 공표치를 누적 저장하는 용도다.
    """
    from lxml import html

    resp = requests.get(_KOFIA_MAIN, timeout=_TIMEOUT)
    resp.raise_for_status()
    doc = html.fromstring(resp.content)
    texts = [t.strip() for t in doc.xpath("//text()") if t.strip()]

    targets = {
        "투자자예탁금": "KR_CUSTOMER_DEPOSIT_VALUE",
        "신용융자": "KR_CREDIT_BALANCE_VALUE",
    }
    results: dict[str, list[tuple[date, float]]] = {}
    for label, code in targets.items():
        for idx, text in enumerate(texts):
            if text != label or idx + 4 >= len(texts):
                continue
            if texts[idx + 2] == "|":
                snapshot_date = _parse_kofia_snapshot_date(texts[idx + 3], end_date)
                value = _parse_first_number(texts[idx + 4])
            else:
                snapshot_date = _parse_kofia_snapshot_date(texts[idx + 1], end_date)
                value = _parse_first_number(texts[idx + 2])
            if snapshot_date is None or value is None or snapshot_date > end_date:
                break
            results[code] = [(snapshot_date, value)]
            break
    return results


# ─── 저장 ────────────────────────────────────────────────────────────────────

def _store(
    conn,
    indicator_code: str,
    source_provider: str,
    rows: list[tuple[date, float]],
) -> int:
    """(날짜, 값) 목록을 날짜 순으로 정렬한 뒤 daily_macro에 upsert하고 건수를 반환.

    prev_value와 change_pct는 같은 배치 내의 직전 행으로 계산한다.
    """
    if not rows:
        return 0
    rows = sorted(rows, key=lambda x: x[0])
    prev_val: float | None = None
    count = 0
    for trade_date, value in rows:
        change_pct = None
        if prev_val is not None and prev_val != 0:
            change_pct = (value - prev_val) / abs(prev_val) * 100
        upsert_daily_macro(
            conn,
            indicator_code=indicator_code,
            trade_date=trade_date,
            source_provider=source_provider,
            value=value,
            prev_value=prev_val,
            change_pct=change_pct,
        )
        prev_val = value
        count += 1
    return count


# ─── 공개 진입점 ─────────────────────────────────────────────────────────────

def run_fetch(
    date_str: str | None = None,
    date_from: str | None = None,
    database_url: str | None = None,
    days_back: int = _DEFAULT_DAYS_BACK,
) -> None:
    """매크로 지표를 수집해 daily_macro에 저장한다.

    date_from이 주어지면 모든 지표를 해당 날짜부터 강제 수집한다 (증분 로직 무시).
    date_from이 없으면 각 지표의 마지막 수집일 다음 날부터 증분 수집한다.
    이력이 전혀 없는 지표는 days_back일 전부터 시작한다.
    """
    end_date = (
        datetime.strptime(date_str, "%Y%m%d").date()
        if date_str
        else date.today()
    )
    # --from이 있으면 모든 지표에 동일한 시작일을 강제 적용
    forced_start: date | None = (
        datetime.strptime(date_from, "%Y%m%d").date() if date_from else None
    )

    api_key = _fred_api_key()
    if not api_key:
        print("  경고: FRED_API_KEY 없음 — FRED 지표를 건너뜁니다.")
    _load_dotenv()
    if not os.getenv("KRX_ID") or not os.getenv("KRX_PW"):
        print("  경고: KRX_ID/KRX_PW 없음 — pykrx KRX 인증 지표가 실패할 수 있습니다.")

    total = 0
    conn = connect(database_url)

    def _start(code: str, provider: str) -> date:
        if forced_start is not None:
            return forced_start
        return _start_date_for(conn, code, provider, end_date, days_back)
    try:
        # ── 1. FRED: 금리·금리차·신용 스프레드·유동성·환율 보조 ──────────────
        if api_key:
            for series_id, code in _FRED_SERIES:
                start = _start(code, "FRED")
                if start > end_date:
                    continue
                try:
                    rows = _fetch_fred(series_id, start, end_date, api_key)
                    n = _store(conn, code, "FRED", rows)
                    print(f"  FRED  {code:<22} {n:>4}건")
                    total += n
                except Exception as e:
                    print(f"  FRED  {code} 실패: {e}")

        # ── 2. yfinance: 주요 주가지수 ────────────────────────────────────
        for symbol, code in _YF_INDICES:
            start = _start(code, "yfinance")
            if start > end_date:
                continue
            try:
                rows = _fetch_yf_close(symbol, start, end_date)
                n = _store(conn, code, "yfinance", rows)
                print(f"  yf    {code:<22} {n:>4}건")
                total += n
            except Exception as e:
                print(f"  yf    {code} 실패: {e}")

        # ── 3. yfinance: 환율 ──────────────────────────────────────────────
        for symbol, code in _YF_FX:
            start = _start(code, "yfinance")
            if start > end_date:
                continue
            try:
                rows = _fetch_yf_close(symbol, start, end_date)
                n = _store(conn, code, "yfinance", rows)
                print(f"  yf    {code:<22} {n:>4}건")
                total += n
            except Exception as e:
                print(f"  yf    {code} 실패: {e}")

        # ── 4. yfinance: 원자재 선물 ───────────────────────────────────────
        for symbol, code in _YF_COMMODITIES:
            start = _start(code, "yfinance")
            if start > end_date:
                continue
            try:
                rows = _fetch_yf_close(symbol, start, end_date)
                n = _store(conn, code, "yfinance", rows)
                print(f"  yf    {code:<22} {n:>4}건")
                total += n
            except Exception as e:
                print(f"  yf    {code} 실패: {e}")

        # ── 5. yfinance: 심리 지표 (VIX, VVIX) ───────────────────────────
        for symbol, code in _YF_SENTIMENT:
            start = _start(code, "yfinance")
            if start > end_date:
                continue
            try:
                rows = _fetch_yf_close(symbol, start, end_date)
                n = _store(conn, code, "yfinance", rows)
                print(f"  yf    {code:<22} {n:>4}건")
                total += n
            except Exception as e:
                print(f"  yf    {code} 실패: {e}")

        # ── 6. pykrx: 한국 시장 전체 투자자 수급 ─────────────────────────
        for market, prefix in _KRX_MARKETS:
            start = min(
                _start(f"{prefix}_INSTITUTION_NET_BUY_VALUE", "pykrx"),
                _start(f"{prefix}_FOREIGN_NET_BUY_VALUE", "pykrx"),
            )
            if start > end_date:
                continue
            try:
                results = _fetch_krx_market_investor_flows(market, prefix, start, end_date)
                for code, rows in results.items():
                    n = _store(conn, code, "pykrx", rows)
                    print(f"  pykrx {code:<28} {n:>4}건")
                    total += n
            except Exception as e:
                print(f"  pykrx {prefix}_INVESTOR_FLOW 실패: {e}")

        # ── 7. pykrx: 한국 시장 전체 공매도 거래대금·잔고금액 ─────────────
        for market, prefix in _KRX_MARKETS:
            start = min(
                _start(f"{prefix}_SHORT_SELL_VALUE", "pykrx"),
                _start(f"{prefix}_SHORT_BALANCE_VALUE", "pykrx"),
            )
            if start > end_date:
                continue
            try:
                results = _fetch_krx_shorting_market(market, prefix, start, end_date)
                for code, rows in results.items():
                    n = _store(conn, code, "pykrx", rows)
                    print(f"  pykrx {code:<28} {n:>4}건")
                    total += n
            except Exception as e:
                print(f"  pykrx {prefix}_SHORTING 실패: {e}")

        # ── 8. FreeSIS: 한국 증시 대기자금·신용융자 최신 스냅샷 ─────────
        try:
            results = _fetch_kofia_market_fund_snapshots(end_date)
            for code, rows in results.items():
                start = _start(code, "KOFIA")
                rows = [(d, v) for d, v in rows if start <= d <= end_date]
                n = _store(conn, code, "KOFIA", rows)
                print(f"  kofia {code:<27} {n:>4}건")
                total += n
        except Exception as e:
            print(f"  kofia KR_MARKET_FUNDS 실패: {e}")

        # ── 9. CoinGecko: BTC·ETH 가격 ────────────────────────────────────
        for coin_id, code in _CG_COINS:
            start = _start(code, "coingecko")
            if start > end_date:
                continue
            try:
                delta = (end_date - start).days + 1
                rows = _fetch_cg_history(coin_id, delta)
                rows = [(d, v) for d, v in rows if start <= d <= end_date]
                n = _store(conn, code, "coingecko", rows)
                print(f"  cg    {code:<22} {n:>4}건")
                total += n
            except Exception as e:
                print(f"  cg    {code} 실패: {e}")

        # ── 10. CoinGecko: 전체 암호화폐 시가총액 ────────────────────────
        # /global은 현재 스냅샷만 제공하므로 오늘 날짜로 저장
        code = "CRYPTO_TOTAL_MCAP"
        start = _start(code, "coingecko")
        if start <= end_date:
            try:
                mcap = _fetch_cg_total_mcap()
                if mcap:
                    n = _store(conn, code, "coingecko", [(end_date, mcap)])
                    print(f"  cg    {code:<22} {n:>4}건")
                    total += n
            except Exception as e:
                print(f"  cg    {code} 실패: {e}")

        # ── 11. alternative.me: 크립토 공포·탐욕 지수 ────────────────────
        code = "CRYPTO_FNG"
        start = _start(code, "alternative.me")
        if start <= end_date:
            try:
                limit = (end_date - start).days + 1
                rows = _fetch_fear_greed(limit)
                rows = [(d, v) for d, v in rows if start <= d <= end_date]
                n = _store(conn, code, "alternative.me", rows)
                print(f"  fng   {code:<22} {n:>4}건")
                total += n
            except Exception as e:
                print(f"  fng   {code} 실패: {e}")

        conn.commit()
        print(f"\n  총 {total}건 저장 완료")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
