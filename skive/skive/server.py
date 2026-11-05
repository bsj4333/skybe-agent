"""SKIVE 로컬 웹서버. `uv run uvicorn skive.server:app --reload` 로 실행.

CLI(skive/cli.py)가 하던 일(ingest, profile, apply, chat)을 HTTP로 노출한다.
목업 UI(ui_mockup/skive_ui.html)를 실제 데이터에 연결하기 위한 첫 백엔드 뼈대.
"""

import base64
import json
import os
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from starlette.datastructures import UploadFile as StarletteUploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel

from skive import store
from skive.drive_api import router as drive_router
from skive.drive_activities import router as activity_router
from skive.drive_workspace import router as workspace_router
from skive.drive_career import router as career_router
from skive.drive_experience import narrative_router, profile_router
from skive.drive_experience import router as experience_router
from skive.drive_google import router as google_router
from skive.drive_project_summary import router as project_summary_router
from skive.analyzer import analyze_folder
from skive.apply import run_apply
from skive.importance import score_importance
from skive.models import JobRequirements, QuestionPlan
from skive.profile import build_profile
from skive.study import STUDY_DIR, list_study
from skive.user import load_user, save_user
from skive.webfetch import fetch_url_text
from skive.writer import revise_answer

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "data" / "outputs"
UI_MOCKUP = BASE_DIR / "ui_mockup" / "skive_ui.html"
DRIVE_UI = BASE_DIR / "ui_mockup" / "skive_drive.html"
WEB_OUT = BASE_DIR / "web" / "out"
TUS_BROWSER_JS = BASE_DIR / "ui_mockup" / "vendor" / "tus-4.3.1.min.js"

