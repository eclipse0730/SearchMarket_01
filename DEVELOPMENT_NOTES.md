# Search60 Development Notes

Last updated: 2026-05-05

이 문서는 프로젝트를 함께 개발하면서 계속 갱신하는 개발/운영 노트입니다. 기능 개발 판단과 코드 구조 이해에 필요한 내용을 이 파일에 모읍니다.

## Project Summary

Search60은 여러 시장의 종목/지수/ETF/원자재를 대상으로 60/120/240일 이동평균선 근접 여부를 스캔하고, CSV, Markdown, HTML 리포트 및 GitHub Pages 사이트를 생성하는 Python 프로젝트입니다.

권장 실행 단위:

- `us`: 미국 주식 시장 전체 활성 종목을 DB `instruments` 기준으로 스캔합니다.
- `kospi`: KOSPI 시장 전체 활성 종목을 DB `instruments` 기준으로 스캔합니다.
- `kosdaq`: KOSDAQ 시장 전체 활성 종목을 DB `instruments` 기준으로 스캔합니다.
- `global-indices`: 주요 글로벌 지수 정적 워치리스트입니다. 현재 22개 심볼(미국 4, 한국 2, 아시아 7, 유럽 5, 기타 2, 브라질 1, 싱가포르 1).
- `테마 ETF`: 별도 시장이 아니라 US 스캔 결과에서 파생 생성되는 사이트 페이지입니다. Dow 30과 동일한 구조입니다.
- `commodities`: 원자재 선물 정적 워치리스트입니다.

대표 유니버스는 시장과 별도로 `universe_memberships`에서 관리합니다. US 시장은 `nasdaq`(NASDAQ 전체), `nyse`(NYSE 전체), `amex`(AMEX 전체), `nasdaq100`, `sp500` 5개 universe를 사용하며 `--market us` 한 번으로 모두 갱신됩니다. 개별 universe 필터는 `--universe nasdaq100`, `--universe sp500` 등으로 사용합니다. 한국 시장은 `--market kospi --universe kospi100`, `--market kospi --universe kospi200`, `--market kosdaq --universe kosdaq150`처럼 필요할 때만 멤버십 필터를 겁니다. 과거 단일 `us` universe key는 폐기되었습니다.

## Main Entry Points

- `Search.py`: CLI 진입점입니다. `--market`, `--universe`, `--stage`, `--date`, `--workers`, `--limit`, `--setup-scheduler` 옵션을 처리합니다.
- `AGENTS.md`: Codex가 프로젝트 작업 시 우선 참고하는 지침 문서입니다. 코드 변경 시 함께 갱신해야 하는 주요 문서 관계도를 포함합니다.
- `docs/database_recommendation.md`: CSV에서 PostgreSQL로 전환하기 위한 권장 구조와 단계별 이전 계획입니다.
- `docs/database_schema_v1.sql`: PostgreSQL 스키마 초안 DDL입니다.
- `docs/database_table_guide.md`: DB 테이블별 역할과 주요 컬럼 설명서입니다.
- `market_scanner/storage/db.py`: PostgreSQL 스키마 적용, 기준 데이터 seed, CSV 스캔 결과 적재 유틸리티입니다.
- `market_scanner/config/markets.py`: 시장 정의, 메타데이터 로더, 유니버스 로더, quote URL 생성기를 관리합니다.
- `market_scanner/pipeline.py`: v2 단계 순서만 제어합니다. 실제 가격 수집, 지표 계산, 스크리닝, 렌더링 로직은 `collectors/`, `analysis/`, `reports/`, `storage/` 하위 모듈에 둡니다.
- `market_scanner/reports/site_builder.py`: DB의 최신 스캔/시장/섹터 스냅샷을 읽어 GitHub Pages용 `site/` 정적 사이트를 재생성합니다.
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
- 현재 동작: `Search.py --stage news`가 DB `scan_results`의 종합점수 상위 종목을 기준으로 yfinance 뉴스를 수집해 캐시를 만들고, 리포트는 캐시가 있으면 뉴스 항목을 표시합니다. 캐시가 없으면 수집 필요 안내를 표시합니다.
- 후보 데이터 소스: yfinance `Ticker.news`, Yahoo Finance RSS/검색, 유료 뉴스 API. 안정성과 사용 제한을 고려해 수집 단계를 분리하는 것이 안전합니다.

