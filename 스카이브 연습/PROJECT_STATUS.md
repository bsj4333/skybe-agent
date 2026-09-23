# SKIVE 프로젝트 현황 (2026-09-22 기준, 전면 개정)

> **2026-09-23 추가:** Supabase 기반 멀티유저 드라이브의 별도 경로와 DB/Storage 토대를 만들었다. 설정·실행·검증 상태와 아직 연결되지 않은 분석/자소서 범위는 [DRIVE_SETUP.md](DRIVE_SETUP.md)를 먼저 볼 것. 아래 본문은 기존 단일 사용자 기능에 대한 기록이다.

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

- **근거 기반(Evidence-grounded)이 목표다.** 지향점은 "원본 파일의 실제 문구와 대조된 것만
  사실로 취급하고, 안 되면 '확인 필요'로 표시한다"이고, 팀 성과를 본인 성과로 쓰는 왜곡도
  코드로 걸러낸다. `SKIVE_NEXT_PLAN.md`가 지적한 P0 결함 5개(F01~F05)는 **2026-09-23 기준
  전부 회귀 테스트로 고정하고 수정 완료했다** — 22개 테스트, xfail 0개.
  - **F01**: 정정이 검증 상태·원본 인용을 물려받던 문제. 새 버전은 근거 없이 시작한다.
  - **F02**: 챗봇 스코프가 읽기 도구엔 안 걸리던 문제. `RequestContext`+`ScopeGuard`가
    도구 실행 직전에 코드로 막는다(프롬프트 지시문이 아니라).
  - **F03**: 인용문이 원문에 존재하기만 하면 검증 통과되던 문제. 인용 존재·주장 지지·주체
    일치·수치 일치를 따로 검사한다.
  - **F04**: 판정자가 지적한 문장이 초안에 남아도 "정제"로 표시되던 문제. 문장마다 ID를
    매겨 판정 커버리지를 강제하고, 삭제 후 최종 결과를 다시 검사한다.
  - **F05**: `F1-score 0.71`을 근거로 "정확도 71%"가 통과하던 문제. 값이 스케일만 같으면
    (소수↔퍼센트) 숫자가 속한 절(clause)의 내용까지 겹치는지 확인한다.

  **남아 있는 한계**(과장하지 않기 위해 명시): 이 다섯은 "재현 가능했던 결함이 고쳐졌다"는
  뜻이지 "완벽히 근거 기반"이라는 뜻은 아니다. `get_profile`/`search_study`/`get_study`는
  아직 스코프 검사를 안 받고, 수치 비교는 정규식 기반 휴리스틱이라 이 프로젝트가 다루는
  한국어 자소서 문장 패턴 밖에서는 검증되지 않았다.
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

- **`WRITER_CORE_RULES`(고정, 절대 안 바뀜)**: 근거 없는 사실·수치·기술명 금지, 팀 성과를 본인
  것처럼 왜곡 금지, 역할 미확인 경험은 "내가 했다"고 못 씀. 이게 SKIVE 존재 이유라서 사용자도
  못 바꾼다.
  **(2026-09-23 사용자 피드백으로 조정)** 단, "[배운 점]이 원본에 명시돼 있어야만 소감·성장
  문장을 쓸 수 있다"는 예전 규칙은 풀었다 — 자소서에서 소감 문장은 사실상 필수인데, 원본
  자료엔 "느낀 점"이 잘 안 적혀 있어서 이 규칙 때문에 자연스러운 문장을 못 쓰는 경우가 많았다.
  지금은 확인된 사실(행동·성과)에서 자연스럽게 이어지는 소감은 [배운 점]이 없어도 쓸 수 있고,
  대신 그 소감 문장 안에서 새 사실(수치·자격·역할)을 지어내면 여전히 막는다 — "근거 없는 감상"과
  "확인된 사실에 기반한 소감"을 나눠서, 후자만 열어준 것. 위 세 가지 핵심 금지사항은 그대로다.
- **`essay_style`(사용자가 자유롭게 수정, `PUT /api/user`)**: 페르소나("10년차 컨설턴트"),
  STAR 구조, 지원동기/장단점 형식 같은 스타일 지침. 프로필 탭에 편집 UI 있음.
- 스타일이 규칙과 충돌하면 **규칙이 이긴다** — 프롬프트 안에 그렇게 명시했고, 실측으로도 STAR
  구조는 반영되면서 근거 없는 감상 문장은 그대로 걸러지는 것 확인함.

