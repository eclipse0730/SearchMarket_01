# Prices Collector Manual

Last updated: 2026-05-07

`market_scanner.collectors.prices`는 종목별 일봉 OHLCV를 수집해 PostgreSQL `daily_prices`에 저장하는 가격 수집기입니다. `refresh-master`로 `instruments`가 준비된 뒤 실행하며, 이후 `daily_indicators` 계산과 screener의 입력 데이터가 됩니다.

## 실행 위치

권장 흐름:

```powershell
uv run python -m market_scanner.collectors.prices fetch --market us
uv run python -m market_scanner.collectors.prices fetch --market kospi
uv run python -m market_scanner.collectors.prices fetch --market kosdaq
```

전체 파이프라인에서는 보통 1단계 종목 수집 이후, 3단계 지표 계산 전에 실행합니다.

```text
1. refresh-master
2. prices fetch/backfill
3. indicators compute
3.5 fundamentals fetch
4. screener run
5. reports render
```

`Search.py --stage scan` 경로에서도 `market_scanner.pipeline.run_scan_stage_with_settings()`를 통해 `run_fetch()`가 먼저 호출됩니다.

## CLI 옵션

전역 옵션:

| 옵션 | 설명 |
|---|---|
| `--database-url URL` | 기본 DB 대신 다른 PostgreSQL 접속 문자열 사용 |

### fetch

증분 일봉 수집입니다. 목표일 기준으로 가격이 이미 있는 종목은 SQL 단계에서 제외합니다.

```powershell
uv run python -m market_scanner.collectors.prices fetch --market us --date 20260505 --workers 8
```

| 옵션 | 설명 |
|---|---|
| `--market` | 필수. `us`, `kospi`, `kosdaq`, `global-indices`, `commodities` 중 하나 |
| `--date YYYYMMDD` | 목표 거래일. 생략 시 한국 시장은 오늘, 비한국 시장은 오늘의 전일 |
| `--limit N` | 테스트용. 대상 종목 앞에서 N개만 처리 |
| `--workers N` | 병렬 fetch worker 수. 기본 8 |

### backfill

과거 가격을 대량 적재합니다.

```powershell
uv run python -m market_scanner.collectors.prices backfill --market us --years 2 --workers 8
uv run python -m market_scanner.collectors.prices backfill --market kospi --new-only
```

| 옵션 | 설명 |
|---|---|
| `--market` | 필수. 수집 대상 시장 |
| `--years N` | 과거 N년 범위. 기본 1년 |
| `--new-only` | `daily_prices`가 전혀 없는 신규 종목만 처리 |
| `--limit N` | 테스트용. 대상 종목 앞에서 N개만 처리 |
| `--workers N` | 병렬 fetch worker 수. 기본 8 |

### retry

최근 실패한 `prices`/`backfill` 실행의 `error_samples`에 남은 symbol만 다시 backfill합니다.

```powershell
uv run python -m market_scanner.collectors.prices retry --market us
uv run python -m market_scanner.collectors.prices retry --market us --run-id <run_id>
```

| 옵션 | 설명 |
|---|---|
| `--market` | 필수. 실패 실행을 찾을 시장 |
| `--run-id` | 특정 `collection_runs.run_id`의 실패 symbol만 재시도 |

## 소스 우선순위

`fetch_ohlcv()` 기준:

| 시장 | 조회 순서 | 저장 `source_provider` |
|---|---|---|
| `kospi`, `kosdaq` | Naver 일봉 직접 조회 -> yfinance fallback | `fdr` 또는 `yfinance` |
| `us`, `global-indices`, `commodities` | yfinance | `yfinance` |

한국 시장은 `_fetch_fdr()` 경로에 들어가지만 실제 가격 조회는 timeout이 적용된 Naver 일봉 API를 먼저 사용합니다. 성공하면 호환상 `source_provider = 'fdr'`로 저장됩니다. Naver 조회가 실패하거나 빈 결과이면 yfinance로 fallback합니다.

