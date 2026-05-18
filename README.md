# Stock MA Scanner

미국 주식, KOSPI, KOSDAQ, 글로벌 지수, 섹터 ETF, 테마 ETF, 원자재를 대상으로 5/20/60/120/240일 이동평균선, 기간 수익률, ATR/변동성, 기술/재무/테마/모멘텀 점수를 계산하고 PostgreSQL 기반 Markdown/HTML 리포트와 GitHub Pages 대시보드를 생성합니다.

## 설치

아래 예시는 Windows와 macOS 터미널에서 같은 형태로 사용할 수 있습니다. `uv`는 사전에 설치되어 있어야 하며, 설치 이후 실행 명령은 `uv run python`이 현재 프로젝트의 `.venv`를 사용합니다.
```bash
uv venv
uv pip install -r requirements.txt
```

## README HTML 버전 관리

`README.md`를 원본으로 두고 HTML 문서는 아래 명령으로 재생성합니다. 생성 파일은 `docs/readme.html`입니다.
```bash
uv run python Search.py readme-html
```

## 기본 실행 흐름

Search60은 `Search.py`를 짧은 명령 컨트롤러로 사용합니다. 각 단계는 PostgreSQL에 결과를 저장하고, 다음 단계는 앞 단계가 저장한 테이블을 읽습니다.
```bash
docker compose up -d postgres
uv run python Search.py init
```

`init`은 `docs/database_schema_v1.sql`을 적용하고 시장/유니버스 기준 데이터를 준비합니다. 새 DB를 만들었거나 스키마가 바뀐 뒤에 실행합니다. 이미 초기화된 DB에서 매일 반복 실행할 필요는 없습니다.

uv run python Search.py counts --database-url postgresql://searchmarket:searchmarket@localhost:5433/searchmarket


## 1단계: 종목 수집

`refresh-master`는 가격이나 지표를 수집하지 않습니다. 시장별 종목 목록을 받아 `instruments`, `universe_memberships`, `collection_runs`만 갱신합니다.
```bash
uv run python Search.py refresh us --universe sp500
uv run python Search.py refresh us --universe dow30
uv run python Search.py refresh kr --universe kospi
uv run python Search.py refresh kr --universe kosdaq
uv run python Search.py refresh kr --universe kospi200
uv run python Search.py refresh kr --universe kosdaq150
uv run python Search.py refresh global-indices
uv run python Search.py refresh sector-etfs
uv run python Search.py refresh commodities
```

데이터 소스:
- `us`, `kr`: 종목 목록은 FinanceDataReader를 우선 사용합니다. 가격 수집은 US는 yfinance, KR(KOSPI/KOSDAQ)은 FinanceDataReader를 사용합니다. `kr` 내 유니버스(kospi, kosdaq, kospi200 등)는 `--universe`로 지정합니다.
- `global-indices`, `commodities`: JSON 메타 파일을 원본으로 사용합니다.
- `sector-etfs`: 11개 GICS 섹터 ETF와 리츠 보조 프록시를 JSON 메타 파일에서 수집합니다. GICS 부동산 섹터 기준은 `XLRE`, 리츠 보조 프록시는 `VNQ`입니다.
- 한국 종목명/업종 보강: `uv run python Search.py names kospi`

`--reset`은 해당 범위의 `universe_memberships`만 삭제 후 재생성합니다. `instruments`, 가격, 지표, 스캔 결과, 뉴스, 리포트, 실행 로그는 보존합니다.

## 2단계: 가격 수집

기본 수집은 US는 전일, KOSPI/KOSDAQ은 오늘을 대상으로 필요한 종목만 조회합니다.
```bash
uv run python Search.py price us
uv run python Search.py price us --from 20250101 --to 20260505 --force --workers 1
uv run python Search.py price kr
uv run python Search.py price kr --from 20250101 --to 20260505 --force --workers 1
uv run python Search.py price sector-etfs
uv run python Search.py retry-price us
```