---

## 3. 지금까지 구현된 것 (기능별 상세)

### 3.1 경험 분석 (Ingestion)

**입력 경로 둘.** (a) 서버 로컬 폴더 경로(`POST /api/experiences`, 개발용 — 배포 서버에서는
남의 컴퓨터 폴더를 못 읽으므로 실사용자에게는 안 맞음). (b) **브라우저 업로드
(`POST /api/experiences/upload`, 2026-09-23 추가)** — 홈 화면 "새 폴더 열기"에서 폴더를
드래그해서 놓거나 "폴더 찾아보기"로 선택한다. 드래그는 `DataTransferItem.webkitGetAsEntry()`로
폴더 구조를 순회해서 **여러 폴더를 한 번에** 큐에 담을 수 있고(폴더마다 경험 하나), 찾아보기는
`<input webkitdirectory>`라 브라우저 제약상 한 번에 폴더 1개만 되지만 여러 번 눌러서 큐에
추가할 수 있다. 큐에 담긴 폴더들은 **순차적으로**(동시에 아님) 업로드·분석되고, 진행 상황을
폴더별로 성공/실패 표시한다. 서버는 각 파일명에 담긴 상대경로(`webkitRelativePath`/드롭 시
`fullPath`)를 그대로 써서 `data/uploads/<experience_id>/` 아래에 원래 폴더 구조를 재현한 뒤,
**경로 입력 방식과 완전히 같은 `analyze_folder`/`sync_chunks` 로직**을 그대로 탄다 — 분석
로직 자체는 하나만 유지한다. 재업로드하면 이전 파일을 완전히 지우고 새로 쓴다(부분 겹침 방지).
업로드는 파일 300개·파일당 15MB로 제한하고, 상대경로에 `..`나 절대경로가 섞여 있으면
거부한다(경로 주입 방지) — 아래 Stage 2 "보안 경계"가 지적한 문제 중 업로드 경로에 해당하는
부분은 여기서 먼저 해결됐다. **서버 로컬 경로 입력(a)은 여전히 그 문제가 있다** — `Path(req.folder)`를
검증 없이 그대로 여니까, 이건 어차피 개발자 본인만 쓰는 경로라 후순위.

(c) **압축파일(zip) 업로드(`POST /api/experiences/upload-zip`, 2026-09-23 추가)** — 파일을
하나하나 끌어다 놓기 번거로운 큰 폴더(과제 여러 개를 한 번에 담은 경우 등)를 위해 zip 하나로
올릴 수 있다. 드롭존에 zip 파일을 직접 끌어다 놓거나 "압축파일(zip) 선택" 버튼으로 고른다.
서버가 `zipfile`로 풀어서 (b)와 같은 `_finish_ingest()`를 탄다 — 분석 경로는 여전히 하나.
**zip slip(압축 안에 `../../etc/passwd` 같은 경로를 심어서 해제 대상 폴더 밖에 쓰는 공격)을
막는다** — 압축 해제 라이브러리를 믿지 않고, 각 항목의 경로가 실제로 대상 폴더 안으로
해석되는지 서버가 직접 확인한다(`dest.resolve().is_relative_to(root.resolve())`). 회귀
테스트로 고정함(`test_zip_upload_rejects_path_traversal_entries`). macOS/Windows가 압축에
끼워 넣는 `__MACOSX/`, `.DS_Store`, `Thumbs.db`는 자동으로 걸러낸다. 압축 총 용량은 200MB로
제한한다(zip bomb 방어).

