"""Opt-in Edge smoke test for the drive's extraction coverage dialog.

Uses a temporary Auth account and mocked drive file responses; no Storage object
or personal source file is created. Run with a local server on port 8010:
uv run --with playwright python tests/live_drive_coverage_ui.py
"""

import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx
from dotenv import load_dotenv
from playwright.sync_api import expect, sync_playwright

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def main():
    url = os.environ["SUPABASE_URL"].rstrip("/")
    secret = os.environ["SUPABASE_SECRET_KEY"]
    headers = {"apikey": secret, "Authorization": f"Bearer {secret}"}
    email = f"skive-coverage-{uuid4().hex}@example.invalid"
    password = secrets.token_urlsafe(24)
    file_id = str(uuid4())
    user_id = None
    queued = False
    with httpx.Client(timeout=30) as remote:
        try:
            response = remote.post(f"{url}/auth/v1/admin/users", headers=headers,
                                   json={"email": email, "password": password, "email_confirm": True})
            response.raise_for_status()
            user_id = (response.json().get("user") or response.json())["id"]
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel="msedge", headless=True)
                page = browser.new_page(viewport={"width": 1280, "height": 800})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))

                def items(route):
                    route.fulfill(json={"folders": [], "files": [{
                        "id": file_id, "folder_id": None, "name": "sample.pdf",
                        "storage_path": "unused", "mime_type": "application/pdf", "size_bytes": 120,
                        "upload_status": "uploaded", "analysis_status": "ready", "analysis_error": None,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    }]})

                def analysis(route):
                    route.fulfill(json={
                        "id": file_id, "name": "sample.pdf", "version": 1,
                        "analysis_status": "queued" if queued else "ready", "analysis_error": None,
                        "analysis_markdown": "# sample.pdf\n\n- C1: p.1 annotation 1",
                        "analysis_coverage": {"format": ".pdf", "supplemental": [{
                            "kind": "pdf_annotations", "label": "PDF 주석", "detected": 2,
                            "extracted": 1, "status": "partial",
                        }]},
                        "preview_chunks": [], "supplemental_chunks": [{
                            "chunk_index": 1, "location": "p.1 annotation 1 (Text)",
                            "text": "수치를 다시 확인",
                        }],
                    })

                def reanalyze(route):
                    nonlocal queued
                    queued = True
                    route.fulfill(json={"id": file_id, "analysis_status": "queued"})

                page.route("**/api/drive/items*", items)
                page.route(f"**/api/drive/files/{file_id}/analysis", analysis)
                page.route(f"**/api/drive/files/{file_id}/reanalyze", reanalyze)
                page.goto(os.getenv("SKIVE_TEST_BASE_URL", "http://127.0.0.1:8010/"),
                          wait_until="domcontentloaded")
                page.locator("#email").fill(email)
                page.locator("#password").fill(password)
                page.locator("#signin").click()
                page.locator("#app").wait_for(state="visible", timeout=30000)
                page.locator("#items .name-button").first.click()
                page.locator("#analysis-dialog").wait_for(state="visible")
                page.locator("#preview-extracted").click()
                assert "PDF 주석: 2개 중 1개 읽음" in page.locator("#analysis-coverage").inner_text()
                assert "수치를 다시 확인" in page.locator("#analysis-text").inner_text()
                page.locator("#reanalyze-file").click()
                assert queued
                expect(page.locator("#reanalyze-file")).to_be_disabled(timeout=10000)
                assert "추출 완료 후 범위" in page.locator("#analysis-coverage").inner_text()
                assert not errors, errors
                print(json.dumps({"browser": "Edge", "coverage_visible": True,
                                  "comment_preview_visible": True, "reanalyze_click": True,
                                  "page_errors": errors}, ensure_ascii=False))
                browser.close()
        finally:
            if user_id:
                remote.request("DELETE", f"{url}/auth/v1/admin/users/{user_id}",
                               headers=headers, json={"should_soft_delete": False}).raise_for_status()


if __name__ == "__main__":
    main()
