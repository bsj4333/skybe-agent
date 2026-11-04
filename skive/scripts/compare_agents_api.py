"""Read-only comparison of SKIVE's current chat path with the managed Agents API.

Run from the SKIVE project root. Uses one existing Supabase account and removes
temporary OpenAI sessions. It does not create SKIVE chat records or upload files.
"""

import argparse
from pathlib import Path
import json
import os
import time
from uuid import UUID

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from openai import OpenAI
from psycopg.conninfo import make_conninfo

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
# The configured 5432 pooler timed out during this run; 6543 connected.
os.environ["DATABASE_URL"] = make_conninfo(os.environ["DATABASE_URL"], port=6543)

from skive.db import get_connection  # noqa: E402
from skive.drive_db import user_connection  # noqa: E402
from skive.drive_workspace import _keywords, _sources  # noqa: E402
from skive.llm import get_llm  # noqa: E402


QUESTION = (
    "화력발전소 이상탐지의 오탐 감소 실험에서 F1 최고 후보와 운영 추천 후보의 "
    "F1, 이상 발생 전 오탐률, 리드타임을 비교해줘. 이 자료만으로 내가 직접 "
    "모델을 만들었다고 말할 수 있는지도 구분해줘."
)
INSTRUCTIONS = (
    "너는 SKIVE의 개인 자료 조사 도우미다. 답하기 전에 반드시 search_my_drive로 "
    "이 계정의 원문을 찾는다. 필요하면 검색어를 바꿔 다시 찾거나 read_chunk로 "
    "더 읽는다. 수치는 파일명과 위치를 포함한 [S번호]로 인용한다. 파일에 적힌 "
    "프로젝트 결과를 사용자의 개인 기여로 단정하지 않는다. 근거가 없으면 확인 "
    "질문을 한다. 한국어로 간결하게 답한다."
)


def account_id() -> UUID:
    with get_connection() as conn:
        rows = conn.execute(
            "select user_id,count(*) from skive.drive_files where trashed_at is null "
            "group by user_id order by count(*) desc"
        ).fetchall()
    if len(rows) != 1:
        raise RuntimeError(f"Expected one test account; found {len(rows)}")
    return rows[0][0]


def source_rows(user_id: UUID, query: str, limit: int = 10):
    with user_connection(user_id) as conn:
        terms = _keywords(query)
        rows = _sources(conn, query, None, terms=terms, limit=limit)
    return terms, rows


def baseline(user_id: UUID):
    started = time.perf_counter()
    terms, rows = source_rows(user_id, QUESTION)
    context = "\n\n".join(
        f"[{row['index']}] {row['name']} | {row['location']} | chunk {row['chunk_index']}\n"
        f"{row['excerpt']}" for row in rows
    )
    response = get_llm().invoke([
        SystemMessage(
            "너는 SKIVE 개인 자료 도우미다. 제공된 원문만 근거로 답하고 [번호]로 인용한다. "
            "프로젝트 결과를 사용자 개인의 기여로 단정하지 않는다. 불명확하면 질문한다."
        ),
        HumanMessage(f"자료:\n{context or '검색 결과 없음'}\n\n질문: {QUESTION}"),
    ])
    return {
        "variant": "current_gpt_4o_mini",
        "seconds": round(time.perf_counter() - started, 2),
        "terms": terms,
        "source_count": len(rows),
        "source_names": [row["name"] for row in rows],
        "answer": str(response.content),
        "answer_tokens": (response.usage_metadata or {}).get("output_tokens"),
    }


