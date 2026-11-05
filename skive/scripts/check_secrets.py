"""Refuse a commit that adds secrets. Run by the pre-commit hook on staged changes only."""

import re
import subprocess
import sys

PATTERNS = {
    "Supabase secret key": r"sb_secret_[A-Za-z0-9_-]{10,}",
    "Anthropic key": r"sk-ant-[A-Za-z0-9_-]{20,}",
    "OpenAI key": r"\bsk-(?:proj-)?[A-Za-z0-9_-]{30,}",
    "Google client secret": r"GOCSPX-[A-Za-z0-9_-]{10,}",
    "Google API key": r"AIza[A-Za-z0-9_-]{30,}",
    "GitHub token": r"gh[pousr]_[A-Za-z0-9]{30,}",
    "Private key": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "Database URL with password": r"postgres(?:ql)?://[^\s:/<\[]+:[^\s@<\[]+@",
}
BLOCKED_PATHS = re.compile(
    r"(^|/)(\.env(\.(?!example$)[^/]*)?|env\.txt|env-[^/]*|client_secret[^/]*\.json|"
    r"service[-_]?account[^/]*\.json|[^/]*\.(pem|p12|pfx|key))$",
    re.IGNORECASE,
)


def git(*args: str) -> str:
    return subprocess.run(["git", "-c", "core.quotepath=false", *args], capture_output=True,
                          encoding="utf-8", errors="replace", check=True).stdout


def main() -> int:
    problems = [f"{path}: 비밀값 파일" for path in git("diff", "--cached", "--name-only").splitlines()
                if BLOCKED_PATHS.search(path)]
    current = None
    for line in git("diff", "--cached", "-U0").splitlines():
        if line.startswith("+++ "):
            current = line[6:]
        elif line.startswith("+") and current and not current.endswith("scripts/check_secrets.py"):
            problems += [f"{current}: {label}" for label, pattern in PATTERNS.items() if re.search(pattern, line)]
    if problems:
        print("커밋을 막았습니다. 값은 출력하지 않습니다.", file=sys.stderr)
        for problem in sorted(set(problems)):
            print(f"  {problem}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
