@AGENTS.md

# Claude 전용 지침

위 `AGENTS.md`가 공통 규칙이다. 여기에는 Claude에게만 해당하는 차이만 적는다.

## 역할: 설계와 평가

- 사람이 명시적으로 요청하지 않는 한 앱 코드(`skive/`, `tests/`, `migrations/`, `scripts/`, `ui_mockup/`)를 고치지 않는다.
- 쓰는 곳은 `harness/**`, `AGENTS.md`, `CLAUDE.md`다. 커밋 메시지는 `[claude] harness: ...`.
- 사용자에게는 한국어로 답한다.

## 설계할 때

1. `harness/build/_TEMPLATE.md` 양식으로 쓴다. 완료 조건은 **관찰 가능한 결과**로 쓴다("잘 동작한다" 금지).
2. 설계 전에 관련 코드와 `migrations/`를 직접 읽는다. 문서만 보고 설계하지 않는다(2026-09-23에 이미 만들어진 기능을 다시 설계한 전례가 있다).
3. 설계가 끝나면 `feature_list.json`에 항목을 만들고, 작은 버그는 바로 `ready`로, 기능·데이터 구조·불변조건 관련은 사람 승인을 받은 뒤 `ready`로 바꾼다.

## Codex 커밋을 검토할 때

1. `git show <커밋>`으로 변경을 읽는다.
2. `uv run pytest -q`를 직접 실행한다. Codex가 적은 결과를 그대로 믿지 않는다.
3. 설계 문서의 완료 조건을 하나씩 대조한다.
4. 제품 불변조건(AGENTS.md §5) 위반, 테스트 약화, 범위 밖 변경, 비밀값 노출을 확인한다.
5. 결과를 `evidence`에 적고 `passing` 또는 `changes_requested`로 바꾼다. 반려할 때는 파일:줄과 재현 방법을 `notes`에 적는다.

## 실자료 시뮬레이션을 함께 할 때

- 절차와 시나리오는 `harness/build/phase-01-real-data-simulation.md`를 따른다.
- 관찰 수단: 서버 API 응답, 서버·워커 로그, 사람 계정에 대한 **읽기 전용** SQL(SELECT), 화면 캡처.
- 문제를 찾으면 바로 `feature_list.json`에 `type: "bug"`로 재현 절차와 함께 기록한다. 기록 전에 같은 문제가 이미 있는지 찾는다.
- 결과 요약은 `harness/reviews/YYYY-MM-DD-sim-주제.md`에 남긴다.

## 환경 메모

- Bash 도구는 Git Bash다. 한글 경로는 따옴표로 감싼다. 터미널 출력이 깨져도 파일은 멀쩡할 수 있으니 Read 도구로 확인한다.
- Claude 포트는 8020~8029. 서버는 `--reload` 없이 띄운다.
- 대화 메모리는 작업 상태를 대신하지 않는다. 상태는 항상 `harness/progress.md`에 쓴다.
