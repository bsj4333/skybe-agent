-- One generated, evidence-bounded project document per user-selected project root.
-- Stage notes remain inside structured_summary; they are not separate Drive files.
create table skive.drive_project_summaries (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null,
    root_folder_id uuid not null unique,
    status text not null default 'queued'
        check (status in ('queued','processing','ready','failed')),
    source_signature text,
    markdown text,
    structured_summary jsonb not null default '{}'::jsonb,
    source_index jsonb not null default '[]'::jsonb,
    coverage jsonb not null default '{}'::jsonb,
    agent_trace jsonb not null default '{}'::jsonb,
    model text,
    prompt_version text,
    error text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint drive_project_summary_folder_owner_fk
        foreign key (user_id, root_folder_id)
        references skive.drive_folders(user_id, id) on delete cascade
);

create index drive_project_summaries_queue_idx
    on skive.drive_project_summaries(status, updated_at);
create index drive_project_summaries_owner_idx
    on skive.drive_project_summaries(user_id, root_folder_id);

alter table skive.drive_project_summaries enable row level security;
create policy drive_project_summaries_owner on skive.drive_project_summaries
    for select to authenticated using (user_id = (select auth.uid()));
grant select on skive.drive_project_summaries to authenticated;
revoke all on skive.drive_project_summaries from anon;