폴더 경로 + 학년을 주면(`skive ingest` CLI 또는 위 두 API 중 하나로):
1. `loaders.py`가 폴더 안 파일(md/txt/csv/py/json/pdf/pptx 등)을 읽어 청크로 쪼갠다(텍스트는
   80줄 단위, PDF는 페이지 단위, PPTX는 슬라이드 단위). **CSV는 전체를 넣지 않고 헤더+20행
   미리보기만 넣는다(2026-09-23 수정).** 실측: 실사용자 폴더(캡스톤, 파일 365개)에 ML
   파이프라인 중간 산출물 CSV가 76개, 합쳐서 **7.9백만 자**(아래 `MAX_CHARS`의 40배) 있었다
   — 숫자 나열이라 LLM이 "무엇을 했는지" 읽는 데 거의 도움이 안 되면서 다른 파일(md, 코드)의
   진짜 서술형 근거를 밀어냈다. 행 수만 제한해서는 부족했다 — 센서 컬럼이 수백 개인 표는
   **20행만으로도 216,039자**였다(실측). 행 수와 글자 수를 둘 다 제한한다
   (`CSV_PREVIEW_ROWS`, `CSV_PREVIEW_CHARS`). CSV 미리보기 처리 후 같은 폴더는 295,492자로
   줄었다(tiktoken `o200k_base` 기준 100,897토큰 — gpt-4o-mini 128K 컨텍스트에 안전하게 들어감).
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

**업로드 직후 인터뷰 (2026-09-23 추가)**: 분석 직후 "요약 확인" 화면에 몇 가지를 더 물어본다
(`GET /api/experiences/{id}/intake-questions` → `POST /api/experiences/{id}/intake`).

- **왜 필요한가**: "원본에 명시된 것만 본인 역할로 인정"하는 기준은 그대로 유지하고 싶었다
  (F01이 막으려던 것과 같은 종류의 왜곡 — 팀 코드 저장소를 통째로 올렸다고 전부 본인 것으로
  치면 정반대 방향으로 같은 문제가 생긴다). 그런데 강의 PDF나 팀 코드에는 "이건 내가 했다"는
  문구가 애초에 잘 없어서, 이 기준만으로는 실제로 너무 자주 "확인 필요"가 뜬다. **문서 근거의
  엄격함은 그대로 두고, 대신 사용자에게 직접 물어봐서 답을 [본인 진술]로 명시적으로 기록하는
  통로를 만들었다.**
- 표준 질문 4개(역할/성과/배운점·기억에 남는 것/자유 코멘트) + **팀 활동으로 기록된
  사실 중 최대 3개를 콕 집어 "본인이 주도했나요? 어떤 판단 기준으로 하셨나요?"로 물어보는
  질문**(`_ownership_check_questions`) + 분석 중 못 채운 `open_questions`를 합쳐서 보여준다.
  후자는 사용자 피드백(2026-09-23 후속)을 반영한 것 — "AI가 업로드했으니 네 것이라고
  추측하는 건 여전히 안 하지만, 팀 활동으로 남은 것 중 실제로 사용자가 주도한 부분이 있으면
  콕 집어 물어보고 확인받아서 기록하자"는 요청. 확인해도 **원래 팀 기록은 지우거나 덮어쓰지
  않는다** — 사용자의 답이 별도의 [본인 진술] 사실로 나란히 추가된다(팀 기록=문서 근거,
  본인 진술=사용자 확인, 둘 다 남아서 감사 가능).
- 답변은 `corrections.py`의 기존 정정 파이프라인(`apply_correction`)을 그대로 탄다 — 역할·
  배운점은 [본인 진술, 원문 근거 없음]으로 덮어쓰고, 성과·기타는 새 사실로 추가되며, 전부
  `provenance_type=user_statement`로 저장돼 검증된 문서 근거와 절대 안 섞인다.
- **이 기능을 만들다가 실제 버그를 하나 발견해서 고쳤다**: My Role과 Lessons가 둘 다 미확인
  상태면 둘 다 "확인 필요"로 시작하는데, 정정 시 `markdown.replace(old_text, ..., 1)`이 문서
  **전체**에서 첫 번째로 걸리는 자리를 바꿨다. My Role을 먼저 정정하면 그 줄에
  "(기존: 확인 필요)"라는 감사 기록이 남는데, 그다음 Lessons를 정정할 때 "확인 필요"를 문서
  전체에서 찾으면 이 감사 기록 안의 문구가 먼저 걸려서, My Role 줄이 또 한 번 잘못
  덮어써지고 정작 Lessons 섹션은 안 바뀌는 사고가 실제로 났다. `_replace_in_section()`으로
  섹션 범위 안에서만 찾고 바꾸게 고쳤고, 회귀 테스트로 고정함
  (`test_correction_does_not_cross_into_other_section_with_same_placeholder`).

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

