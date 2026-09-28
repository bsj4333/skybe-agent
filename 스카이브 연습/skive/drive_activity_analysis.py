"""Evidence-bounded, asynchronous activity fact proposals.

The model only proposes document claims. Human review is required for personal
role, outcome ownership, and using a claim as a career fact.
"""

import hashlib
import json
import re
from typing import Literal
from uuid import UUID

from langchain_core.messages import HumanMessage, SystemMessage
from psycopg.rows import dict_row
from pydantic import BaseModel, Field

from skive.analyzer import _inspect
from skive.db import get_connection
from skive.llm import get_llm
from skive.loaders import Chunk
from skive.models import Evidence
from skive.drive_read_card import _location

MAX_FILES = 40


class ProposedFact(BaseModel):
    kind: Literal["context", "goal", "action", "result", "skill", "lesson", "other"]
    line_id: str = Field(description="Provided source line ID, for example S3")
    subject: Literal["project", "team", "user", "unclear"] = "unclear"


class ProposedFacts(BaseModel):
    facts: list[ProposedFact] = Field(max_length=8)


SYSTEM = """아래에는 파일 원문에서 그대로 가져온 줄마다 S번호가 붙어 있다.
활동의 목표, 행동, 결과, 기술, 배운 점을 알려주는 중요한 S번호를 최대 6개 선택하라.
결과 수치가 있는 줄은 반드시 하나 이상 포함하고, 목표가 있으면 목표 줄도 포함하라.
파일이 여러 개이면 관련 문장이 있는 각 파일에서 최소 한 줄을 선택하라.
새 문장이나 인용문을 만들지 말고 제공된 S번호만 반환하라. 같은 뜻의 중복 줄은 줄인다.
종류는 context/goal/action/result/skill/lesson/other 중에서 고른다.
주체가 명시되지 않으면 unclear, 팀 전체면 team, 프로젝트 전체면 project로 표시한다.
파일 소유자가 본인 역할을 수행했다는 뜻은 아니다. 결과 수치의 단위와 조건은 원문 그대로 유지된다.
S번호가 없는 내용은 반환하지 마라. 사용자가 확인하기 전에는 어떤 사실도 확정되지 않는다."""


def source_signature(files: list[dict]) -> str:
    payload = [(str(row["id"]), row["name"], row["version"], row["analysis_status"],
                row["analyzed_at"].isoformat() if row["analyzed_at"] else None)
               for row in sorted(files, key=lambda item: str(item["id"]))]
    return hashlib.sha256(json.dumps(payload).encode()).hexdigest()


def linked_files(conn, activity_id: UUID, user_id: UUID) -> list[dict]:
    return conn.execute(
        "select f.id,f.name,f.version,f.analysis_status,f.analyzed_at "
        "from skive.drive_activity_files af join skive.drive_files f "
        "on f.id=af.file_id and f.user_id=af.user_id "
        "where af.activity_id=%s and af.user_id=%s and f.trashed_at is null "
        "order by lower(f.name),f.id", (activity_id, user_id),
    ).fetchall()


def source_batches(conn, files: list[dict], user_id: UUID):
    ready = [row for row in files if row["analysis_status"] == "ready"][:MAX_FILES]
    if not ready:
        return [], 0
    by_id = {row["id"]: row for row in ready}
    rows = conn.execute(
        "with ranked as (select c.file_id,c.file_version,c.chunk_index,c.location,"
        "left(c.text,2500) as text,"
        "row_number() over (partition by c.file_id order by c.chunk_index) as first_rank,"
        "row_number() over (partition by c.file_id order by c.chunk_index desc) as last_rank "
        "from skive.drive_file_chunks c where c.user_id=%s "
        "and c.file_id=any(%s::uuid[])) "
        "select file_id,file_version,chunk_index,location,text from ranked "
        "where first_rank=1 or last_rank=1 or location like '%% annotation %%' "
        "or location like '%% speaker notes' or location like '%% cell note %%' "
        "order by file_id,chunk_index", (user_id, [row["id"] for row in ready]),
    ).fetchall()
    per_file = {}
    for row in rows:
        if row["file_version"] != by_id[row["file_id"]]["version"]:
            continue
        selected = per_file.setdefault(row["file_id"], [])
        if len(selected) < 3:
            selected.append(row)
    batches = []
    for start in range(0, len(ready), 5):
        refs, chunks, lines = {}, {}, []
        for file in ready[start:start + 5]:
            for row in per_file.get(file["id"], []):
                cid = f"C{len(refs)+1}"
                refs[cid] = {"file": file, "row": row}
                chunks[cid] = Chunk(source=file["name"], location=row["location"], text=row["text"])
                lines.append(f"[{cid}] {file['name']} @ {row['location']}\n{row['text']}")
        if lines:
            batches.append((refs, chunks, "\n\n".join(lines)))
    return batches, len(ready)


