"""Opt-in Edge smoke test: suggestion -> split -> review -> Markdown -> stale.

Run with the local server: uv run --with playwright python tests/live_drive_activity_pipeline_ui.py
Only synthetic DB metadata/chunks are created; no Storage bytes are uploaded.
"""

import os
import secrets
import sys
from pathlib import Path
from uuid import UUID, uuid4

import httpx
from dotenv import load_dotenv
from fastapi.testclient import TestClient
from playwright.sync_api import expect, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from skive.db import get_connection
from skive.server import app

load_dotenv(Path(__file__).resolve().parents[2] / ".env")


def main():
    url = os.environ["SUPABASE_URL"].rstrip("/")
    secret = os.environ["SUPABASE_SECRET_KEY"]
    public = os.environ.get("SUPABASE_PUBLISHABLE_KEY") or os.environ["SUPABASE_ANON_KEY"]
    admin = {"apikey": secret, "Authorization": f"Bearer {secret}"}
    email = f"skive-activity-ui-{uuid4().hex}@example.invalid"
    password = secrets.token_urlsafe(24)
    user_id = None
    with httpx.Client(timeout=30) as remote:
        try:
            created = remote.post(f"{url}/auth/v1/admin/users", headers=admin,
                                  json={"email": email, "password": password, "email_confirm": True})
            created.raise_for_status()
            user_id = UUID((created.json().get("user") or created.json())["id"])
            signed = remote.post(f"{url}/auth/v1/token?grant_type=password",
                                 headers={"apikey": public},
                                 json={"email": email, "password": password})
            signed.raise_for_status()
            headers = {"Authorization": "Bearer " + signed.json()["access_token"]}
            with TestClient(app) as client:
                folder = client.post("/api/drive/folders", headers=headers,
                                     json={"name": "UI 검증 프로젝트"})
                assert folder.status_code == 201, folder.text
                folder_id = UUID(folder.json()["id"])
            file_ids = [uuid4(), uuid4()]
            with get_connection() as conn:
                for index, file_id in enumerate(file_ids, 1):
                    conn.execute(
                        "insert into skive.drive_files(id,user_id,folder_id,name,storage_path,"
                        "size_bytes,upload_status,analysis_status,analyzed_at) "
                        "values (%s,%s,%s,%s,%s,100,'uploaded','ready',now())",
                        (file_id, user_id, folder_id, f"report-{index}.txt",
                         f"{user_id}/{file_id}/original"),
                    )
                    conn.execute(
                        "insert into skive.drive_file_chunks "
                        "(user_id,file_id,file_version,chunk_index,location,text) "
                        "values (%s,%s,1,1,'L1-1',%s)",
                        (user_id, file_id, f"불량률 {index*12}% 감소"),
                    )
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel="msedge", headless=True)
                page = browser.new_page(viewport={"width": 1280, "height": 850})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(os.getenv("SKIVE_TEST_BASE_URL", "http://127.0.0.1:8010/"),
                          wait_until="domcontentloaded")
                page.locator("#email").fill(email)
                page.locator("#password").fill(password)
                page.locator("#signin").click()
                page.locator("#app").wait_for(state="visible", timeout=30000)
                page.locator("#open-activities").click()
                suggestion = page.locator(".activity-suggestion", has_text="UI 검증 프로젝트")
                suggestion.wait_for(timeout=30000)
                suggestion.locator("summary").click()
                checks = suggestion.locator(".suggestion-files input[type=checkbox]")
                expect(checks).to_have_count(2)
                selected_id = UUID(checks.first.input_value())
                checks.last.uncheck()
                suggestion.get_by_role("button", name="선택한 파일 연결").click()
                page.locator("#activity-detail-dialog").wait_for(state="visible")
                expect(page.locator("#activity-files .activity-row")).to_have_count(1)
                activity_id = None
                with get_connection() as conn:
                    activity_id = conn.execute(
                        "select activity_id from skive.drive_activity_files where file_id=%s",
                        (selected_id,),
                    ).fetchone()[0]
                    analyzed = conn.execute(
                        "select analyzed_at from skive.drive_files where id=%s", (selected_id,),
                    ).fetchone()[0]
                    conn.execute(
                        "insert into skive.drive_activity_facts "
                        "(user_id,activity_id,kind,content,subject,source_file_id,"
                        "source_file_version,source_analyzed_at,source_chunk_index,"
                        "source_location,source_quote,evidence_check) "
                        "values (%s,%s,'result',%s,'unclear',%s,1,%s,1,'L1-1',%s,'{}'::jsonb)",
                        (user_id, activity_id, "불량률 12% 감소" if selected_id == file_ids[0] else "불량률 24% 감소",
                         selected_id, analyzed,
                         "불량률 12% 감소" if selected_id == file_ids[0] else "불량률 24% 감소"),
                    )
                page.get_by_role("button", name="결과 새로고침").click()
                fact = page.locator(".activity-fact")
                fact.wait_for(timeout=30000)
                fact.locator("select").select_option("user")
                fact.locator("input").fill("평가 코드를 직접 작성하고 수치를 확인함")
                fact.get_by_role("button", name="확인", exact=True).click()
                expect(fact.locator(".muted")).to_contain_text("confirmed")
                page.get_by_role("button", name="확인된 내용으로 MD 만들기").click()
                expect(page.locator("#activity-reviewed-md pre")).to_contain_text("불량률")
                assert "파일 " in page.locator("#activity-reviewed-md pre").inner_text()
                with get_connection() as conn:
                    conn.execute("update skive.drive_files set analyzed_at=now()+interval '1 second' "
                                 "where id=%s", (selected_id,))
                page.get_by_role("button", name="결과 새로고침").click()
                expect(page.locator("#activity-reviewed-md .muted")).to_contain_text("갱신 필요")
                assert not errors, errors
                browser.close()
            print("edge_suggestion_split=1 fact_review=1 markdown=1 stale_banner=1")
        finally:
            if user_id:
                remote.request("DELETE", f"{url}/auth/v1/admin/users/{user_id}",
                               headers=admin, json={"should_soft_delete": False}).raise_for_status()
            print("temporary_account_removed=1")


if __name__ == "__main__":
    main()
