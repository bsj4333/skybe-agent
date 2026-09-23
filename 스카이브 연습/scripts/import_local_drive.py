"""Import a local folder into one existing SKIVE account's private drive.

Run from the project directory with the server-side .env loaded. This is an
operator tool: it uses the DB owner connection and the server-only Storage key.
It never accepts an arbitrary user ID; the account must already exist in Auth.
Re-running reuses folders and matching file records and verifies Storage bytes.
"""

import argparse
import base64
import mimetypes
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urljoin
from uuid import uuid4

import httpx
from dotenv import load_dotenv

from skive.db import get_connection


EXCLUDE_DIRS = {".git", ".venv", "node_modules", "__pycache__"}
CHUNK_BYTES = 6 * 1024 * 1024


def source_files(root: Path, extensions: set[str] | None):
    files = []
    skipped = []
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        rel = path.relative_to(root)
        if any(part in EXCLUDE_DIRS for part in rel.parts[:-1]) or path.name.startswith(".env"):
            skipped.append(rel.as_posix())
            continue
        if extensions and path.suffix.lower() not in extensions:
            continue
        if any(len(part) > 255 or "/" in part or "\\" in part for part in rel.parts):
            skipped.append(rel.as_posix())
            continue
        files.append((path, rel, path.stat().st_size))
    return sorted(files, key=lambda item: item[1].as_posix()), skipped


def prepare(user_email: str, root: Path, files):
    """Create the visible folder tree first, then reuse/create file records."""
    with get_connection() as conn:
        user_rows = conn.execute("select id from auth.users where lower(email)=lower(%s)", (user_email,)).fetchall()
        if len(user_rows) != 1:
            raise RuntimeError("Exactly one existing Auth account must match --user-email")
        user_id = user_rows[0][0]
        existing_folders = {
            (row[1], row[2]): row[0]
            for row in conn.execute(
                "select id,parent_id,name from skive.drive_folders where user_id=%s and trashed_at is null",
                (user_id,),
            ).fetchall()
        }
        folder_ids = {}
        paths = {root.name}
        for _, rel, _ in files:
            for depth in range(1, len(rel.parts)):
                paths.add("/".join((root.name, *rel.parts[:depth])))
        for folder_path in sorted(paths, key=lambda p: (p.count("/"), p)):
            parent_path, _, name = folder_path.rpartition("/")
            parent_id = folder_ids[parent_path] if parent_path else None
            key = (parent_id, name)
            folder_id = existing_folders.get(key)
            if folder_id is None:
                folder_id = conn.execute(
                    "insert into skive.drive_folders(user_id,parent_id,name) values (%s,%s,%s) returning id",
                    (user_id, parent_id, name),
                ).fetchone()[0]
                existing_folders[key] = folder_id
            folder_ids[folder_path] = folder_id
        existing_files = {}
        for row in conn.execute(
            "select id,folder_id,name,size_bytes,storage_path,upload_status from skive.drive_files "
            "where user_id=%s and trashed_at is null order by created_at",
            (user_id,),
        ).fetchall():
            existing_files.setdefault((row[1], row[2], row[3]), row)
        tasks = []
        for path, rel, size in files:
            folder_path = "/".join((root.name, *rel.parts[:-1]))
            folder_id = folder_ids[folder_path]
            record = existing_files.get((folder_id, rel.name, size))
            if record is None:
                file_id = uuid4()
                storage_path = f"{user_id}/{file_id}/original"
                mime = mimetypes.guess_type(rel.name)[0] or "application/octet-stream"
                conn.execute(
                    "insert into skive.drive_files(id,user_id,folder_id,name,storage_path,mime_type,size_bytes) "
                    "values (%s,%s,%s,%s,%s,%s,%s)",
                    (file_id, user_id, folder_id, rel.name, storage_path, mime, size),
                )
                status = "pending"
            else:
                file_id, _, _, _, storage_path, status = record
            tasks.append((path, rel, size, file_id, storage_path, status))
    return user_id, tasks, len(paths)


def storage_object(path: str):
    with get_connection() as conn:
        row = conn.execute(
            "select metadata from storage.objects where bucket_id='skive-originals' and name=%s",
            (path,),
        ).fetchone()
    return row[0] if row else None


def mark_complete(user_id, file_id, storage_path, size):
    with get_connection() as conn:
        row = conn.execute(
            "select metadata from storage.objects where bucket_id='skive-originals' and name=%s",
            (storage_path,),
        ).fetchone()
        if not row or int(row[0].get("size", -1)) != size:
            raise RuntimeError("Storage object missing or byte size mismatch")
        conn.execute(
            "update skive.drive_files set upload_status='uploaded',analysis_status='queued',updated_at=now() "
            "where id=%s and user_id=%s and upload_status<>'uploaded'",
            (file_id, user_id),
        )
        conn.execute(
            "insert into skive.drive_jobs(user_id,file_id,file_version) "
            "select user_id,id,version from skive.drive_files where id=%s and user_id=%s "
            "on conflict (file_id,file_version) do nothing",
            (file_id, user_id),
        )


