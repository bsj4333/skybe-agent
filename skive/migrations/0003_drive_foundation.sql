-- Additive drive foundation. Legacy data/store and skive.chunks remain untouched.
-- Auth users own every folder/file; object bytes live in a private Storage bucket.

create table skive.drive_folders (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    parent_id uuid,
    name text not null check (char_length(name) between 1 and 255),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    trashed_at timestamptz,
    unique (user_id, id),
    constraint drive_folders_parent_owner_fk foreign key (user_id, parent_id)
        references skive.drive_folders(user_id, id) on delete restrict,
    constraint drive_folders_name_path_check check (
        position('/' in name) = 0 and position(chr(92) in name) = 0
    )
);
create index drive_folders_children_idx on skive.drive_folders(user_id, parent_id)
    where trashed_at is null;

create table skive.drive_files (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    folder_id uuid,
    name text not null check (char_length(name) between 1 and 255),
    storage_path text not null unique,
    mime_type text not null default 'application/octet-stream',
    size_bytes bigint not null check (size_bytes >= 0),
    sha256 text,
    upload_status text not null default 'pending'
        check (upload_status in ('pending','uploaded','failed')),
    analysis_status text not null default 'waiting'
        check (analysis_status in ('waiting','queued','processing','ready','unsupported','failed')),
    analysis_error text,
    version int not null default 1 check (version >= 1),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    trashed_at timestamptz,
    unique (user_id, id),
    constraint drive_files_folder_owner_fk foreign key (user_id, folder_id)
        references skive.drive_folders(user_id, id) on delete restrict,
    constraint drive_files_name_path_check check (
        position('/' in name) = 0 and position(chr(92) in name) = 0
    ),
    constraint drive_files_storage_owner_check check (
        split_part(storage_path, '/', 1) = user_id::text
        and split_part(storage_path, '/', 2) = id::text
        and split_part(storage_path, '/', 3) = 'original'
    )
);
create index drive_files_children_idx on skive.drive_files(user_id, folder_id)
    where trashed_at is null;

create table skive.drive_jobs (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null,
    file_id uuid not null,
    file_version int not null,
    status text not null default 'queued'
        check (status in ('queued','processing','ready','unsupported','failed')),
    attempts int not null default 0,
    error text,
    created_at timestamptz not null default now(),
    started_at timestamptz,
    finished_at timestamptz,
    constraint drive_jobs_file_owner_fk foreign key (user_id, file_id)
        references skive.drive_files(user_id, id) on delete cascade,
    unique (file_id, file_version)
);
create index drive_jobs_queue_idx on skive.drive_jobs(status, created_at);

create table skive.drive_file_chunks (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null,
    file_id uuid not null,
    file_version int not null,
    chunk_index int not null,
    location text not null,
    text text not null,
    created_at timestamptz not null default now(),
    constraint drive_file_chunks_file_owner_fk foreign key (user_id, file_id)
        references skive.drive_files(user_id, id) on delete cascade,
    unique (file_id, file_version, chunk_index)
);
create index drive_file_chunks_owner_idx on skive.drive_file_chunks(user_id, file_id);

alter table skive.drive_folders enable row level security;
alter table skive.drive_files enable row level security;
alter table skive.drive_jobs enable row level security;
alter table skive.drive_file_chunks enable row level security;

create policy drive_folders_owner on skive.drive_folders for all to authenticated
    using (user_id = (select auth.uid()))
    with check (user_id = (select auth.uid()));
create policy drive_files_owner on skive.drive_files for all to authenticated
    using (user_id = (select auth.uid()))
    with check (user_id = (select auth.uid()));
create policy drive_jobs_owner on skive.drive_jobs for select to authenticated
    using (user_id = (select auth.uid()));
create policy drive_jobs_owner_enqueue on skive.drive_jobs for insert to authenticated
    with check (user_id = (select auth.uid()));
create policy drive_file_chunks_owner on skive.drive_file_chunks for select to authenticated
    using (user_id = (select auth.uid()));

grant usage on schema skive to authenticated;
grant select, insert, update, delete on skive.drive_folders, skive.drive_files to authenticated;
grant select, insert on skive.drive_jobs to authenticated;
grant select on skive.drive_file_chunks to authenticated;
revoke all on skive.drive_folders, skive.drive_files, skive.drive_jobs,
    skive.drive_file_chunks from anon;

insert into storage.buckets (id, name, public)
values ('skive-originals', 'skive-originals', false)
on conflict (id) do nothing;

create policy skive_originals_owner_read on storage.objects for select to authenticated
    using (
        bucket_id = 'skive-originals'
        and (storage.foldername(name))[1] = (select auth.uid())::text
    );
create policy skive_originals_owner_upload on storage.objects for insert to authenticated
    with check (
        bucket_id = 'skive-originals'
        and (storage.foldername(name))[1] = (select auth.uid())::text
    );
