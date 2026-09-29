# SKIVE 진행 상태

**현재 상태의 유일한 기준.** 세션을 시작할 때 읽고, 끝낼 때 갱신한다. 규칙은 `AGENTS.md` §2.

## 현재 스냅샷 (2026-09-29)

- 브랜치 `skive-agent`, HEAD `ff0bc85` (9/28)
- 현재 단계: **phase-00 기준선 고정** → 다음은 phase-01 실자료 시뮬레이션
- 결정론적 테스트 기준선: **85 passed, 1 skipped**
- Supabase: 마이그레이션 `0001`~`0016` 적용됨. **`0016` 파일은 아직 커밋 안 됨** (F-100)
- OpenAI: 2026-09-28 대량 재분석 중 사용 한도로 차단. 현재 해제 여부 미확인
- 구현 현황 판단: [reviews/2026-09-29-implementation-assessment.md](reviews/2026-09-29-implementation-assessment.md)
- 커밋 안 된 Codex 작업 (9/28~): `skive/drive_project_summary.py`, `migrations/0016_*.sql`, `tests/test_drive_project_summary.py`, `scripts/compare_agents_api.py`, `AGENTS_API_COMPARISON_2026-09-28.md`, 그리고 `drive_worker.py`·`drive_workspace.py`·`server.py`·`skive_drive.html`·문서 4개 수정

## 작업 점유표

| 에이전트 | 항목 | 수정 중인 파일 | 포트 | 시작 |
|---|---|---|---|---|
| (비어 있음) | | | | |

## 다음 작업 (우선순위 순)

1. **F-100** (Codex) 진행 중 변경 정리·커밋, 테스트 기준선 기록
2. **F-101** (사람) 원격 저장소 공개 여부, 실사용자 자료 추적 방침 결정
3. **F-103** (Codex) Live 테스트 기본 포트 문제
4. **F-102** (Claude) 동결 문서 안내 추가, F-100 이후
5. phase-01 시작: 사람이 실제 프로젝트 자료로 S1부터

## 열린 질문 (사람에게)

1. Codex는 이 PC의 같은 폴더에서 로컬로 실행하나, Codex 클라우드(GitHub 연동)로 실행하나? 클라우드라면 push·브랜치 규칙을 바꿔야 한다.
2. 원격 저장소 `github.com/bsj4333/skybe-agent`가 공개인가 비공개인가? (F-101)
3. 12월 데모 날짜가 정해졌나? phase 기간을 역산하는 데 필요하다.
4. OpenAI 사용 한도는 풀렸나? 월 지출 상한은 얼마로 설정돼 있나? (F-204)
5. 평가셋에 실사용자 원문을 넣어도 되나, 파일 ID·위치만 넣어야 하나? (phase-02)

## 결정 기록

| 날짜 | 결정 | 누가 |
|---|---|---|
| 2026-09-29 | 역할: Codex는 구현, Claude는 설계·평가, 사람은 실자료 시뮬·승인 | 사람 |
| 2026-09-29 | 하네스 위치 `스카이브 연습/`, 에이전트 커밋 허용 (push·병합은 사람) | 사람 |
| 2026-09-29 | `PROJECT_STATUS.md` 동결, 현재 상태는 이 파일만 사용 | 사람 |

## 세션 로그 (새 기록을 아래에 추가)

### 2026-09-29 · claude
- 저장소를 읽기 전용으로 분석하고 구현 현황을 판단했다 (reviews/2026-09-29-implementation-assessment.md).
- 하네스 파일 작성: `AGENTS.md`, `CLAUDE.md`, `harness/goal.md`, `feature_list.json`, `progress.md`, `build/_TEMPLATE.md`, `build/phase-00~02`.
- 검증: `uv run pytest -q` → 85 passed, 1 skipped. 앱 코드·테스트·설정은 수정하지 않았다.
- 발견: `0016` 적용됐지만 미커밋, 실사용자 자료 git 추적, live 테스트 기본 포트가 8010, `uvx`는 앱 제어 정책에 막힘.
- 다음: Codex가 F-100부터. 하네스 파일은 Codex 커밋과 섞이지 않게 따로 커밋한다.
