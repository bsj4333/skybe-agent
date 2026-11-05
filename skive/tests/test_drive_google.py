"""Google connection rules that must hold without touching Google or the database."""

from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException

from skive import drive_google as google


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GOOGLE_TOKEN_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("SKIVE_PUBLIC_URL", "https://skive.example/")


def test_state_returns_the_user_only_for_the_browser_that_started():
    user_id = uuid4()
    state = google.make_state(user_id, "nonce")
    assert google.read_state(state, "nonce") == user_id
    for wrong in ("other", None, ""):
        with pytest.raises(HTTPException):
            google.read_state(state, wrong)


def test_tampered_state_is_rejected():
    with pytest.raises(HTTPException):
        google.read_state(google.make_state(uuid4(), "nonce")[:-4] + "AAAA", "nonce")


def test_feature_hides_when_any_setting_is_missing(monkeypatch):
    assert google.enabled()
    monkeypatch.delenv("GOOGLE_TOKEN_KEY")
    assert not google.enabled()


def test_redirect_uri_is_exact():
    assert google._redirect_uri() == "https://skive.example/api/drive/google/callback"


@pytest.mark.parametrize("mime,name,expected", [
    ("application/pdf", "보고서.pdf", "보고서.pdf"),
    ("application/vnd.google-apps.document", "초안", "초안.docx"),
    ("application/vnd.google-apps.spreadsheet", "표", "표.xlsx"),
    ("application/vnd.google-apps.presentation", "발표", "발표.pptx"),
])
def test_file_plan_names(mime, name, expected):
    assert google.file_plan({"name": name, "mimeType": mime})[0] == expected


@pytest.mark.parametrize("mime", ["application/vnd.google-apps.shortcut", "application/vnd.google-apps.form"])
def test_items_that_are_not_files_are_skipped(mime):
    assert google.file_plan({"name": "x", "mimeType": mime}) is None


def test_names_stay_valid_for_drive_paths():
    assert "/" not in google.safe_name("결과/정리")
    assert google.safe_name("  ..  ") == "이름 없음"
    assert len(google.safe_name("가" * 400)) == 255


@pytest.mark.parametrize("bad", ["x' or trashed=true or '", "a b", "../up"])
def test_folder_query_rejects_injection(bad):
    with pytest.raises(HTTPException):
        google.folder_query(bad)


def test_folder_query_targets():
    assert google.folder_query("root") == "'root' in parents and trashed=false"
    assert google.folder_query("shared") == "sharedWithMe=true and trashed=false"

