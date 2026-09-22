import re

_STRIP = re.compile(r"[\s|*#>`\-]+")
_LIST_MARKER = re.compile(r"(?m)^\s*(?:#+\s*)?\d+[.)]\s")
_ASCII_TERM = re.compile(r"[A-Za-z][A-Za-z0-9+#.]*")
_NUMBER = re.compile(r"(?<![A-Za-z\d])\d+(?:[.,]\d+)*")
_HANGUL = re.compile(r"[가-힣]+")
_SELF_SUBJECT = re.compile(r"내가|나는|제가|저는|본인이|본인은|본인 ")
_TEAM_SUBJECT = re.compile(r"팀은|팀이|팀에서|팀원|우리 ?팀|우리는|우리가")

# 주장 단위 중 인용문에도 있어야 하는 최소 비율. 낮게 잡은 이유: 이 검사는 "지지한다"를
# 증명하려는 게 아니라 명백히 무관한 인용을 걸러내려는 것이다. 통과해도 quote_matched까지고
# supported로는 올리지 않는다 (SCHEMA.md §2.6).
SUPPORT_MIN_OVERLAP = 0.3


def norm(text: str) -> str:
    return _STRIP.sub("", text)


def quote_in_source(quote: str, source_norm: str) -> bool:
    q = norm(quote)
    return len(q) >= 4 and q in source_norm


def units(text: str) -> set[str]:
    """비교 단위. 영문 용어·숫자는 그대로, 한글은 문자 바이그램으로 쪼갠다.

    형태소 분석기 없이 조사·어미 변화("향상되었다" vs "향상했다")를 흡수하려는 것이다.
    """
    found = {t.lower().rstrip(".") for t in _ASCII_TERM.findall(text) if len(t) >= 2}
    found |= set(_NUMBER.findall(text))
    for run in _HANGUL.findall(text):
        if len(run) < 2:
            found.add(run)
        else:
            found.update(run[i : i + 2] for i in range(len(run) - 1))
    return found


def supports_claim(claim: str, quote: str) -> bool:
    """인용문이 주장과 최소한의 내용을 공유하는가. 인용문 존재 검사와는 별개다 (F03)."""
    claim_units = units(claim)
    if not claim_units:
        return False
    return len(claim_units & units(quote)) / len(claim_units) >= SUPPORT_MIN_OVERLAP


def owner_conflict(claim: str, quote: str) -> bool:
    """주장은 본인이 했다는데 인용문의 주어는 팀뿐인 경우에만 True. 보수적으로 판정한다."""
    return bool(
        _SELF_SUBJECT.search(claim)
        and _TEAM_SUBJECT.search(quote)
        and not _SELF_SUBJECT.search(quote)
    )


def numbers_missing_from(claim: str, quote: str) -> list[str]:
    """주장에는 있는데 인용문에는 없는 수치. 있으면 그 인용문은 주장을 다 못 받친다."""
    return sorted(numbers(claim) - numbers(quote))


def numbers(text: str, ignore: list[str] | None = None) -> set[str]:
    for token in ignore or []:
        text = text.replace(token, " ")
    text = _LIST_MARKER.sub("", text)
    text = re.sub(r"\b\d+[dD]\b", " ", text)
    found: set[str] = set()
    for token in _NUMBER.findall(text):
        token = token.replace(",", "")
        found.add(token)
        for part in token.split("."):
            found.add(part)
            found.add(part.lstrip("0") or "0")
    return found


def job_ascii_terms(items: list[str]) -> set[str]:
    return {t.lower().rstrip(".") for item in items for t in _ASCII_TERM.findall(item) if len(t) >= 2}


def terms_only_in_job(draft: str, job_terms: set[str], experiences: str) -> list[str]:
    draft_l, exp_l = draft.lower(), experiences.lower()
    return sorted(t for t in job_terms if t in draft_l and t not in exp_l)


def unsupported_numbers(answer: str, sources: str, ignore: list[str] | None = None) -> list[str]:
    return sorted(numbers(answer, ignore) - numbers(sources))
