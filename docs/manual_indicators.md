# Indicators Manual

Last updated: 2026-05-06

이 문서는 `uv run python -m market_scanner.analysis.indicators ...` 명령이 시작해서 종료될 때까지 어떤 함수와 DB 테이블을 거치는지 설명합니다.

## 명령어

기본 형태:

```bash
uv run python -m market_scanner.analysis.indicators compute --market us --date 20260505
uv run python -m market_scanner.analysis.indicators compute --market us --from 20260501 --to 20260505
```

`uv`가 현재 셸에서 잡히지 않지만 프로젝트 의존성이 설치된 Python 환경이면 다음처럼 실행할 수 있습니다.

```bash
python3 -m market_scanner.analysis.indicators compute --market us --date 20260505
```

옵션:

| 옵션 | 설명 |
|---|---|
| `--database-url` | PostgreSQL 접속 문자열. 생략하면 `DATABASE_URL` 환경변수 또는 코드 기본값을 사용 |
| `compute` | `daily_prices`에서 `daily_indicators`를 계산하는 하위 명령 |
| `--market` | 필수. `us`, `kospi`, `kosdaq`, `global-indices`, `commodities` 등 시장 key |
| `--date` | 계산 기준일 `YYYYMMDD`. 생략하면 실행일 기준 |
| `--from` | 계산 시작일 `YYYYMMDD`. `--date`와 함께 사용할 수 없음 |
| `--to` | 계산 종료일 `YYYYMMDD`. `--date`와 함께 사용할 수 없음 |
| `--limit` | 앞에서 N개 종목만 처리. 검증용 |

## 실행 위치

CLI 진입점은 `market_scanner/analysis/indicators.py::main()`입니다.

흐름:

1. `argparse.ArgumentParser` 생성
2. 전역 옵션 `--database-url` 등록
3. 하위 명령 `compute` 등록
4. `compute` 명령이면 `run_compute(args.market, args.date, args.database_url, args.limit)` 호출

`Search.py --stage scan` 경로에서도 같은 계산 함수가 호출됩니다.

```text
Search.py
→ market_scanner.pipeline.run_scan_stage_with_settings()
→ collectors.prices.run_fetch()
→ analysis.indicators.run_compute()
→ analysis.screener.run_screen()
```

## 전체 처리 흐름

`run_compute()` 기준 end-to-end 흐름:

1. 기준일 결정
   - `--date`가 있으면 `datetime.strptime(date_str, "%Y%m%d").date()`
   - `--from`/`--to`가 있으면 해당 범위에서 `daily_prices`가 존재하는 날짜만 순서대로 계산
   - 없으면 `date.today()`
2. 가격 소스 라벨 결정
   - `price_source_for_market(market_key)`
   - KOSPI/KOSDAQ은 `fdr`, 그 외 시장은 `yfinance`
3. 시장 설정 로드
   - `MARKETS[market_key]`
   - `price_decimals`를 계산 결과 반올림에 사용
4. DB 연결
   - `connect(explicit_url)`
5. 활성 instruments 조회
   - `instruments.market_key = home_market_key(market_key)`
   - `is_active = TRUE`
   - `ORDER BY symbol`
6. `--limit`이 있으면 대상 종목을 앞에서 N개로 제한
7. `collection_runs`에 `run_type='indicators'`, `status='running'` row 생성
8. 종목별 반복
   - 기준일 가격 row가 `daily_prices`에 있는지 확인
   - 없으면 `skipped += 1` 후 `error_samples`에 `missing_target_price` 샘플 기록
   - 있으면 `compute_for_instrument()` 호출
9. 종목별 계산 결과를 `daily_indicators`에 upsert
10. 실패/스킵 샘플을 `collection_runs.error_samples`에 저장
11. 마지막에 `collection_runs`를 `success`, `partial`, `failed` 중 하나로 업데이트
12. 요약 로그 출력

출력 예:

```text
indicators compute [us] 6543 symbols  run_id=...
    [########----------------] 2400/6543  36.7% success=2320 failed=30 skipped=50
indicators compute [us] done: success=6002 failed=368 skipped=173 status=partial
```

## 주요 함수

