"""Browser smoke test for the posting conversation and clarification UI.

Run: $env:SKIVE_TEST_BASE_URL='http://127.0.0.1:8012/'
     uv run --with playwright python tests/live_drive_career_ui.py
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

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def main():
    url = os.environ["SUPABASE_URL"].rstrip("/")
    secret = os.environ["SUPABASE_SECRET_KEY"]
    headers = {"apikey": secret, "Authorization": f"Bearer {secret}"}
    email = f"skive-career-ui-{uuid4().hex}@example.invalid"
    password = secrets.token_urlsafe(24)
    user_id = None
    with httpx.Client(timeout=30) as remote:
        try:
            response = remote.post(f"{url}/auth/v1/admin/users", headers=headers,
                                   json={"email": email, "password": password, "email_confirm": True})
            response.raise_for_status()
            user_id = UUID((response.json().get("user") or response.json())["id"])
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel="msedge", headless=True)
                page = browser.new_page(viewport={"width": 1440, "height": 900})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(os.getenv("SKIVE_TEST_BASE_URL", "http://127.0.0.1:8012/"),
                          wait_until="domcontentloaded")
                page.locator("#email").fill(email)
                page.locator("#password").fill(password)
                page.locator("#signin").click()
                page.locator("#app").wait_for(state="visible", timeout=30000)
                page.locator("#nav-essays").click()
                expect(page.locator("#career-section")).to_be_visible()
                page.locator("#career-new-toggle").click()
                page.locator("#career-title").fill("기아 SCM 공고")
                page.locator("#career-job-text").fill("SCM 관련 역량이 있는 지원자를 찾습니다.")
                page.locator("#career-questions").fill("본인의 SCM 경험을 설명하세요.")
                page.locator("#career-new-form button[type=submit]").click()
                expect(page.locator("#career-job-title")).to_have_text("기아 SCM 공고", timeout=30000)
                page.locator("#career-message-input").fill("이 문항 초안 써줘")
                page.locator("#career-send").click()
                expect(page.locator("#career-pending")).to_contain_text("본인이 직접", timeout=120000)
                page.locator("#career-message-input").fill("저는 BOM 과제에서 자료 정리를 맡았습니다.")
                page.locator("#career-answer").click()
                expect(page.locator("#career-messages")).to_contain_text("본인 진술로 저장", timeout=30000)
                expect(page.locator("#career-pending")).to_be_hidden()
                page.locator("#nav-profile").click()
                expect(page.locator("#profile-memory-list")).to_contain_text("BOM 과제에서 자료 정리", timeout=30000)
                page.screenshot(path=str(Path(tempfile.gettempdir()) / "skive-career-ui.png"))
                assert not errors, errors
                print("edge_job_create=1 clarification=1 answer_saved=1 page_errors=0")
                browser.close()
        finally:
            if user_id:
                remote.request("DELETE", f"{url}/auth/v1/admin/users/{user_id}",
                               headers=headers, json={"should_soft_delete": False}).raise_for_status()
                with get_connection() as conn:
                    assert conn.execute("select count(*) from skive.drive_job_workspaces where user_id=%s",
                                        (user_id,)).fetchone()[0] == 0
                print("temporary_career_ui_account_removed=1")


if __name__ == "__main__":
    main()
