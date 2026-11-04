"""SKIVE_NEXT_PLAN.md의 P0 결함 F01~F05 고정 회귀 테스트.

LLM·DB·실제 파일 쓰기 없이 순수 함수와 monkeypatch만 쓴다. 매 변경마다 돌릴 수 있어야 한다.

아직 안 고친 결함은 `xfail(strict=True)`로 남겨둔다 — 고치는 순간 XPASS로 바뀌면서
"이제 통과한다"고 알려주고, 그때 마커를 지우면 된다.
"""

import json
import shutil

import pytest

from skive import analyzer, chat, corrections, facts as facts_v2, store, verify, writer
from skive.loaders import Chunk
from skive.models import UNKNOWN, Answerability, CorrectionProposal, Evidence, Fact
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
    "## Results\n- (팀) F1-score가 0.71에서 0.86으로 향상되었다. [근거: r.md @ L1-10]\n\n"
    "## Lessons\n확인 필요\n"
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


# ── F02: 읽기 도구도 스코프를 서버 코드로 강제한다 (R01/R08 대응) ──────────

def _scoped_tools(scope_id):
    from skive.chat import _build_tools
    from skive.context import new_context

    return {t.name: t for t in _build_tools(new_context(active_scope_id=scope_id))}


def test_f02_get_experience_rejects_other_scope(fixture_store):
    tools = _scoped_tools("t")
    result = tools["get_experience"].invoke({"experience_id": "other_raw"})
    assert "범위" in result
    assert result != store.get_markdown("other_raw")


def test_f02_get_evidence_rejects_other_scope(fixture_store):
    tools = _scoped_tools("t")
    result = tools["get_evidence"].invoke({"experience_id": "other_raw", "source": "r.md"})
    assert "범위" in result


LIST_META = {
    "id": "t", "title": "T", "grade": 3, "kind": "project", "period": "p",
    "importance": {"tier": "핵심"}, "my_role_verified": True, "summary": "s", "skills": [],
}


def test_f02_list_experiences_hides_other_scope(fixture_store, monkeypatch):
    monkeypatch.setattr(
        store, "list_meta",
        lambda: [dict(LIST_META), {**LIST_META, "id": "other_raw", "title": "다른 경험"}],
    )
    tools = _scoped_tools("t")
    result = tools["list_experiences"].invoke({})
    assert "other_raw" not in result, "스코프 밖 id가 노출되면 다음 조회에서 우회 통로가 된다"
    assert "id=t" in result


def test_f02_unscoped_tools_still_see_everything(fixture_store, monkeypatch):
    """agent.py(공고 매칭)처럼 스코프가 없는 호출까지 막으면 안 된다."""
    monkeypatch.setattr(
        store, "list_meta",
        lambda: [dict(LIST_META), {**LIST_META, "id": "other_raw", "title": "다른 경험"}],
    )
    tools = _scoped_tools(None)
    result = tools["list_experiences"].invoke({})
    assert "other_raw" in result


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


# ── F04: 판정에서 걸린 문장은 반드시 지워지거나, 못 지우면 '정제'라고 하지 않는다 ──

def test_f04_unremovable_sentence_is_not_reported_as_cleaned(monkeypatch):
    """_check()가 (버그가 있었다면 있었을) 원문과 안 맞는 문장을 flagged로 줘도,
    최종 재검증(_remove_flagged)이 '정제'로 잘못 부르는 걸 마지막 방어선에서 잡는다."""
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
    assert ans["status"] == "경고"
    assert bad in ans["draft"], "이 테스트의 전제는 삭제가 실패하는 상황이다"
    assert any("삭제 실패" in i for i in ans["issues"])


def _judge(monkeypatch, verdicts: dict[str, tuple[str, str]]):
    """sentence_id -> (verdict, reason) 맵으로 judge LLM 호출을 대체한다."""
    from skive.models import JudgeResult, SentenceCheck

    class _Judge:
        def with_structured_output(self, _model):
            return self

        def invoke(self, _messages):
            return JudgeResult(checks=[
                SentenceCheck(sentence_id=sid, verdict=v, reason=r) for sid, (v, r) in verdicts.items()
            ])

    monkeypatch.setattr(writer, "get_judge_llm", lambda: _Judge())


def _job():
    return JobRequirements(company="c", role="r", responsibilities=[], required_skills=[],
                            preferred_skills=[], values=[], key_competencies=[], essay_questions=[])


def test_f04_check_uses_sentence_id_not_paraphrase_matching(monkeypatch):
    """판정자가 문장을 살짝 바꿔 돌려줘도(sentence 문자열이 아니라 ID로 대응하므로) 정상 판정된다."""
    draft = "팀은 모델을 만들었다. 내가 API를 설계했다."
    _judge(monkeypatch, {"S1": ("supported", ""), "S2": ("unsupported", "자료에 없음")})

    issues, flagged = writer._check(draft, "bundle", _job(), [])
    assert flagged == ["내가 API를 설계했다."], "판정자의 재현 문자열이 아니라 원문 문장 리스트에서 가져와야 한다"


