from typing import TypedDict, Literal

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, START, END

load_dotenv()

llm = ChatOpenAI(model="gpt-4o-mini")


class State(TypedDict):
    question: str
    category: str
    answer: str


def classify_node(state: State) -> dict:
    prompt = (
        f"다음 질문이 수학 계산 문제면 'math', 아니면 'general'이라고만 답해.\n"
        f"질문: {state['question']}"
    )
    response = llm.invoke(prompt)
    category = response.content.strip().lower()
    return {"category": category}


def math_node(state: State) -> dict:
    response = llm.invoke(f"다음 수학 문제를 단계별로 풀어줘: {state['question']}")
    return {"answer": response.content}


def general_node(state: State) -> dict:
    response = llm.invoke(state["question"])
    return {"answer": response.content}


def route(state: State) -> Literal["math_node", "general_node"]:
    if state["category"] == "math":
        return "math_node"
    return "general_node"


graph_builder = StateGraph(State)
graph_builder.add_node("classify", classify_node)
graph_builder.add_node("math_node", math_node)
graph_builder.add_node("general_node", general_node)

graph_builder.add_edge(START, "classify")
graph_builder.add_conditional_edges("classify", route)
graph_builder.add_edge("math_node", END)
graph_builder.add_edge("general_node", END)

graph = graph_builder.compile()

result = graph.invoke({"question": "23 곱하기 17은 얼마야?"})
print("[분류]", result["category"])
print("[답변]", result["answer"])

result2 = graph.invoke({"question": "가을에 어울리는 노래 추천해줘"})
print("[분류]", result2["category"])
print("[답변]", result2["answer"])

