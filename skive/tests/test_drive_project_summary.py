from uuid import uuid4

from skive.drive_project_summary import (
    AppendixSection,
    EvidenceRef,
    GroundedNote,
    ProjectMetric,
    ProjectStage,
    ProjectSubmission,
    ensure_stage_coverage,
    render_project_markdown,
    validate_submission,
)


def evidence(source_id="S1", quote="F1 0.2254, 오탐률 0.5294, 리드타임 197분"):
    return [EvidenceRef(source_id=source_id, quote=quote)]


def test_project_summary_keeps_fixed_sections_and_grounded_free_appendix():
    sources = {"S1": {
        "text": "Best candidate: F1 0.2254, 오탐률 0.5294, 리드타임 197분",
        "path": "건설장비 / 모델링 / report.md", "file_version": 2,
        "location": "L10-20", "chunk_index": 1,
    }}
    submission = ProjectSubmission(
        overview=[GroundedNote(text="프로젝트의 최고 F1은 0.2254였다", evidence=evidence())],
        stages=[ProjectStage(name="모델링", path="건설장비 / 모델링",
                             purpose="후보 모델의 F1 0.2254를 평가했다", evidence=evidence())],
        metrics=[ProjectMetric(name="F1", value="0.2254", subject="project", evidence=evidence())],
        personal_actions=[GroundedNote(text="내가 모델을 만들었다", subject="user", evidence=evidence())],
        questions=["모델 구현에서 직접 맡은 부분은 무엇인가요?"],
        appendix=[AppendixSection(title="운영 관점", kind="interpretation",
                                  body="리드타임 197분을 운영 조건과 함께 검토할 필요가 있다.",
                                  evidence=evidence())],
    )
    structured, held = validate_submission(submission, sources)
    markdown = render_project_markdown(
        "건설장비", uuid4(), structured, sources,
        {"folders_total": 4, "files_total": 20, "text_ready": 18,
         "unread_or_partial": 2, "analysis_status": {"ready": 18, "unsupported": 2}}, held,
    )
    assert "## 프로젝트 한눈에 보기" in markdown
    assert "## 폴더와 작업 단계" in markdown
    assert "## AI 확장 부록" in markdown
    assert "리드타임 197분을 운영 조건" in markdown
    assert "내가 모델을 만들었다" not in markdown.split("### 본인이 했다고 확인된 작업", 1)[1].split("### 본인 역할 확인 필요", 1)[0]
    assert "본인 역할 자동 확정 보류" in markdown
    assert "[S1] 건설장비 / 모델링 / report.md" in markdown


def test_project_summary_rejects_unsupported_numbers_and_stage_explanations():
    sources = {"S1": {"text": "정확도는 80%였다", "path": "p / report.md",
                       "file_version": 1, "location": "L1", "chunk_index": 1}}
    submission = ProjectSubmission(
        metrics=[ProjectMetric(name="정확도", value="99%", evidence=[EvidenceRef(
            source_id="S1", quote="정확도는 80%였다")])],
        stages=[ProjectStage(name="전처리", path="p / 전처리", purpose="결측치를 모두 제거했다")],
    )
    structured, held = validate_submission(submission, sources)
    assert structured["metrics"] == []
    assert structured["stages"] == []
    assert any("수치 보류" in item for item in held)
    assert any("단계 설명 보류" in item for item in held)


def test_project_stage_detection_skips_single_wrapper_and_keeps_every_real_stage():
    root, wrapper, stage1, stage2 = uuid4(), uuid4(), uuid4(), uuid4()
    folders = [
        {"id": root, "name": "화력발전소", "path": "화력발전소", "depth": 0},
        {"id": wrapper, "name": "사용자A", "path": "화력발전소 / 사용자A", "depth": 1},
        {"id": stage1, "name": "1. 전처리", "path": "화력발전소 / 사용자A / 1. 전처리", "depth": 2},
        {"id": stage2, "name": "2. 모델링", "path": "화력발전소 / 사용자A / 2. 모델링", "depth": 2},
    ]
    structured = ProjectSubmission(stages=[ProjectStage(
        name="1. 전처리", path="화력발전소 / 사용자A / 1. 전처리",
        purpose="자료 역할 미확인",
    )]).model_dump()
    merged = ensure_stage_coverage(structured, folders)
    assert [stage["name"] for stage in merged["stages"]] == ["1. 전처리", "2. 모델링"]
    assert merged["stages"][1]["purpose"] == "자료 역할 미확인"


def test_project_summary_repairs_paraphrased_quote_to_exact_source_text():
    sources = {"S1": {
        "text": "정확한 원문 줄: 모델 F1은 0.2254로 측정되었다.\n다음 문장",
        "path": "project / report.md", "file_version": 1,
        "location": "L1-2", "chunk_index": 1,
    }}
    submission = ProjectSubmission(overview=[GroundedNote(
        text="모델 F1은 0.2254로 측정되었다",
        evidence=[EvidenceRef(source_id="S1", quote="F1이 0.2254였음")],
    )])
    structured, held = validate_submission(submission, sources)
    assert held == []
    assert structured["overview"][0]["evidence"][0]["quote"] == (
        "정확한 원문 줄: 모델 F1은 0.2254로 측정되었다."
    )
    markdown = render_project_markdown(
        "project", uuid4(), structured, sources,
        {"folders_total": 1, "files_total": 1, "text_ready": 1,
         "unread_or_partial": 0, "analysis_status": {"ready": 1}}, [],
    )
    assert "원문: “정확한 원문 줄: 모델 F1은 0.2254로 측정되었다.”" in markdown
