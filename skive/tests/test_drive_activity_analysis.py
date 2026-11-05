from datetime import datetime, timezone
from uuid import uuid4

from skive.drive_activity_analysis import (ProposedFact, ProposedFacts,
                                           conflict_questions, propose,
                                           source_signature)
from skive.loaders import Chunk


class FakeModel:
    def __init__(self, facts):
        self.facts = facts

    def invoke(self, messages):
        return ProposedFacts(facts=self.facts)


def test_proposal_requires_matching_quote_and_never_auto_confirms_user_role():
    file = {"id": uuid4(), "name": "result.pdf", "version": 1,
            "analyzed_at": datetime.now(timezone.utc)}
    row = {"chunk_index": 3, "location": "p.3", "text": "불량률 12% 감소"}
    batch = ({"C1": {"file": file, "row": row}},
             {"C1": Chunk(source=file["name"], location="p.3", text=row["text"])},
             "[C1] result.pdf @ p.3\n불량률 12% 감소")
    facts = [
        ProposedFact(kind="result", line_id="S1", subject="user"),
        ProposedFact(kind="result", line_id="S99", subject="user"),
    ]
    result = propose(batch, "test", model=FakeModel(facts))
    assert len(result) == 1
    assert result[0]["subject"] == "unclear"
    assert result[0]["row"]["location"] == "p.3"


def test_source_signature_changes_with_analysis_and_conflict_questions():
    now = datetime.now(timezone.utc)
    file = {"id": uuid4(), "name": "source.txt", "version": 1,
            "analysis_status": "ready", "analyzed_at": now}
    assert source_signature([file]) != source_signature([{**file, "version": 2}])
    assert source_signature([file]) != source_signature([{**file, "name": "renamed.txt"}])
    facts = [{"kind": "result", "content": "정확도 91%", "review_state": "candidate",
              "subject": "project"},
             {"kind": "result", "content": "정확도 93%", "review_state": "candidate",
              "subject": "team"}]
    questions = conflict_questions(facts)
    assert any("본인이 직접" in question for question in questions)
    assert any("서로 다른 수치" in question for question in questions)


def test_each_unselected_file_can_supply_a_raw_review_candidate():
    first, second = uuid4(), uuid4()
    from datetime import datetime, timezone
    from skive.loaders import Chunk
    now = datetime.now(timezone.utc)
    refs = {}
    chunks = {}
    for index, file_id in enumerate((first, second), 1):
        cid = f"C{index}"
        text = f"평가 결과 정확도 {90+index}%"
        refs[cid] = {"file": {"id": file_id, "name": f"{index}.txt", "version": 1,
                              "analyzed_at": now},
                     "row": {"chunk_index": 1, "location": "L1-1", "text": text}}
        chunks[cid] = Chunk(source=f"{index}.txt", location="L1-1", text=text)
    result = propose((refs, chunks, ""), "test", model=FakeModel([]))
    assert {item["file"]["id"] for item in result} == {first, second}
    assert all(item["kind"] == "result" and item["subject"] == "unclear" for item in result)


def test_goal_line_is_kept_when_model_only_selects_result():
    file = {"id": uuid4(), "name": "report.txt", "version": 1,
            "analyzed_at": datetime.now(timezone.utc)}
    row = {"chunk_index": 1, "location": "L1-2",
           "text": "목표는 정확도 개선이다.\n평가 결과 정확도 92%"}
    batch = ({"C1": {"file": file, "row": row}},
             {"C1": Chunk(source=file["name"], location=row["location"], text=row["text"])}, "")
    result = propose(batch, "test", model=FakeModel([
        ProposedFact(kind="result", line_id="S2", subject="team")]))
    assert {item["kind"] for item in result} == {"goal", "result"}