def test_f04_judge_skipping_a_sentence_counts_as_failure(monkeypatch):
    """판정자가 문장 하나를 아예 언급 안 하면 '통과'로 취급하지 않는다 — 커버리지 검사."""
    draft = "팀은 모델을 만들었다. 내가 API를 설계했다."
    _judge(monkeypatch, {"S1": ("supported", "")})  # S2 누락

    issues, flagged = writer._check(draft, "bundle", _job(), [])
    assert "내가 API를 설계했다." in flagged
    assert any("커버리지 누락" in i for i in issues)


def test_f04_judge_inventing_unknown_id_is_reported(monkeypatch):
    draft = "팀은 모델을 만들었다."
    _judge(monkeypatch, {"S1": ("supported", ""), "S9": ("unsupported", "존재 안 하는 id")})

    issues, flagged = writer._check(draft, "bundle", _job(), [])
    assert any("판정 오류" in i for i in issues)
    assert flagged == []


# ── F05: 같은 숫자라도 지표 이름이 다르면 다른 수치로 본다 ──────────────────

def test_f05_different_metric_with_same_digits_is_flagged():
    source = "프로젝트 결과, F1-score가 0.71에서 0.86으로 향상되었다."
    assert verify.unsupported_numbers("정확도 71%를 달성했습니다.", source), \
        "F1-score 0.71을 근거로 '정확도 71%'가 통과하면 안 된다"


def test_f05_same_metric_percent_vs_decimal_notation_passes():
    """같은 지표를 소수/퍼센트로 다르게만 적은 경우까지 막으면 안 된다."""
    source = "프로젝트 결과, 정확도가 0.88에서 0.92로 향상되었다."
    assert verify.unsupported_numbers("정확도 92%를 달성했습니다.", source) == []


def test_f05_genuinely_unsupported_number_is_still_flagged():
    source = "프로젝트 결과, F1-score가 0.71에서 0.86으로 향상되었다."
    assert "99" in verify.unsupported_numbers("정확도 99%를 달성했습니다.", source)


def test_f05_decimal_point_is_not_exploded_into_digit_parts():
    mentions = verify.number_mentions("F1-score가 0.71에서 0.86으로 향상되었다.")
    values = {m["value"] for m in mentions}
    assert 0.71 in values and 0.86 in values
    assert 71 not in values and 86 not in values, "0.71을 71로 쪼개 넣으면 안 된다"


# ── 제품 결정: 소감·성장 문장은 [배운 점]이 없어도 쓸 수 있다 (2026-09-23) ──
#
# 사용자 피드백: "근거 없다고 다 막으면 자소서 쓸 때 답답하다. 대신 SKIVE의 차별점은
# 매번 정보를 새로 안 넣어도 된다는 것(세션 기억)이지, 문장 하나하나를 틀어막는 게 아니다."
# 그래서 "AI가 새 사실을 지어내는 것"과 "실제 사실에서 자연스럽게 이어지는 소감"을 나눠서,
# 후자만 허용하기로 했다. 프롬프트 문구만 바뀌므로 LLM 없이는 실제 출력을 테스트할 수 없지만,
# 이 결정이 나중에 조용히 되돌아가지 않도록 문구 자체는 고정해 둔다.

def test_writer_core_rules_allow_reflection_without_lessons_field():
    assert "깨달음·성장·각오·소감을 쓰지 않는다" not in writer.WRITER_CORE_RULES, \
        "소감 문장을 무조건 막던 예전 문구가 되돌아왔다"
    assert "성장·소감·깨달음 문장은 쓸 수 있다" in writer.WRITER_CORE_RULES


def test_judge_prompt_treats_grounded_reflection_as_supported():
    assert "자연스럽게 이어지는 소감·성장·깨달음" in writer.JUDGE_PROMPT
    # 그래도 자료에 없는 새 사실을 끼워 넣거나, 역할 미확인인데 본인이 했다고 하는 건 여전히 막는다
    assert "misattributed" in writer.JUDGE_PROMPT
    assert "구체적" in writer.JUDGE_PROMPT and "unsupported" in writer.JUDGE_PROMPT


# ── P0-3: 서버 세션이 클라이언트가 보낸 history 없이도 대화를 기억한다 ──────
#
# 예전엔 브라우저 변수 chatHistory에만 대화가 있어서 새로고침하면 사라졌다. 이제
# checkpointer(SQLite)가 session_id(=thread_id)로 대화를 들고 있어서, 클라이언트가
# 매번 history를 다시 안 보내도 서버가 이전 대화를 기억한다. LLM 없이 검증한다:
# 가짜 LLM을 꽂아서 실제로 체크포인터를 왕복하는지만 본다(응답 품질은 검증 대상이 아님).

class _FakeLLM:
    """get_llm()이 반환하는 실제 LangChain 모델 대신 쓴다. 도구를 호출하지 않고
    바로 답하는 가장 단순한 경로만 확인하면 되므로 이거면 충분하다."""

    def __init__(self, reply="ok"):
        self.reply = reply

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        from langchain_core.messages import AIMessage
        return AIMessage(content=self.reply)


