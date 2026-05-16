# Codex Project Instructions

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.


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
| 로컬 실행/검증 방식 변경 | `README.md`, 이 `AGENTS.md` |

## Maintenance Rule

새 기능 개발이나 리팩터링이 끝나면 아래를 점검합니다.

- 코드 변경이 CLI/출력/배포/문서 관계도 중 어디에 영향을 주는지 확인합니다.
- 사용자용 실행법이 바뀌면 `README.md`를 갱신합니다.
- Codex 작업 규칙이나 문서 관계도가 바뀌면 이 `AGENTS.md`를 갱신합니다.
