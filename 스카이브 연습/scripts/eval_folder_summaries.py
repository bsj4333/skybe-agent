"""Print compact, ASCII-safe quality evidence for generated folder drafts."""

import json

from skive.db import get_connection


with get_connection() as conn:
    rows = conn.execute(
        "select f.name,s.status,s.files_considered,s.files_selected,s.facts,s.error "
        "from skive.drive_folder_summaries s join skive.drive_folders f on f.id=s.folder_id "
        "order by f.name"
    ).fetchall()
print(json.dumps([
    {"folder": name, "status": status, "considered": considered, "selected": selected,
     "facts": len(facts), "auto_checked": sum(bool(f["auto_checked"]) for f in facts),
     "sources": sorted({e["file_name"] for f in facts for e in f["evidence"]})[:12],
     "examples": [{"text": f["text"], "source": f["evidence"][0]["file_name"] if f["evidence"] else None,
                   "checks": [e["check"] for e in f["evidence"][:1]]}
                  for f in facts[:3]], "error": error}
    for name, status, considered, selected, facts, error in rows
], ensure_ascii=True))
