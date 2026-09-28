"""Opt-in Edge journey through scoped chat, source inspection, essay and revision.

Run with localhost:8010: uv run --with playwright python tests/live_drive_workspace_ui.py
Uses a temporary Auth user and synthetic DB text, then removes both.
"""

import os
import secrets
import sys
import tempfile
from pathlib import Path
from uuid import UUID, uuid4

import httpx
from dotenv import load_dotenv
from playwright.sync_api import expect, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from skive.db import get_connection

load_dotenv(Path(__file__).resolve().parents[2] / ".env")


def main():
    url = os.environ["SUPABASE_URL"].rstrip("/")
    secret = os.environ["SUPABASE_SECRET_KEY"]
    headers = {"apikey": secret, "Authorization": f"Bearer {secret}"}
    email = f"skive-workspace-ui-{uuid4().hex}@example.invalid"
    password = secrets.token_urlsafe(24)
    user_id = None
    with httpx.Client(timeout=30) as remote:
        try:
            response = remote.post(f"{url}/auth/v1/admin/users", headers=headers,
                                   json={"email": email, "password": password,
                                         "email_confirm": True})
            response.raise_for_status()
            user_id = UUID((response.json().get("user") or response.json())["id"])
            folder_id, file_id = uuid4(), uuid4()
            with get_connection() as conn:
                conn.execute("insert into skive.drive_folders(id,user_id,name) values (%s,%s,'SCM class')",
                             (folder_id, user_id))
                conn.execute("insert into skive.drive_files(id,user_id,folder_id,name,storage_path,size_bytes,"
                             "upload_status,analysis_status) values (%s,%s,%s,'BOM notes.txt',%s,120,'uploaded','ready')",
                             (file_id, user_id, folder_id, f"{user_id}/{file_id}/original"))
                conn.execute("insert into skive.drive_file_chunks(user_id,file_id,file_version,chunk_index,location,text) "
                             "values (%s,%s,1,0,'line 1','SCM 강의에서 BOM은 제품을 구성하는 부품의 구조와 소요량을 나타낸다고 배웠다. 개인 과제 역할과 성과 수치는 기록되지 않았다.')",
                             (user_id, file_id))
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel="msedge", headless=True)
                page = browser.new_page(viewport={"width": 1440, "height": 900})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(os.getenv("SKIVE_TEST_BASE_URL", "http://127.0.0.1:8010/"),
                          wait_until="domcontentloaded")
                page.locator("#email").fill(email)
                page.locator("#password").fill(password)
                page.locator("#signin").click()
                page.locator("#app").wait_for(state="visible", timeout=30000)
                page.locator("#nav-chat").click()
                page.locator("#chat-scope").select_option(str(folder_id))
                page.locator("#chat-input").fill("SCM 강의에서 BOM을 무엇이라고 배웠지?")
                page.locator("#chat-send").click()
                expect(page.locator("#chat-log .chat-bubble.assistant")).to_contain_text("BOM", timeout=120000)
                expect(page.locator("#chat-log .citation-list")).to_contain_text("BOM notes.txt")
                page.screenshot(path=str(Path(tempfile.gettempdir()) / "skive-chat-connected.png"))
                page.locator("#chat-log .citation-list button").first.click()
                page.locator("#analysis-dialog").wait_for(state="visible")
                page.locator("#preview-extracted").click()
                expect(page.locator("#analysis-text")).to_contain_text("제품을 구성하는 부품")
                page.locator("#close-analysis").click()
                page.locator("#nav-essays").click()
                page.locator("#essay-job").fill("SCM 운영 직무에서 제품 구조와 부품 계획을 이해하는 사람을 찾습니다.")
                page.locator("#essay-question").fill("BOM을 학습한 경험을 설명해 주세요.")
                page.locator("#essay-scope").select_option(str(folder_id))
                page.locator("#essay-create").click()
                expect(page.locator("#essay-revise")).to_be_enabled(timeout=120000)
                assert page.locator("#essay-draft").inner_text().strip()
                expect(page.locator("#essay-sources")).to_contain_text("BOM notes.txt")
                page.locator("#essay-instruction").fill("첫 문장을 간결하게 고쳐줘")
                page.locator("#essay-revise").click()
                expect(page.locator("#message")).to_contain_text("수정 초안을 저장했습니다", timeout=120000)
                page.screenshot(path=str(Path(tempfile.gettempdir()) / "skive-essay-connected.png"))
                assert not errors, errors
                print("edge_scoped_chat=1 citation_opens_extracted_text=1 essay_create=1 essay_revise=1 page_errors=0")
                browser.close()
        finally:
            if user_id:
                remote.request("DELETE", f"{url}/auth/v1/admin/users/{user_id}",
                               headers=headers, json={"should_soft_delete": False}).raise_for_status()
                with get_connection() as conn:
                    assert conn.execute("select count(*) from skive.drive_chat_sessions where user_id=%s",
                                        (user_id,)).fetchone()[0] == 0
                print("temporary_account_and_workspace_rows_removed=1")


if __name__ == "__main__":
    main()
