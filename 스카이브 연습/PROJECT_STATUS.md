# SKIVE 프로젝트 현황 (2026-09-22 기준, 전면 개정)

이 문서는 **이 대화 맥락을 전혀 모르는 사람(또는 새 대화창)이 읽어도** 프로젝트가 뭔지, 왜 이렇게
생겼는지, 어디까지 됐는지, 다음에 뭘 해야 하는지 파악할 수 있게 쓴 문서다. 새 컴퓨터나 새
대화에서 시작할 때 이 파일부터 읽으면 된다. (대화 세션·Claude 메모리는 컴퓨터마다 로컬이라
안 따라오지만, 이 파일은 git으로 어디서든 똑같이 보인다.)

---

## 1. 우리가 만들려는 것

**SKIVE** — 대학생 개인용 커리어 에이전트. 한 줄로: **경험 자료(파일)를 넣으면 → 근거 인용
기반으로 경험을 구조화하고 → 여러 경험을 종합해 프로필을 만들고 → 채용공고와 매칭해서 →
자소서 초안까지 만들어주는, 로컬 우선(local-first) 웹앱.** 2026년 12월 데모가 목표다.

### 1.1 핵심 차별점 — 이게 없으면 다른 서비스랑 다를 게 없음

- **근거 기반(Evidence-grounded)이 목표다 — 아직 보장은 아니다.** 지향점은 "원본 파일의 실제
  문구와 대조된 것만 사실로 취급하고, 안 되면 '확인 필요'로 표시한다"이고, 팀 성과를 본인 성과로
  쓰는 왜곡도 코드로 걸러내려 한다. 다만 2026-09-22 기준 이 보장은 **부분적으로만 성립한다**:
  판정자가 지적한 문장이 초안에 남아도 "정제"로 표시되고(F04), 숫자 검증이 지표를 구분하지
  못하며(F05), 챗봇 스코프가 읽기 도구에는 안 걸린다(F02). 결함 목록과 수정 순서는
  `SKIVE_NEXT_PLAN.md`와 아래 7절에 있다.
  **수정 완료: F01**(정정이 검증 상태를 물려받던 문제), **F03**(인용문 존재만으로 검증 통과).
- **정정·새 사실도 확인 후에만 반영.** 챗봇이 뭔가 알아냈다고 바로 파일을 덮어쓰지 않는다.
  사람이 확인 카드에서 승인해야 반영되고, 그 이력이 남는다.
- **원본 파일은 절대 안 건드림.** 사용자가 올린 원본 보고서·코드·회의록은 읽기 전용이다.
  파생 정보(요약, 메모, 정리본)만 별도로 쓰거나 고친다.
- 경쟁 서비스(다글로, Lilys AI, UnivAI, ThetaWave 등)는 전부 **단일 문서 요약** 도구라 크로스
  경험 프로필 종합·공고 매칭 기능이 없다. SKIVE의 차별점은 여러 경험을 엮어서 "이 사람이 어떤
  사람인지" 파악하고 그걸 진로/자소서에 직접 연결하는 것.

### 1.2 지금 이 순간 실제로 쓸 수 있는 상태인가

**그렇다.** `uv run uvicorn skive.server:app --reload --port 8010` 켜고 브라우저에서
`localhost:8010` 열면 실제로 동작하는 웹앱이 뜬다 (드라이브, 프로필, 공고, 챗봇, 복습 탭 전부
실제 데이터 연결됨). 다만 지금은 **사용자 1명**을 가정한 로컬 앱이고, 진짜 여러 사람이 쓰는
플랫폼이 되려면 4절 "남은 과제"의 상당 부분이 더 필요하다.

---

## 2. 전체 아키텍처 (큰 그림)

### 2.1 데이터 흐름

```
사용자
  │
  ├─ 폴더 업로드(경로 입력) ──→ [분석 Workflow] ──→ experience.md + facts.json 저장
  │                              (analyzer.py, verify.py로 근거 대조)     │
  │                                                                      ├─→ [청크+임베딩] → Postgres(pgvector)
  │                                                                      │    (chunks_store.py, 검색용)
  ├─ 챗봇 대화 ──→ [챗봇 Agent] ──(도구 호출)──→ 위 저장소 조회/수정
  │                (chat.py, LangGraph)              ├─ 정정/새사실 감지 → 확인 후 facts.json 갱신 (corrections.py)
  │                                                   └─ 메모 파일 읽기/쓰기 (store.py notes/)
  │
  ├─ 공고 등록(텍스트/URL/PDF/이미지/문항 직접입력) ──→ [공고 분석 Workflow] ──→ 인재상·역량 추출 (job.py)
  │                                                                              │
  │                                                        [매칭 Agent] ←────────┘
  │                                                     (agent.py, 경험 탐색 후 계획 수립)
  │                                                              │
  │                                              [자소서 작성 Workflow+평가자]
  │                                           (writer.py: gate→write→judge→repair)
  │                                                              │
  └─ "이렇게 고쳐줘" 대화형 수정 ──→ 같은 근거 범위 안에서 재작성 (writer.revise_answer)
```

경험 하나가 쌓이면 → 프로필 종합(profile.py, 전체 재계산 Workflow)이 역량·성향·보강필요점을
다시 뽑는다. 챗봇 대화가 일정 턴 넘게 이어지면 → 공부 세션 요약(study.py)이 "배운 것/헷갈린
것"만 걸러서 저장한다.

