"""Claude adapter contract. No network: the SDK client is replaced."""

from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from pydantic import BaseModel

from skive import llm


class Block(SimpleNamespace):
    def to_dict(self):
        return dict(self.__dict__)


def fake_client(monkeypatch, response):
    calls = []

    def record(**kwargs):
        calls.append(kwargs)
        return response

    messages = SimpleNamespace(create=record, parse=record)
    client = SimpleNamespace(beta=SimpleNamespace(messages=messages))
    monkeypatch.setattr(llm, "anthropic_client", lambda: client)
    return calls


def test_request_never_sends_sampling_or_forced_tool(monkeypatch):
    calls = fake_client(monkeypatch, SimpleNamespace(
        stop_reason="end_turn", content=[Block(type="text", text="답")]))

    @tool
    def search(query: str) -> str:
        """Search."""
        return query

    reply = llm.get_llm().bind_tools([search]).invoke([HumanMessage("질문")])
    assert reply.content == "답"
    sent = calls[0]
    assert "temperature" not in sent and "tool_choice" not in sent
    assert sent["tools"][0]["name"] == "search"
    assert sent["tools"][0]["input_schema"]["properties"]["query"]["type"] == "string"
    assert sent["thinking"]["block_binding"]["prefix_mismatch_behavior"] == "drop_block"
    assert llm.THINKING_BINDING_BETA in sent["betas"]


def test_thinking_blocks_return_verbatim_in_tool_loop(monkeypatch):
    blocks = [Block(type="thinking", thinking="", signature="sig"),
              Block(type="tool_use", id="t1", name="search", input={"query": "x"})]
    calls = fake_client(monkeypatch, SimpleNamespace(stop_reason="tool_use", content=blocks))
    model = llm.get_llm()
    ai = model.invoke([HumanMessage("질문")])
    assert ai.tool_calls[0]["args"] == {"query": "x"} and ai.content == ""

    model.invoke([HumanMessage("질문"), ai, ToolMessage(content="결과", tool_call_id="t1")])
    history = calls[1]["messages"]
    assert history[1] == {"role": "assistant", "content": [block.to_dict() for block in blocks]}
    assert history[2]["content"] == [{"type": "tool_result", "tool_use_id": "t1", "content": "결과"}]


def test_system_messages_and_tool_results_are_merged():
    ai = AIMessage(content="", tool_calls=[
        {"name": "a", "args": {}, "id": "1", "type": "tool_call"},
        {"name": "b", "args": {}, "id": "2", "type": "tool_call"}])
    system, messages = llm.to_anthropic([
        SystemMessage("규칙"), SystemMessage("범위"), ("user", "질문"), ai,
        ToolMessage(content="r1", tool_call_id="1"), ToolMessage(content="r2", tool_call_id="2"),
        HumanMessage("정리해")])
    assert system == "규칙\n\n범위"
    assert [item["role"] for item in messages] == ["user", "assistant", "user"]
    assert [block["type"] for block in messages[2]["content"]] == ["tool_result", "tool_result", "text"]


def test_structured_output_after_tools_declares_history_tools_without_calling(monkeypatch):
    class Answer(BaseModel):
        value: str

    calls = fake_client(monkeypatch, SimpleNamespace(
        stop_reason="end_turn", parsed_output=Answer(value="ok")))
    ai = AIMessage(content="", tool_calls=[{"name": "a", "args": {}, "id": "1", "type": "tool_call"}])
    result = llm.get_llm().with_structured_output(Answer).invoke(
        [HumanMessage("q"), ai, ToolMessage(content="r", tool_call_id="1"), HumanMessage("제출")])
    assert result.value == "ok"
    assert calls[0]["output_format"] is Answer
    assert calls[0]["tool_choice"] == {"type": "none"}
    assert [item["name"] for item in calls[0]["tools"]] == ["a"]


@pytest.mark.parametrize("reason", ["refusal", "max_tokens"])
def test_incomplete_response_is_an_error_not_an_empty_answer(monkeypatch, reason):
    fake_client(monkeypatch, SimpleNamespace(stop_reason=reason, content=[], stop_details=None))
    with pytest.raises(llm.ClaudeResponseError):
        llm.get_llm().invoke([HumanMessage("질문")])


def test_default_is_cheapest_and_only_essays_use_sonnet(monkeypatch):
    for name in ("SKIVE_MODEL", "SKIVE_EFFORT", "SKIVE_JUDGE_MODEL", "SKIVE_JUDGE_EFFORT",
                 "SKIVE_ESSAY_MODEL", "SKIVE_ESSAY_EFFORT"):
        monkeypatch.delenv(name, raising=False)
    assert (llm.get_llm().model, llm.get_llm().effort) == ("claude-haiku-5-5", "low")
    assert llm.get_judge_llm().model == "claude-haiku-5-5"
    assert (llm.get_essay_llm().model, llm.get_essay_llm().effort) == ("claude-sonnet-5-5", "medium")


def test_fallback_only_for_models_that_accept_it():
    assert llm.request_options("claude-opus-5-5", "medium")["fallbacks"] == "default"
    assert "fallbacks" not in llm.request_options("claude-haiku-5-5", "low")
