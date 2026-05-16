# Stock MA Scanner

미국 주식, KOSPI, KOSDAQ, 글로벌 지수, 섹터 ETF, 테마 ETF, 원자재를 대상으로 5/20/60/120/240일 이동평균선, 기간 수익률, ATR/변동성, 기술/재무/테마/모멘텀 점수를 계산하고 PostgreSQL 기반 Markdown/HTML 리포트와 GitHub Pages 대시보드를 생성합니다.

## 설치

아래 예시는 Windows와 macOS 터미널에서 같은 형태로 사용할 수 있습니다. `uv`는 사전에 설치되어 있어야 하며, 설치 이후 실행 명령은 `uv run python`이 현재 프로젝트의 `.venv`를 사용합니다.
```bash
uv venv
uv pip install -r requirements.txt
```

## 기본 실행 흐름

Search60은 `Search.py`를 짧은 명령 컨트롤러로 사용합니다. 각 단계는 PostgreSQL에 결과를 저장하고, 다음 단계는 앞 단계가 저장한 테이블을 읽습니다.
```bash
docker compose up -d postgres
uv run python Search.py init
```

`init`은 `docs/database_schema_v1.sql`을 적용하고 시장/유니버스 기준 데이터를 준비합니다. 새 DB를 만들었거나 스키마가 바뀐 뒤에 실행합니다. 이미 초기화된 DB에서 매일 반복 실행할 필요는 없습니다.

## 1단계: 종목 수집

`refresh-master`는 가격이나 지표를 수집하지 않습니다. 시장별 종목 목록을 받아 `instruments`, `universe_memberships`, `collection_runs`만 갱신합니다.
```bash
uv run python Search.py refresh us --universe sp500
uv run python Search.py refresh us --universe dow30
uv run python Search.py refresh kospi --universe kospi200
uv run python Search.py refresh kosdaq --universe kosdaq150
uv run python Search.py refresh global-indices
uv run python Search.py refresh sector-etfs
uv run python Search.py refresh commodities
```

데이터 소스:
- `us`, `kospi`, `kosdaq`: 종목 목록은 FinanceDataReader를 우선 사용합니다. 가격 수집은 US는 yfinance, KOSPI/KOSDAQ은 FinanceDataReader를 사용합니다.
- `global-indices`, `commodities`: JSON 메타 파일을 원본으로 사용합니다.
- `sector-etfs`: 11개 GICS 섹터 ETF와 리츠 보조 프록시를 JSON 메타 파일에서 수집합니다. GICS 부동산 섹터 기준은 `XLRE`, 리츠 보조 프록시는 `VNQ`입니다.
- 한국 종목명/업종 보강: `uv run python Search.py names kospi`

`--reset`은 해당 범위의 `universe_memberships`만 삭제 후 재생성합니다. `instruments`, 가격, 지표, 스캔 결과, 뉴스, 리포트, 실행 로그는 보존합니다.

## 2단계: 가격 수집

기본 수집은 US는 전일, KOSPI/KOSDAQ은 오늘을 대상으로 필요한 종목만 조회합니다.
```bash
uv run python Search.py price us
uv run python Search.py price kospi
uv run python Search.py price kosdaq
uv run python Search.py price sector-etfs
uv run python Search.py price kospi --date 20260513 --force --workers 1
uv run python Search.py price us --from 20250101 --to 20260505 --workers 1
uv run python Search.py price us --from 20250101 --to 20260505 --force
uv run python Search.py retry-price us
```

펀더멘탈 수집:
```bash
uv run python Search.py fundamentals us
uv run python Search.py fundamentals kospi
uv run python Search.py fundamentals kosdaq --workers 8 --limit 100
uv run python Search.py fundamentals kospi --source naver --limit 10
```

## 매크로 지표 수집

금리·환율·원자재·신용 스프레드·유동성·크립토 등 시장 공통 매크로 지표를 `daily_macro`에 저장합니다.
FRED API key가 `.env`에 있어야 FRED 지표를 수집합니다.

```bash
# 증분 수집 (각 지표의 마지막 수집일 다음 날부터 오늘까지)
uv run python Search.py macro

# 특정 날짜까지 수집
uv run python Search.py macro --to 20260515

# 날짜 범위 강제 지정 (DB 이력 무시, 해당 구간 재수집)
uv run python Search.py macro --from 20250101 --to 20260515

# 처음 실행 시 소급 기간 조정 (기본 90일)
uv run python Search.py macro --days-back 365
```

수집 소스 및 지표:

