import math
import re
from pathlib import Path

from skive import store
from skive.loaders import load_folder
from skive.study import STUDY_DIR, list_study

WORD = re.compile(r"[가-힣]{3,}|[A-Za-z][A-Za-z0-9+#-]{1,}")
MAX_LINES = 4
MAX_LINE_CHARS = 200


def _docs() -> list[dict]:
    docs = [
        {"kind": "경험", "id": m["id"], "title": m["title"], "text": store.get_markdown(m["id"]) or ""}
        for m in store.list_meta()
    ]
    for m in store.list_meta():
        by_source: dict[str, list[str]] = {}
        for chunk in load_folder(Path(m["raw_dir"])):
            by_source.setdefault(chunk.source, []).append(chunk.text)
        for source, texts in by_source.items():
            docs.append({"kind": "원본 자료", "id": f"{m['id']}/{source}", "title": m["title"], "text": "\n".join(texts)})
    for m in list_study():
        text = (STUDY_DIR / m["id"] / "summary.md").read_text(encoding="utf-8")
        docs.append({"kind": "공부 기록", "id": m["id"], "title": m["topic"], "text": text})
    return docs


def recall(query: str, k: int = 3, min_score: float = 1.5) -> list[dict]:
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
        matched = [w for w in ws if w in q]
        score = sum(math.log(len(docs) / df[w]) for w in matched)
        if score >= min_score:
            lines = [
                line.strip()[:MAX_LINE_CHARS]
                for line in doc["text"].splitlines()
                if any(w in line.lower() for w in matched) and line.strip()
            ][:MAX_LINES]
            hits.append({**doc, "score": score, "matched": sorted(matched), "lines": lines})
    hits.sort(key=lambda h: -h["score"])
    return hits[:k]


def format_recall(hits: list[dict]) -> str:
    blocks = []
    for h in hits:
        lines = "\n".join(f"  {line}" for line in h["lines"])
        blocks.append(f"[{h['kind']} {h['id']}] {h['title']}\n{lines}")
    return "\n\n".join(blocks)
