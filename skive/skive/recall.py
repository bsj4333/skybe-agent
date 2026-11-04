import math
import re

from skive import store
from skive.chunks_store import keyword_source_docs, vector_search
from skive.study import STUDY_DIR, list_study

WORD = re.compile(r"[가-힣]{3,}|[A-Za-z][A-Za-z0-9+#-]{1,}")
MAX_LINES = 4
MAX_LINE_CHARS = 200
VECTOR_K = 5
VECTOR_MIN_SIMILARITY = 0.3


def _docs() -> list[dict]:
    metas = store.list_meta()
    titles = {m["id"]: m["title"] for m in metas}
    docs = [{"kind": "경험", "id": m["id"], "title": m["title"], "text": store.get_markdown(m["id"]) or ""} for m in metas]
    for d in keyword_source_docs():
        docs.append(
            {
                "kind": "원본 자료",
                "id": f"{d['experience_id']}/{d['source']}",
                "title": titles.get(d["experience_id"], d["experience_id"]),
                "text": d["text"],
            }
        )
    for m in list_study():
        text = (STUDY_DIR / m["id"] / "summary.md").read_text(encoding="utf-8")
        docs.append({"kind": "공부 기록", "id": m["id"], "title": m["topic"], "text": text})
    return docs


def _in_scope(doc: dict, scope_id: str | None) -> bool:
    if scope_id is None:
        return True
    if doc["kind"] == "공부 기록":
        return False
    return doc["id"] == scope_id or doc["id"].startswith(scope_id + "/")


def _lines_matching(text: str, matched: list[str]) -> list[str]:
    return [
        line.strip()[:MAX_LINE_CHARS]
        for line in text.splitlines()
        if any(w in line.lower() for w in matched) and line.strip()
    ][:MAX_LINES]


def _keyword_hits(query: str, scope_id: str | None, min_score: float) -> list[dict]:
    """정확한 단어가 겹치는 기록을 찾는다. idf는 항상 전체 자료 기준으로 계산한다 —
    scope로 문서 풀을 줄이면 흔한 단어도 상대적으로 희귀해져 min_score 미달로 못 찾게 된다."""
    docs = _docs()
    if not docs:
        return []
    words = [{w.lower() for w in WORD.findall(d["text"])} for d in docs]
    df: dict[str, int] = {}
    for ws in words:
        for w in ws:
            df[w] = df.get(w, 0) + 1
    q = query.lower()

    hits = []
    for doc, ws in zip(docs, words):
        if not _in_scope(doc, scope_id):
            continue
        matched = [w for w in ws if w in q]
        score = sum(math.log(len(docs) / df[w]) for w in matched)
        if score >= min_score:
            hits.append({**doc, "score": score, "matched": sorted(matched), "lines": _lines_matching(doc["text"], matched)})
    return hits


def _vector_hits(query: str, scope_id: str | None) -> list[dict]:
    """정확한 단어가 안 겹쳐도(패러프레이즈) 의미가 비슷한 원본 자료를 찾는다."""
    titles = {m["id"]: m["title"] for m in store.list_meta()}
    hits = []
    for r in vector_search(query, VECTOR_K, exp_id=scope_id):
        if r["similarity"] < VECTOR_MIN_SIMILARITY:
            continue
        lines = [line.strip()[:MAX_LINE_CHARS] for line in r["text"].splitlines() if line.strip()][:MAX_LINES]
        hits.append(
            {
                "kind": "원본 자료",
                "id": f"{r['experience_id']}/{r['source']}",
                "title": titles.get(r["experience_id"], r["experience_id"]),
                "text": r["text"],
                # 키워드 점수(로그 idf 합, 보통 1.5~5대)와 대략 같은 자릿수로 맞추기 위한 스케일링 — 정밀한 보정은 아님
                "score": r["similarity"] * 10,
                "matched": [],
                "lines": lines,
            }
        )
    return hits


def recall(query: str, k: int = 3, min_score: float = 1.5, scope_id: str | None = None) -> list[dict]:
    keyword = _keyword_hits(query, scope_id, min_score)
    vector = _vector_hits(query, scope_id)
    merged: dict[tuple[str, str], dict] = {}
    for h in keyword + vector:
        key = (h["kind"], h["id"])
        if key not in merged or h["score"] > merged[key]["score"]:
            merged[key] = h
    hits = sorted(merged.values(), key=lambda h: -h["score"])
    return hits[:k]


def format_recall(hits: list[dict]) -> str:
    blocks = []
    for h in hits:
        lines = "\n".join(f"  {line}" for line in h["lines"])
        blocks.append(f"[{h['kind']} {h['id']}] {h['title']}\n{lines}")
    return "\n\n".join(blocks)