## Pipeline Flow

일반 실행:

```powershell
uv run python Search.py --market kospi
uv run python Search.py --market kospi --universe kospi100
uv run python Search.py --market kospi --universe kospi200
uv run python Search.py --market us --universe sp500
```

단계별 흐름:

1. `scan`: `market_scanner.pipeline`이 `collectors.prices.run_fetch` → `analysis.indicators.run_compute` → `analysis.screener.run_screen` 순서로 실행합니다. `--universe`를 지정하면 screener 단계에서 `universe_memberships`의 현재 편입 종목만 스캔합니다. universe가 다른 시장에 속하면 오류로 중단합니다. KOSPI/KOSDAQ/US는 FinanceDataReader OHLCV를 우선 사용하고, 실패 시 yfinance 히스토리로 fallback합니다. 가격 수집은 시장별 목표일 기준으로 이미 가격이 있는 종목을 SQL 단계에서 제외합니다. 기본 목표일은 한국 시장은 실행일, 비한국 시장은 KST 기준 전일이며 `--date`가 있으면 해당 날짜를 사용합니다. 가격 조회는 `--workers`로 병렬 처리하되 DB upsert는 메인 스레드에서 수행합니다. yfinance 조회 실패는 재시도하지 않고 실패 종목 로그만 남긴 뒤 다음 종목으로 진행합니다.
2. `analyze`: DB의 `daily_indicators`/`daily_prices`를 기반으로 screener를 다시 실행하고 Markdown을 재생성합니다.
3. `news`: DB의 최신 `scan_results` 상위 종목에서 yfinance 뉴스 항목을 수집해 `market_scanner/assets/news_cache.json`에 날짜/시장별로 저장합니다.
4. `render`: DB의 `scan_results`를 기반으로 Markdown/HTML 리포트를 렌더링하고 `generated_reports`에 산출물 메타데이터를 기록합니다.
5. `all`: `scan`, `analyze`, `render`를 순서대로 실행합니다. 뉴스 수집은 실행 시간과 외부 요청량 때문에 별도 opt-in 단계로 둡니다.

PostgreSQL 저장 흐름:

1. `docker compose up -d postgres`로 로컬 DB를 실행합니다.
2. `uv run python -m market_scanner.storage.db init`으로 `docs/database_schema_v1.sql`을 적용하고 시장/유니버스 기준 데이터를 seed합니다. 현재 코드에 없는 market/universe 기준 row는 삭제하지 않고 `is_active = false`로 비활성화합니다. 이 흐름은 `psycopg[binary]` 의존성을 사용합니다.
3. `uv run python -m market_scanner.storage.db refresh-master --reset`으로 기존 멤버십을 비우고 시장 유니버스 로더 기반 종목마스터와 멤버십을 다시 구성합니다. `--market kospi`는 KOSPI 전체만 갱신하고, 대표 유니버스는 `--market kospi --universe kospi100`, `--market kospi --universe kospi200`처럼 명시했을 때만 갱신합니다. `--reset`은 `universe_memberships`만 해당 범위에서 삭제 후 재생성하며, `instruments`, 가격, 지표, 스캔 결과, 뉴스, 리포트, `collection_runs` 로그는 보존합니다.
   `refresh-master`는 기존 현재 멤버십과 새 수집 목록을 비교해 previous/fetched/matched/mismatch, added/removed/rank_changed 샘플, 신규/upsert instrument 샘플을 출력하고 `collection_runs.params`에 저장합니다. 멤버십 목록과 순서가 완전히 같으면 `universe_memberships` 삭제/재삽입을 건너뛰고 instrument upsert만 수행합니다.
4. `Search.py --stage scan` 또는 v2 개별 모듈 실행으로 `daily_prices`, `daily_indicators`, `scan_results`를 갱신합니다.
5. `uv run python -m market_scanner.storage.db counts`로 핵심 테이블 적재 건수를 확인합니다.

`load-master`는 `market_scanner/assets/instruments.json` seed를 DB에 넣는 호환/복구용 명령으로 유지합니다. 신규 운영 기준은 `refresh-master`이며, 이 명령은 가격/지표를 수집하지 않고 `instruments`, `universe_memberships`, `collection_runs`만 갱신합니다.

멀티 컴퓨터 접속 운영:

