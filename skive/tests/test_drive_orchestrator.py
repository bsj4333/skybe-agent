"""A model-selected search must update the evidence pool used by the writer."""

from uuid import uuid4

from langchain_core.messages import AIMessage, ToolMessage

from skive.drive_career import CareerReply
from skive.drive_orchestrator import run_career_orchestrator


def test_model_can_search_drive_again_and_reuse_result(monkeypatch):
    class ToolBound:
        calls = 0

        def invoke(self, messages):
            self.calls += 1
            if self.calls == 1:
                return AIMessage(content="", tool_calls=[{
                    "name": "search_my_drive", "args": {"query": "BOM"}, "id": "call-search-1",
                }])
            assert any(isinstance(item, ToolMessage) and "BOM note" in item.content for item in messages)
            return AIMessage(content="찾았습니다")

    class FinalBound:
        def invoke(self, messages):
            assert any(isinstance(item, ToolMessage) for item in messages)
            return CareerReply(action="discuss", answer="BOM 자료를 찾았습니다. [파일 1]")

    class FakeModel:
        def bind_tools(self, tools):
            assert {item.name for item in tools} == {
                "search_my_drive", "search_my_statements", "search_my_previous_essays",
                "search_my_reviewed_facts"}
            return ToolBound()

        def with_structured_output(self, schema):
            assert schema is CareerReply
            return FinalBound()

    monkeypatch.setattr("skive.drive_orchestrator.get_llm", lambda: FakeModel())
    monkeypatch.setattr("skive.drive_workspace._sources", lambda conn, query, folder, limit:
                        [{"index": 1, "file_id": str(uuid4()), "chunk_index": 0,
                          "name": "BOM note", "location": "line 1", "excerpt": "BOM 설명"}])
    sources, memories, past = [], [], []
    reply = run_career_orchestrator(object(), {"request": "BOM 다시 찾아줘"}, uuid4(),
                                    sources, memories, past, CareerReply)
    assert reply.action == "discuss"
    assert len(sources) == 1 and sources[0]["index"] == 1
