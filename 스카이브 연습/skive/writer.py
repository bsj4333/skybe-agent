import re

from langchain_core.messages import HumanMessage, SystemMessage

from skive import facts as facts_v2
from skive import store
from skive.llm import get_judge_llm, get_llm
from skive.models import UNKNOWN, Answerability, JobRequirements, JudgeResult, QuestionPlan, SentenceCheck
from skive.user import load_user
from skive.verify import job_ascii_terms, terms_only_in_job, unsupported_numbers

MAX_REPAIR = 2
NO_EXPERIENCE = "연결 가능한 경험 없음"

# 문장 하나를 가리키는 안정적인 이름. 판정자가 문장을 "글자 그대로 옮기라"고 시켜도
# 실제로는 살짝 바꿔 돌려주는 경우가 있었고(예: "이뤘습니다" → "이루었습니다"), 그러면
# 원문 문자열 매칭으로 삭제하려던 코드가 조용히 실패해서 문제 문장이 초안에 남았는데도
# 상태는 '정제'로 표시됐다(F04). ID로 가리키면 판정자가 뭐라고 베껴 쓰든 우리 쪽 원문
# 문장 리스트에서 정확히 그 위치를 찾아 지울 수 있다.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")

# 절대 안 바뀌는 규칙 — 아래 [스타일 지침](사용자가 data/user.json의 essay_style로 바꿀 수 있음)이
# 뭐라고 하든 이 규칙이 항상 이긴다. 그래야 스타일을 바꿔도 "없는 사실 지어내기"로 새지 않는다.
WRITER_CORE_RULES = f"""자기소개서 문항 하나에 대한 답변을 쓴다. 분량은 문항에 표기된 글자 수 안팎이다.
[근거 자료]에 있는 사실만 쓸 수 있다. 아래 [스타일 지침]과 이 규칙이 충돌하면 이 규칙을 따른다.
규칙:
1. '내가/저는 ~했다'는 [본인이 한 일]에 있는 내용에만 쓴다.
2. [팀·프로젝트 활동]과 [프로젝트 성과]는 '팀은', '프로젝트에서'처럼 주체를 팀으로 쓴다. 성과를 내가 달성한 것처럼 쓰지 않는다.
   성과 문장은 '프로젝트 결과,'나 '이 프로젝트에서'로 시작하고, 앞 문장의 내 행동과 인과로 묶지 않는다.
   (금지: '내가 만든 모델로 F1이 올랐다', '이러한 개선을 통해 F1이 올랐다' / 가능: '프로젝트 결과, F1이 0.62에서 0.78로 향상되었다')
3. 본인 역할이 '미확인'인 경험은 어떤 것도 '내가 했다'고 쓰지 않는다.
4. [배운 점] 항목이 있으면 그 내용을 우선 활용한다. 없어도 성장·소감·깨달음 문장은 쓸 수 있다 —
   단, [본인이 한 일]/[팀·프로젝트 활동]/[프로젝트 성과]에 있는 사실에서 자연스럽게 이어지는
   내용만 쓴다. 그 소감 문장 안에서도 자료에 없는 새 역량·자격·수치·구체적 사건을 지어내지 않고,
   위 1~3번 규칙(본인/팀 구분, 역할 미확인)을 그대로 따른다.
5. 자료에 없는 기술·도구·수치·활동·상황(예: 논의, 합의, 갈등)을 쓰지 않는다. 수치는 자료 그대로 쓴다.
6. 문항이 요구하는 내용 중 자료에 없는 부분은 쓰지 말고, 자료로 답할 수 있는 범위만 쓴다.
   답할 수 있는 내용이 전혀 없으면 '{NO_EXPERIENCE}'라고만 쓴다.
7. [본인 진술] 항목은 사용자가 직접 말한 내용이고 원문 근거가 없다. 본인이 한 일로 쓸 수 있지만,
   그 문장에 없는 수치·기술명·기간을 덧붙여 보강하지 않는다. [프로젝트 성과]의 수치를 끌어와
   본인 진술과 인과로 묶지 않는다."""

