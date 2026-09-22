"""사용자가 채팅 중 저장된 경험 기록을 정정하는 흐름.

버그(PROJECT_STATUS.md #3): 사용자가 "FastAPI는 내가 안 만들었어"처럼 정정해도
recall()이 디스크의 원본 저장값을 다시 읽어와 정정 전 사실을 그대로 재출력함.
recall()은 항상 experience.md/facts.json을 디스크에서 새로 읽으므로(캐시 없음),
정정을 파일에 즉시 반영하기만 하면 같은 세션의 바로 다음 턴부터도 고쳐진 값이 나온다.

흐름: detect_correction()으로 정정 여부·대상을 찾고 → 사용자 확인을 받은 뒤 →
apply_correction()으로 facts.json/experience.md를 고치고 이력을 남긴다.
확인 없이 자동으로 적용하지 않는다 (증거 없는 자기 진술로 검증된 기록을 덮어쓰는 것이므로).
"""

import difflib
import json
from datetime import datetime

from langchain_core.messages import HumanMessage, SystemMessage

from skive import facts as facts_v2
from skive import store
from skive.llm import get_llm
from skive.models import UNKNOWN, CorrectionProposal
from skive.recall import format_recall, recall

FIELD_LISTS = {"action": "actions", "decision": "decisions", "result": "results"}
SECTION_HEADERS = {
    "action": "## Action",
    "decision": "## Technical Decisions / Trial & Error",
    "result": "## Results",
}
MATCH_THRESHOLD = 0.5

DETECT_SYSTEM = """너는 사용자의 채팅 메시지가 저장된 경험 기록에 반영할 정보를 담고 있는지 판단하는 분류기다.
[관련 기록]은 이 메시지로 자동 조회된, 현재 저장되어 있는 기록의 일부다.
규칙:
1. 사용자가 [관련 기록]의 특정 사실(누가 했는지, 무엇을 했는지, 결과가 무엇인지)이 틀렸다거나 다르다고 말하면
   is_correction=true, kind=correction.
2. 사용자가 [관련 기록]에는 없던 새로운 사실(몰랐던 역할, 추가 성과, 못 다룬 시행착오 등)을 말하면
   is_correction=true, kind=new_fact.
3. 단순 질문, 잡담, 위 둘 다 아닌 대화는 is_correction=false.
4. kind=correction일 때만 original_text를 [관련 기록]에 있는 문장 그대로 복사한다. 지어내지 않는다.
   어떤 문장을 가리키는지 특정할 수 없으면 is_correction=false로 한다.
5. kind=new_fact면 original_text는 빈 문자열로 둔다.
6. experience_id는 [관련 기록]의 id를 그대로 쓴다. id가 'a/b.md' 형태(원본 자료)면 '/' 앞부분만 쓴다.
7. corrected_text는 사용자가 말한 내용을 한 문장으로 정리한다."""


def _similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def _resolve_target(proposal: CorrectionProposal) -> CorrectionProposal | None:
    """LLM이 고른 experience_id가 실제 존재하는지, correction이면 original_text가 실제 facts.json
    항목과 맞는지 확인한다. correction은 가장 가까운 항목의 정확한 원문으로 바꿔치기한다.
    매칭되는 게 없으면 None(적용 안 함으로 취급)."""
    facts = store.get_facts(proposal.experience_id)
    if facts is None:
        return None
    if proposal.kind == "new_fact":
        field = proposal.field if proposal.field in FIELD_LISTS else "action"
        return proposal.model_copy(update={"field": field, "original_text": ""})

    candidates: list[tuple[str, str]] = [("my_role", facts.get("my_role", ""))]
    for field, key in FIELD_LISTS.items():
        for item in facts.get(key, []):
            candidates.append((field, item["text"]))
    if not candidates:
        return None
    best_field, best_text = max(candidates, key=lambda c: _similarity(c[1], proposal.original_text))
    if _similarity(best_text, proposal.original_text) < MATCH_THRESHOLD:
        return None
    return proposal.model_copy(update={"field": best_field, "original_text": best_text})


def detect_correction(user_message: str, scope_id: str | None = None) -> CorrectionProposal | None:
    """사용자 메시지가 정정/새 사실 후보면 확인이 필요한 CorrectionProposal을, 아니면 None을 반환한다."""
    hits = recall(user_message, k=5, scope_id=scope_id)
    if not hits:
        return None
    prompt = f"[관련 기록]\n{format_recall(hits)}\n\n[사용자 메시지]\n{user_message}"
    proposal = get_llm().with_structured_output(CorrectionProposal).invoke(
        [SystemMessage(DETECT_SYSTEM), HumanMessage(prompt)]
    )
    if not proposal.is_correction or not proposal.experience_id:
        return None
    if proposal.kind == "correction" and not proposal.original_text:
        return None
    return _resolve_target(proposal)


