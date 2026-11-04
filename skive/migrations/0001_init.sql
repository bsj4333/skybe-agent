-- SKIVE 초기 스키마. 상세 설명은 ../SCHEMA.md 참고.
-- 기존 Supabase 프로젝트를 재사용하므로 전부 skive 스키마 안에 넣는다.

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
    organization           text,
    problem                text,
    skills                 jsonb not null default '[]',
    my_role                text,
    my_role_verified       boolean not null default false,
    my_role_corrected_from text,
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

-- ── 경험 안의 개별 사실 (actions/decisions/results) ──────────
create table skive.experience_facts (
    id                 uuid primary key default gen_random_uuid(),
    experience_id      uuid not null references skive.experiences(id) on delete cascade,
    kind               text not null check (kind in ('action','decision','result')),
    text               text not null,
    owner              text not null check (owner in ('본인','팀')),
    verified           boolean not null default false,
    corrected_from     text,
    corrected_at       timestamptz,
    correction_reason  text,
    sort_order         int not null default 0
);

-- ── 사실 하나당 원본 근거 (여러 개 가능) ───────────────────────
create table skive.fact_evidence (
    id           uuid primary key default gen_random_uuid(),
    fact_id      uuid not null references skive.experience_facts(id) on delete cascade,
    source_file  text not null,
    location     text not null,
    quote        text,
    verified     boolean not null default false
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
    id                 uuid primary key default gen_random_uuid(),
    user_id            uuid not null references skive.users(id) on delete cascade,
    experience_id      uuid references skive.experiences(id) on delete set null,
    storage_path       text not null,
    original_filename  text not null,
    file_type          text not null,
    uploaded_at        timestamptz not null default now()
);

-- ── 청크 + 임베딩 (ingest 시 한 번만 파싱해서 저장) ─────────────
create table skive.chunks (
    id             uuid primary key default gen_random_uuid(),
    file_id        uuid not null references skive.files(id) on delete cascade,
    experience_id  uuid not null references skive.experiences(id) on delete cascade,
    source         text not null,
    location       text not null,
    text           text not null,
    embedding      vector(1536),
    token_count    int,
    created_at     timestamptz not null default now()
);
create index chunks_embedding_idx on skive.chunks using hnsw (embedding vector_cosine_ops);
create index chunks_experience_idx on skive.chunks (experience_id);

-- ── 공부 세션 ────────────────────────────────────────────
create table skive.study_sessions (
    id                      uuid primary key default gen_random_uuid(),
    user_id                 uuid not null references skive.users(id) on delete cascade,
    topic                   text not null,
    session_date            date not null,
    keywords                jsonb not null default '[]',
    learned                 jsonb not null default '[]',
    confusions              jsonb not null default '[]',
    review_questions        jsonb not null default '[]',
    related_experience_ids  jsonb not null default '[]',
    transcript              text,
    needs_review            boolean not null default false,
    created_at              timestamptz not null default now()
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
    id                uuid primary key default gen_random_uuid(),
    user_id           uuid not null references skive.users(id) on delete cascade,
    company           text not null,
    role              text not null,
    raw_text          text not null,
    responsibilities  jsonb not null default '[]',
    required_skills   jsonb not null default '[]',
    preferred_skills  jsonb not null default '[]',
    values            jsonb not null default '[]',
    key_competencies  jsonb not null default '[]',
    essay_questions   jsonb not null default '[]',
    created_at        timestamptz not null default now()
);

-- ── 공고 매칭 결과 / 자소서 ────────────────────────────────
create table skive.applications (
    id                  uuid primary key default gen_random_uuid(),
    job_id              uuid not null references skive.jobs(id) on delete cascade,
    competency_links    jsonb not null default '[]',
    question_plans      jsonb not null default '[]',
    questions_for_user  jsonb not null default '[]',
    trace               jsonb not null default '[]',
    created_at          timestamptz not null default now()
);

create table skive.application_answers (
    id              uuid primary key default gen_random_uuid(),
    application_id  uuid not null references skive.applications(id) on delete cascade,
    question        text not null,
    experience_ids  jsonb not null default '[]',
    angle           text,
    gap             text,
    draft           text,
    status          text,
    attempts        int not null default 0,
    issues          jsonb not null default '[]',
    removed         jsonb not null default '[]'
);
