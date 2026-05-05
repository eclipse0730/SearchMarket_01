# Codex Project Instructions

이 문서는 Codex가 Search60 프로젝트에서 작업할 때 우선 참고해야 하는 프로젝트별 지침입니다.

## Working Principles

- 코드 변경 전 관련 모듈과 산출물 흐름을 먼저 확인합니다.
- 기존 사용자 변경을 되돌리지 않습니다. 특히 `git status`에 이미 잡힌 삭제/수정은 사용자 의도일 수 있으므로 명시 요청 없이 복구하지 않습니다.
- 자동 생성 리포트 파일과 개발 문서를 구분합니다.
- 기능을 추가하거나 동작을 바꾸면 관련 문서도 같은 작업 범위에서 갱신합니다.
- 한국어 리포트/문서 파일은 UTF-8로 읽고 씁니다.

## Local Commands

현재 로컬 기본 `python`/`python3` 명령은 OS별로 다를 수 있습니다. 검증에는 `uv run python`으로 프로젝트 `.venv`를 사용합니다.

```powershell
uv run python --version
uv run python -m compileall Search.py market_scanner
uv run python Search.py --help
```

네트워크가 필요한 명령은 실행 환경에 따라 실패할 수 있습니다.

- `Search.py --stage scan`: yfinance, Wikipedia, FinanceDataReader, Naver Finance, Investing 검색 요청을 사용할 수 있습니다.
- `Search.py --stage news`: DB의 최신 `scan_results` 상위 종목을 기준으로 yfinance `Ticker.news` 요청을 사용해 `market_scanner/assets/news_cache.json`을 갱신합니다. 실행 시간과 요청량 때문에 `all`에는 포함하지 않습니다.
- `uv run python -m market_scanner.reports.site_builder`: DB 기반 사이트 빌드입니다. 로컬 실행은 빌드 후 기본 브라우저로 `site/index.html`을 열며, `--no-open`으로 자동 열기를 끌 수 있습니다. S&P 500/Dow 30 파생 페이지 생성 시 유니버스 로더가 네트워크/캐시를 사용할 수 있습니다.

## Important Files

- `Search.py`: CLI 진입점입니다.
- `market_scanner/models.py`: 공통 데이터 모델과 설정입니다.
- `market_scanner/config/markets.py`: 시장 정의, 유니버스 로더, 메타데이터 로더입니다.
- `market_scanner/analysis/indicators.py`: RSI와 추세 계산입니다.
- `market_scanner/analysis/screener.py`: DB 기반 스크리닝과 점수화입니다.
- `market_scanner/pipeline.py`: v2 단계 순서 제어입니다.
- `market_scanner/reports/site_builder.py`: GitHub Pages용 `site/` 생성기입니다.
- `market_scanner/templates/report.html`: HTML 리포트 템플릿입니다.
- `market_scanner/templates/report.css`: HTML 리포트 스타일입니다.
- `README.md`: 사용자용 설치/실행 설명입니다.
- `DEVELOPMENT_NOTES.md`: 개발/운영 분석 노트입니다.
- `.github/workflows/*.yml`: 자동 스캔과 Pages 배포 설정입니다.

## Documentation Relationship Map

코드 변경 시 아래 관계를 확인하고 필요한 문서를 함께 갱신합니다.

| 변경 대상 | 함께 확인/갱신할 문서와 파일 |
|---|---|
| CLI 옵션, 기본값, 실행 단계 변경 | `README.md`, `DEVELOPMENT_NOTES.md`, `.github/workflows/*.yml` |
| 시장 추가/삭제, 시장 key 변경 | `README.md`, `DEVELOPMENT_NOTES.md`, `market_scanner/reports/site_builder.py`, `.github/workflows/*.yml` |
| 출력 파일명 규칙 변경 | `README.md`, `DEVELOPMENT_NOTES.md`, `.github/workflows/*.yml` |
| 스캔 데이터 컬럼 추가/삭제/이름 변경 | `DEVELOPMENT_NOTES.md`, `market_scanner/analysis/screener.py`, `market_scanner/reports/html_report.py`, `market_scanner/templates/report.html`, `market_scanner/reports/site_builder.py` |
| 점수 산식, RSI, 추세 계산 변경 | `DEVELOPMENT_NOTES.md`, `README.md`의 설명 필요 여부, 관련 테스트가 생기면 테스트 문서 |
| HTML 리포트 UI/필터/차트 변경 | `DEVELOPMENT_NOTES.md`, `market_scanner/templates/report.html`, `market_scanner/templates/report.css`, `site_builder.py` 영향 여부 |
| GitHub Pages 구조 변경 | `README.md`, `DEVELOPMENT_NOTES.md`, `.github/workflows/deploy-pages.yml` |
| GitHub Actions 스케줄/대상 변경 | `README.md`, `DEVELOPMENT_NOTES.md`, 관련 workflow 파일 |
| 의존성 추가/삭제 | `requirements.txt`, `README.md`, `DEVELOPMENT_NOTES.md`, workflow 설치 단계 |
| 로컬 실행/검증 방식 변경 | `README.md`, `DEVELOPMENT_NOTES.md`, 이 `AGENTS.md` |

