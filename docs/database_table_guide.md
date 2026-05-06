# SearchMarket Database Table Guide

Last updated: 2026-04-30

이 문서는 `docs/database_schema_v1.sql`의 테이블 역할과 주요 컬럼을 설명합니다.

## 전체 구조

데이터는 다음 흐름으로 저장합니다.

1. 종목 마스터를 `instruments`에 저장
2. 시장/유니버스 구성을 `markets`, `universe_definitions`, `universe_memberships`에 저장
3. 수집 실행 로그를 `collection_runs`에 저장
4. 일봉 가격을 `daily_prices`에 저장
5. RSI, MA, MACD, 볼린저, 캔들 지표를 `daily_indicators`에 저장
6. 재무/밸류에이션 데이터를 `instrument_fundamentals`에 저장
7. 최종 점수와 랭킹을 `scan_results`에 저장
8. 시장/섹터 요약을 `market_snapshots`, `sector_snapshots`에 저장
9. 뉴스와 생성 리포트는 후속 테이블에 저장

## markets

시장 단위 정의 테이블입니다.

예:

- `us`
- `kospi`
- `kosdaq`
- `global-indices`
- `theme-proxies`
- `commodities`

주요 컬럼:

| 컬럼 | 설명 |
|---|---|
| `market_key` | 코드에서 사용하는 시장 키 |
| `label` | 화면 표시용 시장명 |
| `country_code` | `US`, `KR` 같은 국가 코드 |
| `currency_code` | `USD`, `KRW` 같은 통화 코드 |
| `timezone` | 시장 기준 시간대 |
| `description` | 시장 설명 |
| `is_active` | 사용 여부 |

## instruments

종목, ETF, ETN, 지수, 원자재 등 투자 대상의 마스터 테이블입니다.

주요 컬럼:

| 컬럼 | 설명 |
|---|---|
| `instrument_id` | 내부 PK |
| `market_key` | 기본 소속 시장 |
| `symbol` | 수집/조회용 심볼. 예: `005930.KS`, `AAPL`, `^VIX` |
| `display_symbol` | 화면 표시용 심볼. 예: `005930` |
| `exchange_code` | 거래소 코드. 예: `KOSPI`, `KOSDAQ`, `NASDAQ` |
| `asset_type` | 자산 분류 |
| `listing_status` | 상장 상태 |
| `name_en` | 영어명 |
| `name_local` | 현지명. 한국 종목은 한글명 |
| `sector` | 섹터 |
| `industry` | 산업 |
| `description` | 종목 설명 |
| `source_provider` | 메타데이터 출처 |
| `source_rank` | 소스 우선순위 |
| `raw_metadata` | 원본 payload 보관용 JSON |

`asset_type` 권장값:

| 값 | 의미 |
|---|---|
| `common_stock` | 보통주 |
| `preferred_stock` | 우선주 |
| `etf` | ETF |
| `etn` | ETN |
| `reit` | 리츠 |
| `spac` | 스팩 |
| `fund` | 펀드/인프라펀드/기타 집합투자 |
| `index` | 지수 |
| `commodity` | 원자재 |
| `other` | 분류 보류 |

한국 전체 시장에서는 이 컬럼이 중요합니다. Naver Finance fallback 목록에는 보통주 외 상품이 섞일 수 있으므로, `kospi`/`kosdaq` 기본 스캔은 `asset_type = 'common_stock'` 중심으로 제한하는 것을 권장합니다.

## universe_definitions

스캔 대상 묶음을 정의합니다.

시장과 유니버스는 다릅니다. 예를 들어 `KOSPI`라는 시장 안에 다음 유니버스가 있을 수 있습니다.

- `kospi`: KOSPI 보통주 전체
- `kospi100`: KOSPI 100 대표 유니버스
- `kospi200`: KOSPI 200 대표 유니버스
- `kospi-etf`: KOSPI ETF
- `kospi-preferred`: KOSPI 우선주

주요 컬럼:

| 컬럼 | 설명 |
|---|---|
| `universe_key` | 유니버스 키 |
| `market_key` | 연결 시장 |
| `label` | 화면 표시명 |
| `description` | 유니버스 설명 |
| `source_policy` | 유니버스를 만드는 원천과 fallback 정책 |
| `default_asset_type_filter` | 기본 포함 자산 타입 |
| `is_active` | 사용 여부 |

시장 전체를 의미하는 요약도 `NULL` 대신 명시적인 유니버스 키를 사용합니다. 예를 들어 KOSPI 전체 보통주는 `kospi`, KOSPI 100/200 대표 유니버스는 `kospi100`, `kospi200`처럼 별도 유니버스를 만들어 참조합니다. PostgreSQL primary key에서는 nullable 컬럼이 중복 방지 의미를 흐릴 수 있으므로, snapshot 계열 테이블의 `universe_key`는 `NOT NULL`입니다.

## universe_memberships

특정 유니버스에 어떤 종목이 포함되는지 기록합니다.

주요 컬럼:

| 컬럼 | 설명 |
|---|---|
| `universe_key` | 유니버스 키 |
| `instrument_id` | 종목 ID |
| `effective_from` | 편입 시작일 |
| `effective_to` | 편입 종료일. 현재 편입이면 `NULL` |
| `rank_no` | 시총 순위 등 유니버스 내 순위 |
| `weight` | 지수 비중 등 가중치 |
| `source_provider` | 구성 원천 |
| `raw_payload` | 원본 데이터 |

이 테이블이 있으면 S&P 500 구성 변경, NASDAQ 100 교체, KOSPI 전체 목록 변화를 날짜별로 추적할 수 있습니다.

## collection_runs

수집/계산/렌더 실행 로그입니다.

주요 컬럼:

| 컬럼 | 설명 |
|---|---|
| `run_id` | 실행 ID |
| `run_type` | `universe`, `prices`, `indicators`, `scan`, `news`, `render`, `backfill` |
| `market_key` | 실행 대상 시장 |
| `universe_key` | 실행 대상 유니버스 |
| `trade_date` | 대상 거래일 |
| `source_provider` | 사용 데이터 소스 |
| `status` | `running`, `success`, `partial`, `failed`, `cancelled` |
| `requested_count` | 요청 대상 수 |
| `success_count` | 성공 수 |
| `failed_count` | 실패 수 |
| `skipped_count` | 스킵 수 |
| `params` | 실행 파라미터. `refresh-master`는 멤버십 비교 요약과 추가/삭제/순위 변경 샘플도 저장 |
| `error_samples` | 실패 샘플 |
| `git_sha` | 실행 코드 버전 |

예: `kospi` 900개 중 890개 성공, 10개 실패 같은 정보를 이 테이블에 남깁니다.

## daily_prices

일봉 OHLCV 저장 테이블입니다.

주요 컬럼:

| 컬럼 | 설명 |
|---|---|
| `instrument_id` | 종목 ID |
| `trade_date` | 거래일 |
| `source_provider` | 가격 출처. 예: `fdr`, `yfinance`, `naver`, `polygon` |
| `open_price` | 시가 |
| `high_price` | 고가 |
| `low_price` | 저가 |
| `close_price` | 종가 |
| `adj_close_price` | 수정종가 |
| `volume` | 거래량 |
| `currency_code` | 통화 |
| `is_adjusted` | 수정 가격 여부 |
| `run_id` | 수집 실행 ID |
| `raw_payload` | 원본 데이터 |

Primary key는 `(instrument_id, trade_date, source_provider)`입니다. 같은 종목/날짜라도 FDR과 yfinance 값을 비교 저장할 수 있습니다.

## daily_indicators

가격 데이터로 계산한 기술 지표 저장 테이블입니다.

Primary key는 `(instrument_id, trade_date)`입니다. 한 종목의 한 거래일에 대해 운영 기준 지표는 하나만 저장합니다. 가격 원천이 FDR에서 yfinance로 바뀌어 지표를 다시 계산하면 같은 PK row를 upsert하고, 사용한 원천은 `price_source_provider`에 남깁니다. 소스별 지표를 동시에 비교 저장해야 하는 단계가 오면 PK를 `(instrument_id, trade_date, price_source_provider, indicator_profile)`로 확장합니다.