# 사용자가 PUT /api/user 의 essay_style 필드로 자유롭게 바꿀 수 있는 부분. 문체·구조·페르소나 지침.
DEFAULT_STYLE = """너는 10년차 자기소개서 컨설턴트다. 인재상과 문항의 의도에 맞춰 자소서를 작성한다.
- 경험을 서술할 때는 STAR(상황-과제-행동-결과) 구조로 쓴다.
- 지원동기 문항은 '지원 직무에 관심을 갖게 된 계기 → 이를 위해 준비한 과정 → 이 회사·직무를 선택한 이유' 순서로 쓴다.
- 장단점 문항은 장점은 근거 사실로 뒷받침하고, 단점은 이를 보완하기 위해 실제로 한 행동과 함께 쓴다.
- [프로필]에 있는 역량·성향·진로 목표를 참고해서, 이 경험이 어떤 역량을 보여주는지 자연스럽게 연결한다."""


def _writer_prompt() -> str:
    style = load_user().get("essay_style") or DEFAULT_STYLE
    return f"{WRITER_CORE_RULES}\n\n[스타일 지침]\n{style}"

JUDGE_PROMPT = """너는 자기소개서 초안의 사실 검증관이다. [근거 자료]가 사실의 전부다.
초안은 [S1], [S2]처럼 문장마다 ID가 붙어 입력된다. **입력에 있는 모든 ID에 대해 빠짐없이
검사 결과를 하나씩 반환한다.** 없는 ID를 만들어내지 않는다.
- supported: 자료로 확인되는 사실이거나, 자료의 사실에서 자연스럽게 이어지는 소감·성장·깨달음
  문장(그 문장 안에서 자료에 없는 새 역량·자격·수치·구체적 사건을 덧붙이지 않는 한)
- unsupported: 자료에 없는 사실, 기술, 수치, 상황. 소감·성장 문장이라도 자료에 없는 구체적
  내용(예: 언급 없는 자격증, 수치, 사건)을 새로 주장하면 unsupported다
- misattributed: 자료에서는 팀·프로젝트가 한 일이거나 본인 역할이 미확인인데 '내가/저는' 했다고
  쓴 문장, 또는 팀 성과를 본인이 달성한 것처럼 쓴 문장 — 소감·성장 문장도 이 기준을 똑같이 적용한다
  (예: 역할 미확인인데 "리더십을 발휘했다는 걸 배웠다"는 misattributed)
엄격하게 판정하고, sentence_id에는 입력에 붙어 있던 ID를 그대로 쓰고 reason을 쓴다."""

GATE_PROMPT = """자기소개서 [문항]이 요구하는 내용을 [근거 자료]가 실제로 담고 있는지 판정한다.
- 가능: 문항의 핵심 요구를 자료만으로 답할 수 있다.
- 부분: 일부만 답할 수 있다. (예: 준비 과정은 있지만 지원 동기는 자료에 없음)
- 불가: 문항이 요구하는 핵심 상황이 자료에 없다.
관련 있어 보이는 사실이 있어도, 문항이 요구한 상황 자체(예: 갈등, 의견 충돌, 실패 극복)가 자료에 없으면 '불가'다.
missing에는 문항이 요구하지만 자료에 없는 내용을 쓴다."""