| 함수 | 역할 |
|---|---|
| `main()` | CLI 파싱 후 `run_compute()` 호출 |
| `run_compute()` | 시장 전체 지표 계산 orchestration |
| `compute_for_instrument()` | 단일 종목 히스토리 로드, 계산, upsert |
| `_load_price_history()` | `daily_prices`에서 OHLCV 히스토리 조회 |
| `_compute_from_hist()` | pandas DataFrame 기준 전체 지표 계산 |
| `calc_rsi()` | RSI 14 계산 |
| `calc_macd()` | MACD, signal, histogram, state 계산 |
| `calc_bollinger()` | Bollinger Band width, percent B 계산 |
| `calc_trend()` | 추세 점수와 추세 라벨 계산 |
| `calc_candle_type()` | 당일 캔들 타입 분류 |
| `_safe()` | 숫자 변환, NaN 제거, 반올림 |
| `upsert_daily_indicator()` | 계산 결과를 `daily_indicators`에 저장 |

## DB 입력

### instruments

처리 대상은 `instruments`에서 가져옵니다.

```sql
SELECT instrument_id, symbol
FROM instruments
WHERE market_key = %s AND is_active = TRUE
ORDER BY symbol;
```

`market_key`는 `home_market_key()`를 거칩니다. 예를 들어 universe alias가 들어오면 실제 홈 시장으로 맞춥니다.

### daily_prices

종목별 기준일 가격 존재 여부를 먼저 확인합니다.

```sql
SELECT 1
FROM daily_prices
WHERE instrument_id = %s
  AND trade_date = %s
LIMIT 1;
```

기준일 가격이 없으면 해당 종목은 `skipped`입니다.

히스토리 계산에는 같은 종목의 전체 `daily_prices`를 읽습니다.

```sql
SELECT DISTINCT ON (trade_date)
    trade_date, open_price, high_price, low_price, close_price, volume
FROM daily_prices
WHERE instrument_id = %s
  AND trade_date <= %s
ORDER BY trade_date,
    CASE source_provider WHEN 'fdr' THEN 1 WHEN 'yfinance' THEN 2 ELSE 3 END;
```

같은 날짜에 여러 source가 있으면 `fdr`을 우선하고, 다음으로 `yfinance`, 그 외 source 순서입니다.
히스토리는 계산 기준일 이하 가격만 읽습니다. 따라서 과거 날짜를 재계산해도 미래 가격이 섞이지 않습니다.

## 히스토리 전처리

`_load_price_history()`는 DB row를 pandas DataFrame으로 변환합니다.

컬럼:

```text
trade_date, Open, High, Low, Close, Volume
```

처리:

1. `trade_date`를 datetime으로 변환
2. `trade_date`를 index로 설정
3. 모든 OHLCV 값을 numeric 변환
4. `Close`가 없는 row 제거

`compute_for_instrument()`는 히스토리가 비어 있거나 너무 짧으면 실패 처리합니다.

현재 기준:

```python
_MIN_HISTORY = 270
len(hist) < _MIN_HISTORY // 2  # 135개 미만이면 실패
```

즉 최소 135개 이상의 가격 row가 있어야 계산을 시도합니다. 다만 240일 MA는 240개 미만이면 `None`으로 저장될 수 있습니다.

실패 사유는 `collection_runs.error_samples`에 최대 30개까지 샘플로 저장합니다.

| reason | 의미 |
|---|---|
| `missing_target_price` | 기준일 `daily_prices` row가 없어 skipped |
| `empty_price_history` | 기준일 이하 가격 히스토리가 비어 있음 |
| `insufficient_history` | 기준일 이하 히스토리가 135개 미만 |
| `compute_empty` | 히스토리는 있으나 계산 결과가 비어 있음 |

## 계산 지표

### 당일 가격/변동

`_compute_from_hist()`는 히스토리의 마지막 row를 현재 시점으로 봅니다.

계산값:

| 결과 key | 설명 |
|---|---|
| `change_pct` | 전일 종가 대비 현재 종가 변화율 |
| `gap_pct` | 전일 종가 대비 당일 시가 gap |
| `candle_body_pct` | 시가 대비 종가 변화율 |
| `candle_range_pct` | 시가 대비 고가-저가 범위 |
| `upper_shadow_pct` | 시가 대비 윗꼬리 비율 |
| `lower_shadow_pct` | 시가 대비 아랫꼬리 비율 |

### RSI

`calc_rsi(close, period=14)`에서 계산합니다.

방식:

1. 종가 차분 `delta`
2. 상승분 `gain`, 하락분 `loss`
3. Wilder 방식에 가까운 EWM 평균
4. `RS = avg_gain / avg_loss`
5. `RSI = 100 - (100 / (1 + RS))`

