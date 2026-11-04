from uuid import uuid4

from skive.drive_summary import SummaryClaim, SummaryDraft, build_summary, collect_sources
from skive.loaders import Chunk
from skive.models import Evidence


def test_folder_summary_holds_unquoted_claim(monkeypatch):
    class FakeStructured:
        def invoke(self, _messages):
            return SummaryDraft(claims=[
                SummaryClaim(text="팀의 F1 점수는 0.86이었다 (C1)", evidence=[Evidence(chunk_id="C1", quote="F1 점수는 0.86")]),
                SummaryClaim(text="내가 정확도 99%를 달성했다", evidence=[Evidence(chunk_id="C1", quote="F1 점수는 0.86")]),
            ], questions=["본인이 직접 맡은 부분은 무엇인가요?"])

    class FakeLLM:
        def with_structured_output(self, _schema):
            return FakeStructured()

    monkeypatch.setattr("skive.drive_summary.get_llm", lambda: FakeLLM())
    chunks = {"C1": Chunk(source="report.md", location="L1", text="팀의 F1 점수는 0.86이었다")}
    refs = {"C1": {"file_id": "f", "file_name": "report.md", "file_version": 1,
                   "chunk_index": 1, "location": "L1"}}
    markdown, facts = build_summary("프로젝트", chunks, refs, 3, 1)
    assert facts[0]["auto_checked"] is True
    assert facts[0]["text"] == "팀의 F1 점수는 0.86이었다"
    assert facts[1]["auto_checked"] is False
    assert "## 검증 보류\n- 내가 정확도 99%를 달성했다" in markdown
    assert "대상 파일 3개 중 1개" in markdown


def test_folder_summary_can_use_speaker_note_after_first_three_chunks():
    file_id = uuid4()
    rows = [{"file_id": file_id, "file_version": 1, "chunk_index": i,
             "location": f"slide {i}", "text": f"본문 {i}"} for i in range(1, 4)]
    rows.append({"file_id": file_id, "file_version": 1, "chunk_index": 8,
                 "location": "slide 4 speaker notes", "text": "발표자 노트의 중요한 설명"})

    class Conn:
        def execute(self, _sql, _params):
            class Cursor:
                def fetchall(self):
                    return rows
            return Cursor()

    files = [{"id": file_id, "name": "slides.pptx", "version": 1, "analysis_status": "ready"}]
    chunks, refs, selected = collect_sources(Conn(), uuid4(), files)
    assert selected == 1
    assert any("speaker notes" in ref["location"] for ref in refs.values())
    assert any("발표자 노트" in chunk.text for chunk in chunks.values())
