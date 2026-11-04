import os
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage

from skive import facts as facts_v2
from skive import verify
from skive.llm import get_llm
from skive.loaders import Chunk, load_folder
from skive.models import UNKNOWN, Evidence, Experience, Fact
from skive.verify import norm, quote_in_source

# 폴더 전체를 한 번의 LLM 호출로 분석하는 지금 방식의 상한. 60,000자(원래 값)는 초기
# 샘플 데이터(경험 6개, 청크 17개) 기준으로 잡은 보수적인 값이었는데, 실사용자 폴더는
# 쉽게 이걸 넘는다(실측, 2026-09-23).
#
# 320,000자는 추측이 아니라 실측 기반이다: 실사용자 폴더(캡스톤, 파일 365개 — CSV 76개·
# 코드 17개·md 19개) 하나를 tiktoken(o200k_base)으로 재보니 295,492자가 정확히 100,897
# 토큰이었다(문자당 약 2.93토큰). gpt-4o-mini 컨텍스트 128K 토큰 기준으로 이 폴더는
# 시스템 프롬프트·출력 여유분까지 포함해도 안전하게 들어간다. **단, 이건 로더가 CSV를
# 미리보기로 줄인(loaders.py CSV_PREVIEW_CHARS) *이후* 수치다** — 그 전에는 같은 폴더가
# 7,948,547자였다. 즉 이 상한을 올린 것과 별개로, 애초에 "숫자 나열 원본 데이터를 통째로
# LLM에 넣지 않는다"는 로더 쪽 수정이 실제 해결책이었다. 이 상한은 안전판일 뿐이고, 이걸
# 넘으면 여전히 실패한다 — 진짜 임의로 큰 폴더를 처리하려면 청크를 나눠서 여러 번 분석하고
# 합치는 것(map-reduce)이 필요한데 아직 미구현이다.
MAX_CHARS = int(os.environ.get("SKIVE_ANALYZER_MAX_CHARS", "320000"))

SYSTEM_PROMPT = f"""너는 대학생의 프로젝트·수업·활동 자료를 읽고 경험 기록(experience)을 만드는 분석가다.
입력은 [C숫자] (파일, 위치) 헤더로 구분된 원문 조각들이다. 근거를 댈 때는 이 C숫자를 chunk_id로 쓴다.

규칙:
1. 입력에 있는 사실만 쓴다. 입력에 없는 내용은 절대 추측하지 말고 '{UNKNOWN}'으로 쓴다.
2. 본인의 역할은 사용자가 알려준 이름이 역할표·코드 작성자 표기·'작성자'·'개인 프로젝트' 표기 등에 명시된 경우에만 쓴다.
   '우리 팀은 ~했다' 같은 표현만으로 본인이 한 일이라고 단정하지 않는다.
   근거가 없으면 my_role은 '{UNKNOWN}', my_role_evidence는 빈 리스트로 두고 open_questions에 사용자에게 물어볼 구체적 질문을 적는다.
3. 각 사실의 owner는 본인이 직접 한 일로 원문에서 확인될 때만 '본인', 그 외(팀 전체, 다른 팀원, 불명확)는 '팀'이다.
4. 수치는 원문 그대로 옮기고 계산하거나 반올림하지 않는다.
5. 모든 근거의 quote는 해당 chunk_id 조각에서 글자 그대로 복사한다. 요약하거나 표현을 바꾸지 않는다.
6. 시행착오·의사결정은 회의록, 노트, 코드 주석 등 원문에 드러난 것만 쓴다.
7. skills에는 원문에 등장한 기술·도구·라이브러리(코드의 import 포함)를 적는다.
8. lessons는 원문에 '배운 점'·'소감'으로 명시된 내용만 쓴다. 없으면 '{UNKNOWN}'.
9. resume_draft는 actions/decisions_and_trials/results에 이미 쓴 사실만 문장으로 다시 엮는다. 새 수치나
   사실을 만들어내지 않는다. my_role이 '{UNKNOWN}'이면 주어를 '팀은'으로 쓴다.
10. gaps_to_fill은 이 경험을 자소서·포트폴리오 소재로 쓸 때 아쉬운 부분을 구체적으로 적는다
    (예: "정확한 참여 기간 불명", "최종 정확도 수치 없음"). open_questions와 달리 필수 확인 사항이
    아니라 '있으면 더 강해지는 것'이다. 없으면 빈 리스트."""