def propose(batch, title: str, *, model=None) -> list[dict]:
    refs, chunks, corpus = batch
    lines = {}
    per_file_count = {}
    for cid, chunk in chunks.items():
        file_id = refs[cid]["file"]["id"]
        for offset, raw in enumerate(chunk.text.splitlines()):
            quote = raw.strip()[:450]
            if len(quote) < 4:
                continue
            if per_file_count.get(file_id, 0) >= 24:
                break
            line_id = f"S{len(lines)+1}"
            source = refs[cid]
            lines[line_id] = {"cid": cid, "quote": quote,
                              "location": _location(source["row"]["location"], raw, offset)}
            per_file_count[file_id] = per_file_count.get(file_id, 0) + 1
            if len(lines) >= 160:
                break
        if len(lines) >= 160:
            break
    if not lines:
        return []
    numbered = "\n".join(f"[{line_id}] ({refs[item['cid']]['file']['name']} @ {item['location']}) "
                         f"{item['quote']}" for line_id, item in lines.items())
    result = (model or get_llm().with_structured_output(ProposedFacts)).invoke([
        SystemMessage(SYSTEM), HumanMessage(f"활동 후보: {title}\n\n{numbered}"),
    ])
    proposals = []
    chosen = [(item.line_id, item.kind, item.subject) for item in result.facts]
    selected_files = {refs[lines[line_id]["cid"]]["file"]["id"] for line_id, _, _ in chosen
                      if line_id in lines}
    for file_id in per_file_count:
        if file_id in selected_files:
            continue
        fallback = next((line_id for line_id, item in lines.items()
                         if refs[item["cid"]]["file"]["id"] == file_id and
                         re.search(r"목표|결과|평가|개선|감소|증가|구현|개발|분석|설계|실험|성과|정확도", item["quote"])), None)
        if fallback:
            quote = lines[fallback]["quote"]
            fallback_kind = ("result" if re.search(r"\d", quote) and
                             re.search(r"결과|평가|정확도|감소|증가|달성", quote)
                             else "goal" if re.search(r"목표|목적", quote) else "other")
            chosen.append((fallback, fallback_kind, "unclear"))
    for file_id in per_file_count:
        for wanted, pattern in (("result", r"결과|평가|정확도|감소|증가|달성"),
                                ("goal", r"목표|목적")):
            existing = {kind for line_id, kind, _ in chosen if line_id in lines and
                        refs[lines[line_id]["cid"]]["file"]["id"] == file_id}
            if wanted in existing:
                continue
            matched = next((line_id for line_id, item in lines.items()
                            if refs[item["cid"]]["file"]["id"] == file_id and
                            re.search(pattern, item["quote"]) and
                            (wanted != "result" or re.search(r"\d", item["quote"]))), None)
            if matched and matched not in {line_id for line_id, _, _ in chosen}:
                chosen.append((matched, wanted, "unclear"))
    for line_id, kind, subject in chosen:
        item = lines.get(line_id)
        if item is None:
            continue
        ref = refs[item["cid"]]
        quote = item["quote"]
        check = _inspect(Evidence(chunk_id=item["cid"], quote=quote), chunks, quote)
        if not check["ok"]:
            continue
        proposals.append({"kind": kind, "content": quote,
                          "subject": "unclear" if subject == "user" else subject,
                          "file": ref["file"], "row": {**ref["row"], "location": item["location"]},
                          "quote": quote, "check": check})
    return proposals


