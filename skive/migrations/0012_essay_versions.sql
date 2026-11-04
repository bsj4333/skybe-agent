-- Preserve each generated draft. A later correction can mark old versions stale.
alter table skive.drive_essays add constraint drive_essays_owner_id_unique unique (user_id, id);
create table skive.drive_essay_versions (
    id bigint generated always as identity primary key,
    user_id uuid not null,
    essay_id uuid not null,
    revision_no int not null,
    draft text not null,
    citations jsonb not null default '[]'::jsonb,
    created_at timestamptz not null default now(),
    unique (essay_id, revision_no),
    constraint drive_essay_version_owner_fk foreign key (user_id, essay_id)
        references skive.drive_essays(user_id, id) on delete cascade
);
create index drive_essay_versions_owner_idx on skive.drive_essay_versions(user_id, essay_id, revision_no desc);
alter table skive.drive_essay_versions enable row level security;
create policy drive_essay_versions_owner on skive.drive_essay_versions for all to authenticated
    using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));
grant select, insert, update, delete on skive.drive_essay_versions to authenticated;
grant usage, select on sequence skive.drive_essay_versions_id_seq to authenticated;
revoke all on skive.drive_essay_versions from anon;
