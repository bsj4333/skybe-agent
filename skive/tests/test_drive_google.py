"""Google connection rules that must hold without touching Google or the database."""

from uuid import uuid4

import httpx
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



@pytest.mark.parametrize("name", ["~$초안.docx", "._이력서.pdf", ".DS_Store", "Thumbs.db"])
def test_system_files_are_recognized(name):
    from skive.drive_worker import _is_system_file

    assert _is_system_file(name)


def folder(name):
    return {"id": name, "name": name, "mimeType": google.FOLDER}


def test_tool_folders_are_not_walked(monkeypatch):
    tree = {"p": [folder(".git"), folder("node_modules"), {"id": "a", "name": "보고서.pdf", "mimeType": "application/pdf"}]}
    monkeypatch.setattr(google, "list_children", lambda user, query: tree.get(query.split("'")[1], []))
    monkeypatch.setattr(google, "_set_total", lambda *args: None)
    found, skipped = [], []
    google.collect(uuid4(), {**folder("프로젝트"), "id": "p"}, (), found, skipped, uuid4())
    assert [item["name"] for item, _ in found if item] == ["보고서.pdf"]
    assert skipped == [".git", "node_modules"]


def test_experience_keeps_files_it_can_read():
    pdf = {"id": "1", "name": "보고서.pdf", "mimeType": "application/pdf"}
    doc = {"id": "2", "name": "회의록", "mimeType": "application/vnd.google-apps.document"}
    image = {"id": "3", "name": "layer_0001.png", "mimeType": "image/png"}
    lock = {"id": "4", "name": "package-lock.json", "mimeType": "application/json"}
    senior = {"id": "5", "name": "자소서.docx", "mimeType": "application/msword"}
    entries = [(None, ("프로젝트",)), (pdf, ("프로젝트",)), (doc, ("프로젝트",)), (image, ("프로젝트",)),
               (lock, ("프로젝트",)), (senior, ("프로젝트", "선배 자료"))]
    kept, dropped = google.for_experience(entries, "홍길동")
    assert [item["id"] for item, _ in kept if item] == ["1", "2"]
    assert (None, ("프로젝트",)) in kept
    assert dropped == 3


def drive_tree(monkeypatch, replies):
    def handler(request):
        status, body = replies[request.url.path.rsplit("/", 1)[-1]]
        return httpx.Response(status, json=body)

    monkeypatch.setattr(google, "_google_client", lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(google, "access_token", lambda user: "token")


def test_drive_path_leaves_out_the_folder_and_the_root(monkeypatch):
    drive_tree(monkeypatch, {"c": (200, {"name": "3d", "parents": ["b"]}),
                             "b": (200, {"name": "종합설계", "parents": ["a"]}),
                             "a": (200, {"name": "4학년", "parents": ["root"]}),
                             "root": (200, {"name": "내 드라이브"})})
    assert google.drive_path(uuid4(), "c") == ("4학년", "종합설계")


def test_drive_path_stops_at_a_parent_it_cannot_see(monkeypatch):
    drive_tree(monkeypatch, {"c": (200, {"name": "공유", "parents": ["b"]}), "b": (404, {})})
    assert google.drive_path(uuid4(), "c") == ()


def test_only_a_folder_can_be_linked():
    file = google.GoogleItem(id="a", name="보고서.pdf", mimeType="application/pdf")
    with pytest.raises(HTTPException) as caught:
        google.link_folder(uuid4(), file, uuid4())
    assert caught.value.status_code == 422


def test_real_documents_are_not_system_files():
    from skive.drive_worker import _is_system_file

    assert not _is_system_file("현대모비스 이력서.pdf")
