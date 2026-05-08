# SearchMarket Database Recommendation

Last updated: 2026-05-02

## 결론

SearchMarket의 canonical 저장소는 PostgreSQL로 전환하는 것을 권장합니다.

CSV는 당분간 유지하되, 역할을 다음처럼 낮춥니다.

- PostgreSQL: 원천 저장소, 이력 저장, 조회, 분석, 재계산 기준
- CSV: 기존 사이트 빌드/호환/export 산출물
- JSON asset: 고정 메타데이터 seed 또는 캐시

## 왜 Postgres인가

현재 스캐너는 NASDAQ 100, S&P 500, KOSPI/KOSDAQ 대형주 중심에서는 CSV로 충분했습니다. 하지만 `us`, `kospi`, `kosdaq` 같은 시장 전체 스캔을 기본으로 다루기 시작하면 데이터량과 갱신 방식이 달라집니다.

- 일봉 가격은 종목 수 x 거래일 수만큼 계속 증가합니다.
- 같은 종목을 여러 시장/유니버스에서 재사용합니다.
- 보통주, 우선주, ETF, ETN, 리츠, 스팩 등을 구분해야 합니다.
- 가격, 지표, 스코어, 뉴스, 리포트를 서로 다른 갱신 주기로 관리해야 합니다.
- 전일 대비 신호 변화, 최근 20일 추이, 과거 스코어 백테스트는 CSV 단일 파일 구조로 유지하기 어렵습니다.

PostgreSQL은 이 문제를 다음 방식으로 해결합니다.

- `daily_prices`에 날짜별 가격을 append/upsert
- `daily_indicators`에 계산 지표를 분리 저장
- `scan_results`에 그날의 스코어와 랭킹만 저장
- `collection_runs`에 실패/재시도/소스별 품질을 기록
- DBeaver/Azure Data Studio에서 직접 조회 가능

## 권장 운영 구조

로컬 개발은 Docker Postgres를 사용합니다.

```env
DATABASE_URL=postgresql://searchmarket:searchmarket@localhost:5433/searchmarket
```

추천 Docker 구성:

```yaml
services:
  postgres:
    image: postgres:16
    ports:
      - "5433:5432"
    environment:
      POSTGRES_DB: searchmarket
      POSTGRES_USER: searchmarket
      POSTGRES_PASSWORD: searchmarket
    volumes:
      - postgres_data:/var/lib/postgresql/data

volumes:
  postgres_data:
```

## 데이터 소스 정책

### 한국 시장

권장 기본값:

- 유니버스 목록: KRX/FDR 우선, 실패 시 Naver Finance fallback
- 가격 일봉: FinanceDataReader 우선
- yfinance: 한국 시장에서는 opt-in fallback으로 제한

이유:

- 한국 종목은 yfinance `.KS`/`.KQ` 누락과 404가 자주 발생합니다.
- FinanceDataReader는 한국 일봉 OHLCV 수집에 더 적합합니다.
- Naver Finance는 전체 목록과 종목명 보강에는 유용하지만, 가격 히스토리 주 소스로 쓰기에는 구조가 번거롭습니다.

주의:

- Naver 시가총액 페이지에는 보통주 외에 우선주, ETF, ETN, 리츠, 스팩, 기타 상품이 섞일 수 있습니다.
- 따라서 `instruments.asset_type`에 분류를 저장하고, `kospi`/`kosdaq` 기본 스캔 유니버스는 `common_stock` 중심으로 제한하는 것을 권장합니다.

### 미국 시장

권장 기본값:

- NASDAQ 100: 정적 curated 목록
- S&P 500: Wikipedia 구성 종목 + cache
- US 전체: NASDAQ Trader symbol directory
- 가격 일봉: yfinance 우선

추후 유료 API를 도입한다면 Polygon, Tiingo, Finnhub, Financial Modeling Prep 같은 후보를 비교합니다. 그 경우에도 DB 스키마는 `source_provider`를 통해 소스별 저장을 지원합니다.

## 단계별 전환 계획

### Phase 1: DB 저장 레이어 추가

- `docs/database_schema_v1.sql` 기준으로 Postgres 스키마 생성
- `market_scanner/storage/db.py` 추가
- 스캔 완료 후 CSV 저장과 동시에 DB upsert
- 사이트 빌드는 DB 기반으로 전환

### Phase 2: 한국 전체 시장 안정화

- Naver fallback 목록을 `asset_type` 기준으로 분류 저장
- `kospi`/`kosdaq` 기본 스캔은 시장 전체 `common_stock`을 사용
- `kospi200`/`kosdaq150`은 선택 유니버스 멤버십으로 관리
- 우선주/ETF/ETN은 별도 유니버스로 분리

### Phase 3: DB 기반 조회 전환

- DB에서 최신 `scan_results` 조회
- 메인 페이지 시장 요약은 `market_snapshots` 기반으로 생성
- 상세 페이지는 `scan_results` + `daily_indicators` + `instruments` 조인으로 생성

### Phase 4: 이력 분석과 알림

- 전일 대비 신호 변화
- 최근 20거래일 스코어 추이
- 섹터별 강도 변화
- 신규 MA 근접, MACD 전환, RSI 회복 알림

## 추천 테이블 묶음

초기 필수:

- `markets`
- `instruments`
- `universe_definitions`
- `universe_memberships`
- `collection_runs`
- `daily_prices`
- `daily_indicators`
- `instrument_fundamentals`
- `scan_results`
- `market_snapshots`
- `sector_snapshots`

후속:

- `news_items`
- `instrument_news`
- `generated_reports`