@pytest.fixture
def fixture_chat_session(monkeypatch):
    monkeypatch.setattr(chat, "get_llm", lambda: _FakeLLM())
    monkeypatch.setattr(chat, "recall", lambda *a, **k: [])  # DB 없이 돌리기 위해 빈 결과로 고정
    session_id = "test-p0-3-session"
    yield session_id
    chat.CHECKPOINTER.delete_thread(session_id)  # 다음 테스트 실행에 안 남게 정리


def test_session_remembers_across_separate_calls_without_client_history(fixture_chat_session):
    from skive.context import new_context

    session_id = fixture_chat_session
    chat.ask_in_session(new_context(session_id=session_id), "첫 번째 메시지")
    # 완전히 새 컨텍스트 객체(=새 HTTP 요청을 흉내)로, history를 하나도 안 넘기고 두 번째 호출
    messages, _ = chat.ask_in_session(new_context(session_id=session_id), "두 번째 메시지")

    humans = [m.content for m in messages if m.type == "human"]
    assert humans == ["첫 번째 메시지", "두 번째 메시지"], \
        "클라이언트가 history를 안 보냈는데 이전 turn이 안 보이면 서버 기억이 아니다"


def test_get_session_messages_reads_without_invoking_the_agent(fixture_chat_session):
    from skive.context import new_context

    session_id = fixture_chat_session
    chat.ask_in_session(new_context(session_id=session_id), "안녕")

    # /api/chat/end가 쓰는 경로: 대화를 더 진행하지 않고 지금까지 기록만 읽는다
    messages = chat.get_session_messages(session_id)
    assert any(m.type == "human" and m.content == "안녕" for m in messages)


def test_different_session_ids_do_not_share_history(fixture_chat_session):
    from skive.context import new_context

    session_id = fixture_chat_session
    other_id = session_id + "-other"
    chat.ask_in_session(new_context(session_id=session_id), "세션A 메시지")
    try:
        other_messages, _ = chat.ask_in_session(new_context(session_id=other_id), "세션B 메시지")
        assert not any(m.content == "세션A 메시지" for m in other_messages)
    finally:
        chat.CHECKPOINTER.delete_thread(other_id)


# ── 브라우저 업로드: zip 안의 경로 탈출("zip slip")을 막는다 ─────────────────
#
# 압축 해제 라이브러리 자체를 믿지 않고 서버가 각 항목 경로를 직접 검사한다. 여기서
# LLM이 실제로 필요한 analyze_folder/score_importance는 페이크로 바꿔서, "압축 해제가
# 안전한가"만 따로 검증한다 — 분석 품질은 이 테스트의 관심사가 아니다.

def test_zip_upload_rejects_path_traversal_entries(monkeypatch):
    import io
    import zipfile

    from fastapi.testclient import TestClient

    from skive import server

    def fake_analyze_folder(root, me, exp_id, grade):
        sources = sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())
        meta = {
            "id": exp_id, "title": "T", "summary": "s", "kind": "project", "grade": grade,
            "period": "p", "skills": [], "raw_dir": str(root), "sources": sources,
            "evidence_total": 0, "evidence_verified": 0, "my_role_verified": False, "open_questions": [],
        }
        facts = {
            "title": "T", "summary": "s", "period": "p", "my_role": "확인 필요", "my_role_verified": False,
            "actions": [], "decisions": [], "results": [], "skills": [], "lessons": "확인 필요",
        }
        return "# md", meta, facts

    monkeypatch.setattr(server, "load_user", lambda: {"name": "테스트", "career_goal": "g"})
    monkeypatch.setattr(server, "analyze_folder", fake_analyze_folder)
    monkeypatch.setattr(
        server, "score_importance",
        lambda meta, facts, goal: {"score": 0, "max": 15, "tier": "보관", "breakdown": {}, "reason": ""},
    )
    monkeypatch.setattr(store, "save", lambda *a, **k: None)
    monkeypatch.setattr("skive.chunks_store.sync_chunks", lambda *a, **k: 0)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../../evil.txt", "탈출 시도")
        zf.writestr("normal.md", "정상 파일")
    buf.seek(0)

    exp_id = "test-zip-slip"
    root = store.DATA / "uploads" / exp_id
    try:
        client = TestClient(server.app)
        res = client.post(
            "/api/experiences/upload-zip",
            data={"id": exp_id, "grade": "3"},
            files={"file": ("evil.zip", buf, "application/zip")},
        )
        assert res.status_code == 200
        body = res.json()

        assert body["meta"]["sources"] == ["normal.md"], "탈출 경로 항목이 압축 해제 결과에 섞이면 안 된다"
        assert any(s.get("reason") == "허용되지 않는 경로" for s in body["skipped"])
        assert (root / "normal.md").is_file()
        assert not (store.DATA / "evil.txt").exists(), "data/ 상위로 탈출한 파일이 있으면 안 된다"
        assert not (store.DATA.parent / "evil.txt").exists()
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ── 폴더 업로드: 파일 개수 제한이 실제로 올라간 값을 쓴다 ──────────────────
#
# 실측(2026-09-23): 파일 371개짜리 실사용자 폴더가 두 겹의 숨은 기본값에 막혔다 —
# (1) Starlette 멀티파트 파서의 기본 max_files=1000, (2) 우리 앱의 옛 MAX_UPLOAD_FILES=300.
# (1)을 고치면서 request.form()을 직접 호출하는 방식으로 바꿨는데, 그러면서 돌려주는
# UploadFile이 fastapi.UploadFile이 아니라 그 부모 클래스(starlette)라 isinstance 검사가
# 전부 걸러지는 회귀가 한 번 더 있었다 — 이것도 같이 고정한다.