def agent(user_id: UUID, model: str):
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"], timeout=120)
    source_by_marker: dict[tuple[str, int], dict] = {}
    calls: list[dict] = []
    session_id = None
    started = time.perf_counter()

    def search_my_drive(args):
        query = str(args.get("query", ""))[:300]
        terms, rows = source_rows(user_id, query, limit=8)
        hits = []
        for row in rows:
            marker = (row["file_id"], row["chunk_index"])
            if marker not in source_by_marker:
                source_by_marker[marker] = dict(row, source_id=f"S{len(source_by_marker) + 1}")
            known = source_by_marker[marker]
            hits.append({
                "source_id": known["source_id"], "name": row["name"],
                "location": row["location"], "chunk_index": row["chunk_index"],
                "excerpt": row["excerpt"][:2200],
            })
        calls.append({"tool": "search", "query": query, "terms": terms, "hits": len(hits)})
        return json.dumps(hits, ensure_ascii=False)

    def read_chunk(args):
        source_id = str(args.get("source_id", ""))
        source = next((row for row in source_by_marker.values()
                       if row["source_id"] == source_id), None)
        if source is None:
            return json.dumps({"error": "Unknown source ID"})
        with user_connection(user_id) as conn:
            row = conn.execute(
                "select c.text from skive.drive_file_chunks c "
                "join skive.drive_files f on f.id=c.file_id and f.user_id=c.user_id "
                "where c.file_id=%s and c.chunk_index=%s and f.trashed_at is null "
                "and f.analysis_status='ready'",
                (source["file_id"], source["chunk_index"]),
            ).fetchone()
        calls.append({"tool": "read", "source_id": source_id})
        return json.dumps({"source_id": source_id, "text": row["text"][:6000]
                           if row else None}, ensure_ascii=False)

    tools = [
        {"type": "function", "name": "search_my_drive",
         "description": "Search this signed-in user's readable Supabase drive files. Returns source IDs, locations and excerpts.",
         "parameters": {"type": "object", "properties": {"query": {"type": "string"}},
                        "required": ["query"], "additionalProperties": False}},
        {"type": "function", "name": "read_chunk",
         "description": "Read more text from a source ID returned by search_my_drive.",
         "parameters": {"type": "object", "properties": {"source_id": {"type": "string"}},
                        "required": ["source_id"], "additionalProperties": False}},
    ]
    try:
        with client.beta.agents.sessions.create(
            agent={"model": model, "instructions": INSTRUCTIONS, "tools": tools},
            environment={"type": "none"}, input="설정 확인. READY라고만 답해.", stream=True,
        ) as events:
            for event in events:
                session = getattr(event, "session", None)
                session_id = getattr(session, "id", None) or session_id
        if not session_id:
            raise RuntimeError("Session ID absent")
        completed = False
        with client.beta.agents.sessions.stream(
            session_id, input=QUESTION,
            tool_handlers={"search_my_drive": search_my_drive, "read_chunk": read_chunk},
            timeout=120,
        ) as events:
            for event in events:
                if getattr(event, "type", "") == "agent.session.turn.completed":
                    completed = True
        page = client.beta.agents.sessions.items.list(session_id, order="asc", limit=100)
        item_dicts = [item.model_dump() for item in page.data]
        texts = []
        for item in item_dicts:
            if item.get("role") != "assistant":
                continue
            for part in item.get("content") or []:
                if isinstance(part, dict):
                    value = part.get("text")
                    if isinstance(value, str):
                        texts.append(value)
        return {
            "variant": "agents_api_" + model,
            "seconds": round(time.perf_counter() - started, 2),
            "completed": completed,
            "calls": calls,
            "source_count": len(source_by_marker),
            "source_names": [row["name"] for row in source_by_marker.values()],
            "answer": texts[-1] if texts else "",
            "item_shapes": [(item.get("type"), item.get("role")) for item in item_dicts],
        }
    finally:
        if session_id:
            client.beta.agents.sessions.delete(session_id)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", choices=["baseline", "agent"], required=True)
    parser.add_argument("--agent-model", default="gpt-6-astra")
    args = parser.parse_args()
    user_id = account_id()
    result = baseline(user_id) if args.variant == "baseline" else agent(user_id, args.agent_model)
    print(json.dumps(result, ensure_ascii=True))
