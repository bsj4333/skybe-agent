"""Claude 호출 어댑터.

앱의 나머지 코드는 `get_llm().invoke()`, `.bind_tools()`, `.with_structured_output()`만 쓴다.
그 표면은 유지하고 호출만 공식 Anthropic SDK로 보낸다. 임베딩은 Claude API에 없어서
`skive/embeddings.py`에 그대로 둔다.

비용 기본값: 테스트 기간에는 가장 저렴한 Haiku를 낮은 강도로 쓰고, 사용자가 제출하는
자소서를 쓰는 호출만 `get_essay_llm()`으로 Sonnet을 쓴다. 모두 환경 변수로 바꿀 수 있다.

현재 Claude 모델에서 지켜야 하는 것:
- `temperature`를 보내면 400이다. 강제 `tool_choice`도 400이므로 JSON이 필요하면
  `with_structured_output`을 쓴다.
- 사고(thinking)는 강도로만 조절한다. 응답의 사고 블록은 도구 루프에서 원본 그대로 돌려줘야 해서
  `AIMessage.additional_kwargs`에 원본 블록을 보관한다.
- 시스템 프롬프트나 도구 목록이 바뀌면 이전 사고 블록이 무효가 된다. 챗봇은 질문마다 시스템
  문구가 달라지므로 400 대신 해당 블록만 버리도록 `drop_block`을 켠다.
"""

import os
from functools import lru_cache

import anthropic
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage, convert_to_messages
from langchain_core.utils.function_calling import convert_to_openai_tool

from skive.config import load_environment

load_environment()

DEFAULT_MODEL = "claude-haiku-5-5"
DEFAULT_EFFORT = "low"
ESSAY_MODEL = "claude-sonnet-5-5"
ESSAY_EFFORT = "medium"
MAX_TOKENS = 16000  # 사고 토큰도 여기에 포함된다.
BLOCKS_KEY = "anthropic_blocks"
THINKING_BINDING_BETA = "thinking-binding-controls-2026-08-01"
REFUSAL_FALLBACK_BETA = "server-side-fallback-2026-07-01"
# 서버 측 거절 대체는 이 모델들만 받는다. Haiku로 바꾸면 자동으로 빠진다.
FALLBACK_MODELS = ("claude-opus-5", "claude-fable-5", "claude-sonnet-5-5")


class ClaudeResponseError(RuntimeError):
    """모델이 거절했거나 답이 잘려서 결과를 믿을 수 없다."""


@lru_cache(maxsize=1)
def anthropic_client() -> anthropic.Anthropic:
    return anthropic.Anthropic()


def request_options(model: str, effort: str) -> dict:
    """모든 Claude 요청에 공통으로 붙는 인자."""
    betas = [THINKING_BINDING_BETA]
    options = {
        "thinking": {"type": "adaptive",
                     "block_binding": {"prefix_mismatch_behavior": "drop_block"}},
        "output_config": {"effort": effort},
    }
    if model.startswith(FALLBACK_MODELS):
        betas.append(REFUSAL_FALLBACK_BETA)
        options["fallbacks"] = "default"
    options["betas"] = betas
    return options


def ensure_complete(response) -> None:
    """내용을 읽기 전에 멈춘 이유부터 확인한다."""
    if response.stop_reason == "refusal":
        details = getattr(response, "stop_details", None)
        category = getattr(details, "category", None) or "unknown"
        raise ClaudeResponseError(f"Claude가 요청을 거절했습니다 ({category})")
    if response.stop_reason == "max_tokens":
        raise ClaudeResponseError("Claude 응답이 최대 길이에서 잘렸습니다")


def _text(content) -> str:
    if isinstance(content, str):
        return content
    return "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in content)


def _assistant_blocks(message: AIMessage) -> list[dict]:
    """원본 블록이 없는 메시지(저장된 이전 대화)는 텍스트와 도구 호출로 다시 만든다."""
    blocks = []
    text = _text(message.content)
    if text:
        blocks.append({"type": "text", "text": text})
    for call in message.tool_calls:
        blocks.append({"type": "tool_use", "id": call["id"], "name": call["name"],
                       "input": call["args"]})
    return blocks


