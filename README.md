# Stock MA Scanner

미국 주식, KOSPI, KOSDAQ, 글로벌 지수, 테마 ETF, 원자재를 대상으로 60/120/240일 이동평균선 근접 여부와 기술/재무/수급 점수를 계산하고 CSV, Markdown, HTML 리포트와 GitHub Pages 대시보드를 생성합니다.

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
uv run python -m market_scanner.db init
uv run python -m market_scanner.db refresh-master --reset
uv run python Search.py --market kospi --stage scan --force
uv run python -m market_scanner.db load-csv --market kospi --date YYYYMMDD
uv run python -m market_scanner.db counts
```

`init`은 DB 스키마와 기준 데이터를 준비하는 단계입니다. 새 DB를 처음 만들었을 때, Docker volume을 새로 만들었을 때, 스키마나 시장/유니버스 기준 키가 바뀐 뒤에는 실행해야 합니다. 이미 초기화된 DB에서 일반 스캔만 반복할 때는 매번 실행할 필요가 없습니다. 현재 코드에 없는 market/universe 기준 row는 삭제하지 않고 `is_active = false`로 비활성화합니다.
`refresh-master`는 가격/지표를 수집하지 않고 시장 유니버스 로더로 종목 목록을 받아 `instruments`, `universe_memberships`, `collection_runs`만 갱신합니다. us·kospi·kosdaq는 FDR에서, global-indices·commodities는 JSON 파일에서 심볼 목록을 읽습니다. `--market us`는 nasdaq·nyse·amex·nasdaq100·sp500 5개, `--market kospi`는 kospi·kospi100·kospi200 3개, `--market kosdaq`는 kosdaq·kosdaq150 2개 universe를 한 번에 순차 갱신합니다. 실행 시 기존 멤버십과 새 목록의 일치/불일치 수, 추가/삭제/순위 변경 샘플, 신규/upsert instrument 샘플을 로그로 출력하고 `collection_runs.params`에도 저장합니다. 멤버십 목록과 순서가 같으면 `universe_memberships` 재작성은 건너뜁니다. `--reset`은 `universe_memberships`만 해당 범위에서 삭제 후 재생성합니다. `instruments`, 가격, 지표, 스캔 결과, 뉴스, 리포트, 실행 로그는 보존합니다.
`load-master`는 `market_scanner/assets/instruments.json`을 DB에 일괄 반영하는 명령으로, DB 복구나 seed 초기화 용도로 사용합니다.

## 종목 마스터 갱신
스캔 전에 `refresh-master`로 각 시장의 종목 목록을 최신 상태로 갱신합니다. 가격·지표 수집 없이 `instruments`, `universe_memberships`, `collection_runs`만 업데이트합니다. `--reset`을 붙이면 `universe_memberships`를 해당 범위에서 삭제 후 재생성합니다(instruments, 가격, 지표, 스캔 결과는 보존).

```bash
uv run python -m market_scanner.db refresh-master --market us              # FDR: --universe nasdaq·nyse·amex·nasdaq100·sp500
uv run python -m market_scanner.db refresh-master --market kospi           # FDR: --universe kospi·kospi100·kospi200
uv run python -m market_scanner.db refresh-master --market kosdaq          # FDR: --universe kosdaq·kosdaq150
uv run python -m market_scanner.db refresh-master --market global-indices  # JSON: global_indices_meta.json
uv run python -m market_scanner.db refresh-master --market commodities     # JSON: commodities_meta.json
uv run python -m market_scanner.db counts
```

## 스캔
기본 스캔은 DB `instruments`에서 해당 시장의 전체 활성 종목을 읽습니다.

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
uv run python Search.py --market kospi --stage scan
uv run python Search.py --market kospi --stage analyze
uv run python Search.py --market us --universe sp500 --stage translate
uv run python Search.py --market us --universe sp500 --stage news
uv run python Search.py --market kospi --stage render
```

유용한 옵션:

```bash
uv run python Search.py --market kospi --workers 8
uv run python Search.py --market kospi --date 20260430
uv run python Search.py --market kospi --force
uv run python Search.py --market kospi --limit 5
uv run python Search.py --market us --universe sp500 --stage news --news-symbols 80 --news-items 2
```

## 출력 파일

시장 전체 스캔은 시장 key 기준 파일을 생성합니다. universe 필터 스캔은 universe key 기준 파일을 생성합니다.