주요 컬럼:

| 컬럼 | 설명 |
|---|---|
| `instrument_id` | 종목 ID |
| `trade_date` | 거래일 |
| `price_source_provider` | 지표 계산에 사용한 가격 소스 |
| `rsi14` | 14일 RSI |
| `ma5`, `ma20`, `ma60`, `ma120`, `ma240` | 이동평균 |
| `diff_5_pct`, `diff_20_pct`, `diff_60_pct`, `diff_120_pct`, `diff_240_pct` | 현재가와 이동평균 이격률 |
| `near_5`, `near_20`, `near_60`, `near_120`, `near_240` | 이동평균 근접 여부 |
| `macd`, `macd_signal`, `macd_hist` | MACD 값 |
| `macd_state` | MACD 상태 |
| `bollinger_width_pct` | 볼린저 밴드 폭 |
| `bollinger_percent_b` | 볼린저 %B |
| `high_52w`, `low_52w` | 52주 고가/저가 |
| `from_high_pct`, `from_low_pct` | 52주 고점/저점 대비 위치 |
| `high_20d`, `low_20d`, `high_60d`, `low_60d` | 20/60거래일 종가 고저 |
| `breakout_20d`, `breakout_60d` | 직전 20/60거래일 고점 돌파 여부 |
| `volume_ratio` | 최근 거래량 대비 평균 거래량 비율 |
| `return_5d`, `return_20d`, `return_60d`, `return_120d`, `return_240d` | 기간별 수익률 |
| `atr14`, `atr14_pct` | 14일 ATR과 현재가 대비 ATR 비율 |
| `volatility_20d`, `volatility_60d` | 20/60일 연율화 변동성 |
| `change_pct` | 전일 종가 대비 당일 종가 등락률 |
| `gap_pct` | 전일 종가 대비 금일 시가 갭 |
| `candle_*` | 캔들 몸통/범위/꼬리 비율 |
| `candle_type` | 캔들 해석 |
| `trend`, `trend_score` | 추세 판정 |

RSI, 볼린저, MACD, 이동평균, 기간 수익률, ATR, 변동성은 매일 새 가격이 들어온 뒤 재계산합니다.

현재 `macd_state` 유효값:

| 값 | 의미 |
|---|---|
| `Bullish` | MACD histogram 양수이며 전일 대비 개선 |
| `Positive` | MACD histogram 양수이나 전일 대비 둔화 |
| `Improving` | MACD histogram 음수이나 전일 대비 개선 |
| `Bearish` | MACD histogram 음수이며 둔화 |
| `Unknown` | 계산 불가 |

현재 `candle_type` 유효값:

| 값 | 의미 |
|---|---|
| `Unknown` | OHLC 부족 |
| `Flat` | 고가와 저가가 같음 |
| `Long Lower Doji` | 긴 아래꼬리 도지 |
| `Long Upper Doji` | 긴 위꼬리 도지 |
| `Doji` | 도지 |
| `Bullish Reversal` | 아래꼬리 반등형 양봉 |
| `Bearish Rejection` | 위꼬리 저항형 음봉 |
| `Strong Bullish` | 강한 양봉 |
| `Strong Bearish` | 강한 음봉 |
| `Bullish` | 일반 양봉 |
| `Bearish` | 일반 음봉 |

주의: 현재 스키마는 `ma5`, `ma20`, `ma60`, `ma120`, `ma240`을 컬럼으로 고정합니다. MA 기간을 자주 바꾸거나 사용자별 지표 프로필을 지원하려면 `indicator_values` 같은 long-form 테이블로 분리하는 것이 안전합니다.

## instrument_fundamentals

재무/밸류에이션 데이터 저장 테이블입니다.

주요 컬럼:

| 컬럼 | 설명 |
|---|---|
| `instrument_id` | 종목 ID |
| `as_of_date` | 기준일 |
| `source_provider` | 출처 |
| `trailing_pe` | PER |
| `price_to_book` | PBR |
| `return_on_equity_pct` | ROE |
| `revenue_growth_pct` | 매출 성장률 |
| `market_cap` | 시가총액 |
| `target_price` | 목표가 |
| `shares_outstanding` | 상장주식수 |
| `raw_payload` | 원본 데이터 |

