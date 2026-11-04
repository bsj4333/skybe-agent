-- Reproducible, owner-scoped activity Markdown versions. Staleness is checked
-- against the current linked files and reviewed facts at read time.
create table skive.drive_activity_markdown_snapshots (
    id bigint generated always as identity primary key,
    user_id uuid not null,
    activity_id uuid not null,
    source_signature text not null,
    facts_signature text not null,
    markdown text not null,
    created_at timestamptz not null default now(),
    constraint activity_markdown_owner_fk foreign key (user_id, activity_id)
        references skive.drive_activities(user_id, id) on delete cascade
);
create index activity_markdown_latest_idx on skive.drive_activity_markdown_snapshots(activity_id,id desc);
alter table skive.drive_activity_markdown_snapshots enable row level security;
create policy activity_markdown_owner on skive.drive_activity_markdown_snapshots for all to authenticated
    using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()));
grant select, insert on skive.drive_activity_markdown_snapshots to authenticated;
grant usage, select on sequence skive.drive_activity_markdown_snapshots_id_seq to authenticated;
revoke all on skive.drive_activity_markdown_snapshots from anon;
