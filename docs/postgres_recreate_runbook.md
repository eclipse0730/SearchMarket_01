# SearchMarket PostgreSQL Recreate Runbook

Last updated: 2026-05-06

이 문서는 `localhost:5433`을 다른 PostgreSQL 컨테이너가 점유하고 있을 때, 해당 컨테이너를 제거하고 현재 SearchMarket 프로젝트의 `docker-compose.yml` 기준으로 DB를 새로 생성하는 절차입니다.

## 적용 상황

다음처럼 포트는 열려 있지만 SearchMarket 기본 계정으로 접속되지 않는 경우에 사용합니다.

```bash
pg_isready -h localhost -p 5433 -U searchmarket -d searchmarket
psql postgresql://searchmarket:searchmarket@localhost:5433/searchmarket -At -c "SELECT 1;"
```

예상되는 문제 신호:

```text
localhost:5433 - accepting connections
FATAL:  password authentication failed for user "searchmarket"
```

이 경우 `localhost:5433`에는 PostgreSQL이 떠 있지만, 현재 프로젝트가 기대하는 DB가 아닐 수 있습니다.

## 기본 DB 정보

SearchMarket의 기본 접속 문자열은 다음과 같습니다.

```text
postgresql://searchmarket:searchmarket@localhost:5433/searchmarket
```

`docker-compose.yml`의 Postgres 서비스는 호스트 `5433` 포트를 컨테이너 `5432` 포트에 매핑합니다.

## 사전 확인

현재 실행 중인 컨테이너를 확인합니다.

```bash
docker ps --format '{{.Names}}\t{{.Status}}\t{{.Ports}}'
```

`5433`을 점유한 컨테이너가 SearchMarket 컨테이너인지 확인합니다. SearchMarket 기준 컨테이너 이름은 다음입니다.

```text
searchmarket-postgres
```

다른 컨테이너가 `5433`을 점유하고 있으면 환경변수를 확인합니다.

```bash
docker inspect stock_scanner_01-db-1 --format '{{range .Config.Env}}{{println .}}{{end}}'
```

예를 들어 다음처럼 나오면 SearchMarket DB가 아닙니다.

```text
POSTGRES_DB=stock_scanner
POSTGRES_USER=user
POSTGRES_PASSWORD=password
```

현재 프로젝트의 compose 서비스 상태도 확인합니다.

```bash
docker compose ps
```

## 기존 컨테이너 제거

삭제 전 해당 컨테이너가 사용하는 volume을 확인합니다.

```bash
docker inspect stock_scanner_01-db-1 --format '{{json .Mounts}}'
```

컨테이너만 제거하고 volume은 삭제하지 않습니다. volume 삭제는 기존 DB 데이터를 지우는 파괴 작업입니다.

```bash
docker stop stock_scanner_01-db-1
docker rm stock_scanner_01-db-1
```

## SearchMarket Postgres 신규 생성

현재 프로젝트 루트에서 Postgres 서비스를 생성하고 실행합니다.

```bash
docker compose up -d postgres
```

처음 실행하면 `postgres:16` 이미지를 내려받고 다음 리소스가 생성됩니다.

```text
Network searchmarket_01_default
Volume searchmarket_01_postgres_data
Container searchmarket-postgres
```

상태를 확인합니다.

```bash
docker compose ps
pg_isready -h localhost -p 5433 -U searchmarket -d searchmarket
psql postgresql://searchmarket:searchmarket@localhost:5433/searchmarket -At -c "SELECT current_database(), current_user, inet_server_port();"
```

정상 예:

```text
searchmarket-postgres   Up ... (healthy)   0.0.0.0:5433->5432/tcp
localhost:5433 - accepting connections
searchmarket|searchmarket|5432
```

## 스키마 초기화

프로젝트 스키마와 기준 market/universe 데이터를 생성합니다.

권장 명령:

```bash
uv run python -m market_scanner.storage.db init
```

`uv`가 현재 셸에서 잡히지 않지만 Python 환경에 프로젝트 의존성이 이미 설치되어 있으면 다음으로 실행할 수 있습니다.

```bash
python3 -m market_scanner.storage.db init
```

정상 예:

```text
database initialized
```

## 로컬 종목 마스터 Seed 적재

신규 DB는 스키마 초기화 직후 `instruments`가 비어 있습니다. 로컬 fallback seed인 `market_scanner/assets/instruments.json`을 적재합니다.

권장 명령:

```bash
uv run python -m market_scanner.storage.db load-master
```

대체 명령:

```bash
python3 -m market_scanner.storage.db load-master
```

정상 예:

```text
loaded instrument master for all markets: 914
```

운영 기준 종목마스터와 universe membership을 최신 외부 소스로 갱신하려면 이후 `refresh-master`를 별도로 실행합니다.

```bash
uv run python -m market_scanner.storage.db refresh-master --market us
uv run python -m market_scanner.storage.db refresh-master --market kospi
uv run python -m market_scanner.storage.db refresh-master --market kosdaq
```

## 최종 검증

프로젝트 DB 유틸리티로 핵심 테이블 count를 확인합니다.

```bash
uv run python -m market_scanner.storage.db counts
```

대체 명령:

```bash
python3 -m market_scanner.storage.db counts
```

신규 생성 직후 seed까지 적재한 정상 예:

```text
markets: 5
universe_definitions: 13
instruments: 914
universe_memberships: 0
daily_prices: 0
daily_indicators: 0
instrument_fundamentals: 0
scan_results: 0
market_snapshots: 0
sector_snapshots: 0
collection_runs: 0
```

시장별 instruments count도 확인할 수 있습니다.

```bash
psql postgresql://searchmarket:searchmarket@localhost:5433/searchmarket -At -c "SELECT market_key, count(*) FROM instruments GROUP BY market_key ORDER BY market_key;"
```

정상 예:

```text
commodities|11
global-indices|15
kosdaq|153
kospi|200
us|535
```

마지막으로 실행 중인 컨테이너를 확인합니다.

```bash
docker ps --format '{{.Names}}\t{{.Status}}\t{{.Ports}}'
```

정상 예:

```text
searchmarket-postgres   Up ... (healthy)   0.0.0.0:5433->5432/tcp
```

## 주의 사항

- `docker rm <container>`는 컨테이너만 삭제합니다. Docker volume은 삭제하지 않습니다.
- `docker volume rm ...` 또는 `docker compose down -v`는 DB 데이터를 지울 수 있으므로 명시적인 백업/삭제 의도가 있을 때만 사용합니다.
- `stock_scanner_01_postgres_data`처럼 다른 프로젝트 volume은 SearchMarket 운영에 필요하지 않지만, 원 소유 프로젝트 데이터일 수 있으므로 이 절차에서는 삭제하지 않습니다.
- `stock_scanner_01-redis-1`처럼 `5433`과 무관한 컨테이너는 SearchMarket Postgres 생성에 영향을 주지 않으면 건드리지 않습니다.
