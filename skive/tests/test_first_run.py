"""A source-only clone must not need somebody else's runtime profile."""

import json

from skive import user


def test_missing_profile_starts_with_empty_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(user, "USER_FILE", tmp_path / "data" / "user.json")

    assert user.load_user() == user.DEFAULTS
    assert not user.USER_FILE.exists()


def test_saving_first_profile_creates_runtime_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(user, "USER_FILE", tmp_path / "data" / "user.json")

    saved = user.save_user({"major": "Test major"})

    assert saved["major"] == "Test major"
    assert json.loads(user.USER_FILE.read_text(encoding="utf-8"))["major"] == "Test major"


def test_existing_profile_is_preserved_and_missing_fields_use_defaults(tmp_path, monkeypatch):
    path = tmp_path / "user.json"
    path.write_text(json.dumps({"major": "Existing major", "grade": 2}), encoding="utf-8")
    monkeypatch.setattr(user, "USER_FILE", path)

    profile = user.load_user()

    assert profile["major"] == "Existing major"
    assert profile["grade"] == 2
    assert profile["school"] == ""