| 실행 예 | CSV | Markdown | HTML |
|---|---|---|---|
| `--market kospi` | `data/Data_Kospi_YYYYMMDD.csv` | `analysis/Analysis_Kospi_YYYYMMDD.md` | `reports/Report_Kospi_YYYYMMDD.html` |
| `--market kospi --universe kospi100` | `data/Data_Kospi100_YYYYMMDD.csv` | `analysis/Analysis_Kospi100_YYYYMMDD.md` | `reports/Report_Kospi100_YYYYMMDD.html` |
| `--market kospi --universe kospi200` | `data/Data_Kospi200_YYYYMMDD.csv` | `analysis/Analysis_Kospi200_YYYYMMDD.md` | `reports/Report_Kospi200_YYYYMMDD.html` |
| `--market us --universe sp500` | `data/Data_Sp500_YYYYMMDD.csv` | `analysis/Analysis_Sp500_YYYYMMDD.md` | `reports/Report_Sp500_YYYYMMDD.html` |
| `--market commodities` | `data/Data_Commodities_YYYYMMDD.csv` | `analysis/Analysis_Commodities_YYYYMMDD.md` | `reports/Report_Commodities_YYYYMMDD.html` |

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
uv run python -m market_scanner.site_builder --no-open
```

`site/`에는 GitHub Pages용 정적 대시보드가 생성됩니다. 자동 열기를 원하면 `--no-open`을 빼고 실행합니다.

대시보드는 최신 CSV/리포트 데이터를 기반으로 종합 시장 점수, 시장 체력, 매크로 리스크, 섹터/테마 히트맵, 오늘의 핵심 후보, 시장별 스냅샷, 섹터 리더십, 뉴스 브리핑을 표시합니다.

## 데이터 정책

- `instruments`: 종목마스터의 우선 원천입니다.
- `universe_memberships`: `nasdaq`, `nyse`, `amex`(거래소 전체), `nasdaq100`, `sp500`(지수), `kospi100`, `kospi200`, `kosdaq150` 같은 분석/필터 단위 멤버십입니다. US는 `--market us` 한 번으로 5개 universe가 동시 갱신됩니다.
- `market_scanner/assets/instruments.json`: DB가 비어 있거나 연결되지 않을 때 쓰는 seed/fallback입니다. 스캔 실행은 이 JSON을 자동 갱신하지 않습니다.
- `market_scanner/assets/global_indices_meta.json`, `commodities_meta.json`: 글로벌 지수·원자재는 FDR 자동 발견이 불가능하므로 JSON이 심볼 정의 원본입니다. 새 심볼 추가 시 JSON 편집 후 `refresh-master --market global-indices` 또는 `--market commodities`로 DB에 반영합니다. 현재 글로벌 지수는 22개입니다.
- 테마 ETF는 별도 스캔 없이 US 스캔 결과에서 파생됩니다. 대상 심볼은 `markets.py`의 `_THEME_PROXY_SYMBOLS` 상수로 관리합니다.
- 한국 시장 유니버스는 FinanceDataReader를 우선 사용하고, 실패 시 Naver Finance로 fallback합니다. 정적 JSON fallback(`kospi_static_meta.json`, `kosdaq_static_meta.json`)은 제거되었습니다.
- 한국 시장 가격 히스토리는 FinanceDataReader를 우선 사용하고, 실패하거나 히스토리가 부족하면 yfinance로 fallback합니다.
- `news` 단계는 최신 스캔 CSV가 있어야 실행되며, `all`에는 포함하지 않습니다.

## 패키지 구조

```text
market_scanner/
  models.py        # 공통 데이터 모델·설정
  indicators.py    # RSI·추세 계산
  markets.py       # 시장 설정·유니버스/메타데이터 로더
  pipeline.py      # 스캔/분석/렌더링 파이프라인
  compat.py        # 파일명 규칙·stage 흐름 래퍼
  db.py            # PostgreSQL schema/init/master/load 유틸리티
  translator.py    # US CSV 번역 단계
  assets/          # seed/cache 파일
  templates/       # HTML 리포트 템플릿/CSS
```

## GitHub Actions

| 워크플로우 | 실행 시각 | 대상 |
|---|---|---|
| `daily-scan.yml` | KST 08:05 | US Market |
| `daily-scan-overview.yml` | KST 08:20 | 글로벌 지수·테마 ETF·원자재 |
| `daily-scan-kospi.yml` | KST 16:05 | KOSPI |
| `daily-scan-kosdaq.yml` | KST 16:35 | KOSDAQ |
| `deploy-pages.yml` | 스캔 성공 후 자동, 또는 수동 실행 | GitHub Pages 사이트 빌드·배포 |
