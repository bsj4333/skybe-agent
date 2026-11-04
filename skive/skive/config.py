"""Load only this app's local configuration, preserving deployment variables."""

from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"


def load_environment() -> bool:
    """Never search parent folders: those may belong to another Supabase project."""
    return load_dotenv(dotenv_path=ENV_FILE, override=False)