펀더멘탈 수집:
```bash
uv run python Search.py fundamentals us
uv run python Search.py fundamentals kr
uv run python Search.py fundamentals kr --workers 8 --limit 100
uv run python Search.py fundamentals kr --source naver --limit 10
```

한국 투자자별 수급 수집:
```bash
# 종목별 기관/외국인/개인 순매수 거래대금을 daily_investor_flows에 저장
uv run python Search.py flows kospi
uv run python Search.py flows kosdaq
uv run python Search.py flows kr --date 20260507

# 백필은 기간과 limit으로 나눠 실행
uv run python Search.py flows kospi --from 20260501 --to 20260507 --limit 100 --force

# 거래량 수급까지 함께 저장
uv run python Search.py flows kospi --date 20260507 --include-volume
```

수급 수집은 pykrx/KRX 기준이며, 기본값은 거래대금 수급입니다. `--include-volume`을 지정하면 거래량 수급도 함께 저장합니다. 현재 `flow_score`는 기존 가격/거래량 기반 점수를 유지하며, 실제 기관/외국인/개인 수급 점수 반영은 수집 안정화 뒤 별도 단계에서 적용합니다.

pykrx 1.2 계열은 KRX 로그인 정책 변경으로 `KRX_ID`, `KRX_PW` 환경변수가 필요할 수 있습니다. `.env`에 아래 값을 넣으면 `Search.py` 실행 시 자동 로드됩니다.
```bash
KRX_ID=your_krx_id
KRX_PW=your_krx_password
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
| FRED | SOFR, US_FFR, US_2Y, US_10Y, US_30Y, US_SPREAD_2S10S, US_SPREAD_3M10Y, HY_OAS, IG_OAS, FED_RRP, FED_BS, KR_10Y, KR_INTERBANK_3M, KR_CALL_RATE, KR_DISCOUNT_RATE |
| yfinance | SP500, NASDAQ100, KOSPI, KOSDAQ, USDKRW, EURUSD, USDJPY, USDCNY, GBPUSD, AUDUSD, NZDUSD, USDCAD, USDCHF, USDSGD, USDSEK, USDNOK, USDMXN, DXY, WTI, GOLD, SILVER, NATGAS, COPPER, VIX, VVIX, BTC_USD, ETH_USD |
| pykrx/KRX | KR_KOSPI_FOREIGN_NET_BUY_VALUE, KR_KOSPI_INSTITUTION_NET_BUY_VALUE, KR_KOSDAQ_FOREIGN_NET_BUY_VALUE, KR_KOSDAQ_INSTITUTION_NET_BUY_VALUE, KR_KOSPI_SHORT_SELL_VALUE, KR_KOSPI_SHORT_BALANCE_VALUE, KR_KOSDAQ_SHORT_SELL_VALUE, KR_KOSDAQ_SHORT_BALANCE_VALUE |
| KOFIA FreeSIS | KR_CUSTOMER_DEPOSIT_VALUE, KR_CREDIT_BALANCE_VALUE |
| CoinGecko | CRYPTO_TOTAL_MCAP (현재 스냅샷, `/global` 엔드포인트) |
| alternative.me | CRYPTO_FNG (공포·탐욕 지수) |

한국 고객예탁금과 신용잔고는 금융투자협회 FreeSIS 메인 최신 스냅샷을 저장합니다. 값 단위는 백만원이며, 히스토리 백필용 API가 아니라 매일 실행하면서 최신 공표치를 누적하는 방식입니다.


## 3단계: 지표 계산

`daily_prices`를 읽어 `daily_indicators`를 계산합니다.
```bash
uv run python Search.py indicators us
uv run python Search.py indicators kr
uv run python Search.py indicators us --date 20260505
uv run python Search.py indicators kr --from 20260501 --to 20260507
```

## 4단계: 스코어링

`daily_indicators`와 `daily_prices`를 읽어 눌림목, 돌파, 박스권, 반전, 추세 품질, 테마, 재무, 수급/거래대금 점수를 계산하고 순위와 시장/섹터 스냅샷을 저장합니다.
한국 시장은 `daily_investor_flows`가 있으면 최근 1/5/20거래일 외국인·기관 순매수, 5거래일 외국인+기관 수급 강도(`smart_money_score`), 섹터 내 순위(`sector_rank`), 데이터 품질 태그(`data_quality_flags`)도 `scan_results`에 저장합니다.
`--date`를 생략하면 해당 시장/유니버스의 최신 `daily_indicators.trade_date`를 자동으로 사용합니다.
```bash
uv run python Search.py screen us
uv run python Search.py screen us --universe sp500
uv run python Search.py screen kr
uv run python Search.py screen kr --universe kospi
uv run python Search.py screen kr --universe kospi200
```

## 5단계: 사이트 빌드

DB의 스캔 결과를 읽어 `site/` 아래에 GitHub Pages 정적 사이트를 생성합니다.
```bash
# 전체 빌드 (기본값: all)
uv run python Search.py site --no-open
uv run python Search.py site main --no-open
uv run python Search.py site market kospi --no-open
uv run python Search.py site market us-all --no-open
uv run python Search.py site admin --no-open
uv run python Search.py site db_admin
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
uv run python Search.py all kr --universe kospi
uv run python Search.py all kr --universe kospi200
uv run python Search.py analyze us --universe sp500
```

## 출력

스캔 결과의 원천은 PostgreSQL입니다. GitHub Pages 사이트는 `market_scanner/reports/site/build.py`가 DB에서 직접 읽어 `site/` 아래에 생성합니다.

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

### DB 전환: Neon ↔ 로컬 Docker

연결 우선순위: `--database-url 인수` > `환경변수 DATABASE_URL (.env)` > 로컬 Docker 기본값

**Neon DB 사용** (`.env`에 Neon URL 설정 후 그냥 실행)
```bash
# .env
DATABASE_URL=postgresql://<user>:<password>@<host>/neondb?sslmode=require&channel_binding=require
```
`.env`는 `.gitignore`에 포함되어 있어 커밋되지 않습니다. Neon URL은 [Neon Console](https://console.neon.tech) → Connection Details에서 확인합니다.

**로컬 Docker 사용**
```bash
# Docker 실행
docker compose up -d postgres