| 소스 | 지표 |
|---|---|
| FRED | SOFR, US_FFR, US_2Y, US_10Y, US_30Y, US_SPREAD_2S10S, US_SPREAD_3M10Y, HY_OAS, IG_OAS, FED_RRP, FED_BS |
| yfinance | USDKRW, EURUSD, USDJPY, USDCNY, DXY, WTI, GOLD, SILVER, NATGAS, COPPER, VIX, VVIX, BTC_USD, ETH_USD |
| CoinGecko | CRYPTO_TOTAL_MCAP (현재 스냅샷, `/global` 엔드포인트) |
| alternative.me | CRYPTO_FNG (공포·탐욕 지수) |


## 3단계: 지표 계산

`daily_prices`를 읽어 `daily_indicators`를 계산합니다.
```bash
uv run python Search.py indicators us
uv run python Search.py indicators kospi
uv run python Search.py indicators kosdaq
uv run python Search.py indicators us --date 20260505
uv run python Search.py indicators kospi --from 20260501 --to 20260507
```

## 4단계: 스코어링

`daily_indicators`와 `daily_prices`를 읽어 눌림목, 돌파, 박스권, 반전, 추세 품질, 테마, 재무, 수급/거래대금 점수를 계산하고 순위와 시장/섹터 스냅샷을 저장합니다.
`--date`를 생략하면 해당 시장/유니버스의 최신 `daily_indicators.trade_date`를 자동으로 사용합니다.
```bash
uv run python Search.py screen us
uv run python Search.py screen kospi
uv run python Search.py screen kosdaq
uv run python Search.py screen us --universe sp500
uv run python Search.py screen kospi --universe kospi200
```

## 5단계: 사이트 빌드

`scan_results`를 읽어 전체 GitHub Pages 사이트를 생성합니다.
```bash
uv run python Search.py site --no-open
```

v2
```bash
# 메인 페이지만
uv run python Search.py site-v2 main --no-open

# 특정 마켓 또는 유니버스 페이지
uv run python Search.py site-v2 market kospi --no-open
uv run python Search.py site-v2 market sp500 --no-open

# 특정 섹터 페이지만
uv run python Search.py site-v2 sector kospi 전기전자 --no-open

# 관리 페이지만
uv run python Search.py site-v2 admin --no-open

# 전체 (메인 + 관리 + US/KR 종합 + 주요 유니버스 + 모든 마켓)
uv run python Search.py site-v2 all --no-open
```

## 보조 명령

핵심 테이블 적재 건수 확인:
```bash
uv run python Search.py counts
```

펀더멘탈의 기본 `--source auto`는 US는 Yahoo Finance, KOSPI/KOSDAQ은 Naver Finance -> FinanceDataReader -> Yahoo Finance 순서로 값을 채웁니다. `--workers`는 기본 2이며 US/Yahoo 경로는 최대 4, 한국 Naver/FDR 경로는 최대 8로 제한합니다.

자세한 옵션과 동작은 `docs/fundamentals.manual.md`를 참고합니다.

뉴스 캐시 수집은 짧은 `Search.py` 명령으로 실행할 수 있습니다.
```bash
uv run python Search.py news us --universe sp500
```

## Search.py 단축 실행

`Search.py`는 긴 모듈 명령을 대신하는 얇은 명령 컨트롤러입니다. 실제 수집/계산/스코어링/리포트 작업은 기존 모듈과 파이프라인 함수가 수행합니다.
```bash
uv run python Search.py init
uv run python Search.py refresh us --universe sp500
uv run python Search.py price us --workers 1
uv run python Search.py indicators us
uv run python Search.py screen us --universe sp500
```

파이프라인 묶음 실행:
```bash
uv run python Search.py scan us --universe sp500
uv run python Search.py all kospi --universe kospi200
uv run python Search.py analyze us --universe sp500
```

## 출력

스캔 결과의 원천은 PostgreSQL입니다. GitHub Pages 사이트는 `site_builder`가 DB에서 직접 읽어 `site/` 아래에 생성합니다.

## PostgreSQL

기본 접속 문자열은 `.env.example`의 `DATABASE_URL`입니다.
```text
postgresql://searchmarket:searchmarket@localhost:5433/searchmarket
```

DBeaver 로컬 접속:
```text
Host: localhost
Port: 5433
Database: searchmarket
Username: searchmarket
Password: searchmarket
```

`.postgres-data/`는 로컬 DB 데이터 디렉터리이며 Git 추적 대상이 아닙니다.

