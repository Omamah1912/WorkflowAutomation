"""Pipeline metrics, computed from processed documents, audit events and the ps07 manual baseline
(the analysts' own time_spent_minutes / analyst_action / was_relevant columns). Nothing is stored."""
from collections import Counter

from state import Document
from tools.config import doc_types

NO_HUMAN_ROUTES = ("auto_approve", "archive", "duplicate")


def compute(docs: list[Document], batches: list[dict], events: list) -> dict:
    routed = [d for d in docs if d.route]
    ps07 = [d for d in routed if d.source == "csv_ps07"]
    return {
        "documents_processed": len(routed),
        "routes": dict(Counter(d.route for d in routed)),
        "automation_rate": round(sum(d.route in NO_HUMAN_ROUTES for d in routed) / len(routed), 3) if routed else None,
        "throughput_docs_per_min": _throughput(batches),
        "errors_caught_vs_baseline": _errors(ps07, routed),
        "time_saved_vs_baseline": _time_saved(ps07),
        "relevance_accuracy_vs_ps07_ground_truth": _accuracy(ps07),
        "classical_vs_llm_share": _method_share(events),
        "queue_depth_by_stage": dict(Counter(d.status for d in docs)),
    }


def _throughput(batches: list[dict]) -> float | None:
    done = [b for b in batches if b.get("status") == "done" and b.get("duration_s")]
    seconds = sum(b["duration_s"] for b in done)
    count = sum(len(b["doc_ids"]) for b in done)
    return round(count / (seconds / 60), 1) if seconds else None


def _errors(ps07: list[Document], routed: list[Document]) -> dict:
    """Baseline errors = analysts processing an irrelevant doc, or processing the same document_id twice."""
    irrelevant = {t["name"] for t in doc_types() if not t["relevant"]}
    manual_irrelevant = [d for d in ps07 if d.metadata.get("document_type_detected") in irrelevant
                         and d.metadata.get("analyst_action") == "Processed"]
    by_id = Counter(d.external_id for d in ps07 if d.metadata.get("analyst_action") == "Processed")
    repeat_ids = {i for i, n in by_id.items() if n > 1}
    manual_repeats = [d for d in ps07 if d.external_id in repeat_ids and d.duplicate_of]
    caught = ([d for d in manual_irrelevant if d.route == "archive"] + [d for d in manual_repeats if d.route == "duplicate"])
    real = [d for d in routed if not d.source.startswith("csv")]
    critical = [d for d in real if any(r.status == "fail" and r.severity == "critical"
                                       for t in d.tracks for r in t.rule_results)]
    return {
        "baseline_irrelevant_docs_processed_by_analysts": len(manual_irrelevant),
        "baseline_duplicates_processed_twice": len(manual_repeats),
        "baseline_errors_total": len(manual_irrelevant) + len(manual_repeats),
        "caught_by_pipeline": len(caught),
        "critical_rule_failures_blocked_from_ledger": len([d for d in critical if d.route != "auto_approve"]),
        "critical_failure_docs": [d.doc_id for d in critical],
    }


def _time_saved(ps07: list[Document]) -> dict:
    """Analyst minutes on ps07 rows the pipeline closed without a human (archived admin docs, held duplicates)."""
    def minutes(ds):
        return sum(int(d.metadata.get("time_spent_minutes") or 0) for d in ds)

    irrelevant = {t["name"] for t in doc_types() if not t["relevant"]}
    handled = [d for d in ps07 if d.route in ("archive", "duplicate")]
    total = minutes(ps07)
    return {
        "baseline_total_minutes": total,
        "baseline_minutes_on_irrelevant": minutes([d for d in ps07 if d.metadata.get("document_type_detected") in irrelevant]),
        "minutes_saved": minutes(handled),
        "share_of_baseline": round(minutes(handled) / total, 3) if total else None,
        "docs_closed_without_human": len(handled),
    }


def _accuracy(ps07: list[Document]) -> dict | None:
    judged = [d for d in ps07 if d.relevance is not None and d.metadata.get("was_relevant") in ("TRUE", "FALSE")]
    if not judged:
        return None
    correct = sum(d.relevance == (d.metadata["was_relevant"] == "TRUE") for d in judged)
    return {"correct": correct, "total": len(judged), "accuracy": round(correct / len(judged), 3)}


def _method_share(events: list) -> dict:
    groups = Counter()
    for e in events:
        if e.method.startswith("llm_"):
            groups[e.method] += 1
        elif e.method in ("classical", "derived_from_filing", "fixture", "ocr_tesseract", "human"):
            groups["classical" if e.method != "ocr_tesseract" else "ocr_tesseract"] += 1
    total = sum(groups.values())
    return {"counts": dict(groups), "llm_share": round(sum(v for k, v in groups.items() if k.startswith("llm_")) / total, 3)
            if total else None}
