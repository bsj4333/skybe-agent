# SKIVE 진행 상태

**현재 상태의 유일한 기준.** 세션을 시작할 때 읽고, 끝낼 때 갱신한다. 규칙은 `AGENTS.md` §2.

## 현재 스냅샷 (2026-09-29)

- 브랜치 `skive-agent`, HEAD `ff0bc85` (9/28)
- 현재 단계: **phase-00 기준선 고정** → 다음은 phase-01 실자료 시뮬레이션
- 결정론적 테스트 기준선: **85 passed, 1 skipped**
- Supabase: 마이그레이션 `0001`~`0016` 적용됨. **`0016` 파일은 아직 커밋 안 됨** (F-100)
- OpenAI: **선불 크레딧 잔액 0** (`credit_balance_exhausted`, 2026-09-29 확인). 모델을 부르는 기능은 전부 멈춤 → F-105
- GitHub: 공개 저장소. origin은 `21caf04`(합성 샘플만). **push 안 된 로컬 커밋 4개에 실사용자 자료 포함** → F-101
- 구현 현황 판단: [reviews/2026-09-29-implementation-assessment.md](reviews/2026-09-29-implementation-assessment.md)
- 커밋 안 된 Codex 작업 (9/28~): `skive/drive_project_summary.py`, `migrations/0016_*.sql`, `tests/test_drive_project_summary.py`, `scripts/compare_agents_api.py`, `AGENTS_API_COMPARISON_2026-09-28.md`, 그리고 `drive_worker.py`·`drive_workspace.py`·`server.py`·`skive_drive.html`·문서 4개 수정

## 작업 점유표

| 에이전트 | 항목 | 수정 중인 파일 | 포트 | 시작 |
|---|---|---|---|---|
| (비어 있음) | | | | |

## 다음 작업 (우선순위 순)

1. **F-101** (사람) **다음 push 전에** 저장소 비공개 전환 또는 실사용자 자료 제거. 그 전에는 push하지 않는다
2. **F-100** (Codex) 진행 중 변경 정리·커밋, 테스트 기준선 기록
3. **F-105** (사람) OpenAI 크레딧 충전, 월 지출 상한 설정
4. **F-103** (Codex) Live 테스트 기본 포트 문제
5. **F-102** (Claude) 동결 문서 안내 추가, F-100 이후
6. phase-01: S1·S2는 지금 가능. S3~S8은 F-105 이후

## 열린 질문 (사람에게)

1. F-101: 저장소를 비공개로 돌릴지(A), 공개를 유지하고 push 안 된 커밋에서 실사용자 자료를 뺄지(B)?
2. 평가셋에 실사용자 원문을 넣어도 되나, 파일 ID·위치만 넣어야 하나? 공개 저장소라면 원문은 넣지 않는 쪽이 기본값 (phase-02)
3. 12월 데모 날짜가 정해지면 알려주기. 그때 phase 기간을 역산한다

## 결정 기록

| 날짜 | 결정 | 누가 |
|---|---|---|
| 2026-09-29 | 역할: Codex는 구현, Claude는 설계·평가, 사람은 실자료 시뮬·승인 | 사람 |
| 2026-09-29 | 하네스 위치 `스카이브 연습/`, 에이전트 커밋 허용 (push·병합은 사람) | 사람 |
| 2026-09-29 | `PROJECT_STATUS.md` 동결, 현재 상태는 이 파일만 사용 | 사람 |
| 2026-09-29 | Codex는 이 PC에서 로컬 실행 (클라우드 아님) | 사람 |
| 2026-09-29 | 원격 저장소는 공개. 12월 데모 날짜 미정 | 사람 |

## 세션 로그 (새 기록을 아래에 추가)

### 2026-09-29 · claude
- 저장소를 읽기 전용으로 분석하고 구현 현황을 판단했다 (reviews/2026-09-29-implementation-assessment.md).
- 하네스 파일 작성: `AGENTS.md`, `CLAUDE.md`, `harness/goal.md`, `feature_list.json`, `progress.md`, `build/_TEMPLATE.md`, `build/phase-00~02`.
- 검증: `uv run pytest -q` → 85 passed, 1 skipped. 앱 코드·테스트·설정은 수정하지 않았다.
- 발견: `0016` 적용됐지만 미커밋, 실사용자 자료 git 추적, live 테스트 기본 포트가 8010, `uvx`는 앱 제어 정책에 막힘.
- 다음: Codex가 F-100부터. 하네스 파일은 Codex 커밋과 섞이지 않게 따로 커밋한다.

### 2026-09-29 · claude (2)
- 사람 답변 반영: Codex 로컬 실행, 공개 저장소, OpenAI 한도 미해제, 데모 날짜 미정.
- git 이력 전체 비밀값 검사: 실제 키·토큰·DB 비밀번호 없음 (postgres URL 1건은 자리표시자).
- GitHub(origin `21caf04`)에는 합성 샘플만 있음. 실명·학교가 든 `data/user.json`, `data/store/2. 화력발전소 이상탐지/`, `data/outputs/apply_job_1790126169799.json`은 push 안 된 커밋 4개에만 있음 → F-101을 "다음 push 전 필수"로 올림.
- OpenAI 1토큰 호출 → `credit_balance_exhausted`. 사용량 한도가 아니라 선불 잔액 0 → F-105 추가.
- 코드 확인: 업로드·추출·읽기 카드·활동 후보 제안은 모델 호출 없음 → phase-01 S1·S2는 지금 가능.
- `AGENTS.md`에 공개 저장소 커밋 규칙, 크레딧 소진 시 재시도 금지 규칙 추가.