app = FastAPI(title="SKIVE")
app.include_router(drive_router)
app.include_router(career_router)
app.include_router(activity_router)
app.include_router(workspace_router)
app.include_router(project_summary_router)
app.include_router(google_router)
app.include_router(experience_router)
app.include_router(profile_router)
app.include_router(narrative_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def protect_legacy_api(request: Request, call_next):
    """Never expose the old shared local data routes in multiuser mode."""
    legacy_local = os.getenv("SKIVE_LEGACY_LOCAL_ONLY") == "1"
    if legacy_local and request.client and request.client.host not in {"127.0.0.1", "::1"}:
        return JSONResponse({"detail": "Legacy UI is local only"}, status_code=403)
    if legacy_local:
        origin = request.headers.get("origin")
        referer = request.headers.get("referer")
        allowed = {"http://127.0.0.1:8011", "http://localhost:8011"}
        if (origin and origin not in allowed) or (referer and not any(referer.startswith(p + "/") for p in allowed)):
            return JSONResponse({"detail": "Legacy UI only accepts its own origin"}, status_code=403)
    configured = os.getenv("SUPABASE_URL") and (
        os.getenv("SUPABASE_PUBLISHABLE_KEY") or os.getenv("SUPABASE_ANON_KEY")
    )
    path = request.url.path
    if configured and not legacy_local and path.startswith("/api/") and not path.startswith(("/api/drive/", "/api/workspace/", "/api/career/")):
        return JSONResponse({"detail": "Legacy single-user API disabled in drive mode"}, status_code=410)
    return await call_next(request)


@app.get("/")
def index():
    if WEB_OUT.is_dir() and os.getenv("SKIVE_LEGACY_LOCAL_ONLY") != "1":
        return FileResponse(WEB_OUT / "index.html", headers={"Cache-Control": "no-store"})
    if os.getenv("SKIVE_LEGACY_LOCAL_ONLY") != "1" and os.getenv("SUPABASE_URL") and (os.getenv("SUPABASE_PUBLISHABLE_KEY") or os.getenv("SUPABASE_ANON_KEY")):
        return FileResponse(DRIVE_UI, headers={"Cache-Control": "no-store"})
    if not UI_MOCKUP.is_file():
        raise HTTPException(404, "UI mockup not found")
    return FileResponse(UI_MOCKUP)


@app.get("/classic")
def classic_drive():
    return FileResponse(DRIVE_UI, headers={"Cache-Control": "no-store"})


@app.get("/drive")
def drive_index():
    if WEB_OUT.is_dir():
        return FileResponse(WEB_OUT / "drive" / "index.html", headers={"Cache-Control": "no-store"})
    if not DRIVE_UI.is_file():
        raise HTTPException(404, "Drive UI not found")
    return FileResponse(DRIVE_UI, headers={"Cache-Control": "no-store"})


@app.get("/assets/tus-4.3.1.min.js")
def tus_browser_script():
    return FileResponse(TUS_BROWSER_JS, media_type="application/javascript",
                        headers={"Cache-Control": "public, max-age=31536000, immutable"})


@app.get("/assets/career-ui.js")
def career_browser_script():
    return FileResponse(BASE_DIR / "ui_mockup" / "career_ui.js", media_type="application/javascript",
                        headers={"Cache-Control": "no-store"})


# ---------------- user ----------------


@app.get("/api/user")
def get_user():
    return load_user()


@app.put("/api/user")
def put_user(update: dict[str, Any]):
    return save_user(update)


# ---------------- experiences (드라이브) ----------------


@app.get("/api/experiences")
def list_experiences_api():
    return store.list_meta()


@app.get("/api/experiences/{exp_id}")
def get_experience_api(exp_id: str):
    meta = store.get_meta(exp_id)
    if meta is None:
        raise HTTPException(404, f"존재하지 않는 경험 id: {exp_id}")
    return {
        "meta": meta,
        "markdown": store.get_markdown(exp_id),
        "facts": store.get_facts(exp_id),
    }


class DescriptionUpdate(BaseModel):
    description: str


@app.put("/api/experiences/{exp_id}/description")
def update_experience_description(exp_id: str, req: DescriptionUpdate):
    """사용자가 언제든 다시 들어와서 이 경험에 대한 설명을 적거나 고칠 수 있는 곳.

    사용자 요청(2026-09-23): "지피티 프로젝트처럼, 이 프로젝트에 대한 설명란을 설정으로
    들어가면 적을 수 있게 해줘." 업로드 직후 인터뷰(한 번만 뜨는 질문)와 달리 이건 언제든
    다시 열어서 고칠 수 있는 자유 메모다. `writer.build_bundle()`이 이걸 [프로젝트 설명]
    블록으로 자소서 작성 근거에 포함시킨다(본인이 직접 쓴 설명이므로 사용자 진술과 같은
    성격 — 문서 근거로 승격하지 않는다)."""
    meta = store.get_meta(exp_id)
    facts = store.get_facts(exp_id)
    markdown = store.get_markdown(exp_id)
    if meta is None:
        raise HTTPException(404, f"존재하지 않는 경험 id: {exp_id}")
    meta["description"] = req.description.strip()
    store.save(exp_id, markdown, meta, facts)
    return {"meta": meta}


@app.get("/api/experiences/{exp_id}/sources")
def list_experience_sources(exp_id: str):
    meta = store.get_meta(exp_id)
    if meta is None:
        raise HTTPException(404, f"존재하지 않는 경험 id: {exp_id}")
    return meta["sources"]


@app.get("/api/experiences/{exp_id}/sources/{source:path}")
def get_experience_source(exp_id: str, source: str):
    text = store.get_source_text(exp_id, source)
    if text is None:
        raise HTTPException(404, f"존재하지 않는 id 또는 source: {exp_id}, {source}")
    return {"source": source, "text": text}


@app.get("/api/experiences/{exp_id}/download-source/{source:path}")
def download_experience_source(exp_id: str, source: str):
    """드라이브 기능(사용자 요청, 2026-09-23): 원본 파일 그대로 다운로드.

    `get_experience_source`는 AI 분석용으로 자른/미리보기한 텍스트를 주지만(CSV는
    20행만, 큰 파일은 아예 제외), 다운로드는 **원본 그대로**여야 한다 — 진짜 구글
    드라이브처럼. `meta["raw_dir"]`에서 직접 파일을 찾아 보낸다.

    URL을 `/sources/{source:path}` 밑에 두지 않고 별도 경로로 뺐다 — `{source:path}`가
    탐욕적으로 매칭해서 ".../sources/big.csv/download"를 이 라우트가 아니라 먼저 등록된
    `get_experience_source`가 `source="big.csv/download"`로 통째로 삼켜버렸다(실측: 404)."""
    meta = store.get_meta(exp_id)
    if meta is None or source not in meta["sources"]:
        raise HTTPException(404, f"존재하지 않는 id 또는 source: {exp_id}, {source}")
    raw_dir = Path(meta["raw_dir"]).resolve()
    path = (raw_dir / source).resolve()
    if not path.is_relative_to(raw_dir) or not path.is_file():
        raise HTTPException(404, "파일을 찾을 수 없음")
    return FileResponse(path, filename=Path(source).name)


class IngestRequest(BaseModel):
    folder: str
    grade: int
    id: str | None = None


@app.post("/api/experiences")
def ingest_experience(req: IngestRequest):
    """폴더 하나를 동기적으로 분석해 저장한다. LLM 호출 때문에 응답까지 시간이 걸릴 수 있다.

    TODO: 백그라운드 잡 + 진행상황 폴링/SSE로 바꾸기 (PROJECT_STATUS.md 우선순위 A-4).
    """
    root = Path(req.folder)
    if not root.is_dir():
        raise HTTPException(400, f"폴더를 찾을 수 없음: {req.folder}")
    exp_id = req.id or root.name
    return _finish_ingest(exp_id, root, req.grade)


# 브라우저 업로드 크기 제한. 없으면 실수로 수백 MB짜리 폴더(예: node_modules)를 통째로
# 올려서 서버가 오래 멈추거나 디스크를 다 쓸 수 있다 — PROJECT_STATUS.md 8.3에서 지적된
# "요청 크기·파일 수 제한 없음" 문제를 이 업로드 경로에서는 해결한다.
# 값은 환경변수로 올릴 수 있다 — 실사용자 폴더(예: 4년치 과제 371개)가 기본값을 넘어서
# 막힌 실측 사례가 있었다(2026-09-23).
MAX_UPLOAD_FILES = int(os.environ.get("SKIVE_MAX_UPLOAD_FILES", "2000"))
MAX_UPLOAD_FILE_BYTES = 15 * 1024 * 1024  # 15MB — PDF/이미지 포함해도 넉넉한 크기


@app.post("/api/experiences/upload")
async def upload_experience(request: Request):
    """브라우저에서 폴더를 드래그하거나 선택해서 올린 파일들로 경험을 분석한다.

    FastAPI의 `File(...)`/`Form(...)` 자동 파싱을 안 쓰고 `Request.form()`을 직접
    호출한다 — 자동 파싱은 Starlette의 멀티파트 파서 기본값(`max_files=1000`)을 그대로
    쓰는데, 이게 우리 `MAX_UPLOAD_FILES`보다 먼저 걸려서 이 함수가 실행되기도 전에
    "Too many files. Maximum number of files is 1000."로 끊겨버린다(F02와 비슷한 패턴 —
    코드 안 어딘가의 숨은 기본값이 우리가 정한 정책보다 먼저 적용됨). 실측: 파일 371개짜리
    폴더가 이 경로로 막혔었다.

    프론트엔드가 각 파일명에 폴더 안에서의 상대경로(`webkitRelativePath`/드롭 시
    `fullPath`)를 그대로 넣어 보내므로, 서버가 `data/uploads/<id>/` 아래에 원래
    폴더 구조를 그대로 재현한 뒤 `POST /api/experiences`(경로 입력)와 완전히 같은
    `analyze_folder`/`sync_chunks` 경로를 탄다 — 분석 로직은 하나만 유지한다.
    """
    from starlette.formparsers import MultiPartException

    try:
        form = await request.form(max_files=MAX_UPLOAD_FILES + 1, max_fields=10)
    except MultiPartException:
        raise HTTPException(400, f"파일이 너무 많음(최대 {MAX_UPLOAD_FILES}개) — 압축(zip)으로 올려보세요")

    id = form.get("id")
    grade_raw = form.get("grade")
    files = form.getlist("files")
    if not isinstance(id, str) or not id.strip():
        raise HTTPException(400, "경험 id(폴더 이름)가 비어 있음")
    if not grade_raw:
        raise HTTPException(400, "학년이 비어 있음")
    try:
        grade = int(grade_raw)
    except ValueError:
        raise HTTPException(400, f"학년은 숫자여야 함: {grade_raw!r}")
    # request.form()이 돌려주는 UploadFile은 starlette.datastructures.UploadFile이다 —
    # fastapi.UploadFile(그 서브클래스)로 isinstance 검사하면 전부 걸러져서 매번
    # "업로드된 파일이 없음"이 됐다. 베이스 클래스로 검사해야 fastapi.UploadFile 인스턴스도
    # 같이 통과한다(서브클래스이므로).
    if not files or not all(isinstance(f, StarletteUploadFile) for f in files):
        raise HTTPException(400, "업로드된 파일이 없음")
    if len(files) > MAX_UPLOAD_FILES:
        raise HTTPException(400, f"파일이 너무 많음({len(files)}개, 최대 {MAX_UPLOAD_FILES}개)")

    exp_id = id
    root = store.DATA / "uploads" / exp_id
    if root.exists():
        shutil.rmtree(root)  # 재업로드는 이전 파일을 완전히 대체한다 — 지운 파일이 남아있지 않게
    root.mkdir(parents=True, exist_ok=True)

    saved, skipped = [], []
    for f in files:
        rel = Path(f.filename or "")
        # 경로 주입 방지: "../../etc/passwd" 같은 상대경로 탈출이나 절대경로를 거부한다.
        # 클라이언트가 보낸 파일명을 그대로 서버 경로 조합에 쓰는 곳이라 반드시 필요하다.
        if not rel.parts or ".." in rel.parts or rel.is_absolute():
            skipped.append({"name": f.filename, "reason": "허용되지 않는 경로"})
            continue
        content = await f.read()
        if len(content) > MAX_UPLOAD_FILE_BYTES:
            skipped.append({"name": f.filename, "reason": f"{len(content)//1024//1024}MB — 크기 제한 초과"})
            continue
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
        saved.append(str(rel))

    if not saved:
        shutil.rmtree(root, ignore_errors=True)
        raise HTTPException(400, f"저장할 수 있는 파일이 없음 — 제외된 파일: {skipped}")

    return _finish_ingest(exp_id, root, grade, skipped)


def _finish_ingest(exp_id: str, root: Path, grade: int, skipped: list[dict] | None = None) -> dict:
    """업로드 방식이 뭐든(개별 파일/zip) 여기서부터는 같은 분석 경로를 탄다."""
    user = load_user()
    try:
        markdown, meta, facts = analyze_folder(root, user["name"], exp_id, grade)
    except ValueError as e:
        # analyze_folder가 "폴더가 너무 큼" 같은 걸 ValueError로 던지는데, 안 잡으면
        # FastAPI가 그대로 500(Internal Server Error)으로 감싸서 사용자한테는 원인이
        # 하나도 안 보였다(실측, 2026-09-23 — 화력발전소 폴더가 7,948,547자로 이 검사에
        # 걸렸는데 화면엔 그냥 "Internal Server Error"만 떴다). 사용자가 고칠 수 있는
        # 입력 오류는 400으로, 이유를 그대로 보여준다.
        raise HTTPException(400, str(e))

    # 제목은 사용자가 붙인 폴더 이름을 번호까지 그대로 쓴다. AI가 원문 기준으로 새로
    # 지은 제목("Data Preprocessing and Anomaly Detection" 등)은 ai_title로만 참고
    # 남긴다 — 홈은 드라이브이지 AI가 이름을 정리해주는 곳이 아니다(사용자 피드백,
    # 2026-09-23: "그냥 드라이브니깐 폴더 올리는 대로 그냥 올려. 숫자 왜 임의로 없애").
    ai_title = meta["title"]
    if ai_title != exp_id:
        markdown = markdown.replace(f"# {ai_title}", f"# {exp_id}", 1)
        facts["title"] = exp_id
        meta["title"] = exp_id
        meta["ai_title"] = ai_title

    meta["importance"] = score_importance(meta, facts, user["career_goal"])
    store.save(exp_id, markdown, meta, facts)

    # 검색 인덱스(청크+임베딩) 동기화는 별도 실패 지점으로 다룬다. 실측(2026-09-23):
    # Supabase 커넥션이 간헐적으로 끊기는데, 이걸 여기서 그냥 예외로 올리면 이미 끝난
    # analyze_folder·store.save 결과까지 통째로 날아가서 사용자가 LLM 분석을 처음부터
    # 다시 돌려야 했다. "파일/DB 저장 성공 뒤 임베딩만 실패했다면 전체가 성공했다고
    # 말하지 않고 검색 준비 중으로 표시한다"(SKIVE_NEXT_PLAN_DeepAgents_반영본.md, P1)를
    # 이제 지킨다 — 분석 결과는 살리고, 검색만 "동기화 필요" 상태로 남긴다.
    meta["chunks_synced"] = True
    try:
        from skive.chunks_store import sync_chunks

        sync_chunks(exp_id, root)
    except Exception as e:
        meta["chunks_synced"] = False
        meta["chunks_sync_error"] = str(e)[:300]
        store.save(exp_id, markdown, meta, facts)  # chunks_synced 상태까지 metadata.json에 남긴다

    return {"meta": meta, "markdown": markdown, "facts": facts, "skipped": skipped or []}


@app.post("/api/experiences/{exp_id}/sync-chunks")
def retry_sync_chunks(exp_id: str):
    """`_finish_ingest`에서 검색 인덱스 동기화가 실패했을 때 분석을 다시 안 돌리고
    이 부분만 재시도한다 (`skive sync-chunks` CLI와 같은 일을 HTTP로 노출)."""
    from skive.chunks_store import sync_chunks

    meta = store.get_meta(exp_id)
    if meta is None:
        raise HTTPException(404, f"존재하지 않는 경험 id: {exp_id}")
    try:
        n = sync_chunks(exp_id, Path(meta["raw_dir"]))
    except Exception as e:
        raise HTTPException(503, f"검색 인덱스 동기화 실패(DB 연결 확인 필요): {str(e)[:300]}")

    meta["chunks_synced"] = True
    meta.pop("chunks_sync_error", None)
    markdown, facts = store.get_markdown(exp_id), store.get_facts(exp_id)
    store.save(exp_id, markdown, meta, facts)
    return {"chunks_synced": True, "chunk_count": n}


# macOS/Windows가 압축 파일에 끼워 넣는 잡동사니. 실험 내용이 아니므로 분석에서 제외한다.
_ZIP_JUNK_NAMES = {"__macosx", ".ds_store", "thumbs.db", "desktop.ini"}
MAX_ZIP_TOTAL_BYTES = 200 * 1024 * 1024  # 압축 해제 후 총 용량 상한(zip bomb 방어)


@app.post("/api/experiences/upload-zip")
async def upload_experience_zip(
    id: str = Form(...),
    grade: int = Form(...),
    file: UploadFile = File(...),
):
    """폴더를 통째로 압축한 zip 파일 하나로 경험을 분석한다. 개별 파일을 일일이 드래그하기
    번거로운 큰 폴더(과제 모음 등)에 쓰라고 만들었다 — 압축을 푼 뒤에는 위 업로드와 완전히
    같은 경로(`_finish_ingest`)를 탄다.
    """
    import zipfile

    if not id.strip():
        raise HTTPException(400, "경험 id(폴더 이름)가 비어 있음")
    content = await file.read()
    if len(content) > MAX_UPLOAD_FILE_BYTES * 4:  # zip은 여러 파일을 담으니 개별 파일보다 넉넉히
        raise HTTPException(400, f"압축 파일이 너무 큼({len(content)//1024//1024}MB)")

    import io

    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        raise HTTPException(400, "올바른 zip 파일이 아님")

    infos = [i for i in zf.infolist() if not i.is_dir()]
    if len(infos) > MAX_UPLOAD_FILES:
        raise HTTPException(400, f"압축 안 파일이 너무 많음({len(infos)}개, 최대 {MAX_UPLOAD_FILES}개)")
    total_size = sum(i.file_size for i in infos)
    if total_size > MAX_ZIP_TOTAL_BYTES:
        raise HTTPException(400, f"압축 풀었을 때 총 용량이 너무 큼({total_size//1024//1024}MB)")

    exp_id = id
    root = store.DATA / "uploads" / exp_id
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)

    saved, skipped = [], []
    for info in infos:
        rel = Path(info.filename)
        if rel.name.lower() in _ZIP_JUNK_NAMES or any(p.lower() in _ZIP_JUNK_NAMES for p in rel.parts):
            continue
        # zip slip 방지: "../../etc/passwd" 같은 항목이 압축 안에 들어있으면 해제 대상 폴더
        # 밖으로 탈출할 수 있다. 압축 해제 라이브러리를 믿지 않고 직접 검사한다.
        if not rel.parts or ".." in rel.parts or rel.is_absolute():
            skipped.append({"name": info.filename, "reason": "허용되지 않는 경로"})
            continue
        dest = (root / rel).resolve()
        if not dest.is_relative_to(root.resolve()):
            skipped.append({"name": info.filename, "reason": "허용되지 않는 경로"})
            continue
        if info.file_size > MAX_UPLOAD_FILE_BYTES:
            skipped.append({"name": info.filename, "reason": f"{info.file_size//1024//1024}MB — 크기 제한 초과"})
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(zf.read(info))
        saved.append(str(rel))

    if not saved:
        shutil.rmtree(root, ignore_errors=True)
        raise HTTPException(400, f"압축 안에 저장할 수 있는 파일이 없음 — 제외된 파일: {skipped}")

    return _finish_ingest(exp_id, root, grade, skipped)


