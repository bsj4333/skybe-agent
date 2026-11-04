-- Extraction coverage is a versioned result, not a claim that the whole file was understood.
alter table skive.drive_files add column analysis_coverage jsonb;