def _fake_analyze_folder(root, me, exp_id, grade):
    sources = sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())
    meta = {
        "id": exp_id, "title": "T", "summary": "s", "kind": "project", "grade": grade,
        "period": "p", "skills": [], "raw_dir": str(root), "sources": sources,
        "evidence_total": 0, "evidence_verified": 0, "my_role_verified": False, "open_questions": [],
    }
    facts = {
        "title": "T", "summary": "s", "period": "p", "my_role": "확인 필요", "my_role_verified": False,
        "actions": [], "decisions": [], "results": [], "skills": [], "lessons": "확인 필요",
    }
    return "# md", meta, facts


@pytest.fixture
def fixture_upload(monkeypatch):
    from skive import server

    monkeypatch.setattr(server, "load_user", lambda: {"name": "테스트", "career_goal": "g"})
    monkeypatch.setattr(server, "analyze_folder", _fake_analyze_folder)
    monkeypatch.setattr(
        server, "score_importance",
        lambda meta, facts, goal: {"score": 0, "max": 15, "tier": "보관", "breakdown": {}, "reason": ""},
    )
    monkeypatch.setattr(store, "save", lambda *a, **k: None)
    monkeypatch.setattr("skive.chunks_store.sync_chunks", lambda *a, **k: 0)


def test_upload_accepts_more_than_the_old_1000_file_default(fixture_upload):
    from fastapi.testclient import TestClient

    from skive import server

    n = 1200  # 예전 Starlette 기본값(1000)과 예전 우리 제한(300) 둘 다 넘는 개수
    exp_id = "test-manyfiles"
    root = store.DATA / "uploads" / exp_id
    try:
        client = TestClient(server.app)
        files = [("files", (f"note_{i}.txt", f"내용 {i}".encode(), "text/plain")) for i in range(n)]
        res = client.post(
            "/api/experiences/upload",
            data={"id": exp_id, "grade": "3"},
            files=files,
        )
        assert res.status_code == 200, res.text
        assert len(res.json()["meta"]["sources"]) == n
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ── 업로드 직후 인터뷰: 답변이 [본인 진술]로 정직하게 기록된다 ──────────────
#
# 사용자 피드백(2026-09-23): "원본에 명시돼야만 본인 역할 인정"이 너무 빡빡하다 — 대신
# 업로드 직후 몇 가지를 물어보고, 그 답을 [본인 진술]로 기록하자. 문서 근거의 엄격함
# 자체는 그대로 두고(F01 불변식: 상속 금지·승격 금지), 자기 진술 경로를 넓히는 것.

def test_intake_my_role_answer_is_tagged_as_user_statement(fixture_store):
    from fastapi.testclient import TestClient

    from skive import server

    client = TestClient(server.app)
    res = client.post("/api/experiences/t/intake", json={"answers": [
        {"target": "my_role", "question": "본인 역할이 뭐였나요?", "answer": "제가 데이터 파이프라인을 짰습니다"},
    ]})
    assert res.status_code == 200, res.text
    facts = res.json()["facts"]
    assert facts["my_role"] == "제가 데이터 파이프라인을 짰습니다"
    assert facts["my_role_verified"] is False
    assert facts["my_role_provenance"] == facts_v2.USER_STATEMENT


def test_intake_result_answer_becomes_new_self_reported_fact(fixture_store):
    from fastapi.testclient import TestClient

    from skive import server

    client = TestClient(server.app)
    res = client.post("/api/experiences/t/intake", json={"answers": [
        {"target": "result", "question": "어떤 성과를 냈나요?", "answer": "발표에서 우수상을 받았습니다"},
    ]})
    assert res.status_code == 200, res.text
    facts = res.json()["facts"]
    new_result = next(r for r in facts["results"] if r["text"] == "발표에서 우수상을 받았습니다")
    assert facts_v2.provenance(new_result) == facts_v2.USER_STATEMENT
    assert not facts_v2.is_document_backed(new_result), "본인 진술이 문서 근거로 둔갑하면 안 된다"


def test_intake_lessons_answer_is_tagged_as_user_statement(fixture_store, monkeypatch):
    from fastapi.testclient import TestClient

    from skive import server

    client = TestClient(server.app)
    res = client.post("/api/experiences/t/intake", json={"answers": [
        {"target": "lessons", "question": "배운 점이 있나요?", "answer": "협업 시 초기 인터페이스 합의가 중요함을 배웠습니다"},
    ]})
    assert res.status_code == 200, res.text
    facts = res.json()["facts"]
    assert facts["lessons"] == "협업 시 초기 인터페이스 합의가 중요함을 배웠습니다"
    assert facts["lessons_provenance"] == facts_v2.USER_STATEMENT

    monkeypatch.setattr(store, "get_facts", lambda i: facts)
    bundle = writer.build_bundle("t")
    assert "[배운 점 — 본인 진술, 원문 근거 없음]" in bundle