## Generated Outputs

다음 파일은 스캔/분석/렌더 단계에서 생성되는 산출물입니다.

- `site/**`
- `market_scanner/assets/instruments.json`은 공통 종목 마스터 seed/fallback입니다. PostgreSQL `instruments` 테이블을 우선 원천으로 사용하며, 스캔 단계는 이 JSON을 자동 갱신하지 않습니다.
- `market_scanner/assets/.yfinance_cache/`는 로컬 yfinance SQLite 캐시이며 Git 추적 대상이 아닙니다.

주의:

- `site_builder.py`는 `site/`를 삭제 후 재생성합니다. 수동으로 넣은 `site/` 파일은 유지되지 않습니다.
- Pages 상세페이지는 DB의 `scan_results` 최신 데이터를 현재 템플릿으로 다시 렌더링합니다.

## Current Known State

2026-05-03 기준:

- 권장 CLI 구조는 시장 단위 `--market`과 선택적 멤버십 필터 `--universe`임. 예: `uv run python Search.py --market us --universe nasdaq100`, `uv run python Search.py --market kospi --universe kospi100`
- US universe 구조: `universe_memberships`에 `nasdaq`/`nyse`/`amex`(거래소 전체), `nasdaq100`/`sp500`(지수) 5개 universe 사용. 기존 단일 `us` universe_key는 폐기됨. `--market us` 한 번으로 5개 동시 갱신됨(`_MARKET_UNIVERSE_EXPANSION`)
- US 심볼 소스: FinanceDataReader `StockListing("NASDAQ"|"NYSE"|"AMEX"|"NASDAQ100"|"SP500")`. `ABR PR D`처럼 preferred share 패턴(`... PR ...`)인 심볼은 refresh-master 입력 단계에서 제외. 실패 시 Wikipedia(sp500), 정적 JSON(nasdaq100) fallback. NASDAQ/NYSE/AMEX는 FDR 실패 시 빈 목록 반환 (NASDAQ Trader txt fallback 제거됨)
- `kospi`, `kosdaq`은 시장 전체가 기본이며, `kospi100`, `kospi200`, `kosdaq150`은 `--universe` 옵션값으로만 사용함
- `kospi_static_meta.json`, `kosdaq_static_meta.json`, `sp500_members_cache.json` 삭제됨. KOSPI/KOSDAQ universe 함수는 FDR/Naver 직접 반환, JSON fallback 없음
- 글로벌 지수 워치리스트는 `global_indices_meta.json` 원본, 현재 22개 심볼. 새 지수 추가 시 JSON 편집 후 `load-master` 실행. 글로벌 지수/원자재는 FDR 자동 발견 불가 → JSON이 영구 원본
- 테마 ETF는 별도 시장/JSON/스캔 없이 US 스캔 결과에서 파생됨 (Dow 30과 동일 패턴). 대상 심볼은 `markets.py`의 `_THEME_PROXY_SYMBOLS` 상수로 관리. 추가/삭제 시 상수만 수정
- `site_builder.py`는 DB의 `market_snapshots`, `sector_snapshots`, `scan_results` 최신 데이터를 기준으로 Pages 빌드를 수행함
- `uv run python -m compileall Search.py market_scanner` 통과
- `uv run python Search.py --help` 통과
- 최신 DB 스캔 결과는 정상 로드됨
- `site_builder.py`는 DB 기반 페이지 생성을 지원함
- 메인페이지는 preview-home v2 디자인을 반영해 `site/index.html`에 생성하며, `site/preview-home/index.html`은 같은 디자인의 보조 미리보기 페이지임
- 상세페이지 v2는 좌측 종목 리스트와 우측 Sector Heatmap/Fear/Setup/Scatter 패널 구조임
- 상세페이지 헤더는 제목 아래 기준일/행 수와 KST 기준 갱신시간을 표시함
- 모든 시장의 Investing 링크는 한국 사용자 UX를 위해 `kr.investing.com` 도메인으로 출력함
- KOSPI/KOSDAQ 상세페이지 링크도 NASDAQ 100과 같이 Investing 상세 URL 캐시를 우선 사용하고, 실패 시 검색 링크로 fallback함
- KOSPI/KOSDAQ/US 가격 히스토리는 스캔 시 FinanceDataReader를 우선 사용하고, 실패 또는 히스토리 부족 시 yfinance로 fallback함. 한국 전체 유니버스는 FDR/KRX listing 실패 시 Naver Finance 시가총액 목록으로 보강함. 한국 종목명/섹터는 FinanceDataReader, Naver Finance, 정적 메타데이터로 보강하고, 렌더링 시 placeholder 이름/섹터를 보정함. 한국 시장 화면은 한글 종목명 우선이며, 한글명을 확보하지 못하면 영어 회사명 대신 종목코드를 표시함
- 모든 시장의 고정 종목 메타데이터는 PostgreSQL `instruments` 테이블을 우선 사용하고, DB가 비어 있거나 연결되지 않을 때 `market_scanner/assets/instruments.json`을 seed/fallback으로 사용함. 시장별 `*_static_meta.json`은 모두 삭제됨. `instruments.json`만 유지
- 종목마스터 신규 갱신 기준은 `uv run python -m market_scanner.storage.db refresh-master`이며, `--market us`는 `nasdaq`/`nyse`/`amex`/`nasdaq100`/`sp500` 5개 universe를 한 번에 갱신함. `--market kospi`는 KOSPI 전체만 갱신하고 `--market kospi --universe kospi100`, `--market kospi --universe kospi200`처럼 명시했을 때 대표 유니버스를 갱신함. `--reset`은 `universe_memberships`만 해당 범위에서 삭제 후 재생성하며, `instruments`, 가격, 지표, 스캔 결과, 뉴스, 리포트, `collection_runs` 로그는 보존함. `load-master`는 JSON seed 복구용 호환 명령으로 유지함
- 스캔 기본값은 DB `instruments`의 시장 전체 활성 종목이며, `uv run python Search.py --market kospi --universe kospi200`처럼 `--universe`를 지정하면 `universe_memberships`의 해당 현재 편입 종목만 스캔함. 시장과 universe가 맞지 않으면 오류로 중단함
- `kospi`, `kosdaq`은 시장 전체가 기본이며, `kospi100`, `kospi200`, `kosdaq150`은 `--universe` 옵션값으로만 사용함
- `refresh-master`는 기존 멤버십과 새 수집 목록을 비교해 일치/불일치, 추가/삭제, 순위 변경, 신규 instrument 샘플을 로그와 `collection_runs.params`에 남기며, 멤버십 목록과 순서가 같으면 `universe_memberships` 재작성을 건너뜀
- `uv run python -m market_scanner.storage.db init`은 기준 market/universe row를 최신 코드 기준으로 upsert하고, 현재 코드에 없는 기준 row는 삭제 대신 `is_active = false`로 비활성화함
- 상세페이지 종목 리스트의 추세 정렬은 표시 문자열이 아니라 숫자 추세 점수 기준으로 처리함
- 상세페이지 Heatmap은 섹터별 `change_pct` 평균 상승률 강도 기준으로 표시함. 타일에는 평균, 중앙값, 상승 종목 비율, 종목 수를 함께 표시함
- 상세페이지 종목 리스트에서는 MA60/120/240 차이율 컬럼을 숨기고, 해당 값은 Scatter/Setup 계산용 DATA에는 유지함
- 뉴스 브리핑 탭은 `market_scanner/assets/news_cache.json`이 있으면 캐시 기반으로 표시하고, 렌더링 중 실시간 뉴스 요청은 피함
- 뉴스 캐시는 `Search.py --stage news`에서 생성/갱신하며, 기본값은 종합점수 상위 50개 종목 × 종목당 최대 3건임
- 공포지수는 `yfinance` VIX 조회를 우선 사용하되, 렌더링 환경 네트워크가 막힐 수 있으므로 스캔 데이터의 `^VIX` fallback을 지원함
- Dow 30은 별도 CLI 시장이 아니라 US 스캔 결과에서 파생 생성되는 사이트 페이지임

## Maintenance Rule

새 기능 개발이나 리팩터링이 끝나면 아래를 점검합니다.

- 코드 변경이 CLI/출력/배포/문서 관계도 중 어디에 영향을 주는지 확인합니다.
- `DEVELOPMENT_NOTES.md`의 관련 섹션과 `Last updated`를 갱신합니다.
- 사용자용 실행법이 바뀌면 `README.md`를 갱신합니다.
- Codex 작업 규칙이나 문서 관계도가 바뀌면 이 `AGENTS.md`를 갱신합니다.
