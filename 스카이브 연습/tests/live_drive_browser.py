"""Opt-in browser smoke test against localhost and a temporary Supabase account.

Run with ``uv run --with playwright python tests/live_drive_browser.py``.
"""

import json
import os
import secrets
import tempfile
import time
from pathlib import Path
from uuid import uuid4

import httpx
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright


load_dotenv()


def main() -> None:
    url = os.environ["SUPABASE_URL"].rstrip("/")
    secret = os.environ["SUPABASE_SECRET_KEY"]
    headers = {"apikey": secret, "Authorization": f"Bearer {secret}"}
    email = f"skive-browser-{uuid4().hex}@example.invalid"
    password = secrets.token_urlsafe(24)
    user_id = None
    timings = {}
    with httpx.Client(timeout=30) as remote:
        try:
            created = remote.post(f"{url}/auth/v1/admin/users", headers=headers,
                                  json={"email": email, "password": password, "email_confirm": True})
            created.raise_for_status()
            user_id = (created.json().get("user") or created.json())["id"]
            with tempfile.TemporaryDirectory(prefix="skive-browser-") as temp:
                folder = Path(temp) / "브라우저 테스트"
                folder.mkdir()
                (folder / "notes.txt").write_text("SCM 수업: BOM과 CAPA를 공부했다. 본인 역할은 확인 필요.\n",
                                                    encoding="utf-8")
                (folder / "metrics.csv").write_text("model,f1\nbase,0.71\ntrial,0.86\n",
                                                      encoding="utf-8")
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(channel="msedge", headless=True)
                    page = browser.new_page(viewport={"width": 1440, "height": 900}, accept_downloads=True)
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.goto(os.getenv("SKIVE_TEST_BASE_URL", "http://localhost:8010/"),
                              wait_until="domcontentloaded")
                    page.locator("#email").fill(email)
                    page.locator("#password").fill(password)
                    started = time.monotonic()
                    page.locator("#signin").click()
                    page.locator("#app").wait_for(state="visible", timeout=30000)
                    timings["login_seconds"] = round(time.monotonic() - started, 2)
                    started = time.monotonic()
                    page.locator("#folder-input").set_input_files(str(folder))
                    page.get_by_text("브라우저 테스트", exact=False).first.wait_for(timeout=30000)
                    timings["folder_appears_seconds"] = round(time.monotonic() - started, 2)
                    page.locator("#upload-title").get_by_text("업로드 완료").wait_for(timeout=90000)
                    timings["two_files_uploaded_seconds"] = round(time.monotonic() - started, 2)
                    assert "경과" in page.locator("#upload-detail").inner_text()
                    page.locator("#folders .name").filter(has_text="브라우저 테스트").click()
                    page.get_by_text("2개 파일", exact=False).wait_for(timeout=30000)
                    for _ in range(30):
                        if page.locator("#files .file-row").count() == 2 and page.get_by_text("텍스트 추출 완료").count() == 2:
                            break
                        page.wait_for_timeout(1000)
                        page.locator("#refresh").click()
                    page.locator("#files .file-row").filter(has_text="notes.txt").get_by_role("button", name="원문/색인").click()
                    page.locator("#analysis-dialog").wait_for(state="visible")
                    text = page.locator("#analysis-text").inner_text()
                    assert "BOM" in text and "위치 색인" in text, text[:300]
                    page.locator("#close-analysis").click()
                    page.locator("#folder-summary").click()
                    page.locator("#summary-dialog").wait_for(state="visible")
                    assert page.locator("#summary-title").inner_text().startswith("브라우저 테스트")
                    page.screenshot(path=str(Path(tempfile.gettempdir()) / "skive-drive-browser.png"))
                    assert not errors, errors
                    print(json.dumps({"timings": timings, "preview_ok": True,
                                      "files_in_folder": page.locator("#files .file-row").count(),
                                      "browser_errors": errors}, ensure_ascii=False))
                    browser.close()
        finally:
            if user_id:
                deleted = remote.request("DELETE", f"{url}/auth/v1/admin/users/{user_id}",
                                         headers=headers, json={"should_soft_delete": False})
                deleted.raise_for_status()


if __name__ == "__main__":
    main()