- 로컬 Docker PostgreSQL은 `docker-compose.yml`의 `"5433:5432"` 포트 매핑으로 호스트 네트워크에 공개됩니다.
- 윈도우 PC를 DB 서버로 사용할 때 같은 LAN/Wi-Fi의 맥북은 `postgresql://searchmarket:searchmarket@<windows-ip>:5433/searchmarket`로 접속합니다.
- DBeaver는 Host에 `<windows-ip>`, Port에 `5433`, Database/User/Password에 `searchmarket`을 각각 입력합니다. `5433`을 Host 칸에 넣으면 `Unknown host 5433` 오류가 납니다.
- 윈도우 방화벽이 막는 경우 Private 네트워크 프로필에 TCP 5433 인바운드 허용 규칙을 추가합니다.
- Docker volume이나 `.postgres-data/`를 파일 동기화 서비스로 공유하지 않습니다. 외부 인터넷 접속은 포트포워딩보다 Tailscale/VPN 또는 관리형 PostgreSQL을 우선 검토합니다.

Docker Desktop을 사용할 수 없을 때는 로컬 Postgres 바이너리로 임시 DB를 띄울 수 있습니다. `.postgres-data/`는 `.gitignore`에 포함된 로컬 데이터 디렉터리입니다.

```bash
initdb -D .postgres-data --auth=trust --username=searchmarket
pg_ctl -D .postgres-data -o "-p 5433" -l .postgres-data/postgres.log start
createdb -h localhost -p 5433 -U searchmarket searchmarket
pg_ctl -D .postgres-data status
pg_ctl -D .postgres-data stop
```

출력 규칙:

- 스캔/스크리닝 결과의 원천은 PostgreSQL `daily_prices`, `daily_indicators`, `scan_results`, `market_snapshots`, `sector_snapshots`입니다.
- `render` 단계의 Markdown/HTML 산출물은 `site/reports/{scope}/{YYYYMMDD}/` 아래에 생성합니다.
- 산출물 메타데이터는 `generated_reports`에 기록합니다.

## Data Model And Scoring

주요 데이터 모델은 `market_scanner/models.py`에 있습니다.

- `ScanSettings`: 이동평균 기간, 근접 임계값, 히스토리 기간, worker 수, 출력 경로를 정의합니다.
- `MarketDefinition`: 시장별 label, currency, universe/metadata/URL 로더를 정의합니다.
- v2 스캔 결과는 DB 테이블(`daily_prices`, `daily_indicators`, `scan_results`)과 pandas DataFrame으로 전달합니다. 레거시 단일 레코드 내부 모델은 제거되었습니다.

주요 계산:

- RSI: `market_scanner/analysis/indicators.py::calc_rsi`
- MACD: `market_scanner/analysis/indicators.py::calc_macd`
- 볼린저 밴드: `market_scanner/analysis/indicators.py::calc_bollinger`
- 추세 점수: `market_scanner/analysis/indicators.py::calc_trend`
- 종합 점수: `market_scanner/analysis/screener.py::add_scores`

현재 종합 점수는 PRD v1.1의 복합 스코어링 구조를 반영해 차트 30%, 기술지표 25%, 재무 20%, 테마 15%, 수급 10%로 계산합니다. DB `scan_results`에는 `chart_score`, `technical_score`, `fundamental_score`, `theme_score`, `flow_score`, `composite_score`를 함께 저장합니다.

추가 수집/산출 컬럼:

- 가격 히스토리 기반: `macd`, `macd_signal`, `macd_hist`, `macd_state`, `bollinger_width_pct`, `bollinger_percent_b`
- 당일 캔들 기반: `open`, `high`, `low`, `close`, `prev_close`, `gap_pct`, `candle_body_pct`, `candle_range_pct`, `upper_shadow_pct`, `lower_shadow_pct`, `candle_type`
- yfinance `info` 기반: `price_to_book`, `return_on_equity`, `revenue_growth`, `market_cap`

추세 점수는 `calc_trend`에서 0~5점으로 계산합니다. 기준은 현재가가 단기 MA 위에 있는지, 단기 MA가 중기/장기 MA보다 위인지, 단기/중기 MA의 20거래일 전 대비 기울기가 상승인지입니다.

## Site Build Flow

GitHub Pages 배포는 `uv run python -m market_scanner.reports.site_builder`로 `site/` 폴더를 재생성합니다. 로컬 실행에서는 빌드 후 `site/index.html`을 기본 브라우저로 자동으로 열고, CI/GitHub Actions에서는 자동 열기를 건너뜁니다. 로컬에서도 `--no-open`을 붙이면 브라우저를 열지 않습니다.

