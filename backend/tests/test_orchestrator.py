"""The LangGraph batch graph: fan-out, barrier, resolver loop, escalation, ledger blocking."""
import orchestrator
from tools import audit, ledger


def test_fixture_batch_escalates_and_blocks_ledger():
    batch = orchestrator.run_batch_sync("fixture")
    assert orchestrator.BATCHES[batch]["status"] == "done"
    doc = orchestrator.DOCS["FIX-SAMSUNG-2018"]
    assert doc.route == "needs_review"
    assert doc.resolver_loops == 1            # tried once, nothing to re-read -> stop
    # escalated items never reach the ledger automatically (only a human approval writes them)
    assert not [e for e in ledger.entries("FIX-SAMSUNG-2018") if e["approved_by"] == "auto"]
    stages = [e.stage for e in audit.for_doc(doc.doc_id) if e.batch_id == batch]
    assert stages[:3] == ["intake", "classify", "extract"]
    assert "resolve" in stages and stages[-1] == "route"


def test_manifest_batch_routes_every_document():
    batch = orchestrator.run_batch_sync("manifest")
    docs = [orchestrator.DOCS[i] for i in orchestrator.BATCHES[batch]["doc_ids"]]
    assert len(docs) == 12
    assert all(d.route in ("auto_approve", "needs_review", "archive", "duplicate", "reject") for d in docs)
    assert orchestrator.DOCS["PSX-266509-1"].route == "archive"
    pso = orchestrator.DOCS["PSX-283440"]
    if pso.route == "auto_approve":
        assert len(ledger.entries("PSX-283440")) == 2   # one row per track
