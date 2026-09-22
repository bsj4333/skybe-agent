import re

_STRIP = re.compile(r"[\s|*#>`\-]+")
_LIST_MARKER = re.compile(r"(?m)^\s*(?:#+\s*)?\d+[.)]\s")
_ASCII_TERM = re.compile(r"[A-Za-z][A-Za-z0-9+#.]*")
_NUMBER = re.compile(r"(?<![A-Za-z\d])\d+(?:[.,]\d+)*")


def norm(text: str) -> str:
    return _STRIP.sub("", text)


def quote_in_source(quote: str, source_norm: str) -> bool:
    q = norm(quote)
    return len(q) >= 4 and q in source_norm


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
