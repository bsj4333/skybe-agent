import json
from pathlib import Path

USER_FILE = Path(__file__).resolve().parent.parent / "data" / "user.json"

DEFAULTS = {"school": "", "major": "", "grade": None, "admission_year": None, "essay_style": ""}


def load_user() -> dict:
    data = json.loads(USER_FILE.read_text(encoding="utf-8"))
    return {**DEFAULTS, **data}


def save_user(update: dict) -> dict:
    user = {**load_user(), **update}
    USER_FILE.write_text(json.dumps(user, ensure_ascii=False, indent=2), encoding="utf-8")
    return user