def test_intake_blank_answers_are_skipped(fixture_store):
    from fastapi.testclient import TestClient

    from skive import server

    client = TestClient(server.app)
    res = client.post("/api/experiences/t/intake", json={"answers": [
        {"target": "action", "question": "그 외 알려줄 것", "answer": "   "},
    ]})
    assert res.status_code == 200
    assert res.json()["applied"] == []


# ── 업로드: 검색 인덱스 동기화(DB) 실패가 이미 끝난 분석 결과를 날리면 안 된다 ──
#
# 실측(2026-09-23): Supabase 연결이 간헐적으로 끊긴다. sync_chunks가 던진 예외를
# 그대로 올리면 이미 완료된 analyze_folder/store.save 결과까지 500으로 다 날아가서,
# 사용자가 (비용이 드는) LLM 분석을 처음부터 다시 돌려야 했다. 이제는 청크 동기화만
# "실패"로 표시하고 분석 결과는 살린다.

def test_sync_chunks_failure_does_not_lose_completed_analysis(fixture_upload, monkeypatch):
    from fastapi.testclient import TestClient

    from skive import server

    def boom(*a, **k):
        raise ConnectionError("서버가 연결을 끊음(테스트로 흉내낸 DB 장애)")

    monkeypatch.setattr("skive.chunks_store.sync_chunks", boom)

    exp_id = "test-sync-fail"
    root = store.DATA / "uploads" / exp_id
    try:
        client = TestClient(server.app)
        res = client.post(
            "/api/experiences/upload",
            data={"id": exp_id, "grade": "3"},
            files=[("files", ("note.txt", b"hello", "text/plain"))],
        )
        assert res.status_code == 200, "DB 장애로 이미 끝난 분석 결과까지 실패 처리하면 안 된다"
        meta = res.json()["meta"]
        assert meta["chunks_synced"] is False
        assert "chunks_sync_error" in meta
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ── 정정: 서로 다른 필드가 같은 기본값("확인 필요")을 공유해도 안 섞인다 ────
#
# 실측(2026-09-23, 업로드 직후 인터뷰 기능 테스트 중 발견): My Role과 Lessons가 둘 다
# 미확인 상태면 둘 다 "확인 필요"로 시작한다. My Role을 먼저 정정하면 그 줄에
# "(기존: 확인 필요)" 감사 기록이 남는데, 그다음 Lessons를 정정할 때 문서 전체에서
# "확인 필요"를 찾으면 이 감사 기록 안의 문구가 먼저 걸려서 — My Role 줄이 다시 한번
# 덮어써지고 실제 Lessons 섹션은 전혀 안 바뀌는 사고가 실제로 발생했다.

def test_correction_does_not_cross_into_other_section_with_same_placeholder(monkeypatch):
    meta = {"id": "t", "title": "U", "grade": 3, "sources": ["r.md"]}
    facts = {
        "title": "U", "summary": "s", "period": "p",
        "my_role": UNKNOWN, "my_role_verified": False,
        "actions": [], "decisions": [], "results": [],
        "skills": [], "lessons": UNKNOWN,
    }
    md = f"# U\n\n## My Role\n{UNKNOWN}\n\n## Lessons\n{UNKNOWN}\n"
    saved = {}

    monkeypatch.setattr(store, "get_meta", lambda i: dict(meta))
    monkeypatch.setattr(store, "get_facts", lambda i: dict(saved.get("facts", facts)))
    monkeypatch.setattr(store, "get_markdown", lambda i: saved.get("markdown", md))
    monkeypatch.setattr(store, "save", lambda exp_id, markdown, m, f: saved.update(facts=f, markdown=markdown))
    monkeypatch.setattr(corrections, "_append_history", lambda *a, **k: None)

    _correct("my_role", UNKNOWN, "제가 데이터 수집을 담당했습니다")
    result = _correct("lessons", UNKNOWN, "협업 시 초기 합의가 중요함을 배웠습니다")

    assert result["facts"]["lessons"] == "협업 시 초기 합의가 중요함을 배웠습니다"
    assert "협업 시 초기 합의가 중요함을 배웠습니다" in result["markdown"].split("## Lessons")[1], \
        "Lessons 정정이 실제 Lessons 섹션에 반영돼야 한다"
    my_role_section = result["markdown"].split("## My Role")[1].split("## Lessons")[0]
    assert "협업 시 초기 합의가 중요함을 배웠습니다" not in my_role_section, \
        "Lessons 정정이 My Role 섹션(의 감사 기록)에 잘못 끼어들면 안 된다"
    assert result["facts"]["my_role"] == "제가 데이터 수집을 담당했습니다", "먼저 한 my_role 정정이 유지돼야 한다"


# ── 업로드 직후 인터뷰: "이거 사실 본인이 주도했나요?" 확인 질문 ─────────────
#
# 사용자 피드백(2026-09-23, 후속): AI가 "업로드했으니 네 것"이라고 추측하는 건 여전히
# 안 하지만, 팀 활동으로 기록된 것 중 사용자가 실제로 주도한 부분이 있으면 콕 집어서
# 물어보고 확인받아서 [본인 진술]로 남기자.

