# Stock MA Scanner

미국 주식, KOSPI, KOSDAQ, 글로벌 지수, 테마 ETF, 원자재를 대상으로 5/20/60/120/240일 이동평균선, 기간 수익률, ATR/변동성, 기술/재무/테마/모멘텀 점수를 계산하고 PostgreSQL 기반 Markdown/HTML 리포트와 GitHub Pages 대시보드를 생성합니다.

## 설치

아래 예시는 Windows와 macOS 터미널에서 같은 형태로 사용할 수 있습니다. `uv`는 사전에 설치되어 있어야 하며, 설치 이후 실행 명령은 `uv run python`이 현재 프로젝트의 `.venv`를 사용합니다.
```bash
uv venv
uv pip install -r requirements.txt
```

## 기본 실행 흐름

Search60의 기본 운영 단위는 `Search.py`가 아니라 아래 5단계 DB 파이프라인입니다. 각 단계는 PostgreSQL에 결과를 저장하고, 다음 단계는 앞 단계가 저장한 테이블을 읽습니다.
```bash
docker compose up -d postgres
uv run python -m market_scanner.storage.db init
```

`init`은 `docs/database_schema_v1.sql`을 적용하고 시장/유니버스 기준 데이터를 준비합니다. 새 DB를 만들었거나 스키마가 바뀐 뒤에 실행합니다. 이미 초기화된 DB에서 매일 반복 실행할 필요는 없습니다.

## 1단계: 종목 수집

`refresh-master`는 가격이나 지표를 수집하지 않습니다. 시장별 종목 목록을 받아 `instruments`, `universe_memberships`, `collection_runs`만 갱신합니다.
```bash
uv run python -m market_scanner.storage.db refresh-master --market us             --universe sp500
uv run python -m market_scanner.storage.db refresh-master --market kospi          --universe kospi200
uv run python -m market_scanner.storage.db refresh-master --market kosdaq         --universe kosdaq150
uv run python -m market_scanner.storage.db refresh-master --market global-indices
uv run python -m market_scanner.storage.db refresh-master --market commodities
```

데이터 소스:
- `us`, `kospi`, `kosdaq`: FinanceDataReader를 우선 사용합니다. 한국 시장은 필요 시 Naver Finance 보강 로직을 사용합니다.
- `global-indices`, `commodities`: JSON 메타 파일을 원본으로 사용합니다.
- 한국 종목명/업종 보강: `uv run python -m market_scanner.storage.db fetch-name --market kospi`

`--reset`은 해당 범위의 `universe_memberships`만 삭제 후 재생성합니다. `instruments`, 가격, 지표, 스캔 결과, 뉴스, 리포트, 실행 로그는 보존합니다.

## 2단계: 가격 수집

일일 증분 수집은 목표일 가격이 없는 종목만 조회합니다.
```bash
uv run python -m market_scanner.collectors.prices fetch --market us
uv run python -m market_scanner.collectors.prices fetch --market kospi
uv run python -m market_scanner.collectors.prices fetch --market kosdaq
```

날짜와 병렬도를 지정할 수 있습니다.
```bash
uv run python -m market_scanner.collectors.prices fetch --market us --date 20260505 --workers 8
```

대량 적재나 신규 종목 백필은 `backfill`을 사용합니다.
```bash
uv run python -m market_scanner.collectors.prices backfill --market us    --years 2 --workers 8
uv run python -m market_scanner.collectors.prices backfill --market kospi --new-only
uv run python -m market_scanner.collectors.prices retry    --market us
```

## 3단계: 지표 계산

`daily_prices`를 읽어 `daily_indicators`를 계산합니다.
```bash
uv run python -m market_scanner.analysis.indicators compute --market us
uv run python -m market_scanner.analysis.indicators compute --market kospi
uv run python -m market_scanner.analysis.indicators compute --market kosdaq
uv run python -m market_scanner.analysis.indicators compute --market us     --date 20260505
```

## 4단계: 스코어링