사이트 생성 방식:

- `market_snapshots`, `sector_snapshots`, `scan_results`의 최신 trade_date를 기준으로 사이트 페이지를 생성합니다.
- Pages 상세페이지는 DB의 `scan_results`를 현재 템플릿으로 다시 렌더링합니다. 사이트 페이지의 템플릿 최신화 기준은 DB 재렌더링입니다.
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

현재 로컬에서는 Windows의 `python`과 macOS의 `python3` 사용 방식이 다를 수 있습니다. 개발 검증은 `uv run python`으로 통일해 현재 프로젝트의 `.venv`를 사용합니다.

```powershell
uv run python --version
uv run python -m compileall Search.py market_scanner
uv run python Search.py --help
```

네트워크 의존성이 있는 명령:

- `scan` 단계는 yfinance, Wikipedia, FinanceDataReader, Naver Finance, Investing 검색 요청을 사용할 수 있습니다. KOSPI/KOSDAQ/US OHLCV는 FinanceDataReader를 우선 사용하고 실패 시 yfinance로 fallback합니다.
- `news` 단계는 yfinance `Ticker.news` 요청을 사용하며, `--news-symbols`, `--news-items`, `--news-workers`로 수집 범위를 조절합니다.
- 로컬 sandbox나 네트워크 상태에 따라 재현성이 달라질 수 있습니다.

## Market Membership Caches

US 시장 universe 심볼은 FinanceDataReader `StockListing(exchange)`를 primary source로 사용합니다. FDR 심볼이 `ABR PR D`처럼 preferred share 패턴(`... PR ...`)이면 refresh-master 입력 단계에서 제외합니다.

| Universe | FDR 소스 | Fallback |
|----------|----------|----------|
| `nasdaq` | `StockListing("NASDAQ")` | 없음 (빈 목록 반환) |
| `nyse` | `StockListing("NYSE")` | 없음 (빈 목록 반환) |
| `amex` | `StockListing("AMEX")` | 없음 (빈 목록 반환) |
| `nasdaq100` | `StockListing("NASDAQ100")` | 없음 (빈 목록 반환) |
| `sp500` | `StockListing("SP500")` | Wikipedia S&P 500 페이지 스크래핑 |

KOSPI/KOSDAQ은 FDR `StockListing("KOSPI"|"KOSDAQ")`를 사용하며, 실패 시 Naver Finance 시가총액 페이지로 fallback합니다. 정적 JSON fallback(`kospi_static_meta.json`, `kosdaq_static_meta.json`)은 삭제되었습니다.

현재 ETF 필터링 없이 전체 심볼을 받습니다. `instruments.asset_type`으로 분류(`etf`, `common_stock` 등)되어 저장되며, 향후 `universe_definitions.default_asset_type_filter`로 스캔 시 필터링 예정입니다.

글로벌 지수/원자재는 자동 발견 API가 없으므로 `market_scanner/assets/` JSON이 심볼 정의 원본입니다. DB는 `load-master` 실행 시 JSON을 반영합니다. 테마 ETF는 `markets.py`의 `_THEME_PROXY_SYMBOLS` 상수로 관리하며 별도 JSON 없이 US 스캔 결과에서 파생됩니다.

## Current Repository State Notes

2026-04-28 확인 내용은 v1 산출물 검증 기록입니다. v2에서는 PostgreSQL `scan_results`와 `site/` 산출물을 기준으로 검증합니다.
- 상세페이지 UX 개선: KOSPI/KOSDAQ 티커 링크도 NASDAQ 100과 같은 Investing 상세 URL 캐시를 우선 사용합니다. Sector Heatmap은 섹터 평균 등락률 기준으로 강세가 앞쪽, 약세가 뒤쪽으로 정렬됩니다. MA Distance vs RSI에는 지표 설명과 한줄 해석을 추가했고 scatter point hit radius를 키웠습니다.
- 상세페이지 링크 개선: 모든 시장의 Investing 링크는 한국 도메인으로 출력합니다. US/글로벌/테마/원자재는 상세 URL 캐시를 우선 사용하고, KOSPI/KOSDAQ은 무네트워크 검색 URL을 사용합니다.
- 상세페이지 정렬 개선: 종목 리스트의 추세 컬럼은 문자열이 아니라 추세 점수 기준으로 정렬하며, 첫 클릭 시 강한 추세가 먼저 보입니다.
- 스캔 데이터 컬럼 추가: `change_pct`는 현재 종가와 전일 종가 기준 등락률입니다. 상세페이지 종목 리스트의 `등락률` 컬럼과 섹터별 상승률 Heatmap에 사용합니다.

