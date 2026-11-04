# SKIVE Personal Knowledge Schema (2026-09-22)

지금 `data/store/*`, `data/study/*`, `data/profile/`, `data/user.json`, `data/outputs/*`에 흩어진
플랫파일을 PostgreSQL + pgvector로 옮기기 위한 스키마. 여러 사용자가 쓰는 실제 플랫폼을
가정하고 처음부터 `user_id`를 넣었다.

이 문서는 코드보다 먼저 확정한다 — 여기서 정한 필드가 이후 `analyzer.py`가 뭘 추출해야
하는지, `chat.py`/`corrections.py`가 뭘 조회·수정할 수 있는지를 결정한다.

## 1. 개념 스키마 (Ontology)

경험(Experience) 하나는 최소한 이 필드들을 가진다. 지금 코드가 이미 채우고 있는 필드와,
지금은 유실되고 있어서 이번에 추가해야 하는 필드를 구분했다.

```
Experience
├─ id, user_id, slug (사람이 읽는 식별자, 지금 폴더명과 대응)
├─ type            (project/course/activity/award/other)      — 있음 (kind)
├─ period                                                       — 있음
├─ organization                                                — ⚠️ 없음: analyzer.py가 뽑기는 하지만
│                                                                  experience.md 텍스트에만 박히고
│                                                                  metadata.json/facts.json엔 저장 안 됨
├─ problem                                                     — ⚠️ 없음: 위와 동일한 유실
├─ my_role, my_role_verified, my_role_corrected_from            — 있음
├─ actions[], decisions[], results[]  (각각 text/owner/verified) — 있음 (facts.json)
│    └─ evidence[] (source_file, location, quote, verified)     — 있음 (fact.sources, 근데 quote 원문은
│                                                                  현재 저장 안 하고 위치 문자열만 저장함
│                                                                  → 이번에 quote까지 저장하도록 확장)
├─ skills[]                                                    — 있음
├─ lessons                                                     — 있음
├─ open_questions[]                                            — 있음
├─ evidence_total, evidence_verified                            — 있음
├─ importance (score/tier/breakdown/reason)                     — 있음
└─ related_experiences[]                                       — ❌ 없음: 지금 경험끼리 명시적 연결이 없음.
                                                                    v1 DB에서도 별도 테이블 대신 profile의
                                                                    competency/trait이 간접 연결 역할.
                                                                    "관계 탐색"이 핵심 기능이 되면 그때
                                                                    experience_links 테이블 추가 검토.
```

`context`/`goal`은 지금 논의에서는 `problem`과 `career_goal`(사용자 레벨)로 대체해서 별도
필드를 만들지 않았다 — 실제 코드(`Experience.problem`, `user.career_goal`)와 1:1로 맞춘 것.

> ⚠️ 위 §1의 `verified` 기반 사실 표현은 **폐기됐다.** 아래 §2의 v2 상태 모델로 대체한다.

## 2. 사실 상태 모델 v2 (2026-09-22 개정)

### 2.1 왜 바꾸는가 — 실제로 재현된 결함

`verified` 불리언 한 칸으로는 서로 다른 질문 세 개를 구분할 수 없다: **누가 말했나**,
**근거가 주장을 실제로 뒷받침하나**, **아직 유효한 사실인가**. 구분할 자리가 없으니 코드도
구분하지 못했고, 아래가 실제 구현에서 재현됐다 (LLM 없이 순수 함수로 확인).

| 재현 | 결과 |
|---|---|
| 채팅으로 `"F1-score는 사실 0.99였다"`로 정정 | `verified: true` 유지 + 원본 인용 `[근거: r.md @ L1-10]`까지 상속, `writer.build_bundle()`에 그대로 유입 |
| 역할을 `"팀원이 구현했고 나는 참여만 함"`으로 정정 | `my_role_verified: true` 유지 |
| 주장 `"내가 Kubernetes를 구축했다"` + 인용 `"팀은 보고서를 작성했다"` | `verified: true` (인용문 존재 여부만 검사), quote는 **저장도 안 됨** |

즉 **사용자의 캐주얼한 정정이 "문서로 검증된 사실"로 승격되어 자소서 근거가 된다.** 이건
제품의 핵심 약속을 정면으로 깨는 것이라 다른 무엇보다 먼저 고친다.

### 2.2 사실 하나가 가지는 상태

