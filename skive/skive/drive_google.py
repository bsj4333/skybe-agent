"""Persistent Google Drive connection and server-side snapshot import.

A user approves once. The refresh token is stored encrypted and only the server can
read it. Imports run in the worker: bytes stream from Google to Storage in chunks, so
they neither wait on the browser nor sit whole in memory.
"""

import base64
import json
import os
import re
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlencode, urljoin
from uuid import UUID, uuid4

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from skive.drive_api import require_folder
from skive.drive_auth import current_user_id
from skive.drive_db import service_connection, user_connection

router = APIRouter(prefix="/api/drive/google", tags=["google-drive"])

SCOPE = "https://www.googleapis.com/auth/drive.readonly"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
DRIVE_API = "https://www.googleapis.com/drive/v3"
NONCE_COOKIE = "skive_google_nonce"
STATE_TTL_SECONDS = 600
CHUNK_BYTES = 6 * 1024 * 1024
IMPORT_THREADS = 4
STALE_IMPORT_MINUTES = 5
FOLDER = "application/vnd.google-apps.folder"
GOOGLE_NATIVE = "application/vnd.google-apps."
EXPORTS = {  # Google-native files have no bytes of their own, so they are exported.
    "application/vnd.google-apps.document":
        ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx"),
    "application/vnd.google-apps.spreadsheet":
        ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx"),
    "application/vnd.google-apps.presentation":
        ("application/vnd.openxmlformats-officedocument.presentationml.presentation", ".pptx"),
}
SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")

_token_cache: dict[UUID, tuple[str, float]] = {}
_token_lock = threading.Lock()


class GoogleReconnect(RuntimeError):
    """Google no longer accepts the stored approval; the user must connect again."""


class GoogleItem(BaseModel):
    id: str = Field(pattern=SAFE_ID.pattern, max_length=200)
    name: str = Field(min_length=1, max_length=1000)
    mimeType: str = Field(max_length=200)
    size: str | None = None
    modifiedTime: str | None = None


class ImportRequest(BaseModel):
    items: list[GoogleItem] = Field(min_length=1, max_length=200)
    parent_id: UUID | None = None


def enabled() -> bool:
    return all(os.getenv(name) for name in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET",
                                            "GOOGLE_TOKEN_KEY", "SKIVE_PUBLIC_URL"))


def _fernet() -> Fernet:
    return Fernet(os.environ["GOOGLE_TOKEN_KEY"].encode())


def _public_url() -> str:
    return os.environ["SKIVE_PUBLIC_URL"].rstrip("/")


def _redirect_uri() -> str:
    return _public_url() + "/api/drive/google/callback"


def _google_client() -> httpx.Client:
    return httpx.Client(timeout=60, follow_redirects=True)


def _require_enabled() -> None:
    if not enabled():
        raise HTTPException(503, "구글 드라이브 연동이 아직 설정되지 않았습니다")


def make_state(user_id: UUID, nonce: str) -> str:
    return _fernet().encrypt(json.dumps({"u": str(user_id), "n": nonce}).encode()).decode()


def read_state(state: str, nonce: str | None) -> UUID:
    """The cookie ties approval to the browser that started it, so nobody can trick a
    victim into approving their Drive for the attacker's SKIVE account."""
    try:
        data = json.loads(_fernet().decrypt(state.encode(), ttl=STATE_TTL_SECONDS))
    except (InvalidToken, ValueError) as exc:
        raise HTTPException(400, "연동 요청이 만료되었습니다. 다시 시도해 주세요") from exc
    if not nonce or not secrets.compare_digest(data["n"], nonce):
        raise HTTPException(400, "연동을 시작한 브라우저에서 다시 시도해 주세요")
    return UUID(data["u"])


@router.get("/status")
def status(user_id: UUID = Depends(current_user_id)):
    if not enabled():
        return {"enabled": False, "connected": False, "email": None, "needs_reconnect": False}
    with user_connection(user_id) as conn:
        row = conn.execute("select google_email,needs_reconnect from skive.drive_google_connections "
                           "where user_id=%s", (user_id,)).fetchone()
    return {"enabled": True, "connected": bool(row), "email": row["google_email"] if row else None,
            "needs_reconnect": bool(row and row["needs_reconnect"])}


