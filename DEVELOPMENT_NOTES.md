# Search60 Development Notes

Last updated: 2026-04-30

이 문서는 프로젝트를 함께 개발하면서 계속 갱신하는 개발/운영 노트입니다. 자동 생성되는 `analysis/Analysis_*.md` 리포트와 구분하기 위해, 기능 개발 판단과 코드 구조 이해에 필요한 내용을 이 파일에 모읍니다.

## Project Summary

Search60은 여러 시장의 종목/지수/ETF/원자재를 대상으로 60/120/240일 이동평균선 근접 여부를 스캔하고, CSV, Markdown, HTML 리포트 및 GitHub Pages 사이트를 생성하는 Python 프로젝트입니다.

지원 시장:

- `nasdaq100`: NASDAQ 100 독립 스캔 시장입니다. `nasdaq100_static_meta.json`과 instruments 메타데이터를 사용합니다.
- `sp500`: S&P 500 독립 스캔 시장입니다. 현재 구성 종목과 `sp500_static_meta.json` 기반 메타데이터를 사용합니다.
- `us-all`: NASDAQ Trader 상장 심볼 디렉터리를 사용해 미국 전체 상장 보통주를 수집하는 선택형 시장입니다. ETF, 워런트, 우선주, 채권성 증권은 제외하고, 실패 시 캐시 또는 NASDAQ 100+S&P 500 fallback을 사용합니다.
- `us`: 미국 주식 legacy combined 스캔입니다. 정적 NASDAQ 100 메타데이터와 S&P 500 라이브/캐시 목록을 결합하며, 기존 산출물 호환용으로 유지합니다.
- `kospi`: KOSPI 대형주. 정적 메타데이터와 FinanceDataReader 기반 KOSPI200 목록을 결합합니다.
- `kosdaq`: KOSDAQ 성장주. 정적 메타데이터와 FinanceDataReader 기반 KOSDAQ150 목록을 결합합니다.
- `kospi-all`: FDR/KRX가 가능하면 KOSPI 전체 종목을 수집하고, 실패 시 네이버 시가총액 목록과 정적 메타데이터 fallback을 사용하는 선택형 시장입니다.
- `kosdaq-all`: FDR/KRX가 가능하면 KOSDAQ 전체 종목을 수집하고, 실패 시 네이버 시가총액 목록과 정적 메타데이터 fallback을 사용하는 선택형 시장입니다.
- `global-indices`: 주요 글로벌 지수 정적 워치리스트입니다.
- `theme-proxies`: 테마별 ETF 프록시 정적 워치리스트입니다.
- `commodities`: 원자재 선물 정적 워치리스트입니다.

## Main Entry Points

- `Search.py`: CLI 진입점입니다. `--market`, `--stage`, `--date`, `--force`, `--workers`, `--limit`, `--setup-scheduler` 옵션을 처리합니다.
- `AGENTS.md`: Codex가 프로젝트 작업 시 우선 참고하는 지침 문서입니다. 코드 변경 시 함께 갱신해야 하는 주요 문서 관계도를 포함합니다.
- `docs/database_recommendation.md`: CSV에서 PostgreSQL로 전환하기 위한 권장 구조와 단계별 이전 계획입니다.
- `docs/database_schema_v1.sql`: PostgreSQL 스키마 초안 DDL입니다.
- `docs/database_table_guide.md`: DB 테이블별 역할과 주요 컬럼 설명서입니다.
- `market_scanner/db.py`: PostgreSQL 스키마 적용, 기준 데이터 seed, CSV 스캔 결과 적재 유틸리티입니다.
- `market_scanner/markets.py`: 시장 정의, 메타데이터 로더, 유니버스 로더, quote URL 생성기를 관리합니다.
- `market_scanner/pipeline.py`: 시장별 가격 히스토리 수집, RSI/추세/점수 계산, Markdown/HTML 리포트 생성을 담당합니다. 한국 시장은 FinanceDataReader 히스토리를 우선 사용하고 실패 시 yfinance로 fallback합니다.
- `market_scanner/compat.py`: 기존 루트 출력 파일명 규칙을 유지하는 호환 레이어입니다.
- `market_scanner/site_builder.py`: 최신 루트 산출물을 모아 GitHub Pages용 `site/` 정적 사이트를 재생성합니다.
- `market_scanner/templates/report.html`: 리포트 UI 템플릿입니다. Bootstrap, Chart.js, marked CDN을 사용합니다.
- `market_scanner/templates/report.css`: 리포트 공통 스타일입니다.

