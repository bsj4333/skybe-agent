"""사실(fact)의 출처·근거 상태를 해석하고 새 버전을 만드는 한 곳. SCHEMA.md §2 참고.

v1(`verified` 불리언 한 칸)과 v2(provenance_type/evidence_status/lifecycle/version)가
당분간 공존한다. `analyzer.py`는 아직 v1으로 쓰고(0-2에서 교체 예정), `corrections.py`는
v2로 쓴다. 읽는 쪽은 전부 이 모듈을 거치게 해서 양쪽을 구분하지 않아도 되게 한다.

왜 이 모듈이 생겼는지: 정정이 이전 사실의 `verified`와 원본 인용을 그대로 물려받아
사용자의 진술이 "문서로 검증된 사실"로 승격되고 자소서 근거까지 흘러들어갔다(F01).
"""

import uuid
from datetime import datetime

# provenance_type — 누가 말했나
DOCUMENT = "document"
USER_STATEMENT = "user_statement"
DERIVED = "derived"

# evidence_status — 근거가 주장을 뒷받침하나
UNLINKED = "unlinked"
QUOTE_MATCHED = "quote_matched"  # 인용문이 원문에 존재. 주장 지지까지는 아직 아님
SUPPORTED = "supported"
CONTRADICTED = "contradicted"
NEEDS_REVIEW = "needs_review"

# lifecycle — 지금도 유효한가
ACTIVE = "active"
SUPERSEDED = "superseded"
RETRACTED = "retracted"

BADGES = {DOCUMENT: "자료에서 확인", USER_STATEMENT: "본인 확인", DERIVED: "AI 해석"}


def provenance(fact: dict) -> str:
    return fact.get("provenance_type") or DOCUMENT


def lifecycle(fact: dict) -> str:
    return fact.get("lifecycle") or ACTIVE


def evidence_status(fact: dict) -> str:
    if fact.get("evidence_status"):
        return fact["evidence_status"]
    # v1 legacy: verified=True가 보장하는 것은 "인용문이 원문에 글자 그대로 있다"까지다.
    # 주장을 실제로 지지하는지는 검사한 적이 없으므로 supported로 올리지 않는다 (F03).
    return QUOTE_MATCHED if fact.get("verified") else UNLINKED


def is_document_backed(fact: dict) -> bool:
    """원본 자료가 뒷받침하는 사실인가. 자소서 '근거 자료' 항목에 넣을 기준."""
    return (
        provenance(fact) == DOCUMENT
        and evidence_status(fact) in (QUOTE_MATCHED, SUPPORTED)
        and lifecycle(fact) == ACTIVE
    )


def is_self_reported(fact: dict) -> bool:
    """사용자가 직접 말한 사실. 쓸 수 있지만 출처를 구분해서 표시해야 한다."""
    return provenance(fact) == USER_STATEMENT and lifecycle(fact) == ACTIVE


def badge(fact: dict) -> str:
    return BADGES.get(provenance(fact), "확인 필요")


def legacy_evidence(fact: dict) -> list[dict]:
    """v1의 `sources: ["보고서.md @ L1-31"]`를 v2 evidence 구조로 읽는다.
    v1엔 quote 원문이 없으므로 None으로 두고 재검증 대상으로 남긴다."""
    out = []
    for s in fact.get("sources") or []:
        source, _, location = str(s).partition(" @ ")
        out.append(
            {
                "source": source,
                "location": location,
                "quote": None,
                "quote_matched": bool(fact.get("verified")),
                "supports_claim": "unknown",
                "owner_match": "unknown",
            }
        )
    return out


def evidence_of(fact: dict) -> list[dict]:
    if "evidence" in fact:
        return fact["evidence"]
    return legacy_evidence(fact)


def display_tag(fact: dict) -> str:
    """experience.md 줄 끝과 프론트에 붙는 출처 표기. 렌더링 캐시이며 상태의 원본이 아니다."""
    kind = provenance(fact)
    if kind == USER_STATEMENT:
        return "[본인 진술, 원문 근거 없음]"
    if kind == DERIVED:
        return "[AI 해석]"
    if fact.get("tag"):  # v1 analyzer가 만들어 둔 표기를 그대로 유지
        return fact["tag"]
    ev = evidence_of(fact)
    if not ev:
        return "[근거 없음]"
    return " ".join(
        f"[근거: {e['source']} @ {e['location']}]" if e.get("location") else f"[근거: {e['source']}]"
        for e in ev
    )


