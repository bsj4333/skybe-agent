"""Owner-scoped activity containers over Drive files, independent of folders.

An activity is an organizing draft. Linking a file does not confirm its contents,
the user's role, or any career claim.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from skive.drive_auth import current_user_id
from skive.drive_activity_analysis import conflict_questions, linked_files, source_signature
from skive.drive_activity_suggestions import suggest_groups
from skive.drive_activity_markdown import render_activity_markdown, snapshot_state
from skive.drive_db import user_connection

router = APIRouter(prefix="/api/drive/activities", tags=["drive-activities"])


def clean_title(value: str) -> str:
    value = " ".join(value.split())
    if not value or len(value) > 200:
        raise ValueError("활동 이름은 1~200자로 입력해 주세요")
    return value


def clean_tags(values: list[str]) -> list[str]:
    cleaned = list(dict.fromkeys(" ".join(value.split()) for value in values))
    if len(cleaned) > 8 or any(not value or len(value) > 40 for value in cleaned):
        raise ValueError("활동 분류는 최대 8개, 각 1~40자로 입력해 주세요")
    return cleaned


class ActivityCreate(BaseModel):
    title: str
    kind_tags: list[str] = Field(default_factory=list)
    period_note: str | None = Field(default=None, max_length=120)

    _title = field_validator("title")(clean_title)
    _tags = field_validator("kind_tags")(clean_tags)


class ActivityUpdate(BaseModel):
    title: str | None = None
    kind_tags: list[str] | None = None
    period_note: str | None = Field(default=None, max_length=120)

    _title = field_validator("title")(lambda value: clean_title(value) if value is not None else None)
    _tags = field_validator("kind_tags")(lambda value: clean_tags(value) if value is not None else None)


class ActivityFileSelection(BaseModel):
    file_ids: list[UUID] = Field(min_length=1, max_length=200)


class FactReview(BaseModel):
    review_state: str
    subject: str
    review_note: str = Field(default="", max_length=1000)


def require_activity(conn, activity_id: UUID):
    row = conn.execute(
        "select id,user_id,title,kind_tags,period_note,created_at,updated_at "
        "from skive.drive_activities where id=%s", (activity_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "Activity not found")
    return row


def activity_files(conn, activity_id: UUID):
    return conn.execute(
        "select f.id,f.name,f.folder_id,f.version,f.upload_status,f.analysis_status,"
        "f.analysis_coverage,f.updated_at from skive.drive_activity_files af "
        "join skive.drive_files f on f.id=af.file_id and f.user_id=af.user_id "
        "where af.activity_id=%s and f.trashed_at is null order by lower(f.name),f.id",
        (activity_id,),
    ).fetchall()


@router.get("")
def list_activities(user_id: UUID = Depends(current_user_id)):
    with user_connection(user_id) as conn:
        return conn.execute(
            "select a.id,a.title,a.kind_tags,a.period_note,a.created_at,a.updated_at,"
            "count(f.id)::int as file_count,"
            "count(f.id) filter (where f.analysis_status='ready')::int as text_ready_count "
            "from skive.drive_activities a "
            "left join skive.drive_activity_files af on af.activity_id=a.id and af.user_id=a.user_id "
            "left join skive.drive_files f on f.id=af.file_id and f.user_id=a.user_id "
            "and f.trashed_at is null "
            "group by a.id order by a.updated_at desc,a.id"
        ).fetchall()


@router.post("", status_code=201)
def create_activity(body: ActivityCreate, user_id: UUID = Depends(current_user_id)):
    with user_connection(user_id) as conn:
        return conn.execute(
            "insert into skive.drive_activities(user_id,title,kind_tags,period_note) "
            "values (%s,%s,%s,%s) returning id,title,kind_tags,period_note,created_at,updated_at",
            (user_id, body.title, body.kind_tags, body.period_note),
        ).fetchone()


@router.get("/suggestions")
def activity_suggestions(user_id: UUID = Depends(current_user_id)):
    with user_connection(user_id) as conn:
        folders = conn.execute(
            "select id,parent_id,name from skive.drive_folders where trashed_at is null"
        ).fetchall()
        files = conn.execute(
            "select f.id,f.folder_id,f.name,f.analysis_status,"
            "coalesce((select left(c.text,1200) from skive.drive_file_chunks c "
            "where c.user_id=f.user_id and c.file_id=f.id and c.file_version=f.version "
            "order by c.chunk_index limit 1),'') as preview "
            "from skive.drive_files f where f.trashed_at is null "
            "order by f.updated_at desc,f.id limit 5001"
        ).fetchall()
    return {"suggestions": suggest_groups(folders, files[:5000]),
            "truncated": len(files) > 5000,
            "content_limited": sum(row["analysis_status"] == "ready" for row in files[:5000]) > 500,
            "note": "폴더 위치와 파일명·추출 원문 공통 단어를 이용한 검토 후보입니다. "
                    "본인 역할이나 성과를 확정하지 않습니다."}


@router.get("/{activity_id}")
def get_activity(activity_id: UUID, user_id: UUID = Depends(current_user_id)):
    with user_connection(user_id) as conn:
        activity = require_activity(conn, activity_id)
        return {**activity, "files": activity_files(conn, activity_id)}


@router.post("/{activity_id}/analyze")
def request_activity_analysis(activity_id: UUID, user_id: UUID = Depends(current_user_id)):
    with user_connection(user_id) as conn:
        require_activity(conn, activity_id)
        existing = conn.execute(
            "select status from skive.drive_activity_analysis_jobs "
            "where activity_id=%s for update", (activity_id,),
        ).fetchone()
        if existing and existing["status"] == "processing":
            return {"activity_id": activity_id, "status": "processing"}
        conn.execute(
            "insert into skive.drive_activity_analysis_jobs(user_id,activity_id,status) "
            "values (%s,%s,'queued') on conflict (activity_id) do update "
            "set status='queued',requested_at=now(),updated_at=now(),error=null",
            (user_id, activity_id),
        )
    return {"activity_id": activity_id, "status": "queued"}


@router.get("/{activity_id}/facts")
def activity_facts(activity_id: UUID, user_id: UUID = Depends(current_user_id)):
    with user_connection(user_id) as conn:
        require_activity(conn, activity_id)
        job = conn.execute(
            "select status,source_signature,files_total,files_analyzed,error,updated_at "
            "from skive.drive_activity_analysis_jobs where activity_id=%s", (activity_id,),
        ).fetchone()
        files = linked_files(conn, activity_id, user_id)
        rows = conn.execute(
            "select af.id,af.kind,af.content,af.subject,af.review_state,af.source_file_id,"
            "af.source_file_version,af.source_chunk_index,af.source_location,af.source_quote,"
            "af.review_note,af.created_at,af.reviewed_at,f.name as source_file_name,"
            "(f.id is null or f.trashed_at is not null or f.analysis_status<>'ready' "
            "or f.version<>af.source_file_version "
            "or f.analyzed_at is distinct from af.source_analyzed_at "
            "or not exists (select 1 from skive.drive_activity_files link "
            "where link.activity_id=af.activity_id and link.file_id=af.source_file_id)) as stale "
            "from skive.drive_activity_facts af left join skive.drive_files f "
            "on f.id=af.source_file_id and f.user_id=af.user_id "
            "where af.activity_id=%s order by af.created_at,af.id", (activity_id,),
        ).fetchall()
        facts = [dict(row) for row in rows]
        return {"job": job, "source_changed": bool(job and job["source_signature"] and
                                                 job["source_signature"] != source_signature(files)),
                "facts": facts, "questions": conflict_questions(facts),
                "files_total": len(files)}


@router.patch("/{activity_id}/facts/{fact_id}")
def review_activity_fact(activity_id: UUID, fact_id: UUID, body: FactReview,
                         user_id: UUID = Depends(current_user_id)):
    if body.review_state not in {"confirmed", "rejected"} or body.subject not in {
        "project", "team", "user", "unclear"
    }:
        raise HTTPException(422, "Invalid fact review")
    if body.review_state == "confirmed" and body.subject == "user" and not body.review_note.strip():
        raise HTTPException(422, "Describe what you personally did in the review note")
    with user_connection(user_id) as conn:
        require_activity(conn, activity_id)
        fact = conn.execute(
            "select af.*,f.version as current_version,f.analyzed_at as current_analyzed_at,"
            "f.analysis_status,f.trashed_at from skive.drive_activity_facts af "
            "join skive.drive_files f on f.id=af.source_file_id and f.user_id=af.user_id "
            "where af.id=%s and af.activity_id=%s for update of af", (fact_id, activity_id),
        ).fetchone()
        if not fact:
            raise HTTPException(404, "Fact not found")
        if (fact["trashed_at"] is not None or fact["analysis_status"] != "ready" or
            fact["current_version"] != fact["source_file_version"] or
            fact["current_analyzed_at"] != fact["source_analyzed_at"]):
            raise HTTPException(409, "Source changed; analyze the activity again")
        if not conn.execute("select 1 from skive.drive_activity_files "
                            "where activity_id=%s and file_id=%s",
                            (activity_id, fact["source_file_id"])).fetchone():
            raise HTTPException(409, "Source file is no longer linked to this activity")
        if body.review_state == "confirmed":
            from skive.verify import norm, quote_in_source
            chunk = conn.execute(
                "select text from skive.drive_file_chunks where file_id=%s "
                "and file_version=%s and chunk_index=%s",
                (fact["source_file_id"], fact["source_file_version"], fact["source_chunk_index"]),
            ).fetchone()
            if not chunk or not quote_in_source(fact["source_quote"], norm(chunk["text"])):
                raise HTTPException(409, "Source quote no longer matches")
        return conn.execute(
            "update skive.drive_activity_facts set review_state=%s,subject=%s,review_note=%s,"
            "reviewed_at=now(),updated_at=now() where id=%s returning id,review_state,subject,review_note",
            (body.review_state, body.subject, body.review_note.strip(), fact_id),
        ).fetchone()


@router.patch("/{activity_id}")
def update_activity(activity_id: UUID, body: ActivityUpdate,
                    user_id: UUID = Depends(current_user_id)):
    with user_connection(user_id) as conn:
        current = require_activity(conn, activity_id)
        provided = body.model_fields_set
        if "title" in provided and body.title is None:
            raise HTTPException(422, "활동 이름은 비울 수 없습니다")
        if "kind_tags" in provided and body.kind_tags is None:
            raise HTTPException(422, "활동 분류는 목록으로 입력해 주세요")
        return conn.execute(
            "update skive.drive_activities set title=%s,kind_tags=%s,period_note=%s,updated_at=now() "
            "where id=%s returning id,title,kind_tags,period_note,updated_at",
            (body.title if "title" in provided else current["title"],
             body.kind_tags if "kind_tags" in provided else current["kind_tags"],
             body.period_note if "period_note" in provided else current["period_note"],
             activity_id),
        ).fetchone()


@router.put("/{activity_id}/files/{file_id}")
def link_file(activity_id: UUID, file_id: UUID, user_id: UUID = Depends(current_user_id)):
    with user_connection(user_id) as conn:
        require_activity(conn, activity_id)
        file = conn.execute(
            "select id,name from skive.drive_files where id=%s and user_id=%s and trashed_at is null",
            (file_id, user_id),
        ).fetchone()
        if file is None:
            raise HTTPException(404, "File not found")
        conn.execute(
            "insert into skive.drive_activity_files(user_id,activity_id,file_id) "
            "values (%s,%s,%s) on conflict (activity_id,file_id) do nothing",
            (user_id, activity_id, file_id),
        )
        conn.execute("update skive.drive_activities set updated_at=now() where id=%s", (activity_id,))
        return {"activity_id": activity_id, "file_id": file_id, "name": file["name"]}


@router.post("/{activity_id}/files")
def link_selected_files(activity_id: UUID, body: ActivityFileSelection,
                        user_id: UUID = Depends(current_user_id)):
    selected = list(dict.fromkeys(body.file_ids))
    with user_connection(user_id) as conn:
        require_activity(conn, activity_id)
        owned = conn.execute(
            "select id from skive.drive_files where id=any(%s::uuid[]) and trashed_at is null",
            (selected,),
        ).fetchall()
        if len(owned) != len(selected):
            raise HTTPException(404, "One or more files were not found in this account")
        added = conn.execute(
            "insert into skive.drive_activity_files(user_id,activity_id,file_id) "
            "select %s,%s,id from skive.drive_files where id=any(%s::uuid[]) "
            "on conflict (activity_id,file_id) do nothing returning file_id",
            (user_id, activity_id, selected),
        ).fetchall()
        if added:
            conn.execute("update skive.drive_activities set updated_at=now() where id=%s",
                         (activity_id,))
        return {"activity_id": activity_id, "selected": len(selected), "added": len(added)}


@router.delete("/{activity_id}/files/{file_id}")
def unlink_file(activity_id: UUID, file_id: UUID, user_id: UUID = Depends(current_user_id)):
    with user_connection(user_id) as conn:
        require_activity(conn, activity_id)
        row = conn.execute(
            "delete from skive.drive_activity_files where activity_id=%s and file_id=%s "
            "returning file_id", (activity_id, file_id),
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Linked file not found")
        conn.execute("update skive.drive_activities set updated_at=now() where id=%s", (activity_id,))
        return {"activity_id": activity_id, "file_id": file_id}


@router.post("/{activity_id}/folders/{folder_id}/files")
def link_folder_files(activity_id: UUID, folder_id: UUID,
                      user_id: UUID = Depends(current_user_id)):
    """Link current files in a folder subtree; users can remove individual links."""
    with user_connection(user_id) as conn:
        require_activity(conn, activity_id)
        folder = conn.execute(
            "select id,name from skive.drive_folders where id=%s and user_id=%s and trashed_at is null",
            (folder_id, user_id),
        ).fetchone()
        if folder is None:
            raise HTTPException(404, "Folder not found")
        added = conn.execute(
            "with recursive subtree as ("
            "select id from skive.drive_folders where id=%s and user_id=%s and trashed_at is null "
            "union all select f.id from skive.drive_folders f join subtree s on f.parent_id=s.id "
            "where f.user_id=%s and f.trashed_at is null) "
            "insert into skive.drive_activity_files(user_id,activity_id,file_id) "
            "select %s,%s,d.id from skive.drive_files d join subtree s on d.folder_id=s.id "
            "where d.user_id=%s and d.trashed_at is null "
            "on conflict (activity_id,file_id) do nothing returning file_id",
            (folder_id, user_id, user_id, user_id, activity_id, user_id),
        ).fetchall()
        if added:
            conn.execute("update skive.drive_activities set updated_at=now() where id=%s", (activity_id,))
        return {"activity_id": activity_id, "folder_id": folder_id, "added": len(added)}


def activity_markdown(activity: dict, files: list[dict]) -> str:
    title = " ".join(activity["title"].split())
    tags = ", ".join(activity["kind_tags"]) or "분류 미정"
    ready = sum(file["analysis_status"] == "ready" for file in files)
    issues = sum(file["analysis_status"] in {"failed", "unsupported"} for file in files)
    lines = [f"# {title} — 활동 자료 목차", "", "> 연결된 자료의 목록입니다. 이 활동의 사실, 본인 역할, 성과를 아직 확인하지 않았습니다.",
             "", f"- 분류: {tags}", f"- 기간: {activity['period_note'] or '미확인'}",
             f"- 연결된 파일: {len(files)}개 · 텍스트 추출 완료 {ready}개 · 읽기 문제 {issues}개",
             "", "## 연결된 자료"]
    if not files:
        lines.append("- 아직 연결된 파일이 없습니다.")
    for file in files:
        name = " ".join(file["name"].split())
        lines.append(f"- {name} — 업로드 {file['upload_status']}, 텍스트 추출 {file['analysis_status']} "
                     f"[파일 ID {file['id']}, 버전 {file['version']}]")
    lines += ["", "## 다음 확인", "- 관련 자료가 같은 활동인지 검토하고, 잘못 연결된 파일은 제거하세요.",
              "- 본인이 한 일·팀이 한 일·결과 수치는 원문과 사용자 확인을 거쳐 별도 사실로 정리합니다.", ""]
    return "\n".join(lines)


@router.get("/{activity_id}/markdown")
def get_activity_markdown(activity_id: UUID, user_id: UUID = Depends(current_user_id)):
    with user_connection(user_id) as conn:
        activity = require_activity(conn, activity_id)
        files = activity_files(conn, activity_id)
    return {"activity_id": activity_id, "markdown": activity_markdown(activity, files),
            "filename": f"activity-{activity_id}.md"}


@router.get("/{activity_id}/reviewed-markdown")
def get_reviewed_markdown(activity_id: UUID, user_id: UUID = Depends(current_user_id)):
    with user_connection(user_id) as conn:
        activity = require_activity(conn, activity_id)
        files, facts, source_hash, facts_hash = snapshot_state(conn, activity_id, user_id,
                                                               activity["title"])
        latest = conn.execute(
            "select id,markdown,source_signature,facts_signature,created_at "
            "from skive.drive_activity_markdown_snapshots where activity_id=%s "
            "order by id desc limit 1", (activity_id,),
        ).fetchone()
        return {"activity_id": activity_id, "snapshot": latest,
                "needs_refresh": bool(latest and (latest["source_signature"] != source_hash or
                                                 latest["facts_signature"] != facts_hash)),
                "needs_source_review": any(row["stale"] for row in facts),
                "filename": f"activity-{activity_id}-reviewed.md",
                "files_total": len(files)}


@router.post("/{activity_id}/reviewed-markdown")
def create_reviewed_markdown(activity_id: UUID, user_id: UUID = Depends(current_user_id)):
    with user_connection(user_id) as conn:
        activity = require_activity(conn, activity_id)
        files, facts, source_hash, facts_hash = snapshot_state(conn, activity_id, user_id,
                                                               activity["title"])
        markdown = render_activity_markdown(activity, files, facts)
        snapshot = conn.execute(
            "insert into skive.drive_activity_markdown_snapshots "
            "(user_id,activity_id,source_signature,facts_signature,markdown) "
            "values (%s,%s,%s,%s,%s) returning id,markdown,created_at",
            (user_id, activity_id, source_hash, facts_hash, markdown),
        ).fetchone()
        return {"activity_id": activity_id, "snapshot": snapshot,
                "needs_refresh": False, "needs_source_review": any(row["stale"] for row in facts),
                "filename": f"activity-{activity_id}-reviewed.md"}
