import ast
import operator

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

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


llm = ChatOpenAI(model="gpt-4o-mini")
llm_with_tools = llm.bind_tools([calculator])

messages = [HumanMessage("23 곱하기 17은 얼마야?")]
ai_response = llm_with_tools.invoke(messages)

print("content:", repr(ai_response.content))
print("tool_calls:", ai_response.tool_calls)
