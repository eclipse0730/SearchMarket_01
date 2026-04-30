# Codex Project Instructions

이 문서는 Codex가 Search60 프로젝트에서 작업할 때 우선 참고해야 하는 프로젝트별 지침입니다.

## Working Principles

- 코드 변경 전 관련 모듈과 산출물 흐름을 먼저 확인합니다.
- 기존 사용자 변경을 되돌리지 않습니다. 특히 `git status`에 이미 잡힌 삭제/수정은 사용자 의도일 수 있으므로 명시 요청 없이 복구하지 않습니다.
- 자동 생성 리포트 파일과 개발 문서를 구분합니다.
- 기능을 추가하거나 동작을 바꾸면 관련 문서도 같은 작업 범위에서 갱신합니다.
- 한국어 리포트/문서 파일은 UTF-8로 읽고 씁니다.

## Local Commands

현재 로컬 기본 `python` 명령은 신뢰하지 않습니다. 검증에는 가상환경 Python을 명시합니다.

```powershell
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -m compileall Search.py market_scanner
.\.venv\Scripts\python.exe Search.py --help
```

네트워크가 필요한 명령은 실행 환경에 따라 실패할 수 있습니다.

- `Search.py --stage scan`: yfinance, Wikipedia, FinanceDataReader, Naver Finance, Investing 검색 요청을 사용할 수 있습니다.
- `Search.py --stage translate`: deep-translator/GoogleTranslator 요청을 사용할 수 있습니다.
- `Search.py --stage news`: 최신 CSV 기반으로 yfinance `Ticker.news` 요청을 사용해 `market_scanner/assets/news_cache.json`을 갱신합니다. 실행 시간과 요청량 때문에 `all`에는 포함하지 않습니다.
- `python -m market_scanner.site_builder`: 로컬 파일 기반 사이트 빌드입니다. 로컬 실행은 빌드 후 기본 브라우저로 `site/index.html`을 열며, `--no-open`으로 자동 열기를 끌 수 있습니다. S&P 500 파생 페이지 생성 시 유니버스 로더가 네트워크/캐시를 사용할 수 있습니다.

## Important Files

- `Search.py`: CLI 진입점입니다.
- `market_scanner/models.py`: 공통 데이터 모델과 설정입니다.
- `market_scanner/markets.py`: 시장 정의, 유니버스 로더, 메타데이터 로더입니다.
- `market_scanner/indicators.py`: RSI와 추세 계산입니다.
- `market_scanner/pipeline.py`: 스캔, 점수화, Markdown/HTML 리포트 생성입니다.
- `market_scanner/compat.py`: 루트 산출물 파일명 호환 레이어입니다.
- `market_scanner/site_builder.py`: GitHub Pages용 `site/` 생성기입니다.
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
| 시장 추가/삭제, 시장 key 변경 | `README.md`, `DEVELOPMENT_NOTES.md`, `market_scanner/compat.py`, `market_scanner/site_builder.py`, `.github/workflows/*.yml` |
| 출력 파일명 규칙 변경 | `README.md`, `DEVELOPMENT_NOTES.md`, `market_scanner/compat.py`, `market_scanner/site_builder.py`, `.github/workflows/*.yml` |
| 스캔 데이터 컬럼 추가/삭제/이름 변경 | `DEVELOPMENT_NOTES.md`, `market_scanner/pipeline.py`, `market_scanner/templates/report.html`, `market_scanner/site_builder.py` |
| 점수 산식, RSI, 추세 계산 변경 | `DEVELOPMENT_NOTES.md`, `README.md`의 설명 필요 여부, 관련 테스트가 생기면 테스트 문서 |
| HTML 리포트 UI/필터/차트 변경 | `DEVELOPMENT_NOTES.md`, `market_scanner/templates/report.html`, `market_scanner/templates/report.css`, `site_builder.py` 영향 여부 |
| GitHub Pages 구조 변경 | `README.md`, `DEVELOPMENT_NOTES.md`, `.github/workflows/deploy-pages.yml` |
| GitHub Actions 스케줄/대상 변경 | `README.md`, `DEVELOPMENT_NOTES.md`, 관련 workflow 파일 |
| 의존성 추가/삭제 | `requirements.txt`, `README.md`, `DEVELOPMENT_NOTES.md`, workflow 설치 단계 |
| 로컬 실행/검증 방식 변경 | `README.md`, `DEVELOPMENT_NOTES.md`, 이 `AGENTS.md` |

## Generated Outputs

다음 파일은 스캔/분석/렌더 단계에서 생성되는 산출물입니다.

- `data/Data_*.csv`가 canonical CSV 위치입니다.
- 과거 루트 `Data_*.csv`는 읽기 fallback으로만 지원합니다.
- `analysis/Analysis_*.md`
- `reports/Report_*.html`
- `site/**`
- `market_scanner/assets/investing_url_cache.json`
- `market_scanner/assets/instruments.json`은 공통 종목 마스터입니다. 고정 메타데이터를 누적하지만 자동 스캔값이 `static`/`manual` 출처 레코드를 덮어쓰지 않게 관리합니다.
- `market_scanner/assets/sp500_members_cache.json`
- `market_scanner/assets/us_listed_symbols_cache.json`
- `market_scanner/assets/.yfinance_cache/`는 로컬 yfinance SQLite 캐시이며 Git 추적 대상이 아닙니다.

