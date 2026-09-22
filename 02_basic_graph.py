from typing import TypedDict

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, START, END

load_dotenv()

llm = ChatOpenAI(model="gpt-4o-mini")


class State(TypedDict):
    question: str
    answer: str


def answer_node(state: State) -> dict:
    response = llm.invoke(state["question"])
    return {"answer": response.content}


graph_builder = StateGraph(State)
graph_builder.add_node("answer", answer_node)
graph_builder.add_edge(START, "answer")
graph_builder.add_edge("answer", END)

graph = graph_builder.compile()

result = graph.invoke({"question": "LangGraph가 뭔지 한 문장으로 설명해줘"})
print(result)

