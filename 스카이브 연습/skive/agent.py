from langchain_core.messages import SystemMessage
from langchain_core.tools import tool
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode

from skive import store
from skive.llm import get_llm
from skive.models import JobRequirements, Plan

PLANNER_PROMPT = """너는 채용공고와 지원자의 프로필·경험을 연결하는 커리어 에이전트다.
절차:
1. get_profile로 지원자 프로필(역량·성향)을 읽는다.
2. list_experiences로 경험 목록(학년, 유형, 중요도 등급)을 확인한다.
3. 공고의 핵심 역량과 자소서 문항에 관련 있어 보이는 경험을 get_experience로 읽는다. 읽지 않은 경험은 계획에 넣지 않는다.
4. 가장 유력한 경험 1~2개는 get_evidence로 원본 근거를 확인한다.
5. 탐색이 끝나면 더 이상 도구를 호출하지 말고 '탐색 완료'라고만 답한다. 계획 제출은 별도 단계에서 한다.
규칙:
- 각 자소서 문항에 경험 1~2개를 고른다. 중요도 '핵심' 등급과 본인 역할이 검증된 경험을 우선한다.
- 억지로 연결하지 않는다. 문항이 요구하는 상황(예: 갈등 극복)이 경험 기록에 실제로 있을 때만 배정한다. 없으면 experience_ids를 비우고 gap에 이유를 적는다.
- 문항 일부만 답할 수 있으면(예: 준비 과정은 있지만 지원 동기는 없음) 관련 경험을 배정하고, 답할 수 없는 부분은 gap에 '사용자 입력 필요'로 적는다.
- 공고의 핵심 역량마다 competency_links를 만든다. 근거가 없으면 strength를 '없음'으로 한다.
- strength '강함'은 본인 역할이 검증된 경험에 직접적인 사실이 있을 때만 쓴다. 팀에 참여했다는 사실만으로는 '약함'이다. 팀워크·소통 같은 역량은 갈등 조율이나 역할 조정 같은 구체적 사실이 있어야 '보통' 이상이다.
- 본인 역할이 '확인 필요'인 경험을 쓰게 되면 questions_for_user에 사용자에게 물어볼 질문을 남긴다.
- 프로필·경험 기록에 없는 내용을 지어내지 않는다."""


@tool
def get_profile() -> str:
    """지원자의 종합 프로필(역량, 반복 관찰되는 성향, 보강 필요 부분)을 반환한다."""
    return store.get_profile_markdown() or "프로필 없음"


@tool
def list_experiences() -> str:
    """저장된 모든 경험의 id, 제목, 학년, 유형, 기간, 중요도 등급, 한 줄 요약, 기술 목록을 반환한다."""
    lines = [
        f"- id={m['id']} | {m['title']} | {m['grade']}학년 | {m['kind']} | {m['period']} | "
        f"중요도 {m['importance']['tier']} | 역할검증={'예' if m['my_role_verified'] else '아니오'} | "
        f"{m['summary']} | skills: {', '.join(m['skills'])}"
        for m in store.list_meta()
    ]
    return "\n".join(lines) or "저장된 경험이 없음"


@tool
def get_experience(experience_id: str) -> str:
    """경험 id로 experience.md 전체 내용을 반환한다."""
    return store.get_markdown(experience_id) or f"존재하지 않는 id: {experience_id}"


@tool
def get_evidence(experience_id: str, source: str) -> str:
    """경험의 원본 파일 하나의 텍스트를 반환한다. source는 experience.md의 Evidence 목록에 있는 파일 경로."""
    return store.get_source_text(experience_id, source) or f"존재하지 않는 id 또는 source: {experience_id}, {source}"


TOOLS = [get_profile, list_experiences, get_experience, get_evidence]


def _route(state: MessagesState) -> str:
    return "tools" if getattr(state["messages"][-1], "tool_calls", []) else END


def _build_graph():
    llm = get_llm().bind_tools(TOOLS)

    def agent_node(state: MessagesState) -> dict:
        return {"messages": [llm.invoke([SystemMessage(PLANNER_PROMPT)] + state["messages"])]}

    builder = StateGraph(MessagesState)
    builder.add_node("agent", agent_node)
    builder.add_node("tools", ToolNode(TOOLS))
    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", _route, {"tools": "tools", END: END})
    builder.add_edge("tools", "agent")
    return builder.compile()


def run_planner(job: JobRequirements) -> tuple[Plan, list[tuple[str, dict]]]:
    result = _build_graph().invoke(
        {"messages": [("user", f"다음 공고에 맞는 계획을 세워줘.\n\n{job.model_dump_json(indent=2)}")]},
        config={"recursion_limit": 30},
    )
    messages = result["messages"]
    trace = [(c["name"], c["args"]) for m in messages for c in getattr(m, "tool_calls", [])]
    submit = get_llm().bind_tools([Plan], tool_choice="Plan").invoke(
        [SystemMessage(PLANNER_PROMPT)]
        + messages
        + [("user", "탐색이 끝났다. 위에서 읽은 프로필과 경험 기록만 근거로 Plan을 제출해라.")]
    )
    return Plan.model_validate(submit.tool_calls[0]["args"]), trace