주의:

- `analysis/Analysis_*.md`는 자동 생성 리포트입니다. 개발 노트는 `DEVELOPMENT_NOTES.md`에 작성합니다.
- 새 스캔 CSV 산출물은 `data/`에 저장합니다.
- `site_builder.py`는 `site/`를 삭제 후 재생성합니다. 수동으로 넣은 `site/` 파일은 유지되지 않습니다.
- Pages 상세페이지는 최신 CSV를 현재 템플릿으로 다시 렌더링합니다. `reports/Report_*.html`은 개별 HTML 리포트 산출물로 보관합니다. 과거 루트 `Report_*.html`은 읽기 fallback으로만 지원합니다.
- S&P 500 구성 종목은 `sp500_members_cache.json` 구조화 캐시를 사용합니다.

## Current Known State

2026-04-28 기준:

- `nasdaq100`과 `sp500`은 독립 CLI 시장이며, 기존 `us` 결합 스캔은 호환용으로 유지함. 사이트 빌더는 독립 CSV가 없을 때만 기존 US CSV에서 NASDAQ 100/S&P 500/Dow 30 페이지를 fallback 생성함
- `site_builder.py`는 빈 최신 CSV를 건너뛰고 이전 정상 CSV를 찾아 Pages 빌드를 계속함
- `.\.venv\Scripts\python.exe -m compileall Search.py market_scanner` 통과
- `.\.venv\Scripts\python.exe Search.py --help` 통과
- 최신 CSV 샘플은 정상 로드됨
- `site_builder.py`는 최신 CSV 기반 페이지 fallback을 지원함
- 메인페이지는 preview-home v2 디자인을 반영해 `site/index.html`에 생성하며, `site/preview-home/index.html`은 같은 디자인의 보조 미리보기 페이지임
- 상세페이지 v2는 좌측 종목 리스트와 우측 Sector Heatmap/Fear/Setup/Scatter 패널 구조임
- 상세페이지 헤더는 제목 아래 기준일/행 수와 KST 기준 갱신시간을 표시함
- 모든 시장의 Investing 링크는 한국 사용자 UX를 위해 `kr.investing.com` 도메인으로 출력함
- KOSPI/KOSDAQ 상세페이지 링크도 NASDAQ 100과 같이 Investing 상세 URL 캐시를 우선 사용하고, 실패 시 검색 링크로 fallback함
- KOSPI/KOSDAQ 계열 가격 히스토리는 스캔 시 FinanceDataReader를 우선 사용하고, 실패 또는 히스토리 부족 시 yfinance로 fallback함. 한국 전체 유니버스는 FDR/KRX listing 실패 시 Naver Finance 시가총액 목록으로 보강함. 한국 종목명/섹터는 FinanceDataReader, Naver Finance, 정적 메타데이터로 보강하고, 렌더링 시 placeholder 이름/섹터를 보정함. 한국 시장 화면은 한글 종목명 우선이며, 한글명을 확보하지 못하면 영어 회사명 대신 종목코드를 표시함
- 모든 시장의 고정 종목 메타데이터는 `market_scanner/assets/instruments.json`을 우선 사용하고, 기존 시장별 `*_static_meta.json`은 호환 fallback으로 유지함
- 상세페이지 종목 리스트의 추세 정렬은 표시 문자열이 아니라 숫자 추세 점수 기준으로 처리함
- 상세페이지 Heatmap은 섹터별 `change_pct` 평균 상승률 강도 기준으로 표시함. 타일에는 평균, 중앙값, 상승 종목 비율, 종목 수를 함께 표시함
- 상세페이지 종목 리스트에서는 MA60/120/240 차이율 컬럼을 숨기고, 해당 값은 Scatter/Setup 계산용 DATA에는 유지함
- 뉴스 브리핑 탭은 `market_scanner/assets/news_cache.json`이 있으면 캐시 기반으로 표시하고, 렌더링 중 실시간 뉴스 요청은 피함
- 뉴스 캐시는 `Search.py --stage news`에서 생성/갱신하며, 기본값은 종합점수 상위 50개 종목 × 종목당 최대 3건임
- 공포지수는 `yfinance` VIX 조회를 우선 사용하되, 렌더링 환경 네트워크가 막힐 수 있으므로 글로벌 지수 CSV의 `^VIX` fallback을 지원함
- Dow 30은 별도 CLI 시장이 아니라 US 스캔 결과에서 파생 생성되는 사이트 페이지임
- S&P 500 캐시는 과거 list 형식과 새 metadata 형식을 모두 읽을 수 있음
- `Analysis_*.md`와 `Report_*.html`은 루트가 아니라 각각 `analysis/`, `reports/` 폴더에서 관리함.

## Maintenance Rule

새 기능 개발이나 리팩터링이 끝나면 아래를 점검합니다.

- 코드 변경이 CLI/출력/배포/문서 관계도 중 어디에 영향을 주는지 확인합니다.
- `DEVELOPMENT_NOTES.md`의 관련 섹션과 `Last updated`를 갱신합니다.
- 사용자용 실행법이 바뀌면 `README.md`를 갱신합니다.
- Codex 작업 규칙이나 문서 관계도가 바뀌면 이 `AGENTS.md`를 갱신합니다.
