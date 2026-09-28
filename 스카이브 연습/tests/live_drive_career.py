"""Opt-in two-account career memory and job conversation check.

Run: uv run python tests/live_drive_career.py
Creates disposable Supabase Auth users and removes them afterward.
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
from skive.drive_career import CareerReply
from skive.db import get_connection
from skive.server import app

load_dotenv(Path(__file__).resolve().parents[2] / ".env")


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
                email = f"skive-career-{uuid4().hex}@example.invalid"
                password = secrets.token_urlsafe(24)
                made = remote.post(f"{url}/auth/v1/admin/users", headers=admin_headers,
                                   json={"email": email, "password": password, "email_confirm": True})
                made.raise_for_status()
                user_id = UUID((made.json().get("user") or made.json())["id"])
                created.append(user_id)
                signed = remote.post(f"{url}/auth/v1/token?grant_type=password",
                                     headers={"apikey": public}, json={"email": email, "password": password})
                signed.raise_for_status()
                accounts.append({"id": user_id, "headers": {"Authorization": "Bearer " + signed.json()["access_token"]}})
            owner, other = accounts
            with TestClient(app) as client:
                job = client.post("/api/career/jobs", headers=owner["headers"],
                                  json={"title": "KT SCM 지원", "job_text": "SCM 직무 지원자 모집",
                                        "questions": ["SCM 강점 경험은?"]})
                assert job.status_code == 201, job.text
                job_id = job.json()["id"]
                detail = client.get(f"/api/career/jobs/{job_id}", headers=owner["headers"])
                assert detail.status_code == 200, detail.text
                essay_id = detail.json()["essays"][0]["id"]
                assert client.get(f"/api/career/jobs/{job_id}", headers=other["headers"]).status_code == 404
                assert client.get("/api/career/jobs", headers=other["headers"]).json() == []
                with patch("skive.drive_career._keywords", return_value=["SCM"]):
                    with patch("skive.drive_career._career_response",
                               return_value=CareerReply(action="ask", answer="확인이 필요해요.", question="경험은 무엇인가요?")):
                        asked = client.post(f"/api/career/jobs/{job_id}/messages", headers=owner["headers"],
                                            json={"essay_id": essay_id, "message": "초안 써줘"})
                    assert asked.status_code == 200 and asked.json()["action"] == "ask", asked.text
                    assert asked.json()["pending_question"]
                    confirmed = client.post(f"/api/career/jobs/{job_id}/messages", headers=owner["headers"],
                                            json={"essay_id": essay_id, "message": "제가 BOM 자료 정리를 맡았습니다.",
                                                  "answer_pending": True})
                    assert confirmed.status_code == 200, confirmed.text
                    memory = client.get("/api/career/memory", headers=owner["headers"]).json()
                    assert len(memory) == 1 and memory[0]["provenance"] == "user_statement"
                    assert memory[0]["status"] == "user_confirmed" and memory[0]["source_file_id"] is None
                    assert client.get("/api/career/memory", headers=other["headers"]).json() == []
                    chat = client.post("/api/workspace/chat/sessions", headers=owner["headers"], json={})
                    assert chat.status_code == 201, chat.text
                    def chat_from_memory(system, user):
                        assert "제가 BOM 자료 정리를 맡았습니다" in user
                        assert "사용자가 확인한 진술" in user
                        return "BOM 자료 정리를 맡았다고 말씀했어요. [본인 진술]"
                    with patch("skive.drive_workspace._keywords", return_value=["SCM"]), \
                         patch("skive.drive_workspace._generate", side_effect=chat_from_memory):
                        remembered = client.post(f"/api/workspace/chat/sessions/{chat.json()['id']}/messages",
                                                 headers=owner["headers"], json={"message": "SCM에서 내가 뭘 했지?"})
                    assert remembered.status_code == 200, remembered.text

                    def first_draft(context, **kwargs):
                        assert context["confirmed_user_statements_not_document_evidence"]
                        assert context["drive_file_evidence"] == ""
                        return CareerReply(action="draft", answer="본인 진술을 바탕으로 작성했습니다.",
                                           draft="저는 BOM 자료 정리를 맡았습니다. [본인 진술]")

                    with patch("skive.drive_career._career_response", side_effect=first_draft):
                        drafted = client.post(f"/api/career/jobs/{job_id}/messages", headers=owner["headers"],
                                              json={"essay_id": essay_id, "message": "이제 초안 써줘"})
                    assert drafted.status_code == 200 and drafted.json()["action"] == "draft", drafted.text
                    assert client.get(f"/api/career/jobs/{job_id}", headers=owner["headers"]).json()["essays"][0]["draft"]
                    versions = client.get(f"/api/career/jobs/{job_id}/essays/{essay_id}/versions",
                                          headers=owner["headers"])
                    assert versions.status_code == 200 and versions.json()[0]["revision_no"] == 1, versions.text
                    assert client.get(f"/api/career/jobs/{job_id}/essays/{essay_id}/versions",
                                      headers=other["headers"]).status_code == 404

                    second = client.post("/api/career/jobs", headers=owner["headers"],
                                         json={"title": "다른 SCM 공고", "questions": ["SCM 경험을 적어주세요"]})
                    assert second.status_code == 201, second.text
                    second_id = second.json()["id"]
                    second_essay = client.get(f"/api/career/jobs/{second_id}",
                                              headers=owner["headers"]).json()["essays"][0]["id"]

                    def reuse(context, **kwargs):
                        assert context["confirmed_user_statements_not_document_evidence"]
                        assert any("BOM 자료 정리" in item["draft"] for item in context["past_essays_for_wording_only"])
                        return CareerReply(action="discuss", answer="이전 글의 표현을 참고할 수 있습니다. 사실은 본인 진술입니다.")

                    with patch("skive.drive_career._career_response", side_effect=reuse):
                        reused = client.post(f"/api/career/jobs/{second_id}/messages", headers=owner["headers"],
                                             json={"essay_id": second_essay, "message": "전에 쓴 자소서 참고해줘"})
                    assert reused.status_code == 200, reused.text
                    assert reused.json()["references"]["past_essays"]
                    assert client.post(f"/api/career/jobs/{second_id}/messages", headers=other["headers"],
                                       json={"essay_id": second_essay, "message": "보여줘"}).status_code == 404
                    if "--real-ai" in sys.argv:
                        real = client.post(f"/api/career/jobs/{second_id}/messages", headers=owner["headers"],
                                           json={"essay_id": second_essay,
                                                 "message": "BOM 자료 정리를 맡은 경험으로 짧은 초안을 작성해줘. 이전 글은 표현만 참고해줘."})
                        assert real.status_code == 200, real.text
                        if real.json()["action"] == "draft":
                            assert "[본인 진술]" in real.json()["draft"]
                        print("real_model_action=", real.json()["action"],
                              "real_model_draft_chars=", len(real.json()["draft"]),
                              "clarification=", real.json()["pending_question"][:160])
            print("career_two_accounts_isolated=1 clarification=1 user_statement_provenance=1 prior_essay_reuse=1 general_chat_memory=1")
        finally:
            for user_id in created:
                remote.request("DELETE", f"{url}/auth/v1/admin/users/{user_id}", headers=admin_headers,
                               json={"should_soft_delete": False}).raise_for_status()
            with get_connection() as conn:
                for table in ("drive_memory_claims", "drive_job_workspaces", "drive_job_messages", "drive_essays", "drive_essay_versions"):
                    count = conn.execute(f"select count(*) from skive.{table} where user_id=any(%s::uuid[])",
                                         (created,)).fetchone()[0]
                    assert count == 0, (table, count)
            print("temporary_career_accounts_removed=1")


if __name__ == "__main__":
    main()
