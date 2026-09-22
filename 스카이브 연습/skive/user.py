import json
from pathlib import Path

USER_FILE = Path(__file__).resolve().parent.parent / "data" / "user.json"


def load_user() -> dict:
    return json.loads(USER_FILE.read_text(encoding="utf-8"))