def _where(ev: Evidence, chunks: dict[str, Chunk]) -> str:
    chunk = chunks.get(ev.chunk_id)
    return f"{chunk.source} @ {chunk.location}" if chunk else f"존재하지 않는 조각 {ev.chunk_id}"


def _inspect(ev: Evidence, chunks: dict[str, Chunk], claim: str) -> dict:
    """근거 하나를 네 가지로 나눠 검사한다 (F03).

    예전에는 "인용문이 원문에 있는가" 하나만 봤다. 그래서 원문에 실제로 있는
    `팀은 보고서를 작성했다.`를 인용하면서 `내가 Kubernetes 클러스터를 구축했다.`를
    주장해도 검증 통과였다. quote 자체도 저장하지 않아 사후 감사조차 불가능했다.
    """
    chunk = chunks.get(ev.chunk_id)
    matched = chunk is not None and quote_in_source(ev.quote, norm(chunk.text))
    missing = verify.numbers_missing_from(claim, ev.quote) if matched else []
    rec = {
        "chunk_id": ev.chunk_id,
        "source": chunk.source if chunk else None,
        "location": chunk.location if chunk else None,
        "quote": ev.quote,  # ← 반드시 저장. 없으면 나중에 아무도 재검증할 수 없다
        "quote_matched": matched,
        "supports_claim": matched and verify.supports_claim(claim, ev.quote),
        "owner_match": not (matched and verify.owner_conflict(claim, ev.quote)),
        "numbers_missing": missing,
    }
    rec["ok"] = bool(
        matched and rec["supports_claim"] and rec["owner_match"] and not missing
    )
    return rec


def _reason(rec: dict) -> str:
    if not rec["quote_matched"]:
        return "미확인 근거"
    if not rec["owner_match"]:
        return "근거 불충분(인용문의 주체가 본인이 아님)"
    if not rec["supports_claim"]:
        return "근거 불충분(인용문이 주장과 무관)"
    if rec["numbers_missing"]:
        return f"근거 불충분(인용문에 없는 수치 {', '.join(rec['numbers_missing'])})"
    return "근거"


def _process(facts: list[Fact], chunks: dict[str, Chunk], stats: dict, owner: str | None) -> list[dict]:
    out = []
    for f in facts:
        records, tags = [], []
        for ev in f.evidence:
            rec = _inspect(ev, chunks, f.text)
            records.append(rec)
            stats["total"] += 1
            stats["verified"] += int(rec["ok"])
            tags.append(f"[{_reason(rec)}: {_where(ev, chunks)}]")
        out.append(
            facts_v2.document_fact(f.text, owner or f.owner, records, tag=" ".join(tags))
        )
    return out


def _fact_lines(entries: list[dict]) -> list[str]:
    if not entries:
        return [f"- {UNKNOWN}"]
    return [f"- ({e['owner']}) {e['text']} {e['tag']}" for e in entries]


def _star_summary(problem: str, role: str, role_tags: str, actions: list[dict],
                   decisions: list[dict], results: list[dict]) -> list[str]:
    """이미 뽑아둔 사실을 S/T/A/R로 재배열만 한다 — 새 LLM 호출 없이 만드는 빠른 요약본.

    사용자 피드백(2026-09-23): "정리본"이라고 부를 만한 요약이 experience.md 맨 위에
    있어야 한다는 지적. 아래 상세 Action/Decision/Results 섹션이 원자료이고, 이건 그걸
    한눈에 볼 수 있게 압축한 것 — 근거는 여전히 아래 상세 섹션의 태그에 있다."""
    def top(entries: list[dict], n: int = 3) -> str:
        picked = [f"{e['text']}" for e in entries[:n]]
        return "; ".join(picked) if picked else f"{UNKNOWN}"

    task = f"{role} {role_tags}".strip() if role != UNKNOWN else UNKNOWN
    return [
        "## STAR 요약",
        f"- **S (상황)**: {problem or UNKNOWN}",
        f"- **T (역할)**: {task}",
        f"- **A (행동)**: {top(actions + decisions)}",
        f"- **R (결과)**: {top(results)}",
    ]


