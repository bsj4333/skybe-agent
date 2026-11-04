-- Persistent Google Drive connection and server-side import jobs.
create table skive.drive_google_connections (
    user_id uuid primary key references auth.users(id) on delete cascade,
    google_email text,
    refresh_token_encrypted text not null,
    needs_reconnect boolean not null default false,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);
alter table skive.drive_google_connections enable row level security;
create policy drive_google_connections_owner on skive.drive_google_connections for select to authenticated
    using (user_id = (select auth.uid()));
-- Column grant: signed-in users can see their status, never the token, even in their own row.
grant select (user_id, google_email, needs_reconnect, created_at, updated_at)
    on skive.drive_google_connections to authenticated;
revoke all on skive.drive_google_connections from anon;

create table skive.drive_google_imports (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    parent_id uuid references skive.drive_folders(id) on delete set null,
    selection jsonb not null,
    status text not null default 'queued' check (status in ('queued','processing','done','failed')),
    total int not null default 0,
    done int not null default 0,
    skipped int not null default 0,
    failed int not null default 0,
    error text,
    heartbeat_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);
create index drive_google_imports_queue_idx on skive.drive_google_imports(status, created_at);
create index drive_google_imports_owner_idx on skive.drive_google_imports(user_id, created_at desc);
alter table skive.drive_google_imports enable row level security;
create policy drive_google_imports_owner on skive.drive_google_imports for select to authenticated
    using (user_id = (select auth.uid()));
grant select on skive.drive_google_imports to authenticated;
revoke all on skive.drive_google_imports from anon;

-- Remembers what came from Google so importing the same folder again adds no duplicates.
create table skive.drive_google_files (
    user_id uuid not null,
    google_file_id text not null,
    modified_time text not null,
    file_id uuid not null,
    primary key (user_id, google_file_id),
    constraint drive_google_files_owner_fk foreign key (user_id, file_id)
        references skive.drive_files(user_id, id) on delete cascade
);
alter table skive.drive_google_files enable row level security;
revoke all on skive.drive_google_files from anon, authenticated;
