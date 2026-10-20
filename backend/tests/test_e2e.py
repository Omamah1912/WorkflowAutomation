"""Phase 7 acceptance checks on the classical path (no LLM keys), through the real API."""
from fastapi.testclient import TestClient

import app as app_module
from scripts.run_e2e import acceptance, run_and_wait

client = TestClient(app_module.app)


def call(method, path, body=None):
    r = client.request(method, path, json=body)
    r.raise_for_status()
    return r.json()


def test_phase7_acceptance():
    for source in ("csv", "manifest", "fixture"):
        batch = run_and_wait(call, source, timeout_s=600)
        assert batch["status"] == "done"
    for name, ok, detail in acceptance(call):
        assert ok, f"{name}: {detail}"