**문장 판정과 삭제 (P0-5, F04 수정 완료)**: `_check()`가 초안을 마침표/물음표/느낌표
뒤 공백 기준으로 문장 단위로 쪼개(`split_sentences`, 소수점은 뒤에 공백이 없어 안 잘림)
`[S1] 문장1\n[S2] 문장2…`처럼 ID를 붙여 판정자에게 준다. 판정자가 입력에 있던 ID를
빠뜨리면("커버리지 누락") 통과가 아니라 실패로 센다 — 예전엔 판정자가 살짝 바꿔 쓴
문장("이뤘습니다"→"이루었습니다")이 원문과 문자열이 안 맞아 삭제가 조용히 실패했는데도
상태는 "정제"로 표시됐다. 지금은 삭제할 문장을 판정자의 사본이 아니라 **우리가 나눈
원문 문장 리스트에서** 가져오므로 항상 정확히 일치한다. `_remove_flagged()`가 삭제 후
최종 텍스트를 한 번 더 검사해서, 혹시 안 지워진 게 남으면 "정제"가 아니라 "경고"로
내린다.

**대화형 수정(`POST /api/jobs/{id}/answers/{index}/revise`)**: "두 번째 문장 빼고 더
구체적으로 써줘" 같은 요청을 `writer.revise_answer()`가 받아서, **같은 근거 자료 범위
안에서만** 다시 쓰고 같은 judge 검증을 한 번 더 거친다. 근거 밖 요청이면 안 바꾸고 이유를
알려준다. 요청 이력은 `answer.revisions`에 남는다.

### 3.4 챗봇

`chat.py`, LangGraph Agent. 도구: `get_profile`, `list_experiences`, `get_experience`,
`get_evidence`(원본 파일 읽기), `search_study`, `get_study`, **`save_note`/`list_notes`/
`get_note`(경험 폴더에 메모 파일 쓰기/읽기, 원본은 절대 안 건드림)**.

