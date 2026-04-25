# Stock MA Scanner

S&P 500 + NASDAQ 100 / 코스피 주요 종목을 대상으로  
60 / 120 / 240일 이동평균선 근접 종목을 스캔하고, 분석 리포트 및 HTML 대시보드를 자동 생성합니다.

---

## 파일 구성

| 파일 | 설명 |
|---|---|
| `Search60.py` | S&P 500 + NASDAQ 100 스캐너 (~520개 종목) |
| `Search_Kospi.py` | 코스피 주요 종목 스캐너 (~80개 + KRX 동적 로드) |

---

## 실행 단계

| 단계 | 작업 | 출력 파일 |
|---|---|---|
| **1단계** | 종목 스캔 + 보조 지표 수집 | `Data_YYYYMMDD.csv` |
| **2단계** | 자동 분석 리포트 생성 | `Analysis_YYYYMMDD.md` |
| **3단계** | 한국어 번역 후 CSV 덮어쓰기 *(Search60만 해당)* | `Data_YYYYMMDD.csv` (갱신) |
| **4단계** | 인터랙티브 HTML 대시보드 생성 | `Report_YYYYMMDD.html` |

---

## 설치

```bash
# 가상환경 생성 (최초 1회)
uv venv
.venv\Scripts\activate

# 의존성 설치 (최초 1회)
uv pip install yfinance pandas lxml deep-translator requests
```

---

## 실행 방법

### S&P 500 + NASDAQ 100

```bash
# 전체 실행 (1 → 2 → 3 → 4단계)
python Search60.py

# 특정 단계만 실행
python Search60.py --stage 1        # 스캔만
python Search60.py --stage 2        # 분석 리포트만
python Search60.py --stage 3        # 번역만
python Search60.py --stage 4        # HTML 대시보드만

# 특정 날짜 파일 재처리
python Search60.py --stage 2 --date 20260425

# 강제 재스캔
python Search60.py --force

# Windows 작업 스케줄러 등록 (매일 08:05 자동 실행)
python Search60.py --setup-scheduler
python Search60.py --setup-scheduler --time 08:30
```

### 코스피

```bash
# 전체 실행 (1 → 2 → 4단계, 번역 단계 없음)
python Search_Kospi.py

# 특정 단계만 실행
python Search_Kospi.py --stage 1
python Search_Kospi.py --stage 2
python Search_Kospi.py --stage 4

# 강제 재스캔
python Search_Kospi.py --force
```

---

## 출력 파일 설명

### `Data_YYYYMMDD.csv`

| 컬럼 | 설명 |
|---|---|
| 티커 / 영문명 / 한국명 | 종목 식별 정보 |
| 테마/섹터 / 설명 | 업종 및 사업 요약 |
| 현재가 | 스캔 기준일 종가 |
| RSI(14) | Wilder's RSI (14일) |
| 52주고가 / 52주저가 | 최근 52주 고·저가 |
| 52주고점대비(%) | 현재가 vs 52주 고가 |
| 거래량비율 | 전일 거래량 / 20일 평균 |
| PER(후행) | Yahoo Finance 후행 PER |
| 목표주가 / 업사이드(%) | 애널리스트 평균 목표가 |
| MA60/120/240 | 이동평균 값 |
| MA60/120/240차이(%) | 현재가와 MA의 차이% |
| MA60/120/240근접 | ±2% 이내면 "O" 표시 |
| **추세** | 강상승 / 상승 / 중립 / 하락 / 강하락 |
| **추세점수** | 0–5점 (MA 정렬 + MA 기울기 채점) |

#### 추세 판단 기준 (5점 만점)

| 조건 | 점수 |
|---|---|
| 현재가 > MA60 | +1 |
| MA60 > MA120 | +1 |
| MA120 > MA240 | +1 |
| MA60 기울기 우상향 (20일 전 대비) | +1 |
| MA120 기울기 우상향 (20일 전 대비) | +1 |

→ 5점: 강상승 / 4점: 상승 / 3점: 중립 / 1–2점: 하락 / 0점: 강하락

### `Analysis_YYYYMMDD.md`

- **요약**: 이평선별 근접 종목 수
- **핵심 추천**: 복수 MA 수렴 · RSI · 업사이드 · PER 종합 채점 상위 10종목
- **테마별 분석**: 역발상(RSI 과매도) / 이평선 수렴 / 성장주 / 가치주
- **섹터 분석**: 근접 종목의 섹터 집중도
- **주의 종목**: RSI 과열(70+) 종목
- **전체 목록**: 60 / 120 / 240일선별 전체 근접 종목 표