가격처럼 매일 반드시 바뀌는 데이터가 아니므로, 일봉과 분리합니다. 주 1회 또는 월 1회 갱신도 가능합니다.

## scan_results

스캐너의 최종 결과 저장 테이블입니다.

주요 컬럼:

| 컬럼 | 설명 |
|---|---|
| `run_id` | 스캔 실행 ID |
| `instrument_id` | 종목 ID |
| `market_key` | 시장 |
| `universe_key` | 유니버스 |
| `trade_date` | 기준일 |
| `chart_score` | 차트 점수 |
| `technical_score` | 기술 지표 점수 |
| `fundamental_score` | 재무 점수 |
| `theme_score` | 테마 점수 |
| `flow_score` | 수급/흐름 점수 |
| `composite_score` | 종합 점수 |
| `rank_no` | 랭킹 |
| `setup_tags` | 눌림목, 과매도 반등, MACD 개선 등 태그 |
| `risk_flags` | 과열, 유동성 부족 등 리스크 태그 |
| `summary_payload` | 화면 표시용 추가 요약 |

이 테이블은 상세 페이지의 종목 리스트와 분석 리포트의 핵심 후보 추출에 사용합니다.

현재 종합 점수 가중치:

| 점수 | 가중치 | 설명 |
|---|---:|---|
| `chart_score` | 30% | 추세, MA 근접, 52주 고점 대비 위치 |
| `technical_score` | 25% | RSI, MACD, 볼린저, 거래량, 캔들 |
| `fundamental_score` | 20% | PER, PBR, ROE, 매출 성장률 |
| `theme_score` | 15% | 섹터 평균 추세와 등락률 |
| `flow_score` | 10% | 거래량, 고점 대비 위치, 목표가 괴리, 등락률, 갭/캔들 |

`setup_tags`와 `risk_flags`는 스키마에 선반영한 컬럼입니다. 현재 CSV/HTML 파이프라인은 setup bucket과 일부 리스크 문구를 계산하지만, 이 두 배열 컬럼에 표준화된 값을 저장하는 DB upsert 구현은 아직 없습니다. DB 저장 레이어를 만들 때 태그 사전을 먼저 정의해야 합니다.

## market_snapshots

시장 전체 요약 테이블입니다.

주요 컬럼:

| 컬럼 | 설명 |
|---|---|
| `market_key` | 시장 |
| `universe_key` | 유니버스 |
| `trade_date` | 기준일 |
| `total_count` | 전체 대상 수 |
| `scanned_count` | 스캔 대상 수 |
| `success_count` | 성공 수 |
| `failed_count` | 실패 수 |
| `advance_count` | 상승 종목 수 |
| `decline_count` | 하락 종목 수 |
| `unchanged_count` | 보합 종목 수 |
| `avg_change_pct` | 평균 등락률 |
| `median_change_pct` | 중앙값 등락률 |
| `avg_rsi14` | 평균 RSI |
| `bullish_breadth_pct` | 상승 폭 지표 |
| `avg_composite_score` | 평균 종합 점수 |
| `market_score` | 시장 종합 점수 |
| `regime` | 강세/약세/보합 등 국면 |
| `risk_level` | 리스크 수준 |
| `macro_payload` | VIX, 금리, BTC 등 확장 매크로 데이터 |
| `ai_summary` | AI 시장 요약 |

메인 페이지 상단 카드와 시장별 상태 바의 원천으로 쓰기 좋습니다.

`universe_key`는 `NOT NULL`입니다. 시장 전체 요약도 `NULL`을 쓰지 않고 `kospi:all`, `us:all` 같은 명시 유니버스를 참조합니다.

## sector_snapshots

섹터별 요약 테이블입니다.

주요 컬럼:

| 컬럼 | 설명 |
|---|---|
| `market_key` | 시장 |
| `universe_key` | 유니버스 |
| `trade_date` | 기준일 |
| `sector` | 섹터 |
| `instrument_count` | 섹터 내 종목 수 |
| `advance_count` | 상승 종목 수 |
| `decline_count` | 하락 종목 수 |
| `avg_change_pct` | 평균 상승률 |
| `median_change_pct` | 중앙값 상승률 |
| `avg_rsi14` | 평균 RSI |
| `avg_composite_score` | 평균 종합 점수 |
| `top_instruments` | 섹터 내 주요 종목 JSON |

상세 페이지의 섹터별 상승률/히트맵 패널에 사용합니다.

`universe_key`는 `NOT NULL`입니다. 같은 시장이라도 보통주 전체, 우선주, ETF, 대형주 유니버스의 섹터 요약이 다를 수 있으므로 반드시 어떤 유니버스 기준인지 명시합니다.

## news_items

뉴스 원문 단위 저장 테이블입니다.

주요 컬럼:

| 컬럼 | 설명 |
|---|---|
| `news_id` | 뉴스 ID |
| `source_provider` | 뉴스 출처 |
| `external_id` | 외부 뉴스 ID |
| `url` | 뉴스 URL |
| `title` | 제목 |
| `publisher` | 발행처 |
| `published_at` | 발행 시각 |
| `summary` | 요약 |
| `language_code` | 언어 |
| `raw_payload` | 원본 데이터 |

## instrument_news

종목과 뉴스를 연결하는 테이블입니다.

주요 컬럼:

| 컬럼 | 설명 |
|---|---|
| `instrument_id` | 종목 ID |
| `news_id` | 뉴스 ID |
| `relevance_score` | 관련도 |

한 뉴스가 여러 종목에 연결될 수 있고, 한 종목도 여러 뉴스를 가질 수 있으므로 연결 테이블로 분리합니다.

## generated_reports

생성된 Markdown, HTML, CSV, JSON 산출물 기록 테이블입니다.

주요 컬럼:

| 컬럼 | 설명 |
|---|---|
| `report_id` | 리포트 ID |
| `market_key` | 시장 |
| `universe_key` | 유니버스 |
| `trade_date` | 기준일 |
| `run_id` | 생성 실행 ID |
| `report_type` | `analysis`, `detail_page`, `site_page`, `export` |
| `format` | `markdown`, `html`, `csv`, `json` |
| `file_path` | 생성 파일 경로 |
| `content_hash` | 내용 해시 |
| `metadata` | 추가 메타데이터 |

사이트가 언제 어떤 데이터로 빌드됐는지 추적할 수 있습니다.

## 자주 쓰는 조회 예시

최신 KOSPI 보통주 스캔 상위 30개:

```sql
SELECT
    i.symbol,
    i.name_local,
    s.composite_score,
    s.rank_no
FROM scan_results s
JOIN instruments i ON i.instrument_id = s.instrument_id
WHERE s.market_key = 'kospi'
  AND s.trade_date = (
      SELECT max(trade_date)
      FROM scan_results
      WHERE market_key = 'kospi'
  )
  AND i.asset_type = 'common_stock'
ORDER BY s.composite_score DESC
LIMIT 30;
```

특정 종목 최근 20거래일 가격과 RSI:

```sql
SELECT
    p.trade_date,
    p.close_price,
    d.rsi14,
    d.ma60,
    d.ma120,
    d.ma240
FROM instruments i
JOIN daily_prices p ON p.instrument_id = i.instrument_id
LEFT JOIN daily_indicators d
  ON d.instrument_id = i.instrument_id
 AND d.trade_date = p.trade_date
WHERE i.symbol = '005930.KS'
ORDER BY p.trade_date DESC
LIMIT 20;
```

최신 섹터 히트맵 데이터:

```sql
SELECT
    sector,
    instrument_count,
    advance_count,
    decline_count,
    avg_change_pct,
    median_change_pct,
    avg_composite_score
FROM sector_snapshots
WHERE market_key = 'kospi'
  AND trade_date = (
      SELECT max(trade_date)
      FROM sector_snapshots
      WHERE market_key = 'kospi'
  )
ORDER BY avg_change_pct DESC;
```