- **스코프 (P0-2에서 개정, F02 수정 완료)**: 특정 경험 폴더로 좁히면 `skive/context.py`의
  `RequestContext(active_scope_id=...)`가 만들어지고, `_build_tools(ctx)`가 `get_experience`/
  `get_evidence`/`list_experiences`/`save_note`/`list_notes`/`get_note` **전부**를
  `guard_experience_id(ctx, experience_id)`로 감싼다. 다른 experience_id가 인수로 들어오면
  실제 조회 전에 거부하고, 존재 여부도 알려주지 않는 안전한 메시지만 돌려준다(`out_of_scope`).
  실측: 스코프를 `3d_printer_raw`로 건 채팅에서 "`club_website_raw`를 읽어줘"라고 요청하면
  LLM이 도구를 호출하긴 하지만 서버가 막고, 사용자에게는 "이 범위 밖입니다"로 응답한다.
  **예전에는 프롬프트("다른 경험을 읽지 마라")로만 걸려 있었다 — 이제는 도구 실행 직전에
  코드가 검사한다.** `list_experiences`도 스코프가 있으면 그 경험 하나만 보여준다(다른
  id를 목록으로 노출하면 다음 호출에서 스코프를 우회하는 통로가 되기 때문). 반대로
  `agent.py`(공고 매칭)처럼 스코프가 없는 호출은 원래대로 전체를 본다 — 이건 의도된
  동작이다(그 에이전트의 일은 여러 경험을 넘나들며 비교하는 것).
  **남은 한계**: `get_profile`/`search_study`/`get_study`는 스코프 검사를 안 받는다.
  `get_profile`은 애초에 특정 경험 하나가 아니라 전체 사용자의 집계 결과라 성격이 다르고,
  `search_study`/`get_study`는 공부 세션이 여러 경험을 넘나드는 주제라 지금 단계에서는
  의도적으로 남겨뒀다(단, `search_study`의 `related_experience_ids`로 다른 경험의 존재
  *자체*는 알 수 있다 — `get_experience`처럼 원문 내용이 새는 것보다 심각도가 낮다고
  판단해 후순위로 미룸).
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
- **서버 세션 (P0-3, 2026-09-23 완료).** 예전엔 대화가 브라우저 변수 `chatHistory`에만
  있어서 새로고침하면 사라졌고, 서버는 매 요청마다 클라이언트가 보낸 history를 그대로
  믿었다. 지금은 `chat.py`의 `CHECKPOINTER`(LangGraph `SqliteSaver`, `data/sessions.sqlite3`)가
  `session_id`(=LangGraph의 `thread_id`)로 대화를 서버에 들고 있는다.
  - `POST /api/chat/sessions`가 새 `session_id`를 발급하고 그 순간의 `scope_id`에 고정시킨다.
  - `POST /api/chat`에 `session_id`가 있으면 클라이언트가 보낸 `history`는 **무시**하고,
    새 메시지 하나만 서버에 보낸다 — `ask_in_session()`이 체크포인터에서 이전 대화를
    이어붙인다. `session_id`가 없는 요청은 예전 방식(무상태, history 그대로 신뢰)으로
    당분간 호환 유지.
  - **세션은 범위 하나에 고정된다(R08).** 같은 `session_id`로 다른 `scope_id`를 보내면
    `400`으로 거부한다 — 실측: `3d_printer_raw`로 시작한 세션에 `club_website_raw`를
    보내면 `"이 세션은 '3d_printer_raw' 범위로 시작됐습니다..."` 응답. 프론트엔드
    `setScope()`도 범위를 바꾸는 순간 이전 세션을 종료(`endChat`)하고 `chatHistory`를
    비운 뒤 새 세션으로 넘어가게 고쳤다 — 예전엔 `scope`만 바뀌고 대화 문맥은 안
    분리돼서 다른 프로젝트 얘기가 새 범위 질문에 섞여 들어갈 수 있었다.
  - `POST /api/chat/end`도 클라이언트가 보낸 `history`가 아니라 `chat_session_id`로
    서버가 실제 기록한 대화(`get_session_messages()`)를 읽어서 공부 세션을 만든다 —
    클라이언트가 대화 내용을 조작해서 요약을 만들어낼 수 없다. **프론트엔드에 "대화 종료"
    버튼을 추가해 처음으로 연결했다** — 예전엔 `/api/chat/end` 호출부가 프론트엔드에
    0개라 공부 세션 요약이 웹에서는 한 번도 안 돌고 있었다.
  - **남은 한계**: 세션↔범위 매핑(`_SESSION_SCOPES`)은 서버 프로세스 메모리에만 있어서
    재시작하면 초기화된다(최악의 경우 스코프 고정이 풀리는 것이지, 대화 데이터 자체가
    섞이지는 않는다 — 체크포인터의 메시지는 `session_id`별로 완전히 분리 저장됨).
    영구화하려면 이 매핑도 DB로 옮겨야 한다(Stage 2, DB 이관 때 같이).

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
│   ├── verify.py            근거 인용이 원문에 실제로 있는지 대조하는 저수준 유틸.
│   │                        `number_mentions()`가 수치 검증도 담당(F05 수정) — 값이 완전히
│   │                        같으면 단위 충돌만 확인하고, 소수↔퍼센트처럼 스케일만 같으면
│   │                        숫자가 속한 절(문맥)까지 겹치는지 봐서 "F1-score 0.71"과
│   │                        "정확도 71%"처럼 다른 지표가 우연히 같은 숫자를 갖는 경우를 가른다
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
│   ├── context.py            RequestContext + ScopeGuard. 도구 실행 직전 스코프를
│   │                         코드로 강제하는 곳(P0-2, F02 수정). 하네스가 권한을 갖는 지점
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
│   ├── sessions.sqlite3          **(gitignore 대상, P0-3)** 챗봇 대화 세션(LangGraph
│   │                             checkpointer). 위 나머지와 달리 계속 바뀌는 런타임 상태라
│   │                             git으로 안 올림
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

## 7. 남은 과제 — 실행 계획 (2026-09-23, DeepAgents 반영본 채택)

두 문서가 이 프로젝트의 실행 계획이다:

- **`SKIVE_NEXT_PLAN.md`** — 외부 리뷰(아스트로)의 원본 전체 계획. P0 결함 F01~F05를
  최초로 정의했고, 근거는 여기에 있다.
- **`SKIVE_NEXT_PLAN_DeepAgents_반영본.md`** — 위 계획을 DeepAgents(LangChain 팀의
  에이전트 하네스 설계)의 관례로 재구성한 **실행용 문서. 지금부터는 이 문서를 따른다.**
  DeepAgents *패키지*를 설치하는 게 아니라, 그 하네스 원칙(요청 문맥이 권한을 가짐,
  체크포인터=스레드 상태/사실 저장소=장기 기억의 분리, 실행 예산, 프롬프트 캐시 계측)을
  지금 구조(FastAPI+LangGraph) 위에 그대로 얹는다는 점이 핵심이다. F01~F05는 이 문서의
  R02/R03/R04/R05/R01·R08로 재명명되고, 세션 복원(R07)과 반복 호출 차단(R06)이 새로 추가됐다.

