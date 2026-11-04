"""요청 문맥과 스코프 강제 — 하네스가 권한을 갖는 곳.

SKIVE_NEXT_PLAN_DeepAgents_반영본.md §2.1/P0-2 적용. 지금까지 스코프는 프롬프트("이
폴더 자료만 써라")로만 걸려 있었고, `chat.py`가 가져다 쓰는 읽기 도구 5개
(`get_profile`/`list_experiences`/`get_experience`/`get_evidence`/`search_study`/`get_study`)는
LLM이 다른 experience_id를 인수로 넘기면 그대로 조회됐다 (F02, SKIVE_NEXT_PLAN.md).

이 모듈이 하는 일은 하나다: **도구 실행 직전에, 프롬프트가 아니라 코드로 스코프를 검사한다.**
아직 인증이 없으므로 `user_id`는 서버가 발급하는 고정값이지만, 요청 본문의 값을 신뢰하지
않는다는 원칙(P0-2 규칙 1)은 지금부터 지킨다 — Stage 2에서 Auth가 들어올 때 이 자리에
꽂기만 하면 된다.
"""

import uuid
from dataclasses import dataclass, field

# Stage 2(Auth) 전까지 모든 요청은 이 고정 사용자다. 클라이언트가 무엇을 보내든 무시한다 —
# 요청 본문이 주장한 사용자 ID를 신뢰해 문맥을 만들지 않는다는 원칙은 인증 유무와 무관하다.
DEV_USER_ID = "local-dev-user"


class ScopeError(Exception):
    """도구가 현재 대화 범위 밖 데이터를 요청했을 때. 도구 함수 안에서 잡아 사용자에게
    보여줄 안전한 메시지로 바꾼다 — 원본 예외를 그대로 노출하지 않는다(P0-6 원칙)."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class RequestContext:
    """한 번의 도구 실행 동안 바뀌지 않는 사용자·세션·권한 경계.

    도구 함수는 이 값을 인수로 받되, 인수 이름에 `user_id`/`scope_id`를 그대로 받지
    않는다 — 그러면 LLM이 프롬프트 인젝션으로 값을 바꿔치기할 여지가 생긴다. 대신
    서버(또는 CLI)가 만든 RequestContext 하나를 클로저로 캡처해 쓴다.
    """

    user_id: str
    session_id: str
    active_scope_id: str | None = None


def new_context(session_id: str | None = None, active_scope_id: str | None = None) -> RequestContext:
    """서버/CLI가 요청 진입점에서 딱 한 번 호출한다. 이후 도구 함수들은 이 값만 신뢰한다."""
    return RequestContext(
        user_id=DEV_USER_ID,
        session_id=session_id or f"ctx-{uuid.uuid4().hex[:12]}",
        active_scope_id=active_scope_id,
    )


def guard_experience_id(ctx: RequestContext, experience_id: str) -> str:
    """experience_id 인수를 받는 모든 읽기·쓰기 도구가 거쳐야 하는 검사.

    - 대화 범위가 없으면(전체 매칭 에이전트 등) 그대로 통과시킨다.
    - 범위가 있는데 인수가 비어 있으면 범위의 경험으로 채운다(기존 챗봇 UX 유지).
    - 범위가 있는데 인수가 다른 경험이면 데이터 존재 여부를 알려주지 않고 거부한다
      (P0-2 규칙 5 — 있는지 없는지도 노출하지 않음).
    """
    if ctx.active_scope_id is None:
        return experience_id
    resolved = experience_id or ctx.active_scope_id
    if resolved != ctx.active_scope_id:
        raise ScopeError(
            "out_of_scope",
            f"현재 대화는 '{ctx.active_scope_id}' 범위로 좁혀져 있어 다른 경험을 조회·수정할 수 없습니다.",
        )
    return resolved
