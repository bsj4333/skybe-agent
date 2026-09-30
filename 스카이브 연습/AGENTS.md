# SKIVE 저장소 지침 (Codex·Claude 공통)

이 파일은 `스카이브 연습/`에서 일하는 모든 AI 에이전트가 **가장 먼저** 읽는 규칙 원본이다.
Claude Code는 `CLAUDE.md`에서 이 파일을 불러온다. 규칙을 바꿀 때는 이 파일만 고친다.

- 제품 목표·비목표: [harness/goal.md](harness/goal.md)
- 지금 상태·누가 무엇을 하는 중인지: [harness/progress.md](harness/progress.md)
- 기능·버그 목록과 완료 조건: [harness/feature_list.json](harness/feature_list.json)
- 설계 문서: [harness/build/](harness/build/) · 평가 기록: [harness/reviews/](harness/reviews/)

## 1. 역할 분담

| 누가 | 하는 일 | 쓰는 파일 |
|---|---|---|
| **Codex (구현)** | 설계된 작업을 코드로 구현, 테스트 작성, 버그 수정, 커밋 | `skive/`, `tests/`, `migrations/`, `scripts/`, `ui_mockup/`, `pyproject.toml`(승인 시) + `feature_list.json`의 자기 항목 상태·증거, `progress.md` 점유표·세션 로그 |
| **Claude (설계·평가)** | 설계 문서 작성, 완료 조건 정의, Codex 커밋 검토, 실자료 시뮬레이션 관찰, 버그 기록 | `harness/**`, `AGENTS.md`, `CLAUDE.md` |
| **사람 (저장소 주인)** | 실제 자료 업로드·시뮬 실행, 우선순위 결정, 승인 항목 결정, push·병합 | 전부 가능 |

- Claude는 사람이 명시적으로 요청하지 않는 한 애플리케이션 코드(`skive/`, `tests/`, `migrations/`, `scripts/`, `ui_mockup/`)를 고치지 않는다. 문제를 찾으면 `feature_list.json`에 기록하고 Codex에게 넘긴다.
- Codex는 `harness/build/`의 설계 문서와 `AGENTS.md`를 고치지 않는다. 설계가 틀렸거나 모호하면 `progress.md`의 **열린 질문**에 적는다.

## 2. 세션 시작·종료 절차 (모든 에이전트)

시작할 때:
1. 이 파일 → `harness/progress.md` → `harness/feature_list.json` 순서로 읽는다.
2. `git status`, `git log --oneline -5`로 작업 트리를 확인한다. 모르는 변경이 있으면 건드리지 말고 누가 만든 것인지 `progress.md` 로그에서 찾는다.
3. 사용할 포트가 비어 있는지 확인한다(§7).
4. 작업할 항목 하나를 골라 `progress.md` **작업 점유표**에 적는다.

끝낼 때:
1. 실제로 실행한 검증 명령과 결과를 `feature_list.json`의 `evidence`에 적는다.
2. `progress.md` **세션 로그**에 3~6줄로 남긴다: 한 일, 검증 결과, 남은 일, 다음 사람이 알아야 할 것.
3. 점유표에서 자기 줄을 지운다. 띄운 서버·워커는 종료한다.

## 3. 작업 상태와 누가 바꿀 수 있는가

`feature_list.json`의 `status` 값:

| 상태 | 뜻 | 이 상태로 바꿀 수 있는 쪽 |
|---|---|---|
| `idea` | 적어둔 아이디어, 설계 전 | 누구나 |
| `spec` | Claude가 설계 중 | Claude |
| `ready` | 설계 완료, Codex가 가져갈 수 있음 | Claude(작은 버그), 사람(기능·데이터 구조·불변조건 관련) |
| `in_progress` | Codex 구현 중 (`owner` 필수) | Codex |
| `review` | Codex 완료, Claude 검토 대기 | Codex |
| `changes_requested` | 검토 반려, `notes`에 이유 | Claude |
| `passing` | 필수 검증 전부 통과 | Claude. 단 `real_data`·`manual` 검증이 걸린 항목은 사람 확인 후 |
| `failing` | 재현된 결함 | Claude, 사람 |
| `blocked` | 외부 요인으로 진행 불가, `notes`에 이유 필수 | 누구나 |

**Codex는 자기 작업을 `passing`으로 바꾸지 않는다.** 구현한 쪽이 스스로 채점하지 않는 것이 이 하네스의 핵심이다.

## 4. Codex 구현 규칙