**채택 이유** (비판적으로 읽은 결과, 타당하다고 판단): (1) F02 수정을 "프롬프트에 스코프
지시문 추가"가 아니라 `RequestContext` + 도구 실행 직전 검사라는 구체적 코드 패턴으로
명세해서, 지금까지 우리가 겪은 "코드로 보장한다고 썼는데 실제로는 프롬프트였다"는
실수(0-8 참고)를 구조적으로 막는다. (2) 세션 지속성을 커스텀 `sessions`/`messages` 테이블
대신 **LangGraph가 이미 제공하는 checkpointer**(`SqliteSaver`→`PostgresSaver`)로 처리하라고
명시해서 불필요한 재구현을 줄인다. (3) 서브에이전트·요약·샌드박스 같은 P2 항목에 "측정된
병목이 있을 때만 도입"이라는 명확한 게이트를 걸어서 지금 단계(1인 개발, 샘플 데이터)에
어울리지 않는 기능을 미리 만들지 않게 막는다. (4) DeepAgents 패키지 전면 도입, `chat.py`/
`agent.py` 재작성을 명시적으로 배제했다 — 12월 데모 앞두고 프레임워크를 바꾸는 위험을
피한 것은 맞는 판단이다.

**보류한 판단**: P0-7(프롬프트 캐시 계측, provider별 `cached_tokens` 기록)은 1인 개발·
`gpt-4o-mini` 기준 지금 당장 비용 문제가 없어 구현을 나중으로 미룬다. 다만 "고정 접두사
뒤에 가변 블록을 둔다"는 프롬프트 순서 원칙만은 지금부터 지킨다(공짜이고, 나중에 캐시
계측을 붙일 때 다시 손대지 않아도 된다).

**중요**: 원래 로드맵 1번 "스키마 확정 ✅"은 여전히 다시 열려 있다. `verified` 불리언
하나가 "인용문이 원문에 존재함"과 "주장이 근거로 지지됨"과 "주체가 본인임"을 전부 뭉개고
있었기 때문이다(F03/R03). 이걸 먼저 안 고치면 DB 이관을 두 번 하게 된다.

### P0 진행 상황 (`SKIVE_NEXT_PLAN_DeepAgents_반영본.md` §3 기준)

| # | 항목 | 대상 파일 | 상태 |
|---|---|---|---|
| P0-1 | 회귀 테스트를 먼저 고정(R01~R08) | `tests/test_p0_regressions.py` | 🟡 R01~R05/R08 완료(22 tests), R06/R07 미착수 |
| P0-4 | 사실 상태 모델 v2 문서화 + 정정이 검증 상태·원본 인용을 물려받지 않게(R02) | `SCHEMA.md` §2, `skive/facts.py`, `corrections.py`, `writer.py` | ✅ 완료 |
| P0-5 (추출 검증) | 인용 존재·주장 지지·주체 일치·수치 일치를 분리 검사(R03) | `analyzer.py`, `verify.py` | ✅ 완료 |
| **P0-2** | **`RequestContext` + 모든 도구의 `ScopeGuard`**(R01/R08) — 스코프를 프롬프트가 아니라 코드로 강제 | `skive/context.py`(신규), `chat.py` | ✅ 완료 |
| **P0-5 (작성 검증)** | **문장 ID + 판정 커버리지 + 최종 재검증(R04)** | `writer.py`, `models.py` | ✅ 완료 |
| **P0-5 (수치 스케일·문맥)** | **값이 스케일만 같으면(소수↔퍼센트) 절 단위 문맥 겹침까지 확인(R05)** | `verify.py` | ✅ 완료 |
| **P0-3** | **서버 세션 + LangGraph checkpointer(R07/R08)** | `chat.py`, `server.py`, `skive_ui.html` | ✅ 완료 |
| P0-6 | 실행 예산(`model_calls`/`tool_calls`/`same_tool_same_args_count`)·구조화 오류(R06) | `chat.py`, `agent.py` | ⬜ |
| P0-7 | 프롬프트 순서 고정(지금) / 캐시 계측(보류) | — | 🟡 원칙만 적용 |

