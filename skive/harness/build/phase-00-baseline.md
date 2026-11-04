# phase-00: 기준선 고정

> 작성: Claude · 상태: ready · 관련 항목: F-100, F-101, F-102, F-103

## 1. 목적

하네스 도입 전에 Codex가 진행하던 변경, 이미 DB에 적용된 마이그레이션, 흩어진 상태 문서가 섞여 있다. 이 상태에서 새 작업을 시작하면 무엇이 누구의 변경인지 구분할 수 없다. 하나의 깨끗한 기준선을 만든다.

## 2. 해야 할 일

| 순서 | 담당 | 일 | 항목 |
|---|---|---|---|
| 1 | Codex | 진행 중인 변경을 정리해 커밋한다. 특히 **이미 Supabase에 적용된 `migrations/0016_drive_project_summaries.sql`** 과 `skive/drive_project_summary.py`, `tests/test_drive_project_summary.py`, `scripts/compare_agents_api.py`, 수정된 `drive_worker.py`·`drive_workspace.py`·`server.py`·`skive_drive.html` | F-100 |
| 2 | Codex | `uv run pytest -q` 결과를 `progress.md` 기준선에 적는다 | F-100 |
| 3 | 사람 | 원격 저장소 공개 여부 확인. 실사용자 자료(`data/store/2. 화력발전소 이상탐지/`, `data/profile/`, `data/user.json`)를 계속 git으로 추적할지 결정 | F-101 |
| 4 | Claude | Codex 커밋 뒤, 동결 문서(`PROJECT_STATUS.md` 등) 맨 위에 "동결, 최신은 harness/progress.md" 안내 한 줄 추가 | F-102 |
| 5 | Codex | Live 테스트가 `SKIVE_TEST_BASE_URL` 없이 실행되면 사람의 8010 서버를 치지 않도록 바꾼다 (환경변수 필수화 또는 명확한 오류) | F-103 |
| 6 | 사람 (선택) | ruff를 dev 의존성으로 추가할지 결정 | F-104 |

4번은 1번 이후에 한다. Codex의 커밋 안 된 변경이 같은 문서에 있어서 먼저 고치면 섞인다.

## 3. 완료 조건

- [ ] (deterministic) `git status`에 실사용자 자료 외의 커밋 안 된 변경이 없다
- [ ] (deterministic) `uv run pytest -q`가 85 passed 이상, 새 실패 0
- [ ] (deterministic) `migrations/0016_*.sql`이 커밋에 포함돼 있다
- [ ] (manual) 사람이 데이터 추적 방침을 정하고 `progress.md`에 기록했다
- [ ] (deterministic) `SKIVE_TEST_BASE_URL` 없이 live UI 테스트를 실행하면 8010에 요청하지 않고 종료한다

## 4. 위험

- 1번 커밋 때 Codex가 사람의 자료나 다른 쪽 파일을 같이 올릴 수 있다 → 파일 이름을 지정해서 `git add`한다.
- 데이터 추적을 끊을 때 `git rm --cached`는 로컬 파일을 지우지 않지만, 이미 원격에 올라간 이력은 남는다. 공개 저장소라면 이력 정리는 별도 판단이 필요하다.