def to_anthropic(messages) -> tuple[str, list[dict]]:
    """LangChain 메시지를 (system, messages)로 바꾼다."""
    system, converted = [], []

    def add(role: str, blocks: list[dict]) -> None:
        if role == "user" and converted and converted[-1]["role"] == "user":
            converted[-1]["content"].extend(blocks)  # 도구 결과는 한 user 메시지에 모은다.
        else:
            converted.append({"role": role, "content": blocks})

    for message in convert_to_messages(messages):
        if isinstance(message, SystemMessage):
            system.append(_text(message.content))
        elif isinstance(message, ToolMessage):
            add("user", [{"type": "tool_result", "tool_use_id": message.tool_call_id,
                          "content": _text(message.content)}])
        elif isinstance(message, AIMessage):
            blocks = message.additional_kwargs.get(BLOCKS_KEY) or _assistant_blocks(message)
            if blocks:
                add("assistant", blocks)
        else:
            text = _text(message.content)
            if text:
                add("user", [{"type": "text", "text": text}])
    return "\n\n".join(system), converted


def _history_tools(messages: list[dict]) -> list[dict]:
    """기록에 tool_use가 있으면 요청에 tools가 있어야 한다. 호출은 막고 이름만 선언한다."""
    names = sorted({block["name"] for message in messages if message["role"] == "assistant"
                    for block in message["content"] if block.get("type") == "tool_use"})
    return [{"name": name, "description": "이전 단계에서 사용한 도구",
             "input_schema": {"type": "object"}} for name in names]


def _tool_definition(tool) -> dict:
    function = convert_to_openai_tool(tool)["function"]
    return {"name": function["name"], "description": function.get("description", ""),
            "input_schema": function.get("parameters", {"type": "object"})}


class ClaudeChat:
    def __init__(self, model: str, effort: str, tools: list[dict] | None = None, schema=None):
        self.model = model
        self.effort = effort
        self.tools = tools or []
        self.schema = schema

    def bind_tools(self, tools) -> "ClaudeChat":
        return ClaudeChat(self.model, self.effort, [_tool_definition(tool) for tool in tools],
                          self.schema)

    def with_structured_output(self, schema) -> "ClaudeChat":
        return ClaudeChat(self.model, self.effort, self.tools, schema)

    def invoke(self, messages):
        system, converted = to_anthropic(messages)
        request = {"model": self.model, "max_tokens": MAX_TOKENS, "messages": converted,
                   **request_options(self.model, self.effort)}
        if system:
            request["system"] = system
        tools = self.tools or _history_tools(converted)
        if tools:
            request["tools"] = tools
        if tools and (self.schema is not None or not self.tools):
            request["tool_choice"] = {"type": "none"}

        client = anthropic_client()
        if self.schema is not None:
            response = client.beta.messages.parse(output_format=self.schema, **request)
            ensure_complete(response)
            if response.parsed_output is None:
                raise ClaudeResponseError("Claude 응답을 구조화하지 못했습니다")
            return response.parsed_output

        response = client.beta.messages.create(**request)
        ensure_complete(response)
        return AIMessage(
            content="".join(block.text for block in response.content if block.type == "text"),
            tool_calls=[{"name": block.name, "args": block.input, "id": block.id, "type": "tool_call"}
                        for block in response.content if block.type == "tool_use"],
            additional_kwargs={BLOCKS_KEY: [block.to_dict() for block in response.content]},
        )


def get_llm(model: str | None = None, effort: str | None = None) -> ClaudeChat:
    return ClaudeChat(model or os.getenv("SKIVE_MODEL", DEFAULT_MODEL),
                      effort or os.getenv("SKIVE_EFFORT", DEFAULT_EFFORT))


def get_judge_llm() -> ClaudeChat:
    return get_llm(os.getenv("SKIVE_JUDGE_MODEL"), os.getenv("SKIVE_JUDGE_EFFORT"))


def get_essay_llm() -> ClaudeChat:
    """사용자가 제출하는 자소서 문장을 쓰는 호출 전용."""
    return get_llm(os.getenv("SKIVE_ESSAY_MODEL", ESSAY_MODEL),
                   os.getenv("SKIVE_ESSAY_EFFORT", ESSAY_EFFORT))
