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


_NUM_UNIT = re.compile(
    r"(\d+(?:[.,]\d+)*)\s*(%|퍼센트|점|개|명|건|회|배|시간|분|초|위|ms|kg|km|g|℃)?"
)
# 마침표는 소수점("0.88")이 아닐 때만 절 경계로 본다 — 안 그러면 숫자 중간에서 문맥이
# 잘려서 정작 필요한 지표 이름("정확도가")이 이전 절로 밀려나 버린다.
_CLAUSE_BOUNDARY = re.compile(r"(?<!\d)\.(?!\d)|[!?,\n]")
_CONTEXT_RADIUS = 80  # 이 안에서 절 경계(마침표·쉼표·줄바꿈)를 찾는다


def _mask_noise(text: str) -> str:
    text = _LIST_MARKER.sub("", text)
    return re.sub(r"\b\d+[dD]\b", " ", text)  # "3D 프린터"의 "3D"는 숫자가 아니다


def _clause_before(text: str, pos: int) -> str:
    """숫자가 속한 절의 시작까지 거슬러 올라간다(마침표·쉼표·줄바꿈 기준).

    처음엔 "숫자 바로 앞 단어 하나"를 지표 이름으로 잡으려 했는데, 실데이터
    ("F1-score가 기준 모델(단순 임계값) 0.71에서 제안 모델 0.86으로")처럼 지표와 숫자
    사이에 괄호·수식어가 끼면 엉뚱한 단어("모델")를 잡거나 아예 못 잡았다(빈 문자열).
    그러면 진짜 같은 지표를 다르게 표현한 정상적인 문장까지 '지지 안 됨'으로 걸렸다.
    절 전체를 보고 겹치는 정도를 재면 중간에 낀 수식어에 덜 흔들린다.
    """
    window_start = max(0, pos - _CONTEXT_RADIUS)
    boundary = window_start
    for m in _CLAUSE_BOUNDARY.finditer(text, window_start, pos):
        boundary = m.end()
    return text[boundary:pos]


def number_mentions(text: str) -> list[dict]:
    """텍스트에서 숫자 언급을 (원문 문자열, 값, 단위, 숫자가 속한 절)으로 뽑는다.

    예전에는 숫자를 문자열 집합으로만 비교해서 `0.71`을 `{"0.71","0","71"}`로 쪼개
    넣었다. 그 결과 근거 `F1-score가 0.71`에 대해 답변 `정확도 71%`가 숫자 존재만으로
    통과했다(F05). 이제는 값이 같아도 **속한 절이 다른 지표를 말하고 있으면** 다른
    수치로 본다 — 단, 이 검사는 아래 `_mention_supported`에서 값이 스케일만 다르게
    (소수↔퍼센트) 같을 때만 적용한다. 완전히 같은 값은 절 내용과 무관하게 지지된다.
    """
    text = _mask_noise(text)
    out = []
    for m in _NUM_UNIT.finditer(text):
        raw = m.group(1).replace(",", "")
        try:
            value = float(raw)
        except ValueError:
            continue
        unit = "percent" if m.group(2) in ("%", "퍼센트") else (m.group(2) or "")
        out.append({"raw": raw, "value": value, "unit": unit, "ctx": _clause_before(text, m.start())})
    return out


def _same_scale(a: float, b: float) -> bool:
    return abs(a - b) < 1e-9


def _cross_scale(a: float, b: float) -> bool:
    """"0.71"과 "71%"처럼 같은 비율을 소수/퍼센트로 다르게 적은 경우만 같다고 본다.
    그 밖에 숫자가 우연히 100배 차이 나는 경우까지 같다고 보면 오탐이 늘어난다."""
    for x, y in ((a, b), (b, a)):
        if 0 < x <= 1 and abs(x * 100 - y) < 1e-6:
            return True
    return False


def _context_overlap(a: str, b: str) -> float:
    au, bu = units(a), units(b)
    if not au or not bu:
        return 0.0
    return len(au & bu) / min(len(au), len(bu))


def _mention_supported(claim: dict, sources: list[dict]) -> bool:
    for s in sources:
        if _same_scale(claim["value"], s["value"]):
            # 완전히 같은 값. 단위가 둘 다 있는데 다르면(예: "42명" vs "42ms") 다른 수치다.
            if claim["unit"] and s["unit"] and claim["unit"] != s["unit"]:
                continue
            return True
        if _cross_scale(claim["value"], s["value"]):
            # 값이 우연히 스케일만 같다 — 진짜 같은 지표를 말하는지 절 내용으로 확인한다.
            if _context_overlap(claim["ctx"], s["ctx"]) >= SUPPORT_MIN_OVERLAP:
                return True
    return False


def job_ascii_terms(items: list[str]) -> set[str]:
    return {t.lower().rstrip(".") for item in items for t in _ASCII_TERM.findall(item) if len(t) >= 2}


def terms_only_in_job(draft: str, job_terms: set[str], experiences: str) -> list[str]:
    draft_l, exp_l = draft.lower(), experiences.lower()
    return sorted(t for t in job_terms if t in draft_l and t not in exp_l)


def numbers_missing_from(claim: str, quote: str) -> list[str]:
    """주장에는 있는데 인용문에는 (같은 지표·값으로) 없는 수치. 있으면 그 인용문은
    주장을 다 못 받친다."""
    quote_mentions = number_mentions(quote)
    return sorted({c["raw"] for c in number_mentions(claim) if not _mention_supported(c, quote_mentions)})


def unsupported_numbers(answer: str, sources: str, ignore: list[str] | None = None) -> list[str]:
    text = answer
    for token in ignore or []:
        text = text.replace(token, " ")
    source_mentions = number_mentions(sources)
    return sorted({c["raw"] for c in number_mentions(text) if not _mention_supported(c, source_mentions)})
