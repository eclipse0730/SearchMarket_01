# Search60 — 이동평균선 근접 종목 스캐너

S&P 500 + NASDAQ 100 (~520개 종목)을 대상으로  
60 / 120 / 240일 이동평균선 근접 종목을 스캔하고, 분석 리포트를 자동 생성합니다.

---

## 실행 단계

| 단계 | 작업 | 출력 파일 |
|---|---|---|
| **1단계** | 종목 스캔 + 보조 지표 수집 | `Data_YYYYMMDD.csv` |
| **2단계** | 자동 분석 리포트 생성 | `Analysis_YYYYMMDD.md` |
| **3단계** | 한국어 번역 후 CSV 덮어쓰기 | `Data_YYYYMMDD.csv` (갱신) |

---

## 설치

```bash
# 가상환경 생성 (최초 1회)
uv venv
.venv\Scripts\activate

# 의존성 설치 (최초 1회)
uv pip install yfinance pandas lxml deep-translator
```

---

## 실행 방법

```bash
# 전체 실행 (1 → 2 → 3단계)
python Search60.py

# 특정 단계만 실행
python Search60.py --stage 1        # 스캔만
python Search60.py --stage 2        # 분석 리포트만 (기존 CSV 필요)
python Search60.py --stage 3        # 번역만 (기존 CSV 필요)

# 특정 날짜 파일 재처리
python Search60.py --stage 2 --date 20260424

# 기존 CSV가 있어도 강제 재스캔
python Search60.py --force

# Windows 작업 스케줄러 등록 (매일 08:05 자동 실행)
python Search60.py --setup-scheduler

# 실행 시각 변경 (기본 08:05)
python Search60.py --setup-scheduler --time 08:30
```

---

## 출력 파일 설명

### `Data_YYYYMMDD.csv`
| 컬럼 | 설명 |
|---|---|
| 티커 / 영문명 / 한국명 | 종목 식별 정보 |
| 테마/섹터 / 설명 | 업종 및 사업 요약 |
| 현재가($) | 스캔 기준일 종가 |
| RSI(14) | Wilder's RSI (14일) |
| 52주고가($) / 52주저가($) | 최근 52주 고·저가 |
| 52주고점대비(%) | 현재가 vs 52주 고가 |
| 거래량비율(전일/20일평균) | 전일 거래량 / 20일 평균 |
| PER(후행) | Yahoo Finance 후행 PER |
| 목표주가($) / 업사이드(%) | 애널리스트 평균 목표가 |
| MA60/120/240($) | 이동평균 값 |
| MA60/120/240차이(%) | 현재가와 MA의 차이% |
| MA60/120/240근접 | ±2% 이내면 "O" 표시 |

### `Analysis_YYYYMMDD.md`
- **요약**: 이평선별 근접 종목 수
- **핵심 추천**: 복수 MA 수렴 · RSI · 업사이드 · PER 종합 채점 상위 10종목
- **테마별 분석**: 역발상(RSI 과매도) / 이평선 수렴 / 성장주 / 가치주
- **섹터 분석**: 근접 종목의 섹터 집중도
- **주의 종목**: RSI 과열(70+) 종목
- **전체 목록**: 60 / 120 / 240일선별 전체 근접 종목 표

---

## 자동 실행 설정 (Windows)

### 방법 1 — 명령어 한 줄
```bash
python Search60.py --setup-scheduler
```
매일 **오전 08:05 KST** 에 자동 실행됩니다.  
(미국 동부시간 기준 장 종료: 오전 06:00 KST → 08:05에 실행하면 전일 종가 반영)

### 방법 2 — 수동 등록 (작업 스케줄러 GUI)
1. Windows 검색 → "작업 스케줄러" 실행
2. 작업 만들기 → 트리거: 매일 08:05
3. 동작: 프로그램 시작
   - 프로그램: `C:\Users\Yeop\Desktop\vscode\Search60\.venv\Scripts\python.exe`
   - 인수: `C:\Users\Yeop\Desktop\vscode\Search60\Search60.py`
   - 시작 위치: `C:\Users\Yeop\Desktop\vscode\Search60`

### 스케줄러 확인 / 삭제
```bash
# 등록 확인
schtasks /query /tn "StockScanner_Daily"

# 삭제
schtasks /delete /tn "StockScanner_Daily" /f
```

---

## 주요 설정값 (Search60.py 상단)

| 변수 | 기본값 | 설명 |
|---|---|---|
| `THRESHOLD_PCT` | `2.0` | 이평선 근접 판정 임계값 (%) |
| `MA_PERIODS` | `[60, 120, 240]` | 계산할 이동평균 기간 |

---

## 추가 고려사항

### 현재 미구현 — 필요 시 추가 가능

| 항목 | 설명 |
|---|---|
| **병렬 처리** | `ThreadPoolExecutor`로 전체 실행 시간을 20분 → 3~5분으로 단축 가능 |
| **이메일 알림** | `smtplib`로 분석 완료 시 결과 자동 발송 |
| **히스토리 비교** | 전일 대비 MA차이% 변화 추적, "새로 진입" 종목 별도 표시 |
| **미국 장 휴장일 처리** | 공휴일·주말 감지 후 실행 건너뜀 (`pandas_market_calendars` 활용) |
| **번역 캐시** | 이미 번역한 회사명/설명을 로컬 JSON으로 저장해 API 중복 호출 방지 |
| **임계값 외부 설정** | `config.json`으로 THRESHOLD_PCT, 알림 조건 등 분리 |
| **오래된 파일 정리** | N일 이상 된 Data/Analysis 파일 자동 삭제 |
| **주간 요약 리포트** | 월요일마다 지난 주 패턴 요약 자동 생성 |
| **알림 조건 필터** | RSI < 30 + MA 지지, 업사이드 > 30% 등 특정 조건 충족 시만 알림 |

### 주의사항
- **번역 할당량**: `deep-translator`(Google Translate) 일일 할당량 제한 있음. 500개 이상 번역 시 간헐적 실패 가능 → 3단계 번역은 별도 실행 권장
- **데이터 지연**: Yahoo Finance는 비공식 API로 가끔 데이터 누락·오류 발생. 해당 종목은 자동 건너뜀
- **ANSS**: 야후 파이낸스에서 상장폐지 처리됨 — 자동 제외
- **실행 시간**: 약 15~20분 소요 (네트워크 속도에 따라 변동)
