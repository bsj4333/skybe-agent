-- Google files stay in Google. SKIVE keeps metadata and extracted text, not the original bytes.
alter table skive.drive_files
    add column source text not null default 'upload' check (source in ('upload', 'google')),
    add column google_file_id text,
    add column google_modified_time text,
    add column google_export_mime text,
    add column google_web_url text;

alter table skive.drive_files add constraint drive_files_google_source_check
    check ((source = 'google') = (google_file_id is not null));

-- One live row per Drive file, so importing again updates it instead of duplicating it.
create unique index drive_files_google_file_idx on skive.drive_files(user_id, google_file_id)
    where source = 'google' and trashed_at is null;

-- Replaced by the columns above. It was never populated in production.
drop table skive.drive_google_files;
