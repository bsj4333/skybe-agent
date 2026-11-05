-- Experience map: file cards, experiences on top of activities, profile entries, narrative.

create table skive.drive_file_cards (
    file_id uuid primary key,
    user_id uuid not null,
    file_version int not null,
    doc_type text not null default 'other',
    owner text not null default 'unknown'
        check (owner in ('self', 'team', 'other_person', 'reference', 'unknown')),
    owner_source text not null default 'model' check (owner_source in ('model', 'rule', 'user')),
    owner_reason text not null default '',
    summary text not null default '',
    keywords text[] not null default '{}',
    period_text text not null default '',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint drive_file_cards_owner_fk foreign key (user_id, file_id)
        references skive.drive_files(user_id, id) on delete cascade
);
create index drive_file_cards_user_owner_idx on skive.drive_file_cards(user_id, owner);
alter table skive.drive_file_cards enable row level security;
create policy drive_file_cards_owner on skive.drive_file_cards for all to authenticated
    using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));
grant select, insert, update, delete on skive.drive_file_cards to authenticated;
revoke all on skive.drive_file_cards from anon;

-- An experience is an activity with a place on the map. Facts and summaries keep working unchanged.
alter table skive.drive_activities
    add column status text not null default 'confirmed'
        check (status in ('candidate', 'confirmed', 'excluded')),
    add column origin text not null default 'user' check (origin in ('user', 'auto')),
    add column category text not null default '프로젝트',
    add column subcategory text not null default '',
    add column why text not null default '';
create index drive_activities_user_status_idx on skive.drive_activities(user_id, status);

create table skive.drive_experience_jobs (
    user_id uuid primary key references auth.users(id) on delete cascade,
    status text not null default 'queued' check (status in ('queued', 'processing', 'ready', 'failed')),
    stage text not null default '',
    cards_total int not null default 0,
    cards_done int not null default 0,
    experiences int not null default 0,
    error text,
    heartbeat_at timestamptz,
    updated_at timestamptz not null default now()
);
create index drive_experience_jobs_queue_idx on skive.drive_experience_jobs(status, updated_at);
alter table skive.drive_experience_jobs enable row level security;
create policy drive_experience_jobs_owner on skive.drive_experience_jobs for select to authenticated
    using (user_id = (select auth.uid()));
grant select on skive.drive_experience_jobs to authenticated;
revoke all on skive.drive_experience_jobs from anon;

create table skive.drive_profile_entries (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    kind text not null check (kind in ('education', 'work', 'military', 'license', 'language', 'award', 'overseas')),
    title text not null check (char_length(title) between 1 and 200),
    organization text not null default '',
    start_date text not null default '',
    end_date text not null default '',
    detail text not null default '',
    status text not null default 'candidate' check (status in ('candidate', 'confirmed')),
    source_file_id uuid references skive.drive_files(id) on delete set null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);
create index drive_profile_entries_user_idx on skive.drive_profile_entries(user_id, status);
alter table skive.drive_profile_entries enable row level security;
create policy drive_profile_entries_owner on skive.drive_profile_entries for all to authenticated
    using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));
grant select, insert, update, delete on skive.drive_profile_entries to authenticated;
revoke all on skive.drive_profile_entries from anon;

create table skive.drive_narratives (
    user_id uuid primary key references auth.users(id) on delete cascade,
    content jsonb not null default '{}'::jsonb,
    source_signature text not null default '',
    updated_at timestamptz not null default now()
);
alter table skive.drive_narratives enable row level security;
create policy drive_narratives_owner on skive.drive_narratives for all to authenticated
    using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));
grant select, insert, update, delete on skive.drive_narratives to authenticated;
revoke all on skive.drive_narratives from anon;

alter table skive.drive_essays add column sentence_checks jsonb not null default '[]'::jsonb;
alter table skive.drive_essay_versions add column sentence_checks jsonb not null default '[]'::jsonb;