| 필드 | 값 | 뜻 |
|---|---|---|
| `provenance_type` | `document` / `user_statement` / `derived` | 누가 말했나. 업로드 원본에서 추출 / 사용자가 직접 진술 / 다른 사실에서 모델이 요약·추론 |
| `evidence_status` | `unlinked` / `quote_matched` / `supported` / `contradicted` / `needs_review` | 근거가 주장을 뒷받침하나. **`quote_matched`는 "인용문이 원문에 글자 그대로 있다"일 뿐 주장 지지가 아니다** |
| `lifecycle` | `active` / `superseded` / `retracted` | 지금도 유효한가 |
| `review_state` | `proposed` / `accepted` / `rejected` | 사용자가 확인했나 |
| `owner` | `self` / `team` / `other` / `unknown` | 누가 한 일인가 (현재 JSON은 `본인`/`팀` 두 값만 씀 → DB 이관 때 정규화) |
| `fact_id`, `version`, `supersedes_id` | | 사실의 정체성과 변경 이력 |
| `recorded_at`, `superseded_at` | | 시스템이 알게 된 시점 |
| `evidence[]` | `{source, location, quote, quote_matched, supports_claim, owner_match}` | **quote 원문을 반드시 저장한다.** 저장 안 하면 사후 감사가 불가능 |

LLM이 내놓는 confidence 숫자 하나로 위 상태를 대체하지 않는다. 원본 문서도 현실의 진실을
보장하지 않으므로 UI는 "사실 인증"이 아니라 **"자료에서 확인"**이라고 쓴다.

### 2.3 읽는 쪽이 지켜야 할 규칙

- **자소서 근거 번들**은 `document` 사실과 `user_statement` 사실을 **분리된 항목으로** 넘긴다.
  섞어서 넘기면 작성 모델이 출처를 구분할 방법이 없다.
- `user_statement`는 개인 초안에 **쓸 수 있다.** 다만 출처 배지를 표시하고, 그 문장에 없던
  수치·고유명사를 덧붙여 보강하지 않는다. (나중에 "문서 근거만 사용" 토글 추가)
- `derived`(프로필의 역량·성향)는 **새 독립 근거로 승격하지 않는다.** 입력 사실이 철회되면
  해당 해석도 stale.
- 배지 문구: `document` → "자료에서 확인", `user_statement` → "본인 확인", `derived` → "AI 해석".

### 2.4 불변 규칙 (이번 개정의 핵심)

1. **상속 금지.** 사실의 텍스트가 바뀌면 이전 `evidence`와 `evidence_status`를 물려받지 않는다.
   새 버전은 `evidence_status = needs_review`에서 시작한다.
2. **원본 보존.** 이전 버전은 지우지 않고 `lifecycle = superseded`로 남긴다. 정정된 주장과
   원문이 다르면 둘을 나란히 보여준다.
3. **승격 금지.** 사용자 확인은 `review_state`를 올릴 뿐 `provenance_type`을 `document`로
   바꾸지 않는다.

### 2.5 JSON 표현 (Stage 0에서 지금 구현, DB 이관 전까지)

DB 이관은 Stage 2다. 그 전까지는 `data/store/<id>/facts.json`에 아래 형태로 쓴다.
필드 이름은 §2.6의 테이블과 1:1이라 이관할 때 재설계가 필요 없다.

```jsonc
{
  "results": [                      // active 버전만 이 배열에 둔다
    {
      "fact_id": "…", "version": 2, "supersedes_id": "…",
      "text": "FastAPI 서버는 팀원이 만들었다.",
      "owner": "팀",
      "provenance_type": "user_statement",
      "evidence_status": "needs_review",
      "lifecycle": "active",
      "review_state": "accepted",
      "evidence": [],               // ← 이전 인용을 상속하지 않는다
      "prior_evidence": [ … ],      // 감사용으로만 보관, 근거로 쓰지 않음
      "recorded_at": "2026-09-22T…"
    }
  ],
  "superseded": [ { …version 1 전문, "lifecycle": "superseded"… } ]
}
```

v1 필드(`verified`, `tag`)를 아직 가진 사실은 **legacy로 읽는다** — 읽기 시점에 §2.6의
매핑을 적용하고, 파일을 일괄 재작성하지는 않는다. 새로 ingest하는 경험은 0-2부터 위 구조로
직접 쓴다(`facts.document_fact()`).

