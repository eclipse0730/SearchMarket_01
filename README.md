# Stock MA Scanner

미국 주식·코스피·코스닥·글로벌 지수·테마 ETF·원자재를 대상으로
60/120/240일 이동평균선 근접 종목을 스캔하고 분석 Markdown·HTML 리포트를 생성하는 프로젝트입니다.

## 설치

```bash
uv venv
.venv\Scripts\activate
uv pip install -r requirements.txt
```

## 사용법

```bash
# 기본 (legacy combined US 파이프라인)
python Search.py

# 시장 선택
python Search.py --market nasdaq100
python Search.py --market sp500
python Search.py --market kospi
python Search.py --market kosdaq
python Search.py --market kospi-all       # KOSPI 전체 유니버스
python Search.py --market kosdaq-all      # KOSDAQ 전체 유니버스
python Search.py --market global-indices
python Search.py --market theme-proxies
python Search.py --market commodities
python Search.py --market us              # legacy combined US scan

# 단계 선택 (기본: all)
python Search.py --market nasdaq100 --stage scan      # 스캔 → data/Data_Nasdaq100_YYYYMMDD.csv
python Search.py --market nasdaq100 --stage analyze   # 분석 → analysis/Analysis_Nasdaq100_YYYYMMDD.md
python Search.py --market nasdaq100 --stage translate # 번역 (US 계열)
python Search.py --market sp500 --stage news          # 뉴스 캐시 → market_scanner/assets/news_cache.json
python Search.py --market sp500 --stage render        # HTML → reports/Report_Sp500_YYYYMMDD.html

# 기타 옵션
python Search.py --market nasdaq100 --workers 8       # 병렬 worker 수
python Search.py --market sp500 --date 20260425       # 대상 날짜 지정
python Search.py --market nasdaq100 --force           # CSV 있어도 재스캔
python Search.py --market nasdaq100 --force --limit 5 # 빠른 수집 검증
python Search.py --market sp500 --stage news --news-symbols 80 --news-items 2
python Search.py --market nasdaq100 --setup-scheduler # 윈도우 작업 스케줄러 등록
python Search.py --market sp500 --setup-scheduler --time 08:30
```

## 출력 파일

| 시장 | CSV | Markdown | HTML |
|---|---|---|---|
| nasdaq100 | `data/Data_Nasdaq100_YYYYMMDD.csv` | `analysis/Analysis_Nasdaq100_YYYYMMDD.md` | `reports/Report_Nasdaq100_YYYYMMDD.html` |
| sp500 | `data/Data_Sp500_YYYYMMDD.csv` | `analysis/Analysis_Sp500_YYYYMMDD.md` | `reports/Report_Sp500_YYYYMMDD.html` |
| us | `data/Data_YYYYMMDD.csv` | `analysis/Analysis_YYYYMMDD.md` | `reports/Report_YYYYMMDD.html` |
| kospi | `data/Data_Kospi_YYYYMMDD.csv` | `analysis/Analysis_Kospi_YYYYMMDD.md` | `reports/Report_Kospi_YYYYMMDD.html` |
| kosdaq | `data/Data_Kosdaq_YYYYMMDD.csv` | `analysis/Analysis_Kosdaq_YYYYMMDD.md` | `reports/Report_Kosdaq_YYYYMMDD.html` |
| kospi-all | `data/Data_KospiAll_YYYYMMDD.csv` | `analysis/Analysis_KospiAll_YYYYMMDD.md` | `reports/Report_KospiAll_YYYYMMDD.html` |
| kosdaq-all | `data/Data_KosdaqAll_YYYYMMDD.csv` | `analysis/Analysis_KosdaqAll_YYYYMMDD.md` | `reports/Report_KosdaqAll_YYYYMMDD.html` |
| global-indices | `data/Data_GlobalIndices_YYYYMMDD.csv` | `analysis/Analysis_GlobalIndices_YYYYMMDD.md` | `reports/Report_GlobalIndices_YYYYMMDD.html` |
| theme-proxies | `data/Data_ThemeProxies_YYYYMMDD.csv` | `analysis/Analysis_ThemeProxies_YYYYMMDD.md` | `reports/Report_ThemeProxies_YYYYMMDD.html` |
| commodities | `data/Data_Commodities_YYYYMMDD.csv` | `analysis/Analysis_Commodities_YYYYMMDD.md` | `reports/Report_Commodities_YYYYMMDD.html` |

