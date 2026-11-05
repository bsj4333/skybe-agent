"""Retrieve current, human-reviewed activity facts under the caller's RLS scope."""

from uuid import UUID


def reviewed_facts(conn, terms: list[str], folder_id: UUID | None = None, *, limit=10,
                   all_if_unmatched: bool = False) -> list[dict]:
    """`all_if_unmatched` is for writing: facts the user confirmed must not vanish just because
    the source was English and the search words were Korean."""
    patterns = [f"%{term.replace('%', '').replace('_', '')}%" for term in terms[:6]
                if len(term.strip()) >= 2]
    where = " or ".join("(af.content ilike %s or a.title ilike %s or af.review_note ilike %s)"
                        for _ in patterns)
    match_params = [value for pattern in patterns for value in (pattern, pattern, pattern)]
    folder_filter = "" if folder_id is None else (
        "and f.folder_id in (with recursive scope as ("
        "select id from skive.drive_folders where id=%s and trashed_at is null "
        "union all select child.id from skive.drive_folders child "
        "join scope on child.parent_id=scope.id where child.trashed_at is null) "
        "select id from scope) "
    )
    rows = conn.execute(
        "select af.id,af.activity_id,a.title as activity_title,af.kind,af.content,af.subject,"
        "af.review_note,af.source_file_id as file_id,f.name as file_name,"
        "af.source_file_version as file_version,af.source_chunk_index as chunk_index,"
        "af.source_location as location,af.source_quote as quote "
        "from skive.drive_activity_facts af "
        "join skive.drive_activities a on a.id=af.activity_id and a.user_id=af.user_id "
        "join skive.drive_files f on f.id=af.source_file_id and f.user_id=af.user_id "
        "join skive.drive_activity_files link on link.activity_id=af.activity_id "
        "and link.file_id=f.id and link.user_id=af.user_id "
        "where af.review_state='confirmed' and f.trashed_at is null and a.status<>'excluded' "
        "and not exists (select 1 from skive.drive_file_cards k where k.file_id=f.id and k.owner='other_person') "
        "and f.analysis_status='ready' and f.version=af.source_file_version "
        "and f.analyzed_at is not distinct from af.source_analyzed_at "
        + folder_filter + ("and (" + where + ") " if patterns else "") +
        "order by af.updated_at desc limit %s",
        (*( [folder_id] if folder_id is not None else []), *match_params, limit),
    ).fetchall()
    generic = {"강점", "경험", "성과", "소개", "활동", "프로젝트", "자소서"}
    if not rows and patterns and all_if_unmatched:
        return reviewed_facts(conn, [], folder_id, limit=limit)
    if not rows and patterns and all(term in generic for term in terms if term.strip()):
        return reviewed_facts(conn, [], folder_id, limit=min(limit, 4))
    return [dict(row, index=i) for i, row in enumerate(rows, 1)]
