"""Private drive metadata API. File bytes go directly to Supabase Storage."""

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from psycopg.rows import dict_row

from skive.drive_auth import current_user_id, public_config
from skive.drive_db import user_connection
from skive.drive_summary import folder_files, signature
from skive.db import get_connection

router = APIRouter(prefix="/api/drive", tags=["drive"])


def valid_name(value: str) -> str:
    value = value.strip()
    if not value or len(value) > 255 or "/" in value or "\\" in value or value in {".", ".."}:
        raise ValueError("Invalid drive name")
    return value


class FolderCreate(BaseModel):
    name: str
    parent_id: UUID | None = None

    _valid_name = field_validator("name")(valid_name)


class FileInit(FolderCreate):
    size_bytes: int = Field(ge=0, le=50 * 1024**3)
    mime_type: str = "application/octet-stream"


class Rename(BaseModel):
    name: str

    _valid_name = field_validator("name")(valid_name)


class Move(BaseModel):
    parent_id: UUID | None = None


class FolderImportTree(BaseModel):
    parent_id: UUID | None = None
    paths: list[str] = Field(min_length=1, max_length=5000)


def require_folder(conn, folder_id: UUID | None):
    if folder_id is not None and not conn.execute(
        "select 1 from skive.drive_folders where id=%s and trashed_at is null", (folder_id,)
    ).fetchone():
        raise HTTPException(404, "Folder not found")


def row_or_404(row, kind: str):
    if row is None:
        raise HTTPException(404, f"{kind} not found")
    return row


@router.get("/config")
def config():
    return public_config()


@router.get("/items")
def list_items(parent_id: UUID | None = None, user_id: UUID = Depends(current_user_id)):
    with user_connection(user_id) as conn:
        require_folder(conn, parent_id)
        folders = conn.execute(
            "select id, parent_id, name, created_at, updated_at from skive.drive_folders "
            "where parent_id is not distinct from %s and trashed_at is null order by lower(name), id",
            (parent_id,),
        ).fetchall()
        files = conn.execute(
            "select id, folder_id, name, storage_path, mime_type, size_bytes, upload_status, analysis_status, "
            "analysis_error, created_at, updated_at from skive.drive_files "
            "where folder_id is not distinct from %s and trashed_at is null order by lower(name), id",
            (parent_id,),
        ).fetchall()
    return {"folders": folders, "files": files}


@router.get("/summary")
def drive_summary(user_id: UUID = Depends(current_user_id)):
    """Account-wide committed Storage progress for imports from any client."""
    with user_connection(user_id) as conn:
        return conn.execute(
            "select count(*)::int as total_files, "
            "count(*) filter (where upload_status='uploaded')::int as uploaded_files, "
            "coalesce(sum(size_bytes),0)::bigint as total_bytes, "
            "coalesce(sum(size_bytes) filter (where upload_status='uploaded'),0)::bigint as uploaded_bytes, "
            "count(*) filter (where analysis_status='ready')::int as analyzed_files, "
            "count(*) filter (where analysis_status in ('failed','unsupported'))::int as analysis_issues "
            "from skive.drive_files where trashed_at is null"
        ).fetchone()


@router.post("/folders", status_code=201)
def create_folder(body: FolderCreate, user_id: UUID = Depends(current_user_id)):
    with user_connection(user_id) as conn:
        require_folder(conn, body.parent_id)
        return conn.execute(
            "insert into skive.drive_folders (user_id, parent_id, name) values (%s,%s,%s) "
            "returning id, parent_id, name, created_at",
            (user_id, body.parent_id, body.name),
        ).fetchone()


@router.post("/folders/import-tree")
def import_folder_tree(body: FolderImportTree, user_id: UUID = Depends(current_user_id)):
    """Create/reuse an uploaded directory tree in one DB transaction."""
    paths: set[str] = set()
    for path in body.paths:
        parts = path.split("/")
        try:
            valid_parts = [valid_name(part) for part in parts]
        except ValueError as exc:
            raise HTTPException(422, "Invalid relative folder path") from exc
        if not parts or valid_parts != parts:
            raise HTTPException(422, "Invalid relative folder path")
        for depth in range(1, len(parts) + 1):
            paths.add("/".join(parts[:depth]))
    if len(paths) > 5000:
        raise HTTPException(413, "Too many folders in one upload")
    mapping: dict[str, UUID] = {}
    with user_connection(user_id) as conn:
        require_folder(conn, body.parent_id)
        for path in sorted(paths, key=lambda value: (value.count("/"), value)):
            parent_path, _, name = path.rpartition("/")
            parent_id = mapping[parent_path] if parent_path else body.parent_id
            existing = conn.execute(
                "select id from skive.drive_folders where parent_id is not distinct from %s "
                "and name=%s and trashed_at is null order by created_at,id limit 1",
                (parent_id, name),
            ).fetchone()
            folder_id = existing["id"] if existing else conn.execute(
                "insert into skive.drive_folders (user_id,parent_id,name) values (%s,%s,%s) returning id",
                (user_id, parent_id, name),
            ).fetchone()["id"]
            mapping[path] = folder_id
    return {"folders": mapping}


