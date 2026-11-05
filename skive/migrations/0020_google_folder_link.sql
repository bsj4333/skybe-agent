-- A person can point an experience at a Drive folder. The import job remembers which experience
-- receives the files, so the worker links them once they are registered.
alter table skive.drive_google_imports
    add column activity_id uuid references skive.drive_activities(id) on delete set null,
    add column linked int not null default 0;

create index drive_google_imports_activity_idx on skive.drive_google_imports(activity_id)
    where activity_id is not null;