# ---------------- 업로드 직후 인터뷰 ----------------
#
# 사용자 피드백(2026-09-23): "원본에 명시된 것만 본인 역할로 인정"하는 기준이 실제로는
# 너무 빡빡하다 — 강의 PDF나 팀 코드에는 "이건 내가 했다"는 문구가 애초에 잘 없다.
# 그렇다고 "업로드했으면 다 내가 한 걸로 치자"로 바꾸면, 팀 코드 저장소를 통째로 올렸을 때
# 팀원이 짠 부분까지 전부 본인 것으로 뭉개는 정반대 문제가 생긴다(F01이 막으려던 것과 같은
# 종류의 왜곡). 그래서 "원본 문서 근거"의 엄격함은 그대로 두고, 대신 업로드 직후 몇 가지를
# 직접 물어봐서 사용자가 스스로 말한 내용을 [본인 진술]로 명시적으로 기록하는 통로를 연다 —
# corrections.py의 기존 정정 파이프라인을 그대로 재사용해서, quote 없이도 [본인 진술, 원문
# 근거 없음]으로 늘 정직하게 표시된다(F01 불변식 유지: 상속 금지·승격 금지).
# 사용자 피드백(2026-09-23, 후속): "질문이 좀 많았다." 4개(역할/성과/배운점/자유)를 2개로
# 줄였다 — 배운점과 자유 코멘트를 하나로 합치고, 그마저도 선택사항이라고 명시한다.
STANDARD_INTAKE_QUESTIONS = [
    {"target": "my_role", "question": "이 경험에서 본인 역할이 정확히 뭐였나요?"},
    {"target": "result", "question": "구체적으로 어떤 성과를 냈나요? (수치가 있으면 함께, 모르면 비워두세요)"},
    {"target": "lessons", "question": "(선택) 배운 점이나 더 알려줄 게 있으면 자유롭게"},
]


