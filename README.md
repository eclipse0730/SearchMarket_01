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
python Search.py --market us --stage scan      # 스캔 → Data_YYYYMMDD.csv
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
| us | `Data_YYYYMMDD.csv` | `Analysis_YYYYMMDD.md` | `Report_YYYYMMDD.html` |
| kospi | `Data_Kospi_YYYYMMDD.csv` | `Analysis_Kospi_YYYYMMDD.md` | `Report_Kospi_YYYYMMDD.html` |
| kosdaq | `Data_Kosdaq_YYYYMMDD.csv` | `Analysis_Kosdaq_YYYYMMDD.md` | `Report_Kosdaq_YYYYMMDD.html` |
| global-indices | `Data_Globalindices_YYYYMMDD.csv` | … | `Report_Globalindices_YYYYMMDD.html` |
| theme-proxies | `Data_Themeproxies_YYYYMMDD.csv` | … | `Report_Themeproxies_YYYYMMDD.html` |
| commodities | `Data_Commodities_YYYYMMDD.csv` | … | `Report_Commodities_YYYYMMDD.html` |

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
