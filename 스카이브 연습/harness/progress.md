# SKIVE 진행 상태

**현재 상태의 유일한 기준.** 세션을 시작할 때 읽고, 끝낼 때 갱신한다. 규칙은 `AGENTS.md` §2.

## 현재 스냅샷 (2026-09-30)

- 브랜치 `skive-agent`. 2026-09-30에 개인 자료를 뺀 이력으로 GitHub에 push함 (아래 로그). 9/28 커밋은 새 해시 `e0ea084`
- 현재 단계: **phase-00 기준선 고정** → 다음은 phase-01 실자료 시뮬레이션
- 결정론적 테스트 기준선: **85 passed, 1 skipped**
- Supabase: 마이그레이션 `0001`~`0016` 적용됨. **`0016` 파일은 아직 커밋 안 됨** (F-100)
- OpenAI: **선불 크레딧 잔액 0** (`credit_balance_exhausted`, 2026-09-29 확인). 모델을 부르는 기능은 전부 멈춤 → F-105
- GitHub: 공개 저장소. 실사용자 자료(`data/user.json` 실제 값, `data/store/2. 화력발전소 이상탐지/`, `data/outputs/apply_job_1790126169799.json`)는 이 PC에만 있고 `.gitignore`·skip-worktree로 추적 제외 (F-101 완료)
- 모델 배치 설계: [build/design-model-routing.md](build/design-model-routing.md) (사람 승인 대기)
- 구현 현황 판단: [reviews/2026-09-29-implementation-assessment.md](reviews/2026-09-29-implementation-assessment.md)
- 커밋 안 된 Codex 작업 (9/28~): `skive/drive_project_summary.py`, `migrations/0016_*.sql`, `tests/test_drive_project_summary.py`, `scripts/compare_agents_api.py`, `AGENTS_API_COMPARISON_2026-09-28.md`, 그리고 `drive_worker.py`·`drive_workspace.py`·`server.py`·`skive_drive.html`·문서 4개 수정

## 작업 점유표

| 에이전트 | 항목 | 수정 중인 파일 | 포트 | 시작 |
|---|---|---|---|---|
| (비어 있음) | | | | |

## 다음 작업 (우선순위 순)

1. **F-100** (Codex) 진행 중 변경 정리·커밋, 테스트 기준선 기록
2. **F-106** (Codex) 프로젝트 요약 기본 모델 astra 제거 (비용 안전)
3. **F-105** (사람) OpenAI 크레딧 충전, 월 지출 상한 설정
4. **F-103** (Codex) Live 테스트 기본 포트 문제
5. **F-102** (Claude) 동결 문서 안내 추가, F-100 이후
6. phase-01: S1·S2는 지금 가능. S3~S8은 F-105 이후

## 열린 질문 (사람에게)

1. 모델 배치 설계(`build/design-model-routing.md`) 승인 여부와 §9 질문 3개 (T2 기본 모델, 예산 상한, astra 사용처)
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
| 2026-09-30 | 공개 유지, 실사용자 자료만 빼고 push (F-101 선택지 B) | 사람 |

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

### 2026-09-30 · claude
- 사람 지시("개인 자료만 빼고 push")로 push 안 된 커밋 5개를 개인 자료 없이 다시 만들었다: `687a177→08f77cd`, `38ce281→502d7ec`, `ff0bc85→e0ea084`, `be34693→3edd025`, `1c00365→74656e4`. 작업 트리는 건드리지 않았다(임시 인덱스 사용).
- 뺀 것: `data/store/2. 화력발전소 이상탐지/` 4개, `data/outputs/apply_job_1790126169799.json`. `data/user.json`은 GitHub에 이미 있던 합성 인물(김민수) 버전으로 유지하고, 이 PC의 실제 값은 `git update-index --skip-worktree`로 숨김. 원래 커밋은 로컬 브랜치 `backup/local-before-privacy-filter`에 보존(push 금지).
- `.gitignore`에 실사용자 자료 경로 추가. `samples/` 기반 `*_raw` 예제는 계속 추적.
- 모델 배치 설계 `build/design-model-routing.md` 작성. 발견: `drive_project_summary.py`의 기본 모델이 `gpt-6-astra`로 하드코딩 → F-106. F-205(작업별 모델 표), F-206(자체 루프 vs Agents API 실험) 추가.
- 이미 GitHub에 있던 것(되돌리지 않음): 샘플 `metadata.json`의 로컬 경로에 들어간 폴더명, UI 목업의 학교명.