class IntakeAnswer(BaseModel):
    question: str
    answer: str
    target: Literal["my_role", "action", "decision", "result", "lessons"]


class IntakeRequest(BaseModel):
    answers: list[IntakeAnswer]


# 사용자 피드백(2026-09-23, 후속): "팀 활동으로 기록된 것 중에 사실 본인이 주도한 부분이
# 있을 수 있다 — 있으면 물어보고, 사용자가 확인하면(왜/어떤 기준으로 했는지까지 물어서)
# [본인 진술]로 적어주자." AI가 알아서 "업로드했으니 네 것"이라고 추측하는 건 여전히 안
# 한다 — 자료에 기록된 사실을 사용자에게 보여주고, 답은 사용자가 한다.
# 처음엔 3개까지 물어봤는데 "질문이 많았다"는 피드백을 받고 1개로 줄였다 — 가장 비중 큰
# 사실(문장이 가장 긴 것) 하나만 확인 질문으로 올린다.
MAX_OWNERSHIP_PROMPTS = 1


def _ownership_check_questions(facts: dict) -> list[dict]:
    from skive import facts as facts_v2

    bucket_to_target = {"decisions": "decision", "actions": "action", "results": "result"}
    all_team = [
        (key, f) for key in bucket_to_target
        for f in facts.get(key, [])
        if f.get("owner") == "팀" and facts_v2.lifecycle(f) == facts_v2.ACTIVE
    ]
    # 1개로 줄인 뒤에는 "가장 비중 있어 보이는" 걸 물어보는 게 낫다 — 문장 길이를
    # 대략적인 대리 지표로 쓴다(정교하진 않지만, 순서상 첫 번째보다는 낫다).
    candidates = sorted(all_team, key=lambda kf: -len(kf[1]["text"]))[:MAX_OWNERSHIP_PROMPTS]
    return [
        {
            "target": bucket_to_target[key],
            "question": (
                f"자료에는 팀 활동으로 기록돼 있어요: \"{f['text']}\" — 혹시 이 부분을 "
                "본인이 직접 주도했나요? 그렇다면 어떤 생각·판단 기준으로 하셨는지도 같이 알려주세요."
            ),
        }
        for key, f in candidates
    ]


