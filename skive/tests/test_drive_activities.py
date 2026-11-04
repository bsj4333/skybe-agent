from uuid import uuid4

from skive.drive_activities import ActivityCreate, activity_markdown


def test_activity_accepts_different_study_and_project_labels_without_required_grade():
    course = ActivityCreate(title="  SCM   수업  ", kind_tags=["수업", "물류", "수업"])
    experiment = ActivityCreate(title="반응기 실험", kind_tags=["화공", "실험"])
    assert course.title == "SCM 수업"
    assert course.kind_tags == ["수업", "물류"]
    assert experiment.period_note is None


def test_activity_markdown_is_only_a_source_index_not_a_personal_claim():
    file_id = uuid4()
    markdown = activity_markdown(
        {"title": "화력발전소 이상탐지", "kind_tags": ["팀 프로젝트"], "period_note": None},
        [{"id": file_id, "name": "report.pdf", "version": 1,
          "upload_status": "uploaded", "analysis_status": "ready"}],
    )
    assert "활동 자료 목차" in markdown
    assert "파일 ID" in markdown and str(file_id) in markdown
    assert "본인 역할, 성과를 아직 확인하지 않았습니다" in markdown
    assert "기간: 미확인" in markdown
