"""Test setup: runtime files (ledger, audit log, derived face values) go to a temp dir, and LLM keys
are removed so tests exercise the classical path deterministically. Tests that want the real LLM
use the `live_llm` fixture (and are skipped when no keys are configured)."""
import os
import tempfile

os.environ["GHOSTSTOP_RUNTIME_DIR"] = tempfile.mkdtemp(prefix="ghoststop-test-")

import pytest  # noqa: E402

import llm  # noqa: E402  (loads backend/.env so we can remember the real keys)

LLM_VARS = ("OPENAI_API_KEY", "OPENAI_MODEL", "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL")
REAL_KEYS = {k: os.environ.get(k, "") for k in LLM_VARS}
HAVE_KEYS = bool(REAL_KEYS["OPENAI_API_KEY"] or REAL_KEYS["ANTHROPIC_API_KEY"])


@pytest.fixture(autouse=True)
def no_llm(monkeypatch):
    for k in LLM_VARS:
        monkeypatch.setenv(k, "")


@pytest.fixture
def live_llm(monkeypatch):
    if not HAVE_KEYS:
        pytest.skip("no LLM keys configured")
    for k, v in REAL_KEYS.items():
        monkeypatch.setenv(k, v)
