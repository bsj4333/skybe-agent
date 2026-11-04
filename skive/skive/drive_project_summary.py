"""Agent-built, evidence-bounded summary for one project folder subtree."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from collections import Counter, defaultdict
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from psycopg.rows import dict_row
from pydantic import BaseModel, Field

from skive.db import get_connection
from skive.drive_auth import current_user_id
from skive.drive_db import user_connection
from skive.drive_summary import rank_file
from skive.llm import anthropic_client, ensure_complete, request_options


router = APIRouter(prefix="/api/drive", tags=["project-summary"])
PROMPT_VERSION = "project-summary-agent-v2"
DEFAULT_MODEL = "claude-haiku-5-5"
DEFAULT_EFFORT = "low"
MAX_AGENT_TURNS = 24
AGENT_MAX_TOKENS = 64000
AGENT_TIMEOUT_SECONDS = 360
NUMBER = re.compile(r"(?<![A-Za-z])\d+(?:[.,]\d+)*")
TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{1,}|[가-힣]{2,}")


class EvidenceRef(BaseModel):
    source_id: str = Field(pattern=r"^S\d+$")
    quote: str = Field(default="", max_length=300)


class GroundedNote(BaseModel):
    text: str = Field(min_length=2, max_length=1600)
    subject: Literal["project", "team", "user", "unknown", "not_applicable"] = "unknown"
    evidence: list[EvidenceRef] = Field(min_length=1, max_length=6)


class ProjectStage(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    path: str = Field(min_length=1, max_length=600)
    purpose: str = Field(default="자료 역할 미확인", max_length=1000)
    inputs: list[str] = Field(default_factory=list, max_length=8)
    outputs: list[str] = Field(default_factory=list, max_length=8)
    connections: list[str] = Field(default_factory=list, max_length=8)
    evidence: list[EvidenceRef] = Field(default_factory=list, max_length=6)


class ProjectMetric(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    value: str = Field(min_length=1, max_length=200)
    unit: str = Field(default="", max_length=80)
    comparison: str = Field(default="", max_length=500)
    conditions: str = Field(default="", max_length=800)
    subject: Literal["project", "team", "user", "unknown"] = "unknown"
    evidence: list[EvidenceRef] = Field(min_length=1, max_length=6)


class AppendixSection(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=2, max_length=5000)
    kind: Literal["connection", "interpretation", "domain_note", "open_issue", "other"]
    evidence: list[EvidenceRef] = Field(default_factory=list, max_length=10)


class ProjectSubmission(BaseModel):
    project_type: list[GroundedNote] = Field(default_factory=list, max_length=3)
    period: list[GroundedNote] = Field(default_factory=list, max_length=3)
    data_used: list[GroundedNote] = Field(default_factory=list, max_length=8)
    overview: list[GroundedNote] = Field(default_factory=list, max_length=5)
    stages: list[ProjectStage] = Field(default_factory=list, max_length=30)
    workflow: list[GroundedNote] = Field(default_factory=list, max_length=20)
    goals: list[GroundedNote] = Field(default_factory=list, max_length=12)
    project_actions: list[GroundedNote] = Field(default_factory=list, max_length=20)
    personal_actions: list[GroundedNote] = Field(default_factory=list, max_length=12)
    methods: list[GroundedNote] = Field(default_factory=list, max_length=20)
    decisions: list[GroundedNote] = Field(default_factory=list, max_length=15)
    metrics: list[ProjectMetric] = Field(default_factory=list, max_length=20)
    trials: list[GroundedNote] = Field(default_factory=list, max_length=15)
    relations: list[GroundedNote] = Field(default_factory=list, max_length=20)
    questions: list[str] = Field(default_factory=list, max_length=12)
    appendix: list[AppendixSection] = Field(default_factory=list, max_length=12)


SYSTEM = """너는 SKIVE의 프로젝트 조사 에이전트다. 사용자가 지정한 프로젝트 루트와 모든
하위 폴더를 조사해, 작은 모델도 이 문서 하나로 목적·단계·자료 연결·방법·결과·한계를 이해할 수
있는 구조화 결과를 만든다. 먼저 제공된 구조와 대표 원문을 읽고 부족할 때만 검색한다. 전처리,
특징 선택, 모델링, 평가처럼 하위 폴더 사이의 입력과 출력을 연결한다. 모든 사실과 수치는 S번호와
원문 인용을 붙인다. 팀 결과를 사용자 개인 성과로 바꾸지 않는다. 본인 역할이 불명확하면
personal_actions를 비우고 questions에 묻는다. appendix에는 고정 항목 밖의 연결·도메인 설명·
관찰·남은 문제를 자세히 적을 수 있지만 사실과 숫자에는 근거가 필요하고 추론은 interpretation으로
표시한다. 조사가 끝나면 반드시 submit_project_summary를 호출한다."""


def project_inventory(conn, user_id: UUID, root_folder_id: UUID) -> tuple[list[dict], list[dict]]:
    folders = conn.execute(
        "with recursive tree as ("
        "select id,parent_id,name,name::text as path,0 as depth,updated_at "
        "from skive.drive_folders where id=%s and user_id=%s and trashed_at is null "
        "union all select f.id,f.parent_id,f.name,tree.path || ' / ' || f.name,"
        "tree.depth+1,f.updated_at from skive.drive_folders f join tree on f.parent_id=tree.id "
        "where f.user_id=%s and f.trashed_at is null) "
        "select id,parent_id,name,path,depth,updated_at from tree order by path",
        (root_folder_id, user_id, user_id),
    ).fetchall()
    if not folders:
        raise ValueError("프로젝트 폴더를 찾을 수 없습니다")
    files = conn.execute(
        "with recursive tree as ("
        "select id,name,name::text as path from skive.drive_folders "
        "where id=%s and user_id=%s and trashed_at is null "
        "union all select f.id,f.name,tree.path || ' / ' || f.name "
        "from skive.drive_folders f join tree on f.parent_id=tree.id "
        "where f.user_id=%s and f.trashed_at is null) "
        "select d.id,d.folder_id,d.name,d.version,d.size_bytes,d.mime_type,d.upload_status,"
        "d.analysis_status,d.analysis_error,d.analyzed_at,d.updated_at,"
        "tree.path || ' / ' || d.name as path,c.status as read_card_status,"
        "c.chunk_count,c.quote_count,c.number_count from skive.drive_files d "
        "join tree on d.folder_id=tree.id left join skive.drive_file_read_cards c "
        "on c.file_id=d.id and c.file_version=d.version where d.user_id=%s "
        "and d.trashed_at is null order by path,d.id",
        (root_folder_id, user_id, user_id, user_id),
    ).fetchall()
    return [dict(row) for row in folders], [dict(row) for row in files]


def project_signature(folders: list[dict], files: list[dict]) -> str:
    payload = {
        "folders": [(str(r["id"]), str(r.get("parent_id") or ""), r["name"],
                     r["updated_at"].isoformat()) for r in folders],
        "files": [(str(r["id"]), r["path"], r["version"], r["upload_status"],
                   r["analysis_status"], r["updated_at"].isoformat()) for r in files],
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()


def coverage_for(folders: list[dict], files: list[dict]) -> dict:
    analysis = Counter(row["analysis_status"] for row in files)
    cards = Counter(row.get("read_card_status") or "missing" for row in files)
    return {"folders_total": len(folders), "files_total": len(files),
            "bytes_total": sum(row["size_bytes"] or 0 for row in files),
            "analysis_status": dict(analysis), "read_card_status": dict(cards),
            "text_ready": analysis.get("ready", 0),
            "unread_or_partial": len(files) - analysis.get("ready", 0)}


def _normal(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _best_quote(source_text: str, claim: str) -> str:
    terms = {token.casefold() for token in TOKEN.findall(claim) if len(token) >= 3}
    numbers = set(NUMBER.findall(claim))
    lines = [line.strip() for line in source_text.splitlines() if len(line.strip()) >= 3]
    if not lines:
        return source_text.strip()[:300]
    def score(line: str):
        folded = line.casefold()
        return 4 * sum(number in line for number in numbers) + sum(term in folded for term in terms)
    return max(lines, key=score)[:300]


def _canonical_evidence(refs: list[EvidenceRef], sources: dict[str, dict], text: str,
                        allow_empty: bool = False) -> list[dict] | None:
    if not refs:
        return [] if allow_empty else None
    found = []
    for ref in refs:
        source = sources.get(ref.source_id)
        if source:
            found.append((ref, source))
    if not found:
        return None
    combined = " ".join(source["text"] for _, source in found)
    if not set(NUMBER.findall(text)) <= set(NUMBER.findall(combined)):
        return None
    terms = {token.casefold() for token in TOKEN.findall(text) if len(token) >= 3}
    if terms and not any(term in combined.casefold() for term in terms):
        return None
    result = []
    for ref, source in found:
        quote = ref.quote if ref.quote and _normal(ref.quote) in _normal(source["text"]) else _best_quote(source["text"], text)
        result.append({"source_id": ref.source_id, "quote": quote})
    return result


def validate_submission(submission: ProjectSubmission, sources: dict[str, dict]) -> tuple[dict, list[str]]:
    data, held = submission.model_dump(), []
    note_fields = ("project_type", "period", "data_used", "overview", "workflow", "goals",
                   "project_actions", "personal_actions", "methods", "decisions", "trials", "relations")
    for name in note_fields:
        kept = []
        for raw, note in zip(data[name], getattr(submission, name)):
            canonical = _canonical_evidence(note.evidence, sources, note.text)
            if note.subject == "user":
                held.append(f"본인 역할 자동 확정 보류: {note.text}")
            elif canonical is not None:
                raw["evidence"] = canonical
                kept.append(raw)
            else:
                held.append(note.text)
        data[name] = kept
    kept_stages = []
    for raw, stage in zip(data["stages"], submission.stages):
        text = " ".join([stage.purpose, *stage.inputs, *stage.outputs, *stage.connections])
        empty_placeholder = (not stage.evidence and stage.purpose == "자료 역할 미확인"
                             and not stage.inputs and not stage.outputs and not stage.connections)
        canonical = _canonical_evidence(stage.evidence, sources, text, allow_empty=empty_placeholder)
        if canonical is not None:
            raw["evidence"] = canonical
            kept_stages.append(raw)
        else:
            held.append(f"단계 설명 보류: {stage.path}")
    data["stages"] = kept_stages
    kept_metrics = []
    for raw, metric in zip(data["metrics"], submission.metrics):
        text = " ".join((metric.name, metric.value, metric.unit, metric.comparison, metric.conditions))
        canonical = _canonical_evidence(metric.evidence, sources, text)
        if metric.subject == "user":
            held.append(f"본인 성과 자동 확정 보류: {metric.name} {metric.value}")
        elif canonical is not None:
            raw["evidence"] = canonical
            kept_metrics.append(raw)
        else:
            held.append(f"수치 보류: {metric.name} {metric.value}")
    data["metrics"] = kept_metrics
    kept_appendix = []
    for raw, section in zip(data["appendix"], submission.appendix):
        allowed_empty = section.kind == "open_issue" and not NUMBER.search(section.body)
        canonical = _canonical_evidence(section.evidence, sources, section.body,
                                        allow_empty=allowed_empty)
        if canonical is not None:
            raw["evidence"] = canonical
            kept_appendix.append(raw)
        else:
            held.append(f"부록 보류: {section.title}")
    data["appendix"] = kept_appendix
    return data, held


def _cites(item: dict) -> str:
    ids = list(dict.fromkeys(ref["source_id"] for ref in item.get("evidence", [])))
    return f" [근거: {', '.join(ids)}]" if ids else ""


def _notes(items: list[dict], empty: str = "확인된 내용 없음") -> list[str]:
    return [f"- {item['text']}{_cites(item)}" for item in items] or [f"- {empty}"]


def _cell(value) -> str:
    if isinstance(value, list):
        value = ", ".join(value)
    return str(value or "확인되지 않음").replace("|", "\\|").replace("\n", " ")


def _stage_depth(folders: list[dict]) -> int:
    """Skip single-folder wrappers and use the project's first real branch as its stages."""
    counts = Counter(int(row["depth"]) for row in folders if int(row["depth"]) > 0)
    return next((depth for depth in sorted(counts) if counts[depth] > 1), 1)