## Quote Link Policy

리포트에서 티커를 클릭했을 때의 목적지는 시장별 사용자 경험에 맞춥니다.

- 모든 시장: Investing 상세/검색 URL을 사용하되 출력 시 `kr.investing.com` 도메인으로 강제합니다. 기존 캐시에 `www.investing.com` URL이 저장되어 있어도 렌더링 시 한국 도메인으로 변환합니다.
- KOSPI, KOSDAQ: NASDAQ 100과 같은 Investing 상세 URL 캐시를 우선 사용합니다. 캐시에 없는 종목은 상세 URL 해석을 시도하고, 실패하면 `kr.investing.com/search?q=종목코드` 검색 링크로 fallback합니다.

## News Briefing Policy

US 기준 밤새 뉴스 수집은 가능합니다. 다만 렌더링 중 종목별 실시간 뉴스 요청을 보내면 느려지고 실패 가능성이 커지므로, 별도 수집 단계에서 캐시를 만든 뒤 리포트는 캐시만 읽는 구조를 기본 방향으로 둡니다.

- 캐시 위치: `market_scanner/assets/news_cache.json`
- UI 위치: 상세페이지 상단 `종목 리스트`, `분석 리포트` 옆 `뉴스 브리핑` 탭
- 현재 동작: `Search.py --stage news`가 스캔 CSV의 종합점수 상위 종목을 기준으로 yfinance 뉴스를 수집해 캐시를 만들고, 리포트는 캐시가 있으면 뉴스 항목을 표시합니다. 캐시가 없으면 수집 필요 안내를 표시합니다.
- 후보 데이터 소스: yfinance `Ticker.news`, Yahoo Finance RSS/검색, 유료 뉴스 API. 안정성과 사용 제한을 고려해 수집 단계를 분리하는 것이 안전합니다.

## Pipeline Flow

일반 실행:

```powershell
.\.venv\Scripts\python.exe Search.py --market nasdaq100
.\.venv\Scripts\python.exe Search.py --market sp500
```

단계별 흐름:

1. `scan`: 시장 유니버스를 불러오고 가격 히스토리와 가능한 메타데이터를 가져와 `data/`에 CSV를 저장합니다. 한국 시장은 FinanceDataReader OHLCV를 우선 사용하고, 그 외 시장은 yfinance 히스토리를 사용합니다. KRX listing 실패 시 한국 전체 유니버스는 네이버 시가총액 목록으로 보강합니다.
2. `analyze`: CSV를 기반으로 요약 Markdown 리포트를 생성합니다.
3. `translate`: `nasdaq100`, `sp500`, `us-all`, legacy `us` 시장의 이름/설명 일부를 번역하고 sector alias를 적용합니다.
4. `news`: 최신 CSV의 상위 종목에서 yfinance 뉴스 항목을 수집해 `market_scanner/assets/news_cache.json`에 날짜/시장별로 저장합니다.
5. `render`: CSV와 Markdown을 HTML 리포트로 렌더링합니다.
6. `all`: `scan`, `analyze`, `translate`, `render`를 순서대로 실행합니다. 뉴스 수집은 실행 시간과 외부 요청량 때문에 별도 opt-in 단계로 둡니다.

PostgreSQL 저장 흐름:

1. `docker compose up -d postgres`로 로컬 DB를 실행합니다.
2. `python -m market_scanner.db init`으로 `docs/database_schema_v1.sql`을 적용하고 시장/유니버스 기준 데이터를 seed합니다.
3. 기존 스캔 CSV를 생성하거나 재사용합니다.
4. `python -m market_scanner.db load-csv --market kospi --date YYYYMMDD`로 CSV 결과를 DB에 upsert합니다.
5. `python -m market_scanner.db counts`로 핵심 테이블 적재 건수를 확인합니다.