# 방법 A: --database-url 인수로 일회성 오버라이드
uv run python Search.py counts --database-url "postgresql://searchmarket:searchmarket@localhost:5433/searchmarket"

# 방법 B: 환경변수 일시 오버라이드
DATABASE_URL="postgresql://searchmarket:searchmarket@localhost:5433/searchmarket" uv run python Search.py counts

# 방법 B: .env 없이 실행하면 로컬 Docker 기본값 자동 사용
```

현재 연결된 DB 확인:
```bash
python -c "from market_scanner.storage.connection import connect; conn = connect(); print('host:', conn.info.host)"
```

## 사이트 대시보드

```bash
uv run python Search.py site --no-open
```

`site/`에는 GitHub Pages용 정적 대시보드가 생성됩니다. 자동 열기를 원하면 `--no-open`을 빼고 실행합니다.

대시보드는 DB의 `daily_macro`, `scan_results`, `market_snapshots`, `sector_snapshots` 최신 데이터를 기반으로 메인 핵심 지표(S&P500, Nasdaq100, KOSPI, KOSDAQ, VIX, 미국10년물, DXY, USDKRW, WTI, Gold, BTC, ETH), 글로벌 지수·원자재·환율/통화 강약, 매크로 지표, US/KR 종합 시황, 미국 섹터 ETF, 섹터 히트맵, 리더십, 당일 Top 종목, 워치리스트를 표시합니다.

상단 `관리` 탭(`site/admin/index.html`)은 빌드 시점의 PostgreSQL 테이블 목록·행 수·컬럼·최근 데이터 샘플을 보여주는 정적 읽기 전용 페이지입니다. 데이터 수정/삭제는 DB 또는 CLI에서 처리합니다.

## 데이터 정책

- `instruments`: 종목마스터의 우선 원천입니다.
- `universe_memberships`: `nasdaq`, `nyse`, `amex`(거래소 전체), `nasdaq100`, `sp500`, `dow30`(지수), `kospi`, `kosdaq`, `kospi100`, `kospi200`, `kosdaq150` 같은 분석/필터 단위 멤버십입니다. US는 `refresh us` 한 번으로 6개, KR은 `refresh kr` 한 번으로 5개 universe가 동시 갱신됩니다.
- `market_scanner/assets/instruments.json`: DB가 비어 있거나 연결되지 않을 때 쓰는 seed/fallback입니다. 스캔 실행은 이 JSON을 자동 갱신하지 않습니다.
- `market_scanner/assets/global_indices_meta.json`, `commodities_meta.json`: 글로벌 지수·원자재는 FDR 자동 발견이 불가능하므로 JSON이 심볼 정의 원본입니다. 새 심볼 추가 시 JSON 편집 후 `Search.py refresh global-indices` 또는 `Search.py refresh commodities`로 DB에 반영합니다. 현재 글로벌 지수는 35개, 원자재는 27개입니다.
- `market_scanner/assets/sector_etfs_meta.json`: 섹터 ETF 유니버스의 원본입니다. `XLK`, `XLV`, `XLF`, `XLY`, `XLP`, `XLI`, `XLE`, `XLU`, `XLB`, `XLC`, `XLRE`를 기본 GICS 섹터 프록시로 사용하고, `VNQ`는 리츠 보조 프록시로 함께 수집합니다.
- 테마 ETF는 별도 스캔 없이 US 스캔 결과에서 파생됩니다. 대상 심볼은 `markets.py`의 `_THEME_PROXY_SYMBOLS` 상수로 관리합니다.
- 한국 시장 유니버스는 FinanceDataReader를 우선 사용하고, 실패 시 Naver Finance로 fallback합니다. 정적 JSON fallback(`kospi_static_meta.json`, `kosdaq_static_meta.json`)은 제거되었습니다.
- KOSPI/KOSDAQ 가격 히스토리는 FinanceDataReader를 사용합니다. US 가격 히스토리는 yfinance만 사용합니다.
- `news` 단계는 DB의 최신 `scan_results`가 있어야 실행되며, `all`에는 포함하지 않습니다.

## 패키지 구조

```text
market_scanner/
  models.py             # 공통 데이터 모델·설정
  pipeline.py           # 단계 순서 제어
  analysis/             # 지표 계산·스크리닝
  collectors/           # 가격·펀더멘탈·뉴스·번역 수집
  config/markets.py     # 시장 설정·유니버스/메타데이터 로더
  reports/              # Markdown/HTML/Page 렌더링
    site/               # 정적 사이트 빌더 (site/ 생성)
  storage/              # PostgreSQL 유틸리티
  assets/               # seed/cache 파일
  templates/            # HTML 리포트 템플릿/CSS
```

## GitHub Actions

| 워크플로우 | 실행 시각 | 대상 |
|---|---|---|
| `daily-scan.yml` | KST 08:05 | US Market |
| `daily-scan-overview.yml` | KST 08:20 | 글로벌 지수·섹터 ETF·테마 ETF·원자재 |
| `daily-scan-kospi.yml` | KST 16:05 | kr --universe kospi |
| `daily-scan-kosdaq.yml` | KST 16:35 | kr --universe kosdaq |
| `deploy-pages.yml` | 스캔 성공 후 자동, 또는 수동 실행 | GitHub Pages 사이트 빌드·배포 |

```bash
python -c "from market_scanner.storage.connection import connect; conn = connect(); print('connected:', conn.info.host)"
# localhost 출력되면 로컬 DB
```