def ensure_stage_coverage(structured: dict, folders: list[dict]) -> dict:
    """Keep every structural stage visible even when the agent found no reliable explanation."""
    result = {**structured, "stages": list(structured.get("stages", []))}
    depth = _stage_depth(folders)
    expected = [row for row in folders if int(row["depth"]) == depth]
    by_path = {_normal(stage["path"]): stage for stage in result["stages"]}
    by_name = {_normal(stage["name"]): stage for stage in result["stages"]}
    ordered, used = [], set()
    for folder in expected:
        stage = by_path.get(_normal(folder["path"])) or by_name.get(_normal(folder["name"]))
        if stage:
            used.add(id(stage))
            ordered.append(stage)
        else:
            ordered.append({"name": folder["name"], "path": folder["path"],
                            "purpose": "자료 역할 미확인", "inputs": [], "outputs": [],
                            "connections": [], "evidence": []})
    ordered.extend(stage for stage in result["stages"] if id(stage) not in used)
    result["stages"] = ordered
    return result


def render_project_markdown(title: str, root_folder_id: UUID, structured: dict,
                            sources: dict[str, dict], coverage: dict, held: list[str]) -> str:
    """Render a predictable front section plus an evidence-labelled free appendix."""
    lines = [
        "---", "skive_document: project_summary", "schema_version: 1",
        f"project_root_id: {root_folder_id}",
        "fact_policy: document_evidence_and_user_confirmation_are_separate", "---", "",
        f"# {title} — 프로젝트 통합 요약", "",
        "> 이 문서는 프로젝트 루트 아래 자료를 연결해 만든 AI 초안입니다. `[근거: S번호]`가",
        "> 없는 개인 역할·성과는 사실로 사용하지 않습니다. 부록의 AI 해석은 독립 근거가 아닙니다.",
        "", "## 프로젝트 한눈에 보기",
        *_notes(structured["overview"], "자료에서 확정할 요약을 찾지 못함"),
        "", "### 프로젝트 유형", *_notes(structured["project_type"]),
        "", "### 기간", *_notes(structured["period"]),
        "", "### 사용한 데이터·대상", *_notes(structured["data_used"]),
        "", "## 폴더와 작업 단계", "",
        "| 단계 | 폴더 | 무엇을 한 자료인가 | 입력 | 출력·다음 단계 |",
        "|---:|---|---|---|---|",
    ]
    for index, stage in enumerate(structured["stages"], 1):
        output = [*stage.get("outputs", []), *stage.get("connections", [])]
        lines.append(f"| {index} | {_cell(stage['path'])} | {_cell(stage['purpose'])}{_cites(stage)} | "
                     f"{_cell(stage.get('inputs'))} | {_cell(output)} |")
    if not structured["stages"]:
        lines.append("| 1 | 확인되지 않음 | 폴더 구조만 있고 단계 의미는 아직 확인하지 못함 | — | — |")
    lines += ["", "## 전체 작업 흐름", *_notes(structured["workflow"]),
              "", "## 확인된 프로젝트 목표", *_notes(structured["goals"]),
              "", "## 수행한 작업", "", "### 자료로 확인된 프로젝트·팀 작업",
              *_notes(structured["project_actions"]),
              "", "### 본인이 했다고 확인된 작업",
              *_notes(structured["personal_actions"], "자료만으로 확인된 본인 작업 없음"),
              "", "### 본인 역할 확인 필요"]
    questions = list(dict.fromkeys(structured["questions"]))
    lines += ([f"{i}. {question}" for i, question in enumerate(questions, 1)] or
              ["- 자료에서 본인 역할을 확인할 수 있으면 사용자 확인을 받아야 함"])
    lines += ["", "## 사용한 기술과 방법", *_notes(structured["methods"]),
              "", "## 주요 의사결정", *_notes(structured["decisions"]),
              "", "## 결과와 수치", "",
              "| 지표 | 값 | 단위 | 비교 기준·조건 | 주체 | 근거 |",
              "|---|---:|---|---|---|---|"]
    for metric in structured["metrics"]:
        condition = " / ".join(x for x in (metric.get("comparison"), metric.get("conditions")) if x)
        refs = ", ".join(ref["source_id"] for ref in metric["evidence"])
        lines.append(f"| {_cell(metric['name'])} | {_cell(metric['value'])} | {_cell(metric['unit'])} | "
                     f"{_cell(condition)} | {_cell(metric['subject'])} | {_cell(refs)} |")
    if not structured["metrics"]:
        lines.append("| 확인된 수치 없음 | — | — | — | — | — |")
    lines += ["", "## 시행착오와 변경 과정", *_notes(structured["trials"]),
              "", "## 자료 사이의 연결 관계", *_notes(structured["relations"]),
              "", "## 검증 보류", *([f"- {item}" for item in held] or ["- 없음"]),
              "", "## 읽기 범위",
              f"- 프로젝트 폴더: {coverage['folders_total']}개",
              f"- 전체 파일: {coverage['files_total']}개",
              f"- 텍스트 추출 완료: {coverage['text_ready']}개",
              f"- 읽기 실패·미지원·대기: {coverage['unread_or_partial']}개",
              f"- 파일 상태: {json.dumps(coverage['analysis_status'], ensure_ascii=False)}",
              "", "## AI 확장 부록", "",
              "> 아래는 고정 항목에 담기 어려운 연결과 해석입니다. `interpretation`은 원문을",
              "> 바탕으로 한 AI 해석이며, 자소서의 독립 사실 근거로 사용하지 않습니다."]
    for section in structured["appendix"]:
        lines += ["", f"### {section['title']} · {section['kind']}",
                  section["body"] + _cites(section)]
    if not structured["appendix"]:
        lines += ["", "- 추가 부록 없음"]

    used = set()
    for field in ("project_type", "period", "data_used", "overview", "workflow", "goals",
                  "project_actions", "personal_actions", "methods", "decisions", "trials", "relations",
                  "metrics", "stages", "appendix"):
        for item in structured[field]:
            used.update(ref["source_id"] for ref in item.get("evidence", []))
    quote_index = defaultdict(list)
    for field in ("project_type", "period", "data_used", "overview", "workflow", "goals",
                  "project_actions", "personal_actions", "methods", "decisions", "trials", "relations",
                  "metrics", "stages", "appendix"):
        for item in structured[field]:
            for ref in item.get("evidence", []):
                quote = ref.get("quote", "").strip()
                if quote and quote not in quote_index[ref["source_id"]]:
                    quote_index[ref["source_id"]].append(quote)
    lines += ["", "## 출처"]
    for source_id in sorted(used, key=lambda value: int(value[1:])):
        source = sources[source_id]
        lines.append(f"- [{source_id}] {source['path']} · 파일 버전 {source['file_version']} · "
                     f"{source['location']} · 구간 {source['chunk_index']}")
        for quote in quote_index[source_id][:3]:
            lines.append(f"  - 원문: “{quote}”")
    if not used:
        lines.append("- 사용된 원문 출처 없음")
    return "\n".join(lines).rstrip() + "\n"