데이터가 `period + 1`개 미만이면 `None`입니다. 마지막 평균 손실이 0이면 `100.0`입니다.

### 이동평균선

기간:

```python
_MA_PERIODS = (5, 20, 60, 120, 240)
```

각 기간별 계산:

| 결과 key | 설명 |
|---|---|
| `ma_5`, `ma_20`, `ma_60`, `ma_120`, `ma_240` | 각 기간 rolling mean |
| `diff_5`, `diff_20`, `diff_60`, `diff_120`, `diff_240` | 현재가가 해당 MA에서 얼마나 떨어져 있는지 |
| `near_5`, `near_20`, `near_60`, `near_120`, `near_240` | MA 근접 여부 |

근접 기준:

```python
_MA_THRESHOLD_PCT = 3.0
abs(diff_pct) <= 3.0
```

### MACD

`calc_macd(close, fast=12, slow=26, signal=9)`에서 계산합니다.

계산값:

| 결과 key | 설명 |
|---|---|
| `macd` | 12 EMA - 26 EMA |
| `macd_signal` | MACD line의 9 EMA |
| `macd_hist` | MACD - signal |
| `macd_state` | histogram 방향성 분류 |

`macd_state` 분류:

| 조건 | state |
|---|---|
| hist > 0 and hist >= prev_hist | `Bullish` |
| hist > 0 and hist < prev_hist | `Positive` |
| hist <= 0 and hist > prev_hist | `Improving` |
| 그 외 | `Bearish` |

데이터가 `slow + signal`개 미만이면 `Unknown`입니다.

### Bollinger Band

`calc_bollinger(close, period=20, deviations=2.0)`에서 계산합니다.

계산값:

| 결과 key | 설명 |
|---|---|
| `bollinger_width_pct` | `(upper - lower) / basis * 100` |
| `bollinger_percent_b` | `(current - lower) / (upper - lower)` |

rolling basis는 20일 평균, band 폭은 표준편차 2배입니다.

### 52주 고저

현재 히스토리 길이와 252 중 작은 값을 사용합니다.

```python
trailing_window = min(252, len(close))
high_52w = max(high[-trailing_window:])
low_52w = min(low[-trailing_window:])
```

계산값:

| 결과 key | 설명 |
|---|---|
| `high_52w` | 최근 최대 종가 |
| `low_52w` | 최근 최소 종가 |
| `from_high_pct` | 52주 고점 대비 현재가 괴리율 |
| `from_low_pct` | 52주 저점 대비 현재가 상승률 |

### 20/60일 고저와 돌파

20/60거래일 종가 고저와 직전 고점 돌파 여부를 계산합니다.

| 결과 key | 설명 |
|---|---|
| `high_20d`, `low_20d` | 최근 20거래일 종가 고저 |
| `high_60d`, `low_60d` | 최근 60거래일 종가 고저 |
| `breakout_20d` | 현재가가 직전 20거래일 고점을 넘었는지 |
| `breakout_60d` | 현재가가 직전 60거래일 고점을 넘었는지 |

### 기간별 수익률

현재 종가와 N거래일 전 종가를 비교합니다.

| 결과 key | 설명 |
|---|---|
| `return_5d` | 5거래일 수익률 |
| `return_20d` | 20거래일 수익률 |
| `return_60d` | 60거래일 수익률 |
| `return_120d` | 120거래일 수익률 |
| `return_240d` | 240거래일 수익률 |

### ATR과 변동성

`atr14`는 14일 True Range 평균입니다. `atr14_pct`는 현재가 대비 ATR 비율입니다.

20/60일 변동성은 일간 수익률 표준편차를 연율화해서 저장합니다.

```python
volatility = std(daily_return, window=N) * sqrt(252) * 100
```

| 결과 key | 설명 |
|---|---|
| `atr14` | 14일 ATR |
| `atr14_pct` | 현재가 대비 ATR 비율 |
| `volatility_20d` | 20일 연율화 변동성 |
| `volatility_60d` | 60일 연율화 변동성 |

### 거래량 비율

계산:

```python
volume_ratio = last_volume / average(volume[-21:-1])
```

즉 당일 거래량을 직전 20개 거래일 평균 거래량과 비교합니다.

### 캔들 타입

`calc_candle_type()`에서 Open, High, Low, Close로 분류합니다.

가능한 값:

```text
Unknown
Flat
Long Lower Doji
Long Upper Doji
Doji
Bullish Reversal
Bearish Rejection
Strong Bullish
Strong Bearish
Bullish
Bearish
```

