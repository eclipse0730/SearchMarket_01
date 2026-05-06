# Stock MA Scanner

미국 주식, KOSPI, KOSDAQ, 글로벌 지수, 테마 ETF, 원자재를 대상으로 5/20/60/120/240일 이동평균선, 기간 수익률, ATR/변동성, 기술/재무/수급 점수를 계산하고 PostgreSQL 기반 Markdown/HTML 리포트와 GitHub Pages 대시보드를 생성합니다.

## 설치

아래 예시는 Windows와 macOS 터미널에서 같은 형태로 사용할 수 있습니다. `uv`는 사전에 설치되어 있어야 하며, 설치 이후 실행 명령은 `uv run python`이 현재 프로젝트의 `.venv`를 사용합니다.

```bash
uv venv
uv pip install -r requirements.txt
```

## 권장 실행 흐름

PostgreSQL의 `instruments`가 종목마스터의 우선 원천입니다. 먼저 DB를 띄우고 종목마스터와 유니버스 멤버십을 갱신한 뒤 스캔합니다.

```bash
docker compose up -d postgres
uv run python -m market_scanner.storage.db init
uv run python -m market_scanner.storage.db refresh-master --reset
uv run python Search.py --market kospi --stage scan
uv run python -m market_scanner.storage.db counts
```

`init`은 DB 스키마와 기준 데이터를 준비하는 단계입니다. 새 DB를 처음 만들었을 때, Docker volume을 새로 만들었을 때, 스키마나 시장/유니버스 기준 키가 바뀐 뒤에는 실행해야 합니다. 이미 초기화된 DB에서 일반 스캔만 반복할 때는 매번 실행할 필요가 없습니다. 현재 코드에 없는 market/universe 기준 row는 삭제하지 않고 `is_active = false`로 비활성화합니다.
`refresh-master`는 가격/지표를 수집하지 않고 시장 유니버스 로더로 종목 목록을 받아 `instruments`, `universe_memberships`, `collection_runs`만 갱신합니다. us·kospi·kosdaq는 FDR에서, global-indices·commodities는 JSON 파일에서 심볼 목록을 읽습니다. `--market us`는 nasdaq·nyse·amex·nasdaq100·sp500 5개, `--market kospi`는 kospi·kospi100·kospi200 3개, `--market kosdaq`는 kosdaq·kosdaq150 2개 universe를 한 번에 순차 갱신합니다. 실행 시 기존 멤버십과 새 목록의 일치/불일치 수, 추가/삭제/순위 변경 샘플, 신규/upsert instrument 샘플을 로그로 출력하고 `collection_runs.params`에도 저장합니다. 멤버십 목록과 순서가 같으면 `universe_memberships` 재작성은 건너뜁니다. `--reset`은 `universe_memberships`만 해당 범위에서 삭제 후 재생성합니다. `instruments`, 가격, 지표, 스캔 결과, 뉴스, 리포트, 실행 로그는 보존합니다.
`Search.py --stage scan`은 v2 DB 파이프라인을 실행해 `daily_prices`, `daily_indicators`, `scan_results`를 갱신합니다. `load-master`는 `market_scanner/assets/instruments.json`을 DB에 일괄 반영하는 명령으로, DB 복구나 seed 초기화 용도로 사용합니다.

## 종목 마스터 갱신
스캔 전에 `refresh-master`로 각 시장의 종목 목록을 최신 상태로 갱신합니다. 가격·지표 수집 없이 `instruments`, `universe_memberships`, `collection_runs`만 업데이트합니다. `--reset`을 붙이면 `universe_memberships`를 해당 범위에서 삭제 후 재생성합니다(instruments, 가격, 지표, 스캔 결과는 보존).

```bash
uv run python -m market_scanner.storage.db refresh-master --market us              # FDR: --universe nasdaq·nyse·amex·nasdaq100·sp500
uv run python -m market_scanner.storage.db refresh-master --market kospi           # FDR: --universe kospi·kospi100·kospi200
uv run python -m market_scanner.storage.db refresh-master --market kosdaq          # FDR: --universe kosdaq·kosdaq150
uv run python -m market_scanner.storage.db refresh-master --market global-indices  # JSON: global_indices_meta.json
uv run python -m market_scanner.storage.db refresh-master --market commodities     # JSON: commodities_meta.json
uv run python -m market_scanner.storage.db counts
```

## 종목 이름·업종 보강 (한국 시장)

FDR/Naver 마켓서머리에서 이름이 누락된 종목(우선주·ETF 등)이나 sector가 `Unknown`인 종목을 Naver Finance 개별 종목 페이지에서 보강합니다. `refresh-master` 이후 한 번 실행하면 됩니다.

```bash
# 기본: name_local이 비어 있거나 sector='Unknown'인 종목만 업데이트
uv run python -m market_scanner.storage.db fetch-name --market kospi
uv run python -m market_scanner.storage.db fetch-name --market kosdaq

# 전체 종목 재조회 (초기 1회 or 데이터 품질 리셋)
uv run python -m market_scanner.storage.db fetch-name --market kospi --all
uv run python -m market_scanner.storage.db fetch-name --market kosdaq --all

# 테스트: 10종목만 먼저 확인
uv run python -m market_scanner.storage.db fetch-name --market kospi --limit 10
```

