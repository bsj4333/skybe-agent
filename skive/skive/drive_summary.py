"""Account-scoped folder experience drafts from extracted, cited source chunks."""

import hashlib
import json
import re
from pathlib import Path
from uuid import UUID

from langchain_core.messages import HumanMessage, SystemMessage
from psycopg.rows import dict_row
from pydantic import BaseModel, Field

from skive.analyzer import _inspect
from skive.db import get_connection
from skive.llm import get_llm
from skive.loaders import Chunk
from skive.models import Evidence

MAX_FILES = 24
MAX_CHARS = 100_000


class SummaryClaim(BaseModel):
    text: str = Field(description="원문에서 확인할 수 있는 한 문장. 주체가 명시되지 않으면 '본인'이라고 쓰지 않는다")
    evidence: list[Evidence] = Field(min_length=1, description="입력의 C 번호와 원문 그대로의 60자 이내 인용")


class SummaryDraft(BaseModel):
    claims: list[SummaryClaim] = Field(description="중복 없는 핵심 사실 최대 12개. 프로젝트 목적, 실제 행동, 결과 수치를 우선")
    questions: list[str] = Field(description="본인 역할과 불명확한 수치를 확인할 사용자 질문 최대 5개")


SYSTEM = """너는 업로드된 한 폴더의 경험 기록을 만드는 분석가다.
입력은 [C번호] 원문이다. 최대 12개의 핵심 사실만 뽑아라. 모든 문장에는 원문 그대로의
짧은 인용과 C번호를 붙여라. 원문에 없는 수치, 인과, 성장, 본인 기여를 추론하지 마라.
자료가 팀 프로젝트라면 작성자 본인의 역할을 알 수 없다. 결과 수치는 지표 이름과 함께 적어라.
입력 파일은 일부만 선택됐을 수 있으므로 폴더 전체를 읽은 것처럼 말하지 마라.
의심스러운 내용은 사실에 넣지 말고 사용자에게 물어볼 질문으로 남겨라.
claim.text에는 C번호, 출처 표기, 괄호 속 참조를 절대 쓰지 마라. C번호는 evidence.chunk_id에만 쓴다.
여러 자료가 서로 다른 내용을 다루면 하나의 파일에서만 사실을 뽑지 말고 주요 자료를 고르게 확인하라."""


def folder_files(conn, user_id: UUID, folder_id: UUID) -> list[dict]:
    """Keep owner constraints in every recursive and file query, including worker reads."""
    return conn.execute(
        "with recursive subtree as ("
        "select id from skive.drive_folders where id=%s and user_id=%s and trashed_at is null "
        "union all select f.id from skive.drive_folders f join subtree s on f.parent_id=s.id "
        "where f.user_id=%s and f.trashed_at is null) "
        "select d.id,d.name,d.version,d.analysis_status,d.upload_status,d.updated_at "
        "from skive.drive_files d join subtree s on d.folder_id=s.id "
        "where d.user_id=%s and d.trashed_at is null order by d.id",
        (folder_id, user_id, user_id, user_id),
    ).fetchall()


def signature(files: list[dict]) -> str:
    payload = [(str(f["id"]), f["version"], f["analysis_status"], f["upload_status"],
                f["updated_at"].isoformat()) for f in files]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()


def rank_file(file: dict) -> tuple[int, str]:
    name = file["name"].lower()
    ext = Path(name).suffix
    score = {".md": 8, ".docx": 7, ".pdf": 6, ".pptx": 6, ".txt": 5,
             ".xlsx": 2, ".csv": 1}.get(ext, 0)
    score += sum(weight for term, weight in (("최신본", 30), ("종합", 20), ("최종", 18),
                                            ("readme", 16), ("overview", 16), ("정리", 10),
                                            ("보고서", 8), ("발표", 6), ("결과", 4)) if term in name)
    score -= sum(3 for term in ("node_modules", "package-lock", "raw", "원시", "로그") if term in name)
    if re.match(r"e\d{3}[_-]", name):
        score -= 4  # One test case is less useful than the project overview.
    return -score, name


