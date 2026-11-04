"""Opt-in live Supabase smoke test. Creates and removes two temporary users."""

import base64
import os
import secrets
import time
from pathlib import Path
from urllib.parse import urljoin
from uuid import uuid4

import httpx
from dotenv import load_dotenv
from fastapi.testclient import TestClient

from skive.drive_worker import run_once
from skive.server import app

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def checked(response: httpx.Response) -> dict:
    if response.is_error:
        raise RuntimeError(f"Supabase returned {response.status_code}: {response.text[:300]}")
    return response.json() if response.content else {}


def main():
    url = os.environ["SUPABASE_URL"].rstrip("/")
    publishable = os.environ["SUPABASE_PUBLISHABLE_KEY"]
    secret = os.environ["SUPABASE_SECRET_KEY"]
    admin_headers = {"apikey": secret, "Authorization": f"Bearer {secret}"}
    public_headers = {"apikey": publishable}
    created_users: list[str] = []
    storage_path = None
    cleanup_errors = []
    with httpx.Client(timeout=30) as remote:
        try:
            accounts = []
            for label in ("a", "b"):
                email = f"skive-smoke-{label}-{uuid4().hex}@example.invalid"
                password = secrets.token_urlsafe(24)
                user = checked(remote.post(
                    f"{url}/auth/v1/admin/users", headers=admin_headers,
                    json={"email": email, "password": password, "email_confirm": True},
                ))
                user_id = (user.get("user") or user)["id"]
                created_users.append(user_id)
                token = checked(remote.post(
                    f"{url}/auth/v1/token?grant_type=password", headers=public_headers,
                    json={"email": email, "password": password},
                ))["access_token"]
                accounts.append((label, user_id, token))
            a, b = accounts
            client = TestClient(app)

            def call(account, method, path, **kwargs):
                response = client.request(method, "/api/drive" + path,
                                          headers={"Authorization": f"Bearer {account[2]}"}, **kwargs)
                if response.is_error:
                    raise RuntimeError(f"Drive {method} {path}: {response.status_code} {response.text[:300]}")
                return response.json()

            tree = call(a, "POST", "/folders/import-tree", json={
                "paths": ["SCM 수업/자료", "SCM 수업/정리"],
            })["folders"]
            repeated = call(a, "POST", "/folders/import-tree", json={
                "paths": ["SCM 수업/정리", "SCM 수업/자료"],
            })["folders"]
            assert repeated == tree
            folder_id = tree["SCM 수업/자료"]
            assert call(a, "GET", "/items")["folders"][0]["id"] == tree["SCM 수업"]
            assert call(b, "GET", "/items") == {"folders": [], "files": []}
            assert call(b, "GET", "/summary")["total_files"] == 0
            denied = client.get(f"/api/drive/folders/{folder_id}/breadcrumbs",
                                headers={"Authorization": f"Bearer {b[2]}"})
            assert denied.status_code == 404
            data = ("SCM class notes: BOM lists components. CAPA compares planned and available capacity.\n"
                    "My role needs separate confirmation before essay use.\n").encode()
            file = call(a, "POST", "/files/init", json={
                "name": "scm_notes.txt", "parent_id": folder_id,
                "size_bytes": len(data), "mime_type": "text/plain",
            })
            storage_path = file["storage_path"]
            assert call(b, "GET", "/items") == {"folders": [], "files": []}
            metadata = ",".join(f"{key} {base64.b64encode(value.encode()).decode()}" for key, value in {
                "bucketName": "skive-originals", "objectName": storage_path,
                "contentType": "text/plain", "cacheControl": "3600",
            }.items())
            storage_base = url.replace(".supabase.co", ".storage.supabase.co")
            tus_headers = {**public_headers, "Authorization": f"Bearer {a[2]}", "Tus-Resumable": "1.0.0"}
            creation = remote.post(
                f"{storage_base}/storage/v1/upload/resumable",
                headers={**tus_headers, "Upload-Length": str(len(data)), "Upload-Metadata": metadata},
            )
            if creation.is_error:
                raise RuntimeError(f"TUS create: {creation.status_code} {creation.text[:300]}")
            upload_url = urljoin(storage_base, creation.headers["Location"])
            cut = min(25, len(data) - 1)
            for offset, part in ((0, data[:cut]), (cut, data[cut:])):
                upload = remote.patch(upload_url, headers={**tus_headers, "Upload-Offset": str(offset),
                                                          "Content-Type": "application/offset+octet-stream"},
                                      content=part)
                if upload.is_error:
                    raise RuntimeError(f"TUS PATCH: {upload.status_code} {upload.text[:300]}")
                head = remote.head(upload_url, headers=tus_headers)
                assert int(head.headers["Upload-Offset"]) == offset + len(part)
            print("TUS interrupted upload resumed: yes")

            for attempt in range(5):
                response = client.post(f"/api/drive/files/{file['id']}/complete",
                                       headers={"Authorization": f"Bearer {a[2]}"})
                if response.status_code == 200:
                    break
                time.sleep(1)
            assert response.status_code == 200, response.text
            for _ in range(30):
                run_once(url, secret, file_id=file["id"])  # A separate worker may claim it first.
                analysis = call(a, "GET", f"/files/{file['id']}/analysis")
                if analysis["analysis_status"] in ("ready", "failed", "unsupported"):
                    break
                time.sleep(0.5)
            assert analysis["analysis_status"] == "ready", analysis
            assert "C1" in analysis["analysis_markdown"]
            assert analysis["preview_chunks"] and "BOM" in analysis["preview_chunks"][0]["text"]
            assert call(a, "GET", f"/files/{file['id']}/status")["upload_status"] == "uploaded"
            other = client.get(f"/api/drive/files/{file['id']}/analysis",
                                       headers={"Authorization": f"Bearer {b[2]}"})
            assert other.status_code == 404
            other_status = client.get(f"/api/drive/files/{file['id']}/status",
                                      headers={"Authorization": f"Bearer {b[2]}"})
            assert other_status.status_code == 404
            storage_other = remote.get(
                f"{url}/storage/v1/object/authenticated/skive-originals/{storage_path}",
                headers={**public_headers, "Authorization": f"Bearer {b[2]}"},
            )
            assert storage_other.status_code in (400, 401, 403, 404)
            print("Auth, metadata RLS, Storage isolation, worker extraction: passed")
        finally:
            if storage_path:
                response = remote.delete(f"{url}/storage/v1/object/skive-originals/{storage_path}",
                                         headers=admin_headers)
                if response.is_error and response.status_code != 404:
                    cleanup_errors.append(f"Storage delete: {response.status_code} {response.text[:120]}")
            for user_id in created_users:
                response = remote.request("DELETE", f"{url}/auth/v1/admin/users/{user_id}",
                                          headers=admin_headers, json={"should_soft_delete": False})
                if response.is_error:
                    cleanup_errors.append(f"Auth user delete {user_id}: {response.status_code} {response.text[:120]}")
            if cleanup_errors:
                print("Cleanup errors:", *cleanup_errors, sep="\n")


if __name__ == "__main__":
    main()