- 종목당 Naver Finance 1회 요청, 기본 0.3초 간격 (`--delay` 조정 가능)
- 업데이트 항목: `name_local`, `sector`, `description` / `name_en`은 placeholder인 경우만 교체

## v2 파이프라인 (DB-first)

가격 수집 → 지표 계산 → 스크리닝 → 렌더링 4단계로 분리됩니다. 각 단계는 독립적으로 실행하거나 순서대로 이어서 실행합니다.

```bash
# 1. 일일 OHLCV 수집 (증분 — 최신 목표일이 없는 종목만 조회)
uv run python -m market_scanner.collectors.prices fetch --market kospi
uv run python -m market_scanner.collectors.prices fetch --market kosdaq
uv run python -m market_scanner.collectors.prices fetch --market us
uv run python -m market_scanner.collectors.prices fetch --market us --workers 8

# prices fetch는 시장별 목표일 기준으로 이미 가격이 있는 종목을 SQL 단계에서 제외합니다.
# 기본 목표일: KOSPI/KOSDAQ은 실행일, 비한국 시장은 KST 기준 전일.
# --date YYYYMMDD를 주면 해당 날짜를 명시적으로 목표일로 사용합니다.
# --workers N으로 가격 조회 병렬도를 조절합니다. 기본값은 8입니다.

# 2. 기술적 지표 계산 (daily_prices → daily_indicators)
uv run python -m market_scanner.analysis.indicators compute --market kospi

# 3. 스코어링·랭킹·집계 (daily_indicators → scan_results / market_snapshots)
uv run python -m market_scanner.analysis.screener run --market kospi
uv run python -m market_scanner.analysis.screener run --market kospi --universe kospi200

# 4. 리포트 렌더링 (scan_results → site/reports/ + generated_reports)
uv run python -m market_scanner.reports.render build --market kospi
```

### 백필 (신규 종목 or 1년치 일괄)

```bash
# refresh-master로 새 종목이 들어온 뒤
uv run python -m market_scanner.collectors.prices backfill --market kospi --new-only
# 전체 1년치 재적재
uv run python -m market_scanner.collectors.prices backfill --market kospi --years 1
# 2년치 US 가격을 병렬 백필
uv run python -m market_scanner.collectors.prices backfill --market us --years 2 --workers 8
# 실패 종목 재시도
uv run python -m market_scanner.collectors.prices retry --market kospi
```

### 펀더멘탈 수집 (주 1회)

```bash
uv run python -m market_scanner.collectors.fundamentals fetch --market us
uv run python -m market_scanner.collectors.fundamentals fetch --market kospi
```

### 스케줄러 (docker-compose cron 사이드카)

```bash
docker compose --profile scheduler up -d
# 로그 확인
docker compose logs -f scheduler
```

---

## 스캔 (Search.py v2 오케스트레이션)

`Search.py`는 CLI 진입점이고, 실제 실행 순서는 `market_scanner.pipeline`이 제어합니다. 기본 스캔은 PostgreSQL `instruments`에서 해당 시장의 전체 활성 종목을 읽어 `collectors.prices → analysis.indicators → analysis.screener → reports.render` 순서로 실행합니다.

```bash
uv run python Search.py --market us
uv run python Search.py --market kospi
uv run python Search.py --market kosdaq
uv run python Search.py --market global-indices
uv run python Search.py --market commodities
```

필요할 때만 `--universe`로 멤버십 필터를 겁니다. universe가 다른 시장에 속하면 오류로 중단합니다.

```bash
uv run python Search.py --market us     --universe nasdaq
uv run python Search.py --market us     --universe nyse
uv run python Search.py --market us     --universe amex
uv run python Search.py --market us     --universe nasdaq100
uv run python Search.py --market us     --universe sp500
uv run python Search.py --market kospi  --universe kospi100
uv run python Search.py --market kospi  --universe kospi200
uv run python Search.py --market kosdaq --universe kosdaq150
```

단계별 실행:

```bash
uv run python Search.py --market kospi --stage scan      # 가격 수집 + 지표 계산 + 스크리닝
uv run python Search.py --market kospi --stage analyze   # 기존 DB 지표로 스크리닝/Markdown 재생성
uv run python Search.py --market us --universe sp500 --stage news
uv run python Search.py --market kospi --stage render    # scan_results 기반 리포트 렌더링
```

유용한 옵션:

```bash
uv run python Search.py --market kospi --workers 8
uv run python Search.py --market kospi --date 20260430
uv run python Search.py --market kospi --limit 5
uv run python Search.py --market us --universe sp500 --stage news --news-symbols 80 --news-items 2
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
- KOSPI/KOSDAQ/US 가격 히스토리는 FinanceDataReader를 우선 사용하고, 실패하거나 히스토리가 부족하면 yfinance로 fallback합니다.
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
