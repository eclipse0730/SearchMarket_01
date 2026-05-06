temp.md
아래 피드백은 어떻게 생각해?

문제 4: flow_score 이름과 실제 내용이 조금 다름
현재 _score_flow()는 수급이라기보다:
거래량 + 52주 고점 대비 위치 + 목표가 괴리율 + 당일 등락 + 갭/캔들이다.
진짜 수급이라면 아래 데이터가 들어가야 한다.
외국인 순매수
기관 순매수
개인 순매수
공매도 비중
대차잔고 증감
프로그램 매매
그래서 지금은 이름을 momentum_score 또는 price_flow_score로 바꾸는 게 더 정확하다.
오전 12:11

이 피드백도 맞아. 현재 flow_score는 엄밀한 의미의 “수급”이 아니야.

지금 _score_flow()가 보는 건 대략 이거야:

volume_ratio
from_high_pct
upside_pct
change_pct
gap_pct + candle_type
즉 실제 외국인/기관/개인 순매수 같은 주체별 수급 데이터가 아니라, 가격과 거래량에서 추론한 가격 흐름/모멘텀이야. 그래서 이름만 보면 오해가 생길 수 있어.

내 생각엔 지금 당장 데이터 구조를 크게 바꾸지 않는다면 이름을 바꾸는 게 좋아.

후보는:

momentum_score
price_flow_score
trading_flow_score
나는 **momentum_score**가 제일 깔끔해 보여. 이유는:

change_pct, gap_pct, candle_type는 모멘텀 성격
from_high_pct는 가격 위치
volume_ratio는 거래량 확인
upside_pct는 기대 여지
다 합치면 “수급”보다는 “가격 모멘텀/흐름”이 맞아.

다만 DB 컬럼과 리포트 호환성을 생각하면 바로 flow_score 컬럼명을 삭제/교체하기보다는 단계적으로 가는 게 좋아.

추천:

1차:
- 내부 함수명 `_score_flow` -> `_score_momentum`
- 화면/문서 표현을 “수급” -> “모멘텀” 또는 “가격 흐름”으로 변경
- DB 컬럼 `flow_score`는 유지

2차:
- DB에 `momentum_score` 컬럼 추가
- 기존 `flow_score`는 deprecated 또는 alias 처리

3차:
- 실제 수급 데이터 collector 추가
  - foreign_net_buy 
  - institution_net_buy
  - retail_net_buy
  - short_volume_ratio
  - lending_balance_change
  - program_trading_net
- 그때 진짜 `flow_score` 또는 `supply_demand_score`를 새로 계산
즉 피드백 방향은 맞고, 지금은 이름을 “momentum” 쪽으로 정리하는 게 가장 안전해. 실제 수급 점수는 데이터 소스를 붙인 뒤 별도 점수로 만드는 게 좋아.





오전 12:11
단계별로 진행하자
오전 12:12


2m 8s 동안 작업
1차 정리 완료했어.

이번 단계에서는 DB 컬럼명은 그대로 flow_score로 유지하고, 의미를 명확히 하도록 내부/문서/리포트 표현을 바꿨어.

변경 내용:


screener.py

_score_flow() → _score_momentum()으로 변경
add_scores()에서 momentum_score alias 추가
기존 DB 호환을 위해 flow_score에도 같은 값을 계속 저장
Markdown 리포트 문구를 수급 → 모멘텀, 가격 흐름·업사이드로 변경

README.md
, 
DEVELOPMENT_NOTES.md
, 
docs/database_table_guide.md
 문서 갱신
검증도 했어:

.\.venv\Scripts\python.exe -m compileall market_scanner\analysis\screener.py market_scanner\reports\html_report.py market_scanner\reports\markdown_report.py
샘플에서도 momentum_score와 flow_score가 같은 값으로 잘 들어가는 것 확인했어.
다음 단계는 실제 수급 데이터를 넣기 위한 DB/collector 설계로 가면 돼.


README.md
문서 · MD

열기


DEVELOPMENT_NOTES.md
문서 · MD

열기


database_table_guide.md
문서 · MD

열기

6개 파일 변경됨
+24
-19
실행 취소
리뷰

DEVELOPMENT_NOTES.md
README.md
docs/database_table_guide.md
market_scanner/analysis/screener.py
market_scanner/reports/html_report.py
market_scanner/reports/markdown_report.py




