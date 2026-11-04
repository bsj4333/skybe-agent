-- Owner-scoped, versioned folder experience drafts. File extraction remains separate.
create table skive.drive_folder_summaries (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null,
    folder_id uuid not null unique,
    status text not null default 'queued'
        check (status in ('queued','processing','ready','failed')),
    source_signature text,
    markdown text,
    facts jsonb not null default '[]'::jsonb,
    files_considered integer not null default 0,
    files_selected integer not null default 0,
    error text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint drive_summary_folder_owner_fk foreign key (user_id, folder_id)
        references skive.drive_folders(user_id, id) on delete cascade
);
create index drive_folder_summaries_queue_idx
    on skive.drive_folder_summaries(status, updated_at);
alter table skive.drive_folder_summaries enable row level security;
create policy drive_folder_summaries_owner on skive.drive_folder_summaries
    for select to authenticated using (user_id = (select auth.uid()));
grant select on skive.drive_folder_summaries to authenticated;
revoke all on skive.drive_folder_summaries from anon;