기존 파일명 규칙:

- NASDAQ 100: `data/Data_Nasdaq100_YYYYMMDD.csv`, `analysis/Analysis_Nasdaq100_YYYYMMDD.md`, `reports/Report_Nasdaq100_YYYYMMDD.html`
- S&P 500: `data/Data_Sp500_YYYYMMDD.csv`, `analysis/Analysis_Sp500_YYYYMMDD.md`, `reports/Report_Sp500_YYYYMMDD.html`
- US legacy combined: `data/Data_YYYYMMDD.csv`, `analysis/Analysis_YYYYMMDD.md`, `reports/Report_YYYYMMDD.html`
- KOSPI: `data/Data_Kospi_YYYYMMDD.csv`, `analysis/Analysis_Kospi_YYYYMMDD.md`, `reports/Report_Kospi_YYYYMMDD.html`
- KOSDAQ: `data/Data_Kosdaq_YYYYMMDD.csv`, `analysis/Analysis_Kosdaq_YYYYMMDD.md`, `reports/Report_Kosdaq_YYYYMMDD.html`
- 기타 시장: `data/Data_{MarketName}_YYYYMMDD.csv`, `analysis/Analysis_{MarketName}_YYYYMMDD.md`, `reports/Report_{MarketName}_YYYYMMDD.html`

CSV 경로는 `data/`가 canonical 위치입니다. Markdown 경로는 `analysis/`, HTML 경로는 `reports/`가 canonical 위치입니다. 과거 루트 `Data_*.csv`, `Analysis_*.md`, `Report_*.html`은 읽기 fallback으로만 지원합니다.

## Data Model And Scoring

주요 데이터 모델은 `market_scanner/models.py`에 있습니다.

- `ScanSettings`: 이동평균 기간, 근접 임계값, 히스토리 기간, worker 수, 출력 경로를 정의합니다.
- `MarketDefinition`: 시장별 label, currency, universe/metadata/URL 로더를 정의합니다.
- `ScanRecord`: 스캔 결과의 내부 표현입니다.

주요 계산:

- RSI: `market_scanner/indicators.py::calc_rsi`
- MACD: `market_scanner/indicators.py::calc_macd`
- 볼린저 밴드: `market_scanner/indicators.py::calc_bollinger`
- 추세 점수: `market_scanner/indicators.py::calc_trend`
- 종합 점수: `market_scanner/pipeline.py::score_record`

현재 종합 점수는 PRD v1.1의 복합 스코어링 구조를 반영해 차트 30%, 기술지표 25%, 재무 20%, 테마 15%, 수급 10%로 계산합니다. CSV에는 `chart_score`, `technical_score`, `fundamental_score`, `theme_score`, `flow_score`, `composite_score`를 함께 저장합니다.

추가 수집/산출 컬럼:

- 가격 히스토리 기반: `macd`, `macd_signal`, `macd_hist`, `macd_state`, `bollinger_width_pct`, `bollinger_percent_b`
- 당일 캔들 기반: `open`, `high`, `low`, `close`, `prev_close`, `gap_pct`, `candle_body_pct`, `candle_range_pct`, `upper_shadow_pct`, `lower_shadow_pct`, `candle_type`
- yfinance `info` 기반: `price_to_book`, `return_on_equity`, `revenue_growth`, `market_cap`

추세 점수는 `calc_trend`에서 0~5점으로 계산합니다. 기준은 현재가가 단기 MA 위에 있는지, 단기 MA가 중기/장기 MA보다 위인지, 단기/중기 MA의 20거래일 전 대비 기울기가 상승인지입니다.

## Site Build Flow

GitHub Pages 배포는 `python -m market_scanner.site_builder`로 `site/` 폴더를 재생성합니다. 로컬 실행에서는 빌드 후 `site/index.html`을 기본 브라우저로 자동으로 열고, CI/GitHub Actions에서는 자동 열기를 건너뜁니다. 로컬에서도 `--no-open`을 붙이면 브라우저를 열지 않습니다.

사이트 생성 방식:

- `data/`의 최신 `Data_*.csv`를 기준으로 사이트 페이지를 생성합니다. 과거 루트 CSV가 있으면 fallback으로 읽을 수 있습니다.
- Pages 상세페이지는 `data/`의 최신 CSV를 현재 템플릿으로 다시 렌더링합니다. `reports/Report_*.html`은 개별 HTML 리포트 산출물로 보관되며, 사이트 페이지의 템플릿 최신화 기준은 CSV 재렌더링입니다.
- US 전체 데이터에서 NASDAQ 100, S&P 500, Dow 30 페이지를 파생 생성합니다.
- 메인 페이지 상단에는 종합 시장 점수, 주식 시장 체력, 매크로 리스크, 섹터·테마 히트맵, 오늘의 핵심 후보를 표시합니다. 아래에는 시장별 스냅샷, 섹터 리더십, 오늘의 관찰 종목을 이어서 표시합니다.
- 메인 페이지의 사용자-facing 섹션/카드 제목은 한국어를 우선 사용합니다. 오늘의 관찰 종목 링크는 각 시장의 `quote_url_builder`를 사용해 Investing 한국 상세페이지로 연결하고, 종가는 시장별 통화/소수점 규칙으로 표시합니다.
- 메인페이지는 preview-home v2 디자인을 반영해 `site/index.html`에 생성합니다. `site/preview-home/index.html`은 같은 디자인을 확인하는 보조 미리보기 페이지입니다.
- 상세 페이지는 좌측 종목 리스트와 우측 인사이트 패널 구조입니다. 헤더에는 제목 아래 기준일/행 수와 `KST` 기준 갱신시간을 표시합니다. 상단 Signal Strip에는 이동평균선 근접 수, 시장 상태와 리딩/약세 섹터, RSI 온도 분포, 강세 비율, VIX 공포지수 해석을 표시합니다. 우측에는 Sector Heatmap, Setup Buckets, MA Distance vs RSI Scatter를 표시합니다.
- 글로벌 지수, 테마 ETF, 원자재는 개별 페이지와 홈 overview에 반영됩니다.
- `site/archive/YYYYMMDD/{slug}/index.html`에 날짜별 사본을 둡니다.

주의: `site_builder.py`는 S&P 500 파생 페이지 생성 시 Wikipedia 요청을 시도할 수 있습니다. 네트워크 실패 시 캐시 파일로 fallback합니다.

## Automation

GitHub Actions:

- `.github/workflows/daily-scan.yml`: US 스캔, KST 08:05 기준입니다.
- `.github/workflows/daily-scan-kospi.yml`: KOSPI 스캔, KST 16:05 기준입니다.
- `.github/workflows/daily-scan-kosdaq.yml`: KOSDAQ 스캔, KST 16:35 기준입니다.
- `.github/workflows/daily-scan-overview.yml`: 글로벌 지수/테마 ETF/원자재 스캔, KST 08:20 기준입니다.
- `.github/workflows/deploy-pages.yml`: 데이터/리포트/코드 변경 후 Pages 사이트를 빌드하고 배포합니다. 스캔 workflow 4종이 성공적으로 완료되면 `workflow_run`으로 자동 실행되어, `GITHUB_TOKEN` push가 별도 push workflow를 트리거하지 않는 GitHub Actions 제한을 우회합니다.

## Local Development Notes

현재 로컬에서는 기본 `python` 명령이 제대로 동작하지 않는 것으로 확인되었습니다. 개발 검증은 가상환경의 Python을 명시해서 실행하는 것이 안전합니다.

```powershell
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -m compileall Search.py market_scanner
.\.venv\Scripts\python.exe Search.py --help
```

네트워크 의존성이 있는 명령:

- `scan` 단계는 yfinance, Wikipedia, FinanceDataReader, Naver Finance, Investing 검색 요청을 사용할 수 있습니다. 한국 시장의 OHLCV는 FinanceDataReader를 우선 사용하고 실패 시 yfinance로 fallback합니다.
- `translate` 단계는 deep-translator/GoogleTranslator 요청을 사용할 수 있습니다.
- `news` 단계는 yfinance `Ticker.news` 요청을 사용하며, `--news-symbols`, `--news-items`, `--news-workers`로 수집 범위를 조절합니다.
- 로컬 sandbox나 네트워크 상태에 따라 재현성이 달라질 수 있습니다.

