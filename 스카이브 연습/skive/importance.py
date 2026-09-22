from langchain_core.messages import HumanMessage, SystemMessage

from skive.llm import get_llm
from skive.models import ImportanceLLM

RUBRIC = """경험 기록의 '검증된 사실'만 보고 채점한다. 입력에 없는 내용은 가정하지 않는다.
- impact(0~3): 0=결과 불명, 1=정성적 결과만, 2=정량적 개선이 있음, 3=정량 개선이 크고 의미가 분명함
- uniqueness(0~3): 0=수업 실습이나 흔한 과제, 1=일반적인 팀 활동, 2=문제 정의나 접근이 독자적, 3=시행착오와 의사결정이 뚜렷함
- goal_relevance(0~3): 진로 목표와의 관련성. 0=무관, 3=직접 관련
reason에는 점수를 준 근거를 한두 문장으로 쓴다."""

MAX_SCORE = 15


def _clamp(value: int) -> int:
    return max(0, min(3, int(value)))


def score_importance(meta: dict, facts: dict, goal: str) -> dict:
    verified = [
        f"- ({f['owner']}) {f['text']}"
        for key in ("actions", "decisions", "results")
        for f in facts[key]
        if f["verified"]
    ]
    text = (
        f"제목: {facts['title']}\n요약: {facts['summary']}\n기간: {facts['period']}\n"
        f"본인 역할: {facts['my_role']}\n검증된 사실:\n" + "\n".join(verified)
    )
    llm = get_llm().with_structured_output(ImportanceLLM)
    r: ImportanceLLM = llm.invoke([SystemMessage(RUBRIC), HumanMessage(f"진로 목표: {goal}\n\n{text}")])

    role_pts = 2 if facts["my_role_verified"] else 0
    quantified = any(any(ch.isdigit() for ch in f["text"]) for f in facts["results"] if f["verified"])
    quant_pts = 2 if quantified else 0
    total_ev = meta["evidence_total"]
    evidence_pts = round(2 * meta["evidence_verified"] / total_ev) if total_ev else 0

    breakdown = {
        "role_verified": role_pts,
        "quantified_result": quant_pts,
        "evidence_ratio": evidence_pts,
        "impact": _clamp(r.impact),
        "uniqueness": _clamp(r.uniqueness),
        "goal_relevance": _clamp(r.goal_relevance),
    }
    score = sum(breakdown.values())
    tier = "핵심" if score >= 12 and facts["my_role_verified"] else "활성" if score >= 6 else "보관"
    return {"score": score, "max": MAX_SCORE, "tier": tier, "breakdown": breakdown, "reason": r.reason}