### 2.2 레이어 구조

| 레이어 | 상태 | 위치 |
|---|---|---|
| CLI | 동작함 | `skive/cli.py` |
| HTTP API (FastAPI) | 동작함 | `skive/server.py` |
| 프론트엔드 | 정적 HTML + 바닐라 JS, 프레임워크 없음, `/api/*` fetch로 백엔드와 통신 | `ui_mockup/skive_ui.html` |
| 주 저장소 | **플랫파일**(JSON/Markdown), `data/` 아래 | 여러 모듈 |
| 검색용 저장소 | **Postgres + pgvector** (Supabase), 원본 파일 청크+임베딩만 | `skive/db.py`, `skive/chunks_store.py` |
| 인증/멀티테넌시 | **없음.** 사용자 1명 가정(`data/user.json` 단일 파일) | — |

**왜 두 개의 저장소(플랫파일 + DB)를 같이 쓰는가**: 경험/사실(Experience/Fact)은 자주 안 바뀌고
사람이 직접 파일로 열어봐도 되는 게 장점이라 플랫파일로 남겨뒀다. 반면 원본 파일 청크는 매
챗봇 질문마다 다시 파싱하면 느려지고(실측으로 확인한 병목), 의미 기반 검색(임베딩)을 하려면
벡터 인덱스가 필요해서 DB로 옮겼다. **경험/사실 자체까지 DB로 완전히 옮기는 건 아직 안 했다** —
7절 참고.

### 2.3 설계 원칙: Workflow인가 Agent인가

이 프로젝트에서 의식적으로 지키는 구분이다. **정해진 순서대로 진행해도 되는 부분은 Workflow로,
"이걸 어떻게 풀지 LLM이 스스로 판단해야 하는" 부분만 Agent(LangGraph, 도구 호출)로 만든다.**
전체를 하나의 거대 에이전트로 만들지 않는다.

| 기능 | Workflow / Agent | 근거 |
|---|---|---|
| 파일→청크 로딩 (`loaders.py`) | Workflow | LLM 없음, 고정 파싱 |
| 경험 추출 (`analyzer.py`) | Workflow | LLM 구조화 출력 1콜 + 이후 검증·렌더는 결정론적 |
| 중요도 채점 (`importance.py`) | Workflow | LLM 서브스코어 1콜 + 고정 공식 |
| 프로필 종합 (`profile.py`) | Workflow | LLM 구조화 출력 1콜 + 결정론적 검증·렌더 |
| 공고 파싱 (`job.py`) | Workflow | LLM 구조화 출력 1콜 |
| 공부 세션 요약 (`study.py`) | Workflow | LLM 구조화 출력 1콜 + 결정론적 연결 |
| 정정/새사실 감지·반영 (`corrections.py`) | Workflow(+판단 LLM 1콜) | 분류기 1콜 + 순수 결정론적 파일 수정, 자동 분기 없이 사용자 확인 게이트 |
| 자소서 작성/수정 (`writer.py`) | **Workflow + evaluator** | gate→write→judge→repair가 코드의 while 루프. LLM이 다음 단계를 정하는 게 아니라 파이썬이 루프를 돎 |
| 청크 검색 (`recall.py`, `chunks_store.py`) | Workflow (RAG) | 고정 하이브리드(키워드+벡터) 알고리즘 |
| **공고↔경험 매칭 (`agent.py`)** | **Agent** | LangGraph ReAct 루프. LLM이 `get_profile`/`list_experiences`/`get_experience`/`get_evidence` 중 뭘 언제 부를지 스스로 정하고 "탐색 완료"로 스스로 멈춤 |
| **챗봇 (`chat.py`)** | **Agent** | 도구 호출 여부·순서를 LLM이 결정. 원본 파일 읽기(`get_evidence`)·메모 쓰기(`save_note`)도 LLM이 필요하다고 판단할 때만 스스로 호출함(실측: "복습하면서 헷갈린 점 메모해줘"라고만 했더니 스스로 save_note를 호출해서 파일을 만듦) |

진짜 열린 도구 루프(Agent)는 `agent.py`(매칭)와 `chat.py`(챗봇) 둘뿐이다. 나머지는 전부 Workflow.

### 2.4 프롬프트 설계 원칙: 고정 규칙 vs 커스터마이즈 가능한 스타일

`writer.py`(자소서 작성)에서 처음 도입한 패턴인데, 앞으로 다른 프롬프트에도 적용할 만한
원칙이다:

- **`WRITER_CORE_RULES`(고정, 절대 안 바뀜)**: 근거 없는 내용 금지, 팀 성과를 본인 것처럼 왜곡
  금지, 역할 미확인 경험은 "내가 했다"고 못 씀. 이게 SKIVE 존재 이유라서 사용자도 못 바꾼다.
- **`essay_style`(사용자가 자유롭게 수정, `PUT /api/user`)**: 페르소나("10년차 컨설턴트"),
  STAR 구조, 지원동기/장단점 형식 같은 스타일 지침. 프로필 탭에 편집 UI 있음.
- 스타일이 규칙과 충돌하면 **규칙이 이긴다** — 프롬프트 안에 그렇게 명시했고, 실측으로도 STAR
  구조는 반영되면서 근거 없는 감상 문장은 그대로 걸러지는 것 확인함.

