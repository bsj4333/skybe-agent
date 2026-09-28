from uuid import uuid4

from skive.drive_activity_markdown import render_activity_markdown


def test_markdown_only_promotes_confirmed_current_facts_with_source():
    file_id = uuid4()
    common = {"source_file_id": file_id, "source_file_version": 2,
              "source_chunk_index": 4, "source_location": "p.3",
              "source_file_name": "report.pdf", "source_quote": "정확도 92%",
              "review_note": "내가 평가 코드를 작성함", "subject": "user", "kind": "result"}
    facts = [{**common, "content": "정확도 92%", "review_state": "confirmed", "stale": False},
             {**common, "content": "정확도 99%", "review_state": "candidate", "stale": False},
             {**common, "content": "정확도 88%", "review_state": "confirmed", "stale": True}]
    md = render_activity_markdown({"title": "실험"},
                                  [{"analysis_status": "ready"}], facts)
    assert "정확도 92%" in md
    assert "report.pdf" in md and "버전 2" in md and "C4" in md and "p.3" in md
    result_section = md.split("## 결과", 1)[1].split("## 사용한 역량", 1)[0]
    assert "정확도 99%" not in result_section and "정확도 88%" not in result_section
    assert "출처 재검토: 1개" in md


def test_markdown_does_not_invent_missing_role_or_result():
    md = render_activity_markdown({"title": "SCM 수업"}, [], [])
    assert "확인된 내용 없음" in md
    assert "본인 확인" not in md
