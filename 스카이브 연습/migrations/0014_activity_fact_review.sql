-- Activity-level evidence proposals and human review. Document evidence is
-- never promoted to a confirmed personal contribution by model output alone.
create table skive.drive_activity_analysis_jobs (
    user_id uuid not null,
    activity_id uuid primary key,
    status text not null check (status in ('queued','processing','ready','failed')),
    source_signature text,
    files_total int not null default 0,
    files_analyzed int not null default 0,
    error text,
    requested_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint activity_analysis_owner_fk foreign key (user_id, activity_id)
        references skive.drive_activities(user_id, id) on delete cascade
);

create table skive.drive_activity_facts (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null,
    activity_id uuid not null,
    kind text not null check (kind in ('context','goal','action','result','skill','lesson','other')),
    content text not null check (char_length(content) between 1 and 2000),
    subject text not null check (subject in ('project','team','user','unclear')),
    review_state text not null default 'candidate'
        check (review_state in ('candidate','confirmed','rejected')),
    source_file_id uuid not null,
    source_file_version int not null,
    source_analyzed_at timestamptz,
    source_chunk_index int not null,
    source_location text not null,
    source_quote text not null,
    evidence_check jsonb not null default '{}'::jsonb,
    review_note text not null default '',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    reviewed_at timestamptz,
    constraint activity_fact_activity_owner_fk foreign key (user_id, activity_id)
        references skive.drive_activities(user_id, id) on delete cascade,
    constraint activity_fact_file_owner_fk foreign key (user_id, source_file_id)
        references skive.drive_files(user_id, id) on delete cascade
);
create index drive_activity_facts_activity_idx on skive.drive_activity_facts(activity_id,review_state,created_at);
create index drive_activity_facts_file_idx on skive.drive_activity_facts(source_file_id,source_file_version);

alter table skive.drive_activity_analysis_jobs enable row level security;
alter table skive.drive_activity_facts enable row level security;
create policy activity_analysis_owner on skive.drive_activity_analysis_jobs for all to authenticated
    using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));
create policy activity_facts_owner on skive.drive_activity_facts for all to authenticated
    using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));
grant select, insert, update, delete on skive.drive_activity_analysis_jobs,
    skive.drive_activity_facts to authenticated;
revoke all on skive.drive_activity_analysis_jobs, skive.drive_activity_facts from anon;