## Market Membership Caches

S&P 500 구성 종목은 외부 소스 조회 실패에 대비해 캐시를 사용합니다.

- Primary source: Wikipedia S&P 500 constituents page
- Cache: `market_scanner/assets/sp500_members_cache.json`

캐시는 과거 단순 배열 형식과 새 구조화 형식을 모두 읽을 수 있습니다. 새로 저장될 때는 다음 메타데이터를 포함합니다.

- `source`: 구성 종목을 가져온 원천 URL
- `updated_at`: UTC 갱신 시각
- `count`: 구성 종목 수
- `tickers`: 심볼 목록

캐시가 45일보다 오래되면 콘솔에 stale warning을 출력합니다. S&P 500 고정 메타데이터는 `market_scanner/assets/sp500_static_meta.json`에서 관리합니다.

`us-all`은 NASDAQ Trader 상장 심볼 디렉터리 조회 실패에 대비해 `market_scanner/assets/us_listed_symbols_cache.json`을 사용합니다. 이 캐시는 14일보다 오래되면 stale warning을 출력하며, 스캔 대상은 ETF와 비보통주성 증권을 제외한 미국 상장 보통주 중심입니다.

## Current Repository State Notes

2026-04-28 확인 내용:

- 최신 CSV 샘플은 정상적으로 읽힙니다.
- `data/Data_20260428.csv`: US 최신 CSV로 렌더 검증
- `data/Data_Kospi_20260427.csv`: 202 rows
- `data/Data_Kosdaq_20260427.csv`: 135 rows
- `data/Data_GlobalIndices_20260427.csv`: 10 rows
- `.\.venv\Scripts\python.exe -m compileall Search.py market_scanner` 통과
- `.\.venv\Scripts\python.exe Search.py --help` 통과
- `.\.venv\Scripts\python.exe Search.py --market us --stage render --date 20260428` 통과. 생성된 `reports/Report_20260428.html`의 US 티커 링크가 `kr.investing.com`으로 출력되는 것을 확인함.
- 공포지수 원인 확인: 기본 로컬 실행에서는 프록시가 `127.0.0.1:9`로 잡혀 VIX 요청이 실패할 수 있음. `yfinance` timezone cache 위치도 프로젝트 내부 `market_scanner/assets/.yfinance_cache`로 고정함. 외부 네트워크 권한에서는 VIX 값이 정상 조회되어 리포트에 반영됨.
- `.\.venv\Scripts\python.exe -m market_scanner.site_builder` 통과. 로컬 네트워크 제한으로 Wikipedia 요청은 실패했지만, 캐시 기반으로 `site/` 8개 페이지 생성까지 진행됨.
- 상세페이지 v2 렌더 확인: `reports/Report_Kospi_20260427.html`, `site/kospi/index.html`, `site/dow30/index.html`에 Sector Heatmap, Setup Buckets, MA Distance Scatter, 상단 VIX 변동성 요약 반영됨.
- 상세페이지 UX 개선: KOSPI/KOSDAQ 티커 링크도 NASDAQ 100과 같은 Investing 상세 URL 캐시를 우선 사용합니다. Sector Heatmap은 섹터 평균 등락률 기준으로 강세가 앞쪽, 약세가 뒤쪽으로 정렬됩니다. MA Distance vs RSI에는 지표 설명과 한줄 해석을 추가했고 scatter point hit radius를 키웠습니다.
- 상세페이지 링크 개선: 모든 시장의 Investing 링크는 한국 도메인으로 출력합니다. US/글로벌/테마/원자재는 상세 URL 캐시를 우선 사용하고, KOSPI/KOSDAQ은 무네트워크 검색 URL을 사용합니다.
- 상세페이지 정렬 개선: 종목 리스트의 추세 컬럼은 문자열이 아니라 추세 점수 기준으로 정렬하며, 첫 클릭 시 강한 추세가 먼저 보입니다.
- 스캔 데이터 컬럼 추가: `change_pct`는 현재 종가와 전일 종가 기준 등락률입니다. 상세페이지 종목 리스트의 `등락률` 컬럼과 섹터별 상승률 Heatmap에 사용합니다.
- `Analysis_*.md`와 `Report_*.html`은 루트가 아니라 각각 `analysis/`, `reports/` 폴더에서 관리합니다. 과거 루트 파일은 읽기 fallback으로만 지원합니다.