def test_intake_questions_surface_team_owned_facts_for_ownership_check(fixture_store):
    from fastapi.testclient import TestClient

    from skive import server

    client = TestClient(server.app)
    res = client.get("/api/experiences/t/intake-questions")
    assert res.status_code == 200
    questions = res.json()["questions"]
    ownership_qs = [q for q in questions if "팀 활동으로 기록돼 있어요" in q["question"]]
    assert len(ownership_qs) == 1
    assert "F1-score가 0.71에서 0.86으로 향상되었다" in ownership_qs[0]["question"]
    assert ownership_qs[0]["target"] == "result"


def test_intake_ownership_confirmation_becomes_self_reported_fact(fixture_store):
    from fastapi.testclient import TestClient

    from skive import server

    client = TestClient(server.app)
    res = client.post("/api/experiences/t/intake", json={"answers": [
        {
            "target": "result",
            "question": "자료에는 팀 활동으로 기록돼 있어요: \"F1-score가 0.71에서 0.86으로 향상되었다\" — 본인이 주도했나요?",
            "answer": "네, 제가 임계값 튜닝 방식을 직접 제안하고 검증했습니다",
        },
    ]})
    assert res.status_code == 200, res.text
    facts = res.json()["facts"]
    new_fact = next(f for f in facts["results"] if "임계값 튜닝" in f["text"])
    assert facts_v2.provenance(new_fact) == facts_v2.USER_STATEMENT
    assert new_fact["owner"] == "본인"
    # 팀 기록으로 남아있던 원래 사실은 그대로 보존된다 — 지우거나 덮어쓰지 않는다
    assert any(f["text"] == "F1-score가 0.71에서 0.86으로 향상되었다." for f in facts["results"])


# ── 업로드: 원본 데이터 CSV가 분석 전체를 날려버리면 안 된다 ────────────────
#
# 실측(2026-09-23): 실사용자 폴더(캡스톤 프로젝트, 파일 365개)에 ML 파이프라인 중간
# 산출물 CSV가 76개 있었는데, 합쳐서 7.9백만 자였다(상한의 40배). 이런 CSV는 숫자
# 나열이라 LLM이 "무엇을 했는지" 읽는 데 거의 도움이 안 되면서 자리만 차지해서, 같은
# 폴더의 진짜 서술형 근거(md, 코드)를 밀어낸다. 게다가 처음엔 "20행만 넣자"로 고쳤는데,
# 센서 컬럼이 수백 개인 표는 20행만으로도 216,039자였다 — 행 수 제한만으론 부족했다.

def test_csv_loader_previews_many_rows_instead_of_dumping_all():
    from skive.loaders import _csv_chunks

    header = "a,b,c"
    rows = "\n".join(f"{i},{i*2},{i*3}" for i in range(10_000))  # 좁지만 아주 많은 행
    chunks = _csv_chunks("big.csv", f"{header}\n{rows}")

    assert len(chunks) == 1
    assert len(chunks[0].text) < 5_000, "행이 많다고 표 전체를 다 넣으면 안 된다"
    assert "10000" in chunks[0].location  # 전체 행 수는 어딘가에 남아야 한다(정보 손실 아님)


def test_csv_loader_caps_wide_rows_by_character_count_too():
    from skive.loaders import CSV_PREVIEW_CHARS, _csv_chunks

    # 실제로 재현된 경우: 행은 20개뿐인데 컬럼이 수백 개라 한 줄이 아주 길다
    wide_row = ",".join(f"sensor_{i}" for i in range(500))
    text = "\n".join([wide_row] * 21)  # 헤더 1 + 데이터 20행, 전부 같은 폭
    chunks = _csv_chunks("wide.csv", text)

    assert len(chunks) == 1
    assert len(chunks[0].text) < CSV_PREVIEW_CHARS + 200, \
        "행 개수 제한을 지켜도 열이 아주 많으면 여전히 거대할 수 있다 — 글자 수로도 잘라야 한다"


def test_real_capstone_folder_fits_under_analyzer_limit_after_csv_fix():
    """실제로 이 버그를 일으켰던 폴더가 남아있으면, 고친 게 실제로 통했는지 재확인한다.
    폴더가 없으면(다른 환경) 건너뛴다 — 이 테스트의 목적은 회귀 방지이지, 이 특정
    실사용자 데이터가 항상 있어야 한다는 게 아니다."""
    from skive.analyzer import MAX_CHARS
    from skive.loaders import load_folder

    root = store.DATA / "uploads" / "2. 화력발전소 이상탐지"
    if not root.is_dir():
        pytest.skip("이 실사용자 폴더가 없는 환경 — 스킵")
    chunks = load_folder(root)
    corpus = "\n\n".join(f"[C{i}] ({c.source}, {c.location})\n{c.text}" for i, c in enumerate(chunks, 1))
    assert len(corpus) < MAX_CHARS, f"CSV 미리보기 처리 후에도 여전히 상한을 넘음({len(corpus):,}자)"