@app.get("/api/experiences/{exp_id}/intake-questions")
def get_intake_questions(exp_id: str):
    """업로드 직후 보여줄 질문 목록. 표준 질문 + 분석 중 못 채운 open_questions +
    팀 활동으로 기록된 것 중 본인 주도 여부 확인 질문을 합친다."""
    meta = store.get_meta(exp_id)
    facts = store.get_facts(exp_id)
    if meta is None:
        raise HTTPException(404, f"존재하지 않는 경험 id: {exp_id}")
    # "역할"을 이미 표준 질문으로 물어보므로, 분석기가 만든 open_questions 중 같은 주제를
    # 또 물으면 중복이다("질문이 많았다" 피드백 이후 최대한 줄인다). 최대 1개만 더 보탠다.
    extra_raw = [q for q in (meta.get("open_questions") or []) if "역할" not in q]
    extra = [{"target": "action", "question": q} for q in extra_raw[:1]]
    ownership = _ownership_check_questions(facts or {})
    return {"questions": STANDARD_INTAKE_QUESTIONS + ownership + extra}


@app.post("/api/experiences/{exp_id}/intake")
def submit_intake(exp_id: str, req: IntakeRequest):
    """인터뷰 답변을 사실로 기록한다. 각 답변은 corrections.apply_correction()을 그대로
    타므로, my_role/lessons는 [본인 진술]로 덮어쓰고 나머지는 새 사실로 추가되며, 전부
    provenance_type=user_statement로 표시된다 — 검증된 문서 근거와 절대 안 섞인다."""
    from skive.corrections import apply_correction
    from skive.models import CorrectionProposal

    if store.get_meta(exp_id) is None:
        raise HTTPException(404, f"존재하지 않는 경험 id: {exp_id}")

    applied = []
    result = None
    for a in req.answers:
        text = a.answer.strip()
        if not text:
            continue
        if a.target in ("my_role", "lessons"):
            facts = store.get_facts(exp_id)
            original = facts.get(a.target, "") if a.target == "lessons" else facts.get("my_role", "")
            proposal = CorrectionProposal(
                is_correction=True, kind="correction", experience_id=exp_id,
                field=a.target, original_text=original, corrected_text=text,
                reason=f"업로드 직후 인터뷰: {a.question}",
            )
        else:
            proposal = CorrectionProposal(
                is_correction=True, kind="new_fact", experience_id=exp_id,
                field=a.target, original_text="", corrected_text=text,
                reason=f"업로드 직후 인터뷰: {a.question}",
            )
        try:
            result = apply_correction(proposal)
            applied.append(a.target)
        except ValueError as e:
            raise HTTPException(400, f"'{a.question}' 답변 반영 실패: {e}")

    if result is None:
        result = {
            "meta": store.get_meta(exp_id), "facts": store.get_facts(exp_id),
            "markdown": store.get_markdown(exp_id),
        }
    return {"applied": applied, **result}