def _terms(query: str) -> list[str]:
    stop = {"자료", "파일", "프로젝트", "내용", "관련", "결과", "찾아줘", "알려줘"}
    return list(dict.fromkeys(t[:80] for t in TOKEN.findall(query)
                              if t.casefold() not in stop))[:10]


def _search_rows(conn, user_id: UUID, root_folder_id: UUID, query: str,
                 limit: int = 8) -> list[dict]:
    """Lexical project-only search; it never calls another model."""
    terms = _terms(query)
    if not terms:
        return []
    clauses, patterns = [], []
    for term in terms:
        escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        clauses.append("(d.name ilike %s escape '\\' or c.text ilike %s escape '\\' "
                       "or tree.path ilike %s escape '\\')")
        patterns.extend([f"%{escaped}%"] * 3)
    rows = conn.execute(
        "with recursive tree as ("
        "select id,name,name::text as path from skive.drive_folders "
        "where id=%s and user_id=%s and trashed_at is null "
        "union all select f.id,f.name,tree.path || ' / ' || f.name "
        "from skive.drive_folders f join tree on f.parent_id=tree.id "
        "where f.user_id=%s and f.trashed_at is null) "
        "select d.id as file_id,d.name,d.version as file_version,c.chunk_index,c.location,c.text,"
        "tree.path || ' / ' || d.name as path from skive.drive_file_chunks c "
        "join skive.drive_files d on d.id=c.file_id and d.user_id=c.user_id "
        "join tree on tree.id=d.folder_id where c.user_id=%s and d.trashed_at is null "
        "and d.analysis_status='ready' and (" + " or ".join(clauses) + ") limit 120",
        (root_folder_id, user_id, user_id, user_id, *patterns),
    ).fetchall()
    scored = []
    for raw in rows:
        row = dict(raw)
        content, name, path = row["text"].casefold(), row["name"].casefold(), row["path"].casefold()
        score = sum(5 if t.casefold() in name else 3 if t.casefold() in path
                    else 1 if t.casefold() in content else 0 for t in terms)
        if score:
            scored.append((score, row))
    scored.sort(key=lambda pair: (-pair[0], pair[1]["path"], pair[1]["chunk_index"]))
    selected, per_file = [], defaultdict(int)
    for _, row in scored:
        if per_file[row["file_id"]] >= 2:
            continue
        selected.append(row)
        per_file[row["file_id"]] += 1
        if len(selected) >= limit:
            break
    return selected


