"""Opt-in two-account activity/Drive RLS smoke test with no Storage upload.

Run: uv run python tests/live_drive_activities.py
Temporary Auth users and synthetic DB file records are removed afterward.
"""

import os
import secrets
import sys
from pathlib import Path
from uuid import UUID, uuid4
from unittest.mock import patch

import httpx
from dotenv import load_dotenv
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from skive.db import get_connection
from skive.drive_activity_analysis import run_activity_analysis_once
from skive.drive_db import user_connection
from skive.drive_reviewed_retrieval import reviewed_facts
from skive.drive_career import CareerReply
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
                email = f"skive-activity-{uuid4().hex}@example.invalid"
                password = secrets.token_urlsafe(24)
                response = remote.post(f"{url}/auth/v1/admin/users", headers=admin_headers,
                                       json={"email": email, "password": password,
                                             "email_confirm": True})
                response.raise_for_status()
                user_id = UUID((response.json().get("user") or response.json())["id"])
                created.append(user_id)
                signed = remote.post(f"{url}/auth/v1/token?grant_type=password",
                                     headers={"apikey": public},
                                     json={"email": email, "password": password})
                signed.raise_for_status()
                accounts.append({"id": user_id, "headers": {
                    "Authorization": "Bearer " + signed.json()["access_token"]}})
            owner, other = accounts
            with TestClient(app) as client:
                folder = client.post("/api/drive/folders", headers=owner["headers"],
                                     json={"name": "mixed folder"})
                assert folder.status_code == 201, folder.text
                folder_id = UUID(folder.json()["id"])
                file_id = uuid4()
                with get_connection() as conn:
                    conn.execute(
                        "insert into skive.drive_files(id,user_id,folder_id,name,storage_path,size_bytes,"
                        "upload_status,analysis_status,analyzed_at) "
                        "values (%s,%s,%s,'shared-report.pdf',%s,100,'uploaded','ready',now())",
                        (file_id, owner["id"], folder_id, f'{owner["id"]}/{file_id}/original'),
                    )
                    conn.execute(
                        "insert into skive.drive_file_chunks "
                        "(user_id,file_id,file_version,chunk_index,location,text) "
                        "values (%s,%s,1,1,'p.1','불량률 12%% 감소')", (owner["id"], file_id),
                    )
                course = client.post("/api/drive/activities", headers=owner["headers"],
                                     json={"title": "SCM course", "kind_tags": ["course"]})
                project = client.post("/api/drive/activities", headers=owner["headers"],
                                      json={"title": "team project", "kind_tags": ["team", "chemical"]})
                assert course.status_code == project.status_code == 201, (course.text, project.text)
                course_id, project_id = course.json()["id"], project.json()["id"]
                assert client.put(f"/api/drive/activities/{course_id}/files/{file_id}",
                                  headers=owner["headers"]).status_code == 200
                added = client.post(f"/api/drive/activities/{project_id}/folders/{folder_id}/files",
                                    headers=owner["headers"])
                assert added.status_code == 200 and added.json()["added"] == 1, added.text
                assert client.post(f"/api/drive/activities/{project_id}/folders/{folder_id}/files",
                                   headers=owner["headers"]).json()["added"] == 0
                assert len(client.get(f"/api/drive/activities/{course_id}",
                                      headers=owner["headers"]).json()["files"]) == 1
                assert len(client.get(f"/api/drive/activities/{project_id}",
                                      headers=owner["headers"]).json()["files"]) == 1
                listed = client.get("/api/drive/activities", headers=owner["headers"])
                assert listed.status_code == 200
                assert {item["id"]: item["file_count"] for item in listed.json()} == {
                    course_id: 1, project_id: 1}
                markdown = client.get(f"/api/drive/activities/{course_id}/markdown",
                                      headers=owner["headers"])
                assert markdown.status_code == 200
                assert "shared-report.pdf" in markdown.json()["markdown"]
                assert markdown.json()["filename"].endswith(".md")
                assert client.get(f"/api/drive/activities/{course_id}",
                                  headers=other["headers"]).status_code == 404
                assert client.put(f"/api/drive/activities/{course_id}/files/{file_id}",
                                  headers=other["headers"]).status_code == 404
                foreign = client.post("/api/drive/activities", headers=other["headers"],
                                      json={"title": "other account"})
                assert foreign.status_code == 201
                assert client.put(f"/api/drive/activities/{foreign.json()['id']}/files/{file_id}",
                                  headers=other["headers"]).status_code == 404
                suggestion = client.get("/api/drive/activities/suggestions", headers=owner["headers"])
                assert suggestion.status_code == 200, suggestion.text
                assert client.post(f"/api/drive/activities/{foreign.json()['id']}/files",
                                   headers=other["headers"],
                                   json={"file_ids": [str(file_id)]}).status_code == 404
                batch = client.post(f"/api/drive/activities/{course_id}/files",
                                    headers=owner["headers"],
                                    json={"file_ids": [str(file_id), str(file_id)]})
                assert batch.status_code == 200 and batch.json()["selected"] == 1, batch.text
                requested = client.post(f"/api/drive/activities/{course_id}/analyze",
                                        headers=owner["headers"])
                assert requested.status_code == 200 and requested.json()["status"] == "queued"

                def fake_propose(batch, title):
                    ref = next(iter(batch[0].values()))
                    return [{"kind": "result", "content": "불량률 12% 감소", "subject": "unclear",
                             "file": ref["file"], "row": ref["row"],
                             "quote": "불량률 12% 감소", "check": {"ok": True}}]

                with patch("skive.drive_activity_analysis.propose", side_effect=fake_propose):
                    assert run_activity_analysis_once()
                facts_response = client.get(f"/api/drive/activities/{course_id}/facts",
                                            headers=owner["headers"])
                assert facts_response.status_code == 200, facts_response.text
                fact = facts_response.json()["facts"][0]
                assert fact["review_state"] == "candidate" and not fact["stale"]
                assert client.get(f"/api/drive/activities/{course_id}/facts",
                                  headers=other["headers"]).status_code == 404
                denied = client.patch(f"/api/drive/activities/{course_id}/facts/{fact['id']}",
                                      headers=owner["headers"],
                                      json={"review_state": "confirmed", "subject": "user"})
                assert denied.status_code == 422
                confirmed = client.patch(f"/api/drive/activities/{course_id}/facts/{fact['id']}",
                                         headers=owner["headers"],
                                         json={"review_state": "confirmed", "subject": "user",
                                               "review_note": "내가 직접 맡은 부분을 확인함"})
                assert confirmed.status_code == 200, confirmed.text
                with user_connection(owner["id"]) as conn:
                    assert len(reviewed_facts(conn, ["불량률"])) == 1
                with user_connection(other["id"]) as conn:
                    assert reviewed_facts(conn, ["불량률"]) == []
                chat = client.post("/api/workspace/chat/sessions", headers=owner["headers"], json={})
                assert chat.status_code == 201, chat.text

                def chat_reply(system, user):
                    assert "사용자 검토를 마친 활동 사실" in user
                    assert "불량률 12% 감소" in user
                    return "확인된 활동 결과는 불량률 12% 감소입니다. [활동 사실 1]"

                with patch("skive.drive_workspace._keywords", return_value=["불량률"]), \
                     patch("skive.drive_workspace._generate", side_effect=chat_reply):
                    chatted = client.post(
                        f"/api/workspace/chat/sessions/{chat.json()['id']}/messages",
                        headers=owner["headers"], json={"message": "불량률 결과를 알려줘"},
                    )
                assert chatted.status_code == 200, chatted.text
                assert any(source.get("reviewed_fact_id") for source in chatted.json()["citations"])
                job = client.post("/api/career/jobs", headers=owner["headers"],
                                  json={"title": "검증 공고", "questions": ["결과를 설명해 주세요"]})
                assert job.status_code == 201, job.text
                job_id = job.json()["id"]
                essay_id = client.get(f"/api/career/jobs/{job_id}",
                                      headers=owner["headers"]).json()["essays"][0]["id"]

                def career_reply(context, **kwargs):
                    assert context["human_reviewed_activity_facts_with_document_sources"]
                    return CareerReply(action="draft", answer="확인된 활동 사실을 사용했습니다.",
                                       draft="불량률 12% 감소를 확인했습니다. [활동 사실 1]")

                with patch("skive.drive_career._keywords", return_value=["불량률"]), \
                     patch("skive.drive_career._career_response", side_effect=career_reply), \
                     patch("skive.drive_career._repair_missing_attribution",
                           side_effect=lambda draft, sources, memories: draft):
                    drafted = client.post(f"/api/career/jobs/{job_id}/messages",
                                          headers=owner["headers"],
                                          json={"essay_id": essay_id,
                                                "message": "불량률 결과로 초안을 써줘"})
                assert drafted.status_code == 200 and drafted.json()["action"] == "draft", drafted.text
                assert drafted.json()["references"]["activity_facts"]
                snapshot = client.post(f"/api/drive/activities/{course_id}/reviewed-markdown",
                                       headers=owner["headers"])
                assert snapshot.status_code == 200, snapshot.text
                assert "불량률 12% 감소" in snapshot.json()["snapshot"]["markdown"]
                assert not client.get(f"/api/drive/activities/{course_id}/reviewed-markdown",
                                      headers=owner["headers"]).json()["needs_refresh"]
                renamed = client.patch(f"/api/drive/activities/{course_id}",
                                       headers=owner["headers"], json={"title": "SCM renamed"})
                assert renamed.status_code == 200, renamed.text
                assert client.get(f"/api/drive/activities/{course_id}/reviewed-markdown",
                                  headers=owner["headers"]).json()["needs_refresh"]
                assert client.patch(f"/api/drive/activities/{course_id}",
                                    headers=owner["headers"],
                                    json={"title": "SCM course"}).status_code == 200
                assert client.get(f"/api/drive/activities/{course_id}/reviewed-markdown",
                                  headers=other["headers"]).status_code == 404
                assert client.delete(f"/api/drive/activities/{course_id}/files/{file_id}",
                                     headers=owner["headers"]).status_code == 200
                assert len(client.get(f"/api/drive/activities/{project_id}",
                                      headers=owner["headers"]).json()["files"]) == 1
                updated = client.patch(f"/api/drive/activities/{project_id}",
                                       headers=owner["headers"],
                                       json={"title": "reactor experiment", "kind_tags": ["chemical", "experiment"]})
                assert updated.status_code == 200 and updated.json()["title"] == "reactor experiment"
                with get_connection() as conn:
                    conn.execute("update skive.drive_files set analyzed_at=now()+interval '1 second' "
                                 "where id=%s", (file_id,))
                stale = client.get(f"/api/drive/activities/{course_id}/facts",
                                   headers=owner["headers"]).json()["facts"][0]
                assert stale["stale"]
                with user_connection(owner["id"]) as conn:
                    assert reviewed_facts(conn, ["불량률"]) == []
                assert client.get(f"/api/drive/activities/{course_id}/reviewed-markdown",
                                  headers=owner["headers"]).json()["needs_refresh"]
                assert client.patch(f"/api/drive/activities/{course_id}/facts/{fact['id']}",
                                    headers=owner["headers"],
                                    json={"review_state": "confirmed", "subject": "user",
                                          "review_note": "다시 확인"}).status_code == 409
                print("two_accounts_isolated=1 shared_file_in_two_activities=1 folder_link_idempotent=1 "
                      "unlink_keeps_original_and_other_activity=1 markdown_index=1 "
                      "fact_review=1 source_stale=1 markdown_stale=1 "
                      "reviewed_chat_citation=1 reviewed_career_draft=1")
        finally:
            for user_id in created:
                remote.request("DELETE", f"{url}/auth/v1/admin/users/{user_id}",
                               headers=admin_headers,
                               json={"should_soft_delete": False}).raise_for_status()
            with get_connection() as conn:
                remaining = conn.execute("select count(*) from skive.drive_activities "
                                         "where user_id = any(%s::uuid[])", (created,)).fetchone()[0]
                assert remaining == 0
            print("temporary_accounts_and_activity_rows_removed=1")


if __name__ == "__main__":
    main()
