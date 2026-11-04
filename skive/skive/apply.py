from skive import store
from skive.agent import run_planner
from skive.job import parse_job
from skive.models import Plan, QuestionPlan
from skive.writer import answer_question

DEFAULT_QUESTION = "직무와 관련된 대표 경험을 서술하시오. (600자)"
FALLBACK_TOP_N = 2


def _fallback_ids() -> list[str]:
    metas = [m for m in store.list_meta() if m["my_role_verified"]]
    metas.sort(key=lambda m: m["importance"]["score"], reverse=True)
    return [m["id"] for m in metas[:FALLBACK_TOP_N]]


def _sanitize(plan: Plan, questions: list[str]) -> Plan:
    known = {m["id"] for m in store.list_meta()}
    by_question = {qp.question: qp for qp in plan.question_plans}
    plans = []
    for i, question in enumerate(questions):
        qp = by_question.get(question) or (plan.question_plans[i] if i < len(plan.question_plans) else None)
        if qp is None:
            qp = QuestionPlan(question=question, experience_ids=[], angle="", gap="")
        ids = [x for x in qp.experience_ids if x in known] or _fallback_ids()
        angle = qp.angle or "중요도가 높은 경험 중 문항에 답할 수 있는 부분만 사용"
        plans.append(qp.model_copy(update={"question": question, "experience_ids": ids, "angle": angle}))
    links = [c.model_copy(update={"experience_ids": [x for x in c.experience_ids if x in known]}) for c in plan.competency_links]
    return plan.model_copy(update={"question_plans": plans, "competency_links": links})


def _questions_for_user(plan: Plan, answers: list[dict]) -> list[str]:
    questions, seen = [], set()
    used = {i for a in answers for i in a["experience_ids"]} | {i for c in plan.competency_links for i in c.experience_ids}
    for exp_id in sorted(used):
        meta = store.get_meta(exp_id)
        for q in meta["open_questions"]:
            text = f"[{meta['title']}] {q}"
            if text not in seen:
                seen.add(text)
                questions.append(text)
    for a in answers:
        if a["gap"] and a["status"] in ("근거부족", "통과", "정제", "경고"):
            questions.append(f"[문항 {a['question'][:20]}…] 근거 자료에 없는 내용: {a['gap']}")
    return questions


def run_apply(job_text: str, override_questions: list[str] | None = None) -> dict:
    job = parse_job(job_text)
    if override_questions:
        job = job.model_copy(update={"essay_questions": override_questions})
    questions = job.essay_questions or [DEFAULT_QUESTION]
    plan, trace = run_planner(job)
    plan = _sanitize(plan, questions)
    answers = [answer_question(job, qp) for qp in plan.question_plans]
    return {
        "job": job.model_dump(),
        "plan": plan.model_dump(),
        "trace": trace,
        "answers": answers,
        "questions_for_user": _questions_for_user(plan, answers),
    }
