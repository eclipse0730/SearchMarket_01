# SearchMarket PRD v2 — 데이터 · 스코어링 엔진

> **버전**: v2.0 (Data/Scoring Engineering PRD)
> **작성일**: 2026-05-20
> **대상 코드베이스**: `Search.py` + `market_scanner/` (PostgreSQL 16 기반 데이터 파이프라인)
> **선행 문서**: [stock_scanner_prd_v1.1.md](stock_scanner_prd_v1.1.md) — webapp 비전 문서(보존). 본 문서는 그 후속으로, 현재 실제 구현된 **데이터·지표·스코어링 엔진**을 정의한다. UI/페이지 사양은 v1.1을 따른다.

---

## 0. 변경 이력

| 버전 | 일자 | 변경 |
|---|---|---|
| v1.0 | 2026-04-30 | 초기 PRD (webapp + FastAPI + React MVP 비전) — [stock_scanner_prd_v1.1.md](stock_scanner_prd_v1.1.md) |
| v1.1 | 2026-04-30 | UI/페이지 구조 보강 |
| **v2.0** | **2026-05-20** | **데이터/스코어링 엔진 PRD로 분리. 현재 CLI + PostgreSQL 파이프라인의 as-is 명세 + 가까운 to-be 로드맵** |

---

## 1. 제품 비전 및 범위

### 1.1 비전

미국·한국·글로벌 자산을 동일한 파이프라인으로 수집→지표화→스코어링하여, **장 마감 종가 기준의 신뢰 가능한 종목 발굴 데이터셋**을 매일 PostgreSQL에 적재한다. 상위 응용(웹 대시보드, AI 리포트, 알림 등)은 이 데이터셋을 단일 소스로 사용한다.

### 1.2 본 PRD가 다루는 범위 (In Scope)

- 데이터 수집 (price, fundamentals, investor flows, macro, news cache)
- 일봉 기술 지표 계산 (RSI, MA, MACD, 볼린저, ATR, 변동성, 캔들, 추세)
- 8개 전략 스코어 + 종합 점수 + 시장/섹터 스냅샷
- PostgreSQL 스키마 및 운영 (Neon / 로컬 Docker 듀얼 환경)
- 실행 인터페이스 (CLI: `Search.py`, 로컬 admin 서버, GitHub Actions)
- 데이터 품질 신호 (`data_quality_flags`, `risk_flags`, `setup_tags`)

### 1.3 본 PRD가 다루지 **않는** 범위 (Out of Scope)

- 웹 UI / React 프론트엔드 사양 → v1.1 PRD
- AI 시장 요약 프롬프트 / LLM 통합 세부 사양 → 별도 PRD
- 사용자 인증 / 권한 / 알림 채널 (Slack, Email)
- 백테스트 / 포트폴리오 관리 / 주문 연동

### 1.4 목표 사용자

| 페르소나 | 역할 | 본 데이터셋 활용 |
|---|---|---|
| 데이터 엔지니어 (1차 사용자) | 파이프라인 운영 | CLI / admin / Actions 로그로 수집 안정성 모니터링 |
| 분석가 / 리서처 | SQL 직접 조회 | DBeaver로 `scan_results`, `daily_indicators` 질의 |
| 후속 응용 개발자 | webapp / AI 리포트 빌더 | 본 DB를 read-only로 소비 |
| 소규모 투자 커뮤니티 (5–50명) | 최종 산출물 소비 | 향후 webapp을 통해 접근 |

---

## 2. 시스템 개요

### 2.1 아키텍처 다이어그램 (텍스트)

```
[External Sources]                          [Pipeline (Search.py CLI)]              [PostgreSQL 16]              [Consumers]
─────────────────                          ──────────────────────────              ───────────────              ────────────
 yfinance               ─┐               ┌─ init          (schema)              ┌─ markets                   ┌─ admin server (8765)
 FinanceDataReader      ─┤               ├─ refresh       (universe)            ├─ instruments              │   - 적재 모니터링
 pykrx / KRX            ─┤   collectors  ├─ price         (OHLCV)               ├─ universe_*               │   - 수집 트리거
 Naver Finance          ─┼──────────────►├─ fundamentals  (PER/PBR/ROE)         ├─ collection_runs          ├─ webapp (v1.1, 미구현)
 KOFIA FreeSIS          ─┤               ├─ flows         (KR 투자자별 수급)     ├─ daily_prices            ├─ AI 리포트 (미구현)
 FRED                   ─┤               ├─ macro         (rates/FX/etc)        ├─ daily_indicators         └─ SQL 직접 조회 (DBeaver)
 CoinGecko              ─┤               ├─ news          (cache)               ├─ instrument_fundamentals
 alternative.me (FNG)   ─┘               ├─ indicators    (RSI/MA/MACD/...)     ├─ daily_investor_flows
                                          ├─ screen        (8 strategy scores)   ├─ daily_macro
                                          └─ scan / all    (price→ind→screen)    ├─ scan_results
                                                                                  ├─ market_snapshots
                                          GitHub Actions (KST 08:05 / 16:05 / 16:35 / 08:20)  ├─ sector_snapshots
                                                                                  ├─ news_items / instrument_news
                                                                                  └─ generated_reports
```