`daily_indicators`와 `daily_prices`를 읽어 점수, 순위, 시장/섹터 스냅샷을 저장합니다.
`--date`를 생략하면 해당 시장/유니버스의 최신 `daily_indicators.trade_date`를 자동으로 사용합니다.
```bash
uv run python -m market_scanner.analysis.screener run --market us
uv run python -m market_scanner.analysis.screener run --market kospi
uv run python -m market_scanner.analysis.screener run --market kosdaq
uv run python -m market_scanner.analysis.screener run --market us     --universe sp500
uv run python -m market_scanner.analysis.screener run --market kospi  --universe kospi200
```

## 5단계: 결과 도출

`scan_results`를 읽어 Markdown/HTML 리포트를 생성하고 `generated_reports`에 기록합니다.
```bash
uv run python -m market_scanner.reports.render build --market us
uv run python -m market_scanner.reports.render build --market kospi
uv run python -m market_scanner.reports.render build --market kosdaq
uv run python -m market_scanner.reports.render build --market us     --universe sp500
uv run python -m market_scanner.reports.render build --market kospi  --universe kospi200
```

전체 사이트 대시보드는 별도 빌드 명령으로 생성합니다.
```bash
uv run python -m market_scanner.reports.site_builder --no-open
```

## 날짜 기준 예시

US 시장은 KST 기준으로 실행하면 오늘이 아니라 전일 거래일 데이터가 최신일 수 있습니다. 4단계 스코어링은 날짜를 생략하면 최신 지표일을 자동 선택합니다. 2, 3, 5단계 날짜를 명확히 맞추고 싶을 때는 같은 `--date`를 명시합니다.
```bash
uv run python -m market_scanner.collectors.prices fetch     --market us --date 20260505
uv run python -m market_scanner.analysis.indicators compute --market us --date 20260505
uv run python -m market_scanner.analysis.screener run       --market us --date 20260505
uv run python -m market_scanner.reports.render build        --market us --date 20260505
```

## 보조 명령

핵심 테이블 적재 건수 확인:
```bash
uv run python -m market_scanner.storage.db counts
```

펀더멘탈 수집:
```bash
uv run python -m market_scanner.collectors.fundamentals fetch --market us
uv run python -m market_scanner.collectors.fundamentals fetch --market kospi
uv run python -m market_scanner.collectors.fundamentals fetch --market kosdaq --workers 8 --limit 100
uv run python -m market_scanner.collectors.fundamentals fetch --market kospi --source naver --limit 10
```

기본 `--source auto`는 US는 Yahoo Finance, KOSPI/KOSDAQ은 Naver Finance -> FinanceDataReader -> Yahoo Finance 순서로 값을 채웁니다. `--workers`는 기본 2이며 US/Yahoo 경로는 최대 4, 한국 Naver/FDR 경로는 최대 8로 제한합니다.

자세한 옵션과 동작은 `docs/fundamentals.manual.md`를 참고합니다.

뉴스 캐시 수집은 현재 `Search.py --stage news`를 사용합니다.
```bash
uv run python Search.py --market us --universe sp500 --stage news
```

## Search.py 단축 실행

`Search.py`는 2~5단계를 한 번에 묶어 실행하는 호환용 단축 CLI입니다. 운영 흐름을 명확히 보고 싶을 때는 위의 모듈별 5단계 명령을 권장합니다.
```bash
uv run python Search.py --market us
uv run python Search.py --market kospi
uv run python Search.py --market kosdaq
```

단계별 단축 실행도 가능하지만, 실제 운영 기준은 모듈별 명령입니다.
```bash
uv run python Search.py --market us --stage scan
uv run python Search.py --market us --stage render
```

## 출력

스캔 결과의 원천은 PostgreSQL입니다. `render` 단계는 DB의 `scan_results`를 읽어 `site/reports/{scope}/{YYYYMMDD}/` 아래에 Markdown/HTML을 생성하고 `generated_reports`에 산출물 메타데이터를 기록합니다. GitHub Pages 사이트는 `site/` 아래에 생성됩니다.

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

같은 LAN/Wi-Fi의 다른 컴퓨터에서 윈도우 Docker PostgreSQL에 접속하려면 윈도우 PC IP를 Host로 사용합니다.

```powershell
ipconfig
```

예를 들어 윈도우 PC IP가 `192.168.0.23`이면:

