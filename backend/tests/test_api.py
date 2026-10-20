import time

from fastapi.testclient import TestClient

import app as app_module

client = TestClient(app_module.app)


def _wait(batch_id: str, timeout_s: float = 120):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        b = client.get(f"/batch/{batch_id}").json()
        if b["status"] != "running":
            return b
        time.sleep(0.2)
    raise AssertionError("batch did not finish")


def test_health():
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["ok"] is True


def test_fixture_batch_review_flow():
    batch_id = client.post("/batch", json={"source": "fixture"}).json()["batch_id"]
    batch = _wait(batch_id)
    assert batch["documents"][0]["route"] == "needs_review"
    assert batch["documents"][0]["label"] == "Reconstruction from public reporting"

    doc = client.get("/doc/FIX-SAMSUNG-2018").json()
    assert {r["rule_id"] for r in doc["review_packet"]["rules"]} >= {"DIV-01", "DIV-02"}
    assert doc["ledger"] == []

    # Reviewer corrects the unit: the critical rules re-run and pass, then approval writes the ledger.
    r = client.post("/review/FIX-SAMSUNG-2018", json={
        "action": "approve", "reviewer": "test", "edits": {"cash_dividend": {"value": 1000, "unit": "KRW per share"}}})
    assert r.status_code == 200
    assert r.json()["critical_still_failing"] == []
    assert r.json()["ledger_rows_written"] == 1
    assert client.post("/review/FIX-SAMSUNG-2018", json={"action": "approve", "reviewer": "test"}).status_code == 409


def test_sse_stream_replays_batch_events():
    batch_id = client.post("/batch", json={"source": "fixture"}).json()["batch_id"]
    _wait(batch_id)
    with client.stream("GET", f"/stream/{batch_id}") as r:
        body = "".join(r.iter_text())
    assert "event: audit" in body and "event: done" in body and '"stage":"route"' in body


def test_page_png_and_metrics():
    batch_id = client.post("/batch", json={"source": "manifest"}).json()["batch_id"]
    _wait(batch_id, timeout_s=300)
    png = client.get("/doc/PSX-283440/page/1.png")
    assert png.status_code == 200 and png.content[:4] == b"\x89PNG"
    m = client.get("/metrics").json()
    assert m["documents_processed"] >= 12 and "classical_vs_llm_share" in m
    assert client.get("/llm-log").status_code == 200


def test_upload_rejects_non_pdf():
    r = client.post("/batch", files={"files": ("notes.pdf", b"hello", "application/pdf")})
    batch = _wait(r.json()["batch_id"])
    assert batch["documents"][0]["route"] == "reject"