1. `status`가 `ready`이거나 `failing`인 항목만 가져간다. 한 번에 하나만 한다.
2. 연결된 설계 문서(`links`)의 **완료 조건**을 구현 기준으로 삼는다. 설계에 없는 기능을 덧붙이지 않는다.
3. 버그는 **재현하는 실패 테스트를 먼저** 만들고, 그 테스트가 통과하도록 고친다.
4. 기존 테스트를 지우거나 단언(assert)을 약하게 바꿔서 통과시키지 않는다. 테스트 자체가 틀렸다고 판단되면 고치지 말고 `notes`와 열린 질문에 적는다.
5. 결정론적 테스트 전체가 기준선 이상으로 통과해야 커밋한다. 기준선: **85 passed, 1 skipped (2026-09-29)**. 개수는 늘어날 수만 있다.
6. 마이그레이션은 새 번호 파일로만 추가한다. 이미 적용된 파일은 고치지 않는다. **공유 Supabase에 적용하는 것은 사람 승인 후**이고, 적용했다면 같은 커밋에 파일을 반드시 포함한다.
7. `.env`, 키, `data/` 아래 실사용자 자료, 의존성(`pyproject.toml`, `uv.lock`)은 사람 승인 없이 바꾸지 않는다.
8. 끝나면 `status`를 `review`로 바꾸고, 실행한 명령과 결과를 `evidence`에 적는다. 실행하지 않은 검증을 "통과"라고 쓰지 않는다.
9. 새 상태 보고용 `.md` 파일을 루트에 만들지 않는다(§9).

## 5. 제품 불변조건 (사람 승인 없이 바꿀 수 없음)

1. **근거와 출처 구분.** 모든 사실은 `document`(원문 근거) / `user_statement`(본인 진술) / `derived`(AI 해석) 중 하나다. 본인 진술이나 AI 해석을 원문 근거로 승격하지 않는다.
2. **본인과 팀 구분.** 자료만으로 "본인이 했다"를 자동 확정하지 않는다. 확정하려면 사람의 확인이 필요하다. 팀 성과를 본인 성과로 쓰지 않는다.
3. **정정 우선.** 정정된 사실은 이전 검증 상태를 물려받지 않고, 정정 뒤에 옛 사실이 다시 나오면 결함이다.
4. **수치는 원문 그대로.** 원문에 없는 수치를 만들거나, 다른 지표의 숫자를 끌어오지 않는다.
5. **드라이브는 원본 그대로.** 사용자가 올린 폴더 구조·파일명·번호를 임의로 접거나 바꾸지 않는다.
6. **계정 격리.** 모든 조회는 로그인한 사용자 범위(RLS) 안에서만 한다. 비밀 키를 브라우저·로그·응답에 노출하지 않는다.
7. **추측으로 채우지 않기.** 자료에 없으면 빈칸이나 질문으로 남긴다.

이 중 하나라도 어기는 결함은 **P0**이다. 발견하면 다른 작업보다 먼저 처리한다.

## 6. 명령 모음

작업 위치는 `스카이브 연습/`이다. `.env`는 한 단계 위(git 루트)에 있다. Windows에서 한글 출력이 깨지면 `PYTHONUTF8=1`을 설정한다.

| 목적 | 명령 | 비고 |
|---|---|---|
| 결정론적 테스트 (필수 관문) | `uv run pytest -q` | 무료, 약 30초 |
| 테스트 하나 | `uv run pytest tests/test_x.py -q -k 이름` | |
| 문법 검사 | `uv run python -m compileall -q skive scripts tests` | lint 대용 |
| Lint | 없음 | `uvx`는 이 PC의 앱 제어 정책에 막힌다. ruff를 dev 의존성에 넣는 것은 사람 승인 사항 |
| 서버 | `uv run uvicorn skive.server:app --host 127.0.0.1 --port <자기 포트>` | Windows+한글 경로에서 `--reload`는 WinError 87로 죽는다. 쓰지 않는다 |
| 분석 워커 | `uv run python -m skive.drive_worker` | |
| 레거시 단일 사용자 서버 | `uv run uvicorn skive.legacy_server:app --host 127.0.0.1 --port 8011` | 동결. 사람 전용 |
| Live E2E (API) | `uv run python tests/live_drive_<이름>.py` | Supabase 키 필요, 임시 계정을 만들고 지운다 |
| Live E2E (브라우저) | `uv run --with playwright python tests/live_drive_<이름>_ui.py` | **반드시 `SKIVE_TEST_BASE_URL`을 자기 포트로 지정.** 지정하지 않으면 사람의 8010 서버를 친다 |
| 마이그레이션 적용 | `uv run python -c "from skive.db import run_migrations; print(run_migrations())"` | **사람 승인 필수** (공유 Supabase) |
| 로컬 폴더 가져오기 | `uv run python -m scripts.import_local_drive '<경로>' --user-email '<계정>'` | 사람 전용 운영 도구 |

`tests/live_*.py`는 pytest가 수집하지 않는다(파일명이 `test_`로 시작하지 않음). 유료 모델을 부르는 live 테스트는 §8의 비용 상한을 따른다.

## 7. 병행 작업 규칙