@router.post("/connect")
def connect(response: Response, user_id: UUID = Depends(current_user_id)):
    _require_enabled()
    nonce = secrets.token_urlsafe(24)
    response.set_cookie(NONCE_COOKIE, nonce, max_age=STATE_TTL_SECONDS, httponly=True, samesite="lax",
                        secure=_public_url().startswith("https://"), path="/api/drive/google")
    query = urlencode({"client_id": os.environ["GOOGLE_CLIENT_ID"], "redirect_uri": _redirect_uri(),
                       "response_type": "code", "scope": SCOPE, "access_type": "offline",
                       "prompt": "consent", "state": make_state(user_id, nonce)})
    return {"url": f"{AUTH_URL}?{query}"}


@router.get("/callback")
def callback(state: str = "", code: str = "", error: str = "",
             nonce: str | None = Cookie(default=None, alias=NONCE_COOKIE)):
    _require_enabled()
    user_id = read_state(state, nonce)
    target = RedirectResponse(_public_url() + "/?google=" + ("denied" if error or not code else "connected"))
    target.delete_cookie(NONCE_COOKIE, path="/api/drive/google")
    if error or not code:
        return target
    with _google_client() as client:
        tokens = client.post(TOKEN_URL, data={
            "code": code, "client_id": os.environ["GOOGLE_CLIENT_ID"],
            "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
            "redirect_uri": _redirect_uri(), "grant_type": "authorization_code"})
        if tokens.is_error or not tokens.json().get("refresh_token"):
            failed = RedirectResponse(_public_url() + "/?google=failed")
            failed.delete_cookie(NONCE_COOKIE, path="/api/drive/google")
            return failed
        payload = tokens.json()
        about = client.get(f"{DRIVE_API}/about", params={"fields": "user(emailAddress)"},
                           headers={"Authorization": "Bearer " + payload["access_token"]})
    email = about.json().get("user", {}).get("emailAddress") if about.is_success else None
    encrypted = _fernet().encrypt(payload["refresh_token"].encode()).decode()
    with service_connection() as conn:
        conn.execute(
            "insert into skive.drive_google_connections(user_id,google_email,refresh_token_encrypted) "
            "values (%s,%s,%s) on conflict (user_id) do update set google_email=excluded.google_email,"
            "refresh_token_encrypted=excluded.refresh_token_encrypted,needs_reconnect=false,updated_at=now()",
            (user_id, email, encrypted))
    with _token_lock:
        _token_cache.pop(user_id, None)
    return target


def _stored_refresh_token(user_id: UUID) -> str:
    with service_connection() as conn:
        row = conn.execute("select refresh_token_encrypted from skive.drive_google_connections "
                           "where user_id=%s", (user_id,)).fetchone()
    if not row:
        raise GoogleReconnect("구글 드라이브가 연동되어 있지 않습니다")
    return _fernet().decrypt(row["refresh_token_encrypted"].encode()).decode()


def access_token(user_id: UUID) -> str:
    with _token_lock:
        cached = _token_cache.get(user_id)
        if cached and cached[1] > time.time():
            return cached[0]
        refresh = _stored_refresh_token(user_id)
        with _google_client() as client:
            reply = client.post(TOKEN_URL, data={
                "client_id": os.environ["GOOGLE_CLIENT_ID"], "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
                "refresh_token": refresh, "grant_type": "refresh_token"})
        if reply.status_code in (400, 401):
            with service_connection() as conn:
                conn.execute("update skive.drive_google_connections set needs_reconnect=true,updated_at=now() "
                             "where user_id=%s", (user_id,))
            raise GoogleReconnect("구글 연결이 만료되었습니다. 프로필에서 다시 연동해 주세요")
        reply.raise_for_status()
        body = reply.json()
        _token_cache[user_id] = (body["access_token"], time.time() + int(body.get("expires_in", 3600)) - 120)
        return body["access_token"]