@router.get("/folders/{folder_id}/breadcrumbs")
def folder_breadcrumbs(folder_id: UUID, user_id: UUID = Depends(current_user_id)):
    with user_connection(user_id) as conn:
        require_folder(conn, folder_id)
        return conn.execute(
            "with recursive path as ("
            "select id,parent_id,name,0 as depth from skive.drive_folders where id=%s "
            "union all select f.id,f.parent_id,f.name,p.depth+1 from skive.drive_folders f "
            "join path p on p.parent_id=f.id where f.trashed_at is null) "
            "select id,name from path order by depth desc", (folder_id,),
        ).fetchall()


@router.get("/folders/{folder_id}/summary")
def folder_summary(folder_id: UUID, user_id: UUID = Depends(current_user_id)):
    with user_connection(user_id) as conn:
        require_folder(conn, folder_id)
        row = conn.execute(
            "select status,source_signature,markdown,facts,files_considered,files_selected,error,updated_at "
            "from skive.drive_folder_summaries where folder_id=%s", (folder_id,),
        ).fetchone()
        if not row:
            return {"status": "missing"}
        return {**row, "stale": row["status"] == "ready" and
                row["source_signature"] != signature(folder_files(conn, user_id, folder_id))}


@router.post("/folders/{folder_id}/summary")
def request_folder_summary(folder_id: UUID, user_id: UUID = Depends(current_user_id)):
    # Authentication is checked first; the privileged insert below is restricted
    # to a folder whose owner matches the token, never a caller-supplied user id.
    with user_connection(user_id) as conn:
        require_folder(conn, folder_id)
        files = folder_files(conn, user_id, folder_id)
        if not files:
            raise HTTPException(409, "이 폴더에는 요약할 파일이 없습니다")
        current_signature = signature(files)
    with get_connection() as conn:
        conn.row_factory = dict_row
        row = conn.execute(
            "insert into skive.drive_folder_summaries (user_id,folder_id,status) "
            "select user_id,id,'queued' from skive.drive_folders "
            "where id=%s and user_id=%s and trashed_at is null "
            "on conflict (folder_id) do update set "
            "status=case when skive.drive_folder_summaries.status='ready' "
            "and skive.drive_folder_summaries.source_signature=%s then 'ready' else 'queued' end, "
            "error=null,updated_at=now() "
            "returning status,folder_id,updated_at", (folder_id, user_id, current_signature),
        ).fetchone()
    return row_or_404(row, "Folder")


@router.patch("/folders/{folder_id}")
def rename_folder(folder_id: UUID, body: Rename, user_id: UUID = Depends(current_user_id)):
    with user_connection(user_id) as conn:
        return row_or_404(conn.execute(
            "update skive.drive_folders set name=%s, updated_at=now() "
            "where id=%s and trashed_at is null returning id, parent_id, name",
            (body.name, folder_id),
        ).fetchone(), "Folder")


@router.post("/folders/{folder_id}/move")
def move_folder(folder_id: UUID, body: Move, user_id: UUID = Depends(current_user_id)):
    with user_connection(user_id) as conn:
        require_folder(conn, body.parent_id)
        if folder_id == body.parent_id:
            raise HTTPException(400, "Cannot move a folder into itself")
        if body.parent_id is not None:
            descendants = conn.execute(
                "with recursive children as (select id from skive.drive_folders where id=%s "
                "union all select f.id from skive.drive_folders f join children c on f.parent_id=c.id) "
                "select 1 from children where id=%s",
                (folder_id, body.parent_id),
            ).fetchone()
            if descendants:
                raise HTTPException(400, "Cannot move a folder into a descendant")
        return row_or_404(conn.execute(
            "update skive.drive_folders set parent_id=%s, updated_at=now() "
            "where id=%s and trashed_at is null returning id, parent_id, name",
            (body.parent_id, folder_id),
        ).fetchone(), "Folder")


@router.delete("/folders/{folder_id}")
def trash_folder(folder_id: UUID, user_id: UUID = Depends(current_user_id)):
    with user_connection(user_id) as conn:
        return row_or_404(conn.execute(
            "update skive.drive_folders set trashed_at=now(), updated_at=now() "
            "where id=%s and trashed_at is null returning id, name",
            (folder_id,),
        ).fetchone(), "Folder")


