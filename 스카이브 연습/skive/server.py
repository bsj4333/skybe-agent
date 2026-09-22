"""SKIVE 로컬 웹서버. `uv run uvicorn skive.server:app --reload` 로 실행.

CLI(skive/cli.py)가 하던 일(ingest, profile, apply, chat)을 HTTP로 노출한다.
목업 UI(ui_mockup/skive_ui.html)를 실제 데이터에 연결하기 위한 첫 백엔드 뼈대.
"""

import base64
import json
import re
import time
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel

from skive import store
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

app = FastAPI(title="SKIVE")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def index():
    if not UI_MOCKUP.is_file():
        raise HTTPException(404, "UI mockup not found")
    return FileResponse(UI_MOCKUP)


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


class IngestRequest(BaseModel):
    folder: str
    grade: int
    id: str | None = None


@app.post("/api/experiences")
def ingest_experience(req: IngestRequest):
    """폴더 하나를 동기적으로 분석해 저장한다. LLM 호출 때문에 응답까지 시간이 걸릴 수 있다.

    TODO: 백그라운드 잡 + 진행상황 폴링/SSE로 바꾸기 (PROJECT_STATUS.md 우선순위 A-4).
    """
    user = load_user()
    root = Path(req.folder)
    if not root.is_dir():
        raise HTTPException(400, f"폴더를 찾을 수 없음: {req.folder}")
    exp_id = req.id or root.name
    markdown, meta, facts = analyze_folder(root, user["name"], exp_id, req.grade)
    meta["importance"] = score_importance(meta, facts, user["career_goal"])
    store.save(exp_id, markdown, meta, facts)
    from skive.chunks_store import sync_chunks

    sync_chunks(exp_id, root)
    return {"meta": meta, "markdown": markdown, "facts": facts}


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


class ChatTurn(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatTurn] = []
    scope_id: str | None = None


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
    from skive.chat import ask_once, build_chat_graph
    from skive.corrections import detect_correction

    graph = build_chat_graph(scope_id=req.scope_id)
    messages, answer = ask_once(graph, _to_lc_messages(req.history), req.message)
    proposal = detect_correction(req.message, scope_id=req.scope_id)
    return {
        "answer": answer,
        "history": _to_turns(messages),
        "correction": proposal.model_dump() if proposal else None,
    }


class CorrectionConfirmRequest(BaseModel):
    kind: Literal["correction", "new_fact"] = "correction"
    experience_id: str
    field: Literal["my_role", "action", "decision", "result"]
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
    history: list[ChatTurn]


@app.post("/api/chat/end")
def chat_end(req: ChatEndRequest):
    """대화를 마치고 조건을 넘기면 공부 기록으로 저장한다 (skive/chat.py run_chat과 동일 규칙)."""
    from datetime import datetime

    from skive.chat import MIN_USER_TURNS
    from skive.study import summarize_session

    user_turns = sum(1 for t in req.history if t.role == "user")
    if user_turns < MIN_USER_TURNS:
        return None
    transcript = "\n".join(
        f"나: {t.content}" if t.role == "user" else f"SKIVE: {t.content}" for t in req.history
    )
    session_id = "study-" + datetime.now().strftime("%Y%m%d-%H%M%S")
    return summarize_session(transcript, session_id)