**P0의 정확성 축(F01~F05)은 여기서 전부 끝났다.** 남은 P0 항목(P0-3/P0-6)은 정확성이
아니라 인프라(세션 지속성·실행 예산)라서 성격이 다르고, 각각이 더 큰 변경(서버 세션
스키마, 여러 도구 파일에 예산 훅 추가)을 요구해 독립적인 작업 단위로 남겨뒀다.

이전 세션 문구였던 "0-1~0-8" 번호는 위 표의 P0-1/P0-4/P0-5로 재매핑됐다 — 작업 내용은
전부 유지되고 이름만 DeepAgents 반영본 기준으로 바뀌었다.

Stage 0의 설계 원칙 3가지(`SCHEMA.md` §2.4에 불변식으로 명문화):
**상속 금지**(새 버전은 이전 버전의 근거·검증 상태를 못 물려받는다) /
**원본 보존**(정정해도 이전 버전은 `superseded`로 남는다) /
**승격 금지**(파생물 — 프로필·성찰 — 은 독립 근거가 될 수 없다).

### Stage 1 — 연결 누락 메우기 (UI ↔ 백엔드)

- ✅ **서버 세션 + `POST /api/chat/end` 연결 (P0-3, 2026-09-23 완료).** 아래 3.4/8.3 참고.
- ✅ **브라우저 폴더 업로드 (2026-09-23 완료).** 아래 3.1/8.3 참고 — 서버 로컬 경로 입력은
  개발용 대안으로 남겨뒀다.
- ingest·공고 분석을 **비동기 잡 + `run_id` 폴링/SSE**로 (지금 동기 블로킹) — 폴더 업로드가
  여러 개 큐에 쌓이면서 이 필요성이 더 커졌다(지금은 순차 처리라 폴더 수만큼 기다려야 함)
- 역할 확인 루프: "확인 필요"로 강등된 `my_role`을 사용자에게 되묻는 UI
- 근거 패널: 문장 클릭 → 원본 청크 표시

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
- **파일 업로드에 숨어 있던 3중 상한 (2026-09-23, 실사용자 폴더 371개로 실측 발견)**:
  1. **Starlette 멀티파트 파서의 기본값 `max_files=1000`** — FastAPI가 `File(...)`/`Form(...)`
     자동 파싱을 쓰면 이 기본값이 그대로 적용돼서, 우리 코드(`MAX_UPLOAD_FILES`)가 실행되기도
     전에 "Too many files. Maximum number of files is 1000."로 끊긴다. **고침**: `/api/experiences/
     upload`가 이제 `Request.form(max_files=...)`을 직접 호출해서 이 기본값을 우회한다.
  2. **우리 자체 `MAX_UPLOAD_FILES`가 300이었음** — 초기 샘플 데이터 기준의 보수적인 값.
     **고침**: 환경변수 `SKIVE_MAX_UPLOAD_FILES`로 조절 가능, 기본값 2000으로 올림.
  3. **`analyzer.py`의 `MAX_CHARS`(폴더 전체를 한 번의 LLM 호출로 보내는 상한)가 60,000자였음**
     — 파일 개수 제한을 풀어도 이게 남아있으면 큰 폴더는 여기서 또 막힌다. 처음엔 200,000자로
     올렸는데, 그래도 실사용자 폴더(365개 파일 캡스톤)가 **7,948,547자**로 이 검사에 걸렸다
     (아래 "CSV 미리보기" 항목 참고 — 원인은 원본 CSV를 통째로 넣던 것). CSV를 미리보기로
     바꾸니 같은 폴더가 295,492자(tiktoken `o200k_base`로 실측: 100,897토큰, gpt-4o-mini 128K
     컨텍스트에 안전)가 됐다. **고침**: 이 실측을 근거로 `MAX_CHARS` 기본값을 320,000자로
     조정(환경변수 `SKIVE_ANALYZER_MAX_CHARS`로 추가 조절 가능). **단, 이건 상한을 올린
     것이지 큰 폴더를 제대로 처리하는 아키텍처가 아니다** — 진짜 해결책(청크를 나눠 여러 번
     분석 후 합치는 map-reduce)은 아직 미구현이고, 이 상한도 결국 넘는 폴더가 있을 수 있다.
  4. **위 1번을 고치다가 만든 회귀**: `Request.form()`이 돌려주는 `UploadFile`은
     `starlette.datastructures.UploadFile`인데, `isinstance` 검사를 `fastapi.UploadFile`
     (그 서브클래스)로 해서 업로드된 파일이 매번 "없음"으로 처리됐다. 베이스 클래스로
     검사하도록 고치고, 1200개 파일 업로드를 회귀 테스트로 고정함
     (`test_upload_accepts_more_than_the_old_1000_file_default`).
  5. **`analyze_folder`의 `ValueError`("폴더가 너무 큼" 등)가 안 잡혀서 FastAPI가 그냥
     500(Internal Server Error)으로 감쌌음** — 위 3번 같은, 사용자가 이해할 수 있는 입력
     오류인데 화면엔 원인이 하나도 안 보였다(실측). **고침**: `_finish_ingest()`에서 잡아서
     400 + 실제 이유를 그대로 보여준다. `ingest_experience`(경로 입력 경로)도 중복 코드
     대신 `_finish_ingest()`를 쓰도록 정리해서 이 처리를 같이 받는다.