def new_version(previous: dict, text: str, *, provenance_type: str, reason: str = "") -> tuple[dict, dict]:
    """(superseded가 된 이전 버전, 새 버전)을 돌려준다.

    SCHEMA.md §2.4 불변 규칙: 텍스트가 바뀌면 이전 evidence와 evidence_status를
    **물려받지 않는다.** 새 버전은 needs_review에서 시작하고, 이전 근거는
    prior_evidence로 감사용 보관만 한다.
    """
    now = datetime.now().isoformat()
    fact_id = previous.get("fact_id") or str(uuid.uuid4())
    version = int(previous.get("version", 1))

    old = {**previous, "fact_id": fact_id, "version": version,
           "lifecycle": SUPERSEDED, "superseded_at": now}

    new = {
        "fact_id": fact_id,
        "version": version + 1,
        "supersedes_version": version,
        "text": text,
        "owner": previous.get("owner", "팀"),
        "provenance_type": provenance_type,
        "evidence_status": NEEDS_REVIEW,
        "lifecycle": ACTIVE,
        "review_state": "accepted",
        "evidence": [],
        "prior_evidence": evidence_of(previous),
        "prior_text": previous.get("text"),
        "correction_reason": reason,
        "recorded_at": now,
        # 아래 두 개는 v1 필드를 읽는 기존 코드(profile.py, importance.py)를 위한 호환값이다.
        # 문서 검증이 사라졌으므로 False가 맞다.
        "verified": False,
        "sources": [],
    }
    new["tag"] = display_tag(new)
    return old, new


def document_fact(text: str, owner: str, evidence: list[dict], *, tag: str = "") -> dict:
    """원본 자료에서 추출한 사실. `evidence`는 analyzer가 검사까지 끝낸 기록이다.

    상태 판정 규칙 (SCHEMA.md §2.2):
    - 인용문이 원문에 하나도 없으면        → unlinked
    - 있지만 검사를 통과한 게 하나도 없으면 → needs_review (인용은 존재하나 주장을 못 받침)
    - 통과한 게 하나라도 있으면            → quote_matched
    `supported`로는 올리지 않는다. 문자 겹침은 함의(entailment)가 아니다.
    """
    if not any(e.get("quote_matched") for e in evidence):
        status = UNLINKED
    elif any(e.get("ok") for e in evidence):
        status = QUOTE_MATCHED
    else:
        status = NEEDS_REVIEW

    fact = {
        "fact_id": str(uuid.uuid4()),
        "version": 1,
        "text": text,
        "owner": owner,
        "provenance_type": DOCUMENT,
        "evidence_status": status,
        "lifecycle": ACTIVE,
        "review_state": "accepted",
        "evidence": evidence,
        "recorded_at": datetime.now().isoformat(),
        # v1 필드를 읽는 기존 코드(profile.py, importance.py, 프론트)를 위한 호환값
        "verified": status == QUOTE_MATCHED,
        "sources": [
            f"{e['source']} @ {e['location']}" for e in evidence if e.get("ok") and e.get("source")
        ],
    }
    fact["tag"] = tag or display_tag(fact)
    return fact


def user_statement_fact(text: str, owner: str = "본인", reason: str = "") -> dict:
    """대화에서 새로 알게 된 사실. 처음부터 원문 근거가 없다."""
    now = datetime.now().isoformat()
    fact = {
        "fact_id": str(uuid.uuid4()),
        "version": 1,
        "text": text,
        "owner": owner,
        "provenance_type": USER_STATEMENT,
        "evidence_status": UNLINKED,
        "lifecycle": ACTIVE,
        "review_state": "accepted",
        "evidence": [],
        "correction_reason": reason,
        "recorded_at": now,
        "verified": False,
        "sources": [],
    }
    fact["tag"] = display_tag(fact)
    return fact