**`evidence[]` 한 칸이 담는 것** (0-2에서 `analyzer._inspect()`가 채움):

```jsonc
{
  "chunk_id": "C3", "source": "보고서.md", "location": "L1-31",
  "quote": "F1-score가 0.71에서 0.86으로 향상되었다.",  // ← 반드시 저장
  "quote_matched": true,    // (a) 인용문이 원문에 글자 그대로 있는가
  "supports_claim": true,   // (b) 인용문이 주장과 내용을 공유하는가 (겹침 ≥ 0.3)
  "owner_match": true,      // (c) "내가" 주장에 "팀은" 인용문이 붙지 않았는가
  "numbers_missing": [],    // (d) 주장에 있는데 인용문엔 없는 수치
  "ok": true                // 위 넷 전부
}
```

네 검사를 따로 기록하는 이유: 하나로 합치면 **왜** 떨어졌는지 알 수 없고, 그러면 사용자에게
"이 문장은 왜 안 쓰였나"를 설명할 수도, 나중에 임계값을 조정할 수도 없다.

### 2.6 v1 → v2 매핑 (기존 경험 6건·사실 33건)

| v1 | v2 | 주의 |
|---|---|---|
| `verified: true` | `provenance_type=document`, `evidence_status=`**`quote_matched`** | **`supported`로 올리지 않는다.** v1 검사는 인용문 존재만 봤고, F03이 그 한계를 증명했다 |
| `verified: false` | `provenance_type=document`, `evidence_status=unlinked` | |
| `sources: ["r.md @ L1-31"]` | `evidence[].source` + `.location` | `quote`는 v1에 없으므로 `null`로 두고 `needs_review` |
| `my_role` + `my_role_verified` | `kind='my_role'`인 사실 1건 | Stage 0에선 JSON 평탄 필드 유지(읽는 코드가 5곳), Stage 2에서 통합 |
| `evidence_total` / `evidence_verified` | `evidence_status`별 집계로 대체 | 지금 "41/41"은 **인용 검사 통과 수이지 사실 정확도가 아니다** |

없는 quote를 만들어 채우지 않는다. 모르는 것은 `needs_review`로 남기고 재검증 대상에 넣는다.

## 3. PostgreSQL 스키마

기존 Supabase 프로젝트를 그대로 재사용하기로 해서, 다른 용도의 테이블과 이름이 겹칠 걱정 없이
전부 **`skive` 스키마**(네임스페이스) 안에 넣는다. Supabase 대시보드의 Table Editor에서도
"schema: skive"로 필터링하면 이 프로젝트 테이블만 보인다.

