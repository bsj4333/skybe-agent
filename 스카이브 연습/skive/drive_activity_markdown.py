"""Deterministic activity Markdown from reviewed facts and versioned sources."""

import hashlib
import json

from skive.drive_activity_analysis import conflict_questions, linked_files, source_signature


def _line(value) -> str:
    return " ".join(str(value or "").split())


def snapshot_state(conn, activity_id, user_id, title: str):
    files = linked_files(conn, activity_id, user_id)
    facts = conn.execute(
        "select af.id,af.kind,af.content,af.subject,af.review_state,af.review_note,"
        "af.source_file_id,af.source_file_version,af.source_analyzed_at,"
        "af.source_chunk_index,af.source_location,af.source_quote,af.updated_at,"
        "f.name as source_file_name,"
        "(f.id is null or f.trashed_at is not null or f.analysis_status<>'ready' "
        "or f.version<>af.source_file_version "
        "or f.analyzed_at is distinct from af.source_analyzed_at "
        "or not exists (select 1 from skive.drive_activity_files link "
        "where link.activity_id=af.activity_id and link.file_id=af.source_file_id)) as stale "
        "from skive.drive_activity_facts af left join skive.drive_files f "
        "on f.id=af.source_file_id and f.user_id=af.user_id "
        "where af.activity_id=%s order by af.created_at,af.id", (activity_id,),
    ).fetchall()
    payload = [(str(row["id"]), row["review_state"], row["subject"], row["content"],
                row["review_note"], row["stale"], row["updated_at"].isoformat()) for row in facts]
    facts_hash = hashlib.sha256(json.dumps([title, payload], ensure_ascii=False).encode()).hexdigest()
    return files, facts, source_signature(files), facts_hash


def render_activity_markdown(activity: dict, files: list[dict], facts: list[dict]) -> str:
    title = _line(activity["title"])
    confirmed = [row for row in facts if row["review_state"] == "confirmed" and not row["stale"]]
    stale = [row for row in facts if row["stale"]]
    pending = [row for row in facts if row["review_state"] == "candidate" and not row["stale"]]
    ready = sum(row["analysis_status"] == "ready" for row in files)
    lines = [f"# {title} — 확인된 활동 요약", "",
             "> 이 문서는 사용자가 확인한 사실과 출처를 정리한 결과입니다. "
             "원본 문서의 내용과 사용자의 역할 진술을 구분합니다.", "",
             f"- 연결 파일: {len(files)}개 (텍스트 추출 완료 {ready}개)",
             f"- 확인된 사실: {len(confirmed)}개 / 검토 대기: {len(pending)}개 / 출처 재검토: {len(stale)}개", ""]
    headings = [("context", "배경"), ("goal", "목표"), ("action", "수행한 일"),
                ("result", "결과"), ("skill", "사용한 역량"),
                ("lesson", "배운 점"), ("other", "기타 확인 사실")]
    subjects = {"user": "본인 확인", "team": "팀", "project": "프로젝트", "unclear": "주체 불명"}
    for kind, heading in headings:
        lines += [f"## {heading}"]
        selected = [row for row in confirmed if row["kind"] == kind]
        if not selected:
            lines += ["- 확인된 내용 없음", ""]
            continue
        for fact in selected:
            lines.append(f"- [{subjects[fact['subject']]}] {_line(fact['content'])}")
            lines.append(f"  - 출처: {_line(fact['source_file_name'])} "
                         f"(파일 {fact['source_file_id']}, 버전 {fact['source_file_version']}, "
                         f"C{fact['source_chunk_index']}, {_line(fact['source_location'])})")
            lines.append(f"  - 원문: “{_line(fact['source_quote'])}”")
            if fact["review_note"]:
                lines.append(f"  - 사용자 확인 메모: {_line(fact['review_note'])}")
        lines.append("")
    lines += ["## 확인이 필요한 점"]
    questions = conflict_questions([dict(row) for row in facts if not row["stale"]])
    lines.extend(f"- {_line(question)}" for question in questions)
    if stale:
        lines.append(f"- 원본 변경 또는 연결 해제로 {len(stale)}개 사실의 출처를 다시 확인해야 합니다.")
    if pending:
        lines.append(f"- 아직 검토하지 않은 사실 후보 {len(pending)}개가 있습니다.")
    if len(files) > ready:
        lines.append(f"- 텍스트를 읽지 못한 연결 파일 {len(files)-ready}개가 있습니다.")
    if not lines[-1].startswith("-"):
        lines.append("- 없음")
    return "\n".join(lines) + "\n"
