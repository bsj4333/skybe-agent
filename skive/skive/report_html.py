from html import escape as h

from skive import store
from skive.user import load_user

STATUS_CLASS = {"통과": "ok", "정제": "warn", "경고": "bad", "근거부족": "muted", "해당없음": "muted"}
STATUS_HINT = {
    "통과": "판정자가 모든 문장을 근거로 확인",
    "정제": "근거 없는 문장을 자동 제거함",
    "경고": "미해결 검증 문제가 남음",
    "근거부족": "문항이 요구하는 내용이 근거 자료에 없어 작성하지 않음",
    "해당없음": "연결 가능한 경험이 없어 작성하지 않음",
}
STRENGTH_CLASS = {"강함": "ok", "보통": "warn", "약함": "bad", "없음": "muted"}

CSS = """
:root{--bg:#f6f7f9;--card:#fff;--text:#1c2430;--sub:#5c6675;--line:#e3e7ed;--accent:#2457d6;
--ok:#1f8a4c;--okbg:#e6f5ec;--warn:#a86400;--warnbg:#fff2dc;--bad:#c22f2f;--badbg:#fde8e8;--mutedbg:#eceff3}
@media (prefers-color-scheme:dark){:root{--bg:#12151a;--card:#1b2028;--text:#e8ecf2;--sub:#98a3b3;--line:#2b323d;
--accent:#7ea2ff;--ok:#5fd08d;--okbg:#173425;--warn:#f0b35a;--warnbg:#3a2c12;--bad:#ff8a8a;--badbg:#3d1c1c;--mutedbg:#262c36}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.65 -apple-system,"Malgun Gothic",sans-serif}
main{max-width:1040px;margin:0 auto;padding:28px 16px 64px}
h1{font-size:26px;margin:0 0 4px}h2{font-size:19px;margin:40px 0 12px}h3{font-size:16px;margin:0 0 6px}
.sub{color:var(--sub);font-size:13px}.grid{display:grid;gap:12px;grid-template-columns:repeat(auto-fill,minmax(300px,1fr))}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.badge{display:inline-block;padding:1px 9px;border-radius:999px;font-size:12px;font-weight:600;margin-right:4px;background:var(--mutedbg);color:var(--sub)}
.badge.ok{background:var(--okbg);color:var(--ok)}.badge.warn{background:var(--warnbg);color:var(--warn)}
.badge.bad{background:var(--badbg);color:var(--bad)}.badge.accent{background:var(--accent);color:#fff}
.year{margin:18px 0 8px;font-weight:700;color:var(--accent)}
.chip{display:inline-block;margin:2px 4px 2px 0;padding:0 8px;border-radius:6px;background:var(--mutedbg);color:var(--text);font-size:12.5px;text-decoration:none}
.chip:hover{outline:1px solid var(--accent)}
.bar{height:6px;border-radius:3px;background:var(--mutedbg);overflow:hidden;margin:6px 0}.bar>i{display:block;height:100%;background:var(--accent)}
.answer p{margin:0 0 10px;white-space:pre-wrap}.q{font-weight:700}
details{margin-top:8px;font-size:13px;color:var(--sub)}summary{cursor:pointer}
.removed{color:var(--bad);text-decoration:line-through;margin:2px 0}
table{width:100%;border-collapse:collapse;font-size:14px}td,th{padding:8px 6px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
ul{margin:6px 0;padding-left:20px}
"""


def _chips(ids: list[str]) -> str:
    return "".join(f'<a class="chip" href="#exp-{h(i)}">{h(i)}</a>' for i in ids)


def _experience_cards(metas: list[dict]) -> str:
    out, year = [], None
    for m in metas:
        if m["grade"] != year:
            year = m["grade"]
            out.append(f'</div><div class="year">{year}학년</div><div class="grid">')
        imp = m["importance"]
        ratio = round(100 * imp["score"] / imp["max"])
        role = '<span class="badge ok">역할 검증</span>' if m["my_role_verified"] else '<span class="badge bad">역할 미확인</span>'
        ev = f'{m["evidence_verified"]}/{m["evidence_total"]}'
        tier_cls = "accent" if imp["tier"] == "핵심" else ""
        out.append(
            f'<div class="card" id="exp-{h(m["id"])}"><h3>{h(m["title"])}</h3>'
            f'<div class="sub">{h(m["kind"])} · {h(m["period"])}</div>'
            f'<div style="margin-top:6px"><span class="badge {tier_cls}">{h(imp["tier"])}</span>{role}'
            f'<span class="badge ok">근거 {ev}</span></div>'
            f'<div class="bar" title="중요도 {imp["score"]}/{imp["max"]}"><i style="width:{ratio}%"></i></div>'
            f'<div class="sub">중요도 {imp["score"]}/{imp["max"]} — {h(imp["reason"])}</div>'
            f'<div class="sub" style="margin-top:6px">{h(", ".join(m["skills"]))}</div></div>'
        )
    return "".join(out).replace("</div>", "", 1) + "</div>"


