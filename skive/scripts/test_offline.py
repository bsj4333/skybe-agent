"""Run existing regressions without enabling their optional live-DB checks.

Usage: uv run python -m scripts.test_offline
The real Supabase security checks retain every assertion and can still be run
explicitly against a prepared test project. No credentials are printed here.
"""

import os
import sys


def main() -> int:
    # dotenv preserves an explicitly set process variable, including empty values.
    os.environ["DATABASE_URL"] = ""
    import pytest

    return pytest.main(sys.argv[1:] or ["-q", "--tb=short"])


if __name__ == "__main__":
    raise SystemExit(main())
