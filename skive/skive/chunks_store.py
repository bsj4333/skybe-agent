"""원본 파일 청크 + 임베딩을 skive.chunks(Postgres/pgvector)에 저장·검색.

전에는 recall()이 호출될 때마다 load_folder()로 원본 PDF/PPTX를 처음부터 다시 파싱했다.
여기서는 ingest 시점에 딱 한 번 파싱+임베딩해서 DB에 저장해두고, 이후 검색은 DB만 읽는다.
experiences/facts 자체는 아직 이 DB로 안 옮겼다 — SCHEMA.md 4절 참고. 그래서 chunks는
skive.experiences(uuid)가 아니라 지금 앱 전역이 쓰는 slug 문자열로 바로 식별한다.
"""

from pathlib import Path

from skive.db import get_connection
from skive.embeddings import embed_query, embed_texts
from skive.loaders import load_folder


def _vec_literal(embedding: list[float]) -> str:
    return "[" + ",".join(f"{x:.8f}" for x in embedding) + "]"


def sync_chunks(exp_id: str, raw_dir: Path) -> int:
    """raw_dir을 다시 읽어 exp_id의 청크+임베딩을 DB에 새로 쓴다 (기존 건 지우고 새로 넣음).
    ingest 시점에 한 번만 부르면 된다. 원본 파일이 안 바뀌었으면 다시 부를 필요 없다."""
    chunks = load_folder(Path(raw_dir))
    if not chunks:
        return 0
    embeddings = embed_texts([c.text for c in chunks])
    with get_connection() as conn:
        conn.execute("delete from skive.chunks where experience_id = %s", (exp_id,))
        for chunk, embedding in zip(chunks, embeddings):
            conn.execute(
                "insert into skive.chunks (experience_id, source, location, text, embedding, token_count) "
                "values (%s, %s, %s, %s, %s::vector, %s)",
                (exp_id, chunk.source, chunk.location, chunk.text, _vec_literal(embedding), len(chunk.text) // 4),
            )
        conn.commit()
    return len(chunks)


def has_chunks(exp_id: str) -> bool:
    with get_connection() as conn:
        row = conn.execute("select 1 from skive.chunks where experience_id = %s limit 1", (exp_id,)).fetchone()
    return row is not None


def keyword_source_docs(exp_id: str | None = None) -> list[dict]:
    """청크를 (experience_id, source)별로 묶어서 recall.py의 '원본 자료' 문서 형태로 돌려준다.
    원본 파일을 다시 파싱하지 않고 DB에 저장된 텍스트만 읽는다."""
    sql = "select experience_id, source, text from skive.chunks"
    params: tuple = ()
    if exp_id:
        sql += " where experience_id = %s"
        params = (exp_id,)
    sql += " order by experience_id, source, location"
    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    by_key: dict[tuple[str, str], list[str]] = {}
    for experience_id, source, text in rows:
        by_key.setdefault((experience_id, source), []).append(text)
    return [
        {"experience_id": eid, "source": source, "text": "\n".join(texts)}
        for (eid, source), texts in by_key.items()
    ]


def vector_search(query: str, k: int, exp_id: str | None = None) -> list[dict]:
    """질문을 임베딩해서 코사인 유사도로 가장 가까운 청크 k개를 찾는다 (정확한 단어가 안 겹쳐도 찾음)."""
    query_vec = _vec_literal(embed_query(query))
    sql = (
        "select experience_id, source, location, text, 1 - (embedding <=> %s::vector) as similarity "
        "from skive.chunks where embedding is not null "
    )
    params: list = [query_vec]
    if exp_id:
        sql += "and experience_id = %s "
        params.append(exp_id)
    sql += "order by embedding <=> %s::vector limit %s"
    params += [query_vec, k]
    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [
        {"experience_id": r[0], "source": r[1], "location": r[2], "text": r[3], "similarity": r[4]} for r in rows
    ]