def collect_sources(conn, user_id: UUID, files: list[dict]) -> tuple[dict[str, Chunk], dict[str, dict], int]:
    selected = sorted((f for f in files if f["analysis_status"] == "ready"), key=rank_file)[:MAX_FILES]
    if not selected:
        return {}, {}, 0
    ids = [f["id"] for f in selected]
    rows = conn.execute(
        "select c.file_id,c.file_version,c.chunk_index,c.location,left(c.text,5000) as text "
        "from skive.drive_file_chunks c where c.user_id=%s and c.file_id=any(%s::uuid[]) "
        "and (c.chunk_index<=3 or c.location like '%% annotation %%' or "
        "c.location like '%% speaker notes' or c.location like '%% cell note %%' or "
        "c.location like '%% threaded comment %%') order by c.file_id,c.chunk_index", (user_id, ids),
    ).fetchall()
    by_file = {f["id"]: f for f in selected}
    order = {f["id"]: i for i, f in enumerate(selected)}
    chunks: dict[str, Chunk] = {}
    refs: dict[str, dict] = {}
    used = 0
    supplemental_per_file: dict = {}
    def priority(row):
        location = row["location"]
        supplemental = any(token in location for token in
                           (" annotation ", " speaker notes", " cell note ", " threaded comment "))
        return (order[row["file_id"]], 0 if row["chunk_index"] == 1 else 1 if supplemental else 2,
                row["chunk_index"])

    for row in sorted(rows, key=priority):
        file = by_file[row["file_id"]]
        if row["file_version"] != file["version"]:
            continue
        is_supplemental = any(token in row["location"] for token in
                              (" annotation ", " speaker notes", " cell note ", " threaded comment "))
        if is_supplemental and supplemental_per_file.get(row["file_id"], 0) >= 2:
            continue
        text = row["text"]
        if used + len(text) > MAX_CHARS:
            break
        cid = f"C{len(chunks)+1}"
        chunks[cid] = Chunk(source=file["name"], location=row["location"], text=text)
        refs[cid] = {"file_id": str(file["id"]), "file_name": file["name"],
                     "file_version": file["version"], "chunk_index": row["chunk_index"],
                     "location": row["location"]}
        used += len(text)
        if is_supplemental:
            supplemental_per_file[row["file_id"]] = supplemental_per_file.get(row["file_id"], 0) + 1
    return chunks, refs, len({v["file_id"] for v in refs.values()})