def _seed_rows(conn, user_id: UUID, files: list[dict], stage_depth: int) -> list[dict]:
    ready = [row for row in files if row["analysis_status"] == "ready"]
    by_stage = defaultdict(list)
    for row in sorted(ready, key=rank_file):
        parts = row["path"].split(" / ")
        by_stage[parts[stage_depth] if len(parts) > stage_depth else parts[-1]].append(row)
    picked, seen = [], set()
    for group in by_stage.values():
        for row in group[:1]:
            if row["id"] not in seen:
                picked.append(row); seen.add(row["id"])
    for row in sorted(ready, key=rank_file):
        if len(picked) >= 10:
            break
        if row["id"] not in seen:
            picked.append(row); seen.add(row["id"])
    if not picked:
        return []
    rows = conn.execute(
        "select c.file_id,d.name,d.version as file_version,c.chunk_index,c.location,"
        "left(c.text,2200) as text from skive.drive_file_chunks c "
        "join skive.drive_files d on d.id=c.file_id and d.user_id=c.user_id "
        "where c.user_id=%s and c.file_id=any(%s::uuid[]) and c.file_version=d.version "
        "and c.chunk_index=1 order by c.file_id,c.chunk_index",
        (user_id, [row["id"] for row in picked]),
    ).fetchall()
    paths = {row["id"]: row["path"] for row in picked}
    return [{**dict(row), "path": paths[row["file_id"]]} for row in rows]


