import json
from datetime import date
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool

from skive import store
from skive.llm import get_llm
from skive.models import StudySummary
from skive.verify import norm, quote_in_source

STUDY_DIR = store.DATA / "study"

SYSTEM_PROMPT = """너는 학생의 공부 대화를 읽고 공부 기록을 만드는 분석가다.
대화에서 '나:'는 학생, 'SKIVE:'는 챗봇이다.
규칙:
1. 대화에 나온 내용만 쓴다. 대화에 없는 개념을 추가하지 않는다.
2. learned는 학생이 이해했다고 표현했거나 대화에서 정리된 핵심 개념이다.
3. confusions는 학생이 이해하지 못했다·헷갈린다고 말했거나 같은 내용을 반복 질문한 것이다. 없으면 빈 리스트로 둔다.
4. 모든 quote는 대화에서 글자 그대로 복사한다. 요약하거나 표현을 바꾸지 않는다.
5. related_experience_ids는 주어진 경험 목록에서만 고르고, 직접 관련이 없으면 빈 리스트로 둔다."""


def summarize_session(transcript: str, session_id: str) -> dict:
    metas = store.list_meta()
    context = "\n".join(f"- {m['id']}: {m['title']} ({', '.join(m['skills'])})" for m in metas)
    summary: StudySummary = get_llm().with_structured_output(StudySummary).invoke(
        [SystemMessage(SYSTEM_PROMPT), HumanMessage(f"[경험 목록]\n{context}\n\n[대화]\n{transcript}")]
    )

    transcript_norm = norm(transcript)
    dropped = 0

    def keep(items):
        nonlocal dropped
        kept = [i for i in items if quote_in_source(i.quote, transcript_norm)]
        dropped += len(items) - len(kept)
        return kept

    learned, confusions = keep(summary.learned), keep(summary.confusions)
    from skive.recall import recall

    known = {m["id"]: m for m in metas}
    keyword_hits = [
        h["id"].split("/")[0]
        for h in recall(f"{summary.topic} {' '.join(summary.keywords)}", k=5)
        if h["kind"] in ("경험", "원본 자료")
    ]
    related = list(dict.fromkeys([*keyword_hits, *(i for i in summary.related_experience_ids if i in known)]))

    lines = [
        f"# 공부 기록: {summary.topic}",
        f"> {date.today().isoformat()} · 키워드: {', '.join(summary.keywords)}",
        "",
        "## 배운 것",
        *([f"- {i.text}" for i in learned] or ["- 없음"]),
        "",
        "## 아직 헷갈리는 것",
        *([f"- {i.text}" for i in confusions] or ["- 없음"]),
        "",
        "## 복습·면접 질문",
        *[f"- {q}" for q in summary.review_questions],
        "",
        "## 관련 경험",
        *([f"- [{i}] {known[i]['title']}" for i in related] or ["- 없음"]),
    ]
    meta = {
        "id": session_id,
        "topic": summary.topic,
        "date": date.today().isoformat(),
        "keywords": summary.keywords,
        "learned_count": len(learned),
        "confusion_count": len(confusions),
        "related_experience_ids": related,
        "dropped_unverified": dropped,
        "needs_review": bool(confusions),
    }
    folder = STUDY_DIR / session_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (folder / "transcript.txt").write_text(transcript, encoding="utf-8")
    (folder / "metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def list_study() -> list[dict]:
    if not STUDY_DIR.exists():
        return []
    metas = [
        json.loads(p.read_text(encoding="utf-8")) for p in STUDY_DIR.glob("*/metadata.json")
    ]
    return sorted(metas, key=lambda m: m["id"])


def _read_summary(study_id: str) -> str | None:
    path = STUDY_DIR / study_id / "summary.md"
    return path.read_text(encoding="utf-8") if path.is_file() else None


@tool
def search_study(query: str) -> str:
    """공부 기록을 키워드로 검색해 상위 3개의 id, 주제, 날짜, 복습 필요 여부를 반환한다."""
    tokens = [t for t in query.replace(",", " ").split() if len(t) >= 2]
    scored = []
    for m in list_study():
        text = f"{m['topic']} {' '.join(m['keywords'])} {_read_summary(m['id']) or ''}"
        score = sum(text.count(t) for t in tokens)
        if score:
            scored.append((score, m))
    scored.sort(key=lambda x: -x[0])
    lines = [
        f"- id={m['id']} | {m['topic']} | {m['date']} | 복습필요={'예' if m['needs_review'] else '아니오'}"
        for _, m in scored[:3]
    ]
    return "\n".join(lines) or "검색 결과 없음"


@tool
def get_study(study_id: str) -> str:
    """공부 기록 id로 요약 전문(배운 것, 헷갈리는 것, 복습 질문)을 반환한다."""
    return _read_summary(study_id) or f"존재하지 않는 id: {study_id}"
