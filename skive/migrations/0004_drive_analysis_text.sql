-- Derived text is versioned with the original file. Never replace source bytes.
alter table skive.drive_files add column analysis_markdown text;
alter table skive.drive_files add column analyzed_at timestamptz;
