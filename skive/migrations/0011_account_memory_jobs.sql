-- Shared, account-scoped career memory and independent job workspaces.
-- A user statement is never silently promoted to document evidence.
create table skive.drive_memory_claims (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    activity_id uuid,
    content text not null check (char_length(content) between 1 and 4000),
    provenance text not null check (provenance in ('user_statement', 'document_candidate')),
    status text not null check (status in ('user_confirmed', 'needs_confirmation')),
    source_file_id uuid,
    source_location text,
    source_quote text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (user_id, id),
    constraint drive_memory_activity_owner_fk foreign key (user_id, activity_id)
        references skive.drive_activities(user_id, id) on delete set null (activity_id),
    constraint drive_memory_file_owner_fk foreign key (user_id, source_file_id)
        references skive.drive_files(user_id, id) on delete set null (source_file_id),
    check ((provenance = 'user_statement' and source_file_id is null and status = 'user_confirmed')
        or (provenance = 'document_candidate' and source_file_id is not null
            and status = 'needs_confirmation'))
);
create index drive_memory_claims_owner_idx on skive.drive_memory_claims(user_id, updated_at desc);

create table skive.drive_job_workspaces (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    title text not null check (char_length(title) between 1 and 200),
    job_text text not null default '',
    job_url text not null default '',
    values_url text not null default '',
    pending_question text not null default '',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (user_id, id)
);
create index drive_job_workspaces_owner_idx on skive.drive_job_workspaces(user_id, updated_at desc);

alter table skive.drive_essays add column job_workspace_id uuid;
alter table skive.drive_essays add constraint drive_essay_workspace_owner_fk
    foreign key (user_id, job_workspace_id)
    references skive.drive_job_workspaces(user_id, id) on delete cascade;
create index drive_essays_workspace_idx on skive.drive_essays(job_workspace_id, created_at);

create table skive.drive_job_messages (
    id bigint generated always as identity primary key,
    user_id uuid not null,
    job_workspace_id uuid not null,
    role text not null check (role in ('user', 'assistant')),
    content text not null check (char_length(content) between 1 and 20000),
    references_json jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    constraint drive_job_message_owner_fk foreign key (user_id, job_workspace_id)
        references skive.drive_job_workspaces(user_id, id) on delete cascade
);
create index drive_job_messages_workspace_idx on skive.drive_job_messages(job_workspace_id, id);

alter table skive.drive_memory_claims enable row level security;
alter table skive.drive_job_workspaces enable row level security;
alter table skive.drive_job_messages enable row level security;
create policy drive_memory_claims_owner on skive.drive_memory_claims for all to authenticated
    using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));
create policy drive_job_workspaces_owner on skive.drive_job_workspaces for all to authenticated
    using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));
create policy drive_job_messages_owner on skive.drive_job_messages for all to authenticated
    using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));
grant select, insert, update, delete on skive.drive_memory_claims,
    skive.drive_job_workspaces, skive.drive_job_messages to authenticated;
grant usage, select on sequence skive.drive_job_messages_id_seq to authenticated;
revoke all on skive.drive_memory_claims, skive.drive_job_workspaces,
    skive.drive_job_messages from anon;
