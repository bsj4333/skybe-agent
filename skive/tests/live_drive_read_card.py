"""Opt-in two-account read-card API and Edge UI smoke test.

Run with local server: uv run --with playwright python tests/live_drive_read_card.py
Creates temporary Auth users and a synthetic file record, then removes them.
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
from skive.drive_worker import backfill_read_card_once
from skive.server import app

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def main():
    url = os.environ["SUPABASE_URL"].rstrip("/")
    secret = os.environ["SUPABASE_SECRET_KEY"]
    public = os.environ.get("SUPABASE_PUBLISHABLE_KEY") or os.environ["SUPABASE_ANON_KEY"]
    admin_headers = {"apikey": secret, "Authorization": f"Bearer {secret}"}
    users = []
    with httpx.Client(timeout=30) as remote:
        try:
            for _ in range(2):
                email = f"skive-read-{uuid4().hex}@example.invalid"
                password = secrets.token_urlsafe(24)
                created = remote.post(f"{url}/auth/v1/admin/users", headers=admin_headers,
                                      json={"email": email, "password": password, "email_confirm": True})
                created.raise_for_status()
                user_id = UUID((created.json().get("user") or created.json())["id"])
                users.append({"id": user_id, "email": email, "password": password})
                signed = remote.post(f"{url}/auth/v1/token?grant_type=password",
                                     headers={"apikey": public},
                                     json={"email": email, "password": password})
                signed.raise_for_status()
                users[-1]["headers"] = {"Authorization": "Bearer " + signed.json()["access_token"]}
            owner, other = users
            file_id = uuid4()
            unsupported_id = uuid4()
            with get_connection() as conn:
                conn.execute(
                    "insert into skive.drive_files(id,user_id,name,storage_path,size_bytes,"
                    "upload_status,analysis_status,analysis_coverage,analyzed_at) "
                    "values (%s,%s,'read-card-test.txt',%s,100,'uploaded','ready','{}'::jsonb,now())",
                    (file_id, owner["id"], f'{owner["id"]}/{file_id}/original'),
                )
                for index in range(1, 23):
                    conn.execute(
                        "insert into skive.drive_file_chunks "
                        "(user_id,file_id,file_version,chunk_index,location,text) "
                        "values (%s,%s,1,%s,%s,%s)",
                        (owner["id"], file_id, index, f"L{index}-{index}", f"원문 {index}건"),
                    )
                conn.execute(
                    "insert into skive.drive_files(id,user_id,name,storage_path,size_bytes,"
                    "upload_status,analysis_status,analysis_error) "
                    "values (%s,%s,'unsupported-test.png',%s,100,'uploaded','unsupported',%s)",
                    (unsupported_id, owner["id"], f'{owner["id"]}/{unsupported_id}/original',
                     "synthetic image has no OCR"),
                )
            for candidate in (file_id, unsupported_id):
                if not backfill_read_card_once(candidate):
                    with get_connection() as conn:
                        assert conn.execute(
                            "select 1 from skive.drive_file_read_cards where file_id=%s",
                            (candidate,),
                        ).fetchone()
            with TestClient(app) as client:
                card = client.get(f"/api/drive/files/{file_id}/read-card", headers=owner["headers"])
                assert card.status_code == 200, card.text
                assert card.json()["card"]["chunk_count"] == 22
                assert card.json()["card"]["number_count"] == 22
                first = client.get(f"/api/drive/files/{file_id}/read-card/chunks?limit=20",
                                   headers=owner["headers"])
                assert len(first.json()["chunks"]) == 20 and first.json()["next_after"] == 20
                last = client.get(f"/api/drive/files/{file_id}/read-card/chunks?after=20",
                                  headers=owner["headers"])
                assert [r["chunk_index"] for r in last.json()["chunks"]] == [21, 22]
                assert last.json()["next_after"] is None
                for endpoint in ("read-card", "read-card/chunks"):
                    assert client.get(f"/api/drive/files/{file_id}/{endpoint}",
                                      headers=other["headers"]).status_code == 404
                unsupported = client.get(f"/api/drive/files/{unsupported_id}/read-card",
                                         headers=owner["headers"])
                assert unsupported.status_code == 200
                assert unsupported.json()["card"]["status"] == "unsupported"
                assert client.get(f"/api/drive/files/{unsupported_id}/read-card/chunks",
                                  headers=owner["headers"]).json()["chunks"] == []
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel="msedge", headless=True)
                page = browser.new_page(viewport={"width": 1280, "height": 800})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(os.getenv("SKIVE_TEST_BASE_URL", "http://127.0.0.1:8010/"),
                          wait_until="domcontentloaded")
                page.locator("#email").fill(owner["email"])
                page.locator("#password").fill(owner["password"])
                page.locator("#signin").click()
                page.locator("#app").wait_for(state="visible", timeout=30000)
                page.locator("#items .name-button", has_text="read-card-test.txt").click()
                page.locator("#preview-read-card").click()
                page.locator("#read-card-status").get_by_text("추출 구간 22개", exact=False).wait_for()
                expect(page.locator("#read-card-chunks .read-card-chunk")).to_have_count(20)
                page.locator("#read-card-more").click()
                expect(page.locator("#read-card-chunks .read-card-chunk")).to_have_count(22)
                page.locator("#close-analysis").click()
                page.locator("#items .name-button", has_text="unsupported-test.png").click()
                page.locator("#preview-read-card").click()
                expect(page.locator("#read-card-status")).to_contain_text("synthetic image has no OCR")
                assert not errors, errors
                browser.close()
            print("read_card_backfill=1 unsupported_reason=1 two_account_isolation=1 "
                  "pagination=1 edge_ui=1")
        finally:
            for user in users:
                remote.request("DELETE", f'{url}/auth/v1/admin/users/{user["id"]}',
                               headers=admin_headers,
                               json={"should_soft_delete": False}).raise_for_status()
            print("temporary_accounts_removed=1")


if __name__ == "__main__":
    main()