핵심 기준:

| 조건 | candle_type |
|---|---|
| range <= 0 | `Flat` |
| body_ratio <= 0.12 and lower_shadow >= 0.45 | `Long Lower Doji` |
| body_ratio <= 0.12 and upper_shadow >= 0.45 | `Long Upper Doji` |
| body_ratio <= 0.12 | `Doji` |
| 양봉 and lower_shadow >= 0.45 | `Bullish Reversal` |
| 음봉 and upper_shadow >= 0.45 | `Bearish Rejection` |
| 양봉 and body_ratio >= 0.65 | `Strong Bullish` |
| 음봉 and body_ratio >= 0.65 | `Strong Bearish` |
| 양봉 | `Bullish` |
| 음봉 | `Bearish` |

### 추세 점수

`calc_trend()`에서 0~5점으로 계산합니다.
5/20일선은 단기 지표로 저장하지만, 기존 스코어링 의미를 유지하기 위해 추세 점수는 60/120/240일선 기준으로 계산합니다.

점수 조건:

| 조건 | 점수 |
|---|---|
| 현재가 > MA60 | +1 |
| MA60 > MA120 | +1 |
| MA120 > MA240 | +1 |
| MA60이 20거래일 전보다 상승 | +1 |
| MA120이 20거래일 전보다 상승 | +1 |

라벨:

| 점수 | trend |
|---|---|
| 5 | `Strong Uptrend` |
| 4 | `Uptrend` |
| 3 | `Neutral` |
| 2 | `Downtrend` |
| 1 | `Strong Downtrend` |
| 0 | `Strong Downtrend` |

## DB 출력

계산 결과는 `market_scanner.storage.indicators.upsert_daily_indicator()`를 통해 `daily_indicators`에 저장됩니다.

Primary key:

```text
(instrument_id, trade_date)
```

이미 같은 종목/날짜 row가 있으면 update합니다.

저장 컬럼 매핑:

| 계산 key | DB 컬럼 |
|---|---|
| `rsi` | `rsi14` |
| `ma_5` | `ma5` |
| `ma_20` | `ma20` |
| `ma_60` | `ma60` |
| `ma_120` | `ma120` |
| `ma_240` | `ma240` |
| `diff_5` | `diff_5_pct` |
| `diff_20` | `diff_20_pct` |
| `diff_60` | `diff_60_pct` |
| `diff_120` | `diff_120_pct` |
| `diff_240` | `diff_240_pct` |
| `near_5` | `near_5` |
| `near_20` | `near_20` |
| `near_60` | `near_60` |
| `near_120` | `near_120` |
| `near_240` | `near_240` |
| `macd` | `macd` |
| `macd_signal` | `macd_signal` |
| `macd_hist` | `macd_hist` |
| `macd_state` | `macd_state` |
| `bollinger_width_pct` | `bollinger_width_pct` |
| `bollinger_percent_b` | `bollinger_percent_b` |
| `high_52w` | `high_52w` |
| `low_52w` | `low_52w` |
| `from_high_pct` | `from_high_pct` |
| `from_low_pct` | `from_low_pct` |
| `high_20d` | `high_20d` |
| `low_20d` | `low_20d` |
| `high_60d` | `high_60d` |
| `low_60d` | `low_60d` |
| `breakout_20d` | `breakout_20d` |
| `breakout_60d` | `breakout_60d` |
| `volume_ratio` | `volume_ratio` |
| `return_5d` | `return_5d` |
| `return_20d` | `return_20d` |
| `return_60d` | `return_60d` |
| `return_120d` | `return_120d` |
| `return_240d` | `return_240d` |
| `atr14` | `atr14` |
| `atr14_pct` | `atr14_pct` |
| `volatility_20d` | `volatility_20d` |
| `volatility_60d` | `volatility_60d` |
| `change_pct` | `change_pct` |
| `gap_pct` | `gap_pct` |
| `candle_body_pct` | `candle_body_pct` |
| `candle_range_pct` | `candle_range_pct` |
| `upper_shadow_pct` | `upper_shadow_pct` |
| `lower_shadow_pct` | `lower_shadow_pct` |
| `candle_type` | `candle_type` |
| `trend` | `trend` |
| `trend_score` | `trend_score` |

추가 저장값:

| DB 컬럼 | 설명 |
|---|---|
| `instrument_id` | 종목 PK |
| `trade_date` | 계산 기준일 |
| `price_source_provider` | 시장 기본 가격 source 라벨 |
| `run_id` | `collection_runs` 실행 ID |
| `calculated_at` | insert/update 시각 |