def build_bundle(exp_id: str) -> str | None:
    """작성 모델에게 넘길 근거 자료. 출처가 다른 사실을 절대 같은 항목에 섞지 않는다.

    원본 자료가 뒷받침하는 사실과 사용자가 말한 사실을 한 덩어리로 넘기면 모델이 둘을
    구분할 방법이 없고, 그 결과 자기 진술이 문서로 검증된 성과처럼 쓰인다 (F01).
    """
    meta, facts = store.get_meta(exp_id), store.get_facts(exp_id)
    if meta is None or facts is None:
        return None

    def documented(key: str, owner: str) -> list[str]:
        return [f"- {f['text']}" for f in facts[key]
                if facts_v2.is_document_backed(f) and f["owner"] == owner]

    def self_reported(key: str) -> list[dict]:
        return [f for f in facts[key] if facts_v2.is_self_reported(f)]

    if facts.get("my_role_verified"):
        role_line = f"본인 역할: {facts['my_role']} (자료에서 확인)"
    elif facts.get("my_role_provenance") == facts_v2.USER_STATEMENT:
        role_line = (
            f"본인 역할: {facts['my_role']} (본인 확인, 원문 근거 없음 — "
            "본인이 한 일로 쓸 수 있으나 이 문장에 없는 수치·기술명을 덧붙이지 말 것)"
        )
    else:
        role_line = "본인 역할: 미확인 (이 경험의 어떤 일도 '내가 했다'고 쓰지 말 것)"

    mine = documented("actions", "본인") + documented("decisions", "본인")
    team = documented("actions", "팀") + documented("decisions", "팀")
    stated = [f"- {f['text']}" for key in ("actions", "decisions", "results") for f in self_reported(key)]

    lines = [f"[{exp_id}] {facts['title']} ({meta['grade']}학년, {facts['period']})", role_line]
    if meta.get("description"):
        # 사용자가 설정에서 언제든 고쳐 쓰는 자유 설명. 본인이 직접 쓴 것이므로 본인 진술과
        # 같은 성격 — 여기 없는 새 사실을 이 설명 하나만 보고 지어내면 안 된다.
        lines += ["[프로젝트 설명 — 본인 작성]", f"- {meta['description']}"]
    lines += ["[본인이 한 일]", *(mine or ["- 없음"])]
    lines += ["[팀·프로젝트 활동]", *(team or ["- 없음"])]
    lines += ["[프로젝트 성과]", *(documented("results", "팀") or ["- 없음"])]
    if stated:
        lines += ["[본인 진술 — 원문 근거 없음]", *stated]
    if not facts["lessons"].startswith(UNKNOWN):
        lessons_label = (
            "[배운 점 — 본인 진술, 원문 근거 없음]"
            if facts.get("lessons_provenance") == facts_v2.USER_STATEMENT
            else "[배운 점]"
        )
        lines += [lessons_label, f"- {facts['lessons']}"]
    if facts["skills"]:
        lines += ["[기술]", f"- {', '.join(facts['skills'])}"]
    return "\n".join(lines)


def _gate(question: str, bundle: str) -> Answerability:
    return get_judge_llm().with_structured_output(Answerability).invoke(
        [SystemMessage(GATE_PROMPT), HumanMessage(f"[문항]\n{question}\n\n[근거 자료]\n{bundle}")]
    )


def _write(
    job: JobRequirements,
    qp: QuestionPlan,
    bundle: str,
    missing: str,
    feedback: tuple[str, list[str]] | None,
) -> str:
    profile_md = store.get_profile_markdown() or ""
    prompt = (
        f"[지원 직무] {job.company} / {job.role}\n[인재상] {', '.join(job.values) or '명시 없음'}\n"
        f"[문항] {qp.question}\n[작성 관점] {qp.angle}\n\n"
        + (f"[프로필]\n{profile_md}\n\n" if profile_md else "")
        + f"[근거 자료]\n{bundle}"
    )
    if missing:
        prompt += (
            f"\n\n다음 내용은 자료에 없으므로 쓰지 않는다: {missing}\n"
            f"문항의 나머지 부분(예: 준비 과정, 관련 경험)은 자료로 답할 수 있는 만큼 써라. '{NO_EXPERIENCE}'라고 쓰지 마라."
        )
    if feedback:
        prev, issues = feedback
        prompt += (
            "\n\n이전 초안에 다음 문제가 있었다. 해당 내용을 삭제하거나 근거 있는 표현으로 고쳐서 다시 써라.\n"
            + "\n".join(f"- {i}" for i in issues)
            + f"\n\n[이전 초안]\n{prev}"
        )
    return get_llm().invoke([SystemMessage(_writer_prompt()), HumanMessage(prompt)]).content.strip()