# ── 업로드: analyze_folder가 던지는 ValueError가 500이 아니라 400으로 나가야 한다 ──
#
# 실측(2026-09-23): "폴더가 너무 큼" 같은 사용자가 이해할 수 있는 오류가 안 잡혀서
# FastAPI가 그냥 500(Internal Server Error)으로 감쌌다. 화면엔 원인이 하나도 안 보였다.

def test_analyze_folder_valueerror_becomes_clean_400(fixture_upload, monkeypatch):
    from fastapi.testclient import TestClient

    from skive import server

    def too_big(*a, **k):
        raise ValueError("폴더가 너무 큼(9,999,999자 > 320,000자). 분할 요약 단계는 아직 미구현")

    monkeypatch.setattr(server, "analyze_folder", too_big)

    exp_id = "test-too-big"
    root = store.DATA / "uploads" / exp_id
    try:
        client = TestClient(server.app)
        res = client.post(
            "/api/experiences/upload",
            data={"id": exp_id, "grade": "3"},
            files=[("files", ("note.txt", b"hello", "text/plain"))],
        )
        assert res.status_code == 400, "사용자가 이해할 수 있는 오류가 500으로 감춰지면 안 된다"
        assert "폴더가 너무 큼" in res.json()["detail"]
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ── 경험 설명(설정): 언제든 다시 열어서 고칠 수 있는 자유 메모 ────────────────
#
# 사용자 요청(2026-09-23): "지피티 프로젝트처럼 이 프로젝트에 대한 설명란을 설정으로
# 들어가면 적을 수 있게 해줘." 업로드 직후 인터뷰(한 번만 뜸)와 달리 언제든 다시 고칠 수
# 있어야 하고, writer가 이걸 근거 자료에 포함해야 한다.

def test_experience_description_can_be_set_and_updated(fixture_store):
    from fastapi.testclient import TestClient

    from skive import server

    client = TestClient(server.app)
    res = client.put("/api/experiences/t/description", json={"description": "4학년 종합설계 프로젝트"})
    assert res.status_code == 200, res.text
    assert res.json()["meta"]["description"] == "4학년 종합설계 프로젝트"

    res2 = client.put("/api/experiences/t/description", json={"description": "수정된 설명"})
    assert res2.json()["meta"]["description"] == "수정된 설명", "다시 열어서 고칠 수 있어야 한다"


def test_experience_description_flows_into_writer_bundle(fixture_store, monkeypatch):
    monkeypatch.setattr(store, "get_meta", lambda i: {**META, "description": "4학년 종합설계 프로젝트"})
    bundle = writer.build_bundle("t")
    assert "[프로젝트 설명 — 본인 작성]" in bundle
    assert "4학년 종합설계 프로젝트" in bundle


# ── 업로드: 제목·폴더 구조는 사용자가 올린 그대로다 — 드라이브는 정리해주는 곳이 아니다
#
# 실측(2026-09-23)과 그 직후 사용자 피드백을 합친 결론: 처음엔 "AI가 만든 제목이 사용자
# 폴더 이름과 달라서 헷갈린다"는 문제를, 번호를 벗기고 감싸는 폴더를 접는 "정리"로
# 풀려고 했다. 그런데 "홈은 그냥 드라이브다. 폴더 올리는 대로 그냥 올려야지, 왜
# 임의로 구조를 바꾸냐"는 피드백을 받고 되돌렸다 — 제목은 exp_id(사용자가 붙인 폴더
# 이름) 그대로, 번호("2. ")도 그대로, 폴더 구조도 있는 그대로 보여준다. AI가 원문
# 기준으로 뽑은 제목은 버리지 않고 `ai_title`로만 참고 남긴다.