## 사이트 대시보드

```bash
uv run python Search.py site --no-open
```

`site/`에는 GitHub Pages용 정적 대시보드가 생성됩니다. 자동 열기를 원하면 `--no-open`을 빼고 실행합니다.

대시보드는 DB의 `scan_results`, `market_snapshots`, `sector_snapshots` 최신 데이터를 기반으로 종합 시장 점수, 시장 체력, 매크로 리스크, 섹터/테마 히트맵, 오늘의 핵심 후보, 시장별 스냅샷, 섹터 리더십, 뉴스 브리핑을 표시합니다.

상단 `관리` 탭은 빌드 시점의 PostgreSQL 테이블 목록, 행 수, 컬럼, 최근 데이터 샘플을 보여주는 정적 읽기 전용 페이지입니다. v2에서는 `site/v2/admin/index.html`로 생성됩니다. 데이터 수정/삭제는 DB 또는 CLI에서 처리합니다.

## 데이터 정책

- `instruments`: 종목마스터의 우선 원천입니다.
- `universe_memberships`: `nasdaq`, `nyse`, `amex`(거래소 전체), `nasdaq100`, `sp500`, `dow30`(지수), `kospi100`, `kospi200`, `kosdaq150` 같은 분석/필터 단위 멤버십입니다. US는 `--market us` 한 번으로 6개 universe가 동시 갱신됩니다.
- `market_scanner/assets/instruments.json`: DB가 비어 있거나 연결되지 않을 때 쓰는 seed/fallback입니다. 스캔 실행은 이 JSON을 자동 갱신하지 않습니다.
- `market_scanner/assets/global_indices_meta.json`, `commodities_meta.json`: 글로벌 지수·원자재는 FDR 자동 발견이 불가능하므로 JSON이 심볼 정의 원본입니다. 새 심볼 추가 시 JSON 편집 후 `Search.py refresh global-indices` 또는 `Search.py refresh commodities`로 DB에 반영합니다. 현재 글로벌 지수는 22개입니다.
- `market_scanner/assets/sector_etfs_meta.json`: 섹터 ETF 유니버스의 원본입니다. `XLK`, `XLV`, `XLF`, `XLY`, `XLP`, `XLI`, `XLE`, `XLU`, `XLB`, `XLC`, `XLRE`를 기본 GICS 섹터 프록시로 사용하고, `VNQ`는 리츠 보조 프록시로 함께 수집합니다.
- 테마 ETF는 별도 스캔 없이 US 스캔 결과에서 파생됩니다. 대상 심볼은 `markets.py`의 `_THEME_PROXY_SYMBOLS` 상수로 관리합니다.
- 한국 시장 유니버스는 FinanceDataReader를 우선 사용하고, 실패 시 Naver Finance로 fallback합니다. 정적 JSON fallback(`kospi_static_meta.json`, `kosdaq_static_meta.json`)은 제거되었습니다.
- KOSPI/KOSDAQ 가격 히스토리는 FinanceDataReader를 사용합니다. US 가격 히스토리는 yfinance만 사용합니다.
- `news` 단계는 DB의 최신 `scan_results`가 있어야 실행되며, `all`에는 포함하지 않습니다.

## 패키지 구조

```text
market_scanner/
  models.py             # 공통 데이터 모델·설정
  pipeline.py           # v2 단계 순서 제어
  analysis/             # 지표 계산·스크리닝
  collectors/           # 가격·펀더멘탈·뉴스·번역 수집
  config/markets.py     # 시장 설정·유니버스/메타데이터 로더
  reports/              # Markdown/HTML/Page 렌더링
  storage/              # PostgreSQL 유틸리티
  assets/               # seed/cache 파일
  templates/            # HTML 리포트 템플릿/CSS
```

## GitHub Actions

| 워크플로우 | 실행 시각 | 대상 |
|---|---|---|
| `daily-scan.yml` | KST 08:05 | US Market |
| `daily-scan-overview.yml` | KST 08:20 | 글로벌 지수·섹터 ETF·테마 ETF·원자재 |
| `daily-scan-kospi.yml` | KST 16:05 | KOSPI |
| `daily-scan-kosdaq.yml` | KST 16:35 | KOSDAQ |
| `deploy-pages.yml` | 스캔 성공 후 자동, 또는 수동 실행 | GitHub Pages 사이트 빌드·배포 |


python -c "from market_scanner.storage.connection import connect; conn = connect(); print('connected:', conn.info.host)"
# localhost 출력되면 로컬 DB