### 2.2 핵심 설계 원칙

1. **PostgreSQL = canonical store.** CSV/JSON 산출물은 export 또는 fallback seed로만 사용한다.
2. **단계별 분리.** price → indicators → screen 은 분리된 명령이며, 각 단계는 직전 단계의 DB 출력을 읽는다. 한 단계 실패가 다음 단계 실행을 가로막지 않도록 한다.
3. **하나의 가격 소스 = 하나의 행.** `daily_prices`의 PK는 `(instrument_id, trade_date, source_provider)`. 같은 종목·날짜라도 FDR/yfinance 값을 비교 저장 가능.
4. **지표는 운영 기준 1개 + 출처 메모.** `daily_indicators`의 PK는 `(instrument_id, trade_date)`. 사용한 가격 출처는 `price_source_provider`에 남긴다.
5. **시장/유니버스 명시.** `NULL` 대신 `kospi`, `kospi200`, `us:all` 같은 명시 키를 쓴다. snapshot 계열의 `universe_key`는 `NOT NULL`.
6. **실행 추적은 `collection_runs`.** 모든 단계는 run row를 만들고, 결과 행은 `run_id`로 추적한다.
7. **DB 환경 우선순위.** `--database-url 인수` > `환경변수 DATABASE_URL` > 로컬 Docker 기본값.

---

## 3. 데이터 모델

### 3.1 시장(Market) 정의

본 시스템이 처리하는 7개 시장 키:

| `market_key` | 라벨 | 국가 | 통화 | 표준 유니버스 | 비고 |
|---|---|---|---|---|---|
| `us` | US Market | US | USD | `nasdaq`, `nyse`, `amex`, `nasdaq100`, `sp500`, `dow30` | `refresh us` 한 번에 6개 유니버스 동시 갱신 |
| `kospi` | KOSPI | KR | KRW | `kospi`, `kospi100`, `kospi200` | FDR 우선, Naver fallback |
| `kosdaq` | KOSDAQ | KR | KRW | `kosdaq`, `kosdaq150` | FDR 우선, Naver fallback |
| `global-indices` | 글로벌 지수 | — | — | 35개 지수 | JSON 메타가 원본 |
| `sector-etfs` | 섹터 ETF | US | USD | 11 GICS 섹터 + VNQ 리츠 보조 프록시 | JSON 메타가 원본 |
| `theme-proxies` | 테마 ETF | US | USD | 13개 ETF (`SOXX`, `BOTZ`, ... `TLT`) | US 스캔 결과에서 파생 |
| `commodities` | 원자재 | — | — | 27개 종목 | JSON 메타가 원본 |

**시장 키와 유니버스 키는 다르다.** 시장은 거래 규칙·통화·시간대 정의 단위이고, 유니버스는 분석/필터 멤버십 단위다. `kr`은 CLI 편의용 별칭이며, `home_market_key()`가 `kr` → `kospi`로 정규화한다 ([market_scanner/domain/market_policy.py](../market_scanner/domain/market_policy.py)).

### 3.2 PostgreSQL 테이블 카탈로그

총 16개 테이블. 자세한 컬럼 명세는 [docs/database_table_guide.md](database_table_guide.md), DDL은 [docs/database_schema_v1.sql](database_schema_v1.sql).

| # | 테이블 | 역할 | PK |
|---|---|---|---|
| 1 | `markets` | 시장 마스터 | `market_key` |
| 2 | `instruments` | 종목/ETF/지수/원자재 마스터 | `instrument_id` (BIGSERIAL) |
| 3 | `universe_definitions` | 유니버스 정의 | `universe_key` |
| 4 | `universe_memberships` | 유니버스 멤버십 (이력) | `(universe_key, instrument_id, effective_from)` |
| 5 | `collection_runs` | 실행 로그 | `run_id` (UUID) |
| 6 | `daily_prices` | 일봉 OHLCV | `(instrument_id, trade_date, source_provider)` |
| 7 | `daily_indicators` | 기술 지표 (운영 기준 1개) | `(instrument_id, trade_date)` |
| 8 | `instrument_fundamentals` | 재무/밸류에이션 | `(instrument_id, as_of_date, source_provider)` |
| 9 | `daily_investor_flows` | KR 종목별 기관/외국인/개인 수급 | `(instrument_id, trade_date, source_provider)` |
| 10 | `scan_results` | 스캔 최종 결과 | `(run_id, instrument_id)` |
| 11 | `daily_macro` | 매크로 시계열 | `(indicator_code, trade_date, source_provider)` |
| 12 | `market_snapshots` | 시장 요약 | `(market_key, trade_date, universe_key)` |
| 13 | `sector_snapshots` | 섹터 요약 | `(market_key, trade_date, universe_key, sector)` |
| 14 | `news_items` | 뉴스 원문 | `news_id`, `url` UNIQUE |
| 15 | `instrument_news` | 종목↔뉴스 연결 | `(instrument_id, news_id)` |
| 16 | `generated_reports` | 산출물 메타 | `report_id` |

### 3.3 `asset_type` 분류 (instruments)