현재 timeout은 5초입니다. 한국/Naver 경로는 `_FDR_RETRY = 2`, yfinance 경로는 `_YF_RETRY = 1`입니다.

## 데이터 정규화

모든 소스 결과는 `_normalize_ohlcv()`를 거칩니다.

처리 규칙:

- 컬럼명을 `Open`, `High`, `Low`, `Close`, `Volume`로 맞춥니다.
- `Open`, `High`, `Low`, `Close`가 없으면 빈 DataFrame으로 처리합니다.
- OHLCV를 numeric으로 변환합니다.
- `Close`가 비어 있는 row는 제거합니다.
- timezone이 있는 index는 timezone을 제거합니다.
- 날짜 index 기준으로 정렬합니다.

`Volume`은 없을 수 있습니다. `Close`는 DB 저장에 필수입니다.

## fetch 처리 흐름

`run_fetch()` 기준 end-to-end 흐름:

1. 목표일 결정
   - `--date`가 있으면 `datetime.strptime(date_str, "%Y%m%d").date()`
   - 생략 시 한국 시장은 오늘, 그 외 시장은 전일
2. 시장 통화 결정
   - `country_currency_for_market(market_key)`
3. DB 연결
   - `connect(explicit_url)`
4. 활성 종목 수 조회
   - `instruments.market_key = home_market_key(market_key)`
   - `is_active = TRUE`
5. 목표일보다 이전까지만 가격이 있거나 가격이 전혀 없는 종목 조회
   - `_instruments_needing_prices(conn, market_key, target_date)`
6. `--limit`이 있으면 대상 종목을 앞에서 N개로 제한
7. 대상이 없으면 실행 로그를 만들지 않고 종료
8. `collection_runs`에 `run_type = 'prices'`, `status = 'running'` row 생성
9. 종목별 시작일 계산
   - 기존 가격이 있으면 마지막 가격일 다음 날
   - 없으면 기본 1년 전부터
10. worker 수만큼 fetch 작업 제출
11. 완료된 작업부터 메인 스레드에서 `daily_prices` upsert
12. 빈 결과나 예외는 `failed` 처리하고 `error_samples`에 최대 30개 저장
13. 마지막에 `collection_runs`를 `success`, `partial`, `failed` 중 하나로 업데이트

출력 예:

```text
prices fetch [us] 120 symbols -> 2026-05-05  workers=8  run_id=...
    [■■■■□□□□□□□□□□□□□□] 24/120  20.0% queued=31 active=7 success=24 failed=0 skipped=6400
prices fetch [us] done: success=118 failed=2 skipped=6400 status=partial
```

## backfill 처리 흐름

`run_backfill()`은 목표일 기준 증분 판단을 하지 않고 지정 범위 전체를 다시 조회합니다.

대상 선택:

| 옵션 조합 | 대상 |
|---|---|
| 기본 | 해당 시장의 모든 활성 종목 |
| `--new-only` | `daily_prices` row가 전혀 없는 활성 종목 |
| `retry` 내부 호출 | 실패 샘플의 symbol 목록 |

범위:

- 시작일: `date.today() - (years * 365 + 30 days)`
- 종료일: 오늘

`collection_runs`에는 `run_type = 'backfill'`로 기록합니다. `params.mode`는 기본 `backfill_all`, `--new-only`는 `backfill_new`입니다.

## retry 처리 흐름

`run_retry()`는 DB에서 실패 샘플을 읽은 뒤 `run_backfill()`을 호출합니다.

조회 기준:

- `--run-id`가 있으면 해당 run의 `error_samples`
- 없으면 같은 시장에서 `run_type IN ('prices', 'backfill')`이고 `status IN ('failed', 'partial')`인 가장 최근 실행

`error_samples` 안의 dict 중 `symbol` 키가 있는 항목만 재시도합니다. 재시도 범위는 기본 1년입니다.

