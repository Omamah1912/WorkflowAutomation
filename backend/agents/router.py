"""Router agent: decide auto_approve / needs_review / archive / reject / duplicate from thresholds.yaml,
build the review packet for escalated documents, and write approved tracks to the ledger.
Escalated documents never reach the ledger until a human approves them (POST /review)."""
import time

import llm
import prompts
from state import Document
from tools import audit, ledger
from tools.config import thresholds

CRITICAL_FIELDS = ("cash_dividend", "cash_dividend_percent", "bonus_shares")


def escalation_reasons(doc: Document) -> list[str]:
    th = thresholds()
    cx = th["complexity_escalate"]
    reasons = []
    if doc.doc_type_confidence < th["classifier_confidence_min"]:
        reasons.append(f"classification confidence {doc.doc_type_confidence:.2f} < {th['classifier_confidence_min']}")
    for track in doc.tracks:
        for r in track.rule_results:
            if r.status == "fail" and (r.severity == "critical" or (doc.source.startswith("csv") and r.severity == "warning")):
                reasons.append(f"{r.rule_id} failed: {r.message}")
    if doc.source.startswith("csv"):
        return reasons

    if not doc.company or not doc.company.value:
        reasons.append("company not identified from the document")
    for track in doc.tracks:
        for f in track.fields:
            if f.name in CRITICAL_FIELDS and f.method.startswith("llm_"):
                reasons.append(f"{f.name} came from {f.method} without classical confirmation")
            elif f.name in CRITICAL_FIELDS and f.method != "fixture" and f.confidence < th["classifier_confidence_min"]:
                reasons.append(f"{f.name} confidence {f.confidence:.2f} below threshold")
    unread = sorted(p for p, m in doc.page_methods.items() if m == "unread")
    if cx["scanned"] and unread:
        reasons.append(f"complexity: {len(unread)} scanned page(s) could not be read (no OCR / LLM): {unread}")
    if len(doc.tracks) > cx["max_entities"]:
        reasons.append(f"complexity: {len(doc.tracks)} entities > {cx['max_entities']}")
    for note in doc.complexity:
        if "percent-only" in note and not cx["percent_without_face_value"]:
            continue
        reasons.append(f"complexity: {note}")
    return reasons


def route(doc: Document) -> None:
    t0 = time.perf_counter()
    if doc.status == "rejected":
        doc.route = "reject"
    elif doc.duplicate_of:
        doc.route = "duplicate"
    elif doc.relevance is False:
        doc.route = "archive"
    else:
        doc.escalation_reasons = escalation_reasons(doc)
        doc.route = "needs_review" if doc.escalation_reasons else "auto_approve"
    method = "classical"
    if doc.route == "needs_review":
        method = build_review_packet(doc)
    doc.status = {"auto_approve": "done", "needs_review": "needs_review", "archive": "archived",
                  "duplicate": "duplicate", "reject": "rejected"}[doc.route]
    detail = {"duplicate": f" of {doc.duplicate_of}", "archive": f" ({doc.doc_type})"}.get(doc.route, "")
    audit.log(doc, "route", "router", method=method, confidence=doc.doc_type_confidence,
              decision=doc.route + detail + ("" if not doc.escalation_reasons else " | " + " ; ".join(doc.escalation_reasons)),
              rule_ids=[r.rule_id for t in doc.tracks for r in t.rule_results if r.status == "fail"],
              status="warning" if doc.route in ("needs_review", "duplicate", "reject") else "ok",
              duration_ms=audit.ms_since(t0))


def build_review_packet(doc: Document) -> str:
    """Consequence sentence (LLM if available, else computed from the failures), failed rules with
    clauses, evidence for the implicated fields, and suggested fixes. Returns the method used."""
    failed = [(t, r) for t in doc.tracks for r in t.rule_results if r.status == "fail"]
    evidence = []
    for track, rule in failed:
        for name in rule.fields:
            f = track.get(name)
            if f:
                evidence.append({"track_id": track.track_id, "field": f.name, "value": f.value, "unit": f.unit,
                                 "unit_type": f.unit_type, "method": f.method, **f.evidence.model_dump()})
    fixes = [f"{r.rule_id}: {r.suggested_fix}" for _, r in failed if r.suggested_fix]
    for track in doc.tracks:  # computed hint: what the source actually declared
        declared, entered = track.get("declared_cash_dividend"), track.get("cash_dividend")
        if declared and entered and declared.unit_type != entered.unit_type:
            fixes.insert(0, f"Declared: {declared.value:,} {declared.unit}; entered: {entered.value:,} {entered.unit}. "
                            f"Enter the declared figure.")

    critical = [r.message for _, r in failed if r.severity == "critical"]
    template = (f"If approved as-is: {'; '.join(critical)}." if critical
                else f"Needs a human because: {'; '.join(doc.escalation_reasons[:3])}.")
    sentence, method = template, "classical"
    try:
        out, method = llm.call_llm(
            prompts.CONSEQUENCE.format(doc=f"{doc.doc_type} from {doc.company.value if doc.company else 'unknown company'}",
                                       failures="\n".join(doc.escalation_reasons[:6])),
            prompts.ConsequenceOut, "router_consequence", doc_id=doc.doc_id)
        sentence = out.sentence
    except llm.LLMUnavailable:
        pass  # the computed template above is used
    doc.review_packet = {
        "consequence": sentence, "consequence_method": method, "computed_consequence": template,
        "reasons": doc.escalation_reasons,
        "rules": [{"track_id": t.track_id, "rule_id": r.rule_id, "severity": r.severity, "message": r.message,
                   "source_clause": r.source_clause, "verify": r.verify, "expected": r.expected, "actual": r.actual}
                  for t, r in failed],
        "evidence": evidence, "suggested_fix": fixes, "label": doc.label,
    }
    return method


def ledger_payload(doc: Document, track) -> dict:
    return {"doc_type": doc.doc_type, "company": doc.company.value if doc.company else None, "symbol": doc.symbol,
            "period": doc.period.value if doc.period else None, "entity": track.entity_label,
            "fields": [f.model_dump(include={"name", "value", "unit", "unit_type", "method", "confidence", "evidence"})
                       for f in track.fields]}


def enter(doc: Document, approved_by: str) -> int:
    """Idempotent ledger write of every track. Returns the number of new rows."""
    t0 = time.perf_counter()
    if doc.source.startswith("csv"):
        return 0  # CSV rows carry no financial values; they are routed, not entered
    written = sum(ledger.write(doc.doc_id, t.track_id, ledger_payload(doc, t), approved_by) for t in doc.tracks)
    audit.log(doc, "entry", "ledger", decision=f"ledger: {written} new row(s) of {len(doc.tracks)} track(s), approved_by={approved_by}",
              duration_ms=audit.ms_since(t0))
    return written