### `Report_YYYYMMDD.html`

브라우저에서 직접 열기 (더블클릭 또는 `start Report_YYYYMMDD.html`)

| 기능 | 설명 |
|---|---|
| 요약 카드 | MA60 / MA120 / MA240 / 복수 수렴 종목 수 |
| 차트 | 섹터 분포 (가로 막대) + RSI 분포 히스토그램 |
| 탭 필터 | 전체 / MA60 / MA120 / MA240 / 복수MA |
| 컬럼 정렬 | 헤더 클릭으로 오름/내림 정렬 |
| 검색·필터 | 티커/종목명 검색, 섹터·RSI·**추세** 드롭다운 |
| 색상 코딩 | RSI 초록(<35) / 빨강(>65), 업사이드, PER, 추세 화살표 |
| 분석 리포트 탭 | Analysis 마크다운을 탭 전환으로 인라인 렌더링 |
| 종목 링크 | S&P500 → Yahoo Finance / 코스피 → 네이버 금융 |

---

## 자동 실행 설정

### 방법 1 — Windows 작업 스케줄러 (PC 켜져 있을 때)

```bash
python Search60.py --setup-scheduler
```

매일 **오전 08:05 KST** 에 자동 실행됩니다.

```bash
# 등록 확인
schtasks /query /tn "StockScanner_Daily"

# 삭제
schtasks /delete /tn "StockScanner_Daily" /f
```

### 방법 2 — GitHub Actions (PC 꺼져 있어도 실행)

1. GitHub에 저장소 생성 후 push
2. **Settings → Actions → General → Workflow permissions → Read and write permissions** 활성화
3. `.github/workflows/daily-scan.yml` 이 이미 포함되어 있어 자동 등록됨

- 실행 시각: 매일 **UTC 23:05 = KST 08:05**
- 스캔 결과(`Data_*.csv`, `Analysis_*.md`, `Report_*.html`)를 자동 커밋·푸시
- GitHub 저장소 **Actions** 탭에서 수동 실행(`workflow_dispatch`) 가능

---

## 코스피 종목 확장

`Search_Kospi.py` 실행 시 KRX API에서 코스피200 구성종목을 자동 로드합니다.  
API 실패 시 `TICKER_INFO`에 정의된 정적 80개 종목으로 폴백합니다.

종목 수동 추가는 파일 상단 `TICKER_INFO` 딕셔너리에 아래 형식으로 추가:

```python
"XXXXXX.KS": ("English Name", "한국명", "섹터", "사업 설명"),
```

---

## 주요 설정값

| 변수 | 기본값 | 설명 |
|---|---|---|
| `THRESHOLD_PCT` | `2.0` | 이평선 근접 판정 임계값 (%) |
| `MA_PERIODS` | `[60, 120, 240]` | 계산할 이동평균 기간 |

---

## 실행 시간 및 주의사항

| 항목 | 내용 |
|---|---|
| **실행 시간** | Search60: 약 15~20분 / Search_Kospi: 약 5~10분 |
| **번역 할당량** | `deep-translator` 일일 제한 있음. 3단계는 별도 실행 권장 |
| **데이터 지연** | Yahoo Finance 비공식 API — 간헐적 누락·오류 발생 시 자동 건너뜀 |
| **KRX API** | OTP 인증 필요로 실패 시 정적 리스트 자동 사용 |

---

## 추가 고려사항 (미구현)

| 항목 | 설명 |
|---|---|
| **병렬 처리** | `ThreadPoolExecutor`로 실행 시간 20분 → 3~5분으로 단축 가능 |
| **이메일 알림** | `smtplib`로 분석 완료 시 결과 자동 발송 |
| **히스토리 비교** | 전일 대비 MA차이% 변화 추적, "새로 진입" 종목 별도 표시 |
| **번역 캐시** | 번역된 회사명/설명을 로컬 JSON으로 저장해 API 중복 호출 방지 |
| **미국 장 휴장일 처리** | `pandas_market_calendars` 활용, 공휴일·주말 감지 후 건너뜀 |
| **주간 요약 리포트** | 월요일마다 지난 주 패턴 요약 자동 생성 |
| **코스닥 버전** | `Search_Kosdaq.py` — `.KQ` suffix 방식으로 동일 구조 적용 가능 |
