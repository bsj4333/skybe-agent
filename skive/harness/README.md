# SKIVE 하네스 사용법 (사람용)

에이전트용 규칙은 `../AGENTS.md`에 있다. 이 파일은 사람이 Codex와 Claude를 어떻게 돌리는지만 설명한다.

## 파일 구성

| 파일 | 내용 | 주로 쓰는 쪽 |
|---|---|---|
| `goal.md` | 목표·비목표·단계·성공 기준 | Claude, 사람 |
| `feature_list.json` | 기능·버그 목록, 완료 조건, 검증 증거 | 전부 |
| `progress.md` | 지금 상태, 작업 점유표, 열린 질문, 세션 로그 | 전부 |
| `build/phase-NN-*.md` | 단계별 설계 (양식: `_TEMPLATE.md`) | Claude |
| `reviews/*.md` | 시뮬레이션·검토·실험 결과 | Claude |

## 기본 흐름

```
사람이 실제 자료로 시뮬 ── Claude가 관찰하고 결함 기록 (feature_list: failing)
                              │
                     Claude가 설계 또는 바로 ready 처리
                              │
                     Codex가 구현·테스트·커밋 (review)
                              │
                     Claude가 검토 (passing / changes_requested)
                              │
                     사람이 같은 시나리오로 다시 확인
```

- Codex와 Claude를 **동시에** 켜도 된다. Claude는 앱 코드를 고치지 않으므로 파일이 겹치지 않는다.
- push와 브랜치 병합은 사람이 한다.

## 복사해서 쓰는 지시문

**Codex에게: 다음 작업하기**
```
AGENTS.md, harness/progress.md, harness/feature_list.json을 읽고,
ready 또는 failing 상태 중 우선순위가 가장 높은 항목 하나를 AGENTS.md 규칙대로 처리해.
끝나면 review로 바꾸고 progress.md에 세션 로그를 남겨.
```

**Codex에게: 특정 항목**
```
AGENTS.md 규칙대로 F-100만 처리해. 다른 항목은 건드리지 마.
```

**Claude에게: 검토하기**
```
review 상태 항목을 CLAUDE.md의 검토 절차대로 검토해줘.
```

**Claude에게: 시뮬 같이 하기**
```
phase-01 S4 시나리오를 화력발전소 자료로 같이 돌리자. 내가 화면에서 질문할게.
```

**Claude에게: 설계하기**
```
B-0xx 문제를 설계 문서로 만들어줘. 완료되면 나한테 승인받고 ready로 바꿔.
```

## 사람만 할 수 있는 것

- 마이그레이션을 공유 Supabase에 적용하는 것
- `.env`·키·의존성 변경 승인
- `real_data`·`manual` 검증 통과 처리
- push, 병합, 되돌리기
- 기능·데이터 구조·불변조건 관련 설계의 `ready` 승인