---

## 3. 지금까지 구현된 것 (기능별 상세)

### 3.1 경험 분석 (Ingestion)

폴더 경로 + 학년을 주면(`skive ingest` CLI 또는 `POST /api/experiences`):
1. `loaders.py`가 폴더 안 파일(md/txt/csv/py/json/pdf/pptx 등)을 읽어 청크로 쪼갠다(텍스트는
   80줄 단위, PDF는 페이지 단위, PPTX는 슬라이드 단위).
2. `analyzer.py`가 LLM 구조화 출력(`Experience` 모델)으로 제목/기간/문제/본인역할/행동/의사결정/
   결과/기술/배운점/열린질문을 뽑는다. 이때 모든 근거(Evidence)는 `[C숫자]` 형식으로 원문
   청크를 가리키게 시킨다.
3. `verify.py`가 근거를 **네 가지로 나눠서** 검사한다 **(0-2에서 개정)**:
   (a) 인용문이 그 청크 안에 글자 그대로 있는가(공백/기호 무시),
   (b) 인용문이 주장과 최소한의 내용을 공유하는가(한글 바이그램 + 영문 용어 + 숫자 겹침,
       임계값 `verify.SUPPORT_MIN_OVERLAP = 0.3`),
   (c) 주장은 "내가"인데 인용문 주어는 "팀은"뿐인 주체 불일치가 아닌가,
   (d) 주장에 있는 수치가 인용문에도 있는가.
   **넷 다 통과해야** 근거로 인정된다. 하나라도 떨어지면 `needs_review`가 되어 자소서 근거에서
   빠지고, 이유가 태그에 남는다(`[근거 불충분(인용문의 주체가 본인이 아님): …]`).
   **`quote` 원문도 이제 저장한다** — 안 하면 사후 감사가 불가능하다.
   (b)의 임계값 0.3은 기존 실데이터 검증사실 33건의 겹침 분포(최솟값 0.38)와 F03 재현
   케이스(0.12) 사이에서 잡았다. 통과해도 상태는 `quote_matched`까지이고 `supported`로는
   올리지 않는다 — 문자 겹침은 함의(entailment)가 아니기 때문.
4. `importance.py`가 역할검증여부·정량성과여부·근거비율(결정론적 3항목) + LLM이 매긴
   영향력/독자성/진로연관성(3항목)을 더해 15점 만점 중요도를 매기고 핵심/활성/보관 등급을 준다.
5. `store.py`가 `data/store/<experience_id>/`에 `experience.md`(사람이 읽는 요약),
   `facts.json`(구조화된 사실), `metadata.json`(등급·통계)을 저장한다.
6. **(2026-09-22 추가)** `chunks_store.py`가 같은 원본 파일을 다시 읽어 각 청크를 임베딩하고
   Postgres `skive.chunks`에 저장한다. 이후 검색은 이 DB만 읽는다(재파싱 없음).

### 3.2 프로필 종합

`skive profile` / `POST /api/profile/rebuild`: 저장된 모든 경험의 검증된 사실을 모아 LLM
구조화 출력(`Profile` 모델)으로 역량(competencies)·반복 성향(traits, 서로 다른 경험 2개
이상에서 확인된 것만)·보강 필요점(gaps)을 뽑는다. `_validate()`가 LLM이 없는 경험 id를
근거로 댔으면 걸러낸다(환각 방지).

### 3.3 공고 분석 & 매칭 & 자소서

**공고 입력(`POST /api/jobs`)** — 여러 소스를 조합 가능:
- 공고 원문 텍스트, 공고 URL(해당 페이지만 fetch, 검색 아님 — `webfetch.py`)
- 인재상 직접입력 또는 URL
- 참고자료 텍스트
- 직무기술서 PDF/이미지 업로드(`POST /api/extract-file` — PDF는 `pypdf`, 이미지는 vision LLM으로 텍스트화)
- 자소서 문항 직접입력(주면 LLM 추출 대신 그대로 씀)

**분석**: `job.py`가 이 조합된 텍스트에서 회사/직무/자격요건/인재상/핵심역량/자소서문항을
구조화(`JobRequirements`)한다.

**매칭(`agent.py`, Agent)**: LangGraph ReAct 루프가 `get_profile`→`list_experiences`→
필요한 경험만 `get_experience`로 깊이 읽고→유력한 것만 `get_evidence`로 원본까지 확인한 뒤,
공고 핵심역량마다 강함/보통/약함/없음으로 근거 강도를 매기고 문항마다 쓸 경험 1~2개를 고른다.
"팀에 참여했다"는 사실만으로는 "약함"까지만 준다 — 본인 역할이 검증된 직접적 사실이 있어야
"강함".

**작성(`writer.py`+`apply.py`, Workflow+evaluator)**: 문항마다 (1) gate — 근거로 답할 수
있는지 가능/부분/불가 판정 → (2) write — 근거 자료+프로필+스타일 지침으로 초안 작성
→ (3) judge — 문장마다 supported/unsupported/misattributed 판정 → (4) 문제 있으면 최대
2번 재작성, 그래도 남은 미검증 문장은 강제로 잘라낸다.

