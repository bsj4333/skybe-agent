"""Local-only compatibility entry point for the old single-user SKIVE UI.

Run on a separate loopback port: ``uv run uvicorn skive.legacy_server:app
--host 127.0.0.1 --port 8011``. This keeps legacy local data out of the
multiuser drive served on port 8010.
"""

import os

os.environ["SKIVE_LEGACY_LOCAL_ONLY"] = "1"

from skive.server import app  # noqa: E402
