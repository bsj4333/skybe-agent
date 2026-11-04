"""Only the deterministic pre-save checks; model behavior needs live evaluation."""

import pytest
from pydantic import ValidationError

from skive.drive_career import JobCreate, _draft_gap


def test_draft_gap_asks_about_unsupported_metric():
    sources = [{"index": 1, "excerpt": "SCM 프로젝트에서 BOM 구조를 분석했다."}]
    assert "92%" in _draft_gap("정확도를 92% 높였습니다. [파일 1]", sources, [])


def test_draft_gap_asks_about_missing_citation():
    sources = [{"index": 1, "excerpt": "BOM 구조를 분석했다."}]
    assert "2번" in _draft_gap("BOM 구조를 분석했습니다. [파일 2]", sources, [])


def test_draft_gap_allows_number_in_user_statement_without_document_upgrade():
    memories = [{"content": "사용자 확인: 팀 보고서의 처리 시간이 12% 감소했다."}]
    assert _draft_gap("팀 보고서의 처리 시간은 12% 줄었습니다. [본인 진술]", [], memories) == ""


def test_draft_gap_requires_user_statement_label():
    assert "표시하지" in _draft_gap("제가 자료 정리를 맡았습니다.", [], [{"content": "자료 정리를 맡음"}])


def test_draft_gap_accepts_current_reviewed_fact_but_checks_its_index_and_numbers():
    reviewed = [{"index": 1, "content": "불량률 12% 감소", "review_note": "내가 평가를 맡음"}]
    assert _draft_gap("불량률 12% 감소를 확인했습니다. [활동 사실 1]", [], [], reviewed) == ""
    assert "인용" in _draft_gap("불량률 12% 감소를 확인했습니다. [활동 사실 2]", [], [], reviewed)
    assert "99%" in _draft_gap("불량률 99% 감소를 확인했습니다. [활동 사실 1]", [], [], reviewed)


def test_job_rejects_script_link_and_blank_title():
    with pytest.raises(ValidationError):
        JobCreate(title="공고", job_url="javascript:alert(1)")
    with pytest.raises(ValidationError):
        JobCreate(title="   ")
