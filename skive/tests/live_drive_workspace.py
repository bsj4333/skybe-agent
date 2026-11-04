"""Opt-in two-account profile/chat/essay isolation check with synthetic source text.

Run: uv run python tests/live_drive_workspace.py
Creates temporary Auth users and removes them and all related rows afterward.
"""

import os
import secrets
import sys
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

import httpx
from dotenv import load_dotenv
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from skive.db import get_connection
from skive.drive_db import user_connection
from skive.drive_workspace import _chat_memory
from skive.server import app

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def main():
    url = os.environ["SUPABASE_URL"].rstrip("/")
    secret = os.environ["SUPABASE_SECRET_KEY"]
    public = os.environ.get("SUPABASE_PUBLISHABLE_KEY") or os.environ["SUPABASE_ANON_KEY"]
    admin_headers = {"apikey": secret, "Authorization": f"Bearer {secret}"}
    created = []
    with httpx.Client(timeout=30) as remote:
        try:
            accounts = []
            for _ in range(2):
                email = f"skive-workspace-{uuid4().hex}@example.invalid"
                password = secrets.token_urlsafe(24)
                made = remote.post(f"{url}/auth/v1/admin/users", headers=admin_headers,
                                   json={"email": email, "password": password,
                                         "email_confirm": True})
                made.raise_for_status()
                user_id = UUID((made.json().get("user") or made.json())["id"])
                created.append(user_id)
                signed = remote.post(f"{url}/auth/v1/token?grant_type=password",
                                     headers={"apikey": public},
                                     json={"email": email, "password": password})
                signed.raise_for_status()
                accounts.append({"id": user_id, "headers": {
                    "Authorization": "Bearer " + signed.json()["access_token"]}})
            owner, other = accounts
            folder_id, child_id, file_id = uuid4(), uuid4(), uuid4()
            with get_connection() as conn:
                conn.execute("insert into skive.drive_folders(id,user_id,name) values (%s,%s,'SCM course')",
                             (folder_id, owner["id"]))
                conn.execute("insert into skive.drive_folders(id,user_id,parent_id,name) "
                             "values (%s,%s,%s,'week 3')", (child_id, owner["id"], folder_id))
                conn.execute("insert into skive.drive_files(id,user_id,folder_id,name,storage_path,size_bytes,"
                             "upload_status,analysis_status) values (%s,%s,%s,'BOM notes.txt',%s,120,'uploaded','ready')",
                             (file_id, owner["id"], child_id, f'{owner["id"]}/{file_id}/original'))
                conn.execute("insert into skive.drive_file_chunks(user_id,file_id,file_version,chunk_index,location,text) "
                             "values (%s,%s,1,0,'line 1','SCM 수업에서 BOM은 제품 구조와 부품 소요량을 나타낸다고 학습했다. 학습자의 과제 역할은 기록되지 않았다.')",
                             (owner["id"], file_id))
            with TestClient(app) as client:
                saved = client.put("/api/workspace/profile", headers=owner["headers"],
                                   json={"display_name": "Owner", "major": "산업공학", "career_goal": "SCM"})
                assert saved.status_code == 200, saved.text
                assert client.get("/api/workspace/profile", headers=owner["headers"]).json()["display_name"] == "Owner"
                assert client.get("/api/workspace/profile", headers=other["headers"]).json()["display_name"] == ""
                folders = client.get("/api/workspace/folders", headers=owner["headers"])
                assert folders.status_code == 200 and len(folders.json()) == 2, folders.text
                assert client.get("/api/workspace/folders", headers=other["headers"]).json() == []
                session = client.post("/api/workspace/chat/sessions", headers=owner["headers"],
                                      json={"folder_id": str(folder_id)})
                assert session.status_code == 201, session.text
                session_id = session.json()["id"]
                assert client.get(f"/api/workspace/chat/sessions/{session_id}",
                                  headers=other["headers"]).status_code == 404
                assert client.post("/api/workspace/chat/sessions", headers=other["headers"],
                                   json={"folder_id": str(folder_id)}).status_code == 404
                with patch("skive.drive_workspace._keywords", return_value=["BOM"]), \
                     patch("skive.drive_workspace._generate", return_value="BOM은 부품 소요 구조입니다. [1]"):
                    message = client.post(f"/api/workspace/chat/sessions/{session_id}/messages",
                                          headers=owner["headers"], json={"message": "BOM 배웠지?"})
                    assert message.status_code == 200, message.text
                    assert message.json()["citations"][0]["file_id"] == str(file_id)
                    global_session = client.post("/api/workspace/chat/sessions", headers=owner["headers"],
                                                 json={"folder_id": None})
                    assert global_session.status_code == 201, global_session.text
                    global_id = global_session.json()["id"]
                    global_answer = client.post(
                        f"/api/workspace/chat/sessions/{global_id}/messages",
                        headers=owner["headers"], json={"message": "BOM 복기"})
                    assert global_answer.status_code == 200 and global_answer.json()["citations"], global_answer.text
                    with user_connection(owner["id"]) as conn:
                        remembered = _chat_memory(conn, ["BOM"], UUID(global_id))
                        assert any("BOM 배웠지" in item["content"] for item in remembered)
                    assert client.post(f"/api/workspace/chat/sessions/{session_id}/messages",
                                       headers=other["headers"], json={"message": "BOM"}).status_code == 404
                    essay = client.post("/api/workspace/essays", headers=owner["headers"],
                                        json={"folder_id": str(folder_id),
                                              "job_text": "SCM 직무에서 제품 구조를 이해하는 인재를 찾습니다.",
                                              "question": "BOM을 공부한 경험을 말하세요."})
                    assert essay.status_code == 201, essay.text
                    essay_id = essay.json()["id"]
                    assert essay.json()["review_status"] == "needs_review"
                    assert client.get(f"/api/workspace/essays/{essay_id}",
                                      headers=other["headers"]).status_code == 404
                    revised = client.post(f"/api/workspace/essays/{essay_id}/revise",
                                          headers=owner["headers"],
                                          json={"instruction": "BOM을 더 간단히"})
                    assert revised.status_code == 200 and revised.json()["revision_count"] == 1, revised.text
                if "--real-ai" in sys.argv:
                    real_session = client.post("/api/workspace/chat/sessions", headers=owner["headers"],
                                               json={"folder_id": str(folder_id)})
                    real_session.raise_for_status()
                    real = client.post(
                        f"/api/workspace/chat/sessions/{real_session.json()['id']}/messages",
                        headers=owner["headers"], json={"message": "SCM 수업에서 BOM에 대해 무엇을 배웠지?"},
                    )
                    assert real.status_code == 200, real.text
                    assert real.json()["citations"] and "BOM" in real.json()["content"], real.text
                    print("real_model_chat=1 sources=", len(real.json()["citations"]))
            print("two_accounts_isolated=1 profile=1 recursive_folder_search=1 global_search=1 prior_chat_memory=1 cited_chat=1 essay_create_revise=1")
        finally:
            for user_id in created:
                remote.request("DELETE", f"{url}/auth/v1/admin/users/{user_id}",
                               headers=admin_headers,
                               json={"should_soft_delete": False}).raise_for_status()
            with get_connection() as conn:
                for table in ("drive_profiles", "drive_chat_sessions", "drive_chat_messages", "drive_essays"):
                    count = conn.execute(f"select count(*) from skive.{table} where user_id=any(%s::uuid[])",
                                         (created,)).fetchone()[0]
                    assert count == 0, (table, count)
            print("temporary_accounts_and_workspace_rows_removed=1")


if __name__ == "__main__":
    main()