def _manifest(folders: list[dict], files: list[dict], coverage: dict) -> str:
    stages = []
    stage_depth = _stage_depth(folders)
    for row in folders:
        if row["depth"] == stage_depth:
            prefix = row["path"] + " / "
            members = [f for f in files if f["path"].startswith(prefix)]
            stages.append({"path": row["path"], "files": len(members),
                           "ready": sum(f["analysis_status"] == "ready" for f in members)})
    important = sorted(files, key=rank_file)[:120]
    return json.dumps({"coverage": coverage, "stage_depth": stage_depth,
        "project_stage_folders": stages,
        "representative_file_inventory": [{"path": row["path"],
            "analysis_status": row["analysis_status"],
            "read_card_status": row.get("read_card_status")} for row in important],
        "inventory_truncated": len(files) > len(important)}, ensure_ascii=False, default=str)


def run_agent(user_id: UUID, root_folder_id: UUID, title: str, folders: list[dict],
              files: list[dict]) -> tuple[ProjectSubmission, dict[str, dict], dict]:
    """Run one bounded Claude tool loop over this project's sources."""
    model = os.getenv("SKIVE_PROJECT_AGENT_MODEL", DEFAULT_MODEL)
    effort = os.getenv("SKIVE_PROJECT_AGENT_EFFORT", DEFAULT_EFFORT)
    client = anthropic_client().with_options(timeout=AGENT_TIMEOUT_SECONDS)
    source_keys, sources, calls = {}, {}, []
    counts, submitted = Counter(), []

    def register(raw: dict) -> dict:
        row = dict(raw)
        key = (str(row["file_id"]), row["chunk_index"])
        source_id = source_keys.get(key)
        if source_id is None:
            source_id = f"S{len(sources) + 1}"
            source_keys[key] = source_id
            sources[source_id] = {**row, "file_id": str(row["file_id"])}
        source = sources[source_id]
        return {"source_id": source_id, "path": source["path"],
                "location": source["location"], "chunk_index": source["chunk_index"],
                "excerpt": source["text"][:1800]}

    with user_connection(user_id) as conn:
        seeds = [register(row) for row in _seed_rows(conn, user_id, files, _stage_depth(folders))]

    def list_project_files(args):
        counts["list"] += 1
        if counts["list"] > 4:
            return json.dumps({"error": "목록 호출 한도에 도달했습니다"}, ensure_ascii=False)
        prefix = str(args.get("path_prefix", "")).casefold().strip()
        offset = max(0, int(args.get("offset", 0)))
        limit = min(100, max(1, int(args.get("limit", 50))))
        matched = [row for row in files if not prefix or prefix in row["path"].casefold()]
        result = [{"path": row["path"], "analysis_status": row["analysis_status"],
                   "read_card_status": row.get("read_card_status")}
                  for row in matched[offset:offset + limit]]
        calls.append({"tool": "list_project_files", "prefix": prefix,
                      "offset": offset, "returned": len(result)})
        return json.dumps({"files": result, "next_offset": offset + limit
                           if offset + limit < len(matched) else None}, ensure_ascii=False)

    def search_project(args):
        counts["search"] += 1
        if counts["search"] > 8:
            return json.dumps({"error": "검색 호출 한도에 도달했습니다"}, ensure_ascii=False)
        query = str(args.get("query", ""))[:400]
        with user_connection(user_id) as conn:
            rows = _search_rows(conn, user_id, root_folder_id, query)
        hits = [register(row) for row in rows]
        calls.append({"tool": "search_project", "query": query, "hits": len(hits)})
        return json.dumps(hits, ensure_ascii=False)

    def read_source(args):
        counts["read"] += 1
        if counts["read"] > 8:
            return json.dumps({"error": "원문 읽기 호출 한도에 도달했습니다"}, ensure_ascii=False)
        source_id = str(args.get("source_id", ""))
        source = sources.get(source_id)
        calls.append({"tool": "read_source", "source_id": source_id,
                      "found": source is not None})
        if source is None:
            return json.dumps({"error": "먼저 검색 결과의 S번호를 사용해 주세요"}, ensure_ascii=False)
        return json.dumps({"source_id": source_id, "path": source["path"],
                           "location": source["location"], "text": source["text"][:10000]},
                          ensure_ascii=False)

    def submit_project_summary(args):
        try:
            result = ProjectSubmission.model_validate(args)
        except Exception as exc:
            return json.dumps({"accepted": False, "error": str(exc)[:1200]}, ensure_ascii=False)
        submitted.append(result)
        calls.append({"tool": "submit_project_summary"})
        return json.dumps({"accepted": True}, ensure_ascii=False)

    tools = [
        {"name": "list_project_files",
         "description": "List files and read states under this project root, optionally filtered by path.",
         "input_schema": {"type": "object", "properties": {
             "path_prefix": {"type": "string"}, "offset": {"type": "integer", "minimum": 0},
             "limit": {"type": "integer", "minimum": 1, "maximum": 100}},
             "required": ["path_prefix", "offset", "limit"], "additionalProperties": False}},
        {"name": "search_project",
         "description": "Search only this signed-in user's current project subtree and return S sources.",
         "input_schema": {"type": "object", "properties": {"query": {"type": "string"}},
                          "required": ["query"], "additionalProperties": False}},
        {"name": "read_source",
         "description": "Read the full extracted chunk for an S source returned by seed or search.",
         "input_schema": {"type": "object", "properties": {"source_id": {"type": "string"}},
                          "required": ["source_id"], "additionalProperties": False}},
        {"name": "submit_project_summary",
         "description": "Submit the final structured project understanding. Required to finish.",
         "input_schema": ProjectSubmission.model_json_schema()},
    ]
    # 긴 요약 입력이 한 번에 버퍼링되지 않게 한다. 잘린 입력은 아래 ensure_complete가 막는다.
    tools = [{**tool, "eager_input_streaming": True} for tool in tools]
    handlers = {"list_project_files": list_project_files, "search_project": search_project,
                "read_source": read_source, "submit_project_summary": submit_project_summary}
    prompt = (f"프로젝트 루트: {title}\n\n[폴더·파일 구조]\n"
              f"{_manifest(folders, files, coverage_for(folders, files))}\n\n"
              f"[우선 읽을 대표 원문]\n{json.dumps(seeds, ensure_ascii=False)}\n\n"
              "project_stage_folders의 각 단계와 자료 연결을 조사한 뒤 구조화 요약을 제출하세요. "
              "고정 필드를 최대한 채우고, 여기에 담기 어려운 프로젝트 고유 맥락·파일 관계·도메인 "
              "설명은 appendix에 충분히 기록하세요. 대표 원문만으로 근거가 부족한 항목은 검색하고, "
              "본인 역할은 단정하지 말고 질문으로 남기세요.")
    started = time.perf_counter()
    messages = [{"role": "user", "content": prompt}]
    for _ in range(MAX_AGENT_TURNS):
        with client.beta.messages.stream(
            model=model, max_tokens=AGENT_MAX_TOKENS, system=SYSTEM, tools=tools,
            messages=messages, cache_control={"type": "ephemeral"},
            **request_options(model, effort),
        ) as stream:
            response = stream.get_final_message()
        ensure_complete(response)
        messages.append({"role": "assistant", "content": response.content})
        uses = [block for block in response.content if block.type == "tool_use"]
        if not uses:
            messages.append({"role": "user",
                             "content": "submit_project_summary 도구로 구조화 요약을 제출하세요."})
            continue
        results = []
        for use in uses:
            handler = handlers.get(use.name)
            output = handler(use.input) if handler else json.dumps(
                {"error": "지원하지 않는 도구입니다"}, ensure_ascii=False)
            results.append({"type": "tool_result", "tool_use_id": use.id, "content": output})
        messages.append({"role": "user", "content": results})
        if submitted:
            trace = {"model": model, "prompt_version": PROMPT_VERSION,
                     "seconds": round(time.perf_counter() - started, 2), "calls": calls,
                     "tool_counts": dict(counts)}
            return submitted[-1], sources, trace
    raise RuntimeError("프로젝트 분석 에이전트가 구조화 요약을 제출하지 않았습니다")


