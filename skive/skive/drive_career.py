"""Account-wide career memory and per-posting conversations.

The conversation may reuse a user's own drafts for wording. Drafts and user
statements are never presented as documentary proof of a career claim.
"""

import json
import re
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, field_validator

from skive.drive_auth import current_user_id
from skive.drive_db import user_connection
from skive.drive_workspace import _keywords, _profile, _source_text, _sources
from skive.llm import get_essay_llm

router = APIRouter(prefix="/api/career", tags=["career"])


class MemoryCreate(BaseModel):
    content: str = Field(min_length=2, max_length=4000)
    activity_id: UUID | None = None

    @field_validator("content")
    @classmethod
    def nonempty_content(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("경험 내용을 입력해 주세요")
        return value


class JobCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    job_text: str = Field(default="", max_length=20000)
    job_url: str = Field(default="", max_length=2000)
    values_url: str = Field(default="", max_length=2000)
    questions: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("title")
    @classmethod
    def nonempty_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("공고 이름을 입력해 주세요")
        return value

    @field_validator("job_url", "values_url")
    @classmethod
    def safe_link(cls, value: str) -> str:
        value = value.strip()
        if value and not value.startswith("https://"):
            raise ValueError("공개 HTTPS 링크만 입력해 주세요")
        return value


class JobTurn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    essay_id: UUID | None = None
    answer_pending: bool = False

    @field_validator("message")
    @classmethod
    def nonempty_message(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("메시지를 입력해 주세요")
        return value


class CareerReply(BaseModel):
    action: Literal["discuss", "ask", "draft"]
    answer: str
    question: str = ""
    draft: str = ""


class DraftRepair(BaseModel):
    draft: str


def _job(conn, job_id: UUID):
    row = conn.execute("select * from skive.drive_job_workspaces where id=%s", (job_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "공고를 찾을 수 없습니다")
    return row


def _essay(conn, job_id: UUID, essay_id: UUID | None):
    if essay_id is None:
        return None
    row = conn.execute(
        "select * from skive.drive_essays where id=%s and job_workspace_id=%s",
        (essay_id, job_id),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "이 공고의 문항을 찾을 수 없습니다")
    return row


@router.get("/memory")
def list_memory(user_id: UUID = Depends(current_user_id)):
    with user_connection(user_id) as conn:
        return conn.execute(
            "select id,activity_id,content,provenance,status,source_file_id,source_location,"
            "created_at from skive.drive_memory_claims order by updated_at desc limit 200"
        ).fetchall()


@router.post("/memory", status_code=201)
def add_memory(body: MemoryCreate, user_id: UUID = Depends(current_user_id)):
    with user_connection(user_id) as conn:
        if body.activity_id and not conn.execute(
            "select 1 from skive.drive_activities where id=%s", (body.activity_id,)
        ).fetchone():
            raise HTTPException(404, "활동을 찾을 수 없습니다")
        return conn.execute(
            "insert into skive.drive_memory_claims(user_id,activity_id,content,provenance,status) "
            "values (%s,%s,%s,'user_statement','user_confirmed') "
            "returning id,activity_id,content,provenance,status,created_at",
            (user_id, body.activity_id, body.content.strip()),
        ).fetchone()


@router.get("/jobs")
def list_jobs(user_id: UUID = Depends(current_user_id)):
    with user_connection(user_id) as conn:
        return conn.execute(
            "select j.id,j.title,j.job_url,j.updated_at,count(e.id)::int as question_count "
            "from skive.drive_job_workspaces j left join skive.drive_essays e "
            "on e.job_workspace_id=j.id group by j.id order by j.updated_at desc limit 100"
        ).fetchall()


@router.post("/jobs", status_code=201)
def create_job(body: JobCreate, user_id: UUID = Depends(current_user_id)):
    questions = [item.strip() for item in body.questions if item.strip()]
    if len(questions) != len(set(questions)):
        raise HTTPException(422, "같은 문항이 중복됐습니다")
    with user_connection(user_id) as conn:
        job = conn.execute(
            "insert into skive.drive_job_workspaces(user_id,title,job_text,job_url,values_url) "
            "values (%s,%s,%s,%s,%s) returning *",
            (user_id, body.title.strip(), body.job_text, body.job_url, body.values_url),
        ).fetchone()
        for question in questions:
            conn.execute(
                "insert into skive.drive_essays(user_id,job_workspace_id,job_text,question,draft) "
                "values (%s,%s,%s,%s,'')",
                (user_id, job["id"], body.job_text, question),
            )
        return {**job, "questions": questions}


@router.get("/jobs/{job_id}")
def get_job(job_id: UUID, user_id: UUID = Depends(current_user_id)):
    with user_connection(user_id) as conn:
        job = _job(conn, job_id)
        essays = conn.execute(
            "select id,question,draft,citations,review_status,revision_count,updated_at "
            "from skive.drive_essays where job_workspace_id=%s order by created_at,id",
            (job_id,),
        ).fetchall()
        messages = conn.execute(
            "select id,role,content,references_json,created_at from skive.drive_job_messages "
            "where job_workspace_id=%s order by id", (job_id,),
        ).fetchall()
        return {**job, "essays": essays, "messages": messages}


@router.get("/jobs/{job_id}/essays/{essay_id}/versions")
def essay_versions(job_id: UUID, essay_id: UUID, user_id: UUID = Depends(current_user_id)):
    with user_connection(user_id) as conn:
        _job(conn, job_id)
        _essay(conn, job_id, essay_id)
        return conn.execute(
            "select revision_no,draft,citations,created_at from skive.drive_essay_versions "
            "where essay_id=%s order by revision_no desc limit 30", (essay_id,),
        ).fetchall()


def _past_essays(conn, job_id: UUID, question: str, message: str):
    terms = _keywords(question + " " + message)
    request_previous = any(word in message for word in ("이전 자소서", "전에 쓴", "예전 자소서", "지난 자소서"))
    if request_previous:
        return conn.execute(
            "select e.id,e.question,left(e.draft,3000) as draft,j.title as job_title "
            "from skive.drive_essays e left join skive.drive_job_workspaces j "
            "on j.id=e.job_workspace_id where e.job_workspace_id is distinct from %s "
            "and e.draft<>'' order by e.updated_at desc limit 4", (job_id,),
        ).fetchall()
    if not terms:
        return []
    patterns = [f"%{word.replace('%', '').replace('_', '')}%" for word in terms[:5]]
    where = " or ".join("(e.question ilike %s or e.draft ilike %s)" for _ in patterns)
    return conn.execute(
        "select e.id,e.question,left(e.draft,3000) as draft,j.title as job_title "
        "from skive.drive_essays e left join skive.drive_job_workspaces j "
        "on j.id=e.job_workspace_id where e.job_workspace_id is distinct from %s "
        "and e.draft<>'' and (" + where + ") order by e.updated_at desc limit 4",
        (job_id, *(value for pattern in patterns for value in (pattern, pattern))),
    ).fetchall()


def _memory(conn, terms: list[str]):
    if not terms:
        return []
    patterns = [f"%{term.replace('%', '').replace('_', '')}%" for term in terms[:6]]
    where = " or ".join("content ilike %s" for _ in patterns)
    matches = conn.execute(
        "select id,content,provenance,status from skive.drive_memory_claims "
        "where status='user_confirmed' and (" + where + ") order by updated_at desc limit 12", patterns,
    ).fetchall()
    recent = conn.execute(
        "select id,content,provenance,status from skive.drive_memory_claims "
        "where status='user_confirmed' order by updated_at desc limit 4"
    ).fetchall()
    return list({row["id"]: row for row in [*matches, *recent]}.values())[:12]


def _career_response(context: dict, *, runtime=None) -> CareerReply:
    if runtime is not None:
        from skive.drive_orchestrator import run_career_orchestrator
        conn, job_id, sources, memories, past, reviewed = runtime
        return run_career_orchestrator(conn, context, job_id, sources, memories, past,
                                       CareerReply, reviewed)
    return get_essay_llm().with_structured_output(CareerReply).invoke([
        SystemMessage(
            "너는 SKIVE 계정의 커리어 대화 오케스트레이터다. 문항과 대화 목적을 파악해 "
            "discuss(답변), ask(사용자에게 확인 질문), draft(초안 또는 수정안) 중 선택한다. "
            "드라이브 원문은 파일 근거이고, 사용자 확인 진술은 본인 진술이며, 이전 자소서는 "
            "표현·구성 참고자료일 뿐 사실 증거가 아니다. 세 범주를 절대 혼동하지 마라. "
            "자료에 없거나 원본과 이전 자소서가 충돌하는 본인 역할·성과는 삭제하거나 단정하지 말고 "
            "구체적인 한 가지 확인 질문을 하라. 질문할 때 action=ask, question에 질문을 적는다. "
            "초안을 요청받았고 본인 역할 근거가 충분하면 action=draft, draft에 문항의 전체 초안을 적는다. "
            "검증되지 않은 성과 수치·자격증은 쓰지 마라. 파일 사실 문장에는 [파일 1]처럼 근거를 붙인다. "
            "본인 진술을 쓴 문장에는 [본인 진술]을 표시한다. 이전 글의 표현을 차용하면 답변에서 밝힌다. "
            "사용자 검토를 마친 활동 사실은 출처 파일과 확인 메모를 함께 보고 [활동 사실 N]으로 인용한다. "
            "그 사실의 주체가 팀이나 프로젝트라면 본인 단독 성과로 바꾸지 마라. "
            "질문에 답할 때는 answer를, 초안을 쓸 때도 변경 이유를 answer에 간결하게 적는다."
        ),
        HumanMessage(json.dumps(context, ensure_ascii=False, default=str)),
    ])


def _draft_gap(draft: str, sources: list[dict], memories: list[dict],
               reviewed: list[dict] | None = None) -> str:
    """Find obvious citation or numeric gaps before persisting a generated draft."""
    reviewed = reviewed or []
    has_reviewed_label = bool(re.search(r"\[활동 사실\s*\d+\]", draft))
    if memories and not sources and not reviewed and "[본인 진술]" not in draft:
        return "초안이 본인 진술을 사용했지만 표시하지 않았어요. 어떤 문장이 본인 진술에 근거하나요?"
    if reviewed and not sources and not memories and not has_reviewed_label:
        return "확인된 활동 사실을 썼다면 [활동 사실 N] 출처를 표시해 주세요."
    if sources and not re.search(r"\[파일\s*\d+\]", draft) and not has_reviewed_label and "[본인 진술]" not in draft:
        return "초안에 파일 또는 본인 진술의 근거 표시가 없어요. 어떤 자료를 근거로 쓸까요?"
    available = {str(source["index"]) for source in sources}
    cited = set(re.findall(r"\[파일\s*(\d+)\]", draft))
    missing = cited - available
    if missing:
        return f"초안의 파일 인용 {', '.join(sorted(missing))}번을 이번에 확인한 원문에서 찾지 못했어요. 어떤 자료를 근거로 쓰면 될까요?"
    reviewed_ids = {str(fact["index"]) for fact in reviewed}
    missing_reviewed = set(re.findall(r"\[활동 사실\s*(\d+)\]", draft)) - reviewed_ids
    if missing_reviewed:
        return "초안의 활동 사실 인용을 이번에 확인한 사실 목록에서 찾지 못했어요. 다시 선택해 주세요."
    without_citations = re.sub(r"\[(?:파일|활동 사실)\s*\d+\]", "", draft)
    evidence = "\n".join([*(source.get("excerpt", "") for source in sources),
                            *(fact.get("content", "") for fact in memories),
                            *(fact.get("content", "") for fact in reviewed),
                            *(fact.get("review_note", "") for fact in reviewed)])
    numbers = set(re.findall(r"\d+(?:\.\d+)?%?", without_citations))
    unsupported = [number for number in sorted(numbers) if number not in evidence]
    if unsupported:
        return f"초안의 수치 {', '.join(unsupported[:5])}에 대한 원본 또는 본인 확인 내용을 찾지 못했어요. 이 수치는 무엇을 뜻하고 누가 달성했나요?"
    return ""


def _repair_missing_attribution(draft: str, sources: list[dict], memories: list[dict]) -> str:
    """One bounded attempt to add missing attribution without changing the facts."""
    needs_user_label = memories and not sources and "[본인 진술]" not in draft
    needs_file_label = sources and "[파일" not in draft and "[본인 진술]" not in draft
    if not (needs_user_label or needs_file_label):
        return draft
    try:
        repaired = get_essay_llm().with_structured_output(DraftRepair).invoke([
            SystemMessage(
                "자소서 초안의 출처 표시만 보완한다. 사실·수치·주체·문장 내용은 바꾸거나 추가하지 마라. "
                "사용자가 확인한 진술에 의존한 문장에는 [본인 진술]을 붙인다. "
                "파일 내용에 의존한 문장에는 실제 파일 번호 [파일 N]을 붙인다. "
                "적합한 근거가 없는 문장은 출처 표시를 지어내지 마라."
            ),
            HumanMessage(json.dumps({"draft": draft, "files": sources,
                                     "user_statements": memories}, ensure_ascii=False, default=str)),
        ])
        candidate = repaired.draft.strip()
        remove_labels = lambda value: re.sub(r"\s+", "", re.sub(r"\[(?:파일\s*\d+|본인 진술)\]", "", value))
        return candidate if candidate and remove_labels(candidate) == remove_labels(draft) else draft
    except Exception:
        return draft


@router.post("/jobs/{job_id}/messages")
def send_job_message(job_id: UUID, body: JobTurn, user_id: UUID = Depends(current_user_id)):
    from skive.drive_reviewed_retrieval import reviewed_facts
    with user_connection(user_id) as conn:
        job = _job(conn, job_id)
        essay = _essay(conn, job_id, body.essay_id)
        prior = conn.execute(
            "select role,content from skive.drive_job_messages where job_workspace_id=%s "
            "order by id desc limit 10", (job_id,),
        ).fetchall()[::-1]
        profile = _profile(conn, user_id)
        if body.answer_pending:
            if not job["pending_question"]:
                raise HTTPException(409, "대기 중인 확인 질문이 없습니다")
            claim = conn.execute(
                "insert into skive.drive_memory_claims(user_id,content,provenance,status) "
                "values (%s,%s,'user_statement','user_confirmed') returning id,content,provenance,status",
                (user_id, f"{job['title'][:200]} · {(essay['question'] if essay else '')[:200]} · "
                 f"{job['pending_question'][:200]} — {body.message.strip()[:3300]}"),
            ).fetchone()
            conn.execute("update skive.drive_job_workspaces set pending_question='' where id=%s", (job_id,))
            reply = CareerReply(action="discuss", answer="답변을 본인 진술로 저장했어요. 원본으로 확인된 사실과 구분해서 이후 공고에서도 참고할게요. 이어서 초안 작성을 요청해 주세요.")
            sources, memories, past, reviewed = [], [claim], [], []
        else:
            target = " ".join([job["title"], job["job_text"][:600], essay["question"] if essay else "", body.message])
            terms = _keywords(target)
            sources = _sources(conn, target, None, limit=12, terms=terms)
            memories = _memory(conn, terms)
            past = _past_essays(conn, job_id, essay["question"] if essay else "", body.message)
            reviewed = reviewed_facts(conn, terms, limit=12)
            context = {
                "job": {"title": job["title"], "posting": job["job_text"], "url": job["job_url"], "values_url": job["values_url"]},
                "selected_question": essay["question"] if essay else "선택 안 됨",
                "current_draft": essay["draft"] if essay else "",
                "profile_user_statement": profile,
                "writing_style": profile.get("essay_style") or "간결하고 구체적으로 작성",
                "recent_job_conversation": prior,
                "request": body.message,
                "drive_file_evidence": _source_text(sources),
                "confirmed_user_statements_not_document_evidence": memories,
                "past_essays_for_wording_only": past,
                "human_reviewed_activity_facts_with_document_sources": reviewed,
            }
            reply = _career_response(context, runtime=(conn, job_id, sources, memories, past, reviewed))
            wants_draft = any(word in body.message for word in ("초안", "작성", "써줘", "고쳐", "수정"))
            if essay and wants_draft and not sources and not memories and not reviewed:
                reply = CareerReply(
                    action="ask", answer="다른 자료도 찾아봤지만 이 문항에 쓸 확인된 경험을 찾지 못했어요. 이전 자소서 표현은 사실 확인을 대신할 수 없어요.",
                    question="관련 수업·프로젝트는 무엇이고, 그때 본인이 직접 한 일은 무엇인가요?",
                )
            elif reply.action == "draft" and essay is None:
                reply = CareerReply(action="ask", answer="초안을 저장할 문항을 먼저 선택해 주세요.", question="어느 자소서 문항을 작성할까요?")
            elif reply.action == "draft" and essay:
                reply.draft = _repair_missing_attribution(reply.draft, sources, memories)
                gap = _draft_gap(reply.draft, sources, memories, reviewed)
                if gap:
                    reply = CareerReply(action="ask", answer="초안을 저장하기 전에 확인할 내용이 있어요.", question=gap)
        conn.execute(
            "insert into skive.drive_job_messages(user_id,job_workspace_id,role,content) values (%s,%s,'user',%s)",
            (user_id, job_id, body.message),
        )
        if reply.action == "ask":
            conn.execute("update skive.drive_job_workspaces set pending_question=%s where id=%s", (reply.question, job_id))
        elif not body.answer_pending:
            conn.execute("update skive.drive_job_workspaces set pending_question='' where id=%s", (job_id,))
        if reply.action == "draft" and reply.draft.strip() and essay:
            draft_citations = json.dumps({"files": sources, "activity_facts": reviewed},
                                         ensure_ascii=False, default=str)
            saved = conn.execute(
                "update skive.drive_essays set draft=%s,citations=%s,review_status='needs_review',"
                "revision_count=revision_count+1,updated_at=now() where id=%s returning revision_count",
                (reply.draft.strip(), draft_citations, essay["id"]),
            ).fetchone()
            conn.execute(
                "insert into skive.drive_essay_versions(user_id,essay_id,revision_no,draft,citations) "
                "values (%s,%s,%s,%s,%s)",
                (user_id, essay["id"], saved["revision_count"], reply.draft.strip(),
                 draft_citations),
            )
        references = {"files": sources, "user_statements": memories,
                      "activity_facts": reviewed, "past_essays": [dict(row) for row in past]}
        assistant_text = reply.answer + ("\n\n확인 질문: " + reply.question if reply.action == "ask" else "")
        message = conn.execute(
            "insert into skive.drive_job_messages(user_id,job_workspace_id,role,content,references_json) "
            "values (%s,%s,'assistant',%s,%s) returning id,role,content,references_json,created_at",
            (user_id, job_id, assistant_text, json.dumps(references, ensure_ascii=False, default=str)),
        ).fetchone()
        conn.execute("update skive.drive_job_workspaces set updated_at=now() where id=%s", (job_id,))
        return {"message": message, "action": reply.action, "pending_question": reply.question,
                "draft": reply.draft if reply.action == "draft" else "", "essay_id": essay["id"] if essay else None,
                "references": references}
