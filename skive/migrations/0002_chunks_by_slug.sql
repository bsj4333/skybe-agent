-- 0001의 skive.chunks는 experience_id를 skive.experiences(uuid)에 FK로 걸어놨는데,
-- 실제로는 experiences/facts 자체는 아직 DB로 옮기지 않고 계속 data/store/*.json에 있다
-- (SCHEMA.md 참고 — 이번 마이그레이션은 "원본 파일 청크 + 임베딩"만 DB로 옮기는 범위로 좁혔음).
-- 그래서 chunks를 지금 앱 전역이 실제로 쓰는 식별자인 slug(예: "3d_printer_raw") 문자열로
-- 바로 참조하도록 다시 만든다. skive.files 테이블도 이번 범위에선 안 쓴다.
drop table if exists skive.chunks;

create table skive.chunks (
    id             uuid primary key default gen_random_uuid(),
    experience_id  text not null,   -- 슬러그. data/store/<experience_id>/ 폴더명과 동일
    source         text not null,   -- 예: 최종보고서.md, code/preprocess.py
    location       text not null,   -- 예: L1-31, p.3, slide 2
    text           text not null,
    embedding      vector(1536),    -- text-embedding-3-small
    token_count    int,
    created_at     timestamptz not null default now()
);
create index chunks_embedding_idx on skive.chunks using hnsw (embedding vector_cosine_ops);
create index chunks_experience_idx on skive.chunks (experience_id);