## 사이트 대시보드

```bash
python -m market_scanner.site_builder
```

`site/`에는 GitHub Pages용 정적 대시보드가 생성됩니다. 로컬 실행 시 빌드 완료 후 `site/index.html`이 기본 브라우저로 자동 열립니다. 자동 열기를 건너뛰려면 `--no-open`을 붙입니다.

```bash
python -m market_scanner.site_builder --no-open
```

메인페이지는 preview-home v2 디자인을 반영해 `site/index.html`에 생성됩니다. `site/preview-home/index.html`은 같은 디자인을 확인하는 보조 미리보기 페이지입니다.

메인 페이지는 최신 CSV/리포트 데이터를 기반으로 다음 통합 지표를 보여줍니다.

- 종합 시장 점수: 주식 강세 비율, 매크로 강도, RSI 균형, 전체 평균 등락을 결합한 0-100점 요약
- 주식 시장 체력: NASDAQ 100, S&P 500, KOSPI, KOSDAQ의 강세 비율과 최강/최약 시장
- 매크로 리스크: 글로벌 지수, 테마 ETF, 원자재 흐름을 묶은 위험자산 환경
- 섹터·테마 히트맵: 추세와 등락률 기준의 리딩/약세 섹터
- 오늘의 핵심 후보: 종합점수와 상승률 기준으로 가장 먼저 볼 종목
- 시장별 스냅샷: NASDAQ 100, S&P 500, Dow 30, KOSPI, KOSDAQ, 글로벌 지수, 테마 ETF, 원자재 비교
- 섹터 리더십: 추세 점수가 높은 섹터 요약
- 오늘의 관찰 종목: 모멘텀, 눌림목, 과매도, 과열, 급등, 거래량 관점의 후보를 표시하며 종목 링크는 Investing 한국 상세페이지로 연결

GitHub Pages 사이트는 `data/`의 최신 CSV를 현재 템플릿으로 다시 렌더링합니다. `reports/Report_*.html`은 개별 HTML 리포트 산출물로 보관됩니다.
자동 스캔 워크플로가 성공적으로 끝나면 `Deploy GitHub Pages`가 이어서 실행되어 Pages artifact를 다시 빌드하고 배포합니다.

상세 페이지는 좌측 종목 리스트와 우측 인사이트 패널로 구성됩니다.

- 헤더 갱신시간: 상세페이지 제목 아래에 생성 시각을 `KST` 기준으로 표시
- 압축형 Signal Strip: 이동평균선 근접 수, 시장 상태와 리딩/약세 섹터, RSI 온도 분포, 강세 비율, VIX 공포지수 해석
- 섹터별 상승률 Heatmap: 섹터 평균 등락률, 중앙값, 상승 종목 비율, 종목 수와 전체 상승/하락 종목 수 표시
- Setup Buckets
- MA Distance vs RSI Scatter
- 추세 화살표 표시: `↑↑`, `↑`, `→`, `↓`, `↓↓`
- 캔들 표시: OHLC 컬럼이 있는 최신 스캔 CSV에서는 종목 리스트에 미니 캔들 모양 표시
- 뉴스 브리핑 탭: 향후 뉴스 수집 캐시가 있으면 밤새 뉴스 요약 표시

분석 리포트와 CSV에는 PRD v1.1 기준 복합 점수가 포함됩니다.

- 점수 비중: 차트 30%, 기술지표 25%, 재무 20%, 테마 15%, 수급 10%
- 추가 지표: 시가/고가/저가/종가, 갭, 캔들 몸통/꼬리, MACD, 볼린저 밴드, PBR, ROE, 매출성장률, 시총

