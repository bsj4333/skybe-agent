from uuid import uuid4

from skive.drive_activity_suggestions import suggest_groups


def test_suggestions_overlap_for_user_review_and_do_not_create_every_stage():
    root, project_a, project_b, stage = [uuid4() for _ in range(4)]
    folders = [
        {"id": root, "parent_id": None, "name": "종합설계"},
        {"id": project_a, "parent_id": root, "name": "건설장비 이상탐지"},
        {"id": project_b, "parent_id": root, "name": "화력발전소 이상탐지"},
        {"id": stage, "parent_id": project_a, "name": "데이터 전처리"},
    ]
    files = [{"id": uuid4(), "folder_id": folder, "name": f"file-{i}.pdf",
              "analysis_status": "ready"}
             for i, folder in enumerate([stage, stage, project_b, project_b], 1)]
    groups = suggest_groups(folders, files)
    assert {group["title"] for group in groups} == {
        "종합설계", "건설장비 이상탐지", "화력발전소 이상탐지"}
    assert next(group for group in groups if group["title"] == "종합설계")["file_count"] == 4
    assert all(group["reason"] for group in groups)


def test_single_file_and_unfoldered_files_are_not_forced_into_activities():
    folder = uuid4()
    assert suggest_groups([{"id": folder, "parent_id": None, "name": "SCM"}], [
        {"id": uuid4(), "folder_id": folder, "name": "one.pdf", "analysis_status": "ready"},
        {"id": uuid4(), "folder_id": None, "name": "other.txt", "analysis_status": "ready"},
    ]) == []


def test_cross_folder_matching_source_terms_are_review_candidates():
    folders = [{"id": uuid4(), "parent_id": None, "name": name}
               for name in ("첫 자료함", "두 번째 자료함", "다른 실험")]
    files = [
        {"id": uuid4(), "folder_id": folders[0]["id"], "name": "reactor-failure.txt",
         "analysis_status": "ready", "preview": "reactor failure anomaly signal"},
        {"id": uuid4(), "folder_id": folders[1]["id"], "name": "reactor-anomaly.md",
         "analysis_status": "ready", "preview": "reactor failure anomaly detection"},
        {"id": uuid4(), "folder_id": folders[2]["id"], "name": "vitamin.txt",
         "analysis_status": "ready", "preview": "vitamin dosage study"},
    ]
    groups = suggest_groups(folders, files)
    assert len(groups) == 1
    assert groups[0]["file_count"] == 2
    assert "원문" in groups[0]["reason"]
    assert {item["id"] for item in groups[0]["files"]} == {files[0]["id"], files[1]["id"]}
