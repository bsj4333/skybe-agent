"""Persistent Google Drive connection and Drive-sourced files.

A user approves once. The refresh token is stored encrypted and only the server can
read it. Originals stay in Google: importing registers each file, the worker reads it to
a temp file, and SKIVE keeps only metadata and the extracted text.
"""

import json
import os
import re
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from urllib.parse import urlencode
from uuid import UUID, uuid4

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from skive.drive_activities import require_activity
from skive.drive_api import require_folder
from skive.drive_auth import current_user_id
from skive.drive_db import service_connection, user_connection
from skive.drive_tiers import noise_folder, worth_reading

router = APIRouter(prefix="/api/drive/google", tags=["google-drive"])

SCOPE = "https://www.googleapis.com/auth/drive.readonly"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
DRIVE_API = "https://www.googleapis.com/drive/v3"
NONCE_COOKIE = "skive_google_nonce"
STATE_TTL_SECONDS = 600
IMPORT_THREADS = 4
STALE_IMPORT_MINUTES = 5
MAX_FOLDER_DEPTH = 30
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
    webViewLink: str | None = Field(default=None, max_length=2000)


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
                      "fields": "nextPageToken,files(id,name,mimeType,size,modifiedTime,webViewLink)"}
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


def _require_connected(conn, user_id: UUID) -> None:
    if not conn.execute("select 1 from skive.drive_google_connections where user_id=%s and not needs_reconnect",
                        (user_id,)).fetchone():
        raise HTTPException(409, "구글 드라이브를 먼저 연동해 주세요")


def _queue_import(user_id: UUID, body: ImportRequest, activity_id: UUID | None = None) -> dict:
    with service_connection() as conn:
        return conn.execute(
            "insert into skive.drive_google_imports(user_id,parent_id,selection,activity_id) "
            "values (%s,%s,%s::jsonb,%s) returning id,status",
            (user_id, body.parent_id, body.model_dump_json(include={"items"}), activity_id),
        ).fetchone()


@router.post("/imports", status_code=201)
def start_import(body: ImportRequest, user_id: UUID = Depends(current_user_id)):
    _require_enabled()
    with user_connection(user_id) as conn:
        require_folder(conn, body.parent_id)
        _require_connected(conn, user_id)
    return _queue_import(user_id, body)


@router.post("/experiences/{activity_id}/folder", status_code=201)
def link_folder(activity_id: UUID, folder: GoogleItem, user_id: UUID = Depends(current_user_id)):
    """Reads the Drive folder a person points at and links its files to that experience."""
    _require_enabled()
    if folder.mimeType != FOLDER:
        raise HTTPException(422, "폴더를 골라 주세요")
    with user_connection(user_id) as conn:
        require_activity(conn, activity_id)
        _require_connected(conn, user_id)
        # A rebuild replaces untouched candidates; this one now carries the user's decision.
        conn.execute("update skive.drive_activities set origin='user',updated_at=now() where id=%s", (activity_id,))
    return _queue_import(user_id, ImportRequest(items=[folder]), activity_id)