@router.delete("/connection")
def disconnect(user_id: UUID = Depends(current_user_id)):
    _require_enabled()
    try:
        refresh = _stored_refresh_token(user_id)
    except GoogleReconnect:
        return {"connected": False}
    try:
        with _google_client() as client:
            client.post(REVOKE_URL, data={"token": refresh})
    except httpx.HTTPError:
        pass  # Google may be unreachable; deleting our copy still ends SKIVE's access.
    with service_connection() as conn:
        conn.execute("delete from skive.drive_google_connections where user_id=%s", (user_id,))
    with _token_lock:
        _token_cache.pop(user_id, None)
    return {"connected": False}


def list_children(user_id: UUID, query: str) -> list[dict]:
    files, page_token = [], None
    with _google_client() as client:
        while True:
            params = {"q": query, "pageSize": 1000, "orderBy": "folder,name",
                      "includeItemsFromAllDrives": "true", "supportsAllDrives": "true",
                      "fields": "nextPageToken,files(id,name,mimeType,size,modifiedTime)"}
            if page_token:
                params["pageToken"] = page_token
            reply = client.get(f"{DRIVE_API}/files", params=params,
                               headers={"Authorization": "Bearer " + access_token(user_id)})
            reply.raise_for_status()
            page = reply.json()
            files.extend(page.get("files", []))
            page_token = page.get("nextPageToken")
            if not page_token:
                return files


def folder_query(parent: str) -> str:
    if parent == "shared":
        return "sharedWithMe=true and trashed=false"
    if parent != "root" and not SAFE_ID.match(parent):
        raise HTTPException(422, "잘못된 폴더입니다")
    return f"'{parent}' in parents and trashed=false"