```sql
create extension if not exists vector;
create extension if not exists pgcrypto;  -- gen_random_uuid()
create schema if not exists skive;

-- ── 사용자 ────────────────────────────────────────────────
create table skive.users (
    id              uuid primary key default gen_random_uuid(),
    email           text unique not null,
    name            text not null,
    school          text,
    major           text,
    grade           int,
    admission_year  int,
    career_goal     text,
    created_at      timestamptz not null default now()
);

-- ── 경험 ──────────────────────────────────────────────────
create table skive.experiences (
    id                     uuid primary key default gen_random_uuid(),
    user_id                uuid not null references skive.users(id) on delete cascade,
    slug                   text not null,          -- 기존 experience_id (폴더명)
    title                  text not null,
    summary                text not null,
    kind                   text not null check (kind in ('project','course','activity','award','other')),
    grade                  int not null,
    period                 text,
    organization           text,                   -- 신규: 지금 유실되는 필드
    problem                text,                   -- 신규: 지금 유실되는 필드
    skills                 jsonb not null default '[]',
    -- my_role* 컬럼은 v2에서 제거: experience_facts의 kind='my_role' 사실로 통합
    lessons                text,
    open_questions         jsonb not null default '[]',
    evidence_total         int not null default 0,
    evidence_verified      int not null default 0,
    importance_score       int,
    importance_tier        text,
    importance_breakdown   jsonb,
    created_at             timestamptz not null default now(),
    updated_at             timestamptz not null default now(),
    unique (user_id, slug)
);

-- ── 경험 안의 개별 사실 (v2: §2 상태 모델) ───────────────────
-- my_role도 kind='my_role'인 사실 1건으로 통합한다 (experiences의 my_role* 컬럼 제거).
create table skive.experience_facts (
    id               uuid primary key default gen_random_uuid(),
    experience_id    uuid not null references skive.experiences(id) on delete cascade,
    fact_id          uuid not null,   -- 버전이 바뀌어도 유지되는 사실의 정체성
    version          int  not null default 1,
    supersedes_id    uuid,            -- 직전 버전 행의 id
    kind             text not null check (kind in ('action','decision','result','my_role')),
    text             text not null,
    owner            text not null check (owner in ('self','team','other','unknown')),
    provenance_type  text not null check (provenance_type in ('document','user_statement','derived')),
    evidence_status  text not null check (evidence_status in
                       ('unlinked','quote_matched','supported','contradicted','needs_review')),
    lifecycle        text not null default 'active'
                       check (lifecycle in ('active','superseded','retracted')),
    review_state     text not null default 'accepted'
                       check (review_state in ('proposed','accepted','rejected')),
    recorded_at      timestamptz not null default now(),
    superseded_at    timestamptz,
    sort_order       int not null default 0,
    unique (fact_id, version)
);
create index experience_facts_active_idx on skive.experience_facts (experience_id, lifecycle);

-- ── 사실 하나당 원본 근거 (quote 저장 필수) ────────────────────
create table skive.fact_evidence (
    id              uuid primary key default gen_random_uuid(),
    fact_row_id     uuid not null references skive.experience_facts(id) on delete cascade,
    chunk_id        uuid references skive.chunks(id) on delete set null,
    source_file     text not null,   -- 예: 최종보고서.md
    location        text not null,   -- 예: L1-31, p.1, slide 3
    quote           text,            -- 원문 그대로. 없으면 감사 불가 → needs_review
    quote_matched   boolean not null default false,
    supports_claim  text not null default 'unknown'
                      check (supports_claim in ('supported','unsupported','unknown')),
    owner_match     text not null default 'unknown'
                      check (owner_match in ('match','mismatch','unknown'))
);

-- ── 정정 이력 (지금 폴더별 corrections.json 대체) ──────────────
create table skive.corrections (
    id              uuid primary key default gen_random_uuid(),
    experience_id   uuid not null references skive.experiences(id) on delete cascade,
    field           text not null,
    original_text   text not null,
    corrected_text  text not null,
    reason          text,
    applied_at      timestamptz not null default now()
);

-- ── 업로드된 원본 파일 ─────────────────────────────────────
create table skive.files (
    id               uuid primary key default gen_random_uuid(),
    user_id          uuid not null references skive.users(id) on delete cascade,
    experience_id    uuid references skive.experiences(id) on delete set null,
    storage_path     text not null,   -- 로컬 경로 또는 S3/Object Storage 키
    original_filename text not null,
    file_type        text not null,
    uploaded_at      timestamptz not null default now()
);

-- ── 청크 + 임베딩 (ingest 시 한 번만 파싱해서 저장) ─────────────
-- 2026-09-22 실제로 구현하면서 아래 원래 설계에서 한 가지 바뀜: experiences/files 자체는
-- 아직 이 DB로 안 옮겼기 때문에(여전히 data/store/*.json이 원본), chunks.experience_id를
-- uuid FK가 아니라 지금 앱 전역이 실제로 쓰는 slug 텍스트(예: "3d_printer_raw")로 바로
-- 참조하게 만들었다. files 테이블도 이번 범위에선 안 씀. 실제 마이그레이션은
-- migrations/0002_chunks_by_slug.sql 참고 (0001의 아래 정의를 DROP하고 다시 만듦).
create table skive.chunks (
    id             uuid primary key default gen_random_uuid(),
    experience_id  text not null,    -- (변경됨) slug 문자열, uuid FK 아님 — 위 설명 참고
    source         text not null,
    location       text not null,
    text           text not null,
    embedding      vector(1536),     -- text-embedding-3-small 기준. 모델 바뀌면 차원도 같이 바뀜
    token_count    int,
    created_at     timestamptz not null default now()
);
create index chunks_embedding_idx on skive.chunks using hnsw (embedding vector_cosine_ops);
create index chunks_experience_idx on skive.chunks (experience_id);

-- ── 공부 세션 ────────────────────────────────────────────
create table skive.study_sessions (
    id                       uuid primary key default gen_random_uuid(),
    user_id                  uuid not null references skive.users(id) on delete cascade,
    topic                    text not null,
    session_date             date not null,
    keywords                 jsonb not null default '[]',
    learned                  jsonb not null default '[]',
    confusions               jsonb not null default '[]',
    review_questions         jsonb not null default '[]',
    related_experience_ids   jsonb not null default '[]',
    transcript               text,
    needs_review             boolean not null default false,
    created_at               timestamptz not null default now()
);

-- ── 종합 프로필 (사용자당 1개, 매번 재계산해서 덮어씀) ────────────
create table skive.profiles (
    user_id       uuid primary key references skive.users(id) on delete cascade,
    headline      text,
    competencies  jsonb not null default '[]',
    traits        jsonb not null default '[]',
    gaps          jsonb not null default '[]',
    generated_at  timestamptz not null default now()
);

-- ── 채용공고 ─────────────────────────────────────────────
create table skive.jobs (
    id                 uuid primary key default gen_random_uuid(),
    user_id            uuid not null references skive.users(id) on delete cascade,
    company            text not null,
    role               text not null,
    raw_text           text not null,
    responsibilities   jsonb not null default '[]',
    required_skills    jsonb not null default '[]',
    preferred_skills   jsonb not null default '[]',
    values             jsonb not null default '[]',
    key_competencies   jsonb not null default '[]',
    essay_questions    jsonb not null default '[]',
    created_at         timestamptz not null default now()
);

-- ── 공고 매칭 결과 / 자소서 ────────────────────────────────
create table skive.applications (
    id                    uuid primary key default gen_random_uuid(),
    job_id                uuid not null references skive.jobs(id) on delete cascade,
    competency_links      jsonb not null default '[]',
    question_plans        jsonb not null default '[]',
    questions_for_user    jsonb not null default '[]',
    trace                 jsonb not null default '[]',
    created_at            timestamptz not null default now()
);

create table skive.application_answers (
    id               uuid primary key default gen_random_uuid(),
    application_id   uuid not null references skive.applications(id) on delete cascade,
    question         text not null,
    experience_ids   jsonb not null default '[]',
    angle            text,
    gap              text,
    draft            text,
    status           text,
    attempts         int not null default 0,
    issues           jsonb not null default '[]',
    removed          jsonb not null default '[]'
);
```

