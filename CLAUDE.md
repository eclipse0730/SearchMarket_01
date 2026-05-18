# Codex 프로젝트 지침

## 1. 코딩 전 생각하기

**추측하지 마세요. 모호한 부분을 숨기지 마세요. 장단점을 명확히 드러내세요.**

구현 전:
- 가정을 명확하게 명시하세요. 불확실하면 질문하세요.
- 여러 가지 해석이 가능한 경우, 모두 제시하세요. 묵묵히 선택하지 마세요.
- 더 간단한 접근 방식이 있다면, 그렇게 말하세요. 필요하다면 반대 의견을 제시하세요.
- 불분명한 부분이 있으면 멈추세요. 무엇이 모호한지 파악하고 질문하세요.
* 기획단계에서 사용자가 놓치거나 모르는 단계가 있을수도 있으니 더 확장되고 좋은 방향과 관점들을 제시해주세요

## 2. 단순성 우선

**문제를 해결하는 최소한의 코드만 작성하세요. 추측성 코드는 포함하지 마세요.**

- 요청된 기능 이상의 기능은 추가하지 마세요. (필요하다면 제시하세요.)
- 일회용 코드를 위한 추상화는 사용하지 마세요.
- 요청되지 않은 "유연성"이나 "구성 가능성"은 추가하지 마세요.
- 불가능한 시나리오에 대한 오류 처리는 하지 마세요.
- 200줄을 작성했는데 50줄로 줄일 수 있다면 다시 작성하세요.

스스로에게 물어보세요. "선임 엔지니어가 이 코드가 너무 복잡하다고 말할까?" 만약 그렇다면, 간소화하세요.

## 3. 외과적 수정

**꼭 필요한 부분만 수정하세요. 자신이 만든 코드만 정리하세요.**

기존 코드를 편집할 때:
- 인접한 코드, 주석 또는 서식을 "개선"하지 마세요. (필요하다면 제시하세요.)
- 문제가 없는 부분을 리팩토링하지 마세요.
- 기존 스타일을 따르세요. 비록 다른 방식으로 작성하고 싶더라도.

변경 사항으로 인해 사용되지 않는 요소가 생긴 경우:
- 변경으로 인해 사용되지 않게 된 import 문/변수/함수를 제거하세요.
- 업데이트 등으로 기존의 사용되지 않는 코드가 발생 할 경우 리스트업 하고, 컨펌 받은 후 코드 삭제를 진행하세요.

테스트: 변경된 모든 코드는 사용자의 요청과 직접적으로 연결되어야 합니다.

## 4. 목표 중심 실행

**성공 기준을 정의하고 검증될 때까지 반복합니다.**

작업을 검증 가능한 목표로 변환합니다.
- "유효성 검사 추가" → "유효하지 않은 입력에 대한 테스트를 작성하고 통과하도록 합니다."
- "버그 수정" → "버그를 재현하는 테스트를 작성하고 통과하도록 합니다."
- "X 리팩토링" → "리팩토링 전후에 테스트가 통과하는지 확인합니다.”
-“샘플테스트” → 테스트를 할때 타임아웃을 정의해서 무한로딩되지 않게 합니다.

여러 단계로 이루어진 작업의 경우, 간략한 계획을 명시합니다.
```
1. [단계] → 검증: [확인]
2. [단계] → 검증: [확인]
3. [단계] → 검증: [확인]
여러 단계로 이루어진 작업의 경우, 간략한 계획을 명시합니다.
```
명확한 성공 기준은 독립적인 반복 작업을 가능하게 합니다. 약한 기준("작동하게 만들기")은 지속적인 명확화를 요구합니다.

## 5. 문서의 일관화** 중요문서들과 실제 작업 내용을 일관화 하세요.
-수정을 진행하다가 코드와 문서가 다르게 작동되는 것을 발견할 경우 사용자에게 확인하고 기준을 잡아 수정하세요.
-수정뒤에는 관련문서들을 업데이트하세요. (너무 세세할 필요는 없는지 명령어, 환경세팅등 중요정보는 필수)

## 6. 사용자는 완벽하지 않습니다. 개발도중 다양한 의견과 잘못된 코드들이 있다면 언제든 피드백을 환영합니다.

## Important Files

- `Search.py`: CLI 진입점입니다.
- `market_scanner/models.py`: 공통 데이터 모델과 설정입니다.
- `market_scanner/config/markets.py`: 시장 정의, 유니버스 로더, 메타데이터 로더입니다.
- `market_scanner/analysis/indicators.py`: RSI와 추세 계산입니다.
- `market_scanner/analysis/screener.py`: DB 기반 스크리닝과 점수화입니다.
- `market_scanner/pipeline.py`: 파이프라인 단계 순서 제어입니다.
- `market_scanner/reports/site/build.py`: GitHub Pages용 `site/` 생성기입니다.
- `market_scanner/templates/report.html`: HTML 리포트 템플릿입니다.
- `market_scanner/templates/report.css`: HTML 리포트 스타일입니다.
- `README.md`: 사용자용 설치/실행 설명입니다.
- `.github/workflows/*.yml`: 자동 스캔과 Pages 배포 설정입니다.

## Documentation Relationship Map

코드 변경 시 아래 관계를 확인하고 필요한 문서를 함께 갱신합니다.

| 변경 대상 | 함께 확인/갱신할 문서와 파일 |
|---|---|
| CLI 옵션, 기본값, 실행 단계 변경 | `README.md`, `.github/workflows/*.yml` |
| 시장 추가/삭제, 시장 key 변경 | `README.md`, `market_scanner/reports/site/build.py`, `.github/workflows/*.yml` |
| 출력 파일명 규칙 변경 | `README.md`, `.github/workflows/*.yml` |
| 스캔 데이터 컬럼 추가/삭제/이름 변경 | `market_scanner/analysis/screener.py`, `market_scanner/reports/html_report.py`, `market_scanner/templates/report.html`, `market_scanner/reports/site/` |
| 점수 산식, RSI, 추세 계산 변경 | `README.md`의 설명 필요 여부, 관련 테스트가 생기면 테스트 문서 |
| HTML 리포트 UI/필터/차트 변경 | `market_scanner/templates/report.html`, `market_scanner/templates/report.css`, `market_scanner/reports/site/layout.py` |
| GitHub Pages 구조 변경 | `README.md`, `.github/workflows/deploy-pages.yml` |
| GitHub Actions 스케줄/대상 변경 | `README.md`, 관련 workflow 파일 |
| 의존성 추가/삭제 | `requirements.txt`, `README.md`, workflow 설치 단계 |
| 로컬 실행/검증 방식 변경 | `README.md`, 이 `AGENTS.md`, `CLAUDE.md` |