def test_slide_titles_are_not_review_candidates():
    """2026-11-05 real-data run: titles became '결과' and '기타' facts."""
    file = {"id": uuid4(), "name": "deck.pptx", "version": 1,
            "analyzed_at": datetime.now(timezone.utc)}
    row = {"chunk_index": 1, "location": "slide 3",
           "text": "인터뷰 세부결과(1)\n시장 규모 분석\n인터뷰 결과 요약"}
    batch = ({"C1": {"file": file, "row": row}},
             {"C1": Chunk(source=file["name"], location=row["location"], text=row["text"])}, "")
    result = propose(batch, "test", model=FakeModel([
        ProposedFact(kind="other", line_id="S2", subject="unclear")]))
    assert result == []


def test_heading_numbers_are_not_conflicting_results():
    facts = [{"kind": "result", "content": "인터뷰 세부결과(1)", "review_state": "candidate",
              "subject": "unclear"},
             {"kind": "result", "content": "인터뷰 세부결과(3)", "review_state": "candidate",
              "subject": "unclear"}]
    questions = conflict_questions(facts)
    assert not any("서로 다른 수치" in question for question in questions)
    assert not any("결과 수치" in question for question in questions)


def test_every_chunk_of_every_ready_file_is_read():
    from uuid import uuid4

    from skive.drive_activity_analysis import source_batches

    files = [{"id": uuid4(), "name": f"보고서{i}.md", "version": 1, "analysis_status": "ready"} for i in range(50)]
    rows = [{"file_id": file["id"], "file_version": 1, "chunk_index": index, "location": f"L{index}",
             "text": f"{file['name']} 구간 {index}"} for file in files for index in range(1, 7)]

    class Connection:
        def execute(self, *_):
            return type("Result", (), {"fetchall": lambda _: rows})()

    batches, covered = source_batches(Connection(), files, uuid4())
    assert covered == 50
    assert sum(len(refs) for refs, _, _ in batches) == 300


def test_lines_are_not_cut_from_the_middle_of_a_long_file():
    from types import SimpleNamespace
    from uuid import uuid4

    from skive.drive_activity_analysis import ProposedFacts, propose
    from skive.loaders import Chunk

    file = {"id": uuid4(), "name": "report.md"}
    text = "\n".join(f"line number {index} here" for index in range(400))
    batch = ({"C1": {"file": file, "row": {"location": "L1-400", "chunk_index": 1}}},
             {"C1": Chunk("report.md", "L1-400", text)}, "")
    seen = {}

    def invoke(messages):
        seen["text"] = messages[1].content
        return ProposedFacts(facts=[])

    propose(batch, "활동", model=SimpleNamespace(invoke=invoke))
    assert "line number 399 here" in seen["text"]


def _batches_for(names):
    from uuid import uuid4

    from skive.drive_activity_analysis import source_batches

    files = [{"id": uuid4(), "name": name, "version": 1, "analysis_status": "ready"} for name in names]
    rows = [{"file_id": file["id"], "file_version": 1, "chunk_index": index, "location": f"L{index}",
             "text": f"{file['name']} 구간 {index}"} for file in files for index in range(1, 4)]

    class Connection:
        def execute(self, _query, params):
            wanted = set(params[1])  # The real query returns only the requested files.
            found = [row for row in rows if row["file_id"] in wanted]
            return type("Result", (), {"fetchall": lambda _: found})()

    batches, _ = source_batches(Connection(), files, uuid4())
    return [(ref["file"]["name"], ref["row"]["chunk_index"]) for refs, _, _ in batches for ref in refs.values()]


def test_code_and_raw_data_stay_out_when_documents_exist():
    seen = _batches_for(["보고서.pdf", "train.py", "batch_1.json", "raw.csv"])
    assert {name for name, _ in seen} == {"보고서.pdf"}
    assert len(seen) == 3


def test_results_get_a_first_look_only():
    seen = _batches_for(["보고서.pdf", "results_summary.csv"])
    assert [index for name, index in seen if name == "results_summary.csv"] == [1]


def test_code_is_sampled_when_a_project_has_no_documents():
    seen = _batches_for(["train.py", "eval.py"])
    assert {name for name, _ in seen} == {"train.py", "eval.py"}
    assert {index for _, index in seen} == {1}


def test_lock_files_are_never_read():
    assert _batches_for(["package-lock.json"]) == []

