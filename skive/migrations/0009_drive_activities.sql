-- Folder-independent activity containers. Files can describe several activities.
-- This is an organizing layer, not a verified experience/fact store.
create table skive.drive_activities (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    title text not null check (char_length(title) between 1 and 200),
    kind_tags text[] not null default '{}',
    period_note text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (user_id, id),
    check (cardinality(kind_tags) <= 8),
    check (period_note is null or char_length(period_note) <= 120)
);

create table skive.drive_activity_files (
    user_id uuid not null,
    activity_id uuid not null,
    file_id uuid not null,
    linked_at timestamptz not null default now(),
    primary key (activity_id, file_id),
    constraint drive_activity_files_activity_owner_fk foreign key (user_id, activity_id)
        references skive.drive_activities(user_id, id) on delete cascade,
    constraint drive_activity_files_file_owner_fk foreign key (user_id, file_id)
        references skive.drive_files(user_id, id) on delete cascade
);
create index drive_activity_files_owner_file_idx
    on skive.drive_activity_files(user_id, file_id);

alter table skive.drive_activities enable row level security;
alter table skive.drive_activity_files enable row level security;
create policy drive_activities_owner on skive.drive_activities for all to authenticated
    using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));
create policy drive_activity_files_owner on skive.drive_activity_files for all to authenticated
    using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));
grant select, insert, update, delete on skive.drive_activities, skive.drive_activity_files to authenticated;
revoke all on skive.drive_activities, skive.drive_activity_files from anon;
