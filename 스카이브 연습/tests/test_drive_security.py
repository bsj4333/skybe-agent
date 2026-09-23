"""Security regressions for the separate Supabase-backed drive."""

import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from psycopg.errors import InsufficientPrivilege

from skive.db import get_connection
from skive.server import app


def test_drive_requires_login():
    client = TestClient(app)
    assert client.get("/api/drive/items").status_code == 401
    assert client.post("/api/drive/folders", json={"name": "private"}).status_code == 401


def test_drive_rls_blocks_other_account():
    if not os.getenv("DATABASE_URL"):
        pytest.skip("Live Supabase database is not configured")
    conn = get_connection()
    try:
        row = conn.execute("select id from auth.users limit 1").fetchone()
        if not row:
            pytest.skip("No Supabase Auth user exists for the RLS test")
        owner = row[0]
        conn.execute("select set_config('request.jwt.claim.sub', %s, true)", (str(owner),))
        conn.execute("set local role authenticated")
        folder_id = conn.execute(
            "insert into skive.drive_folders(user_id,name) values (%s,%s) returning id",
            (owner, "temporary RLS check"),
        ).fetchone()[0]
        assert conn.execute("select id from skive.drive_folders where id=%s", (folder_id,)).fetchone()

        conn.execute("select set_config('request.jwt.claim.sub', %s, true)", (str(uuid4()),))
        assert conn.execute("select id from skive.drive_folders where id=%s", (folder_id,)).fetchone() is None
        assert conn.execute(
            "update skive.drive_folders set name='forbidden' where id=%s returning id", (folder_id,)
        ).fetchone() is None
    finally:
        conn.rollback()
        conn.close()


def test_storage_policy_accepts_only_registered_path():
    if not os.getenv("DATABASE_URL"):
        pytest.skip("Live Supabase database is not configured")
    conn = get_connection()
    try:
        row = conn.execute("select id from auth.users limit 1").fetchone()
        if not row:
            pytest.skip("No Supabase Auth user exists for the Storage policy test")
        owner = row[0]
        conn.execute("select set_config('request.jwt.claim.sub', %s, true)", (str(owner),))
        conn.execute("set local role authenticated")
        file_id = uuid4()
        registered_path = f"{owner}/{file_id}/original"
        conn.execute(
            "insert into skive.drive_files(id,user_id,name,storage_path,size_bytes) "
            "values (%s,%s,%s,%s,%s)", (file_id, owner, "policy.txt", registered_path, 3),
        )
        assert conn.execute(
            "insert into storage.objects(bucket_id,name,owner_id) values (%s,%s,%s) returning id",
            ("skive-originals", registered_path, str(owner)),
        ).fetchone()

        conn.execute("savepoint before_invalid_upload")
        with pytest.raises(InsufficientPrivilege):
            conn.execute(
                "insert into storage.objects(bucket_id,name,owner_id) values (%s,%s,%s)",
                ("skive-originals", f"{owner}/{uuid4()}/original", str(owner)),
            )
        conn.execute("rollback to savepoint before_invalid_upload")
    finally:
        conn.rollback()
        conn.close()