@router.get("/imports/latest")
def latest_import(user_id: UUID = Depends(current_user_id)):
    with user_connection(user_id) as conn:
        return conn.execute(
            "select id,status,total,done,skipped,failed,error,activity_id,linked,created_at,updated_at "
            "from skive.drive_google_imports "
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


def _set_total(import_id: UUID, total: int, skipped: int) -> None:
    with service_connection() as conn:
        conn.execute("update skive.drive_google_imports set total=%s,skipped=%s,done=0,failed=0,"
                     "heartbeat_at=now(),updated_at=now() where id=%s", (total, skipped, import_id))


def drive_path(user_id: UUID, item_id: str) -> tuple[str, ...]:
    """Folder names above a Drive item, so a nested folder lands where a full import would put it."""
    names, current = [], item_id
    with _google_client() as client:
        for _ in range(MAX_FOLDER_DEPTH):
            reply = client.get(f"{DRIVE_API}/files/{current}",
                               params={"fields": "name,parents", "supportsAllDrives": "true"},
                               headers={"Authorization": "Bearer " + access_token(user_id)})
            if reply.status_code in (403, 404):
                break  # A shared folder's parents can belong to someone else.
            reply.raise_for_status()
            meta = reply.json()
            if not meta.get("parents"):
                break  # The drive root has no parent and is not part of the path.
            if current != item_id:
                names.append(safe_name(meta["name"]))
            current = meta["parents"][0]
    return tuple(reversed(names))


def collect(user_id: UUID, item: dict, path: tuple[str, ...], out: list, skipped: list, import_id: UUID) -> None:
    if item["mimeType"] == FOLDER and noise_folder(item["name"]):
        skipped.append(item["name"])
    elif item["mimeType"] == FOLDER:
        folder = (*path, safe_name(item["name"]))
        out.append((None, folder))
        for child in list_children(user_id, folder_query(item["id"])):
            collect(user_id, child, folder, out, skipped, import_id)
        # A deep tree can take minutes to list; keep the job from looking abandoned.
        _set_total(import_id, sum(1 for found, _ in out if found is not None), len(skipped))
    elif file_plan(item) is None:
        skipped.append(item["name"])
    else:
        out.append((item, path))


def ensure_folder(user_id: UUID, parent_id: UUID | None, path: tuple[str, ...], cache: dict) -> UUID | None:
    if path in cache or not path:
        return cache.get(path, parent_id)
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


def register_file(user_id: UUID, item: dict, folder_id: UUID | None) -> bool:
    """Records a Drive file for reading. Returns False when nothing changed since last time."""
    name, mime, export = file_plan(item)
    modified = item.get("modifiedTime") or ""
    size = int(item.get("size") or 0)
    web_url = item.get("webViewLink")
    with service_connection() as conn:
        found = conn.execute(
            "select id,version,google_modified_time from skive.drive_files where user_id=%s and "
            "google_file_id=%s and source='google' and trashed_at is null", (user_id, item["id"])).fetchone()
        if found and found["google_modified_time"] == modified:
            return False
        if found:
            file_id, version = found["id"], found["version"] + 1
            conn.execute(
                "update skive.drive_files set version=%s,name=%s,mime_type=%s,size_bytes=%s,google_modified_time=%s,"
                "google_web_url=%s,analysis_status='queued',analysis_error=null,updated_at=now() where id=%s",
                (version, name, mime[:255], size, modified, web_url, file_id))
            # Search reads every chunk of a file, so the old version must not stay beside the new one.
            conn.execute("delete from skive.drive_file_chunks where file_id=%s and file_version<%s", (file_id, version))
        else:
            file_id, version = uuid4(), 1
            conn.execute(
                "insert into skive.drive_files(id,user_id,folder_id,name,storage_path,mime_type,size_bytes,"
                "upload_status,analysis_status,source,google_file_id,google_modified_time,google_export_mime,"
                "google_web_url) values (%s,%s,%s,%s,%s,%s,%s,'uploaded','queued','google',%s,%s,%s,%s)",
                (file_id, user_id, folder_id, name, f"{user_id}/{file_id}/original", mime[:255], size,
                 item["id"], modified, export, web_url))
        conn.execute("insert into skive.drive_jobs(user_id,file_id,file_version) values (%s,%s,%s) "
                     "on conflict (file_id,file_version) do nothing", (user_id, file_id, version))
    return True


@contextmanager
def download_stream(job: dict):
    """Opens the original at Google. The worker reads it to a temp file and keeps only the text."""
    headers = {"Authorization": "Bearer " + access_token(job["user_id"])}
    if job["google_export_mime"]:
        url = f"{DRIVE_API}/files/{job['google_file_id']}/export"
        params = {"mimeType": job["google_export_mime"]}
    else:
        url = f"{DRIVE_API}/files/{job['google_file_id']}"
        params = {"alt": "media", "supportsAllDrives": "true"}
    with _google_client() as client, client.stream("GET", url, params=params, headers=headers) as reply:
        yield reply


def _bump(import_id: UUID, column: str) -> None:
    assert column in {"done", "skipped", "failed"}
    with service_connection() as conn:
        conn.execute(f"update skive.drive_google_imports set {column}={column}+1,heartbeat_at=now(),"
                     "updated_at=now() where id=%s", (import_id,))


def for_experience(entries: list, person: str) -> tuple[list, int]:
    """Keeps files an experience can use. A project folder can hold thousands of images."""
    from skive.drive_experience import rule_owner
    from skive.drive_worker import readable

    kept = []
    for item, path in entries:
        name = file_plan(item)[0] if item else ""
        if item is None or (readable(name) and worth_reading(name)
                            and rule_owner("/".join(path), name, person) != "other_person"):
            kept.append((item, path))
    return kept, len(entries) - len(kept)


def link_imported(job: dict, google_ids: list[str]) -> None:
    """A file already in SKIVE links too, unless the user said it belongs to someone else."""
    with service_connection() as conn:
        added = conn.execute(
            "insert into skive.drive_activity_files(user_id,activity_id,file_id) "
            "select d.user_id,%s,d.id from skive.drive_files d where d.user_id=%s and d.source='google' "
            "and d.google_file_id=any(%s) and d.trashed_at is null and not exists ("
            "select 1 from skive.drive_file_cards k where k.file_id=d.id and k.owner='other_person' "
            "and k.owner_source='user') on conflict (activity_id,file_id) do nothing returning file_id",
            (job["activity_id"], job["user_id"], google_ids)).fetchall()
        conn.execute("update skive.drive_google_imports set linked=%s,updated_at=now() where id=%s",
                     (len(added), job["id"]))
        conn.execute("update skive.drive_activities set updated_at=now() where id=%s", (job["activity_id"],))


def _person(user_id: UUID) -> str:
    with service_connection() as conn:
        row = conn.execute("select display_name from skive.drive_profiles where user_id=%s", (user_id,)).fetchone()
    return row["display_name"] if row else ""


def execute_import(job: dict) -> None:
    user_id, entries, skipped = job["user_id"], [], []
    linking = job["activity_id"] is not None
    base = drive_path(user_id, job["selection"]["items"][0]["id"]) if linking else ()
    for item in job["selection"]["items"]:
        collect(user_id, item, base, entries, skipped, job["id"])
    dropped = 0
    if linking:
        entries, dropped = for_experience(entries, _person(user_id))
    _set_total(job["id"], sum(1 for item, _ in entries if item is not None), len(skipped) + dropped)
    cache: dict = {}
    files = []
    for item, path in entries:
        folder_id = ensure_folder(user_id, job["parent_id"], path, cache)
        if item is not None:
            files.append((item, folder_id))

    def process(entry):
        item, folder_id = entry
        try:
            register_file(user_id, item, folder_id)
            _bump(job["id"], "done")
        except Exception as exc:
            print(f"Google import file failed: {type(exc).__name__}", flush=True)
            _bump(job["id"], "failed")

    with ThreadPoolExecutor(IMPORT_THREADS) as pool:
        list(pool.map(process, files))
    if linking:
        link_imported(job, [item["id"] for item, _ in files])


def run_google_import_once() -> bool:
    if not enabled():
        return False
    with service_connection() as conn:
        job = conn.execute(
            "select id,user_id,parent_id,selection,activity_id from skive.drive_google_imports "
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