## collection_runs

실행 시작 시 row를 생성합니다.

```text
run_type = indicators
status = running
requested_count = 대상 instruments 수
params = {"mode": "compute"}
```

종료 시 업데이트:

| status | 조건 |
|---|---|
| `success` | failed와 skipped가 모두 0 |
| `partial` | success가 있고 failed 또는 skipped가 있음 |
| `failed` | success가 0이고 failed 또는 skipped가 있음 |

`skipped`는 기준일 가격 row가 없는 종목 수입니다. 현재는 skipped가 1개 이상이면 실행 상태가 `partial` 또는 `failed`에 반영됩니다.

## 날짜 사용 시 주의점

`run_compute()`는 기준일 `trade_date`에 가격 row가 있는지 확인한 뒤 계산합니다. `_load_price_history()`는 `trade_date <= 기준일` 조건으로 히스토리를 읽습니다.

운영에서는 `--date`를 해당 시장의 최신 가격일로 맞추는 것을 권장합니다. 과거 날짜로 재계산할 경우에도 미래 가격이 섞이지는 않지만, 해당 과거 날짜 기준 지표 row만 upsert됩니다.

최신 US 가격일 확인:

```bash
psql postgresql://searchmarket:searchmarket@localhost:5433/searchmarket -At -c "SELECT max(p.trade_date) FROM daily_prices p JOIN instruments i ON i.instrument_id = p.instrument_id WHERE i.market_key = 'us';"
```

확인한 날짜가 `2026-05-05`이면:

```bash
python3 -m market_scanner.analysis.indicators compute --market us --date 20260505
```

## 실행 후 검증 쿼리

최근 indicators run:

```bash
psql postgresql://searchmarket:searchmarket@localhost:5433/searchmarket -c "SELECT run_id, status, requested_count, success_count, failed_count, skipped_count, started_at, finished_at FROM collection_runs WHERE market_key='us' AND run_type='indicators' ORDER BY started_at DESC LIMIT 5;"
```

기준일 지표 row 수:

```bash
psql postgresql://searchmarket:searchmarket@localhost:5433/searchmarket -c "SELECT count(*) FROM daily_indicators di JOIN instruments i ON i.instrument_id = di.instrument_id WHERE i.market_key='us' AND di.trade_date='2026-05-05';"
```

가격은 있지만 지표가 없는 종목:

```bash
psql postgresql://searchmarket:searchmarket@localhost:5433/searchmarket -c "SELECT i.symbol, i.name_en FROM instruments i JOIN daily_prices p ON p.instrument_id = i.instrument_id AND p.trade_date='2026-05-05' LEFT JOIN daily_indicators di ON di.instrument_id = i.instrument_id AND di.trade_date='2026-05-05' WHERE i.market_key='us' AND i.is_active = true AND di.instrument_id IS NULL ORDER BY i.symbol;"
```

기준일 가격이 없어 skipped될 종목:

```bash
psql postgresql://searchmarket:searchmarket@localhost:5433/searchmarket -c "SELECT i.symbol, i.name_en FROM instruments i LEFT JOIN daily_prices p ON p.instrument_id = i.instrument_id AND p.trade_date='2026-05-05' WHERE i.market_key='us' AND i.is_active = true AND p.instrument_id IS NULL ORDER BY i.symbol;"
```

## 다음 단계

지표 계산이 끝나면 스크리너를 실행합니다.

```bash
python3 -m market_scanner.analysis.screener run --market us --date 20260505
```

그 다음 리포트를 렌더링합니다.

```bash
python3 -m market_scanner.reports.render build --market us --date 20260505
```

## Indicator Calculation Updates

- `calc_rsi()` seeds average gain/loss with an initial SMA over `period`, then applies Wilder smoothing.
- `high_52w` now uses the trailing 252-session High column. `low_52w` uses the trailing 252-session Low column.
- `breakout_20d` and `breakout_60d` are close-price breakouts above the prior 20/60-session High.
- `breakout_high_20d` and `breakout_high_60d` are intraday High breakouts above the prior 20/60-session High.
- `atr14` uses Wilder smoothing over True Range instead of a simple rolling average.
- Added traded value, prior-volume averages, value ratio, MA alignment/slope, RSI previous/change, RSI2/5/30, RSI14 MA5, MACD cross/hist-change, explicit new-high flags, and close position in 20/60-day ranges.