def _nearest_project_summary(conn, folder_id: UUID):
    return conn.execute(
        "with recursive ancestors as ("
        "select id,parent_id,0 as distance from skive.drive_folders where id=%s and trashed_at is null "
        "union all select f.id,f.parent_id,a.distance+1 from skive.drive_folders f "
        "join ancestors a on a.parent_id=f.id where f.trashed_at is null) "
        "select s.*,f.name as root_name,a.distance from ancestors a "
        "join skive.drive_project_summaries s on s.root_folder_id=a.id "
        "join skive.drive_folders f on f.id=s.root_folder_id order by a.distance limit 1", (folder_id,),
    ).fetchone()


@router.get("/folders/{folder_id}/project-summary")
def get_project_summary(folder_id: UUID, user_id: UUID = Depends(current_user_id)):
    with user_connection(user_id) as conn:
        if not conn.execute("select 1 from skive.drive_folders where id=%s and trashed_at is null",
                            (folder_id,)).fetchone():
            raise HTTPException(404, "Folder not found")
        row = _nearest_project_summary(conn, folder_id)
        if not row:
            return {"status": "missing", "requested_folder_id": folder_id}
        folders, files = project_inventory(conn, user_id, row["root_folder_id"])
        return {**row, "stale": row["status"] == "ready" and
                row["source_signature"] != project_signature(folders, files)}