`common_stock`, `preferred_stock`, `etf`, `etn`, `reit`, `spac`, `fund`, `index`, `commodity`, `other`. 한국 시장 기본 스캔은 `asset_type='common_stock'`로 제한한다 (Naver fallback에 섞이는 비표준 상품 회피).

### 3.4 `universe_memberships` 시점 정책

- `effective_from`: 편입 시작일
- `effective_to`: NULL이면 현재 편입
- 동일 (`universe_key`, `instrument_id`)의 과거 편입 이력 보존 → S&P 500 구성 변경, KOSPI 200 교체 추적 가능
- `refresh --reset`은 해당 범위 멤버십만 삭제 후 재생성. `instruments`, 가격, 지표, 스캔, 뉴스, 실행 로그는 보존한다.

---

## 4. 데이터 수집 사양

### 4.1 수집 단계 일람

| 단계 | CLI | 적재 대상 테이블 | 핵심 출처 | 빈도 |
|---|---|---|---|---|
| 1. 스키마 초기화 | `init` | (DDL 적용) | — | 1회/스키마 변경 |
| 2. 종목 마스터 | `refresh <market>` | `instruments`, `universe_memberships`, `collection_runs` | FDR, Wikipedia, Naver, JSON 메타 | 일 1회 또는 멤버십 변경 시 |
| 3. 가격 | `price <market>` | `daily_prices`, `collection_runs` | US: yfinance batch / KR: FDR | 일 1회 (장 마감 후) |
| 4. 재무 | `fundamentals <market>` | `instrument_fundamentals` | auto: US=Yahoo / KR=Naver→FDR→Yahoo | 주 1회 또는 stale 시 |
| 5. 한국 수급 | `flows <kr/kospi/kosdaq>` | `daily_investor_flows` | pykrx / KRX | 일 1회 |
| 6. 매크로 | `macro` | `daily_macro` | FRED, yfinance, pykrx, KOFIA, CoinGecko, alternative.me | 일 1회 |
| 7. 지표 | `indicators <market>` | `daily_indicators` | (DB 내 daily_prices) | price 직후 |
| 8. 스크리닝 | `screen <market>` | `scan_results`, `market_snapshots`, `sector_snapshots` | (DB) | indicators 직후 |
| 9. 뉴스 캐시 | `news <market>` | `news_items`, `instrument_news` | Finnhub, RSS | 선택 |
| 묶음 | `scan` / `all` | (3→7→8) | — | — |

### 4.2 수집 출처별 정책

**US 가격** — yfinance batch download만 사용. 긴 기간 재수집도 동일 batch 경로. `--workers`는 yfinance 내부 download thread 상한.

**KR 가격** — FinanceDataReader. 정적 JSON fallback (`kospi_static_meta.json` 등)은 제거됨. FDR 실패 시 Naver Finance fallback.

**KR 수급** — pykrx 1.2 계열은 KRX 로그인 정책에 따라 `.env`의 `KRX_ID` / `KRX_PW` 필요. 기본 거래대금 수급, `--include-volume`으로 거래량 수급 병기.

**Fundamentals** — `--source auto` 기본. US는 Yahoo, KR은 Naver→FDR→Yahoo 순서로 채움. `--workers` 기본 2, US/Yahoo는 최대 4, KR Naver/FDR은 최대 8.

**매크로** — `.env`의 `FRED_API_KEY` 필요 (FRED 지표). 증분 수집은 각 지표의 마지막 수집일 다음 날부터 오늘까지. `--days-back` 기본 90 (이력 없는 지표의 초기 소급 기간).

### 4.3 매크로 지표 카탈로그

| 카테고리 | 코드 | 출처 |
|---|---|---|
| 금리 | `SOFR`, `US_FFR`, `US_2Y`, `US_10Y`, `US_30Y`, `US_SPREAD_2S10S`, `US_SPREAD_3M10Y`, `HY_OAS`, `IG_OAS`, `FED_RRP`, `FED_BS` | FRED |
| KR 금리 | `KR_10Y`, `KR_INTERBANK_3M`, `KR_CALL_RATE`, `KR_DISCOUNT_RATE` | FRED |
| 주가 지수 | `SP500`, `NASDAQ100`, `KOSPI`, `KOSDAQ` | yfinance |
| FX | `USDKRW`, `EURUSD`, `USDJPY`, `USDCNY`, `GBPUSD`, `AUDUSD`, `NZDUSD`, `USDCAD`, `USDCHF`, `USDSGD`, `USDSEK`, `USDNOK`, `USDMXN`, `DXY` | yfinance |
| 원자재 | `WTI`, `GOLD`, `SILVER`, `NATGAS`, `COPPER` | yfinance |
| 변동성 | `VIX`, `VVIX` | yfinance |
| 크립토 | `BTC_USD`, `ETH_USD`, `CRYPTO_TOTAL_MCAP`, `CRYPTO_FNG` | yfinance / CoinGecko / alternative.me |
| KR 수급 (시장 단위) | `KR_KOSPI_FOREIGN_NET_BUY_VALUE`, `KR_KOSPI_INSTITUTION_NET_BUY_VALUE`, `KR_KOSDAQ_FOREIGN_NET_BUY_VALUE`, `KR_KOSDAQ_INSTITUTION_NET_BUY_VALUE` | pykrx/KRX |
| KR 공매도 | `KR_KOSPI_SHORT_SELL_VALUE`, `KR_KOSPI_SHORT_BALANCE_VALUE`, `KR_KOSDAQ_SHORT_SELL_VALUE`, `KR_KOSDAQ_SHORT_BALANCE_VALUE` | pykrx/KRX |
| KR 유동성 | `KR_CUSTOMER_DEPOSIT_VALUE`, `KR_CREDIT_BALANCE_VALUE` (단위: 백만원) | KOFIA FreeSIS |

