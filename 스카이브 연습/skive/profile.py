from langchain_core.messages import HumanMessage, SystemMessage

from skive import store
from skive.llm import get_llm
from skive.models import Profile
from skive.user import load_user

SYSTEM_PROMPT = """너는 대학생의 경험 기록들을 종합해 프로필을 만드는 분석가다.
입력은 진로 목표와 경험별 '검증된 사실'이다.

규칙:
1. 역량(competencies)은 입력 경험의 사실로 뒷받침되는 것만 쓴다. 각 역량에 근거 경험 id를 1개 이상 붙인다.
2. 성향(traits)은 서로 다른 경험 2개 이상에서 반복해서 관찰될 때만 쓰고, 그 경험 id를 붙인다. 한 번만 나타난 것은 성향으로 쓰지 않는다.
3. 본인 역할이 미확인(role_verified=False)인 경험의 팀 활동은 본인 역량의 유일한 근거로 쓰지 않는다.
4. '전문가', '뛰어난' 같은 과장 표현을 쓰지 않는다. 사실로 확인된 수준만 쓴다.
5. gaps에는 진로 목표에 비해 근거가 부족한 부분을 쓴다.
6. 입력에 없는 기술이나 경험을 만들지 않는다."""


def _experience_block(meta: dict, facts: dict) -> str:
    lines = [
        f"[{meta['id']}] {meta['title']} | {meta['grade']}학년 | {meta['kind']} | {meta['period']} | "
        f"중요도 {meta['importance']['tier']} | role_verified={meta['my_role_verified']}",
        f"본인 역할: {facts['my_role']}",
    ]
    for key in ("actions", "decisions", "results"):
        lines += [f"- ({f['owner']}) {f['text']}" for f in facts[key] if f["verified"]]
    if facts["skills"]:
        lines.append(f"기술: {', '.join(facts['skills'])}")
    if not facts["lessons"].startswith("확인 필요"):
        lines.append(f"배운 점: {facts['lessons']}")
    return "\n".join(lines)


def _validate(profile: Profile, ids: set[str]) -> Profile:
    competencies = []
    for c in profile.competencies:
        valid = [i for i in c.experience_ids if i in ids]
        if valid:
            competencies.append(c.model_copy(update={"experience_ids": valid}))
    traits = []
    for t in profile.traits:
        valid = sorted({i for i in t.experience_ids if i in ids})
        if len(valid) >= 2:
            traits.append(t.model_copy(update={"experience_ids": valid}))
    return profile.model_copy(update={"competencies": competencies, "traits": traits})


def _render(profile: Profile, goal: str, metas: dict[str, dict]) -> str:
    def refs(ids: list[str]) -> str:
        return ", ".join(f"[{i}] {metas[i]['title']} ({metas[i]['grade']}학년)" for i in ids)

    lines = [f"# 프로필 — {load_user()['name']}", f"> {profile.headline}", "", f"진로 목표: {goal}", "", "## 역량"]
    for c in profile.competencies:
        lines += ["", f"### {c.name}", c.description, f"- 근거 경험: {refs(c.experience_ids)}"]
    lines += ["", "## 반복 관찰되는 성향 (2개 이상 경험에서 확인)"]
    for t in profile.traits:
        lines += ["", f"### {t.trait}", t.rationale, f"- 근거 경험: {refs(t.experience_ids)}"]
    if not profile.traits:
        lines += ["", "- 아직 반복 관찰된 성향 없음"]
    lines += ["", "## 보강이 필요한 부분", *[f"- {g}" for g in profile.gaps]]
    return "\n".join(lines) + "\n"


def build_profile() -> tuple[str, dict]:
    user = load_user()
    metas = store.list_meta()
    blocks = [_experience_block(m, store.get_facts(m["id"])) for m in metas]
    profile: Profile = get_llm().with_structured_output(Profile).invoke(
        [
            SystemMessage(SYSTEM_PROMPT),
            HumanMessage(f"진로 목표: {user['career_goal']}\n\n" + "\n\n".join(blocks)),
        ]
    )
    profile = _validate(profile, {m["id"] for m in metas})
    markdown = _render(profile, user["career_goal"], {m["id"]: m for m in metas})
    return markdown, profile.model_dump()