@router.post("/folders/{folder_id}/project-summary")
def request_project_summary(folder_id: UUID, user_id: UUID = Depends(current_user_id)):
    with user_connection(user_id) as conn:
        folder = conn.execute("select id,name from skive.drive_folders where id=%s and trashed_at is null",
                              (folder_id,)).fetchone()
        if not folder:
            raise HTTPException(404, "Folder not found")
        ancestor = _nearest_project_summary(conn, folder_id)
        if ancestor and ancestor["root_folder_id"] != folder_id:
            raise HTTPException(409, f"이미 상위 프로젝트 '{ancestor['root_name']}'의 통합 요약에 포함된 폴더입니다")
        folders, files = project_inventory(conn, user_id, folder_id)
        if not files:
            raise HTTPException(409, "이 프로젝트 폴더에는 요약할 파일이 없습니다")
    with get_connection() as conn:
        conn.row_factory = dict_row
        return conn.execute(
            "insert into skive.drive_project_summaries(user_id,root_folder_id,status) "
            "values (%s,%s,'queued') on conflict (root_folder_id) do update set "
            "status=case when skive.drive_project_summaries.status in ('queued','processing') "
            "then skive.drive_project_summaries.status else 'queued' end,"
            "error=null,updated_at=now() returning id,root_folder_id,status,updated_at",
            (user_id, folder_id),
        ).fetchone()