### 4.4 실행 추적 (`collection_runs`)

모든 수집/계산 단계는 row를 만든다.

- `run_type` ∈ {`universe`, `prices`, `indicators`, `scan`, `news`, `render`, `backfill`, `fundamentals`, `investor_flows`}
- `status` ∈ {`running`, `success`, `partial`, `failed`, `cancelled`}
- `params` JSONB: 실행 파라미터 (`refresh`는 멤버십 비교 요약과 추가/삭제/순위 변경 샘플 포함)
- `error_samples` JSONB: 실패 샘플 (admin 화면이 표시)
- `git_sha`: 실행 시점 코드 버전

---

## 5. 지표 계산 사양 (`daily_indicators`)

소스: [market_scanner/analysis/indicators.py](../market_scanner/analysis/indicators.py).

### 5.1 지표 카테고리

| 카테고리 | 컬럼 |
|---|---|
| RSI | `rsi14`, `rsi14_prev`, `rsi14_change`, `rsi14_ma5`, `rsi2`, `rsi5`, `rsi30` |
| 이동평균 | `ma5`, `ma20`, `ma60`, `ma120`, `ma240` |
| 이격률 | `diff_5_pct`, `diff_20_pct`, `diff_60_pct`, `diff_120_pct`, `diff_240_pct` |
| 이평선 근접 (`abs(diff_pct) ≤ 2.0%`) | `near_5`, `near_20`, `near_60`, `near_120`, `near_240` |
| MA 정배열 | `ma_alignment_score` (정수), `is_ma_bullish_alignment` (완전 정배열) |
| MA 기울기 | `ma20_slope_pct`, `ma60_slope_pct` |
| MACD | `macd`, `macd_signal`, `macd_hist`, `macd_state`, `macd_cross`, `macd_hist_change` |
| 볼린저 | `bollinger_width_pct`, `bollinger_percent_b` |
| 52주 | `high_52w`, `low_52w`, `from_high_pct`, `from_low_pct` |
| 20/60 거래일 박스 | `high_20d`, `low_20d`, `high_60d`, `low_60d`, `breakout_*`, `close_position_in_range_*` |
| 거래량/거래대금 | `volume_ratio`, `value_traded`, `value_ratio_20d`, `volume_avg20`, `volume_avg60` |
| 수익률 | `return_5d`, `return_20d`, `return_60d`, `return_120d`, `return_240d` |
| ATR / 변동성 | `atr14`, `atr14_pct`, `volatility_20d`, `volatility_60d` |
| 캔들 | `change_pct`, `gap_pct`, `candle_body_pct`, `candle_range_pct`, `upper_shadow_pct`, `lower_shadow_pct`, `candle_type` |
| 추세 | `trend`, `trend_score` |

### 5.2 핵심 정의

- **52주 고/저 (`high_52w`/`low_52w`)** — trailing 일봉의 High/Low (종가가 아님)
- **`breakout_20d`/`breakout_60d`** — 종가가 직전 20/60거래일 High를 돌파
- **`breakout_high_20d`/`breakout_high_60d`** — 당일 High가 직전 20/60거래일 High를 돌파 (장중 돌파)
- **`value_traded`** — `close × volume` (당일 거래대금)
- **`value_ratio_20d`** — `value_traded / 최근 20거래일 평균 value_traded`
- **`macd_state`** ∈ {`Bullish`, `Positive`, `Improving`, `Bearish`, `Unknown`}
- **`candle_type`** ∈ {`Unknown`, `Flat`, `Long Lower Doji`, `Long Upper Doji`, `Doji`, `Bullish Reversal`, `Bearish Rejection`, `Strong Bullish`, `Strong Bearish`, `Bullish`, `Bearish`}

### 5.3 수치 안정성

- 가격 소스 극단값으로 DB numeric 범위를 넘는 지표값은 해당 컬럼만 `NULL` 저장. 나머지 지표 저장은 계속 진행.
- MA/볼린저 계산 시 데이터 부족 (lookback < period) → 해당 컬럼 `NULL`.

### 5.4 스키마 확장 노트

현재는 `ma5/20/60/120/240` 컬럼이 고정되어 있다. MA 기간을 자주 바꾸거나 사용자별 indicator profile을 지원해야 할 때는 `indicator_values(instrument_id, trade_date, indicator_code, value, profile)` long-form 테이블로 분리한다. **본 v2 PRD에서는 wide-form 유지.**

---

## 6. 스코어링 사양 (`scan_results`)

소스: [market_scanner/analysis/screener.py](../market_scanner/analysis/screener.py).

