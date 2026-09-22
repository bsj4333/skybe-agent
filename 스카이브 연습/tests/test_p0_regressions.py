"""SKIVE_NEXT_PLAN.md의 P0 결함 F01~F05 고정 회귀 테스트.

LLM·DB·실제 파일 쓰기 없이 순수 함수와 monkeypatch만 쓴다. 매 변경마다 돌릴 수 있어야 한다.

아직 안 고친 결함은 `xfail(strict=True)`로 남겨둔다 — 고치는 순간 XPASS로 바뀌면서
"이제 통과한다"고 알려주고, 그때 마커를 지우면 된다.
"""

import json

import pytest

from skive import analyzer, corrections, facts as facts_v2, store, verify, writer
from skive.loaders import Chunk
from skive.models import Answerability, CorrectionProposal, Evidence, Fact
from skive.models import JobRequirements, QuestionPlan

META = {"id": "t", "title": "T", "grade": 3, "sources": ["r.md"]}
FACTS = {
    "title": "T", "summary": "s", "period": "p",
    "my_role": "모델 구현 담당", "my_role_verified": True,
    "actions": [], "decisions": [],
    "results": [{
        "text": "F1-score가 0.71에서 0.86으로 향상되었다.",
        "owner": "팀", "verified": True,
        "sources": ["r.md @ L1-10"], "tag": "[근거: r.md @ L1-10]",
    }],
    "skills": [], "lessons": "확인 필요",
}
MD = (
    "# T\n\n## My Role\n모델 구현 담당 [근거: r.md @ L1-10]\n\n"
    "## Results\n- (팀) F1-score가 0.71에서 0.86으로 향상되었다. [근거: r.md @ L1-10]\n"
)


@pytest.fixture
def fixture_store(monkeypatch):
    """실제 data/ 를 건드리지 않고 정정 경로를 돌린다."""
    monkeypatch.setattr(store, "get_meta", lambda i: dict(META))
    monkeypatch.setattr(store, "get_facts", lambda i: json.loads(json.dumps(FACTS)))
    monkeypatch.setattr(store, "get_markdown", lambda i: MD)
    monkeypatch.setattr(store, "save", lambda *a, **k: None)
    monkeypatch.setattr(corrections, "_append_history", lambda *a, **k: None)


def _correct(field, original, corrected):
    return corrections.apply_correction(CorrectionProposal(
        is_correction=True, kind="correction", experience_id="t",
        field=field, original_text=original, corrected_text=corrected, reason="테스트",
    ))


# ── F01: 정정이 검증 상태·원본 인용을 물려받지 않는다 ────────────────────

def test_f01_correction_does_not_inherit_verification(fixture_store):
    res = _correct("result", FACTS["results"][0]["text"], "F1-score는 사실 0.99였다.")
    item = res["facts"]["results"][0]

    assert item["text"] == "F1-score는 사실 0.99였다."
    assert facts_v2.provenance(item) == facts_v2.USER_STATEMENT
    assert facts_v2.evidence_status(item) == facts_v2.NEEDS_REVIEW
    assert item["evidence"] == [], "이전 인용을 상속하면 안 된다"
    assert item["verified"] is False
    assert not facts_v2.is_document_backed(item)


def test_f01_previous_version_is_preserved_not_deleted(fixture_store):
    res = _correct("result", FACTS["results"][0]["text"], "F1-score는 사실 0.99였다.")

    superseded = res["facts"]["superseded"]
    assert len(superseded) == 1
    assert superseded[0]["text"] == FACTS["results"][0]["text"]
    assert superseded[0]["lifecycle"] == facts_v2.SUPERSEDED
    assert res["facts"]["results"][0]["version"] == superseded[0]["version"] + 1
    # 감사용으로 이전 근거는 남되, 근거로는 쓰이지 않는다
    assert res["facts"]["results"][0]["prior_evidence"][0]["source"] == "r.md"


def test_f01_role_correction_drops_document_verification(fixture_store):
    res = _correct("my_role", "모델 구현 담당", "사실 팀원이 구현했고 나는 참여만 함")
    facts = res["facts"]

    assert facts["my_role_verified"] is False
    assert facts["my_role_provenance"] == facts_v2.USER_STATEMENT
    assert facts["my_role_corrected_from"] == "모델 구현 담당"


def test_f01_corrected_fact_is_separated_in_writer_bundle(monkeypatch, fixture_store):
    corrected = _correct("result", FACTS["results"][0]["text"], "F1-score는 사실 0.99였다.")["facts"]
    monkeypatch.setattr(store, "get_facts", lambda i: corrected)

    bundle = writer.build_bundle("t")

    # 문서 근거 항목에 섞이면 안 되고, 본인 진술 항목에 출처가 드러나야 한다
    documented = bundle.split("[본인 진술")[0]
    assert "0.99" not in documented
    assert "[본인 진술 — 원문 근거 없음]" in bundle
    assert "0.99" in bundle.split("[본인 진술")[1]


def test_f01_role_correction_changes_writer_instruction(monkeypatch, fixture_store):
    corrected = _correct("my_role", "모델 구현 담당", "팀원이 구현했고 나는 참여만 함")["facts"]
    monkeypatch.setattr(store, "get_facts", lambda i: corrected)

    bundle = writer.build_bundle("t")
    assert "자료에서 확인" not in bundle.split("\n")[1]
    assert "원문 근거 없음" in bundle