**대화형 수정(`POST /api/jobs/{id}/answers/{index}/revise`)**: "두 번째 문장 빼고 더
구체적으로 써줘" 같은 요청을 `writer.revise_answer()`가 받아서, **같은 근거 자료 범위
안에서만** 다시 쓰고 같은 judge 검증을 한 번 더 거친다. 근거 밖 요청이면 안 바꾸고 이유를
알려준다. 요청 이력은 `answer.revisions`에 남는다.

### 3.4 챗봇

`chat.py`, LangGraph Agent. 도구: `get_profile`, `list_experiences`, `get_experience`,
`get_evidence`(원본 파일 읽기), `search_study`, `get_study`, **`save_note`/`list_notes`/
`get_note`(경험 폴더에 메모 파일 쓰기/읽기, 원본은 절대 안 건드림)**.

- **스코프**: 특정 경험 폴더로 좁히면(`scope_id`) 메모 도구 3개(`save_note`/`list_notes`/
  `get_note`)는 클로저로 그 경험에 고정된다. **하지만 `get_experience`/`get_evidence`/
  `search_study`/`get_study`는 아직 스코프가 안 걸려 있어서, LLM이 다른 `experience_id`를 넘기면
  그대로 읽힌다(F02).** 즉 지금 스코프는 쓰기에만 강제되고 읽기에는 강제되지 않는다. 0-6에서
  전 도구에 서버 주입 범위를 강제할 예정.
- **회상(recall)**: 하이브리드 — 정확한 단어가 겹치는 것(키워드, TF-IDF 비슷한 방식)과 의미가
  비슷한 것(벡터, pgvector 코사인 유사도)을 둘 다 찾아서 합친다. 아래 5절 버그 #2가 이걸로
  해결됨.
- **정정/새사실(`corrections.py`)**: 매 턴마다 자동으로 "이 메시지가 기존 사실을 정정하는
  건지, 새 사실을 추가하는 건지"를 판단해서 확인 카드를 띄운다. 사용자가 승인해야만
  facts.json/experience.md에 반영된다.
  **(0-3에서 수정)** 정정은 기존 항목을 덮어쓰는 게 아니라 **새 버전을 만든다**: 이전 버전은
  `facts["superseded"]`로 내려가 보존되고, 새 버전은 `provenance_type=user_statement` /
  `evidence_status=needs_review` / `evidence=[]`로 시작한다 — 즉 **이전 인용과 검증 상태를
  절대 물려받지 않는다.** 감사용으로 `prior_evidence`/`prior_text`만 따로 남는다. 자소서
  작성 시에도 `[본인 진술 — 원문 근거 없음]` 블록으로 문서 근거와 분리돼서 들어간다.

### 3.5 공부 세션 요약

대화가 끝나고(`POST /api/chat/end`) 사용자 턴이 2번 넘으면, `study.py`가 전체 transcript에서
"배운 것/헷갈리는 것/복습질문/관련경험"만 LLM으로 뽑는다. 인용문(quote)은 실제 transcript에
있는 문구인지 대조 검증하고, 관련 경험은 `recall()`로 한 번 더 교차 확인한다.

### 3.6 DB 연동 (Postgres/Supabase)

- 기존에 있던 Supabase 프로젝트(예전 `skybe`라는 다른 시도가 쓰던 것)를 재사용하되, **`skive`
  스키마로 완전히 분리**해서 `public.*`(예전 프로젝트 테이블 14개)와 안 겹친다.
- `SCHEMA.md`에 전체 개념 스키마(12개 테이블 설계) 문서가 있지만, **실제로 지금 쓰는 건
  `skive.chunks` 하나뿐**이다(의도적 축소 — 아래 "왜 전체를 안 옮겼나" 참고).
- `migrations/0001_init.sql`이 원래 설계한 12개 테이블 전체를 만들고, `migrations/
  0002_chunks_by_slug.sql`이 그중 `chunks`만 다시 만든다(uuid FK 대신 slug 텍스트로 —
  experiences 테이블에 실제 데이터가 없어서 FK를 걸 수 없었기 때문).
- `skive/db.py`: `DATABASE_URL`(`.env`)로 접속, `migrations/*.sql`을 파일명 순서대로 한 번만
  적용(`skive.schema_migrations` 테이블로 추적).
- `skive/embeddings.py`: OpenAI `text-embedding-3-small`(1536차원)로 임베딩.
- `skive/chunks_store.py`: `sync_chunks(exp_id, raw_dir)`로 원본 파일을 다시 읽어 청크+임베딩을
  DB에 씀(ingest 시 자동 호출, 또는 `skive sync-chunks`로 수동 재생성). `keyword_source_docs()`
  로 DB에서 청크 텍스트를 재파싱 없이 가져오고, `vector_search()`로 코사인 유사도 검색.

**왜 experiences/facts 자체는 DB로 안 옮겼나**: 지금 병목은 "매 챗봇 질문마다 원본 파일을
다시 파싱하는 것"이었지, experience.md/facts.json을 읽는 게 아니었다(파일이 작고 이미
디스크에 있어서 안 느림). 그래서 실제로 문제인 부분(청크+임베딩)만 옮기고, 나머지는 그대로
둬서 위험을 줄였다. experiences 자체를 옮기려면 corrections.py/analyzer.py/profile.py/
apply.py 등 8개 넘는 모듈이 전부 파일 대신 DB를 읽고 쓰게 바뀌어야 해서 훨씬 큰 작업이고,
지금은 사용자가 1명이라 시급하지도 않다 — 멀티유저 Auth를 붙일 때 같이 하는 게 맞다(7절 참고).