def run_project_summary_once() -> bool:
    with get_connection() as conn:
        conn.row_factory = dict_row
        job = conn.execute(
            "select s.id,s.user_id,s.root_folder_id,f.name from skive.drive_project_summaries s "
            "join skive.drive_folders f on f.id=s.root_folder_id and f.user_id=s.user_id "
            "where s.status='queued' and f.trashed_at is null order by s.updated_at "
            "for update of s skip locked limit 1"
        ).fetchone()
        if not job:
            return False
        folders, files = project_inventory(conn, job["user_id"], job["root_folder_id"])
        if any(row["upload_status"] == "pending" or
               row["analysis_status"] in {"waiting", "queued", "processing"} for row in files):
            return False
        conn.execute("update skive.drive_project_summaries set status='processing',error=null,"
                     "updated_at=now() where id=%s", (job["id"],))
    try:
        submission, sources, trace = run_agent(job["user_id"], job["root_folder_id"],
                                                job["name"], folders, files)
        structured, held = validate_submission(submission, sources)
        structured = ensure_stage_coverage(structured, folders)
        coverage = coverage_for(folders, files)
        markdown = render_project_markdown(job["name"], job["root_folder_id"], structured,
                                           sources, coverage, held)
        used_ids = sorted(set(re.findall(r"\bS\d+\b", markdown)), key=lambda value: int(value[1:]))
        source_index = [{key: value for key, value in sources[source_id].items() if key != "text"}
                        | {"source_id": source_id} for source_id in used_ids]
        with get_connection() as conn:
            conn.row_factory = dict_row
            latest_folders, latest_files = project_inventory(conn, job["user_id"], job["root_folder_id"])
            if project_signature(latest_folders, latest_files) != project_signature(folders, files):
                conn.execute("update skive.drive_project_summaries set status='queued',updated_at=now() "
                             "where id=%s", (job["id"],))
                return True
            conn.execute(
                "update skive.drive_project_summaries set status='ready',source_signature=%s,"
                "markdown=%s,structured_summary=%s::jsonb,source_index=%s::jsonb,coverage=%s::jsonb,"
                "agent_trace=%s::jsonb,model=%s,prompt_version=%s,error=null,updated_at=now() where id=%s",
                (project_signature(folders, files), markdown, json.dumps(structured, ensure_ascii=False),
                 json.dumps(source_index, ensure_ascii=False, default=str),
                 json.dumps(coverage, ensure_ascii=False), json.dumps(trace, ensure_ascii=False),
                 trace["model"], PROMPT_VERSION, job["id"]),
            )
    except Exception as exc:
        with get_connection() as conn:
            # A failed refresh must not hide a previously usable report.
            conn.execute("update skive.drive_project_summaries set "
                         "status=case when markdown is not null then 'ready' else 'failed' end,"
                         "error=%s,updated_at=now() where id=%s", (str(exc)[:1000], job["id"]))
    return True