@router.post("/files/init", status_code=201)
def init_file(body: FileInit, user_id: UUID = Depends(current_user_id)):
    file_id = uuid4()
    storage_path = f"{user_id}/{file_id}/original"
    with user_connection(user_id) as conn:
        require_folder(conn, body.parent_id)
        row = conn.execute(
            "insert into skive.drive_files (id,user_id,folder_id,name,storage_path,mime_type,size_bytes) "
            "values (%s,%s,%s,%s,%s,%s,%s) returning id,folder_id,name,size_bytes,upload_status",
            (file_id, user_id, body.parent_id, body.name, storage_path,
             body.mime_type[:255] or "application/octet-stream", body.size_bytes),
        ).fetchone()
    return {**row, "bucket": "skive-originals", "storage_path": storage_path}


@router.post("/files/{file_id}/complete")
def complete_file(file_id: UUID, user_id: UUID = Depends(current_user_id)):
    with user_connection(user_id) as conn:
        row = row_or_404(conn.execute(
            "select id,storage_path,size_bytes,version,upload_status from skive.drive_files "
            "where id=%s and trashed_at is null for update", (file_id,)
        ).fetchone(), "File")
        obj = conn.execute(
            "select metadata from storage.objects where bucket_id='skive-originals' and name=%s",
            (row["storage_path"],),
        ).fetchone()
        if obj is None:
            raise HTTPException(409, "Storage upload has not finished")
        actual_size = (obj["metadata"] or {}).get("size")
        if actual_size is not None and int(actual_size) != row["size_bytes"]:
            raise HTTPException(409, "Storage object size differs from declared size")
        conn.execute(
            "update skive.drive_files set upload_status='uploaded',analysis_status='queued',updated_at=now() "
            "where id=%s", (file_id,)
        )
        conn.execute(
            "insert into skive.drive_jobs (user_id,file_id,file_version) values (%s,%s,%s) "
            "on conflict (file_id,file_version) do nothing", (user_id, file_id, row["version"]),
        )
    return {"id": file_id, "upload_status": "uploaded", "analysis_status": "queued"}


@router.get("/files/{file_id}/status")
def file_status(file_id: UUID, user_id: UUID = Depends(current_user_id)):
    with user_connection(user_id) as conn:
        return row_or_404(conn.execute(
            "select id,upload_status,size_bytes,storage_path from skive.drive_files "
            "where id=%s and trashed_at is null", (file_id,),
        ).fetchone(), "File")


@router.patch("/files/{file_id}")
def rename_file(file_id: UUID, body: Rename, user_id: UUID = Depends(current_user_id)):
    with user_connection(user_id) as conn:
        return row_or_404(conn.execute(
            "update skive.drive_files set name=%s, updated_at=now() "
            "where id=%s and trashed_at is null returning id, folder_id, name",
            (body.name, file_id),
        ).fetchone(), "File")


@router.get("/files/{file_id}/analysis")
def file_analysis(file_id: UUID, user_id: UUID = Depends(current_user_id)):
    with user_connection(user_id) as conn:
        row = row_or_404(conn.execute(
            "select id,name,storage_path,mime_type,upload_status,version,analysis_status,analysis_error,analysis_markdown,analysis_coverage,analyzed_at "
            "from skive.drive_files where id=%s and trashed_at is null", (file_id,)
        ).fetchone(), "File")
        preview = conn.execute(
            "select chunk_index,location,left(text,8000) as text from skive.drive_file_chunks "
            "where file_id=%s and file_version=%s order by chunk_index limit 12",
            (file_id, row["version"]),
        ).fetchall()
        supplemental = conn.execute(
            "select chunk_index,location,left(text,8000) as text from skive.drive_file_chunks "
            "where file_id=%s and file_version=%s and ("
            "location like '%% annotation %%' or location like '%% speaker notes' or "
            "location like '%% cell note %%' or location like '%% threaded comment %%') "
            "order by chunk_index limit 20", (file_id, row["version"]),
        ).fetchall()
        return {**row, "preview_chunks": preview, "supplemental_chunks": supplemental}


@router.get("/files/{file_id}/read-card")
def file_read_card(file_id: UUID, user_id: UUID = Depends(current_user_id)):
    with user_connection(user_id) as conn:
        file = row_or_404(conn.execute(
            "select id,name,version,sha256,upload_status,analysis_status,analysis_error,"
            "analysis_coverage,analyzed_at from skive.drive_files "
            "where id=%s and trashed_at is null", (file_id,),
        ).fetchone(), "File")
        card = conn.execute(
            "select file_version,parser_version,status,chunk_count,quote_count,number_count,"
            "quote_samples,number_samples,coverage,error,created_at "
            "from skive.drive_file_read_cards where file_id=%s and file_version=%s",
            (file_id, file["version"]),
        ).fetchone()
        state = (file["analysis_status"] if file["analysis_status"] != "ready" else
                 card["status"] if card else "building")
        return {"file": file, "state": state, "card": card,
                "note": "대표 문장과 수치는 추출 원문의 위치 색인입니다. 본인 역할이나 성과로 확인된 사실이 아닙니다."}


