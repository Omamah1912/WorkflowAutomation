"""Validator agent: run the YAML rules on every track. Cross-record rules (DIV-05, DIV-08) read
`records`, a flat list of facts from every processed document (built after the batch barrier)."""
import time

from state import Document, Track
from tools import audit, rules_engine
from tools.config import thresholds

CSV_RULES = "rules/csv_rules.yaml"
DIVIDEND_RULES = "rules/dividend_rules.yaml"


def records_from(docs: list[Document]) -> list[dict]:
    """One record per document with a money-per-share cash dividend (for cross-record checks)."""
    out = []
    for d in docs:
        if not d.tracks or d.source.startswith("csv") or d.duplicate_of:
            continue
        cash = d.tracks[0].get("cash_dividend")
        out.append({"doc_id": d.doc_id, "symbol": d.symbol, "company": d.company.value if d.company else None,
                    "period": d.period.value if d.period else None, "doc_type": d.doc_type,
                    "cash_dividend": cash.value if cash and cash.unit_type == "currency_per_share" else None})
    return out


def validate(doc: Document, records: list[dict]) -> None:
    t0 = time.perf_counter()
    doc.status = "validating"
    if doc.source.startswith("csv"):
        if not doc.tracks:
            doc.tracks = [Track(track_id=f"{doc.doc_id}/metadata", entity_label="metadata")]
        rule_file = CSV_RULES
    else:
        rule_file = DIVIDEND_RULES
    for i, track in enumerate(doc.tracks):
        ctx = {"doc": doc, "track": track, "records": records, "thresholds": thresholds(), "is_primary": i == 0}
        track.rule_results = rules_engine.evaluate(rule_file, ctx)
        failed = [r for r in track.rule_results if r.status == "fail"]
        audit.log(doc, "validate", "validator", track_id=track.track_id,
                  rule_ids=[r.rule_id for r in failed],
                  decision=(f"loop {doc.resolver_loops}: " if doc.resolver_loops else "") +
                           (", ".join(f"{r.rule_id} {r.severity} FAIL: {r.message}" for r in failed) or "all rules pass / n.a."),
                  status="error" if any(r.severity == "critical" for r in failed) else ("warning" if failed else "ok"),
                  duration_ms=audit.ms_since(t0) if i == len(doc.tracks) - 1 else 0.0)


def critical_failures(doc: Document) -> list[tuple[Track, object]]:
    return [(t, r) for t in doc.tracks for r in t.rule_results if r.status == "fail" and r.severity == "critical"]
