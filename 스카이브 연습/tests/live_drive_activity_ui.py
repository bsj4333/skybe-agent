"""Opt-in Edge check of activity create, folder link and Markdown download.

Run with localhost:8010 serving SKIVE:
uv run --with playwright python tests/live_drive_activity_ui.py
Creates only synthetic DB metadata and removes the temporary Auth account.
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
    email = f"skive-activity-ui-{uuid4().hex}@example.invalid"
    password = secrets.token_urlsafe(24)
    user_id = None
    with httpx.Client(timeout=30) as remote:
        try:
            response = remote.post(f"{url}/auth/v1/admin/users", headers=headers,
                                   json={"email": email, "password": password,
                                         "email_confirm": True})
            response.raise_for_status()
            user_id = UUID((response.json().get("user") or response.json())["id"])
            folder_id, sibling_id, child_id, file_id = uuid4(), uuid4(), uuid4(), uuid4()
            with get_connection() as conn:
                conn.execute("insert into skive.drive_folders(id,user_id,name) values (%s,%s,'practice folder')",
                             (folder_id, user_id))
                conn.execute("insert into skive.drive_folders(id,user_id,name) values (%s,%s,'another folder')",
                             (sibling_id, user_id))
                conn.execute("insert into skive.drive_folders(id,user_id,parent_id,name) values (%s,%s,%s,'child folder')",
                             (child_id, user_id, folder_id))
                conn.execute(
                    "insert into skive.drive_files(id,user_id,folder_id,name,storage_path,size_bytes,"
                    "upload_status,analysis_status) "
                    "values (%s,%s,%s,'course-notes.pdf',%s,100,'uploaded','ready')",
                    (file_id, user_id, folder_id, f"{user_id}/{file_id}/original"),
                )
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel="msedge", headless=True)
                page = browser.new_page(viewport={"width": 1440, "height": 900}, accept_downloads=True)
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                def handle_dialog(dialog):
                    if dialog.type == "prompt":
                        dialog.accept("scratch renamed" if dialog.message == "새 이름" else "scratch")
                    else:
                        dialog.accept()
                page.on("dialog", handle_dialog)
                page.goto(os.getenv("SKIVE_TEST_BASE_URL", "http://127.0.0.1:8010/"),
                          wait_until="domcontentloaded")
                page.locator("#email").fill(email)
                page.locator("#password").fill(password)
                page.locator("#signin").click()
                page.locator("#app").wait_for(state="visible", timeout=30000)
                expect(page.locator("#items .drive-row")).to_have_count(2, timeout=15000)
                assert page.locator("#items .name-text").all_inner_texts() == ["another folder", "practice folder"]
                page.locator("#new-menu").click()
                expect(page.locator("#new-popover")).to_be_visible()
                assert page.locator("#new-popover button").count() == 3
                page.keyboard.press("Escape")
                page.locator("#items .drive-row").filter(has_text="practice folder").locator(".row-more").click()
                expect(page.locator("#row-menu")).to_contain_text("이름 변경")
                expect(page.locator("#row-menu")).to_contain_text("이동")
                page.keyboard.press("Escape")
                page.locator("#search").fill("practice")
                page.locator("#search").press("Enter")
                expect(page.locator("#items .drive-row")).to_have_count(1)
                page.locator("#search").fill("")
                page.locator("#search").press("Enter")
                expect(page.locator("#items .drive-row")).to_have_count(2)
                page.locator('[data-sort="name"]').click()
                assert page.locator("#items .name-text").all_inner_texts() == ["practice folder", "another folder"]
                page.locator("#items .name-button").filter(has_text="practice folder").click()
                page.locator("#items .name-button").filter(has_text="child folder").click()
                expect(page.locator("#breadcrumbs button")).to_have_text(["내 드라이브", "practice folder", "child folder"])
                page.locator("#breadcrumbs button").filter(has_text="practice folder").click()
                expect(page.locator("#items .drive-row")).to_have_count(2)
                assert page.get_by_text("상위 폴더").count() == 0
                assert page.get_by_text("경험 초안").count() == 0
                page.locator("#brand-home").click()
                expect(page.locator("#breadcrumbs button")).to_have_text(["내 드라이브"])
                page.screenshot(path=str(Path(tempfile.gettempdir()) / "skive-drive-redesign.png"))
                page.locator("#nav-profile").click()
                expect(page.locator("#profile-section")).to_be_visible()
                page.locator("#profile-name").fill("Temporary tester")
                page.locator("#profile-save").click()
                expect(page.locator("#message")).to_contain_text("프로필을 저장했습니다")
                page.locator("#nav-chat").click()
                expect(page.locator("#chat-section")).to_be_visible()
                expect(page.locator("#chat-scope option")).to_have_count(4)
                page.locator("#nav-essays").click()
                expect(page.locator("#essays-section")).to_be_visible()
                page.locator("#home").click()
                expect(page.locator("#drive-section")).to_be_visible()
                page.locator("#new-menu").click()
                page.locator("#menu-new-folder").click()
                page.locator("#items .name-text").filter(has_text="scratch").wait_for()
                page.locator("#items .drive-row").filter(has_text="scratch").locator(".row-more").click()
                page.locator("#row-menu").get_by_text("이름 변경").click()
                page.locator("#items .name-text").filter(has_text="scratch renamed").wait_for()
                page.locator("#items .drive-row").filter(has_text="scratch renamed").locator(".row-more").click()
                page.locator("#row-menu").get_by_text("휴지통으로 이동").click()
                expect(page.locator("#items .name-text").filter(has_text="scratch renamed")).to_have_count(0)
                page.locator("#items .name-button").filter(has_text="practice folder").click()
                page.locator("#open-activities").click()
                page.locator("#activities-dialog").wait_for(state="visible")
                page.locator("#activity-name").fill("SCM course")
                page.locator("#activity-tags").fill("course, supply chain")
                page.locator("#create-activity").click()
                page.locator("#activity-detail-dialog").wait_for(state="visible")
                assert "SCM course" in page.locator("#activity-detail-title").inner_text()
                page.locator("#activity-link-folder").click()
                expect(page.locator("#activity-files")).to_contain_text("course-notes.pdf", timeout=15000)
                with page.expect_download() as download_info:
                    page.locator("#activity-download").click()
                download = download_info.value
                assert download.suggested_filename.endswith(".md")
                content = Path(download.path()).read_text(encoding="utf-8")
                assert "course-notes.pdf" in content and "SCM course" in content
                page.locator("#activity-files button").first.click()
                expect(page.locator("#activity-files")).to_contain_text("연결된 파일이 없습니다", timeout=15000)
                assert not errors, errors
                print("edge_drive_sort=1 breadcrumb=1 brand_home=1 search=1 menu=1 create_rename_trash=1 activity_create=1 folder_link=1 markdown_download=1 unlink=1 page_errors=0")
                browser.close()
        finally:
            if user_id:
                remote.request("DELETE", f"{url}/auth/v1/admin/users/{user_id}",
                               headers=headers, json={"should_soft_delete": False}).raise_for_status()
                with get_connection() as conn:
                    assert conn.execute("select count(*) from skive.drive_activities where user_id=%s",
                                        (user_id,)).fetchone()[0] == 0
                print("temporary_account_and_metadata_removed=1")


if __name__ == "__main__":
    main()