# ---------------- profile ----------------


@app.get("/api/profile")
def get_profile_api():
    return {"markdown": store.get_profile_markdown(), "json": store.get_profile_json()}


@app.post("/api/profile/rebuild")
def rebuild_profile():
    markdown, profile = build_profile()
    store.save_profile(markdown, profile)
    return {"markdown": markdown, "json": profile}


# ---------------- jobs (공고) ----------------


def _job_id_from_filename(path: Path) -> str:
    return path.stem.removeprefix("apply_")


@app.get("/api/jobs")
def list_jobs():
    if not OUTPUT_DIR.exists():
        return []
    jobs = []
    for path in sorted(OUTPUT_DIR.glob("apply_*.json")):
        result = json.loads(path.read_text(encoding="utf-8"))
        job = result["job"]
        jobs.append(
            {
                "id": _job_id_from_filename(path),
                "company": job["company"],
                "role": job["role"],
                "status": "분석완료",
                "key_competencies": job["key_competencies"],
                "questions_for_user": result["questions_for_user"],
            }
        )
    return jobs


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    path = OUTPUT_DIR / f"apply_{job_id}.json"
    if not path.is_file():
        raise HTTPException(404, f"존재하지 않는 공고 id: {job_id}")
    return json.loads(path.read_text(encoding="utf-8"))


class JobRequest(BaseModel):
    id: str | None = None
    text: str | None = None
    url: str | None = None
    values_text: str | None = None
    values_url: str | None = None
    reference_text: str | None = None
    essay_questions: list[str] | None = None


def _slugify(text: str) -> str:
    # 회사명이 한글뿐이면 ASCII만 남기는 슬러그가 전부 "job"으로 뭉개져서 서로 덮어쓰게 됨 —
    # 그 경우엔 타임스탬프를 붙여 최소한 겹치지 않게 한다.
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return slug or f"job_{int(time.time()*1000)}"


def _save_job_result(job_id: str, result: dict) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / f"apply_{job_id}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )


@app.post("/api/jobs")
def create_job(req: JobRequest):
    """공고 원문/URL/인재상/참고자료를 합쳐 분석 → 매칭 → 자소서 초안까지 동기 실행.
    LLM 호출 여러 번 + URL을 주면 fetch까지 해서 느릴 수 있다."""
    parts = []
    if req.text:
        parts.append(f"[공고 원문]\n{req.text}")
    if req.url:
        try:
            parts.append(f"[공고 URL: {req.url}]\n{fetch_url_text(req.url)}")
        except Exception as e:
            raise HTTPException(400, f"공고 URL을 가져오지 못했습니다: {e}")
    if req.values_text:
        parts.append(f"[인재상 - 직접입력]\n{req.values_text}")
    if req.values_url:
        try:
            parts.append(f"[인재상 URL: {req.values_url}]\n{fetch_url_text(req.values_url)}")
        except Exception as e:
            raise HTTPException(400, f"인재상 URL을 가져오지 못했습니다: {e}")
    if req.reference_text:
        parts.append(f"[참고자료]\n{req.reference_text}")
    if not parts:
        raise HTTPException(400, "공고 원문, URL, 참고자료 중 최소 하나는 입력해야 합니다")

    essay_questions = [q for q in (req.essay_questions or []) if q.strip()] or None
    result = run_apply("\n\n".join(parts), override_questions=essay_questions)
    job_id = req.id or _slugify(result["job"]["company"])
    _save_job_result(job_id, result)
    return {"id": job_id, **result}


@app.post("/api/extract-file")
async def extract_file(file: UploadFile = File(...)):
    """직무기술서/참고자료로 올린 PDF나 이미지에서 텍스트를 뽑아 돌려준다.
    바로 저장하지 않는다 — 프론트에서 사용자가 확인·수정한 뒤 /api/jobs에 넣는다."""
    content = await file.read()
    suffix = Path(file.filename or "").suffix.lower()
    if suffix == ".pdf":
        import io

        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(content))
        text = "\n".join((page.extract_text() or "") for page in reader.pages).strip()
    elif suffix in (".jpg", ".jpeg", ".png"):
        b64 = base64.b64encode(content).decode()
        mime = "image/png" if suffix == ".png" else "image/jpeg"
        message = HumanMessage(
            content=[
                {"type": "text", "text": "이 이미지에 있는 텍스트를 그대로 옮겨 적어라. 설명하지 말고 텍스트만 출력해라."},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
            ]
        )
        from skive.llm import get_llm

        text = get_llm().invoke([message]).content.strip()
    else:
        raise HTTPException(400, f"지원하지 않는 파일 형식: {suffix or '(확장자 없음)'}")
    if not text:
        raise HTTPException(400, "파일에서 텍스트를 추출하지 못했습니다")
    return {"filename": file.filename, "text": text}


class ReviseRequest(BaseModel):
    message: str


@app.post("/api/jobs/{job_id}/answers/{index}/revise")
def revise_job_answer(job_id: str, index: int, req: ReviseRequest):
    """자소서 초안을 채팅하듯 계속 고쳐 쓴다. 같은 근거 자료 범위 안에서만 반영된다."""
    path = OUTPUT_DIR / f"apply_{job_id}.json"
    if not path.is_file():
        raise HTTPException(404, f"존재하지 않는 공고 id: {job_id}")
    result = json.loads(path.read_text(encoding="utf-8"))
    answers = result["answers"]
    if index < 0 or index >= len(answers):
        raise HTTPException(404, f"존재하지 않는 문항 인덱스: {index}")

    job = JobRequirements.model_validate(result["job"])
    answer = answers[index]
    qp = QuestionPlan(
        question=answer["question"],
        experience_ids=answer["experience_ids"],
        angle=answer["angle"],
        gap=answer["gap"] or "",
    )
    revised = revise_answer(job, qp, answer["draft"], req.message)

    answer["draft"] = revised["draft"]
    answer["status"] = revised["status"]
    answer["issues"] = revised["issues"]
    answer["removed"] = answer.get("removed", []) + revised["removed"]
    answer["attempts"] = answer.get("attempts", 0) + 1
    answer.setdefault("revisions", []).append({"message": req.message, "draft": revised["draft"]})

    answers[index] = answer
    _save_job_result(job_id, result)
    return {"answer": answer}


# ---------------- study ----------------


@app.get("/api/study")
def get_study_list():
    return list_study()


@app.get("/api/study/{study_id}")
def get_study_detail(study_id: str):
    path = STUDY_DIR / study_id / "summary.md"
    if not path.is_file():
        raise HTTPException(404, f"존재하지 않는 공부 기록 id: {study_id}")
    meta = next((m for m in list_study() if m["id"] == study_id), None)
    return {"meta": meta, "summary": path.read_text(encoding="utf-8")}


# ---------------- chat ----------------

# 세션 하나가 어느 scope로 시작됐는지 기억해서, 같은 session_id로 다른 scope_id를
# 보내는 걸 막는다(R08). 대화 메시지 자체는 skive.chat.CHECKPOINTER가 디스크에 저장하지만,
# 이 매핑은 지금은 프로세스 메모리에만 있다 — 서버 재시작하면 사라진다. 그 경우 최악의
# 결과는 "스코프 고정이 풀린다"이지 데이터가 새는 게 아니라서(체크포인터 자체는 세션별로
# 분리돼 있음) Stage 1 이전까지는 이 정도로 둔다.
_SESSION_SCOPES: dict[str, str | None] = {}


