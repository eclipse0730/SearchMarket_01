# Fundamentals Collector Manual

`market_scanner.collectors.fundamentals`는 종목별 재무/밸류에이션 데이터를 수집해 PostgreSQL `instrument_fundamentals`에 저장하는 3.5단계 보조 수집기입니다. 가격/지표처럼 매일 반드시 필요한 단계는 아니지만, screener의 `fundamental_score`에 영향을 줍니다.

## 실행 위치

권장 흐름:

```powershell
uv run python -m market_scanner.collectors.fundamentals fetch --market us
uv run python -m market_scanner.collectors.fundamentals fetch --market kospi
uv run python -m market_scanner.collectors.fundamentals fetch --market kosdaq
```

전체 파이프라인에서는 보통 1단계 종목 수집 이후, 4단계 스코어링 전에 실행합니다.

```text
1. refresh-master
2. prices fetch/backfill
3. indicators compute
3.5 fundamentals fetch
4. screener run
5. reports render
```

## CLI 옵션

```powershell
uv run python -m market_scanner.collectors.fundamentals fetch --market kospi
```

| 옵션 | 설명 |
|---|---|
| `--market` | 필수. `us`, `kospi`, `kosdaq` 등 시장 key |
| `--date YYYYMMDD` | `instrument_fundamentals.as_of_date` 기준일. 생략 시 오늘 |
| `--stale-days N` | 기본 7. 마지막 fundamentals 기준일이 N일보다 오래된 종목만 수집 |
| `--all` | stale 여부와 관계없이 해당 시장의 모든 활성 종목 재수집 |
| `--limit N` | 테스트용. 앞에서 N개 종목만 처리 |
| `--workers N` | 병렬 요청 worker 수. 기본 2. Yahoo/US는 최대 4, 한국 Naver/FDR 경로는 최대 8 |
| `--source auto/yahoo/naver/fdr` | 기본 `auto`. 특정 소스만 테스트할 때 지정 |
| `--database-url URL` | 기본 DB 대신 다른 PostgreSQL 접속 문자열 사용 |

예시:

```powershell
# 7일 이상 지난 종목만
uv run python -m market_scanner.collectors.fundamentals fetch --market kospi

# 전체 재수집
uv run python -m market_scanner.collectors.fundamentals fetch --market kospi --all

# 네이버만 테스트
uv run python -m market_scanner.collectors.fundamentals fetch --market kospi --source naver --limit 10

# 한국장 병렬 조회 (최대 8)
uv run python -m market_scanner.collectors.fundamentals fetch --market kosdaq --workers 8
```

## 소스 우선순위

`--source auto` 기준:

| 시장 | 조회 순서 |
|---|---|
| `us` | Yahoo Finance |
| `kospi`, `kosdaq` | Naver Finance -> FinanceDataReader -> Yahoo Finance |

한국 시장은 Naver Finance를 주 소스로 사용합니다. Naver에서 비어 있는 값은 FDR과 Yahoo로 보강합니다. FDR은 재무 전문 소스가 아니므로 주로 시가총액과 상장주식수 보조값에 사용됩니다.

명시 소스:

- `--source naver`: 한국 종목의 Naver Finance 페이지만 조회합니다.
- `--source fdr`: 한국 종목의 FDR 상장 데이터만 조회합니다.
- `--source yahoo`: Yahoo Finance quoteSummary/quote API만 조회합니다.

## 수집 데이터

저장 컬럼:

| 저장 컬럼 | 주요 원천 | 설명 |
|---|---|---|
| `trailing_pe` | Naver `PER`, Yahoo `trailingPE` | PER |
| `price_to_book` | Naver `PBR`, Yahoo `priceToBook` | PBR |
| `return_on_equity_pct` | Naver `ROE`, Yahoo `returnOnEquity` | ROE, % 단위 |
| `revenue_growth_pct` | Naver 매출액 YoY, Yahoo `revenueGrowth` | 매출 성장률, % 단위 |
| `market_cap` | Naver/FDR/Yahoo | 시가총액 |
| `target_price` | Naver 목표주가, Yahoo `targetMeanPrice` | 목표가 평균 |
| `shares_outstanding` | Naver/FDR | 상장주식수 |

모든 값이 비어 있으면 `skipped`로 처리하고 DB에 저장하지 않습니다.

## DB 기록

수집 실행은 `collection_runs`에 `run_type = 'fundamentals'`로 기록됩니다. `source_provider`에는 실행 옵션이 저장됩니다. 기본값은 `auto`입니다.

성공한 종목은 `instrument_fundamentals`에 upsert됩니다.

```text
PRIMARY KEY (instrument_id, as_of_date, source_provider)
```

row의 `source_provider`에는 실제로 값을 제공한 첫 번째 소스가 저장됩니다. 예를 들어 한국 종목에서 Naver 값이 하나라도 있으면 `naver`, Naver가 실패하고 FDR 값만 있으면 `fdr`입니다. 보강에 사용된 소스 목록은 `raw_payload.raw_sources`에 남깁니다.

screener와 render는 같은 기준일에 여러 소스 row가 있을 때 `naver -> yahoo -> yfinance -> fdr -> 기타` 순서로 우선 선택합니다.

## 진행률

진행률 표시는 공통 `market_scanner.progress.progress_bar`를 사용합니다.

```text
[■■■■□□□□□□□□□□□□□□] 120/500  24.0% queued=124 active=4 success=100 failed=10 skipped=10
```

규칙:

- 전체 20칸
- 완료 `■`
- 미완료 `□`
- queued/active/success/failed/skipped 카운트 표시

## Ctrl+C 동작

Ctrl+C를 누르면 현재 요청이 끝나거나 timeout된 뒤 루프를 중단합니다. 중단된 실행은 `collection_runs.status = 'cancelled'`로 기록하고, 그 시점까지의 `success`, `failed`, `skipped`, `error_samples`를 저장합니다. 병렬 실행 중에는 새 작업 제출을 멈추고, 아직 시작하지 않은 pending 작업을 취소합니다.

네트워크 요청 timeout 기본값은 5초입니다.

## 주의사항

- Naver Finance HTML 구조가 바뀌면 일부 컬럼 파싱이 실패할 수 있습니다.
- Yahoo Finance 무료 엔드포인트는 일부 한국 종목의 재무 데이터를 제공하지 않을 수 있습니다.
- `--all`은 요청량이 크므로 `--limit`으로 테스트한 뒤 실행하는 것이 좋습니다.
- screener의 `fundamental_score`는 fundamentals가 없어도 50점 중립값으로 동작하지만, 데이터가 있으면 PER/PBR/ROE/성장률 기반으로 점수가 달라집니다.