## Metadata Fix Notes

- 2026-04-28: US 결과 파일을 NASDAQ 100/S&P 500 단위로 생성할 수 있게 분리했습니다. 2026-05-01 이후 권장 CLI는 `--market us --universe nasdaq100`, `--market us --universe sp500`입니다.
- 2026-04-28: `market_scanner/assets/instruments.json`을 공통 종목 마스터 seed로 추가했습니다. 2026-05-01부터 모든 시장의 `metadata_loader`는 PostgreSQL `instruments` 테이블을 먼저 읽고, DB가 비어 있거나 연결되지 않을 때만 이 JSON과 기존 시장별 `*_static_meta.json`을 fallback으로 사용합니다. 스캔 단계는 더 이상 `instruments.json`을 자동 갱신하지 않습니다.
- 2026-04-28: KOSPI/KOSDAQ 스캔에서 yfinance `Ticker.info`를 실제 조회한 티커 객체에서 읽도록 수정했습니다. 렌더링 단계도 정적 메타데이터와 FinanceDataReader 한국 종목명으로 placeholder 이름/섹터를 보정하므로, 기존 CSV에 `047040.KS`/`Unknown`처럼 저장된 값도 사이트 재생성 시 가능한 범위에서 정상 종목명/섹터로 표시됩니다. 한국 시장 화면의 종목명은 한글 표시를 우선하며, 한글명을 확보하지 못한 경우 영어 회사명 대신 종목코드를 표시합니다.
- 2026-04-30: KOSPI/KOSDAQ 가격 히스토리 수집은 FinanceDataReader를 먼저 사용합니다. FDR 조회 실패 또는 히스토리 부족 시 기존 yfinance 경로로 fallback합니다. FDR/pykrx listing 엔드포인트가 실패하는 환경에서는 네이버 시가총액 페이지를 파싱해 시장 전체 유니버스를 보강합니다.
- 2026-05-01: 종목마스터 운영 기준을 DB-only 방향으로 전환했습니다. `refresh-master`가 시장 전체 종목을 `instruments`에 저장하고, 대표 지수/그룹은 `universe_memberships` 멤버십으로 관리합니다. 스캔 기본값은 시장 전체이고, 필요한 경우 `--universe`로 필터링합니다.
- 2026-05-03: US market universe 구조를 전면 개편했습니다. 기존 단일 `us` universe_key를 폐기하고 `nasdaq`(NASDAQ 전체), `nyse`(NYSE 전체), `amex`(AMEX 전체), `nasdaq100`, `sp500` 5개로 분리했습니다. 심볼 소스를 NASDAQ Trader txt 파싱에서 FinanceDataReader `StockListing()`으로 전환했습니다. `--market us` 한 번으로 5개 universe가 모두 갱신됩니다(`_MARKET_UNIVERSE_EXPANSION`). `nasdaq100`/`sp500` universe도 정적 JSON/Wikipedia에서 FDR로 전환하고 기존 방식은 fallback으로 유지합니다. US 메타데이터 로더를 `_us_metadata()`(DB first → FDR NASDAQ/NYSE → nasdaq100 static JSON)로 교체했습니다.
- 2026-05-03: JSON fallback 코드 정리. `kospi_static_meta.json`, `kosdaq_static_meta.json`, `sp500_members_cache.json` 삭제. `_kospi_static_meta()`, `_kosdaq_static_meta()`, SP500 캐시/수동 오버라이드 6개 함수, `_merge_static_with_live()` 제거. `_kospi_universe()`, `_kosdaq_universe()`는 FDR/Naver 결과를 직접 반환. `_kospi200_universe()`, `_kospi100_universe()`, `_kosdaq150_universe()`는 FDR 단독 호출로 단순화. `_kospi_metadata()`, `_kosdaq_metadata()` DB 미스 fallback도 JSON 없이 Naver+FDR만 사용.
- 2026-05-03: 글로벌 지수 워치리스트 확장. 15개 → 22개. 추가: `^KQ11`(코스닥), `^RUT`(러셀 2000), `^BVSP`(보베스파), `^NSEI`(니프티 50), `000300.SS`(CSI 300), `^STI`(싱가포르), `^NDX`(나스닥 100). `_INVESTING_SPECIAL_QUERIES`와 `_display_index()` 처리 추가.
- 2026-05-03: `theme-proxies` 시장 폐기. `theme_proxies_meta.json` 삭제, `MARKETS["theme-proxies"]` 제거, CLI/워크플로우/DB 분류 코드 제거. 테마 ETF 페이지는 Dow 30과 동일하게 US 스캔 결과에서 파생(`_build_theme_page_from_us()`). 대상 심볼은 `_THEME_PROXY_SYMBOLS` 상수로 관리. 13개 ETF의 `instruments.json` market_key를 `"theme-proxies"` → `"us"`로 변경.

