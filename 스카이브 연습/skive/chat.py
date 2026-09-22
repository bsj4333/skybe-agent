from datetime import datetime
from pathlib import Path

from langchain_core.messages import SystemMessage
from langchain_core.tools import tool
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode

from skive import store
from skive.agent import get_evidence, get_experience, get_profile, list_experiences
from skive.llm import get_llm
from skive.recall import format_recall, recall
from skive.study import get_study, search_study, summarize_session

MIN_USER_TURNS = 2

CHAT_PROMPT = """너는 SKIVE 챗봇이다. 사용자의 대학생활 기억(프로필, 경험 기록, 공부 기록)을 바탕으로 대화한다.
규칙:
1. 사용자의 경험·역량·공부 이력에 대한 질문은 반드시 도구로 조회한 내용만으로 답한다. 조회 결과에 없으면 '기록에 없다'고 말한다. 추측하지 않는다.
2. 조회한 내용을 인용할 때는 [경험 id] 또는 [공부 기록 id]를 붙인다.
3. 개념 설명 같은 학습 질문은 일반 지식으로 답해도 된다. 다만 사용자의 기록과 연결되는 부분(예전에 헷갈렸던 점, 관련 프로젝트)이 있으면 조회해서 함께 알려준다. 일반 지식 부분은 '(일반 지식)'이라고 표시한다.
4. 답변은 간결하게 한다.
5. get_evidence로 원본 파일을 읽을 수 있다. 원본 파일은 절대 고치지 않는다 — 정리한 내용이나 새로 만든 자료는
   save_note로 그 경험의 '메모'로만 저장한다. list_notes/get_note로 이전에 저장한 메모를 다시 볼 수 있다."""


def _build_tools(scope_id: str | None):
    def _resolve(experience_id: str) -> str:
        return scope_id or experience_id

    @tool
    def save_note(filename: str, content: str, experience_id: str = "") -> str:
        """경험 폴더에 메모 파일을 새로 만들거나 덮어쓴다. 원본 증거 파일은 건드리지 않는다.
        대화 범위가 특정 경험으로 좁혀져 있으면 그 경험에 저장되고, experience_id는 무시된다."""
        exp_id = _resolve(experience_id)
        if not exp_id:
            return "어느 경험에 저장할지 알 수 없음 — experience_id를 지정해야 함"
        if store.get_meta(exp_id) is None:
            return f"존재하지 않는 경험 id: {exp_id}"
        path = store.save_note(exp_id, filename, content)
        return f"저장함: {path}"

    @tool
    def list_notes(experience_id: str = "") -> str:
        """경험 폴더에 저장된 메모 파일 목록을 반환한다."""
        exp_id = _resolve(experience_id)
        if not exp_id:
            return "experience_id가 필요함"
        names = store.list_notes(exp_id)
        return "\n".join(names) if names else "저장된 메모 없음"

    @tool
    def get_note(filename: str, experience_id: str = "") -> str:
        """경험 폴더의 메모 파일 하나를 읽는다."""
        exp_id = _resolve(experience_id)
        if not exp_id:
            return "experience_id가 필요함"
        text = store.get_note(exp_id, filename)
        return text or f"존재하지 않는 메모: {filename}"

    return [
        get_profile,
        list_experiences,
        get_experience,
        get_evidence,
        search_study,
        get_study,
        save_note,
        list_notes,
        get_note,
    ]