## Metadata Fix Notes

- 2026-04-28: `nasdaq100`과 `sp500`을 독립 CLI 시장으로 분리했습니다. 새 US workflow는 두 시장을 각각 스캔해 `Data_Nasdaq100_YYYYMMDD.csv`, `Data_Sp500_YYYYMMDD.csv`를 생성합니다. 기존 `us` 결합 스캔은 호환용으로 유지하고, 사이트 빌더는 독립 CSV가 없을 때만 기존 결합 US CSV에서 NASDAQ 100/S&P 500/Dow 30 페이지를 fallback 생성합니다.
- 2026-04-28: `site_builder.py`가 빈 최신 CSV를 만나면 해당 날짜를 건너뛰고 이전 정상 CSV를 찾도록 수정했습니다. 예: `Data_Commodities_20260428.csv`가 비어 있어도 `Data_Commodities_20260427.csv`로 사이트 빌드가 계속됩니다.
- 2026-04-28: `market_scanner/assets/instruments.json`을 공통 종목 마스터로 추가했습니다. 모든 시장의 `metadata_loader`는 이 JSON을 우선 읽고, 기존 시장별 `*_static_meta.json`은 호환 fallback으로 유지합니다. 스캔 단계는 새 종목의 `symbol`, `display_symbol`, `name_en`, `name_local`, `sector`, `description`을 instruments에 누적하되 `static`/`manual` 출처 레코드는 자동 스캔값으로 덮어쓰지 않습니다.
- 2026-04-28: KOSPI/KOSDAQ 스캔에서 yfinance `Ticker.info`를 실제 조회한 티커 객체에서 읽도록 수정했습니다. 렌더링 단계도 정적 메타데이터와 FinanceDataReader 한국 종목명으로 placeholder 이름/섹터를 보정하므로, 기존 CSV에 `047040.KS`/`Unknown`처럼 저장된 값도 사이트 재생성 시 가능한 범위에서 정상 종목명/섹터로 표시됩니다. 한국 시장 화면의 종목명은 한글 표시를 우선하며, 한글명을 확보하지 못한 경우 영어 회사명 대신 종목코드를 표시합니다.
- 2026-04-30: KOSPI/KOSDAQ 계열(`kospi`, `kosdaq`, `kospi-all`, `kosdaq-all`)의 가격 히스토리 수집은 FinanceDataReader를 먼저 사용합니다. FDR 조회 실패 또는 히스토리 부족 시 기존 yfinance 경로로 fallback합니다. FDR/pykrx listing 엔드포인트가 실패하는 환경에서는 네이버 시가총액 페이지를 파싱해 `kospi-all`/`kosdaq-all` 전체 유니버스를 보강합니다.

## 2026-04-29 Pages Automation Note

- 스캔 workflow가 `GITHUB_TOKEN`으로 결과를 커밋/푸시하면 GitHub Actions의 재귀 방지 정책 때문에 `push` 기반 Pages workflow가 자동 실행되지 않을 수 있습니다. `deploy-pages.yml`에 `workflow_run` 트리거를 추가해 US, overview, KOSPI, KOSDAQ 스캔 성공 후 Pages 빌드/배포가 이어지도록 했습니다.

## 2026-04-29 Detail Page UI Note

- 상세페이지 상단 전환 버튼은 노란색 테두리로 강조하고, Signal Strip의 영문 `Avg RSI`, `Bull Breadth`, `Fear` 표기를 한글화했습니다. MA60/120/240 근접 수는 하나의 큰 박스 안에 묶고 복수 MA 항목은 제거했습니다.
- 기존 우측 `Fear & Volatility` 패널은 제거하고 동일한 공포지수 해석 UI를 상단 Signal Strip으로 이동했습니다. 상단에는 평균 등락률과 강세/보합/약세 섹터 수를 기반으로 현재 상세페이지 시장 상태도 표시합니다. Sector Heatmap 제목 옆에는 전체 상승/하락 종목 수를 함께 표시합니다. 종목 리스트 내부 탭의 `분석 리포트` 항목은 제거하고 상단 전환 버튼에서만 접근하도록 정리했습니다.
- 상단 Signal Strip에는 근접 종목 비중, 리딩/약세 섹터, RSI 온도 분포, 추세/섹터 breadth 보조 정보를 추가했습니다.