- **Supabase 연결이 간헐적으로 끊길 수 있음(2026-09-23 실측)**: `sync_chunks()`가
  `psycopg.OperationalError: server closed the connection unexpectedly`로 실패하는 걸
  확인함(여러 pooler IP에 다 시도 후 최종 타임아웃). Supabase 무료 플랜은 **일정 기간 활동이
  없으면 프로젝트를 자동으로 일시정지(pause)한다** — 증상이 정확히 이 패턴과 일치한다.
  **파일 업로드 개수 제한과는 무관한 별개 문제**이고, 유료 전환이 지금 당장 이 문제를
  해결해주지 않는다(이미 일시정지된 프로젝트는 유료로 바꿔도 대시보드에서 직접 다시
  켜야 함) — 다만 유료 플랜은 애초에 자동 일시정지가 없어서 앞으로 이런 일이 안 생기게는
  해준다. **대시보드에서 프로젝트 상태를 확인해봐야 함(내가 직접 켤 수 없음 — 계정 소유자만
  가능).** 대시보드가 "Healthy"로 떠도(2026-09-23 확인) 실제 연결은 이후에도 여러 번 다시
  끊겼다 — Supabase 쪽이 아니라 이 개발 환경과 Supabase 사이 네트워크 경로 자체가 불안정할
  가능성도 있다. 근본 원인은 아직 못 찾았고, 대신 아래 두 가지로 **DB가 끊겨도 이미 끝난
  작업이 안 날아가게** 만들었다:
  - `db.py`에 `connect_timeout=5`를 추가했다. 원래는 pooler 뒤의 IP 여러 개를 하나씩
    시도하다가 OS 기본 TCP 타임아웃(1분+)을 다 기다려서, 업로드 요청 하나가 90초 넘게
    응답이 없는 걸 실측함. 지금은 실패해도 훨씬 빨리 실패한다.
  - `_finish_ingest()`가 `sync_chunks()` 실패를 더는 전체 요청 실패로 취급하지 않는다.
    분석·저장(`analyze_folder`, `store.save`)은 이미 끝난 뒤에 검색 인덱스 동기화만
    실패하는 경우라, 그것 때문에 (비용이 드는) LLM 분석을 처음부터 다시 돌리게 하면 안
    된다. `meta.chunks_synced=false`로 표시하고, `POST /api/experiences/{id}/sync-chunks`로
    나중에 그 부분만 재시도할 수 있다. 화면에도 "검색 인덱스 동기화 실패 — 다시 시도" 배너와
    버튼을 띄운다.

---

## 9. 참고
- 경쟁 서비스 조사함: 다글로/Lilys AI/UnivAI/ThetaWave — 전부 단일 문서 요약 도구, 크로스
  경험 프로필·공고매칭 기능 없음(SKIVE 차별점).
- 이 프로젝트 이전에 `bsj4333/skybe`라는 다른 시도(Next.js + Supabase, "AI 학습 아카이브"
  컨셉)가 있었고, 지금 쓰는 Supabase 프로젝트가 그때 만든 것. `public` 스키마에 그 흔적(14개
  테이블)이 남아있지만 지금 SKIVE와는 완전히 분리되어 있음(`skive` 스키마).