def test_title_is_exactly_the_users_folder_name_numbers_included(fixture_upload, monkeypatch):
    from fastapi.testclient import TestClient

    from skive import server

    def fake_analyze_folder(root, me, exp_id, grade):
        meta = {
            "id": exp_id, "title": "Data Preprocessing and Anomaly Detection", "summary": "s",
            "kind": "project", "grade": grade, "period": "p", "skills": [], "raw_dir": str(root),
            "sources": [], "evidence_total": 0, "evidence_verified": 0, "my_role_verified": False,
            "open_questions": [],
        }
        facts = {
            "title": "Data Preprocessing and Anomaly Detection", "summary": "s", "period": "p",
            "my_role": "확인 필요", "my_role_verified": False,
            "actions": [], "decisions": [], "results": [], "skills": [], "lessons": "확인 필요",
        }
        md = "# Data Preprocessing and Anomaly Detection\n> s\n"
        return md, meta, facts

    monkeypatch.setattr(server, "analyze_folder", fake_analyze_folder)

    exp_id = "2. 화력발전소 이상탐지"
    root = store.DATA / "uploads" / exp_id
    try:
        client = TestClient(server.app)
        res = client.post(
            "/api/experiences/upload",
            data={"id": exp_id, "grade": "3"},
            files=[("files", ("note.txt", b"hello", "text/plain"))],
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["meta"]["title"] == exp_id, "번호까지 포함해서 사용자가 붙인 이름 그대로여야 한다"
        assert body["meta"]["ai_title"] == "Data Preprocessing and Anomaly Detection", "AI 제목도 참고용으로 남겨야 한다"
        assert body["facts"]["title"] == exp_id
        assert body["markdown"].startswith(f"# {exp_id}")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_folder_structure_is_never_collapsed_drive_is_literal(tmp_path):
    """감싸는 폴더가 하나뿐이어도(예: 본인 이름 폴더) 절대 접지 않는다 — 드라이브는
    사용자가 정리한 구조를 있는 그대로 보여주는 곳이다."""
    from skive.loaders import load_folder

    root = tmp_path / "업로드루트"
    wrapper = root / "사용자A"
    cat1 = wrapper / "1. 데이터 전처리"
    cat1.mkdir(parents=True)
    (cat1 / "report.md").write_text("# 보고서\n실제 내용", encoding="utf-8")

    chunks = load_folder(root)
    assert len(chunks) == 1
    assert chunks[0].source == "사용자A/1. 데이터 전처리/report.md", \
        "감싸는 폴더 이름이 그대로 경로에 남아야 한다 — 임의로 접으면 안 된다"


# ── 드라이브: 원본 파일을 그대로 다운로드할 수 있어야 한다 ──────────────────
#
# 사용자 요청(2026-09-23): "드라이브니깐 다운받기 같은 게 있어야지." 미리보기(`/sources/
# {source}`)는 AI 분석용으로 자른 텍스트를 주지만, 다운로드는 원본 바이트 그대로여야 한다.

def test_download_source_returns_the_actual_original_bytes(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from skive import server

    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    original_bytes = ("헤더1,헤더2\n" + "\n".join(f"{i},{i*2}" for i in range(1000))).encode("utf-8")
    (raw_dir / "big.csv").write_bytes(original_bytes)

    monkeypatch.setattr(store, "get_meta", lambda i: {
        "id": "t", "title": "T", "sources": ["big.csv"], "raw_dir": str(raw_dir),
    })

    client = TestClient(server.app)
    res = client.get("/api/experiences/t/download-source/big.csv")
    assert res.status_code == 200
    assert res.content == original_bytes, \
        "다운로드는 CSV 미리보기(20행)가 아니라 원본 전체 바이트여야 한다"


def test_download_rejects_path_outside_raw_dir(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from skive import server

    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / "ok.md").write_text("ok", encoding="utf-8")

    monkeypatch.setattr(store, "get_meta", lambda i: {
        "id": "t", "title": "T", "sources": ["../secret.txt"], "raw_dir": str(raw_dir),
    })

    client = TestClient(server.app)
    res = client.get("/api/experiences/t/download-source/../secret.txt")
    assert res.status_code == 404, "raw_dir 밖으로 나가는 경로는 거부해야 한다"


# ── KT 참고문서 수준: experience.md에 자소서 초안·부족한 부분이 있어야 한다 ──
#
# 사용자 피드백(2026-09-23): "내가 원하는거는 kt 같이 md 파일 정리하는거면서 우리가
# 하려고하는 포트폴리오나 자소서 만들때 필요한 것들을 명시하는거지." — STAR 요약만으로는
# 부족하고, (검토가 필요하다고 명시된) 자소서 표현 초안과 채워야 할 것 목록이 있어야 한다.

def test_experience_md_includes_resume_draft_and_gaps_sections(tmp_path, monkeypatch):
    from skive import analyzer
    from skive.models import Evidence, Experience

    (tmp_path / "report.md").write_text("본인은 모델을 구현했다. F1이 0.71에서 0.86으로 향상됨.", encoding="utf-8")

    exp = Experience(
        title="테스트 프로젝트", summary="s", kind="project", period="2026",
        organization="학교", problem="문제 상황", my_role="모델 구현",
        my_role_evidence=[Evidence(chunk_id="C1", quote="본인은 모델을 구현했다.")],
        actions=[], decisions_and_trials=[],
        results=[Fact(text="F1이 0.71에서 0.86으로 향상됨.", owner="팀",
                       evidence=[Evidence(chunk_id="C1", quote="F1이 0.71에서 0.86으로 향상됨.")])],
        skills=["Python"], lessons="확인 필요", open_questions=[],
        resume_draft="본인은 모델 구현을 맡아 F1을 0.71에서 0.86으로 향상시키는 데 기여했다.",
        gaps_to_fill=["정확한 참여 기간 불명", "최종 배포 여부 불명"],
    )

    class _Stub:
        def with_structured_output(self, _model):
            return self

        def invoke(self, _messages):
            return exp

    monkeypatch.setattr(analyzer, "get_llm", lambda: _Stub())

    markdown, meta, facts = analyzer.analyze_folder(tmp_path, "테스터", "테스트 프로젝트", 4)

    assert "## 자소서 표현 초안 (AI 해석 — 검토 필요)" in markdown
    assert exp.resume_draft in markdown
    assert "## 채워야 할 것 (있으면 더 강해짐)" in markdown
    assert "정확한 참여 기간 불명" in markdown
    assert facts["resume_draft"] == exp.resume_draft
    assert meta["gaps_to_fill"] == exp.gaps_to_fill