- **포트:** 8010·8011은 사람 전용. Claude는 8020~8029, Codex는 8030~8039.
- **프로세스:** 자기가 띄우지 않은 프로세스는 종료하지 않는다. 포트가 막혀 있으면 PID를 확인해 점유표에 적고 사람에게 묻는다.
- **파일:** 다른 에이전트가 점유표에 적어둔 파일은 수정하지 않는다. 역할상 Claude는 앱 코드를 고치지 않으므로 보통은 겹치지 않는다.
- **커밋:** 에이전트는 커밋할 수 있다. 기능 하나에 커밋 하나를 원칙으로 한다.
  - 메시지 형식: `[codex] F-012: 한 줄 요약` / `[claude] harness: 한 줄 요약`
  - 자기가 바꾼 파일만 파일 이름으로 지정해서 올린다(`git add -A` 금지). 다른 쪽의 커밋 안 된 변경을 대신 커밋하지 않는다.
  - `push`, 브랜치 병합, `--amend`(남의 커밋), `reset --hard`, force 작업은 사람만 한다.
- **공유 Supabase:** 개발·시험·사람의 실제 자료가 **같은 프로젝트**에 있다. 에이전트는 사람 계정 데이터를 읽기(SELECT)만 한다. 쓰기·삭제는 임시 계정에서만 하고 끝나면 정리한다.
- **실행 환경:** Codex와 Claude 모두 이 PC의 같은 작업 폴더에서 로컬로 실행한다. 브랜치는 `skive-agent` 하나를 같이 쓴다.
- **공개 저장소:** 원격 `github.com/bsj4333/skybe-agent`는 **공개**다. 커밋하는 모든 것은 push되는 순간 누구나 볼 수 있다.
  - 실사용자 자료(실명·학교·실제 프로젝트 내용·자소서·대화 기록), `.env`, 키, DB 연결 문자열, Supabase 계정 ID를 커밋하지 않는다. 예시가 필요하면 `samples/`의 합성 자료나 `[비밀번호]` 같은 자리표시자를 쓴다.
  - 평가 기록(`harness/reviews/`)에도 실제 원문을 길게 옮기지 않는다. 파일 경로·위치·수치 요약까지만 적는다.

## 8. 반복 제한·중단 조건·사람 승인

- **세션당 항목 최대 2개.** 같은 검사가 **3번 연속 실패하면** 멈추고 `blocked`로 바꾼 뒤 원인·시도한 것을 적는다.
- **검토 반려 반복:** 같은 항목이 `changes_requested`를 2번 받으면 사람이 설계를 다시 본다.
- **유료 모델 비용:** 세션당 예상 **$2 초과** 시 먼저 묻는다. 여러 폴더 재분석처럼 대량 호출은 항상 먼저 묻는다(2026-09-28 선불 크레딧 소진 전례). 호출이 `insufficient_quota`/`credit_balance_exhausted`로 실패하면 재시도하지 말고 `blocked`로 두고 사람에게 알린다.
- **회귀:** 결정론적 테스트가 하나라도 새로 깨지면 자기 변경을 되돌리고 보고한다.
- **즉시 멈추고 사람에게 묻는 경우:**
  - 마이그레이션 적용, 데이터·Storage 삭제, 사람 계정 데이터 수정
  - `.env`·키·의존성 변경, push·병합·force 작업
  - 제품 불변조건(§5)에 영향을 주는 변경
  - 테스트를 약하게 바꿔야만 통과하는 상황
  - 다른 에이전트의 점유 파일·프로세스를 건드려야 하는 상황
  - 설계와 실제 코드가 크게 달라 설계를 바꿔야 하는 상황

## 9. 문서 규칙

**하나의 사실은 한 곳에만 쓴다.** 새 상태 보고서를 루트에 만들지 않는다.

| 쓰려는 것 | 쓰는 곳 |
|---|---|
| 지금 상태, 누가 무엇을 하는지, 세션 기록 | `harness/progress.md` |
| 기능·버그와 완료 조건, 검증 증거 | `harness/feature_list.json` |
| 여러 작업에 걸친 설계 | `harness/build/phase-NN-이름.md` (양식: `_TEMPLATE.md`) |
| 여러 단계에 걸친 공통 설계 (예: 모델 배치) | `harness/build/design-주제.md` |
| 시뮬레이션·검토·실험 결과 | `harness/reviews/YYYY-MM-DD-주제.md` |
| 설치·키·실행 방법 | `DRIVE_SETUP.md` (설정 부분만 갱신) |

기존 문서의 지위 (2026-09-29 기준):

| 문서 | 지위 |
|---|---|
| `PROJECT_STATUS.md` | **동결.** 2026-09-22~28 기록. 수정하지 않는다 |
| `SKIVE_NEXT_PLAN.md`, `SKIVE_NEXT_PLAN_DeepAgents_반영본.md` | 설계 배경 참고. 동결 |
| `SKIVE_IMPLEMENTATION_2026-09-28.md`, `SKIVE_SUMMARY_DESIGN.md` | 9/28 시점 기록. 동결. 현재 상태는 `progress.md` |
| `SKIVE_REVIEW_2026-09-23.md`, `DRIVE_*_EVAL_2026-09-23.md`, `AGENTS_API_COMPARISON_2026-09-28.md` | 과거 평가 기록. 새 평가는 `harness/reviews/` |
| `SCHEMA.md` | 옛 스키마(0001) 설명. 현재 스키마의 기준은 `migrations/` |
| `DRIVE_SETUP.md` | 설치·키·실행 안내로 계속 사용 |
