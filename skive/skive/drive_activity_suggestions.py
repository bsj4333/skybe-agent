"""Conservative, review-only activity suggestions from Drive organization.

Folder membership is a clue, never proof that files describe one activity.
Suggestions can overlap; the user decides which files to link to an activity.
"""

from collections import defaultdict
from collections import Counter
from pathlib import Path
import re


STOP = {"보고서", "자료", "파일", "결과", "분석", "데이터", "프로젝트", "최종", "초안",
        "수업", "실험", "모델", "테스트", "코드", "사용", "연구", "내용", "정리",
        "report", "result", "results", "data", "project", "final", "test", "file",
        "model", "output", "outputs", "readme", "sample", "analysis", "script"}
TOKEN = re.compile(r"[가-힣]{2,}|[a-zA-Z][a-zA-Z0-9]{2,}")


def _tokens(file: dict) -> set[str]:
    title = Path(file["name"]).stem.replace("_", " ").replace("-", " ")
    content = (file.get("preview") or "")[:1200]
    return {token for token in (match.group().casefold() for match in TOKEN.finditer(title + " " + content))
            if token not in STOP and len(token) >= 3}


def _content_groups(folders: dict, files: list[dict], limit: int) -> list[dict]:
    ready = [file for file in files if file["analysis_status"] == "ready" and file.get("preview")][:500]
    if len(ready) < 2:
        return []
    tokens = [_tokens(file) for file in ready]
    index = defaultdict(list)
    for i, terms in enumerate(tokens):
        for term in terms:
            index[term].append(i)
    pair_terms = defaultdict(set)
    maximum = max(3, min(20, len(ready) // 3))
    for term, positions in index.items():
        if not (2 <= len(positions) <= maximum):
            continue
        for left_index, left in enumerate(positions):
            for right in positions[left_index + 1:]:
                pair_terms[left, right].add(term)

    def root(folder_id):
        seen = set()
        while folder_id in folders and folder_id not in seen:
            seen.add(folder_id)
            parent = folders[folder_id]["parent_id"]
            if parent is None:
                return folder_id
            folder_id = parent
        return None

    roots = [root(file["folder_id"]) for file in ready]
    parent = list(range(len(ready)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for (left, right), common in sorted(pair_terms.items(), key=lambda item: -len(item[1])):
        if roots[left] == roots[right]:
            continue
        title_left = _tokens({**ready[left], "preview": ""})
        title_right = _tokens({**ready[right], "preview": ""})
        special_title = any(len(term) >= 6 and term in title_left and term in title_right
                            and len(index[term]) <= 3 for term in common)
        if len(common) >= 2 or special_title:
            left_root, right_root = find(left), find(right)
            if left_root != right_root:
                parent[right_root] = left_root
    groups = defaultdict(list)
    for i, file in enumerate(ready):
        groups[find(i)].append(i)
    suggestions = []
    for positions in groups.values():
        if len(positions) < 2 or len(positions) > 30:
            continue
        if len({roots[i] for i in positions}) < 2:
            continue
        shared = Counter(term for i in positions for term in tokens[i])
        terms = [term for term, count in shared.most_common() if count >= 2][:3]
        if not terms:
            continue
        group = [ready[i] for i in positions]
        suggestions.append({"folder_id": None, "title": "관련 자료: " + ", ".join(terms[:2]),
                            "reason": "서로 다른 폴더의 파일명·원문 공통 단어: " + ", ".join(terms),
                            "file_count": len(group),
                            "files": [{"id": item["id"], "name": item["name"],
                                       "analysis_status": item["analysis_status"]} for item in group]})
    suggestions.sort(key=lambda item: (-item["file_count"], item["title"]))
    return suggestions[:limit]


def suggest_groups(folders: list[dict], files: list[dict], *, min_files=2, max_groups=40) -> list[dict]:
    by_id = {row["id"]: row for row in folders}
    members: dict[object, list[dict]] = defaultdict(list)
    depths: dict[object, int] = {}
    for file in files:
        ancestry = []
        seen = set()
        folder_id = file["folder_id"]
        while folder_id in by_id and folder_id not in seen:
            seen.add(folder_id)
            folder = by_id[folder_id]
            ancestry.append(folder)
            folder_id = folder["parent_id"]
        for depth, folder in enumerate(reversed(ancestry[:2] if len(ancestry) <= 2 else ancestry[-2:]), start=1):
            # The first two ancestors below the drive root are useful starting
            # points. A deep stage directory must not become an activity by default.
            if depth > 2:
                break
            members[folder["id"]].append(file)
            depths[folder["id"]] = depth
    result = []
    for folder_id, group in members.items():
        if len(group) < min_files:
            continue
        folder = by_id[folder_id]
        result.append({
            "folder_id": folder_id,
            "title": folder["name"],
            "reason": "같은 상위 폴더의 파일" if depths[folder_id] == 1 else "같은 하위 폴더의 파일",
            "file_count": len(group),
            "files": [{"id": item["id"], "name": item["name"],
                       "analysis_status": item["analysis_status"]} for item in group],
        })
    result.sort(key=lambda item: (0 if depths[item["folder_id"]] == 2 else 1,
                                  -item["file_count"], item["title"].casefold()))
    content = _content_groups(by_id, files, max_groups)
    return (content + result)[:max_groups]
