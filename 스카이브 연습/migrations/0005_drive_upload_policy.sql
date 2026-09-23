-- An authenticated user may upload only an object already registered by /files/init.
drop policy skive_originals_owner_upload on storage.objects;
create policy skive_originals_owner_upload on storage.objects for insert to authenticated
    with check (
        bucket_id = 'skive-originals'
        and (storage.foldername(name))[1] = (select auth.uid())::text
        and exists (
            select 1 from skive.drive_files f
            where f.storage_path = name
              and f.user_id = (select auth.uid())
              and f.upload_status = 'pending'
              and f.trashed_at is null
        )
    );