# ── F02~F05: 아직 안 고침. 고치면 XPASS로 알려준다 ──────────────────────

@pytest.mark.xfail(strict=True, reason="0-6에서 수정: 모든 도구에 서버 주입 범위 강제")
def test_f02_scoped_chat_tools_reject_other_experiences():
    from skive.chat import _build_tools

    tools = {t.name: t for t in _build_tools("3d_printer_raw")}
    result = tools["get_experience"].invoke({"experience_id": "club_website_raw"})
    assert "범위" in result or "권한" in result, "스코프 밖 경험이 그대로 조회됐다"


def _analyze(claim, quote, chunk_text, owner="본인"):
    chunks = {"C1": Chunk(source="r.md", location="L1-5", text=chunk_text)}
    return analyzer._process(
        [Fact(text=claim, owner=owner, evidence=[Evidence(chunk_id="C1", quote=quote)])],
        chunks, {"total": 0, "verified": 0}, None,
    )[0]


def test_f03_unrelated_quote_is_not_marked_verified():
    quote = "팀은 보고서를 작성했다."
    fact = _analyze("내가 Kubernetes 클러스터를 구축했다.", quote, quote)

    assert fact["verified"] is False
    assert facts_v2.evidence_status(fact) == facts_v2.NEEDS_REVIEW
    assert not facts_v2.is_document_backed(fact)
    assert fact["sources"] == [], "검사에 떨어진 근거를 출처로 내보내면 안 된다"


def test_f03_quote_is_stored_for_audit():
    quote = "팀은 보고서를 작성했다."
    ev = _analyze("내가 Kubernetes 클러스터를 구축했다.", quote, quote)["evidence"][0]

    assert ev["quote"] == quote, "quote를 저장해야 사후 감사가 가능하다"
    assert ev["source"] == "r.md" and ev["location"] == "L1-5"
    # 네 검사가 각각 따로 기록돼야 왜 떨어졌는지 알 수 있다
    assert ev["quote_matched"] is True, "인용문 자체는 원문에 존재한다"
    assert ev["supports_claim"] is False
    assert ev["owner_match"] is False


def test_f03_genuine_evidence_still_passes():
    quote = "F1-score가 0.71에서 0.86으로 향상되었다."
    fact = _analyze("F1-score가 0.71에서 0.86으로 향상되었다.", quote, f"프로젝트 결과, {quote}")

    assert fact["verified"] is True
    assert facts_v2.is_document_backed(fact)
    assert fact["sources"] == ["r.md @ L1-5"]


def test_f03_number_not_in_quote_is_rejected():
    quote = "모델 성능이 향상되었다."
    fact = _analyze("모델 성능이 12%p 향상되었다.", quote, quote)

    assert fact["verified"] is False, "인용문에 없는 수치를 주장에 넣으면 안 된다"
    assert fact["evidence"][0]["numbers_missing"] == ["12"]


def test_f03_missing_chunk_is_unlinked():
    fact = analyzer._process(
        [Fact(text="아무 주장", owner="팀",
              evidence=[Evidence(chunk_id="C99", quote="어디에도 없는 문구")])],
        {}, {"total": 0, "verified": 0}, None,
    )[0]

    assert facts_v2.evidence_status(fact) == facts_v2.UNLINKED
    assert fact["evidence"][0]["quote_matched"] is False


@pytest.mark.xfail(strict=True, reason="0-4에서 수정: 문장 ID + 판정 커버리지 + 최종 재검증")
def test_f04_unremovable_sentence_is_not_reported_as_cleaned(monkeypatch):
    bad = "이 경험을 통해 큰 성장을 이루었습니다."
    monkeypatch.setattr(writer, "_gate", lambda q, b: Answerability(level="가능", missing=""))
    monkeypatch.setattr(writer, "_write", lambda *a, **k: f"팀은 모델을 만들었습니다. {bad}")
    monkeypatch.setattr(writer, "_check", lambda d, b, j, i: (
        ['[unsupported] "이 경험을 통해 큰 성장을 이뤘습니다." — 자료에 없음'],
        ["이 경험을 통해 큰 성장을 이뤘습니다."],  # 판정자가 원문과 다르게 돌려준 경우
    ))
    monkeypatch.setattr(store, "get_meta", lambda i: dict(META))
    monkeypatch.setattr(store, "get_facts", lambda i: json.loads(json.dumps(FACTS)))

    ans = writer.answer_question(
        JobRequirements(company="c", role="r", responsibilities=[], required_skills=[],
                        preferred_skills=[], values=[], key_competencies=[], essay_questions=[]),
        QuestionPlan(question="q", experience_ids=["t"], angle="a", gap=""),
    )
    assert not (bad in ans["draft"] and ans["status"] == "정제"), \
        "문제 문장이 남았는데 '정제'라고 표시하면 안 된다"


@pytest.mark.xfail(strict=True, reason="0-5에서 수정: (지표, 값, 단위) 튜플로 비교")
def test_f05_different_metric_with_same_digits_is_flagged():
    source = "프로젝트 결과, F1-score가 0.71에서 0.86으로 향상되었다."
    assert verify.unsupported_numbers("정확도 71%를 달성했습니다.", source), \
        "F1-score 0.71을 근거로 '정확도 71%'가 통과하면 안 된다"
