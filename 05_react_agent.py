import ast
import operator

from dotenv import load_dotenv
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, START, END, MessagesState
from langgraph.prebuilt import ToolNode, tools_condition

load_dotenv()

_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
}


def _safe_eval(node):
    if isinstance(node, ast.BinOp):
        return _OPERATORS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp):
        return _OPERATORS[type(node.op)](_safe_eval(node.operand))
    if isinstance(node, ast.Constant):
        return node.value
    raise ValueError(f"허용되지 않은 표현식: {ast.dump(node)}")


@tool
def calculator(expression: str) -> str:
    """사칙연산 수학 계산식을 계산한다. 예: '23 * 17'"""
    tree = ast.parse(expression, mode="eval")
    return str(_safe_eval(tree.body))


tools = [calculator]
llm = ChatOpenAI(model="gpt-4o-mini")
llm_with_tools = llm.bind_tools(tools)


def agent_node(state: MessagesState) -> dict:
    response = llm_with_tools.invoke(state["messages"])
    return {"messages": [response]}


graph_builder = StateGraph(MessagesState)
graph_builder.add_node("agent", agent_node)
graph_builder.add_node("tools", ToolNode(tools))

graph_builder.add_edge(START, "agent")
graph_builder.add_conditional_edges("agent", tools_condition)
graph_builder.add_edge("tools", "agent")

graph = graph_builder.compile()

result = graph.invoke({"messages": [("user", "127 곱하기 89는 얼마고, 그 다음에 15를 더하면?")]})

for message in result["messages"]:
    message.pretty_print()
