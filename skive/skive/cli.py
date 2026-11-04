import argparse
import json
import sys
from pathlib import Path

from skive import store
from skive.analyzer import analyze_folder
from skive.apply import run_apply
from skive.importance import score_importance
from skive.profile import build_profile
from skive.user import load_user

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "outputs"


def _ingest(folder: str, grade: int, exp_id: str | None = None) -> None:
    from skive.chunks_store import sync_chunks

    user = load_user()
    root = Path(folder)
    exp_id = exp_id or root.name
    markdown, meta, facts = analyze_folder(root, user["name"], exp_id, grade)
    meta["importance"] = score_importance(meta, facts, user["career_goal"])
    store.save(exp_id, markdown, meta, facts)
    n_chunks = sync_chunks(exp_id, root)
    imp = meta["importance"]
    print(
        f"[{exp_id}] {meta['grade']}학년 {meta['kind']} | 근거 {meta['evidence_verified']}/{meta['evidence_total']} | "
        f"역할검증={meta['my_role_verified']} | 중요도 {imp['score']}/{imp['max']} ({imp['tier']}) | 청크 {n_chunks}개 임베딩"
    )
    for question in meta["open_questions"]:
        print(f"    [질문] {question}")


def cmd_ingest(args: argparse.Namespace) -> None:
    _ingest(args.folder, args.grade, args.id)


def cmd_ingest_all(args: argparse.Namespace) -> None:
    for item in json.loads(Path(args.manifest).read_text(encoding="utf-8")):
        _ingest(item["folder"], item["grade"])


def cmd_list(_: argparse.Namespace) -> None:
    for m in store.list_meta():
        print(f"- {m['id']} | {m['grade']}학년 | {m['title']} | {m['importance']['tier']} | 근거 {m['evidence_verified']}/{m['evidence_total']}")


def cmd_profile(_: argparse.Namespace) -> None:
    markdown, profile = build_profile()
    path = store.save_profile(markdown, profile)
    print(markdown)
    print(f"저장: {path}")


def cmd_apply(args: argparse.Namespace) -> None:
    result = run_apply(Path(args.job_file).read_text(encoding="utf-8"))
    job = result["job"]
    print(f"== 공고: {job['company']} / {job['role']} ==")
    print("핵심 역량:", ", ".join(job["key_competencies"]))
    print("인재상:", ", ".join(job["values"]) or "명시 없음")
    print("\n== 도구 호출 ==")
    for name, call_args in result["trace"]:
        print(f"  {name} {json.dumps(call_args, ensure_ascii=False)[:100]}")
    print("\n== 역량 ↔ 경험 ==")
    for link in result["plan"]["competency_links"]:
        print(f"  [{link['strength']}] {link['competency']} <- {link['experience_ids']} : {link['note']}")
    for ans in result["answers"]:
        print(f"\n== 문항: {ans['question']} ==")
        print(f"경험: {ans['experience_ids']} | 상태: {ans['status']} | 재작성 {ans['attempts']}회")
        if ans["gap"]:
            print(f"부족한 점: {ans['gap']}")
        print(ans["draft"] or "(작성하지 않음)")
        for sentence in ans["removed"]:
            print(f"  (제거됨) {sentence}")
        for issue in ans["issues"]:
            if not issue.startswith("["):
                print(f"  (미해결) {issue}")
    if result["questions_for_user"]:
        print("\n== 사용자에게 확인할 질문 ==")
        for q in result["questions_for_user"]:
            print(f"  - {q}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUTPUT_DIR / f"apply_{Path(args.job_file).stem}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장: {out}")


def cmd_chat(args: argparse.Namespace) -> None:
    from skive.chat import run_chat

    run_chat(Path(args.script) if args.script else None)


def cmd_ask(args: argparse.Namespace) -> None:
    from skive.chat import ask_once, build_chat_graph

    _, answer = ask_once(build_chat_graph(), [], args.question)
    print(answer)


def cmd_migrate(_: argparse.Namespace) -> None:
    from skive.db import run_migrations

    applied = run_migrations()
    print("적용된 마이그레이션:", ", ".join(applied) if applied else "없음 (이미 최신 상태)")


def cmd_sync_chunks(args: argparse.Namespace) -> None:
    """이미 ingest된 경험의 원본 파일을 다시 읽어 청크+임베딩을 DB에 (재)생성한다.
    스키마를 처음 만든 뒤 기존 경험들을 채워 넣거나, 원본 파일이 바뀌었을 때 쓴다."""
    from skive.chunks_store import sync_chunks

    ids = [args.id] if args.id else [m["id"] for m in store.list_meta()]
    for exp_id in ids:
        meta = store.get_meta(exp_id)
        if meta is None:
            print(f"[{exp_id}] 존재하지 않는 id, 건너뜀")
            continue
        n = sync_chunks(exp_id, Path(meta["raw_dir"]))
        print(f"[{exp_id}] 청크 {n}개 임베딩 완료")


def cmd_report(args: argparse.Namespace) -> None:
    from skive.report_html import build_report

    apply_result = json.loads(Path(args.apply_json).read_text(encoding="utf-8"))
    out = OUTPUT_DIR / f"report_{Path(args.apply_json).stem.removeprefix('apply_')}.html"
    out.write_text(build_report(apply_result), encoding="utf-8")
    print(f"저장: {out}")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="skive")
    sub = parser.add_subparsers(required=True)

    p = sub.add_parser("ingest", help="프로젝트 폴더 1개 분석")
    p.add_argument("folder")
    p.add_argument("--grade", type=int, required=True)
    p.add_argument("--id")
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("ingest-all", help="manifest.json의 폴더들을 모두 분석")
    p.add_argument("manifest")
    p.set_defaults(func=cmd_ingest_all)

    sub.add_parser("list", help="저장된 경험 목록").set_defaults(func=cmd_list)
    sub.add_parser("profile", help="경험들을 종합해 프로필 생성").set_defaults(func=cmd_profile)

    p = sub.add_parser("apply", help="공고 → 인재상·역량 분석 → 문항별 경험 매칭·초안")
    p.add_argument("job_file")
    p.set_defaults(func=cmd_apply)

    p = sub.add_parser("chat", help="챗봇 대화. 종료하면 공부 내용을 자동 기록")
    p.add_argument("--script", help="입력을 파일의 줄 단위로 대신함 (시연·테스트용)")
    p.set_defaults(func=cmd_chat)

    p = sub.add_parser("ask", help="기억(프로필·경험·공부 기록)에 한 번 질문")
    p.add_argument("question")
    p.set_defaults(func=cmd_ask)

    sub.add_parser("migrate", help="migrations/*.sql을 DB에 순서대로 적용").set_defaults(func=cmd_migrate)

    p = sub.add_parser("sync-chunks", help="경험의 원본 파일을 다시 읽어 청크+임베딩을 DB에 (재)생성")
    p.add_argument("--id", help="이 경험만. 생략하면 저장된 경험 전체")
    p.set_defaults(func=cmd_sync_chunks)

    p = sub.add_parser("report", help="apply 결과로 시연용 HTML 리포트 생성")
    p.add_argument("apply_json")
    p.set_defaults(func=cmd_report)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
