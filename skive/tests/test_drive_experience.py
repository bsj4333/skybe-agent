"""Experience map and sentence check rules that must hold without a model or database."""

from skive.drive_experience import (
    Narrative,
    NarrativeParagraph,
    NarrativeSkill,
    ProposedExperience,
    attach_by_folder,
    grounded_narrative,
    rule_owner,
    valid_experiences,
)
from skive.drive_sentence_check import Judgment, merge_judgments, split_sentences


def experience(ids):
    return ProposedExperience(title="경험", category="프로젝트", card_ids=ids)


def test_invented_file_ids_are_dropped():
    kept = valid_experiences([experience([1, 2, 999])], {1, 2})
    assert kept[0].card_ids == [1, 2]


def test_one_file_lands_in_one_candidate_and_empty_groups_vanish():
    kept = valid_experiences([experience([1, 2]), experience([2]), experience([777])], {1, 2})
    assert [item.card_ids for item in kept] == [[1, 2]]


def test_senior_folder_is_other_person_regardless_of_model():
    assert rule_owner("자기소개서/선배님들 자소서/김철수", "자소서.docx", "홍길동") == "other_person"


def test_own_name_beats_the_folder_rule():
    assert rule_owner("자기소개서/선배님들 자소서", "홍길동_첨삭.docx", "홍길동") == "self"


def test_own_folder_is_left_to_the_model():
    assert rule_owner("종합설계/홍길동/선배 자료", "보고서.pdf", "홍길동") is None


def test_reference_folder_and_plain_folder():
    assert rule_owner("3-2/족보", "기출.pdf", "홍길동") == "reference"
    assert rule_owner("3-2/신뢰성", "보고서.pdf", "홍길동") is None


def test_code_follows_the_experience_of_its_folder():
    items = [{"id": 1, "path": "프로젝트/A"}, {"id": 2, "path": "프로젝트/A"}, {"id": 3, "path": "프로젝트/B"}]
    bulk = [{"id": "x", "path": "프로젝트/A/src"}, {"id": "y", "path": "다른곳"}]
    attached = attach_by_folder({1: 0, 2: 0, 3: 1}, items, bulk)
    assert [file["id"] for file in attached[0]] == ["x"]
    assert 1 not in attached


def test_narrative_keeps_only_offered_experiences_and_known_numbers():
    data = {"experiences": [{"id": "a", "title": "이상탐지", "facts": [{"content": "F1 0.86"}]}], "entries": []}
    narrative = Narrative(
        paragraphs=[NarrativeParagraph(text="F1 0.86을 확인했다", experience_ids=["a", "ghost"]),
                    NarrativeParagraph(text="정확도 99를 달성했다", experience_ids=["a"]),
                    NarrativeParagraph(text="근거 없는 문단", experience_ids=["ghost"])],
        skills=[NarrativeSkill(name="시계열", experience_ids=["ghost"])])
    result = grounded_narrative(narrative, data)
    assert [item["experience_ids"] for item in result["paragraphs"]] == [["a"]]
    assert result["skills"] == []


def test_sentences_are_split():
    assert split_sentences("첫 문장입니다. 둘째 문장입니다.\n\n셋째 문장입니다.") == [
        "첫 문장입니다.", "둘째 문장입니다.", "셋째 문장입니다."]


def test_missing_judgment_is_not_a_pass():
    checks = merge_judgments(["모델을 비교했습니다."], [], "모델을 비교했습니다.")
    assert checks[0]["status"] == "unsupported"


def test_code_catches_a_number_the_judge_passed():
    checks = merge_judgments(["F1을 0.91로 높였습니다 [파일 1]."],
                             [Judgment(id=0, status="supported")], "F1은 0.86이다.")
    assert checks[0]["status"] == "unsupported"
    assert "0.91" in checks[0]["reason"]


def test_citation_numbers_are_not_treated_as_claims():
    checks = merge_judgments(["모델을 비교했습니다 [파일 3]."],
                             [Judgment(id=0, status="supported")], "모델을 비교했다.")
    assert checks[0]["status"] == "supported"