def split_sentences(text: str) -> list[str]:
    """마침표/물음표/느낌표 뒤 공백에서 자른다. 소수점(`0.71`)은 뒤에 공백이 없어 안 잘린다."""
    return [s.strip() for s in _SENTENCE_SPLIT.split(text.strip()) if s.strip()]


def _check(draft: str, bundle: str, job: JobRequirements, ids: list[str]) -> tuple[list[str], list[str]]:
    issues, flagged = [], []
    numbers = unsupported_numbers(draft, bundle, ids)
    if numbers:
        issues.append(f"근거 자료에 없는 수치: {numbers}")
    job_terms = job_ascii_terms(job.required_skills + job.preferred_skills + job.responsibilities)
    terms = terms_only_in_job(draft, job_terms, bundle)
    if terms:
        issues.append(f"공고에만 있고 근거 자료에는 없는 기술명: {terms}")

    sentences = split_sentences(draft)
    if not sentences:
        return issues, flagged
    sentence_ids = [f"S{i + 1}" for i in range(len(sentences))]
    labeled = "\n".join(f"[{sid}] {s}" for sid, s in zip(sentence_ids, sentences))
    judged: JudgeResult = get_judge_llm().with_structured_output(JudgeResult).invoke(
        [SystemMessage(JUDGE_PROMPT), HumanMessage(f"[근거 자료]\n{bundle}\n\n[초안]\n{labeled}")]
    )

    # sentence_id별로 모은다. 같은 id가 두 번 오면 더 엄격한(=지워야 하는) 쪽을 따른다 —
    # 판정이 애매하면 문장을 남기는 쪽보다 지우는 쪽이 안전하다.
    by_id: dict[str, SentenceCheck] = {}
    for c in judged.checks:
        prev = by_id.get(c.sentence_id)
        if prev is None or (prev.verdict == "supported" and c.verdict != "supported"):
            by_id[c.sentence_id] = c

    unknown = sorted(set(by_id) - set(sentence_ids))
    if unknown:
        issues.append(f"[판정 오류] 판정자가 존재하지 않는 문장 ID를 반환함: {unknown}")

    for sid, sentence in zip(sentence_ids, sentences):
        c = by_id.get(sid)
        if c is None:
            # 판정자가 이 문장을 아예 건너뛴 경우. "언급이 없으니 통과"로 취급하면 F04가
            # 다른 얼굴로 재발한다 — 검사 못 한 문장은 통과가 아니라 실패로 센다.
            issues.append(f"[커버리지 누락] \"{sentence}\" — 판정자가 이 문장을 검사하지 않음")
            flagged.append(sentence)
        elif c.verdict != "supported":
            issues.append(f"[{c.verdict}] \"{sentence}\" — {c.reason}")
            flagged.append(sentence)
    return issues, flagged


