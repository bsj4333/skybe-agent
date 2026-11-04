"""The app must never pick up credentials from an unrelated parent project."""

import os

from skive import config


def test_environment_is_loaded_from_project_even_with_another_working_directory(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    dotenv_path = project / ".env"
    dotenv_path.write_text("SKIVE_CONFIG_TEST=project\n", encoding="utf-8")
    other = tmp_path / "other"
    other.mkdir()
    (other / ".env").write_text("SKIVE_CONFIG_TEST=other\n", encoding="utf-8")
    monkeypatch.chdir(other)
    monkeypatch.delenv("SKIVE_CONFIG_TEST", raising=False)
    monkeypatch.setattr(config, "ENV_FILE", dotenv_path)

    config.load_environment()

    assert os.environ["SKIVE_CONFIG_TEST"] == "project"


def test_environment_does_not_fall_back_to_parent_credentials(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    (tmp_path / ".env").write_text("SKIVE_CONFIG_TEST=parent\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SKIVE_CONFIG_TEST", raising=False)
    monkeypatch.setattr(config, "ENV_FILE", project / ".env")

    assert config.load_environment() is False
    assert "SKIVE_CONFIG_TEST" not in os.environ


def test_explicit_process_environment_overrides_local_dotenv(tmp_path, monkeypatch):
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text("SKIVE_CONFIG_TEST=file\n", encoding="utf-8")
    monkeypatch.setattr(config, "ENV_FILE", dotenv_path)
    monkeypatch.setenv("SKIVE_CONFIG_TEST", "deployment")

    config.load_environment()

    assert os.environ["SKIVE_CONFIG_TEST"] == "deployment"