## 2026-04-29 Pages Automation Note

- 스캔 workflow가 `GITHUB_TOKEN`으로 결과를 커밋/푸시하면 GitHub Actions의 재귀 방지 정책 때문에 `push` 기반 Pages workflow가 자동 실행되지 않을 수 있습니다. `deploy-pages.yml`에 `workflow_run` 트리거를 추가해 US, overview, KOSPI, KOSDAQ 스캔 성공 후 Pages 빌드/배포가 이어지도록 했습니다.

## 2026-04-29 Detail Page UI Note

- 상세페이지 상단 전환 버튼은 노란색 테두리로 강조하고, Signal Strip의 영문 `Avg RSI`, `Bull Breadth`, `Fear` 표기를 한글화했습니다. MA60/120/240 근접 수는 하나의 큰 박스 안에 묶고 복수 MA 항목은 제거했습니다.
- 기존 우측 `Fear & Volatility` 패널은 제거하고 동일한 공포지수 해석 UI를 상단 Signal Strip으로 이동했습니다. 상단에는 평균 등락률과 강세/보합/약세 섹터 수를 기반으로 현재 상세페이지 시장 상태도 표시합니다. Sector Heatmap 제목 옆에는 전체 상승/하락 종목 수를 함께 표시합니다. 종목 리스트 내부 탭의 `분석 리포트` 항목은 제거하고 상단 전환 버튼에서만 접근하도록 정리했습니다.
- 상단 Signal Strip에는 근접 종목 비중, 리딩/약세 섹터, RSI 온도 분포, 추세/섹터 breadth 보조 정보를 추가했습니다.

## 2026-04-29 KOSPI200 Metadata Note

- KOSPI static metadata and instruments records were realigned to 200 KOSPI 200 components. When the static KOSPI metadata has at least 200 symbols, `_kospi_universe()` treats it as authoritative and does not append the FinanceDataReader market-cap fallback.

## Known Risks And Improvement Areas

- S&P 500 유니버스 갱신은 FDR 실패 시 Wikipedia 스크래핑으로 fallback합니다. 무료 소스 기반이므로 공식 라이선스 데이터 피드만큼 보장되지는 않습니다.
- `site_builder.py`가 `site/`를 통째로 삭제 후 재생성합니다. 사이트 빌드 중 수동으로 넣은 파일은 유지되지 않습니다.
- `reports/site_builder.py`는 DB의 universe key 기준으로 페이지를 생성합니다.
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
- 한국 전체 유니버스: 기본 스캔은 `kospi`/`kosdaq` 시장 전체 활성 종목입니다. `kospi100`, `kospi200`, `kosdaq150` 같은 대표 그룹은 `--universe` 필터로 실행합니다.
- 미국 전체 유니버스: `instruments.market_key = 'us'`로 전체 미국 종목을 관리하고, `universe_memberships`에서 `nasdaq`/`nyse`/`amex`(거래소 전체)와 `nasdaq100`/`sp500`(지수) 5개 universe로 구분합니다. `--market us` 한 번으로 5개 동시 갱신됩니다. 심볼 소스는 FinanceDataReader입니다.
- Dow 30 파생 페이지: 별도 스캔 없이 US 스캔 결과에서 Dow 30 구성 종목을 필터링해 `site/dow30/index.html`을 생성합니다.
- v2 구조 정리: 루트 산출물 폴더를 제거하고 DB와 `site/` 산출물을 기준으로 전환했습니다.
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