def build_summary(folder_name: str, chunks: dict[str, Chunk], refs: dict[str, dict],
                  total: int, selected: int) -> tuple[str, list[dict]]:
    # Split by source file so one early document cannot consume every fact slot.
    file_ids = list(dict.fromkeys(refs[cid]["file_id"] for cid in chunks))
    group_count = min(4, len(file_ids))
    file_group = {file_id: i % group_count for i, file_id in enumerate(file_ids)}
    groups = [[] for _ in range(group_count)]
    for cid, chunk in chunks.items():
        groups[file_group[refs[cid]["file_id"]]].append(
            f"[{cid}] ({refs[cid]['file_name']} @ {chunk.location})\n{chunk.text}"
        )
    model = get_llm().with_structured_output(SummaryDraft)
    drafts = [model.invoke([
        SystemMessage(SYSTEM),
        HumanMessage(f"폴더: {folder_name}\n이 자료 묶음에서 중요한 사실 최대 3개와 사용자 질문을 뽑아라.\n\n"
                     + "\n\n".join(group)),
    ]) for group in groups]
    claims = [claim for i in range(3) for draft in drafts for claim in draft.claims[i:i + 1]]
    questions = list(dict.fromkeys(q for draft in drafts for q in draft.questions))[:5]
    facts = []
    lines = [f"# {folder_name} — 경험 초안", "", "> AI가 선택된 원문에서 뽑은 초안입니다. 본인 기여와 성장 여부는 사용자 확인 전까지 확정하지 않습니다.",
             "", f"대상 파일 {total}개 중 {selected}개, 원문 {len(chunks)}구간을 사용했습니다.",
             "", "## 자동 근거 검사 통과 (사용자 검토 필요)"]
    held = []
    for claim in claims[:12]:
        text = re.sub(r"\s*(?:\(C\d+\)|\[C\d+\])\s*$", "", claim.text).strip()
        checks = [_inspect(ev, chunks, text) for ev in claim.evidence]
        passed = [check for check in checks if check["ok"]]
        entries = [{**refs[c["chunk_id"]], "quote": c["quote"], "check": c}
                   for c in checks if c["chunk_id"] in refs]
        fact = {"text": text, "evidence": entries, "auto_checked": bool(passed),
                "user_confirmed": False}
        facts.append(fact)
        if passed:
            lines.append(f"- {text}")
            for item in entries:
                if item["check"]["ok"]:
                    lines.append(f"  - 출처: {item['file_name']} @ {item['location']} [파일 {item['file_id']}, C{item['chunk_index']}] — “{item['quote']}”")
        else:
            held.append(text)
    if not any(f["auto_checked"] for f in facts):
        lines.append("- 자동 검사에 통과한 문장이 없습니다.")
    lines += ["", "## 검증 보류"]
    if not any(f["auto_checked"] for f in facts):
        lines.append(f"- 자동 검사를 통과하지 못한 문장 {len(held)}개는 표시하지 않습니다. 설명 문서나 본인 역할 기록을 추가해 주세요.")
    elif held:
        lines.extend(f"- {x}" for x in held)
    else:
        lines.append("- 없음")
    lines += ["", "## 사용자에게 확인할 질문", *(f"- {x}" for x in questions)]
    if not questions:
        lines.append("- 이 자료에서 본인이 직접 맡은 역할과 성과는 무엇인가요?")
    lines += ["", "## 범위", f"- 파일 {total}개 중 {selected}개를 선택했습니다. 다른 파일의 내용과 충돌할 수 있어 전체 경험으로 확정하지 않습니다.",
              "- 자동 검사는 인용 존재·문장 유사성·주체 충돌·수치를 확인합니다. 의미와 본인 기여는 사람이 검토해야 합니다."]
    return "\n".join(lines) + "\n", facts


def run_summary_once() -> bool:
    with get_connection() as conn:
        conn.row_factory = dict_row
        job = conn.execute(
            "select s.id,s.user_id,s.folder_id,f.name from skive.drive_folder_summaries s "
            "join skive.drive_folders f on f.id=s.folder_id and f.user_id=s.user_id "
            "where s.status='queued' and f.trashed_at is null "
            "order by s.updated_at for update of s skip locked limit 1"
        ).fetchone()
        if not job:
            return False
        files = folder_files(conn, job["user_id"], job["folder_id"])
        if any(f["upload_status"] == "pending" or f["analysis_status"] in {"waiting", "queued", "processing"}
               for f in files):
            return False
        conn.execute("update skive.drive_folder_summaries set status='processing',updated_at=now() where id=%s",
                     (job["id"],))
    try:
        with get_connection() as conn:
            conn.row_factory = dict_row
            files = folder_files(conn, job["user_id"], job["folder_id"])
            chunks, refs, selected = collect_sources(conn, job["user_id"], files)
        if not chunks:
            raise ValueError("요약할 수 있는 텍스트가 없습니다. 파일 추출 상태를 확인하세요")
        markdown, facts = build_summary(job["name"], chunks, refs, len(files), selected)
        with get_connection() as conn:
            conn.row_factory = dict_row
            latest = folder_files(conn, job["user_id"], job["folder_id"])
            if signature(latest) != signature(files):
                conn.execute("update skive.drive_folder_summaries set status='queued',updated_at=now() where id=%s",
                             (job["id"],))
                return True
            conn.execute(
                "update skive.drive_folder_summaries set status='ready',source_signature=%s,markdown=%s,"
                "facts=%s::jsonb,files_considered=%s,files_selected=%s,error=null,updated_at=now() where id=%s",
                (signature(files), markdown, json.dumps(facts, ensure_ascii=False), len(files), selected, job["id"]),
            )
    except Exception as exc:
        with get_connection() as conn:
            conn.execute("update skive.drive_folder_summaries set status='failed',error=%s,updated_at=now() where id=%s",
                         (str(exc)[:500], job["id"]))
    return True
