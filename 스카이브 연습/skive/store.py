import json
from pathlib import Path

from skive.loaders import load_folder

DATA = Path(__file__).resolve().parent.parent / "data"
STORE = DATA / "store"
PROFILE_DIR = DATA / "profile"


def _write_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def save(exp_id: str, markdown: str, meta: dict, facts: dict) -> Path:
    folder = STORE / exp_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "experience.md").write_text(markdown, encoding="utf-8")
    _write_json(folder / "metadata.json", meta)
    _write_json(folder / "facts.json", facts)
    return folder / "experience.md"


def list_meta() -> list[dict]:
    if not STORE.exists():
        return []
    metas = []
    for folder in STORE.iterdir():
        meta_path = folder / "metadata.json"
        if meta_path.is_file():
            metas.append(json.loads(meta_path.read_text(encoding="utf-8")))
    return sorted(metas, key=lambda m: (m.get("grade", 0), m["period"], m["id"]))


def get_meta(exp_id: str) -> dict | None:
    return next((m for m in list_meta() if m["id"] == exp_id), None)


def get_markdown(exp_id: str) -> str | None:
    if get_meta(exp_id) is None:
        return None
    return (STORE / exp_id / "experience.md").read_text(encoding="utf-8")


def get_facts(exp_id: str) -> dict | None:
    if get_meta(exp_id) is None:
        return None
    return json.loads((STORE / exp_id / "facts.json").read_text(encoding="utf-8"))


def get_source_text(exp_id: str, source: str, limit: int = 6000) -> str | None:
    meta = get_meta(exp_id)
    if meta is None or source not in meta["sources"]:
        return None
    chunks = [c for c in load_folder(Path(meta["raw_dir"])) if c.source == source]
    text = "\n".join(f"[{c.location}]\n{c.text}" for c in chunks)
    return text[:limit]


def save_profile(markdown: str, profile: dict) -> Path:
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    (PROFILE_DIR / "profile.md").write_text(markdown, encoding="utf-8")
    _write_json(PROFILE_DIR / "profile.json", profile)
    return PROFILE_DIR / "profile.md"


def get_profile_markdown() -> str | None:
    path = PROFILE_DIR / "profile.md"
    return path.read_text(encoding="utf-8") if path.is_file() else None


def get_profile_json() -> dict | None:
    path = PROFILE_DIR / "profile.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