## DB 입력

### instruments

처리 대상은 `instruments`에서 가져옵니다.

```sql
SELECT instrument_id, symbol, currency_code
FROM instruments
WHERE market_key = %s AND is_active = TRUE
ORDER BY symbol;
```

`market_key`는 `home_market_key()`를 거칩니다. 따라서 대표 유니버스 alias가 들어와도 실제 홈 시장 기준으로 조회됩니다.

`fetch`는 `daily_prices`와 LEFT JOIN해서 목표일 이전까지만 가격이 있는 종목을 찾습니다.

```sql
HAVING MAX(dp.trade_date) IS NULL OR MAX(dp.trade_date) < %s
```

### daily_prices

저장은 `upsert_daily_price()`가 담당합니다.

주요 저장 컬럼:

| 컬럼 | 값 |
|---|---|
| `instrument_id` | 대상 종목 ID |
| `trade_date` | DataFrame index의 날짜 |
| `source_provider` | 실제 성공 소스. 현재 저장 값은 `fdr` 또는 `yfinance`. 빈 결과는 저장하지 않음 |
| `open_price`, `high_price`, `low_price`, `close_price` | 정규화된 OHLC |
| `volume` | 거래량 |
| `currency_code` | 종목 통화, 없으면 시장 기본 통화 |
| `is_adjusted` | 현재 `FALSE` |
| `run_id` | 이번 `collection_runs.run_id` |
| `raw_payload` | open/high/low/close/volume 원본 payload |

Primary key는 `(instrument_id, trade_date, source_provider)`입니다. 같은 종목/날짜/source가 다시 들어오면 가격, 거래량, 통화, run_id, raw_payload를 업데이트합니다.

## collection_runs 기록

`fetch`:

```text
run_type = 'prices'
source_provider = 'fdr'      # 한국 시장
source_provider = 'yfinance' # 그 외 시장
params.mode = 'incremental'
```

`backfill`:

```text
run_type = 'backfill'
params.mode = 'backfill_all' 또는 'backfill_new'
```

완료 상태:

| 상태 | 조건 |
|---|---|
| `success` | 실패가 0개 |
| `partial` | 성공과 실패가 모두 있음 |
| `failed` | 성공이 없고 실패만 있음 |

`fetch`의 `skipped_count`는 목표일까지 이미 가격이 있어서 처리 대상에서 제외된 활성 종목 수입니다. `backfill`은 skipped를 기록하지 않습니다.

## 진행률

진행률 표시는 공통 `market_scanner.progress.progress_line()`을 사용합니다.

```text
[■■■■□□□□□□□□□□□□□□] 120/500  24.0% queued=124 active=4 success=100 failed=20 skipped=380
```

규칙:

- 전체 20칸
- 완료 `■`
- 미완료 `□`
- `queued`는 지금까지 제출한 작업 수
- `active`는 제출됐지만 아직 완료되지 않은 작업 수
- `success`, `failed`, `skipped` 카운트 표시

병렬 실행은 모든 종목을 한 번에 제출하지 않고 worker 수만큼 pending 작업을 유지합니다. 완료된 future가 없을 때도 1초마다 진행 상태를 다시 출력합니다.

## 주의사항

- `fetch`는 종목별 마지막 가격일 다음 날부터 조회하므로, 중간 결측일을 별도로 탐지하지는 않습니다.
- 한국 시장의 성공 소스 라벨은 현재 `fdr`로 저장되지만 실제 1차 조회는 Naver 일봉 API입니다.
- `backfill`은 같은 PK를 upsert하므로 기존 row를 갱신할 수 있습니다.
- `retry`는 실패 샘플에 남은 symbol만 기준으로 하며, 실패 원인을 다시 검증하지는 않습니다.
- Ctrl+C 전용 cancelled 처리 로직은 현재 `prices.py`에 없습니다. 중단 시 실행 중이던 `collection_runs`가 `running`으로 남을 수 있습니다.