```text
DATABASE_URL=postgresql://searchmarket:searchmarket@192.168.0.23:5433/searchmarket
```

방화벽이 막으면 관리자 권한 터미널에서 Private 네트워크용 인바운드 규칙을 추가합니다.

```powershell
netsh advfirewall firewall add rule name="SearchMarket PostgreSQL 5433" dir=in action=allow protocol=TCP localport=5433 profile=private
```

DB 파일이나 Docker volume을 iCloud/Dropbox 같은 파일 동기화 도구로 공유하지 마세요. 여러 컴퓨터가 같은 DB를 보려면 한쪽 PostgreSQL 서버에 네트워크로 접속합니다. 외부 인터넷 접속은 포트포워딩보다 Tailscale/VPN 또는 관리형 PostgreSQL을 권장합니다.

Docker Desktop을 쓰지 않고 로컬 Postgres 바이너리로 임시 DB를 띄울 수도 있습니다.

```powershell
initdb -D .postgres-data --auth=trust --username=searchmarket
pg_ctl -D .postgres-data -o "-p 5433" -l .postgres-data/postgres.log start
createdb -h localhost -p 5433 -U searchmarket searchmarket
pg_ctl -D .postgres-data status
pg_ctl -D .postgres-data stop
```

`.postgres-data/`는 로컬 DB 데이터 디렉터리이며 Git 추적 대상이 아닙니다.

## 사이트 대시보드

```bash
uv run python -m market_scanner.reports.site_builder --no-open
```

`site/`에는 GitHub Pages용 정적 대시보드가 생성됩니다. 자동 열기를 원하면 `--no-open`을 빼고 실행합니다.

대시보드는 DB의 `scan_results`, `market_snapshots`, `sector_snapshots` 최신 데이터를 기반으로 종합 시장 점수, 시장 체력, 매크로 리스크, 섹터/테마 히트맵, 오늘의 핵심 후보, 시장별 스냅샷, 섹터 리더십, 뉴스 브리핑을 표시합니다.

## 데이터 정책

- `instruments`: 종목마스터의 우선 원천입니다.
- `universe_memberships`: `nasdaq`, `nyse`, `amex`(거래소 전체), `nasdaq100`, `sp500`(지수), `kospi100`, `kospi200`, `kosdaq150` 같은 분석/필터 단위 멤버십입니다. US는 `--market us` 한 번으로 5개 universe가 동시 갱신됩니다.
- `market_scanner/assets/instruments.json`: DB가 비어 있거나 연결되지 않을 때 쓰는 seed/fallback입니다. 스캔 실행은 이 JSON을 자동 갱신하지 않습니다.
- `market_scanner/assets/global_indices_meta.json`, `commodities_meta.json`: 글로벌 지수·원자재는 FDR 자동 발견이 불가능하므로 JSON이 심볼 정의 원본입니다. 새 심볼 추가 시 JSON 편집 후 `refresh-master --market global-indices` 또는 `--market commodities`로 DB에 반영합니다. 현재 글로벌 지수는 22개입니다.
- 테마 ETF는 별도 스캔 없이 US 스캔 결과에서 파생됩니다. 대상 심볼은 `markets.py`의 `_THEME_PROXY_SYMBOLS` 상수로 관리합니다.
- 한국 시장 유니버스는 FinanceDataReader를 우선 사용하고, 실패 시 Naver Finance로 fallback합니다. 정적 JSON fallback(`kospi_static_meta.json`, `kosdaq_static_meta.json`)은 제거되었습니다.
- KOSPI/KOSDAQ 가격 히스토리는 timeout이 적용된 Naver 일봉 조회를 우선 사용하고, 실패하거나 히스토리가 부족하면 yfinance로 fallback합니다. US 가격 히스토리는 Yahoo 계열 조회를 사용합니다.
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
| `daily-scan-overview.yml` | KST 08:20 | 글로벌 지수·테마 ETF·원자재 |
| `daily-scan-kospi.yml` | KST 16:05 | KOSPI |
| `daily-scan-kosdaq.yml` | KST 16:35 | KOSDAQ |
| `deploy-pages.yml` | 스캔 성공 후 자동, 또는 수동 실행 | GitHub Pages 사이트 빌드·배포 |