def _history_path(exp_id: str):
    return store.STORE / exp_id / "corrections.json"


def get_corrections(exp_id: str) -> list[dict]:
    path = _history_path(exp_id)
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []


def _append_history(exp_id: str, entry: dict) -> None:
    path = _history_path(exp_id)
    history = get_corrections(exp_id)
    history.append(entry)
    path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


def _append_to_section(markdown: str, header: str, line: str) -> str:
    """experience.md의 '## Action' 같은 섹션 끝에 새 줄을 추가한다. 섹션이 없으면 새로 만든다."""
    idx = markdown.find(header)
    if idx == -1:
        return markdown.rstrip("\n") + f"\n\n{header}\n{line}\n"
    next_header = markdown.find("\n## ", idx + len(header))
    insert_at = next_header if next_header != -1 else len(markdown)
    section = markdown[:insert_at].rstrip("\n")
    if section.endswith(f"\n- {UNKNOWN}"):
        section = section[: -len(f"\n- {UNKNOWN}")]
    return section + f"\n{line}\n" + markdown[insert_at:]


def apply_correction(proposal: CorrectionProposal) -> dict:
    """사용자가 확인한 정정/새 사실을 facts.json과 experience.md에 반영하고 이력을 남긴다."""
    meta = store.get_meta(proposal.experience_id)
    facts = store.get_facts(proposal.experience_id)
    markdown = store.get_markdown(proposal.experience_id)
    if meta is None or facts is None or markdown is None:
        raise ValueError(f"존재하지 않는 경험 id: {proposal.experience_id}")

    now = datetime.now().isoformat()

    if proposal.kind == "new_fact":
        key = FIELD_LISTS.get(proposal.field, "actions")
        new_item = facts_v2.user_statement_fact(proposal.corrected_text, reason=proposal.reason)
        facts.setdefault(key, []).append(new_item)
        new_line = f"- (본인) {proposal.corrected_text} {new_item['tag']}"
        markdown = _append_to_section(markdown, SECTION_HEADERS[proposal.field], new_line)

    elif proposal.field == "my_role":
        old_text = facts["my_role"]
        if old_text not in markdown:
            raise ValueError("원본 문구를 experience.md에서 찾지 못해 정정을 반영할 수 없음")
        # 사용자가 역할을 고쳤다는 것은 원문이 뒷받침하던 역할이 더는 유효하지 않다는 뜻이다.
        # 문서 검증 상태를 물려주지 않는다 (SCHEMA.md §2.4).
        facts["my_role"] = proposal.corrected_text
        facts["my_role_verified"] = False
        facts["my_role_provenance"] = facts_v2.USER_STATEMENT
        facts["my_role_evidence_status"] = facts_v2.NEEDS_REVIEW
        facts["my_role_corrected_from"] = old_text
        markdown = markdown.replace(
            old_text, f"{proposal.corrected_text} [본인 진술, 원문 근거 없음] (기존: {old_text})", 1
        )

    else:
        key = FIELD_LISTS.get(proposal.field)
        items = facts.get(key, []) if key else []
        index = next((i for i, it in enumerate(items) if it["text"] == proposal.original_text), None)
        if index is None:
            raise ValueError("정정 대상 사실을 facts.json에서 찾지 못함")
        item = items[index]
        old_line = f"- ({item['owner']}) {item['text']} {facts_v2.display_tag(item)}"
        if old_line not in markdown:
            raise ValueError("원본 문구를 experience.md에서 찾지 못해 정정을 반영할 수 없음")

        superseded, new_item = facts_v2.new_version(
            item, proposal.corrected_text,
            provenance_type=facts_v2.USER_STATEMENT, reason=proposal.reason,
        )
        items[index] = new_item
        facts.setdefault("superseded", []).append(superseded)

        new_line = f"- ({new_item['owner']}) {new_item['text']} {new_item['tag']} (기존: {item['text']})"
        markdown = markdown.replace(old_line, new_line, 1)

    store.save(proposal.experience_id, markdown, meta, facts)
    _append_history(
        proposal.experience_id,
        {
            "kind": proposal.kind,
            "field": proposal.field,
            "original_text": proposal.original_text,
            "corrected_text": proposal.corrected_text,
            "reason": proposal.reason,
            "provenance_type": facts_v2.USER_STATEMENT,
            "evidence_status": facts_v2.NEEDS_REVIEW,
            "applied_at": now,
        },
    )
    return {"meta": meta, "facts": facts, "markdown": markdown}
