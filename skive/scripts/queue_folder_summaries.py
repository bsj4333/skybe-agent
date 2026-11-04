"""Operator-only: queue experience drafts for explicit folder UUIDs."""

import sys
from uuid import UUID

from psycopg.rows import dict_row

from skive.db import get_connection


def main(ids: list[str]) -> None:
    if not ids:
        raise SystemExit("Usage: python -m scripts.queue_folder_summaries <folder-uuid> [...]")
    with get_connection() as conn:
        conn.row_factory = dict_row
        for raw in ids:
            folder_id = UUID(raw)
            row = conn.execute(
                "insert into skive.drive_folder_summaries (user_id,folder_id,status) "
                "select user_id,id,'queued' from skive.drive_folders where id=%s and trashed_at is null "
                "on conflict (folder_id) do update set status='queued',error=null,updated_at=now() "
                "returning folder_id", (folder_id,),
            ).fetchone()
            if not row:
                raise ValueError(f"Folder not found: {folder_id}")
            print(f"queued {folder_id}")


if __name__ == "__main__":
    main(sys.argv[1:])