def run_activity_analysis_once() -> bool:
    with get_connection() as conn:
        conn.row_factory = dict_row
        job = conn.execute(
            "select j.user_id,j.activity_id,a.title from skive.drive_activity_analysis_jobs j "
            "join skive.drive_activities a on a.id=j.activity_id and a.user_id=j.user_id "
            "where j.status='queued' or (j.status='processing' "
            "and j.updated_at < now()-interval '30 minutes') order by j.requested_at "
            "for update of j skip locked limit 1"
        ).fetchone()
        if not job:
            return False
        conn.execute("update skive.drive_activity_analysis_jobs "
                     "set status='processing',error=null,updated_at=now() where activity_id=%s",
                     (job["activity_id"],))
    try:
        with get_connection() as conn:
            conn.row_factory = dict_row
            files = linked_files(conn, job["activity_id"], job["user_id"])
            signature = source_signature(files)
            batches, selected = source_batches(conn, files, job["user_id"])
        if not batches:
            raise ValueError("읽기 완료된 연결 파일이 없습니다")
        candidates = []
        for batch in batches:
            candidates.extend(propose(batch, job["title"]))
        with get_connection() as conn:
            conn.row_factory = dict_row
            if source_signature(linked_files(conn, job["activity_id"], job["user_id"])) != signature:
                conn.execute("update skive.drive_activity_analysis_jobs "
                             "set status='queued',updated_at=now() where activity_id=%s",
                             (job["activity_id"],))
                return True
            conn.execute("delete from skive.drive_activity_facts where activity_id=%s "
                         "and user_id=%s and review_state='candidate'",
                         (job["activity_id"], job["user_id"]))
            seen = set()
            for item in candidates:
                file, row = item["file"], item["row"]
                key = (file["id"], row["chunk_index"], item["content"])
                if key in seen:
                    continue
                seen.add(key)
                conn.execute(
                    "insert into skive.drive_activity_facts "
                    "(user_id,activity_id,kind,content,subject,source_file_id,source_file_version,"
                    "source_analyzed_at,source_chunk_index,source_location,source_quote,evidence_check) "
                    "select %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb "
                    "where not exists (select 1 from skive.drive_activity_facts old "
                    "where old.activity_id=%s and old.source_file_id=%s "
                    "and old.source_file_version=%s and old.source_chunk_index=%s "
                    "and old.content=%s and old.review_state in ('confirmed','rejected'))",
                    (job["user_id"], job["activity_id"], item["kind"], item["content"],
                     item["subject"], file["id"], file["version"], file["analyzed_at"],
                     row["chunk_index"], row["location"], item["quote"],
                     json.dumps(item["check"], ensure_ascii=False), job["activity_id"],
                     file["id"], file["version"], row["chunk_index"], item["content"]),
                )
            conn.execute("update skive.drive_activity_analysis_jobs set status='ready',"
                         "source_signature=%s,files_total=%s,files_analyzed=%s,error=null,"
                         "updated_at=now() where activity_id=%s",
                         (signature, len(files), selected, job["activity_id"]),
            )
    except Exception as exc:
        with get_connection() as conn:
            conn.execute("update skive.drive_activity_analysis_jobs set status='failed',"
                         "error=%s,updated_at=now() where activity_id=%s",
                         (str(exc)[:500], job["activity_id"]),
            )
    return True


def conflict_questions(facts: list[dict]) -> list[str]:
    questions = []
    if facts and not any(f["review_state"] == "confirmed" and f["subject"] == "user"
                         and f["kind"] == "action" for f in facts):
        questions.append("이 활동에서 본인이 직접 맡아 수행한 일은 무엇인가요? 팀 전체의 작업과 구분해 주세요.")
    numeric = [f for f in facts if f["kind"] == "result" and re.search(r"\d", f["content"])]
    if numeric:
        questions.append("결과 수치의 지표·단위·비교 기준·측정 시점과 본인 기여를 확인해 주세요.")
    by_pattern = {}
    for fact in numeric:
        pattern = re.sub(r"\d+(?:[.,]\d+)*", "#", fact["content"].casefold())
        by_pattern.setdefault(pattern, []).append(fact)
    for group in by_pattern.values():
        values = {tuple(re.findall(r"\d+(?:[.,]\d+)*", fact["content"])) for fact in group}
        if len(values) > 1:
            questions.append("같은 결과 항목에 서로 다른 수치가 있습니다. 버전과 측정 조건 중 어느 것이 맞나요? "
                             + " / ".join(fact["content"] for fact in group[:3]))
    return questions[:8]