### 3.7 목업 프론트엔드 → 실제 API 연결

`ui_mockup/skive_ui.html` (바닐라 JS, 프레임워크 없음, 766→850줄 정도). 원래는 하드코딩된 mock
데이터였는데 전부 실제 `/api/*` 호출로 교체함. 드라이브(경험 탐색+원본파일 미리보기),
프로필(기본정보 수정, 자소서 스타일 설정, 역량/성향 표시), 공고(다중 소스 등록, 매칭표,
대화형 자소서 수정), 챗봇(스코프 칩, 정정/새사실 확인 카드), 복습(공부기록 목록) 전부 연결됨.
백엔드에 대응 기능이 없던 목업 요소(SRS 플래시카드, "내 생각.md" 개인 메모)는 정직하게
제거했다.

---

## 4. 파일/폴더 구조 상세

```
스카이브 연습/
├── PROJECT_STATUS.md        ← 이 문서
├── SCHEMA.md                 ← DB 개념 스키마 설계 문서 (12개 테이블, 실제 쓰는 건 chunks뿐)
│                               §2가 사실 상태 모델 v2 — 정정/근거 판정의 기준 문서
├── SKIVE_NEXT_PLAN.md        ← 외부 리뷰(아스트로). P0 결함 F01~F05, 목표 아키텍처, 실행 5단계
├── README.md
├── pyproject.toml            ← 의존성 정의(uv) + pytest 설정
│
├── tests/
│   └── test_p0_regressions.py           P0 결함 회귀 테스트. 아직 안 고친 결함은
│                                        xfail(strict=True)로 박아둬서 고치는 순간 XPASS로 알려줌
│
├── migrations/                          [Postgres 마이그레이션 — 파일명 순서대로 1번씩 적용]
│   ├── 0001_init.sql                    최초 스키마 (users/experiences/facts/jobs 등 12개 테이블)
│   └── 0002_chunks_by_slug.sql          chunks 테이블을 slug 기반으로 다시 정의 (실제 쓰는 것)
│
├── skive/                               [진짜 패키지 — 여기가 전부다]
│   ├── models.py            Pydantic 스키마 전체 (Experience, Fact, Profile, JobRequirements,
│   │                        Plan, CorrectionProposal 등 LLM 구조화 출력에 쓰는 모든 타입)
│   ├── loaders.py           폴더→청크 로딩 (md/txt/csv/py/json/pdf/pptx 파싱)
│   ├── verify.py            근거 인용이 원문에 실제로 있는지 대조하는 저수준 유틸
│   ├── facts.py             **사실 상태를 해석하는 유일한 곳.** provenance/evidence_status/
│   │                        lifecycle 읽기, v1(verified 불리언) 호환, 새 버전 생성(new_version).
│   │                        "이 사실을 자소서 근거로 써도 되나?" = is_document_backed()
│   ├── analyzer.py          경험 추출 (폴더 → experience.md/facts.json/metadata.json 원재료)
│   ├── importance.py        경험 중요도 채점 (핵심/활성/보관 등급)
│   ├── store.py             경험 저장소 (플랫파일 read/write) + 메모(notes/) 읽기/쓰기
│   ├── profile.py           프로필 종합 (경험들 → 역량/성향/보강점)
│   ├── job.py                공고 텍스트 → JobRequirements 구조화
│   ├── agent.py              공고↔경험 매칭 Agent (LangGraph, get_profile/get_evidence 등 도구)
│   ├── writer.py             자소서 문항 작성 + 대화형 수정 (gate→write→judge→repair)
│   ├── apply.py              writer.py를 문항마다 돌리는 오케스트레이션 (run_apply)
│   ├── chat.py               챗봇 Agent (LangGraph) — 스코프, 회상, 도구 목록, CLI 대화 루프
│   ├── recall.py             하이브리드 회상: 키워드(TF-IDF류) + 벡터(pgvector) 검색·병합
│   ├── chunks_store.py       원본 파일 청크+임베딩을 Postgres에 저장/검색 (recall.py가 씀)
│   ├── embeddings.py         OpenAI 임베딩 계산 (text-embedding-3-small, 1536차원)
│   ├── corrections.py        정정/새사실 감지(LLM 분류) + 확인 후 facts.json/md 반영
│   ├── study.py               공부 세션 요약 (대화 → 배운 것/헷갈린 것)
│   ├── webfetch.py            공고/인재상 URL 하나를 fetch해서 텍스트만 추출 (검색 아님)
│   ├── db.py                  Postgres 연결 + migrations/*.sql 실행
│   ├── user.py                 단일 사용자 프로필(data/user.json) read/write
│   ├── llm.py                   LLM 클라이언트 팩토리 (get_llm, get_judge_llm)
│   ├── report_html.py           apply 결과로 시연용 정적 HTML 리포트 생성
│   ├── server.py                 FastAPI 앱 — 전체 HTTP API (아래 6절에 라우트 전체 목록)
│   └── cli.py                     `skive` CLI 진입점 (ingest/list/profile/apply/chat/ask/
│                                    migrate/sync-chunks/report)
│
├── ui_mockup/
│   └── skive_ui.html          목업이자 실제 프론트엔드. 바닐라 JS, `/api/*` fetch로 통신.
│                                server.py가 `GET /`에서 이 파일을 그대로 서빙함.
│
├── samples/                    [ingest 테스트용 가짜 원본 자료 — 실제 학생 자료 아님, make_samples.py로 생성]
│   ├── make_samples.py
│   ├── 3d_printer_raw/, club_website_raw/, construction_phm_raw/,
│   │   field_camp_raw/, heat_treatment_raw/, ml_course_raw/   각각 보고서·코드·회의록 등
│   ├── job_frontend.txt, job_production.txt                   가짜 채용공고 원문
│   └── manifest.json                                           ingest-all이 읽는 폴더 목록
│
├── data/                        [실행하면서 쌓이는 실제 상태 — 전부 gitignore 대상은 아님, 지금은 커밋되어 있음]
│   ├── user.json                단일 사용자 프로필 (이름/진로목표/학교 등)
│   ├── store/<experience_id>/   경험별 저장소
│   │   ├── experience.md         사람이 읽는 요약 (analyzer.py가 생성, corrections.py가 갱신)
│   │   ├── facts.json            구조화된 사실 (actions/decisions/results, 각각 owner/verified/tag)
│   │   ├── metadata.json         등급·통계 (중요도, 근거검증비율, raw_dir 경로 등)
│   │   ├── corrections.json      정정/새사실 반영 이력 (있으면)
│   │   └── notes/                챗봇이 만든 메모 파일 (있으면, 원본과 별개)
│   ├── study/<session_id>/       공부 세션 (summary.md, transcript.txt, metadata.json)
│   ├── profile/                  종합 프로필 (profile.md, profile.json)
│   └── outputs/                  apply 결과 저장 (apply_<job_id>.json — 지금 "공고 DB" 역할을
│                                   임시로 하고 있음, 진짜 레코드화는 7절 과제)
│
├── .env                          (레포 루트, git 안 올라감) OPENAI_API_KEY, DATABASE_URL
└── src/skive_practice/           uv init이 만든 기본 스캐폴드, 실제로 안 씀 (무시해도 됨)
```

---

## 5. 실측으로 확인한 버그 현황 (추측 아니라 실제로 돌려서 확인한 것들)

1. ✅ 단순 회상, 경험 통합, 드릴다운, 오염/거짓전제 방어, 공부기록 회상 — 다 잘 됨.
2. ✅ **패러프레이즈 실패 → 해결됨.** "오류 잡는 성능 좋아진 사례?"처럼 정확한 단어(F1-score,
   퍼센타일)를 안 써도, 하이브리드 recall의 벡터 검색이 의미로 찾아낸다. 실측: 이 정확한
   질문으로 3D프린터·건설장비 PHM 프로젝트를 정확한 수치와 함께 찾아내는 것 확인함(전에는
   "기록에 없다"고 답했음). 다만 `cmd_ask`가 도구 호출 자체를 안 하고 바로 "기록에 없다"고
   답하는 경우가 가끔 관찰된 적 있음(recall 문제 아니라 LLM이 시스템 프롬프트를 안 따르는
   별개 이슈로 추정) — 재현 빈도 낮음, 미해결로 남겨둠.
3. ✅ **정정이 씹힘 → 해결됨.** 같은 대화 세션 안에서 정정해도 다음 턴에 원래 값이 다시
   나오던 문제. `corrections.py`가 확인 즉시 파일에 써서 다음 recall부터 바로 반영됨.
4. ⚠️ 자소서 문항 간 소재 중복 — **프론트엔드에서만** 감지함(문항들의 `experience_ids`가
   겹치면 ⚠ 표시). 백엔드에 실제로 반영(예: 자동으로 다른 경험으로 바꿔쓰기)은 안 함.

---

## 6. API 전체 목록 (`skive/server.py`)

| 메서드 | 경로 | 역할 |
|---|---|---|
| GET | `/` | `ui_mockup/skive_ui.html` 서빙 |
| GET/PUT | `/api/user` | 사용자 프로필 조회/수정 (이름·학교·학과·학년·진로목표·자소서스타일) |
| GET | `/api/experiences` | 경험 목록 (metadata 배열) |
| GET | `/api/experiences/{id}` | 경험 상세 (meta+markdown+facts) |
| GET | `/api/experiences/{id}/sources` | 원본 파일 목록 |
| GET | `/api/experiences/{id}/sources/{path}` | 원본 파일 텍스트 |
| POST | `/api/experiences` | 새 폴더 ingest (동기, 느림) |
| GET | `/api/experiences/{id}/corrections` | 정정/새사실 이력 |
| GET/POST | `/api/profile`, `/api/profile/rebuild` | 프로필 조회/재계산 |
| GET | `/api/jobs`, `/api/jobs/{id}` | 공고 목록/상세 |
| POST | `/api/jobs` | 공고 등록+분석 (텍스트/URL/인재상/참고자료/문항 조합) |
| POST | `/api/extract-file` | PDF/이미지 업로드 → 텍스트 추출 |
| POST | `/api/jobs/{id}/answers/{index}/revise` | 자소서 초안 대화형 수정 |
| GET | `/api/study`, `/api/study/{id}` | 공부 세션 목록/상세 |
| POST | `/api/chat` | 챗봇 대화 (scope_id로 폴더 스코프 지정) |
| POST | `/api/corrections/confirm` | 정정/새사실 확인 카드 승인/거절 |
| POST | `/api/chat/end` | 대화 종료 → 공부 세션 저장 |

CLI: `uv run python -m skive.cli {ingest|ingest-all|list|profile|apply|chat|ask|migrate|
sync-chunks|report}` — 각각 `--help`로 인자 확인 가능.

---

## 7. 남은 과제 — Stage 0~4 실행 계획 (2026-09-22 전면 재정렬)

외부 리뷰(`SKIVE_NEXT_PLAN.md`, 작성자 "아스트로")에서 P0 결함 5개가 지적됐고, 내가 LLM·DB
없이 순수 함수만으로 **5개 전부 재현했다**. 이 결함들이 "근거 기반"이라는 제품의 전제 자체를
깨기 때문에, 원래 세웠던 로드맵(아래 Stage 2~3으로 흡수됨)보다 먼저 온다.

**중요**: 원래 로드맵 1번 "스키마 확정 ✅"은 **다시 열렸다.** F01/F03이 스키마 결함이기
때문이다 — `verified` 불리언 하나가 "인용문이 원문에 존재함"과 "주장이 근거로 지지됨"과
"주체가 본인임"을 전부 뭉개고 있었다. 이걸 먼저 안 고치면 DB 이관을 두 번 하게 된다.

### Stage 0 — P0 결함 수정 (진행 중)

| # | 항목 | 대상 파일 | 상태 |
|---|---|---|---|
| 0-1 | 사실 상태 모델 v2 문서화 (`verified` 1개 → provenance/evidence_status/lifecycle/review_state/owner 분리) | `SCHEMA.md` §2 | ✅ 완료 |
| 0-3 | **F01** 정정이 검증 상태·원본 인용을 물려받던 문제 | `skive/facts.py`(신규), `corrections.py`, `writer.py`, `skive_ui.html` | ✅ 완료 |
| 0-7 | P0 회귀 테스트 고정 | `tests/test_p0_regressions.py` | ✅ 완료 (5 passed / 4 xfail) |
| 0-8 | 이 문서의 과장 문구 수정 | `PROJECT_STATUS.md` | ✅ 완료 |
| 0-2 | **F03** 인용문이 원문에 있기만 하면 `verified:true`가 됨. `quote`를 저장조차 안 함 | `analyzer.py`, `verify.py`, `facts.py` | ✅ 완료 |
| 0-4 | **F04** 판정자가 지적한 문장이 초안에 남아도 "정제"로 표시됨 (판정자가 문장을 바꿔 인용하면 삭제가 안 됨) | `writer.py` | ⬜ 다음 |
| 0-5 | **F05** 숫자 검증이 지표를 구분 못 함 (`F1-score 0.71` 근거로 "정확도 71%"가 통과) | `verify.py` | ⬜ |
| 0-6 | **F02** 스코프가 메모 도구 3개에만 걸려 있음. 읽기 도구는 스코프 밖 경험을 그대로 읽음 | `chat.py` | ⬜ |

Stage 0의 설계 원칙 3가지(`SCHEMA.md` §2.4에 불변식으로 명문화):
**상속 금지**(새 버전은 이전 버전의 근거·검증 상태를 못 물려받는다) /
**원본 보존**(정정해도 이전 버전은 `superseded`로 남는다) /
**승격 금지**(파생물 — 프로필·성찰 — 은 독립 근거가 될 수 없다).

### Stage 1 — 연결 누락 메우기 (UI ↔ 백엔드)

- 브라우저 파일 업로드(지금은 서버 로컬 경로 입력만 됨)
- 파일별 성공/제외 사유 표시
- ingest·공고 분석을 **비동기 잡 + `run_id` 폴링/SSE**로 (지금 동기 블로킹)
- 역할 확인 루프: "확인 필요"로 강등된 `my_role`을 사용자에게 되묻는 UI
- 근거 패널: 문장 클릭 → 원본 청크 표시
- `POST /api/chat/end` 연결 (**프론트엔드에 호출부가 0개다** — 공부 세션 요약이 실제로는
  한 번도 안 돌고 있음)
- MemGPT식 서버 세션 + 구조화된 `working_context`

### Stage 2 — 저장소·멀티테넌시 (원래 로드맵 1~4번)

1. **저장소 인터페이스 추출.** `store.py` 호출부를 repository 인터페이스 뒤로 숨긴다. 이걸
   먼저 해야 플랫파일→DB 전환이 한 곳에서 끝난다.
2. **experiences/facts를 DB로 이관** — 단, **스키마 v2 기준으로.** `SCHEMA.md`의 나머지
   테이블을 실제로 채우고, chunks의 `experience_id`도 slug 텍스트 대신 uuid FK로 정리한다.
3. **멀티유저 Auth.** 지금 `user.py`/대부분의 저장소가 "사용자 1명"을 가정. FastAPI에
   최소 세션/JWT를 붙이고, `data/user.json` 단일 파일 → `user_id` 기반 다중 사용자로 바꿔야
   함. 이걸 할 때 experiences/facts를 DB로 완전히 옮기는 것도 같이 하는 게 자연스럽다(지금
   플랫파일은 애초에 "폴더 하나 = 사용자 하나" 가정이라 여러 사용자를 못 담음).
4. **공고를 1회성 파일 처리 → 저장되는 레코드로.** 지금 `/api/jobs`는 `data/outputs/
   apply_*.json`을 그대로 읽고 쓰는 편법. DB 이관과 같이 하면 자연히 해결됨.
5. **보안 경계** (멀티유저가 되는 순간 필수): CORS 화이트리스트, 경로 주입 차단(지금 ingest가
   서버 로컬 경로를 그대로 받음), URL fetch의 SSRF 방어, 프론트엔드 `attrEsc`가 `"`를 이스케이프
   안 하는 문제와 `innerHTML` 사용처 정리.

### Stage 3 — 정확성·기능 확장

- **정정 → 파생물 무효화.** 사실이 정정되면 그걸 근거로 쓴 프로필·자소서 초안이 stale로
  표시돼야 한다. 지금은 조용히 옛날 근거를 유지한다.
- **`apply.py:25`의 폴백 제거.** 근거가 비면 중요도 상위 경험으로 자동 채우는데, 이건 "근거
  없으면 안 쓴다" 원칙 위반이다.
- **문장 단위 `fact_id` 연결.** 자소서 문장마다 어떤 사실을 썼는지 저장 → 근거 패널·중복 감지·
  stale 전파가 전부 여기서 나온다.
- **자소서 문항 간 소재 중복 감지를 백엔드로.** 지금은 프론트엔드 계산만.
- **Career Agent로 승격.** `agent.py`의 매칭 로직이 `apply.py` 안에서만 호출됨. "내 갭이 뭐야"
  같은 오픈엔디드 진로 상담용 대화형 엔드포인트로 독립시킨다.
- **Portfolio/Resume 생성기.** `report_html.py`는 자소서 결과 리포트일 뿐이다.
- **프로필을 Generative Agents식 reflection으로.** 단, 출처 링크 필수이고 독립 근거로는
  승격 금지(Stage 0 불변식 3).
- `profile.py` 증분 업데이트(지금은 매번 전체 재계산).

### Stage 4 — 평가·파일럿

- **Eval 셋 60케이스** (dev 40 / holdout 20). 사용자가 만든 8유형 테스트 프롬프트를
  `expected_experience_id`/`expected_evidence`/`expected_behavior` 필드를 가진 jsonl로 코드화.
  본인 데이터를 golden set으로 쓰는 게 제일 좋다(정답을 이미 아니까).
- **10~20명 파일럿.** 여기서 처음으로 "내 데이터에서만 동작하는지"가 검증된다.

### 의도적으로 안 하는 것

**채용공고 자동 수집(웹 검색/크롤링).** API 라이선싱·재판매 금지 조항 문제가 있어서, 사용자가
URL/원문을 직접 넣는 지금 방식을 유지한다.

---

## 8. 실행 방법 / 개발 환경

### 8.1 환경 변수 (`.env`, 레포 루트, git 안 올라감)
```
OPENAI_API_KEY=...
DATABASE_URL=postgresql://postgres.xxxx:비밀번호@aws-...pooler.supabase.com:5432/postgres
```
Supabase 연결 문자열은 대시보드 상단 "Connect" 버튼 → Direct 탭 → Connection Method를
**Session pooler**로(Direct connection은 IPv6 전용이라 가정용 인터넷에서 대부분 안 됨).

### 8.2 서버 실행
```
uv sync
uv run python -m skive.cli migrate        # 최초 1회, DB 스키마 생성
uv run python -m skive.cli sync-chunks    # 최초 1회(또는 원본 파일 바뀌었을 때), 청크+임베딩 채우기
uv run uvicorn skive.server:app --reload --port 8010
```
브라우저에서 `localhost:8010` 열면 됨.

### 8.3 알려진 인프라 이슈
- **`localhost:8000`이 이 개발 환경에서 좀비 프로세스로 막혀 있었음** — Bash 도구와
  PowerShell 도구가 서로 다른 프로세스/네트워크 네임스페이스를 보는 것으로 추정(PowerShell엔
  없다는 PID가 Bash의 curl엔 계속 응답함, taskkill도 "process not found"). 그래서 **`8010`
  포트를 씀.** 다음에 서버 켤 때도 특정 포트가 이상하면 다른 포트로 바꾸는 게 빠름.
- `_slugify()`(`server.py`)가 한글로만 된 회사명을 밀리초 타임스탬프로 대체함(ASCII만 남기면
  전부 "job"으로 뭉개져서 서로 덮어쓰는 실측 버그를 발견해 고침) — 임시방편, 7절 2번(DB 이관)
  하면 UUID를 쓰게 될 테니 자연히 없어질 문제.
- `POST /api/jobs`의 URL/PDF/이미지 파싱은 전부 동기 처리라 여러 소스를 한꺼번에 넣으면 응답이
  오래 걸릴 수 있음(7절 3번과 같은 근본 해결책 필요).

---

## 9. 참고
- 경쟁 서비스 조사함: 다글로/Lilys AI/UnivAI/ThetaWave — 전부 단일 문서 요약 도구, 크로스
  경험 프로필·공고매칭 기능 없음(SKIVE 차별점).
- 이 프로젝트 이전에 `bsj4333/skybe`라는 다른 시도(Next.js + Supabase, "AI 학습 아카이브"
  컨셉)가 있었고, 지금 쓰는 Supabase 프로젝트가 그때 만든 것. `public` 스키마에 그 흔적(14개
  테이블)이 남아있지만 지금 SKIVE와는 완전히 분리되어 있음(`skive` 스키마).