## 2026-04-29 KOSPI200 Metadata Note

- KOSPI static metadata and instruments records were realigned to 200 KOSPI 200 components. When the static KOSPI metadata has at least 200 symbols, `_kospi_universe()` treats it as authoritative and does not append the FinanceDataReader market-cap fallback.

## Known Risks And Improvement Areas

- S&P 500 유니버스 갱신은 네트워크 실패 시 캐시 품질에 의존합니다.
- S&P 500 캐시는 무료 소스 기반이므로 공식 라이선스 데이터 피드만큼 보장되지는 않습니다.
- `site_builder.py`가 `site/`를 통째로 삭제 후 재생성합니다. 사이트 빌드 중 수동으로 넣은 파일은 유지되지 않습니다.
- 시장별 파일명 규칙이 `compat.py`, `site_builder.py`, README, GitHub Actions에 중복되어 있어 새 시장 추가 시 여러 위치를 동시에 갱신해야 합니다.
- `pipeline.py`가 스캔, 분석 문장 생성, HTML 데이터 변환을 모두 포함하고 있어 기능이 늘면 모듈 분리가 필요할 수 있습니다.
- 외부 API 실패 시 일부 유니버스가 캐시/정적 목록으로 축소될 수 있습니다.
- 리포트 UI는 CDN 의존성이 있습니다. 오프라인/차단 환경에서는 차트/Markdown 렌더링이 깨질 수 있습니다.

## Candidate Features

앞으로 개발하기 좋은 기능 후보:

- 관심종목 watchlist 및 우선 표시
- 전일 대비 변화 추적: 신규 근접, 이탈, 점수 변화, RSI 변화
- 스캔 이력 저장 및 종목별 타임라인
- 조건식 알림: 예를 들어 `near_count >= 2`, `RSI < 40`, `trend_score >= 3`
- 점수 산식 설정화: 가중치와 threshold를 CLI/설정 파일로 분리
- 종목 상세 페이지: MA/RSI/가격 히스토리 차트
- 테스트 추가: indicators, compat path, scoring, site builder 단위 테스트

## Improvement Backlog

2026-04-27 논의된 개선 방향:

- Yahoo Finance 확장 데이터 활용: 배당/분할, 재무제표, 실적 일정, 애널리스트 추천/목표가, 기관/내부자 보유, 옵션 체인, 뉴스, ESG/지속가능성 데이터를 단계적으로 추가합니다.
- 메인 페이지 고도화: 상단 카드 5개를 종합 시장 점수, 주식 시장 체력, 매크로 리스크, 섹터·테마 히트맵, 오늘의 핵심 후보 중심으로 재구성했습니다. 다음 단계는 전일 대비 변화와 신호 변화 추적입니다.
- 상세 페이지 v2: B안 Heatmap 중심성과 C안 리서치 대시보드 구조를 혼합했습니다. 상단 Signal Strip, 좌측 종목 리스트, 우측 Sector Heatmap/Fear/Setup/Scatter 패널 구조입니다.
- 섹터별 상승률 Heatmap: 전일 종가 대비 `change_pct`를 섹터별로 동일가중 평균해 색상/정렬 기준으로 사용합니다. 타일에는 중앙값, 상승 종목 비율, 종목 수를 함께 표시해 평균이 일부 극단값에 흔들렸는지 확인할 수 있게 합니다.
- 종목 리스트 컬럼 정리: MA60/120/240 차이율 컬럼은 화면에서 숨기되, Setup Buckets와 MA Distance Scatter 계산을 위해 JSON DATA에는 유지합니다.
- 공포지수 안정화: VIX는 실시간 yfinance 조회를 우선 사용하고, 글로벌 지수 스캔에 `^VIX`를 포함해 향후 CSV fallback으로도 값을 표시할 수 있게 했습니다.
- 뉴스 브리핑: 상단 탭을 추가했습니다. 현재는 캐시 기반 표시 구조이며, 실제 밤새 뉴스 수집은 별도 `news` 단계 또는 workflow로 분리하는 방향이 안전합니다.
- 상세 페이지 해석 패널: MA Distance는 현재가와 가장 가까운 MA(60/120/240)의 이격률, RSI는 과열·과매도 온도 지표로 표시합니다.
- 분석 리포트: 기존 MA 근접 중심 리포트에서 시장 총평, 핵심 후보, 상승추세 눌림, 과매도 반등, 복수 MA 수렴, 수급·업사이드, MACD 개선, 캔들 신호, 섹터, 리스크 점검 구조로 개편했습니다.
- 상세 페이지 종목 리스트: 기본 정렬은 종목명/티커순이 아니라 당일 상승률(`change_pct`) 내림차순입니다.
- 상세 페이지 종목 리스트: 최신 스캔 CSV에 OHLC 캔들 컬럼이 있으면 등락률 옆에 미니 캔들 아이콘을 표시합니다.
- 스캔 안정화: 실패 종목 수와 샘플 티커를 scan 로그에 표시합니다. `Search.py --limit N`으로 소수 종목만 빠르게 스캔해 신규 컬럼 저장 여부를 검증할 수 있습니다.
- 한국 전체 유니버스: 기본 `kospi`/`kosdaq`은 대형주 중심을 유지하고, 전체 수집은 `kospi-all`/`kosdaq-all` 별도 시장으로 제공합니다. FDR/KRX listing이 실패하면 네이버 시가총액 목록으로 전체 종목을 보강합니다.
- 미국 전체 유니버스: 기본 `nasdaq100`/`sp500`은 운영용 범위를 유지하고, 전체 수집은 `us-all` 별도 시장으로 제공합니다. 소스는 NASDAQ Trader `nasdaqlisted.txt`/`otherlisted.txt`이며, yfinance 호환을 위해 클래스 주식 구분자는 `.`에서 `-`로 정규화합니다.
- Dow 30 파생 페이지: 별도 스캔 없이 US 스캔 결과에서 Dow 30 구성 종목을 필터링해 `site/dow30/index.html`을 생성합니다.
- CSV 파일 정리: 루트에 흩어진 `Data_*.csv`를 `data/` 폴더로 이동하고, 새 스캔 결과도 `data/`에 저장하도록 변경했습니다.
- 디자인 개선: 현재 Bootstrap 기반 어두운 대시보드를 더 전문적인 금융 터미널/리서치 대시보드 스타일로 개선합니다. 정보 밀도, 타이포그래피, 차트, 카드 계층, 모바일 가독성을 함께 다룹니다.
- HTML 생성 방식 재검토: GitHub Pages를 유지하면 최종 결과는 정적 HTML이어야 하지만, 시장/날짜별 큰 HTML을 매번 생성하는 대신 공통 shell + JSON 데이터 파일 방식의 SPA 형태를 검토합니다.
- CSV에서 DB로 전환: 초기에는 SQLite 또는 DuckDB로 로컬 이력 저장을 만들고, 맥북/윈도우 양쪽 공유가 필요하면 중앙 Postgres 계열(Supabase/Neon 등) 또는 Turso/libSQL 같은 sync 가능한 SQLite 계열을 검토합니다.

## Maintenance Rules

이 문서는 다음 상황마다 갱신합니다.

- 새 기능을 추가하거나 기존 기능의 동작이 바뀐 경우
- `AGENTS.md`의 Codex 작업 규칙이나 문서 관계도가 바뀐 경우
- CLI 옵션, 파일명 규칙, 배포 흐름이 바뀐 경우
- 중요한 버그/리스크를 발견하거나 해결한 경우
- 새 시장/새 데이터 소스/새 출력 형식을 추가한 경우
- 검증 방법이나 로컬 실행 방식이 바뀐 경우

갱신 시에는 `Last updated` 날짜와 관련 섹션을 함께 수정합니다.
