"""Append-only audit trail. Every agent decision becomes an AuditEvent: kept in memory for the
API/SSE and appended to runtime/audit.jsonl. SSE readers poll events_since() with a cursor,
which is thread-safe without any asyncio plumbing (the pipeline runs in worker threads)."""
import threading
import time

from state import AuditEvent, Document, Evidence
from tools.config import RUNTIME

EVENTS: list[AuditEvent] = []
_lock = threading.Lock()


def ms_since(t0: float) -> float:
    return round((time.perf_counter() - t0) * 1000, 2)


def log(doc: Document, stage: str, agent: str, *, decision: str, method: str = "classical",
        confidence: float | None = None, rule_ids: list[str] | None = None,
        evidence: Evidence | None = None, duration_ms: float = 0.0, status: str = "ok",
        track_id: str | None = None) -> AuditEvent:
    event = AuditEvent(batch_id=doc.batch_id, doc_id=doc.doc_id, track_id=track_id, stage=stage,
                       agent=agent, method=method, decision=decision, confidence=confidence,
                       rule_ids=rule_ids or [], evidence=evidence, duration_ms=duration_ms, status=status)
    doc.timings[stage] = round(doc.timings.get(stage, 0.0) + duration_ms, 2)
    with _lock:
        EVENTS.append(event)
        RUNTIME.mkdir(parents=True, exist_ok=True)
        with open(RUNTIME / "audit.jsonl", "a", encoding="utf-8") as f:
            f.write(event.model_dump_json() + "\n")
    return event


def events_since(cursor: int, batch_id: str | None = None) -> tuple[list[AuditEvent], int]:
    """Events after position `cursor` (optionally for one batch) and the new cursor."""
    with _lock:
        new = EVENTS[cursor:]
        end = len(EVENTS)
    if batch_id:
        new = [e for e in new if e.batch_id == batch_id]
    return new, end


def for_doc(doc_id: str) -> list[AuditEvent]:
    with _lock:
        return [e for e in EVENTS if e.doc_id == doc_id]