티커 링크는 한국 사용자 기준으로 동작하며, 모든 시장의 Investing 링크는 `kr.investing.com`으로 연결합니다. KOSPI/KOSDAQ도 NASDAQ 100처럼 Investing 상세 URL 캐시를 우선 사용하고, 캐시에 없거나 해석에 실패한 종목만 검색 링크로 fallback합니다.

`news` 단계는 최신 스캔 CSV가 있어야 실행됩니다. 기본적으로 종합점수 상위 50개 종목에서 종목당 최대 3개 뉴스를 수집해 `market_scanner/assets/news_cache.json`에 날짜/시장별로 저장합니다. 실행 시간이 늘 수 있어 `all`에는 자동 포함하지 않습니다.

## 패키지 구조

```
market_scanner/
  models.py        # 공통 데이터 모델·설정 (ScanSettings, MarketDefinition)
  indicators.py    # RSI·추세 계산
  markets.py       # 시장별 설정·유니버스 로더
  pipeline.py      # 스캔/분석/렌더링 공통 파이프라인
  compat.py        # 파일명 규칙·stage 흐름 래퍼
  translator.py    # US CSV 번역 단계
  assets/
    instruments.json
    nasdaq100_static_meta.json
    kospi_static_meta.json
    kosdaq_static_meta.json
    sp500_members_cache.json
    global_indices_meta.json
    theme_proxies_meta.json
    commodities_meta.json
  templates/
    report.html
    report.css
```

## Metadata Notes

KOSPI/KOSDAQ 종목명과 섹터는 정적 메타데이터와 FinanceDataReader 한국 종목명을 우선 사용하고, 동적 편입 종목은 스캔 단계에서 yfinance `Ticker.info`도 함께 사용합니다. 이미 생성된 CSV에 티커 문자열이나 `Unknown`이 남아 있어도 사이트 렌더링 단계에서 가능한 범위의 표시값을 보정합니다. 한국 시장 화면은 한글 종목명을 우선 표시하고, 한글명을 확보하지 못한 경우 영어 회사명 대신 종목코드를 표시합니다.

`market_scanner/assets/instruments.json` is the shared instrument master for all markets. Fixed metadata such as `symbol`, `display_symbol`, `name_en`, `name_local`, `sector`, and `description` is read from this file first, while `Data_*.csv` remains the daily scan output. Scan runs append newly observed metadata to `instruments.json`, but `static`/`manual` records are not overwritten by automatic scan values.

KOSPI metadata is maintained against the KOSPI 200 component set. When the static KOSPI metadata already contains at least 200 symbols, the scanner treats that list as the authoritative KOSPI universe instead of appending the FinanceDataReader market-cap fallback.

## US Market Split

`nasdaq100` and `sp500` are standalone scan markets. New US scans write `data/Data_Nasdaq100_YYYYMMDD.csv` and `data/Data_Sp500_YYYYMMDD.csv` instead of relying on the legacy combined `us` CSV. The `us` market remains available for backward compatibility, and the site builder can still derive NASDAQ 100, S&P 500, and Dow 30 pages from an old combined US CSV when standalone files are missing.

## GitHub Actions

| 워크플로우 | 실행 시각 | 대상 |
|---|---|---|
| `daily-scan.yml` | KST 08:05 (장 마감 후 익일 오전) | US Market |
| `daily-scan-overview.yml` | KST 08:20 | 글로벌 지수·테마 ETF·원자재 |
| `daily-scan-kospi.yml` | KST 16:05 (코스피 장 마감 직후) | KOSPI |
| `daily-scan-kosdaq.yml` | KST 16:35 (코스닥 장 마감 직후) | KOSDAQ |
| `deploy-pages.yml` | 스캔 성공 후 자동, 또는 관련 파일 push/수동 실행 | GitHub Pages 사이트 빌드·배포 |
