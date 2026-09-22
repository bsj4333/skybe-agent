# SKIVE 다음 실행 계획 — DeepAgents 반영본

작성일: 2026-09-22  
대상: 현재 로컬 SKIVE 구현 → 신뢰 가능한 개인 에이전트 기반 완성  
관계 문서: `SKIVE_NEXT_PLAN.md`는 원래의 전체 고도화 계획으로 그대로 보존한다.

> 이 문서는 DeepAgents를 새 프레임워크로 도입하는 계획이 아니다. 현재 FastAPI + LangGraph + SKIVE 도메인 구조를 유지하면서, DeepAgents에서 검증된 하네스 설계 원칙을 필요한 부분부터 적용하는 실행 문서다.

## 1. 이 문서의 결론

SKIVE는 지금 에이전트 수나 기능 수를 늘리는 것보다 다음 여섯 가지를 먼저 완성해야 한다.

1. 서버가 사용자·세션·활성 경험 범위를 결정하고 모든 도구에 강제한다.
2. 대화를 서버에 저장하고 중단·재접속·재개할 수 있게 한다.
3. 정정된 기억을 새 사실 버전으로 다루고 과거 검증 상태를 상속하지 않는다.
4. 모델 호출·도구 호출·시간·재시도에 각각 실행 예산을 둔다.
5. 프롬프트의 고정 영역을 정리하고 실제 캐시 효과와 비용을 측정한다.
6. 위 동작을 외부 LLM 없이 반복 검증할 회귀 테스트로 고정한다.

DeepAgents 전체를 설치하거나 현재 `chat.py`, `agent.py`를 다시 작성하지 않는다. DeepAgents의 가치인 **실행 문맥, 미들웨어, 백엔드, 영속 상태, 컨텍스트 관리, 승인 경계**를 현재 구조에 이식한다.

## 2. 적용 원칙

### 2.1 에이전트보다 하네스가 권한을 가진다

모델은 어떤 도구를 사용할지 제안할 수 있지만 다음 항목은 코드가 결정한다.

- 현재 사용자와 활성 경험 범위
- 읽거나 쓸 수 있는 데이터
- 모델·도구 호출 횟수
- 재시도 가능 여부
- 장기기억 반영 여부
- 승인 없이 실행할 수 있는 작업
- 중단 사유와 사용자에게 공개할 오류

프롬프트에 “다른 경험을 읽지 마라”라고 쓰는 것은 권한 통제가 아니다. 권한은 도구 실행 직전에 다시 검사한다.

### 2.2 상태를 세 종류로 분리한다

| 상태 | 용도 | SKIVE 적용 |
|---|---|---|
| 요청 문맥 | 한 실행 동안 바뀌지 않는 사용자·권한·예산 | `RequestContext` |
| 스레드 상태 | 현재 대화·도구 실행·중단 후 재개 | LangGraph checkpointer |
| 장기기억 | 세션을 넘어 유지하는 사실·선호·경험 | 사실/경험 저장소 |

LangGraph 공식 문서도 checkpointer를 스레드 단기 상태, store를 교차 스레드 장기 데이터로 구분한다. 체크포인터를 추가했다고 사용자 권한이나 장기기억 정책이 자동으로 생기는 것은 아니다. [LangGraph Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)

### 2.3 항상 넣을 정보와 필요할 때 찾을 정보를 분리한다

- 항상 포함: SKIVE 역할, 안전 규칙, 답변 형식, 최소 사용자 프로필
- 필요할 때 로드: 자소서 작성 기준, 회고 질문법, 직무별 평가 기준
- 검색으로 가져오기: 경험 사실, 원문 근거, 공부 기록, 공고 요구사항
- 모델에 넣지 않기: 사용자 ID, 권한, DB 연결, API 키, 내부 저장 경로