def analyze_folder(root: Path, me: str, exp_id: str, grade: int) -> tuple[str, dict, dict]:
    chunks = {f"C{i}": c for i, c in enumerate(load_folder(root), start=1)}
    corpus = "\n\n".join(
        f"[{cid}] (파일: {c.source}, 위치: {c.location})\n{c.text}" for cid, c in chunks.items()
    )
    if len(corpus) > MAX_CHARS:
        raise ValueError(f"폴더가 너무 큼({len(corpus):,}자 > {MAX_CHARS:,}자). 분할 요약 단계는 아직 미구현")

    exp: Experience = get_llm().with_structured_output(Experience).invoke(
        [SystemMessage(SYSTEM_PROMPT), HumanMessage(f"본인 이름: {me}\n\n{corpus}")]
    )

    stats = {"total": 0, "verified": 0}
    role, role_tags, role_verified, role_evidence = exp.my_role, "", False, []
    if role != UNKNOWN:
        # 역할은 가장 오용되기 쉬운 필드라 사실과 똑같은 4가지 검사를 그대로 적용한다.
        role_evidence = [_inspect(ev, chunks, exp.my_role) for ev in exp.my_role_evidence]
        stats["total"] += len(role_evidence)
        stats["verified"] += sum(r["ok"] for r in role_evidence)
        passed = [r for r in role_evidence if r["ok"]]
        if passed:
            role_verified = True
            role_tags = " ".join(f"[근거: {r['source']} @ {r['location']}]" for r in passed)
        else:
            why = _reason(role_evidence[0]) if role_evidence else "근거 없음"
            role = f"{UNKNOWN} (모델이 '{exp.my_role}'라고 했으나 {why})"

    force_team = None if role_verified else "팀"
    actions = _process(exp.actions, chunks, stats, force_team)
    decisions = _process(exp.decisions_and_trials, chunks, stats, force_team)
    results = _process(exp.results, chunks, stats, "팀")
    sources = sorted({c.source for c in chunks.values()})

    lines = [
        f"# {exp.title}",
        f"> {exp.summary}",
        "",
        "## Overview",
        f"- 유형: {exp.kind}",
        f"- 학년: {grade}학년",
        f"- 기간: {exp.period}",
        f"- 소속/유형: {exp.organization}",
        "",
        *_star_summary(exp.problem, role, role_tags, actions, decisions, results),
        "",
        "## Problem",
        exp.problem,
        "",
        "## My Role",
        f"{role} {role_tags}".strip(),
        "",
        "## Action",
        *_fact_lines(actions),
        "",
        "## Technical Decisions / Trial & Error",
        *_fact_lines(decisions),
        "",
        "## Results",
        *_fact_lines(results),
        "",
        "## Skills / Tools",
        ", ".join(exp.skills) or UNKNOWN,
        "",
        "## Lessons",
        exp.lessons,
        "",
        "## 자소서 표현 초안 (AI 해석 — 검토 필요)",
        exp.resume_draft or UNKNOWN,
        "",
        "## Evidence (원본 파일)",
        *[f"- {s}" for s in sources],
    ]
    if exp.gaps_to_fill:
        lines += ["", "## 채워야 할 것 (있으면 더 강해짐)", *[f"- {g}" for g in exp.gaps_to_fill]]
    if exp.open_questions:
        lines += ["", "## Open Questions (사용자 확인 필요)", *[f"- {q}" for q in exp.open_questions]]

    meta = {
        "id": exp_id,
        "title": exp.title,
        "summary": exp.summary,
        "kind": exp.kind,
        "grade": grade,
        "period": exp.period,
        "skills": exp.skills,
        "raw_dir": str(root.resolve()),
        "sources": sources,
        "evidence_total": stats["total"],
        "evidence_verified": stats["verified"],
        "my_role_verified": role_verified,
        "open_questions": exp.open_questions,
        "gaps_to_fill": exp.gaps_to_fill,
    }
    facts = {
        "title": exp.title,
        "summary": exp.summary,
        "period": exp.period,
        "my_role": role,
        "my_role_verified": role_verified,
        "my_role_provenance": facts_v2.DOCUMENT,
        "my_role_evidence_status": (
            facts_v2.QUOTE_MATCHED if role_verified
            else facts_v2.NEEDS_REVIEW if role_evidence
            else facts_v2.UNLINKED
        ),
        "my_role_evidence": role_evidence,
        "actions": actions,
        "decisions": decisions,
        "results": results,
        "skills": exp.skills,
        "lessons": exp.lessons,
        "resume_draft": exp.resume_draft,
        "gaps_to_fill": exp.gaps_to_fill,
    }
    return "\n".join(lines) + "\n", meta, facts