def _profile(profile: dict | None) -> str:
    if not profile:
        return '<p class="sub">프로필이 아직 생성되지 않았습니다.</p>'
    comps = "".join(
        f'<div class="card"><h3>{h(c["name"])}</h3><div>{h(c["description"])}</div><div style="margin-top:6px">{_chips(c["experience_ids"])}</div></div>'
        for c in profile["competencies"]
    )
    traits = "".join(
        f'<div class="card"><h3>{h(t["trait"])}</h3><div>{h(t["rationale"])}</div><div style="margin-top:6px">{_chips(t["experience_ids"])}</div></div>'
        for t in profile["traits"]
    )
    gaps = "".join(f"<li>{h(g)}</li>" for g in profile["gaps"])
    return (
        f'<p><b>{h(profile["headline"])}</b></p><h3>역량</h3><div class="grid">{comps}</div>'
        f'<h3 style="margin-top:16px">반복 관찰되는 성향 <span class="sub">(2개 이상 경험에서 확인된 것만)</span></h3><div class="grid">{traits}</div>'
        f'<h3 style="margin-top:16px">보강이 필요한 부분</h3><ul>{gaps}</ul>'
    )


def _links(plan: dict) -> str:
    rows = "".join(
        f'<tr><td><b>{h(c["competency"])}</b></td><td><span class="badge {STRENGTH_CLASS[c["strength"]]}">{h(c["strength"])}</span></td>'
        f'<td>{_chips(c["experience_ids"])}</td><td>{h(c["note"])}</td></tr>'
        for c in plan["competency_links"]
    )
    return f"<table><tr><th>직무 핵심 역량</th><th>근거 강도</th><th>연결 경험</th><th>이유</th></tr>{rows}</table>"


def _answers(answers: list[dict]) -> str:
    cards = []
    for a in answers:
        cls = STATUS_CLASS[a["status"]]
        body = "".join(f"<p>{h(p)}</p>" for p in a["draft"].split("\n\n") if p.strip()) or '<p class="sub">(작성하지 않음)</p>'
        gap = f'<div class="sub">부족한 점: {h(a["gap"])}</div>' if a["gap"] else ""
        removed = ""
        if a["removed"]:
            items = "".join(f'<div class="removed">{h(s)}</div>' for s in a["removed"])
            removed = f"<details><summary>자동 제거된 문장 {len(a['removed'])}개 (판정자가 근거 없음으로 판정)</summary>{items}</details>"
        cards.append(
            f'<div class="card answer" style="margin-bottom:12px"><div class="q">{h(a["question"])}</div>'
            f'<div style="margin:6px 0"><span class="badge {cls}">{h(a["status"])}</span>'
            f'<span class="sub">{h(STATUS_HINT[a["status"]])} · 재작성 {a["attempts"]}회</span></div>'
            f'<div style="margin-bottom:6px">{_chips(a["experience_ids"])}</div>{body}{gap}{removed}</div>'
        )
    return "".join(cards)


def _study() -> str:
    from skive.study import STUDY_DIR, list_study

    cards = []
    for m in list_study():
        summary = (STUDY_DIR / m["id"] / "summary.md").read_text(encoding="utf-8")
        review = '<span class="badge warn">복습 필요</span>' if m["needs_review"] else '<span class="badge ok">이해 완료</span>'
        body = "".join(f"<div>{h(line)}</div>" for line in summary.splitlines()[3:] if line.strip())
        cards.append(
            f'<div class="card"><h3>{h(m["topic"])}</h3><div class="sub">{h(m["date"])} · {h(", ".join(m["keywords"]))}</div>'
            f'<div style="margin:6px 0">{review}{_chips(m["related_experience_ids"])}</div>'
            f'<details><summary>기록 보기</summary>{body}</details></div>'
        )
    return f'<div class="grid">{"".join(cards)}</div>' if cards else '<p class="sub">아직 공부 기록이 없습니다.</p>'


def build_report(result: dict) -> str:
    user, job = load_user(), result["job"]
    metas = store.list_meta()
    experiences = _experience_cards(metas)
    questions = "".join(f"<li>{h(q)}</li>" for q in result["questions_for_user"])
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>SKIVE 시연 리포트</title><style>{CSS}</style></head><body><main>
<h1>SKIVE 시연 리포트</h1>
<div class="sub">{h(user["name"])} · 진로 목표: {h(user["career_goal"])}</div>

<h2>1. 경험 지도 <span class="sub">— 폴더 {len(metas)}개를 분석해 구조화한 결과</span></h2>
<div class="grid" style="display:block"><div>{experiences}</div></div>

<h2>2. 나는 어떤 사람인가 <span class="sub">— 경험들을 종합한 프로필</span></h2>
{_profile(store.get_profile_json())}

<h2>3. 공고 분석 <span class="sub">— {h(job["company"])} / {h(job["role"])}</span></h2>
<div class="card"><div><b>핵심 역량</b> {h(", ".join(job["key_competencies"]))}</div>
<div style="margin-top:6px"><b>인재상</b> {h(", ".join(job["values"]) or "명시 없음")}</div></div>

<h2>4. 직무 역량 ↔ 내 경험</h2>
{_links(result["plan"])}

<h2>5. 자기소개서 문항별 결과</h2>
{_answers(result["answers"])}

<h2>6. 사용자 확인이 필요한 항목</h2>
<div class="card"><ul>{questions or "<li>없음</li>"}</ul></div>

<h2>7. 공부 기록 <span class="sub">— 챗봇 대화가 끝날 때 자동으로 요약·저장</span></h2>
{_study()}
</main></body></html>"""