## 4. 지금 플랫파일 → 이 테이블 매핑 (마이그레이션 스크립트가 할 일)

| 지금 파일 | 새 테이블 |
|---|---|
| `data/user.json` | `users` (1 row) |
| `data/store/<id>/metadata.json` | `experiences` |
| `data/store/<id>/facts.json`의 `actions`/`decisions`/`results` | `experience_facts` |
| 각 fact의 `sources` 리스트 | `fact_evidence` (여러 row) |
| `data/store/<id>/corrections.json` | `corrections` |
| `data/store/<id>/experience.md` | 저장 안 함 — DB의 구조화 데이터로부터 필요할 때 다시 렌더링 (지금처럼 파일로 들고 있을 필요 없어짐) |
| 원본 자료 (`samples/<id>/...`, 지금 `raw_dir`로만 참조) | `files` + `chunks` (ingest 시 파싱+임베딩해서 새로 생성) |
| `data/study/<id>/metadata.json` + `summary.md`/`transcript.txt` | `study_sessions` |
| `data/profile/profile.json` | `profiles` (1 row) |
| `data/outputs/apply_*.json`의 `job` | `jobs` |
| `data/outputs/apply_*.json`의 `plan`/`trace`/`questions_for_user` | `applications` |
| `data/outputs/apply_*.json`의 `answers[]` | `application_answers` |

## 5. 아직 결정 안 한 것 (다음에 확정 필요)

- 임베딩 모델·차원: 일단 OpenAI `text-embedding-3-small`(1536차원)으로 가정. 바꾸면 `chunks.embedding` 컬럼 차원도 같이 바뀌어야 함.
- `competencies`/`traits`를 `profiles.jsonb`에 뭉쳐둘지, 아니면 `experience_id` 참조가 가능한 별도 테이블로 정규화할지 — v1은 지금 코드(`Profile` pydantic 모델)와 1:1로 맞추려고 jsonb로 유지. "이 역량을 어떤 경험들이 뒷받침하는지"를 SQL로 직접 조회해야 하는 요구가 생기면 그때 정규화.
- `related_experiences`(경험 간 명시적 연결)는 v1에 없음. 필요해지면 `experience_links(from_id, to_id, relation, note)` 테이블 추가.