class ChatTurn(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str
    scope_id: str | None = None
    session_id: str | None = None
    # 레거시 필드. session_id를 보내면 무시된다 — 서버가 저장한 대화가 신뢰 원본이다.
    # session_id가 없는 옛날 프론트엔드 호출까지는 이걸로 이전처럼 동작하게 해준다.
    history: list[ChatTurn] = []


def _to_lc_messages(history: list[ChatTurn]) -> list:
    return [HumanMessage(t.content) if t.role == "user" else AIMessage(t.content) for t in history]


def _to_turns(messages: list) -> list[dict]:
    turns = []
    for m in messages:
        if m.type == "human":
            turns.append({"role": "user", "content": m.content})
        elif m.type == "ai" and m.content:
            turns.append({"role": "assistant", "content": m.content})
    return turns


@app.post("/api/chat")
def chat_api(req: ChatRequest):
    from skive.chat import ask_in_session, ask_once, build_chat_graph
    from skive.context import new_context
    from skive.corrections import detect_correction

    if req.session_id is None:
        # 옛 프론트엔드 호환 경로: 매 요청마다 클라이언트가 보낸 history로 무상태 실행.
        # 새 프론트엔드는 항상 session_id를 보내므로 이 분기는 점점 안 쓰이게 된다.
        graph = build_chat_graph(scope_id=req.scope_id)
        messages, answer = ask_once(graph, _to_lc_messages(req.history), req.message)
        session_id = None
    else:
        session_id = req.session_id
        pinned = _SESSION_SCOPES.get(session_id, req.scope_id)
        if pinned != req.scope_id:
            raise HTTPException(
                400,
                f"이 세션은 '{pinned}' 범위로 시작됐습니다. 범위를 바꾸려면 새 세션을 시작하세요.",
            )
        _SESSION_SCOPES[session_id] = req.scope_id
        ctx = new_context(session_id=session_id, active_scope_id=req.scope_id)
        messages, answer = ask_in_session(ctx, req.message)

    proposal = detect_correction(req.message, scope_id=req.scope_id)
    return {
        "answer": answer,
        "session_id": session_id,
        "history": _to_turns(messages),
        "correction": proposal.model_dump() if proposal else None,
    }


@app.post("/api/chat/sessions")
def new_chat_session(scope_id: str | None = None):
    """프론트엔드가 대화를 시작할 때(또는 scope를 바꿀 때) 새 session_id를 받아간다."""
    session_id = f"chat-{uuid.uuid4().hex[:16]}"
    _SESSION_SCOPES[session_id] = scope_id
    return {"session_id": session_id, "scope_id": scope_id}


class CorrectionConfirmRequest(BaseModel):
    kind: Literal["correction", "new_fact"] = "correction"
    experience_id: str
    field: Literal["my_role", "action", "decision", "result", "lessons"]
    original_text: str = ""
    corrected_text: str
    reason: str = ""
    accept: bool


@app.post("/api/corrections/confirm")
def confirm_correction(req: CorrectionConfirmRequest):
    """챗봇이 띄운 정정/새 사실 확인 카드에 대한 사용자 응답. accept=false면 아무것도 바꾸지 않는다."""
    from skive.corrections import apply_correction
    from skive.models import CorrectionProposal

    if not req.accept:
        return {"applied": False}
    proposal = CorrectionProposal(
        is_correction=True,
        kind=req.kind,
        experience_id=req.experience_id,
        field=req.field,
        original_text=req.original_text,
        corrected_text=req.corrected_text,
        reason=req.reason,
    )
    try:
        result = apply_correction(proposal)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"applied": True, **result}


@app.get("/api/experiences/{exp_id}/corrections")
def get_experience_corrections(exp_id: str):
    from skive.corrections import get_corrections

    if store.get_meta(exp_id) is None:
        raise HTTPException(404, f"존재하지 않는 경험 id: {exp_id}")
    return get_corrections(exp_id)


class ChatEndRequest(BaseModel):
    chat_session_id: str | None = None  # /api/chat이 돌려준 session_id — 있으면 이걸 신뢰
    history: list[ChatTurn] = []  # chat_session_id가 없는 레거시 호출용 폴백


@app.post("/api/chat/end")
def chat_end(req: ChatEndRequest):
    """대화를 마치고 조건을 넘기면 공부 기록으로 저장한다 (skive/chat.py run_chat과 동일 규칙).

    `chat_session_id`가 있으면 클라이언트가 보낸 history를 안 쓰고 서버가 실제로 기록해 둔
    대화(checkpointer)를 읽는다 — 클라이언트가 대화 내용을 조작해서 만들어내지 않은
    기록만 공부 기록으로 남기려는 것.
    """
    from datetime import datetime

    from skive.chat import MIN_USER_TURNS, _transcript, get_session_messages
    from skive.study import summarize_session

    if req.chat_session_id:
        messages = get_session_messages(req.chat_session_id)
        if sum(1 for m in messages if m.type == "human") < MIN_USER_TURNS:
            return None
        transcript = _transcript(messages)
        _SESSION_SCOPES.pop(req.chat_session_id, None)
    else:
        if sum(1 for t in req.history if t.role == "user") < MIN_USER_TURNS:
            return None
        transcript = "\n".join(
            f"나: {t.content}" if t.role == "user" else f"SKIVE: {t.content}" for t in req.history
        )

    session_id = "study-" + datetime.now().strftime("%Y%m%d-%H%M%S")
    return summarize_session(transcript, session_id)


# Must stay last: anything not matched above is the web app.
if WEB_OUT.is_dir():
    app.mount("/", StaticFiles(directory=WEB_OUT, html=True), name="web")