def build_chat_graph(scope_id: str | None = None):
    tools = _build_tools(scope_id)
    llm = get_llm().bind_tools(tools)

    def agent_node(state: MessagesState) -> dict:
        system = [SystemMessage(CHAT_PROMPT)]
        if scope_id is not None:
            meta = store.get_meta(scope_id)
            title = meta["title"] if meta else scope_id
            system.append(
                SystemMessage(
                    f"[대화 범위 제한] 사용자가 '{title}' 경험 폴더 안에서 대화하기를 선택했다. "
                    "다른 경험의 기록은 조회하지도, 답변에 쓰지도 않는다. 다른 경험 관련 질문이면 "
                    "이 폴더 범위 밖이라고 안내한다."
                )
            )
        last_user = next((m.content for m in reversed(state["messages"]) if m.type == "human"), "")
        hits = recall(last_user, scope_id=scope_id)
        if hits:
            system.append(
                SystemMessage(
                    "[자동 조회된 관련 기억] 아래는 사용자의 기록에서 이 질문과 겹치는 부분이다. "
                    "답변에 관련이 있으면 반드시 '[관련 기록]' 항목으로 알려주고, 기록에 없는 내용은 덧붙이지 않는다.\n\n"
                    + format_recall(hits)
                )
            )
        return {"messages": [llm.invoke(system + state["messages"])]}

    def route(state: MessagesState) -> str:
        return "tools" if getattr(state["messages"][-1], "tool_calls", []) else END

    builder = StateGraph(MessagesState)
    builder.add_node("agent", agent_node)
    builder.add_node("tools", ToolNode(tools))
    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", route, {"tools": "tools", END: END})
    builder.add_edge("tools", "agent")
    return builder.compile()


def _transcript(messages: list) -> str:
    lines = []
    for m in messages:
        if m.type == "human":
            lines.append(f"나: {m.content}")
        elif m.type == "ai" and m.content:
            lines.append(f"SKIVE: {m.content}")
    return "\n".join(lines)


def ask_once(graph, messages: list, text: str) -> tuple[list, str]:
    result = graph.invoke({"messages": messages + [("user", text)]}, config={"recursion_limit": 20})
    return result["messages"], result["messages"][-1].content


def run_chat(script: Path | None) -> dict | None:
    graph = build_chat_graph()
    messages: list = []
    if script:
        inputs = iter(line.strip() for line in script.read_text(encoding="utf-8").splitlines() if line.strip())
    else:
        print("SKIVE 챗봇입니다. 종료하려면 /exit 를 입력하세요. 종료하면 공부 내용이 자동으로 기록됩니다.")
        inputs = None

    while True:
        if inputs is None:
            try:
                line = input("나> ").strip()
            except EOFError:
                break
        else:
            line = next(inputs, "/exit")
            if line != "/exit":
                print(f"나> {line}")
        if line in ("/exit", "/quit"):
            break
        if not line:
            continue
        messages, answer = ask_once(graph, messages, line)
        print(f"SKIVE> {answer}\n")

        if inputs is None:
            from skive.corrections import apply_correction, detect_correction

            proposal = detect_correction(line)
            if proposal:
                if proposal.kind == "new_fact":
                    print(
                        f"[새 사실 확인] '{proposal.corrected_text}' 를 경험 '{proposal.experience_id}'에 "
                        f"추가할까요? (이유: {proposal.reason})"
                    )
                else:
                    print(
                        f"[정정 확인] '{proposal.original_text}' → '{proposal.corrected_text}' "
                        f"(경험: {proposal.experience_id}, 이유: {proposal.reason})"
                    )
                if input("이대로 반영할까요? (y/n) > ").strip().lower() in ("y", "yes", "예", "응"):
                    apply_correction(proposal)
                    print("[반영 완료]\n")
                else:
                    print("[취소]\n")

    user_turns = sum(1 for m in messages if m.type == "human")
    if user_turns < MIN_USER_TURNS:
        print("(대화가 짧아 공부 기록을 만들지 않았습니다)")
        return None
    session_id = "study-" + datetime.now().strftime("%Y%m%d-%H%M%S")
    meta = summarize_session(_transcript(messages), session_id)
    print(f"[공부 기록 저장] {meta['id']} | {meta['topic']} | 배운 것 {meta['learned_count']} / 헷갈리는 것 {meta['confusion_count']}")
    return meta