@router.get("/files/{file_id}/read-card/chunks")
def file_read_card_chunks(file_id: UUID, after: int = Query(default=0, ge=0),
                          limit: int = Query(default=20, ge=1, le=50),
                          user_id: UUID = Depends(current_user_id)):
    with user_connection(user_id) as conn:
        file = row_or_404(conn.execute(
            "select id,version,analysis_status from skive.drive_files "
            "where id=%s and trashed_at is null", (file_id,),
        ).fetchone(), "File")
        if file["analysis_status"] != "ready":
            return {"file_id": file_id, "file_version": file["version"],
                    "analysis_status": file["analysis_status"], "chunks": [], "next_after": None}
        rows = conn.execute(
            "select chunk_index,location,text from skive.drive_file_chunks "
            "where file_id=%s and file_version=%s and chunk_index>%s "
            "order by chunk_index limit %s",
            (file_id, file["version"], after, limit + 1),
        ).fetchall()
        page = rows[:limit]
        return {"file_id": file_id, "file_version": file["version"], "analysis_status": file["analysis_status"],
                "chunks": page, "next_after": page[-1]["chunk_index"] if len(rows) > limit else None}


@router.post("/files/{file_id}/reanalyze")
def reanalyze_file(file_id: UUID, user_id: UUID = Depends(current_user_id)):
    """Explicitly refresh an old extraction without changing the private original."""
    with get_connection() as conn:
        conn.row_factory = dict_row
        row = row_or_404(conn.execute(
            "select id,user_id,version,upload_status,analysis_status from skive.drive_files "
            "where id=%s and user_id=%s and trashed_at is null for update", (file_id, user_id),
        ).fetchone(), "File")
        if row["upload_status"] != "uploaded":
            raise HTTPException(409, "File upload has not finished")
        if row["analysis_status"] in {"queued", "processing"}:
            return {"id": file_id, "analysis_status": row["analysis_status"]}
        conn.execute("delete from skive.drive_file_read_cards where file_id=%s and file_version=%s",
                     (file_id, row["version"]))
        conn.execute(
            "update skive.drive_files set analysis_status='queued',analysis_error=null,"
            "analysis_coverage=null,updated_at=now() where id=%s and user_id=%s and version=%s",
            (file_id, user_id, row["version"]),
        )
        conn.execute(
            "insert into skive.drive_jobs (user_id,file_id,file_version,status) values (%s,%s,%s,'queued') "
            "on conflict (file_id,file_version) do update set status='queued',attempts=0,error=null,"
            "started_at=null,finished_at=null",
            (user_id, file_id, row["version"]),
        )
    return {"id": file_id, "analysis_status": "queued"}


@router.post("/files/{file_id}/move")
def move_file(file_id: UUID, body: Move, user_id: UUID = Depends(current_user_id)):
    with user_connection(user_id) as conn:
        require_folder(conn, body.parent_id)
        return row_or_404(conn.execute(
            "update skive.drive_files set folder_id=%s, updated_at=now() "
            "where id=%s and trashed_at is null returning id, folder_id, name",
            (body.parent_id, file_id),
        ).fetchone(), "File")


@router.delete("/files/{file_id}")
def trash_file(file_id: UUID, user_id: UUID = Depends(current_user_id)):
    with user_connection(user_id) as conn:
        return row_or_404(conn.execute(
            "update skive.drive_files set trashed_at=now(), updated_at=now() "
            "where id=%s and trashed_at is null returning id, name",
            (file_id,),
        ).fetchone(), "File")


@router.get("/search")
def search(q: str = Query(min_length=1, max_length=100), user_id: UUID = Depends(current_user_id)):
    pattern = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    with user_connection(user_id) as conn:
        folders = conn.execute(
            "select id,parent_id,name,updated_at from skive.drive_folders "
            "where name ilike %s escape '\\' and trashed_at is null order by updated_at desc limit 100",
            (pattern,),
        ).fetchall()
        files = conn.execute(
            "select id,folder_id,name,storage_path,mime_type,size_bytes,upload_status,analysis_status,updated_at from skive.drive_files "
            "where name ilike %s escape '\\' and trashed_at is null order by updated_at desc limit 100",
            (pattern,),
        ).fetchall()
    return {"folders": folders, "files": files}
