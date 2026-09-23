"""Durable drive extraction worker: ``uv run python -m skive.drive_worker``.

Run as a separate process. Its server-only Supabase secret key downloads source
bytes; users never see that key. Source text stays linked to file/version/location.
"""

import os
import shutil
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote
from zipfile import ZipFile

import httpx
from dotenv import load_dotenv
from psycopg.rows import dict_row

from skive.db import get_connection
from skive.loaders import DRIVE_TEXT_EXT, load_drive_file

load_dotenv(Path(__file__).resolve().parents[2] / ".env")
MAX_ANALYSIS_BYTES = 50 * 1024 * 1024
MAX_XLSX_FULL_BYTES = 5 * 1024 * 1024
MAX_ANALYSIS_CHUNKS = 10_000
SUPPORTED_EXT = DRIVE_TEXT_EXT | {".csv", ".pdf", ".pptx", ".xlsx", ".docx"}


class UnsupportedFile(Exception):
    pass


@contextmanager
def extraction_workspace():
    path = Path(tempfile.mkdtemp(prefix="skive-drive-"))
    try:
        yield path
    finally:
        # Windows may keep openpyxl's ZIP handle briefly after Workbook.close().
        # A cleanup race must not turn a successful extraction into a failed job.
        for attempt in range(8):
            try:
                shutil.rmtree(path)
                break
            except FileNotFoundError:
                break
            except PermissionError:
                if attempt == 7:
                    print(f"Could not remove temporary extraction directory: {path}", flush=True)
                else:
                    time.sleep(0.5)


def claim_job(file_id=None):
    with get_connection() as conn:
        conn.row_factory = dict_row
        file_filter = "and j.file_id=%s " if file_id is not None else ""
        job = conn.execute(
            "select j.id,j.user_id,j.file_id,j.file_version,f.name,f.storage_path,f.size_bytes "
            "from skive.drive_jobs j join skive.drive_files f on f.id=j.file_id "
            "where (j.status='queued' or (j.status='processing' and j.started_at < now()-interval '1 hour')) "
            "and f.upload_status='uploaded' and f.trashed_at is null "
            + file_filter + "order by j.created_at for update of j skip locked limit 1",
            (file_id,) if file_id is not None else (),
        ).fetchone()
        if job:
            conn.execute(
                "update skive.drive_jobs set status='processing',attempts=attempts+1,started_at=now(),error=null "
                "where id=%s", (job["id"],)
            )
            conn.execute(
                "update skive.drive_files set analysis_status='processing',analysis_error=null "
                "where id=%s", (job["file_id"],)
            )
        return job


def extract(job: dict, base_url: str, secret_key: str):
    if Path(job["name"]).suffix.lower() not in SUPPORTED_EXT:
        raise UnsupportedFile("This file type has no text extractor yet")
    if job["size_bytes"] > MAX_ANALYSIS_BYTES:
        raise UnsupportedFile("File exceeds the current 50 MB extraction limit")
    if Path(job["name"]).suffix.lower() == ".xlsx" and job["size_bytes"] > MAX_XLSX_FULL_BYTES:
        raise UnsupportedFile("Spreadsheet exceeds the current 5 MB full-cell extraction limit; original retained")
    url = (base_url.rstrip("/") + "/storage/v1/object/authenticated/skive-originals/"
           + quote(job["storage_path"], safe="/"))
    with extraction_workspace() as temp:
        path = temp / ("original" + Path(job["name"]).suffix.lower())
        size = 0
        with httpx.stream("GET", url, headers={"apikey": secret_key,
                                               "Authorization": f"Bearer {secret_key}"}, timeout=60) as response:
            response.raise_for_status()
            with path.open("wb") as output:
                for part in response.iter_bytes():
                    size += len(part)
                    if size > MAX_ANALYSIS_BYTES:
                        raise UnsupportedFile("File exceeds the current 50 MB extraction limit")
                    output.write(part)
        if size != job["size_bytes"]:
            raise RuntimeError("Downloaded object size differs from file record")
        if path.suffix in {".pptx", ".xlsx", ".docx"}:
            with ZipFile(path) as archive:
                if sum(member.file_size for member in archive.infolist()) > 200 * 1024 * 1024:
                    raise UnsupportedFile("Office document expands beyond the 200 MB extraction limit")
        chunks = load_drive_file(path, job["name"])
        if len(chunks) > MAX_ANALYSIS_CHUNKS:
            raise UnsupportedFile("File produces too many text chunks")
        if not chunks:
            raise UnsupportedFile("No extractable text found (scanned PDF may need OCR)")
        return chunks


def finish_job(job: dict, chunks=None, error: str | None = None, unsupported: bool = False):
    status = "unsupported" if unsupported else "failed" if error else "ready"
    with get_connection() as conn:
        if chunks is not None:
            conn.execute(
                "delete from skive.drive_file_chunks where file_id=%s and file_version=%s",
                (job["file_id"], job["file_version"]),
            )
            with conn.cursor() as cursor:
                cursor.executemany(
                    "insert into skive.drive_file_chunks "
                    "(user_id,file_id,file_version,chunk_index,location,text) values (%s,%s,%s,%s,%s,%s) "
                    "on conflict (file_id,file_version,chunk_index) do update "
                    "set location=excluded.location,text=excluded.text",
                    [(job["user_id"], job["file_id"], job["file_version"], i,
                      chunk.location, chunk.text) for i, chunk in enumerate(chunks, 1)],
                )
            # This is an extraction manifest, not an AI-written factual summary.
            md = (f"# {job['name']}\n\n"
                  f"원본 파일에서 텍스트 {len(chunks)}개 구간을 추출했습니다. "
                  "아래는 위치 색인입니다. 사실 요약과 본인 기여도 검증은 후속 분석 대상입니다.\n\n"
                  + "\n".join(f"- C{i}: {chunk.location}" for i, chunk in enumerate(chunks, 1)))
            conn.execute(
                "update skive.drive_files set analysis_status='ready',analysis_error=null,"
                "analysis_markdown=%s,analyzed_at=now(),updated_at=now() "
                "where id=%s and version=%s", (md, job["file_id"], job["file_version"]),
            )
        else:
            conn.execute(
                "update skive.drive_files set analysis_status=%s,analysis_error=%s,updated_at=now() "
                "where id=%s and version=%s", (status, (error or "")[:500], job["file_id"], job["file_version"]),
            )
        conn.execute(
            "update skive.drive_jobs set status=%s,error=%s,finished_at=now() where id=%s",
            (status, (error or "")[:500], job["id"]),
        )


def run_once(base_url: str, secret_key: str, file_id=None) -> bool:
    job = claim_job(file_id)
    if not job:
        return False
    try:
        chunks = extract(job, base_url, secret_key)
        finish_job(job, chunks=chunks)
    except UnsupportedFile as exc:
        finish_job(job, error=str(exc), unsupported=True)
    except Exception as exc:
        finish_job(job, error=str(exc))
    return True


def main():
    base_url = os.getenv("SUPABASE_URL", "")
    secret_key = os.getenv("SUPABASE_SECRET_KEY", "") or os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    if not base_url.startswith("https://") or not secret_key:
        raise SystemExit("Worker needs SUPABASE_URL and server-only SUPABASE_SECRET_KEY in .env")
    while True:
        if not run_once(base_url, secret_key):
            from skive.drive_summary import run_summary_once

            if not run_summary_once():
                time.sleep(5)


if __name__ == "__main__":
    main()
