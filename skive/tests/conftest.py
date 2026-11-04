"""Keep legacy regression tests in their original single-user configuration."""

import pytest


@pytest.fixture(autouse=True)
def legacy_mode_for_legacy_tests(request, monkeypatch):
    if request.node.path.name == "test_p0_regressions.py":
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        monkeypatch.delenv("SUPABASE_PUBLISHABLE_KEY", raising=False)
        monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)