### 6.1 전략별 점수 (8개)

각 점수는 0–100 범위. `_DEFAULT_SETTINGS`는 [screener.py:50-67](../market_scanner/analysis/screener.py#L50-L67)에서 정의.

| 점수 컬럼 | 가중치 | 정의 |
|---|---:|---|
| `pullback_score` | 22% | 상승 추세 안에서 20/60일선 근처 조정받는 눌림목 |
| `breakout_score` | 22% | 신고가/고점 돌파 + MACD/RSI/거래대금 동반 |
| `box_breakout_score` | 12% | 20/60일 박스권 내 종가 위치와 돌파 후보 |
| `trend_quality_score` | 14% | MA 정배열, MA 기울기, 장기 수익률, 52주 위치 |
| `theme_score` | 10% | 섹터 수익률, MA20 상회 비율, 거래대금 유입, 돌파 비율, 평균 추세 |
| `fundamental_score` | 8% | 절대 PER/PBR/ROE/매출성장률 40% + 업종 내 상대 점수 60% |
| `flow_score` | 7% | 거래대금, 평균 거래량, 거래대금 비율, 거래량 비율 (KR은 `smart_money_score` 60% 가산) |
| `reversal_score` | 5% | 과매도 구간 RSI/MACD/캔들 반전 신호 |

**합계 100%.**

### 6.2 합산 식

```
raw_composite_score = Σ(score_i × weight_i)
risk_penalty        = risk_score × 0.35
composite_score     = clamp(raw_composite_score − risk_penalty, 0, 100)
                       → 유동성 부족: cap 65
                       → 심한 하락 추세: cap 70
```

- `overbought_score`는 가중치에 직접 들어가지 않는다. `risk_score`와 태그 판단에 사용.
- `action_score` = `max(pullback, breakout, box_breakout, reversal)` — 4개 액션 전략 중 최고.
- `quality_score` = `mean(trend_quality, fundamental, theme, flow)`.
- `setup_label` — 가장 강한 전략 라벨 (예: `이평선 눌림`, `신고가/고점 돌파`, `중립/관망`).

### 6.3 안정화 (Shrinkage)

소수 종목 섹터의 노이즈 억제:

- **`theme_score`** — 섹터 구성 종목 < 10 개일 때: `50 + (raw_theme − 50) × min(sector_count/10, 1)` → 중립값(50)으로 수축.
- **`fundamental_score`의 업종 상대 점수** — 같은 섹터 유효 재무 데이터 < 10 개일 때 동일 공식. PER/PBR 0 이하 값은 상대 비교에서 제외.

### 6.4 KR 수급 점수 (smart money)

`daily_investor_flows` 데이터가 있을 때 KR 시장에 한해:

- `smart_money_ratio_5d = (최근 5거래일 외국인+기관 순매수 거래대금) / (20일 평균 거래대금)`
- `smart_money_score`: 위 비율을 0–100으로 정규화
- `flow_score`에 60% 가산. 수급 데이터 결측/stale 시 기존 가격·거래량 기반 `flow_score` 유지 + `data_quality_flags`에 결측/stale 기록.

### 6.5 출력 컬럼 (요약)

`scan_results`에 저장되는 핵심 컬럼:

| 컬럼군 | 컬럼 |
|---|---|
| 식별 | `run_id`, `instrument_id`, `market_key`, `universe_key`, `trade_date` |
| 점수 (호환 별칭 포함) | `chart_score`(=trend_quality), `technical_score`(=action), `fundamental_score`, `theme_score`, `flow_score`, `composite_score`, `pullback_score`, `breakout_score`, `box_breakout_score`, `trend_quality_score`, `reversal_score`, `overbought_score`, `risk_score`, `raw_composite_score`, `action_score`, `quality_score` |
| 셋업 | `setup_label`, `pullback_ma_period`, `setup_tags[]`, `risk_flags[]`, `data_quality_flags[]` |
| 스냅샷 | `close_price`, `change_pct`, `value_traded`, `rsi14` |
| KR 수급 | `foreign_net_buy_1d/5d/20d`, `institution_net_buy_1d/5d/20d`, `smart_money_ratio_5d`, `smart_money_score`, `sector_rank` |
| 메타 | `rank_no`, `summary_payload` JSONB |

**호환 별칭 주의:** `chart_score`는 실제 의미가 `trend_quality_score`, `technical_score`는 `action_score`. DB 스키마 호환 위해 컬럼명은 유지한다.

### 6.6 태그 사전

| 태그 종류 | 예시 값 |
|---|---|
| `setup_tags` | `pullback_20`, `pullback_60`, `pullback_120`, `pullback_240`, `breakout`, `box_breakout`, `oversold_reversal`, `theme_strong`, `high_value_traded` |
| `risk_flags` | `overbought`, `low_liquidity`, `severe_downtrend` |
| `data_quality_flags` | `missing_investor_flow`, `stale_investor_flow`, `missing_fundamentals`, `missing_sector`, `low_liquidity` |

---

## 7. 시장 / 섹터 요약 (`market_snapshots`, `sector_snapshots`)

스크리닝 마지막에 자동 생성. 빌더: [market_scanner/domain/snapshots.py](../market_scanner/domain/snapshots.py).

### 7.1 `market_snapshots`

(`market_key`, `trade_date`, `universe_key`) PK. `universe_key`는 **NOT NULL** — 시장 전체 요약도 `kospi:all` 같은 명시 키 사용.

핵심 컬럼: `total_count`, `scanned_count`, `success_count`, `failed_count`, `advance_count`, `decline_count`, `unchanged_count`, `avg_change_pct`, `median_change_pct`, `avg_rsi14`, `bullish_breadth_pct`, `avg_composite_score`, `market_score`, `regime`, `risk_level`, `macro_payload` (JSONB), `ai_summary` (텍스트, AI가 채움).

### 7.2 `sector_snapshots`

(`market_key`, `trade_date`, `universe_key`, `sector`) PK. `universe_key` **NOT NULL**.

핵심 컬럼: `instrument_count`, `advance_count`, `decline_count`, `avg_change_pct`, `median_change_pct`, `avg_rsi14`, `avg_composite_score`, `top_instruments` (JSONB).

웹 대시보드의 섹터 히트맵 / 시장 상태 카드의 원천.

---

## 8. 실행 인터페이스

### 8.1 `Search.py` CLI 명령 일람

| 명령 | 인자 | 주요 옵션 |
|---|---|---|
| `init` | — | `--database-url` |
| `refresh` | `[market]` (생략 시 기본 시장 전체) | `--universe`, `--date`, `--reset` |
| `price` | `market` | `--date`, `--from`, `--to`, `--limit`, `--workers`, `--force` |
| `retry-price` | `market` | `--run-id` |
| `fundamentals` | `market` | `--all`, `--stale-days`(7), `--limit`, `--workers`(2), `--source`(auto/yahoo/naver/fdr) |
| `flows` | `kr`/`kospi`/`kosdaq` | `--date`, `--from`, `--to`, `--limit`, `--force`, `--include-volume` |
| `indicators` | `market` | `--date`, `--from`, `--to`, `--limit` |
| `screen` | `market` | `--universe`, `--date` |
| `scan` | `market` | `--universe`, `--date`, `--limit`, `--workers` → price + indicators + screen |
| `all` | `market` | (scan과 동일. alias) |
| `news` | `market` | `--universe`, `--date`, `--symbols`(50), `--items`(3), `--workers`(4), `--provider`(all/auto/finnhub/rss) |
| `macro` | — | `--date`, `--from`, `--to`, `--days-back`(90) |
| `counts` | — | — |
| `admin` | — | `--host`(127.0.0.1), `--port`(8765) |
| `names` | `kospi`/`kosdaq` | `--all`, `--limit`, `--delay`(0.3) |

전부 `--database-url`로 DB 오버라이드 가능.

### 8.2 GitHub Actions 스케줄

| Workflow | KST | 대상 |
|---|---|---|
| `daily-scan.yml` | 08:05 | US Market (수동 트리거 기본) |
| `daily-scan-overview.yml` | 08:20 | 글로벌 지수, 섹터 ETF, 테마 ETF, 원자재 |
| `daily-scan-kospi.yml` | 16:05 | `kr --universe kospi` |
| `daily-scan-kosdaq.yml` | 16:35 | `kr --universe kosdaq` |

Actions에서 사용하는 환경변수: `TZ=Asia/Seoul`, `DATABASE_URL=${{ secrets.DATABASE_URL }}`. **현재 Actions는 조회만 (yml 수정) 가능**하며, 웹에서 trigger/commit하는 워크플로우 추가는 권한 정책 합의 후 별도 단계로 추가한다.

### 8.3 로컬 admin 서버

`uv run python Search.py admin` → `http://127.0.0.1:8765`

- 최근 7일 price/indicator/scan_result/flows 적재 건수
- refresh 변경 이력 (멤버십 추가/삭제/순위 변경)
- `collection_runs` 실패 샘플 (symbol + 종목명)
- 수집 버튼: `Search.py` 명령을 로컬에서 실행. price/flows 버튼은 `--force` 포함
- 실행 중 작업: `/api/jobs` JSON으로 경과 시간 + 최근 로그 동적 갱신

### 8.4 DB 환경 전환

```
우선순위: --database-url 인수 > 환경변수 DATABASE_URL (.env) > 로컬 Docker 기본값
                                                          (postgresql://searchmarket:searchmarket@localhost:5433/searchmarket)
```

- **Neon DB**: `.env`에 Neon URL 설정. `.gitignore`에 포함되어 커밋되지 않음
- **로컬 Docker**: `docker compose up -d postgres` 후 환경변수 없이 실행
- 일회성 오버라이드: `--database-url` 인수

### 8.5 환경 변수

| 변수 | 용도 | 필수 |
|---|---|---|
| `DATABASE_URL` | PostgreSQL 접속 문자열 | 권장 (없으면 로컬 Docker 기본값) |
| `FRED_API_KEY` | FRED 매크로 지표 수집 | macro 단계에서 필요 |
| `KRX_ID`, `KRX_PW` | pykrx 1.2 KRX 로그인 | flows 단계에서 필요할 수 있음 |
| `FINNHUB_API_KEY` | Finnhub 뉴스 수집 | news --provider finnhub에서 필요 |

---

## 9. 비기능 요구사항

### 9.1 성능 / 처리량

| 항목 | 목표 |
|---|---|
| US 일일 가격 수집 (S&P 500) | 단일 `price us --universe sp500` 5분 이내 (yfinance batch) |
| KR 일일 가격 수집 (KOSPI 보통주 전체) | 10분 이내 (FDR) |
| KR 수급 수집 (KOSPI 일일) | 15분 이내 (pykrx 종목별 rate limit 고려) |
| 지표 계산 (시장 단위) | 2분 이내 |
| 스크리닝 (시장 단위) | 1분 이내 |
| 전체 일일 파이프라인 (`all kr --universe kospi`) | 30분 이내 |

### 9.2 안정성

- 한 단계 실패가 다음 단계 실행을 막지 않는다. `collection_runs.status='partial'`로 기록하고 후속 단계 진행.
- 가격 수집 실패 종목은 `retry-price` 명령으로 재시도 가능 (`run-id` 지정).
- 지표 계산은 가격 데이터가 부족하거나 numeric overflow일 때 해당 컬럼만 `NULL`. 다른 종목/컬럼은 계속 진행.

### 9.3 데이터 품질

- `data_quality_flags`로 결측·stale 상태를 출력에 노출 (`missing_investor_flow`, `stale_investor_flow`, `missing_fundamentals`, `missing_sector`, `low_liquidity`).
- `collection_runs.error_samples` JSONB에 실패 케이스 보존. admin 화면이 표시.
- 가격 소스 비교: 같은 종목·날짜에 FDR/yfinance 값을 병행 저장 가능 (`daily_prices` PK 설계).

### 9.4 관측성

- 모든 단계의 `run_id`로 산출물 추적 (`daily_prices.run_id`, `daily_indicators.run_id`, `scan_results.run_id`, ...)
- `collection_runs.git_sha`로 실행 시점 코드 버전 기록
- admin 페이지에서 최근 7일 적재 건수 모니터링

### 9.5 보안 / 비밀 관리

- `.env`는 `.gitignore`에 포함. 커밋되지 않음
- Neon URL, FRED key, KRX 계정, Finnhub key 모두 `.env` 또는 GitHub Secrets로 관리
- admin 서버는 `127.0.0.1` 바인딩 기본 (로컬 전용). 외부 노출 금지

### 9.6 의존성 (requirements.txt)

```
yfinance
pandas
lxml
requests
finance-datareader
pykrx
psycopg[binary]
```

Python 3.12+ (GitHub Actions 기준). 로컬은 `uv venv` + `uv pip install -r requirements.txt`.

---

## 10. 데이터 흐름 시나리오

### 10.1 KOSPI 일일 스캔 (운영 표준)

```
1. refresh kr --universe kospi       → instruments + universe_memberships
2. price kr                          → daily_prices (KRW, FDR)
3. flows kospi                       → daily_investor_flows
4. fundamentals kr --source auto     → instrument_fundamentals (stale only)
5. indicators kr                     → daily_indicators
6. screen kr --universe kospi        → scan_results + market_snapshots + sector_snapshots
                                       (smart_money_score 포함, sector_rank 계산)
검증: counts → 적재 건수 확인. admin에서 collection_runs 상태 점검.
```

### 10.2 US S&P 500 일일 스캔

```
1. refresh us --universe sp500       → universe_memberships 갱신
2. price us                          → daily_prices (USD, yfinance batch)
3. fundamentals us                   → instrument_fundamentals (stale only, Yahoo)
4. indicators us                     → daily_indicators
5. screen us --universe sp500        → scan_results (smart_money_* 컬럼 NULL)
```

### 10.3 매크로 + 글로벌 오버뷰

```
1. macro                                                → daily_macro
2. refresh global-indices                               → instruments
3. price global-indices                                 → daily_prices
4. indicators global-indices                            → daily_indicators
5. (스코어링 없음. market_snapshots의 macro_payload는 daily_macro에서 별도 빌더로 생성)
```

### 10.4 백필 (긴 기간 재수집)

```
price us --from 20250101 --to 20260505 --force --workers 1
indicators us --from 20250101 --to 20260505
(screen은 trade_date 단위로 반복 실행 — 추후 batch 옵션 추가 검토)
```

---

## 11. 성공 지표 (KPI)

| 지표 | 목표 | 측정 방법 |
|---|---|---|
| 일일 파이프라인 성공률 (KOSPI) | ≥ 95% | `collection_runs.status='success'` 비율 (최근 30일) |
| 일일 가격 수집 종목 커버리지 | ≥ 98% (시장 보통주) | `daily_prices` 당일 종목 수 / `instruments` 활성 종목 수 |
| 지표 계산 누락률 | ≤ 1% | `daily_indicators` 행 중 핵심 컬럼 `NULL` 비율 |
| 스코어링 점수 분포 안정성 | 표준편차 일별 변동 < 10% | `composite_score` 분포 모니터링 |
| 데이터 품질 flag 비율 | `missing_investor_flow` ≤ 5%, `stale_*` ≤ 10% | `scan_results.data_quality_flags` |
| admin 페이지 응답 시간 | p95 < 1초 | 로컬 응답 시간 |

---

## 12. 로드맵 (다음 단계)

### 12.1 즉시 (현재 코드베이스 정합성)

- [ ] `scan_results.flow_score` 산식에서 KR `smart_money_score` 60% 가산 정책 → 산식 문서화 및 단위 테스트
- [ ] `data_quality_flags` 값 사전 확정 (현재 코드/문서 차이 점검)
- [ ] `news` 단계 운영 정책 결정: `all` 묶음 포함 여부, 일일 실행 여부
- [ ] backfill용 `screen --from --to` 옵션 추가 검토

### 12.2 단기 (1–2개월)

- [ ] **장중 데이터** — 일중 갱신 정책 (현재는 EOD only). 한국 휴장/거래시간 캘린더 필요
- [ ] **펀더멘탈 우선순위 큐** — `--stale-days` 의존 대신 최근 스캔 상위 종목 우선 갱신
- [ ] **점수 캘리브레이션** — 가중치 / shrinkage 임계값을 backtest 기반으로 재조정
- [ ] **시장 레짐 자동 라벨링** — `market_snapshots.regime` / `risk_level`을 macro_payload 기반으로 산출

### 12.3 중기 (3–6개월)

- [ ] **Webapp UI** (v1.1 PRD 비전 실현) — React + FastAPI. 본 DB를 read-only로 소비
- [ ] **AI 시장 요약** — `market_snapshots.ai_summary` 채우기. LLM 프롬프트 + 데이터 컨텍스트 사양 별도 PRD
- [ ] **알림 채널** — composite_score 급변, 신고가 돌파, smart_money_score 급증 등 트리거
- [ ] **`indicator_values` long-form 테이블** — 사용자별 indicator profile 지원 시점에 도입

### 12.4 미정 (검토 대상)

- 옵션/파생 데이터 — 현재 범위 밖
- 백테스트 엔진 — 별도 모듈로 검토
- 포트폴리오 / 주문 연동 — 본 PRD 범위 밖

---

## 13. 관련 문서 / 코드 위치

| 자료 | 경로 |
|---|---|
| 사용자 실행 가이드 | [README.md](../README.md) |
| DB DDL | [docs/database_schema_v1.sql](database_schema_v1.sql) |
| DB 테이블 상세 가이드 | [docs/database_table_guide.md](database_table_guide.md) |
| Fundamentals 매뉴얼 | docs/fundamentals.manual.md |
| v1.1 (선행 PRD, webapp 비전) | [docs/stock_scanner_prd_v1.1.md](stock_scanner_prd_v1.1.md) |
| CLI 엔트리포인트 | [Search.py](../Search.py) |
| 시장 정의 | [market_scanner/config/markets.py](../market_scanner/config/markets.py) |
| 데이터 모델 | [market_scanner/models.py](../market_scanner/models.py) |
| 파이프라인 orchestrator | [market_scanner/pipeline.py](../market_scanner/pipeline.py) |
| 지표 계산 | [market_scanner/analysis/indicators.py](../market_scanner/analysis/indicators.py) |
| 스코어링 엔진 | [market_scanner/analysis/screener.py](../market_scanner/analysis/screener.py) |
| 시장/섹터 스냅샷 빌더 | [market_scanner/domain/snapshots.py](../market_scanner/domain/snapshots.py) |
| 시장 정책 | [market_scanner/domain/market_policy.py](../market_scanner/domain/market_policy.py) |
| 수집기 | [market_scanner/collectors/](../market_scanner/collectors/) |
| Storage / DB I/O | [market_scanner/storage/](../market_scanner/storage/) |
| Admin 서버 | [market_scanner/services/admin_server.py](../market_scanner/services/admin_server.py) |
| GitHub Actions | [.github/workflows/](../.github/workflows/) |

---

## 14. 용어집

| 용어 | 정의 |
|---|---|
| **Market** | 거래 규칙·통화·시간대 단위 (`us`, `kospi`, `kosdaq`, `global-indices`, `sector-etfs`, `theme-proxies`, `commodities`) |
| **Universe** | 분석/필터 멤버십 단위 (`sp500`, `nasdaq100`, `kospi200`, `kosdaq150`, ...) |
| **Instrument** | 종목/ETF/지수/원자재 마스터 단위 |
| **Composite score** | 8개 전략 점수 가중평균에서 리스크 차감한 종합 점수 (0–100) |
| **Action score** | 4개 액션 전략(`pullback`/`breakout`/`box_breakout`/`reversal`) 중 최고 |
| **Quality score** | trend_quality + fundamental + theme + flow의 평균 |
| **Setup label** | 가장 강한 전략 라벨 (예: `이평선 눌림`, `신고가/고점 돌파`, `중립/관망`) |
| **Smart money score** | KR 외국인+기관 5거래일 순매수 거래대금을 20일 평균 거래대금으로 정규화한 0–100 점수 |
| **EOD** | End of Day. 장 마감 종가 기준 |
| **Run** | 한 번의 수집/계산 실행. `collection_runs.run_id`로 식별 |

---

*문서 끝.*