DeepAgents의 현재 설계도 memory는 항상 로드하므로 작게 유지하고, 상세 워크플로는 skill 또는 retrieval로 필요할 때 불러오는 방향이다. [DeepAgents Context Engineering](https://docs.langchain.com/oss/python/deepagents/context-engineering)

## 3. P0 범위: 지금 바로 구현할 것

P0는 기능 확장이 아니라 현재 제품 약속을 신뢰할 수 있게 만드는 작업이다. 각 묶음은 독립적으로 검증하고, 앞 묶음의 완료 조건을 통과한 뒤 다음 묶음으로 이동한다.

### P0-1. 실패 사례를 회귀 테스트로 먼저 고정

#### 목적

기존 문제를 수정하는 동안 다른 경로가 조용히 깨지는 것을 막는다.

#### 고정할 최소 사례

| ID | 입력 | 반드시 보장할 결과 |
|---|---|---|
| R01 | 다른 경험 ID를 현재 scope 도구에 전달 | 조회 거부 또는 `out_of_scope` |
| R02 | 검증된 사실의 문장을 다른 수치로 정정 | 기존 `verified`, `sources`를 상속하지 않음 |
| R03 | 팀 문장 인용으로 개인 Kubernetes 구축 주장 생성 | `supported` 처리하지 않음 |
| R04 | 판정자가 존재하지 않는 문장 또는 일부 문장만 반환 | 작성 결과 통과 금지 |
| R05 | 근거 `0.71`을 답변에서 `71% 정확도`로 변경 | 지표·단위 불일치 탐지 |
| R06 | 같은 도구와 같은 인수를 반복 호출 | 설정한 반복 제한에서 종료 |
| R07 | 브라우저 새로고침 후 같은 `session_id`로 재접속 | 서버 대화 상태 복원 |
| R08 | scope 변경 후 이전 경험을 질문 | 이전 scope 문맥과 도구 접근 차단 |

#### 구현 지침

- 기존 임시 진단을 `tests/`의 결정론적 테스트로 옮긴다.
- 외부 LLM·실제 Supabase 호출 없이 fake model, fake repository를 사용한다.
- 실패를 먼저 재현한 다음 구현을 바꾼다.
- 테스트가 검증하는 범위와 검증하지 않는 범위를 이름과 주석에 명시한다.

#### 완료 기준

- 위 8개 사례가 수정 전 실패 또는 위험을 재현한다.
- 수정 후 모두 통과한다.
- 실제 사용자 데이터 파일을 테스트 중 변경하지 않는다.

### P0-2. `RequestContext`와 모든 도구의 `ScopeGuard`

#### 목적

사용자와 경험 범위를 프롬프트가 아니라 코드로 강제한다.

#### 권장 문맥

```python
@dataclass(frozen=True)
class RequestContext:
    user_id: str
    session_id: str
    active_scope_id: str | None
    role: str
    allowed_tool_groups: frozenset[str]
    max_model_calls: int
    max_tool_calls: int
    deadline_at: datetime
```

이 값은 요청 본문이 주장한 사용자 ID를 그대로 신뢰해 만들지 않는다. 서버 인증 정보와 서버 저장 세션을 기준으로 생성한다. 현재 인증이 없는 로컬 단계에서는 고정 개발 사용자라도 서버가 발급한다.

#### 모든 도구가 따를 규칙

1. 도구 입력에서 `user_id`를 받지 않는다.
2. `RequestContext.user_id`를 repository 조회 조건에 항상 포함한다.
3. 경험 단위 도구는 `active_scope_id`와 대상 ID의 소속을 검사한다.
4. 읽기와 쓰기 도구를 그룹으로 분리한다.
5. 범위 오류는 데이터 존재 여부를 노출하지 않는 구조화 오류로 반환한다.
6. 모델이 우회 인수를 만들더라도 repository 계층에서 한 번 더 검사한다.

#### 우선 적용 대상

- `get_profile`
- `list_experiences`
- `get_experience`
- `get_evidence`
- `search_study`
- `get_study`
- 메모·정정·경험 쓰기 도구
- 공고 및 작성 결과 조회

#### 권장 흐름

```text
FastAPI 인증/개발 사용자
        ↓
RequestContext 생성
        ↓
도구 호출
        ↓
ScopeGuard + 입력 검증
        ↓
서비스 계층
        ↓
사용자·scope 조건이 포함된 repository
```

#### 완료 기준

- 다른 경험 ID를 직접 넣어도 모든 읽기·쓰기 도구가 같은 정책으로 차단한다.
- scope 전환 시 이전 scope의 메시지와 검색 결과를 새 답변에 사용하지 않는다.
- 전역 관리 도구가 필요하면 일반 도구와 분리하고 명시적 관리자 문맥에서만 노출한다.

### P0-3. 서버 세션과 영속 checkpointer

#### 목적

브라우저 변수에만 있는 `chatHistory`를 서버가 관리하는 대화 스레드로 바꾼다.

#### 최소 데이터

```text
sessions
- session_id
- user_id
- active_scope_id
- status: active / ended / expired
- created_at / updated_at / ended_at

messages 또는 checkpointer
- session_id(thread_id)
- 순서
- role
- content
- tool_call/result metadata
- created_at
```

#### 구현 순서

1. 서버가 `session_id`를 발급한다.
2. LangGraph 호출에 같은 값을 `thread_id`로 전달한다.
3. 개발 단계에는 `SqliteSaver`, 운영 후보에는 PostgreSQL checkpointer를 사용한다.
4. UI는 전체 history를 신뢰 원본처럼 매 요청마다 보내지 않는다.
5. `/api/chat/end`를 실제 종료 UI와 연결한다.
6. 새로고침 시 현재 세션 또는 최근 세션을 복원한다.
7. scope 변경은 새 세션을 만들거나 명시적인 분기 메시지와 정책을 남긴다. 초기에는 새 세션 방식이 안전하다.

#### 주의사항

- `MemorySaver`는 프로세스 재시작 후 사라지므로 개발 시연 외에는 완료로 보지 않는다.
- checkpointer에 저장된 메시지를 장기기억으로 자동 승격하지 않는다.
- 대화 전문과 사용자에게 확정된 사실을 같은 저장 구조로 취급하지 않는다.
- 세션 종료는 장기기억 저장 성공을 의미하지 않는다.

#### 완료 기준

- 새로고침과 서버 재시작 후 대화가 의도한 범위에서 복원된다.
- 종료 API가 중복 호출돼도 공부 기록이나 요약이 중복 저장되지 않는다.
- 서로 다른 `session_id`와 `scope_id`의 메시지가 섞이지 않는다.

### P0-4. 기억 정정과 출처 상태의 버전화

#### 목적

사용자 정정이 과거 문서에 의해 검증된 새로운 사실처럼 보이는 문제를 없앤다.

#### 최소 상태 모델

| 필드 | 값 예시 | 의미 |
|---|---|---|
| `provenance_type` | `document`, `user_statement`, `derived` | 어디서 나온 주장인지 |
| `review_state` | `proposed`, `accepted`, `rejected` | 사용자가 검토했는지 |
| `evidence_status` | `unlinked`, `quote_matched`, `supported`, `contradicted`, `needs_review` | 근거가 무엇을 지지하는지 |
| `lifecycle` | `active`, `superseded`, `retracted` | 현재 사용 가능한 버전인지 |
| `owner` | `self`, `team`, `other`, `unknown` | 행동과 결과의 주체 |

#### 정정 규칙

1. 기존 사실을 제자리에서 덮어쓰지 않는다.
2. 새 `fact_version`을 만들고 `supersedes_id`를 연결한다.
3. 기존 문서 인용과 `verified`를 자동 상속하지 않는다.
4. 사용자 정정은 `provenance_type=user_statement`로 저장한다.
5. 원문 인용이 새 문장을 실제로 지지할 때만 근거를 다시 연결한다.
6. 역할·수치·기간·성과 변경은 의존 산출물을 `stale`로 표시한다.
7. 모델이 제안한 기억은 `proposed` 상태이며 승인 전 작성 근거로 쓰지 않는다.

DeepAgents의 현재 메모리 구현도 저장 메모리를 오래되거나 잘못됐을 수 있는 비신뢰 데이터로 취급하고, 사용자 메시지와 도구로 검증된 근거가 우선한다고 명시한다. SKIVE는 여기에 사용자 승인과 사실 버전을 추가한다. [DeepAgents MemoryMiddleware](https://github.com/langchain-ai/deepagents/blob/main/libs/deepagents/deepagents/middleware/memory.py)

#### 완료 기준

- 수치와 역할 정정 후 이전 값이 최신 조회·검색·새 작성물에 재등장하지 않는다.
- 과거 산출물은 자동으로 조용히 바뀌지 않고 `갱신 필요`로 표시된다.
- 사용자 진술, 문서 근거, AI 해석이 UI와 API에서 구분된다.

### P0-5. 근거 검증과 작성기의 문장 단위 폐쇄성

#### 목적

“인용문이 존재한다”와 “인용문이 해당 주장을 지지한다”를 구분하고, 판정되지 않은 문장이 결과물에 남지 않게 한다.

#### 추출 검증

- 인용문 존재 여부
- 주장과 인용의 의미적 지지 여부
- 주체 일치 여부
- 수치의 지표·값·단위·대상·조건 일치 여부
- 파일 버전·페이지·청크 위치

#### 작성 검증

1. 앱이 생성 전 또는 생성 직후 각 문장에 안정적인 `sentence_id`를 부여한다.
2. 판정기는 원문 문자열 대신 `sentence_id`별 결과를 반환한다.
3. 입력한 전체 문장 ID와 판정 결과 ID 집합이 일치하지 않으면 통과시키지 않는다.
4. 삭제·수정 후 최종 결과를 다시 검사한다.
5. 문장에 연결된 `fact_id`, `fact_version`, `source_ref`를 저장한다.
6. 근거가 부족한 문장은 몰래 보완하지 않고 사용자 질문 또는 `근거 부족`으로 남긴다.

#### 완료 기준

- 검사 누락 문장과 알 수 없는 문장 ID가 있으면 결과 상태가 성공이 되지 않는다.
- `0.71`, `71%`, `정확도`, `F1-score`처럼 값은 관련돼 보여도 의미가 다른 사례를 구분한다.
- 최종 결과의 모든 검증 가능한 사실 문장을 근거 또는 사용자 확인 사실까지 추적할 수 있다.

### P0-6. 실행 예산, 반복 차단, 구조화 오류

#### 목적

`recursion_limit` 하나에 의존하지 않고 비용과 실패를 통제한다.

DeepAgents 현재 구현의 높은 recursion limit은 복잡한 작업을 허용하는 프레임워크 상한이지 SKIVE의 안전한 기본값이 아니다. SKIVE의 기존 `20/30`도 모델·도구·비용 제한을 대신하지 않는다.

#### 별도로 기록하고 제한할 항목

```text
model_calls
tool_calls_total
tool_calls_by_name
same_tool_same_args_count
retry_count
input_tokens
output_tokens
cached_tokens
cache_write_tokens
elapsed_ms
estimated_cost
```

#### 초기값 예시

| 흐름 | 모델 호출 | 도구 호출 | 동일 호출 | 시간 |
|---|---:|---:|---:|---:|
| 일반 채팅 | 4~6 | 8~12 | 2 | 30~60초 |
| 경험 분석 | 단계별 명시 | 단계별 명시 | 1~2 | worker 정책 |
| 자소서 작성·검증 | 계획/작성/검증별 명시 | 조회 도구 제한 | 2 | worker 정책 |

숫자는 출시 약속이 아니라 시작 설정이다. 실제 run 로그와 평가 결과로 조정한다.

#### 오류 분류

| 오류 종류 | 처리 |
|---|---|
| 사용자가 고칠 수 있는 입력 오류 | 안전한 코드와 수정 방법 반환 |
| 일시적 네트워크·rate limit | 제한된 exponential backoff |
| scope·권한 오류 | 재시도 없이 차단 |
| 근거 부족 | 실패가 아니라 질문 또는 불충분 상태 |
| 예상하지 못한 내부 오류 | 실행 중단, `run_id` 기록, 내부 세부정보 비공개 |

원본 예외 문자열 전체를 모델이나 사용자에게 그대로 보내지 않는다. 오류 코드, 재시도 가능 여부, 안전한 설명을 구조화한다. LangChain 공식 미들웨어도 도구 오류 정제, 도구/모델 재시도, 모델·도구 호출 제한을 서로 다른 정책으로 제공한다. [LangChain Prebuilt Middleware](https://docs.langchain.com/oss/python/langchain/middleware/built-in)

#### 완료 기준

- 같은 도구 호출 반복, 시간 초과, 모델 호출 초과가 각각 다른 종료 사유로 기록된다.
- 권한 오류나 검증 오류를 재시도하지 않는다.
- 예산 초과 시 확인된 범위까지만 답하고, 완료하지 않은 작업을 성공으로 표시하지 않는다.

### P0-7. 프롬프트 안정화와 캐시 계측

#### 목적

캐시를 기대하는 데서 끝내지 않고, 같은 고정 prefix가 실제로 재사용되는지 측정한다.

#### 프롬프트 순서

```text
[고정]
1. SKIVE 역할·안전 규칙
2. 출력 형식과 근거 정책
3. 안정된 순서의 도구 스키마
4. prompt_version / toolset_version
──────── 캐시 가능한 경계 ────────
[준고정]
5. 최소 사용자 프로필
6. 활성 scope 요약
[동적]
7. 검색된 사실과 근거
8. 최근 대화 또는 요약
9. 현재 질문
```

#### 적용 규칙

- 사용자 ID, API 키, 권한, 현재 시각을 고정 prefix 앞에 넣지 않는다.
- 도구 이름·설명·JSON schema·순서를 요청마다 바꾸지 않는다.
- 사용하지 않는 도구는 에이전트 유형별로 제거한다.
- 거대한 `AGENTS.md`를 항상 주입하지 않는다.
- 프롬프트 변경 시 `prompt_version`을 올린다.
- 현재 모델에서 제공하는 usage 필드를 실제 응답에서 확인한 뒤 저장한다.

#### API별 주의

- OpenAI: 지원 모델에서 prefix 캐싱이 적용되지만 모델 세대별 최소 길이·retention·명시적 breakpoint 지원이 다르다. `cached_tokens`와 가능하면 `cache_write_tokens`를 기록한다. [OpenAI Prompt Caching](https://developers.openai.com/api/docs/guides/prompt-caching)
- Anthropic: 자동 또는 명시적 `cache_control`을 사용하며 기본 5분, 선택적 1시간 TTL이 있다. 매번 바뀌는 블록 앞에서 안정된 prefix를 끝낸다. [Anthropic Prompt Caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)
- Gemini: 2.5 이상에서 implicit caching이 기본 제공되지만 모델별 최소 입력 길이가 있다. `total_cached_tokens`를 확인한다. [Gemini Context Caching](https://ai.google.dev/gemini-api/docs/caching)

현재 기본 모델이 `gpt-4o-mini`/`gpt-4o`인 경로에 GPT-5.6 전용 옵션을 그대로 넣지 않는다. 모델별 어댑터가 지원 여부를 확인하게 하고 도메인 코드에는 제공자별 필드를 흩뿌리지 않는다.

#### LLM 프롬프트 캐시와 별개로 둘 캐시

| 캐시 | 권장 키 | 무효화 |
|---|---|---|
| 임베딩 | 원문 hash + chunker version + embedding model/dimension | 원문·청커·모델 변경 |
| 검색 결과 | user + scope + query + index revision + retrieval policy | 사실·청크·검색 정책 변경 |
| 추출 결과 | source hash + parser + prompt + model version | 입력 또는 파이프라인 변경 |

개인화된 일반 채팅 응답 전체는 기본적으로 캐싱하지 않는다. checkpointer도 캐시가 아니라 실행 상태 저장소다.

#### 완료 기준

- run마다 모델, 프롬프트 버전, 입력/출력/캐시 토큰, 지연, 예상 비용이 남는다.
- 동일한 개발 시나리오를 반복해 cache hit와 총비용을 비교할 수 있다.
- 캐시 miss가 발생했을 때 toolset 또는 prompt version 차이를 추적할 수 있다.

## 4. P0 구현 순서와 변경 경계

### 권장 순서

```text
회귀 테스트 기준선
    ↓
RequestContext + ScopeGuard
    ↓
세션 + checkpointer
    ↓
사실 버전과 정정 정책
    ↓
문장 단위 근거 검증
    ↓
실행 예산과 오류 정책
    ↓
프롬프트·캐시 계측
```

ScopeGuard와 사실 버전은 병렬로 설계할 수 있지만, 한 커밋에서 여러 도메인을 대규모 재작성하지 않는다.

### 예상 변경 위치

| 영역 | 우선 확인 파일 | 목표 |
|---|---|---|
| 요청 문맥 | `skive/server.py`, `skive/user.py` | 서버 발급 사용자·세션·scope |
| 도구 경계 | `skive/chat.py`, `skive/agent.py` | 공통 context 주입과 guard |
| 서비스/저장 | `skive/store.py`, `skive/facts.py`, `skive/corrections.py` | 사용자·scope 조건과 사실 버전 |
| 근거 검증 | `skive/analyzer.py`, `skive/verify.py` | 주장·주체·수치·인용 분리 |
| 작성 | `skive/writer.py`, `skive/apply.py` | 문장 ID, 전체 판정, 최종 재검증 |
| 세션 UI | `ui_mockup/skive_ui.html` | session_id, 종료, 복원, scope 전환 |
| 테스트 | `tests/` | R01~R08 결정론적 회귀 |
| 관측 | 새 `observability` 경계 또는 공통 모듈 | run budget와 usage 기록 |

새 디렉터리 구조를 먼저 만들고 코드를 한꺼번에 옮기지 않는다. 기능을 바꿀 때 해당 경계만 추출한다.

## 5. P0 완료 판정표

다음 항목을 모두 충족해야 P0 완료로 기록한다.

- [ ] 다른 경험·사용자·scope 접근 회귀 테스트 0건 실패
- [ ] 정정 후 이전 사실이 최신 조회와 새 작성물에 재등장하지 않음
- [ ] 수정 사실이 이전 문서 검증 상태와 출처를 자동 상속하지 않음
- [ ] 모든 최종 사실 문장이 사실 버전 또는 명시적 부족 상태로 추적됨
- [ ] 새로고침·서버 재시작 후 세션 복원 확인
- [ ] scope 전환 뒤 이전 범위 문맥 분리 확인
- [ ] 모델·도구·반복·시간 예산 초과를 각각 재현하고 종료 사유 확인
- [ ] usage에 prompt/tool/model version과 토큰·지연 기록
- [ ] 외부 모델 없는 테스트가 일반 개발 과정에서 반복 실행 가능
- [ ] `PROJECT_STATUS.md`에는 실제로 검증한 항목만 완료로 반영

## 6. P0에서 하지 않을 것

아래 작업은 가치가 없어서가 아니라 P0의 신뢰성 문제를 흐리므로 보류한다.

- DeepAgents 패키지로 전면 이전
- 범용 셸·파일 삭제 도구 제공
- 다수 서브에이전트와 자동 병렬 위임
- Neo4j 또는 별도 그래프 DB
- 전체 프론트엔드 재작성
- 모델 파인튜닝
- 자동 지원서 제출과 외부 메시지 전송
- 모든 사용자 기억의 자동 저장
- 여러 외부 서비스 동시 연결
- 캐시 hit를 만들기 위해 불필요한 텍스트를 프롬프트에 추가

---

# 부록 A. P1 — 실제 학생 사용과 운영 경계

P1은 P0가 완료된 뒤, 개발자 본인의 로컬 자료가 아닌 다른 학생이 실제 파일로 처음부터 끝까지 사용할 수 있게 만드는 단계다.

## A.1 시작 조건

- P0 완료 판정표 통과
- 범위·정정·세션 회귀 테스트가 CI 또는 반복 실행 절차에 포함
- 한 경험에 대해 업로드 전 데이터부터 결과물까지 추적 가능한 run 기록 존재
- 현재 로컬 파일 저장과 DB 데이터의 백업 방법 확인

조건을 충족하지 못하면 인증·업로드 UI만 먼저 붙이지 않는다. 사용자 수가 늘어날수록 기존 범위와 기억 오류를 재현하기 어려워진다.

## A.2 구현 범위

### 브라우저 파일 업로드

- 서버 폴더 경로 입력을 다중 파일 업로드로 교체
- 파일 크기·개수·페이지 수·MIME 제한
- 파일별 `읽음 / 제외 / 실패 / 사용자 확인 필요` 표시
- PDF, DOCX, HWP/HWPX, 이미지 OCR의 우선순위를 실제 학생 자료로 결정
- 원본 파일 hash와 parser version 저장
- 실패한 파일을 조용히 건너뛰지 않음

### 지속 작업과 worker

- 긴 분석은 `202 + run_id`로 시작
- `queued / running / awaiting_review / succeeded / failed / cancelled` 구분
- 중복 요청 키와 제한된 재시도
- worker lease/heartbeat와 재시작 후 복구
- 파싱 성공·임베딩 실패처럼 부분 성공을 별도로 표시
- FastAPI `BackgroundTasks`만으로 복구 가능한 작업이라고 간주하지 않음

### 인증과 사용자 격리

- 인증 사용자 ID를 모든 테이블과 원본 저장 경로의 최상위 경계로 사용
- 서버 발급 UUID 사용
- PostgreSQL RLS 또는 동등한 repository 검사
- CORS allowlist
- rate limit과 파일 업로드 제한
- URL 수집 시 내부망·metadata 주소와 redirect 재검사
- 원본 저장소는 비공개이며 결과물 공유 권한과 분리

### 저장소 이전

- 로컬 JSON/Markdown을 당장 삭제하지 않고 import와 검증 수행
- `files/file_versions`, `chunks`, `facts/fact_versions/fact_evidence`
- `sessions/messages`, `memory_proposals`
- `derived_artifacts/artifact_dependencies`
- `task_runs/run_events`
- 사용자별 건수·checksum·표본 비교 후 읽기 경로 전환
- 되돌리기 가능한 기간을 둔 뒤 쓰기 경로 전환

### 검색 고도화

- 사용자·scope·최신 fact version을 먼저 필터링
- 키워드와 vector 후보를 `chunk_id` 기준으로 결합
- 서로 다른 점수를 임의 배수로 섞지 않고 RRF 등 순위 결합 실험
- 첫 4줄이 아닌 관련 구간과 앞뒤 문맥 전달
- `fact_id`, `chunk_id`, 페이지·슬라이드 위치 반환
- 검색 실패, 미등록, 철회, 부분 장애를 구분
- 한국어 질문 평가셋으로 Recall@5 측정

### 파생 결과 무효화

- 사실·역할·수치·원본 버전이 바뀌면 의존 산출물을 `stale` 처리
- 기존 자소서·프로필을 조용히 덮어쓰지 않음
- 어떤 사실 변경이 어떤 결과물에 영향을 줬는지 표시
- 재생성은 사용자 승인 또는 명시적 작업으로 실행

### Human-in-the-loop

P1에서는 다음 작업에 승인 중단점을 고려한다.

- 사실과 역할을 장기기억으로 확정
- 기존 사실을 supersede/retract
- 결과물 외부 공유
- 원본 삭제
- 비용이 큰 재분석

HITL은 상태 저장 없이 단순 확인창만 붙이는 기능이 아니다. 실행을 중단하고 checkpointer에 상태를 남긴 뒤 같은 run을 재개해야 한다. [DeepAgents Human-in-the-loop](https://docs.langchain.com/oss/python/deepagents/human-in-the-loop)

## A.3 완료 기준

- 처음 사용하는 학생이 도움 없이 파일 업로드부터 경험 카드 승인까지 완료
- 두 사용자 교차 접근 테스트 0건 실패
- worker 중단·재시작 후 작업 복구 또는 명확한 실패 처리
- 정정 후 영향받는 프로필·자소서에 갱신 필요 표시
- 근거 패널에서 원본 위치 확인 가능
- 개발 자료와 분리된 사용자 동의 평가 자료 확보
- 지연, 비용, 실패율, Retrieval Recall@5의 표본 수와 결과 기록

## A.4 P1에서 아직 하지 않을 것

- 자유로운 셸 실행
- 자동 지원서 제출
- 무제한 웹 탐색
- 장시간 자율 서브에이전트
- 사용자가 끌 수 없는 알림
- 근거 없는 자동 프로필 확정

---

# 부록 B. P2 — 확장형 에이전트와 고급 컨텍스트 관리

P2는 “기능적으로 가능하다”가 아니라 P1 사용 로그에서 병목이 확인됐을 때 선택한다.

## B.1 서브에이전트

### 도입 조건

- 한 작업의 중간 도구 출력이 메인 대화 컨텍스트를 반복적으로 크게 차지함
- 서로 독립적인 조사·평가 작업이 두 개 이상 존재함
- 병렬 처리로 줄일 수 있는 실제 대기시간이 측정됨
- 단일 에이전트의 tool/model budget으로 품질 목표를 달성하지 못함

### 적합한 SKIVE 작업

- 여러 프로젝트 경험의 독립 평가
- 과목 자료와 프로젝트 자료의 분리 조사 후 비교
- 긴 포트폴리오 근거 분석 후 요약만 메인으로 반환
- 여러 직무 후보를 동일 rubric으로 병렬 평가

### 부적합한 작업

- 프로필 단순 조회
- 경험 하나 저장
- 도구 한두 번으로 끝나는 질문
- 중간 상태를 계속 공유해야 하는 정정 작업
- 비용 절감 근거가 없는 단순 병렬화

서브에이전트의 가장 큰 가치는 작업자 수가 아니라 **context quarantine**이다. 메인 에이전트에는 최종 구조화 결과와 근거 ID만 반환한다. [DeepAgents Subagents](https://docs.langchain.com/oss/python/deepagents/subagents)

### 완료 기준

- 동일 평가셋에서 단일 에이전트 대비 품질·지연·비용 중 최소 하나가 개선되고 나머지가 허용 범위
- 부모의 사용자·scope·budget보다 넓은 권한을 갖지 않음
- subagent별 tool/model usage와 실패가 추적됨
- 중간 결과가 장기기억으로 자동 저장되지 않음

## B.2 요약과 context offloading

### 도입 조건

- 실제 긴 세션에서 입력 토큰이 설정한 soft limit를 반복적으로 초과
- 단순 최근 메시지 절삭이 중요한 정정·역할을 잃게 함
- 큰 도구 결과 때문에 비용 또는 context overflow가 발생

### 구현 방향

- 최근 메시지와 아직 해결되지 않은 질문은 원문 유지
- 오래된 대화는 사실 ID와 결정 사항 중심으로 요약
- 원문은 삭제하지 않고 별도 저장하고 요약에서 참조 ID 제공
- 큰 도구 결과는 저장소에 offload하고 모델에는 요약과 위치만 제공
- 요약은 장기기억이 아니며 사실 확정 권한을 갖지 않음
- context overflow가 발생하면 무제한 재시도하지 않고 한 번 압축 후 재시도

DeepAgents는 모델 프로필이 있을 때 컨텍스트 비율 기반 요약과 최근 구간 보존을 제공하지만, SKIVE의 정확한 임계값은 실제 세션 로그로 정한다. [DeepAgents SummarizationMiddleware](https://github.com/langchain-ai/deepagents/blob/main/libs/deepagents/deepagents/middleware/summarization.py)

## B.3 가상 작업공간과 샌드박스

### 도입 조건

- 사용자가 업로드한 파일을 변환·빌드·검사해야 하는 실제 요구가 반복됨
- 라이브러리 실행이나 문서 변환을 격리하지 않으면 호스트 안전성을 보장하기 어려움
- 실행 결과의 재현과 정리가 필요함

### 구현 방향

- 사용자별 임시 작업공간
- 기본 read-only 입력과 별도 output 경로
- `.env`, 인증서, 호스트 저장소 접근 금지
- CPU, 메모리, 실행 시간, 네트워크 제한
- 실행 명령 allowlist 또는 격리된 sandbox backend
- 결과물만 검토 후 영속 저장소로 이동
- 삭제·실행 도구에는 별도 승인 정책

범용 shell을 현재 FastAPI 프로세스에 직접 노출하지 않는다. DeepAgents도 shell 실행은 sandbox backend에서만 도구로 제공한다. [DeepAgents Overview](https://docs.langchain.com/oss/python/deepagents/overview)

## B.4 Skill과 모델별 profile

### 도입 조건

- 자소서, 포트폴리오, 학습 회고 등 상세 지침이 기본 프롬프트를 비대하게 만듦
- 모델 교체 시 같은 도구 설명과 프롬프트가 반복적으로 다르게 동작함
- 작업별 도구 집합이 안정적으로 구분됨

### 구현 방향

- 항상 필요한 핵심 규칙만 base prompt에 둔다.
- 자소서, 포트폴리오, 회고 질문, 직무 분석을 개별 skill로 분리한다.
- skill은 설명 메타데이터만 기본 노출하고 필요한 작업에서 본문을 로드한다.
- 제공자·모델별 차이는 `ModelProfile` 또는 adapter 한곳에 둔다.
- domain/service 코드에는 `cache_control` 같은 제공자 전용 필드를 넣지 않는다.
- toolset version과 skill version을 run 기록에 남긴다.

## B.5 능동적 에이전트와 외부 연결

### 도입 조건

- 사용자가 주간 회고나 알림을 실제로 반복 요청함
- 알림의 수용률과 해제율을 측정할 수 있음
- 외부 서비스별 OAuth, 최소 권한, 데이터 삭제 정책이 준비됨
- 외부 행동 전에 승인할 UX와 감사 로그가 있음

### 후보 기능

- 사용자가 선택한 빈도의 주간 경험 회고
- 새 사실 승인 후 프로필 갱신 제안
- 공고 요구사항과 현재 근거 간 차이 설명
- 캘린더·Drive·Notion 등 단일 연결부터 검증

사용자를 대신한 지원서 제출, 이메일 전송, 공개 게시, 결제는 별도 제품·법적·보안 검토 없이는 추가하지 않는다.

## B.6 P2 완료 판정 원칙

P2 기능은 기능 존재가 아니라 다음 증거로 판단한다.

- 어떤 실제 병목을 해결했는가
- 단일 에이전트 기준선보다 품질·비용·지연이 개선됐는가
- 권한과 사용자 데이터 경계가 더 넓어지지 않았는가
- 실패 시 취소·재개·복구가 가능한가
- 사용자가 기능을 이해하고 끌 수 있는가
- 변경 전후 평가 결과와 표본 수가 남아 있는가

---

# 부록 C. 다른 대화방에서 구현할 때의 판단 규칙

다른 에이전트 또는 대화에서 이 문서를 사용할 때 다음 순서를 따른다.

1. `PROJECT_STATUS.md`와 실제 코드를 읽어 현재 구현 여부를 다시 확인한다.
2. 이 문서의 항목을 구현 완료 사실로 해석하지 않는다.
3. P0 완료 판정표에서 아직 실패하는 가장 앞 항목을 선택한다.
4. 관련된 기존 테스트와 사용자 변경 사항을 보존한다.
5. 입력 → 실패 재현 → 최소 수정 → 결정론적 테스트 → 필요한 통합 검증 순으로 진행한다.
6. 외부 LLM 호출 결과와 구조적 준비를 구분해 보고한다.
7. 모델·가격·API 캐시 정책처럼 바뀔 수 있는 내용은 구현 시점의 공식 문서를 다시 확인한다.
8. 프레임워크 전면 교체, 새 DB, 새 외부 서비스처럼 범위를 넓히는 결정은 ADR과 비교 근거 없이 실행하지 않는다.
9. 사용자 데이터 삭제·이동·대규모 마이그레이션 전에는 정확한 대상과 복구 방법을 확인한다.
10. 완료 후 `PROJECT_STATUS.md`에는 실제 검증한 결과와 남은 한계를 함께 기록한다.

## 구현 작업 요청 예시

```text
SKIVE_NEXT_PLAN_DeepAgents_반영본.md의 P0-2만 구현한다.
먼저 R01/R08 실패를 재현하고, 현재 도구 전체 목록과 scope 전달 경로를 확인한다.
RequestContext와 ScopeGuard를 최소 변경으로 추가하되 다른 P0/P1 기능은 구현하지 않는다.
외부 LLM 없이 회귀 테스트를 실행하고, 변경 파일·통과 증거·남은 미적용 도구를 보고한다.
```

이 형식으로 한 번에 하나의 P0 묶음을 요청하면 대화가 바뀌어도 범위와 완료 조건이 흔들리지 않는다.

## 참고 자료

- 원래 전체 계획: [SKIVE_NEXT_PLAN.md](SKIVE_NEXT_PLAN.md)
- 현재 구현 현황: [PROJECT_STATUS.md](PROJECT_STATUS.md)
- DeepAgents 공식 개요: [Deep Agents Overview](https://docs.langchain.com/oss/python/deepagents/overview)
- DeepAgents context engineering: [Context Engineering](https://docs.langchain.com/oss/python/deepagents/context-engineering)
- DeepAgents backends: [Backends](https://docs.langchain.com/oss/python/deepagents/backends)
- DeepAgents subagents: [Subagents](https://docs.langchain.com/oss/python/deepagents/subagents)
- DeepAgents HITL: [Human-in-the-loop](https://docs.langchain.com/oss/python/deepagents/human-in-the-loop)
- LangGraph persistence: [Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
- LangChain middleware: [Prebuilt Middleware](https://docs.langchain.com/oss/python/langchain/middleware/built-in)
- OpenAI prompt caching: [Prompt Caching](https://developers.openai.com/api/docs/guides/prompt-caching)
- Anthropic prompt caching: [Prompt Caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)
- Gemini context caching: [Context Caching](https://ai.google.dev/gemini-api/docs/caching)

이 문서의 P0는 지금 구현할 범위, 부록 A·B는 도입 조건이 충족됐을 때 판단할 후보 범위다. 구현 순서는 **신뢰성 → 첫 사용자 운영 → 고급 자율성**을 유지한다.