@router.get("/files")
def browse(parent: str = "root", user_id: UUID = Depends(current_user_id)):
    _require_enabled()
    try:
        return {"files": list_children(user_id, folder_query(parent))}
    except GoogleReconnect as exc:
        raise HTTPException(409, str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(502, f"구글 드라이브 응답 오류 ({exc.response.status_code})") from exc


@router.post("/imports", status_code=201)
def start_import(body: ImportRequest, user_id: UUID = Depends(current_user_id)):
    _require_enabled()
    with user_connection(user_id) as conn:
        require_folder(conn, body.parent_id)
        if not conn.execute("select 1 from skive.drive_google_connections where user_id=%s and not needs_reconnect",
                            (user_id,)).fetchone():
            raise HTTPException(409, "구글 드라이브를 먼저 연동해 주세요")
    with service_connection() as conn:
        return conn.execute(
            "insert into skive.drive_google_imports(user_id,parent_id,selection) values (%s,%s,%s::jsonb) "
            "returning id,status", (user_id, body.parent_id, body.model_dump_json(include={"items"})),
        ).fetchone()


@router.get("/imports/latest")
def latest_import(user_id: UUID = Depends(current_user_id)):
    with user_connection(user_id) as conn:
        return conn.execute(
            "select id,status,total,done,skipped,failed,error,created_at,updated_at from skive.drive_google_imports "
            "where user_id=%s order by created_at desc limit 1", (user_id,)).fetchone() or {}


def safe_name(name: str) -> str:
    """Drive allows names SKIVE paths cannot hold; keep them readable instead of failing."""
    cleaned = name.replace("/", "／").replace("\\", "＼").strip()[:255].strip()
    return "이름 없음" if cleaned in {"", ".", ".."} else cleaned


def file_plan(item: dict) -> tuple[str, str, str | None] | None:
    """Returns (name, mime type, export mime type), or None for items that are not files."""
    export = EXPORTS.get(item["mimeType"])
    if export:
        return safe_name(item["name"])[:250] + export[1], export[0], export[0]
    if item["mimeType"].startswith(GOOGLE_NATIVE):
        return None  # Shortcuts, forms and the like have nothing to copy.
    return safe_name(item["name"]), item["mimeType"], None


def collect(user_id: UUID, item: dict, path: tuple[str, ...], out: list, skipped: list) -> None:
    if item["mimeType"] == FOLDER:
        folder = (*path, safe_name(item["name"]))
        out.append((None, folder))
        for child in list_children(user_id, folder_query(item["id"])):
            collect(user_id, child, folder, out, skipped)
    elif file_plan(item) is None:
        skipped.append(item["name"])
    else:
        out.append((item, path))


def ensure_folder(user_id: UUID, parent_id: UUID | None, path: tuple[str, ...], cache: dict) -> UUID | None:
    current = parent_id
    with service_connection() as conn:
        for depth in range(1, len(path) + 1):
            key = path[:depth]
            if key in cache:
                current = cache[key]
                continue
            found = conn.execute(
                "select id from skive.drive_folders where user_id=%s and parent_id is not distinct from %s "
                "and name=%s and trashed_at is null order by created_at,id limit 1",
                (user_id, current, key[-1])).fetchone()
            current = found["id"] if found else conn.execute(
                "insert into skive.drive_folders(user_id,parent_id,name) values (%s,%s,%s) returning id",
                (user_id, current, key[-1])).fetchone()["id"]
            cache[key] = current
    return current


def already_imported(user_id: UUID, item: dict) -> bool:
    with service_connection() as conn:
        return bool(conn.execute(
            "select 1 from skive.drive_google_files g join skive.drive_files f on f.id=g.file_id "
            "where g.user_id=%s and g.google_file_id=%s and g.modified_time=%s and f.trashed_at is null",
            (user_id, item["id"], item.get("modifiedTime") or "")).fetchone())


def _chunks(stream, size: int):
    buffer = bytearray()
    for piece in stream:
        buffer.extend(piece)
        while len(buffer) >= size:
            yield bytes(buffer[:size])
            del buffer[:size]
    if buffer:
        yield bytes(buffer)


def _send_to_storage(storage_path: str, mime: str, size: int, pieces) -> None:
    secret = os.environ["SUPABASE_SECRET_KEY"]
    base = os.environ["SUPABASE_URL"].rstrip("/").replace(".supabase.co", ".storage.supabase.co")
    headers = {"apikey": secret, "Authorization": f"Bearer {secret}", "Tus-Resumable": "1.0.0"}
    metadata = ",".join(f"{key} {base64.b64encode(value.encode()).decode()}" for key, value in {
        "bucketName": "skive-originals", "objectName": storage_path,
        "contentType": mime or "application/octet-stream", "cacheControl": "3600"}.items())
    with httpx.Client(timeout=120) as client:
        if size == 0:  # The resumable endpoint rejects empty uploads.
            client.post(f"{base}/storage/v1/object/skive-originals/{storage_path}", content=b"", headers={
                "apikey": secret, "Authorization": f"Bearer {secret}",
                "Content-Type": mime or "application/octet-stream"}).raise_for_status()
            return
        created = client.post(f"{base}/storage/v1/upload/resumable",
                              headers={**headers, "Upload-Length": str(size), "Upload-Metadata": metadata})
        created.raise_for_status()
        location = urljoin(base, created.headers["Location"])
        offset = 0
        for piece in pieces:
            client.patch(location, content=piece, headers={
                **headers, "Upload-Offset": str(offset),
                "Content-Type": "application/offset+octet-stream"}).raise_for_status()
            offset += len(piece)


def _finish_file(user_id: UUID, item: dict, file_id: UUID, storage_path: str, size: int) -> None:
    for _ in range(10):
        with service_connection() as conn:
            row = conn.execute("select metadata from storage.objects where bucket_id='skive-originals' "
                               "and name=%s", (storage_path,)).fetchone()
            if row:
                if int((row["metadata"] or {}).get("size", size)) != size:
                    raise RuntimeError("저장된 파일 크기가 다릅니다")
                conn.execute("update skive.drive_files set upload_status='uploaded',analysis_status='queued',"
                             "updated_at=now() where id=%s and user_id=%s", (file_id, user_id))
                conn.execute("insert into skive.drive_jobs(user_id,file_id,file_version) values (%s,%s,1) "
                             "on conflict (file_id,file_version) do nothing", (user_id, file_id))
                conn.execute(
                    "insert into skive.drive_google_files(user_id,google_file_id,modified_time,file_id) "
                    "values (%s,%s,%s,%s) on conflict (user_id,google_file_id) do update set "
                    "modified_time=excluded.modified_time,file_id=excluded.file_id",
                    (user_id, item["id"], item.get("modifiedTime") or "", file_id))
                return
        time.sleep(0.5)
    raise RuntimeError("저장소에서 파일을 찾지 못했습니다")


def import_file(user_id: UUID, item: dict, folder_id: UUID | None) -> None:
    name, mime, export = file_plan(item)
    file_id = uuid4()
    storage_path = f"{user_id}/{file_id}/original"
    headers = {"Authorization": "Bearer " + access_token(user_id)}
    with _google_client() as client:
        if export:
            reply = client.get(f"{DRIVE_API}/files/{item['id']}/export", params={"mimeType": export}, headers=headers)
            reply.raise_for_status()
            data, size, stream = reply.content, len(reply.content), None
        else:
            data, size = None, int(item.get("size") or 0)
            stream = client.stream("GET", f"{DRIVE_API}/files/{item['id']}",
                                   params={"alt": "media", "supportsAllDrives": "true"}, headers=headers)
        with service_connection() as conn:
            conn.execute("insert into skive.drive_files(id,user_id,folder_id,name,storage_path,mime_type,size_bytes) "
                         "values (%s,%s,%s,%s,%s,%s,%s)", (file_id, user_id, folder_id, name, storage_path, mime[:255], size))
        try:
            if stream is None:
                _send_to_storage(storage_path, mime, size, [data] if size else [])
            else:
                with stream as source:
                    source.raise_for_status()
                    _send_to_storage(storage_path, mime, size, _chunks(source.iter_bytes(), CHUNK_BYTES))
            _finish_file(user_id, item, file_id, storage_path, size)
        except Exception:
            with service_connection() as conn:
                conn.execute("delete from skive.drive_files where id=%s and user_id=%s", (file_id, user_id))
            raise


def _bump(import_id: UUID, column: str) -> None:
    assert column in {"done", "skipped", "failed"}
    with service_connection() as conn:
        conn.execute(f"update skive.drive_google_imports set {column}={column}+1,heartbeat_at=now(),"
                     "updated_at=now() where id=%s", (import_id,))


def execute_import(job: dict) -> None:
    user_id, entries, skipped = job["user_id"], [], []
    for item in job["selection"]["items"]:
        collect(user_id, item, (), entries, skipped)
    cache: dict = {}
    files = []
    for item, path in entries:
        folder_id = ensure_folder(user_id, job["parent_id"], path, cache)
        if item is not None:
            files.append((item, folder_id))
    with service_connection() as conn:
        conn.execute("update skive.drive_google_imports set total=%s,done=0,failed=0,skipped=%s,"
                     "heartbeat_at=now(),updated_at=now() where id=%s", (len(files), len(skipped), job["id"]))

    def process(entry):
        item, folder_id = entry
        try:
            if already_imported(user_id, item):
                _bump(job["id"], "done")
                return
            import_file(user_id, item, folder_id)
            _bump(job["id"], "done")
        except Exception as exc:
            print(f"Google import file failed: {type(exc).__name__}", flush=True)
            _bump(job["id"], "failed")

    with ThreadPoolExecutor(IMPORT_THREADS) as pool:
        list(pool.map(process, files))


def run_google_import_once() -> bool:
    if not enabled():
        return False
    with service_connection() as conn:
        job = conn.execute(
            "select id,user_id,parent_id,selection from skive.drive_google_imports "
            "where status='queued' or (status='processing' and heartbeat_at < now()-make_interval(mins => %s)) "
            "order by created_at for update skip locked limit 1", (STALE_IMPORT_MINUTES,)).fetchone()
        if not job:
            return False
        conn.execute("update skive.drive_google_imports set status='processing',error=null,heartbeat_at=now(),"
                     "updated_at=now() where id=%s", (job["id"],))
    try:
        execute_import(job)
        status_value, error = "done", None
    except GoogleReconnect as exc:
        status_value, error = "failed", str(exc)
    except Exception as exc:
        print(f"Google import failed: {type(exc).__name__}", flush=True)
        status_value, error = "failed", "구글 드라이브에서 가져오지 못했습니다"
    with service_connection() as conn:
        conn.execute("update skive.drive_google_imports set status=%s,error=%s,updated_at=now() where id=%s",
                     (status_value, error, job["id"]))
    return True


def google_import_loop() -> None:
    """Separate from extraction so a long import never holds up reading other files."""
    while True:
        try:
            if not run_google_import_once():
                time.sleep(5)
        except Exception as exc:
            print(f"Google import loop error: {type(exc).__name__}", flush=True)
            time.sleep(10)