def upload_one(user_id, task, storage_base, secret):
    path, rel, size, file_id, storage_path, status = task
    metadata = storage_object(storage_path)
    if metadata is not None:
        if int(metadata.get("size", -1)) != size:
            raise RuntimeError(f"Existing object has wrong size: {rel}")
        if status != "uploaded":
            mark_complete(user_id, file_id, storage_path, size)
        return "reused"
    if status == "uploaded":
        raise RuntimeError(f"DB says uploaded but Storage object is absent: {rel}")
    headers = {"apikey": secret, "Authorization": f"Bearer {secret}", "Tus-Resumable": "1.0.0"}
    mime = mimetypes.guess_type(rel.name)[0] or "application/octet-stream"
    upload_metadata = ",".join(
        f"{key} {base64.b64encode(value.encode()).decode()}"
        for key, value in {
            "bucketName": "skive-originals", "objectName": storage_path,
            "contentType": mime, "cacheControl": "3600",
        }.items()
    )
    with httpx.Client(timeout=120) as client:
        response = client.post(
            f"{storage_base}/storage/v1/upload/resumable",
            headers={**headers, "Upload-Length": str(size), "Upload-Metadata": upload_metadata},
        )
        response.raise_for_status()
        upload_url = urljoin(storage_base, response.headers["Location"])
        with path.open("rb") as source:
            offset = 0
            while offset < size:
                source.seek(offset)
                data = source.read(CHUNK_BYTES)
                for attempt in range(4):
                    try:
                        response = client.patch(
                            upload_url,
                            headers={**headers, "Upload-Offset": str(offset),
                                     "Content-Type": "application/offset+octet-stream"},
                            content=data,
                        )
                        response.raise_for_status()
                        offset = int(response.headers.get("Upload-Offset", offset + len(data)))
                        break
                    except (httpx.RequestError, httpx.HTTPStatusError):
                        if attempt == 3:
                            raise
                        time.sleep(1 + attempt)
                        head = client.head(upload_url, headers=headers)
                        head.raise_for_status()
                        offset = int(head.headers["Upload-Offset"])
                        if offset >= source.tell():
                            break
        for _ in range(8):
            if storage_object(storage_path) is not None:
                break
            time.sleep(0.5)
        mark_complete(user_id, file_id, storage_path, size)
    return "uploaded"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--user-email", required=True)
    parser.add_argument("--extensions", help="Comma-separated suffixes, e.g. .md,.py,.xlsx")
    parser.add_argument("--max-bytes", type=int, default=1024**3)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    root = args.root.resolve(strict=True)
    if not root.is_dir():
        parser.error("root must be a directory")
    extensions = {part.strip().lower() for part in args.extensions.split(",")} if args.extensions else None
    files, skipped = source_files(root, extensions)
    total_bytes = sum(size for _, _, size in files)
    print(f"SOURCE files={len(files)} bytes={total_bytes} skipped={len(skipped)}", flush=True)
    if total_bytes > args.max_bytes:
        parser.error(f"source exceeds --max-bytes={args.max_bytes}; no DB or Storage changes made")
    if not files:
        parser.error("no files selected")
    user_id, tasks, folders = prepare(args.user_email, root, files)
    print(f"PREPARED folders={folders} files={len(tasks)} account={args.user_email}", flush=True)
    base = os.environ["SUPABASE_URL"].rstrip("/").replace(".supabase.co", ".storage.supabase.co")
    secret = os.environ["SUPABASE_SECRET_KEY"]
    completed = uploaded = reused = completed_bytes = 0
    failures = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(upload_one, user_id, task, base, secret): task for task in tasks}
        for future in as_completed(futures):
            task = futures[future]
            try:
                result = future.result()
                uploaded += result == "uploaded"
                reused += result == "reused"
            except Exception as exc:
                failures.append((task[1].as_posix(), str(exc)[:200]))
            completed += 1
            if future.exception() is None:
                completed_bytes += task[2]
            if completed % 25 == 0 or completed == len(tasks):
                percent = 100 * completed_bytes / total_bytes if total_bytes else 100
                print(f"PROGRESS {completed}/{len(tasks)} bytes={completed_bytes}/{total_bytes} "
                      f"({percent:.1f}%) uploaded={uploaded} reused={reused} failed={len(failures)}", flush=True)
    for path, error in failures[:20]:
        print(f"FAILED {path}: {error}", flush=True)
    if failures:
        raise SystemExit(f"Import finished with {len(failures)} failed files; rerun to retry")


if __name__ == "__main__":
    main()