def _remove_flagged(draft: str, flagged: list[str], issues: list[str]) -> tuple[str, list[str], str, list[str]]:
    """판정에서 걸린 문장을 지우고 최종 결과를 재검증한다.

    `flagged`는 `_check()`가 만든 `sentences` 리스트에서 그대로 가져온 원문 문장이므로
    (판정자가 베껴 쓴 문자열이 아니라) `draft`에 정확히 존재함이 보장된다 — 이게 F04의
    핵심 수정이다. 그래도 "지웠다고 기록했는데 실제로는 남아 있다"를 마지막에 한 번 더
    확인한다(P0-5 규칙 4: 삭제·수정 후 최종 텍스트를 다시 검사).
    """
    removed = []
    for sentence in flagged:
        if sentence in draft:
            draft = draft.replace(sentence, "")
            removed.append(sentence)
    draft = re.sub(r"[ \t]{2,}", " ", draft).strip()

    # 지우기로 한 문장이 실제로는 안 지워진 두 경우: (a) 원문과 글자가 안 맞아서 애초에
    # 못 찾음(F04의 원래 증상), (b) 지웠는데 부분 겹침으로 다시 나타남. 둘 다 잡아야
    # "정제"라는 표시를 믿을 수 있다 — _check()가 항상 우리 기대대로 동작한다고 가정하지 않는다.
    not_removed = [s for s in flagged if s not in removed]
    survived = [s for s in removed if s in draft]
    failed = not_removed + survived
    if failed:
        issues = [*issues, f"[삭제 실패] 제거 대상으로 표시된 문장이 최종 결과에 남음: {failed}"]

    remaining = [i for i in issues if not i.startswith("[")]
    status = "통과" if not issues else "경고" if (remaining or failed) else "정제"
    return draft, removed, status, issues


def answer_question(job: JobRequirements, qp: QuestionPlan) -> dict:
    ids = [i for i in qp.experience_ids if store.get_meta(i)]
    bundles = [b for b in (build_bundle(i) for i in ids) if b]
    base = {"question": qp.question, "experience_ids": ids, "angle": qp.angle, "gap": qp.gap, "removed": []}
    if not bundles:
        return {**base, "draft": "", "status": "해당없음", "attempts": 0, "issues": []}

    bundle = "\n\n".join(bundles)
    gate = _gate(qp.question, bundle)
    if gate.level == "불가":
        return {**base, "gap": gate.missing or qp.gap, "draft": "", "status": "근거부족", "attempts": 0, "issues": []}
    missing = gate.missing if gate.level == "부분" else ""
    if missing:
        base["gap"] = f"{qp.gap} / 자료에 없음: {missing}" if qp.gap else f"자료에 없음: {missing}"

    draft = _write(job, qp, bundle, missing, None)
    attempts, issues, flagged = 0, [], []
    while draft != NO_EXPERIENCE:
        issues, flagged = _check(draft, bundle, job, ids)
        if not issues or attempts >= MAX_REPAIR:
            break
        attempts += 1
        draft = _write(job, qp, bundle, missing, (draft, issues))

    if draft == NO_EXPERIENCE:
        return {**base, "draft": "", "status": "해당없음", "attempts": attempts, "issues": []}

    draft, removed, status, issues = _remove_flagged(draft, flagged, issues)
    return {**base, "draft": draft, "status": status, "attempts": attempts, "issues": issues, "removed": removed}


def revise_answer(job: JobRequirements, qp: QuestionPlan, current_draft: str, user_message: str) -> dict:
    """이미 만든 초안을 사용자 요청대로 고쳐 쓴다. 같은 근거 자료 범위 밖으로는 못 나간다."""
    ids = [i for i in qp.experience_ids if store.get_meta(i)]
    bundles = [b for b in (build_bundle(i) for i in ids) if b]
    if not bundles:
        return {"draft": current_draft, "status": "반영 안 됨", "issues": ["근거 경험이 없어 수정할 수 없음"], "removed": []}
    bundle = "\n\n".join(bundles)

    draft = _write(job, qp, bundle, "", (current_draft, [f"[사용자 요청] {user_message}"]))
    if draft == NO_EXPERIENCE or not draft.strip():
        return {
            "draft": current_draft,
            "status": "반영 안 됨",
            "issues": ["요청한 내용이 근거 자료 범위 밖이라 초안을 바꾸지 않았습니다"],
            "removed": [],
        }

    issues, flagged = _check(draft, bundle, job, ids)
    draft, removed, status, issues = _remove_flagged(draft, flagged, issues)
    return {"draft": draft, "status": status, "issues": issues, "removed": removed}
