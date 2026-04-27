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
# 기본 (US 전체 파이프라인)
python Search.py

# 시장 선택
python Search.py --market us
python Search.py --market kospi
python Search.py --market kosdaq
python Search.py --market global-indices
python Search.py --market theme-proxies
python Search.py --market commodities

# 단계 선택 (기본: all)
python Search.py --market us --stage scan      # 스캔 → data/Data_YYYYMMDD.csv
python Search.py --market us --stage analyze   # 분석 → Analysis_YYYYMMDD.md
python Search.py --market us --stage translate # 번역 (US 전용)
python Search.py --market us --stage render    # HTML → Report_YYYYMMDD.html

# 기타 옵션
python Search.py --market us --workers 8       # 병렬 worker 수
python Search.py --market us --date 20260425   # 대상 날짜 지정
python Search.py --market us --force           # CSV 있어도 재스캔
python Search.py --market us --setup-scheduler # 윈도우 작업 스케줄러 등록
python Search.py --market us --setup-scheduler --time 08:30
```

## 출력 파일

| 시장 | CSV | Markdown | HTML |
|---|---|---|---|
| us | `data/Data_YYYYMMDD.csv` | `Analysis_YYYYMMDD.md` | `Report_YYYYMMDD.html` |
| kospi | `data/Data_Kospi_YYYYMMDD.csv` | `Analysis_Kospi_YYYYMMDD.md` | `Report_Kospi_YYYYMMDD.html` |
| kosdaq | `data/Data_Kosdaq_YYYYMMDD.csv` | `Analysis_Kosdaq_YYYYMMDD.md` | `Report_Kosdaq_YYYYMMDD.html` |
| global-indices | `data/Data_GlobalIndices_YYYYMMDD.csv` | … | `Report_GlobalIndices_YYYYMMDD.html` |
| theme-proxies | `data/Data_ThemeProxies_YYYYMMDD.csv` | … | `Report_ThemeProxies_YYYYMMDD.html` |
| commodities | `data/Data_Commodities_YYYYMMDD.csv` | … | `Report_Commodities_YYYYMMDD.html` |

## 사이트 대시보드

```bash
python -m market_scanner.site_builder
```

`site/`에는 GitHub Pages용 정적 대시보드가 생성됩니다. 메인 페이지는 최신 CSV/리포트 데이터를 기반으로 다음 통합 지표를 보여줍니다.

- Market Regime: 주식 breadth와 매크로 프록시를 결합한 Risk-On/Risk-Off 요약
- Equity Breadth: 주요 주식 시장의 강세/약세 종목 비율
- MA Concentration: 전체 시장에서 이동평균선 근접 신호가 몰린 정도
- RSI Temperature: 평균 RSI와 과열/과매도 종목 수
- 시장별 스냅샷: NASDAQ 100, S&P 500, Dow 30, KOSPI, KOSDAQ, 글로벌 지수, 테마 ETF, 원자재 비교
- 섹터 리더십: 추세 점수가 높은 섹터 요약

루트 `Report_*.html`이 없더라도 `data/`의 최신 CSV가 있으면 사이트 페이지를 재렌더링합니다.

상세 페이지는 좌측 종목 리스트와 우측 인사이트 패널로 구성됩니다.

- 압축형 Signal Strip
- 섹터별 상승률 Heatmap: 섹터 평균 등락률, 중앙값, 상승 종목 비율, 종목 수 표시
- Fear & Volatility 패널
- Setup Buckets
- MA Distance vs RSI Scatter
- 추세 화살표 표시: `↑↑`, `↑`, `→`, `↓`, `↓↓`
- 뉴스 브리핑 탭: 향후 뉴스 수집 캐시가 있으면 밤새 뉴스 요약 표시

티커 링크는 한국 사용자 기준으로 동작하며, 모든 시장의 Investing 링크는 `kr.investing.com`으로 연결합니다.

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
    us_static_meta.json
    kospi_static_meta.json
    kosdaq_static_meta.json
    sp500_members_cache.json
    sp500_members_manual.json
    global_indices_meta.json
    theme_proxies_meta.json
    commodities_meta.json
  templates/
    report.html
    report.css
```

## GitHub Actions

| 워크플로우 | 실행 시각 | 대상 |
|---|---|---|
| `daily-scan.yml` | KST 08:05 (장 마감 후 익일 오전) | US Market |
| `daily-scan-kospi.yml` | KST 16:05 (코스피 장 마감 직후) | KOSPI |
| `daily-scan-kosdaq.yml` | KST 16:35 (코스닥 장 마감 직후) | KOSDAQ |
