"""Orchestrator: LangGraph wiring of the agents.

Batch graph:   intake -> (fan-out) front x N -> cross_index -> (fan-out) back x N -> finish
  front (per doc):  classify -> [archive | duplicate | CSV row: stop]  else  extract -> transform
  cross_index:      barrier; fuzzy duplicate check (company + type + period) and cross-record facts
  back (per doc):   reference -> validate -> (critical fail? resolve -> validate, max N loops) -> route -> entry

The barrier exists because some rules compare documents with each other (DIV-05 credit vs
declaration, DIV-08 vs previous period) and face values derived from one filing are used by others.
Documents live in DOCS; graph state only carries IDs.
"""
import threading
import time
import uuid
from operator import add
from pathlib import Path
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from agents import classifier, extractor, intake, resolver, router, transformer, validator
from state import Document, now_iso
from tools import audit
from tools.config import thresholds
from tools.dedup import DedupIndex

DOCS: dict[str, Document] = {}
BATCHES: dict[str, dict] = {}
_lock = threading.Lock()
MAX_PARALLEL = 8


# ---------------------------------------------------------------- per-document graphs

class DocState(TypedDict):
    doc_id: str


def _doc(state: DocState) -> Document:
    return DOCS[state["doc_id"]]


def _after_intake(state: DocState) -> str:
    d = _doc(state)
    return "stop" if d.status == "rejected" or d.duplicate_of else "classify"


def _after_classify(state: DocState) -> str:
    d = _doc(state)
    if not d.relevance or d.source.startswith("csv"):
        return "stop"  # admin docs are archived without extraction; CSV rows carry no content to extract
    return "extract"


front_builder = StateGraph(DocState)
front_builder.add_node("classify", lambda s: classifier.classify(_doc(s)) or {})
front_builder.add_node("extract", lambda s: extractor.extract(_doc(s)) or {})
front_builder.add_node("transform", lambda s: transformer.transform(_doc(s)) or {})
front_builder.add_conditional_edges(START, _after_intake, {"classify": "classify", "stop": END})
front_builder.add_conditional_edges("classify", _after_classify, {"extract": "extract", "stop": END})
front_builder.add_edge("extract", "transform")
front_builder.add_edge("transform", END)
FRONT = front_builder.compile()


class BackState(TypedDict):
    doc_id: str
    batch_id: str


def _skip_validation(state: BackState) -> str:
    d = _doc(state)
    return "route" if d.status == "rejected" or d.duplicate_of or d.relevance is False else "reference"


def _validate(state: BackState) -> dict:
    validator.validate(_doc(state), BATCHES[state["batch_id"]]["records"])
    return {}


def _after_validate(state: BackState) -> str:
    d = _doc(state)
    if (not d.source.startswith("csv") and validator.critical_failures(d)
            and d.resolver_loops < thresholds()["resolver_max_loops"]):
        return "resolve"
    return "route"


def _after_resolve(state: BackState) -> str:
    return "validate" if _doc(state).metadata.get("_resolver_changed") else "route"


def _resolve(state: BackState) -> dict:
    d = _doc(state)
    d.metadata["_resolver_changed"] = resolver.resolve(d)
    return {}


def _entry(state: BackState) -> dict:
    router.enter(_doc(state), approved_by="auto")
    return {}


back_builder = StateGraph(BackState)
back_builder.add_node("reference", lambda s: transformer.apply_reference(_doc(s)) or {})
back_builder.add_node("validate", _validate)
back_builder.add_node("resolve", _resolve)
back_builder.add_node("route", lambda s: router.route(_doc(s)) or {})
back_builder.add_node("entry", _entry)
back_builder.add_conditional_edges(START, _skip_validation, {"route": "route", "reference": "reference"})
back_builder.add_edge("reference", "validate")
back_builder.add_conditional_edges("validate", _after_validate, {"resolve": "resolve", "route": "route"})
back_builder.add_conditional_edges("resolve", _after_resolve, {"validate": "validate", "route": "route"})
back_builder.add_conditional_edges("route", lambda s: "entry" if _doc(s).route == "auto_approve" else "end",
                                   {"entry": "entry", "end": END})
back_builder.add_edge("entry", END)
BACK = back_builder.compile()


# ---------------------------------------------------------------- batch graph

class BatchState(TypedDict):
    batch_id: str
    source: str
    upload_paths: list
    doc_ids: Annotated[list[str], add]


def _load(source: str, upload_paths: list) -> list[Document]:
    if source == "csv":
        return intake.load_csv_rows()
    if source == "manifest":
        return intake.load_manifest()
    if source == "fixture":
        return intake.load_fixtures()
    if source == "upload":
        return [intake.from_upload(Path(p), name) for p, name in upload_paths]
    raise ValueError(f"unknown source {source}")


def intake_node(state: BatchState) -> dict:
    index = DedupIndex()  # duplicates are detected within a batch; the ledger is idempotent across batches
    ids = []
    for doc in _load(state["source"], state["upload_paths"]):
        doc.batch_id = state["batch_id"]
        with _lock:
            DOCS[doc.doc_id] = doc
        intake.accept(doc, index)
        ids.append(doc.doc_id)
    BATCHES[state["batch_id"]]["doc_ids"] = ids
    return {"doc_ids": ids}


def _safely(stage: str, doc_id: str, fn) -> None:
    """One bad document must not stop the batch: record the error and reject it."""
    try:
        fn()
    except Exception as e:
        d = DOCS[doc_id]
        d.status, d.route = "rejected", "reject"
        d.escalation_reasons.append(f"{stage} error: {type(e).__name__}: {e}")
        audit.log(d, stage, "orchestrator", method="none", status="error", decision=f"error: {type(e).__name__}: {e}"[:300])


def front_node(state: dict) -> dict:
    _safely("front", state["doc_id"], lambda: FRONT.invoke({"doc_id": state["doc_id"]}))
    return {}


def cross_index_node(state: BatchState) -> dict:
    index = DedupIndex()
    for doc_id in state["doc_ids"]:
        d = DOCS[doc_id]
        if d.source.startswith("csv") or d.duplicate_of or not d.relevance:
            continue
        dup, reason = index.check_fuzzy(d.doc_id, d.company.value if d.company else None, d.doc_type,
                                        d.period.value if d.period else None)
        if dup:
            d.duplicate_of, d.duplicate_reason = dup, reason
            audit.log(d, "dedup", "intake", decision=f"hold duplicate of {dup} ({reason})", status="warning")
    with _lock:
        all_docs = list(DOCS.values())
    BATCHES[state["batch_id"]]["records"] = validator.records_from(all_docs)
    return {}


def back_node(state: dict) -> dict:
    _safely("back", state["doc_id"], lambda: BACK.invoke({"doc_id": state["doc_id"], "batch_id": state["batch_id"]}))
    return {}


def finish_node(state: BatchState) -> dict:
    b = BATCHES[state["batch_id"]]
    b["status"], b["finished_at"] = "done", now_iso()
    b["duration_s"] = round(time.time() - b["_t0"], 2)
    return {}


batch_builder = StateGraph(BatchState)
batch_builder.add_node("intake", intake_node)
batch_builder.add_node("front", front_node)
batch_builder.add_node("cross_index", cross_index_node)
batch_builder.add_node("back", back_node)
batch_builder.add_node("finish", finish_node)
batch_builder.add_edge(START, "intake")
batch_builder.add_conditional_edges("intake", lambda s: [Send("front", {"doc_id": i}) for i in s["doc_ids"]] or ["cross_index"])
batch_builder.add_edge("front", "cross_index")
batch_builder.add_conditional_edges(
    "cross_index", lambda s: [Send("back", {"doc_id": i, "batch_id": s["batch_id"]}) for i in s["doc_ids"]] or ["finish"])
batch_builder.add_edge("back", "finish")
BATCH = batch_builder.compile()


# ---------------------------------------------------------------- entry points

def new_batch(source: str) -> str:
    batch_id = f"B-{uuid.uuid4().hex[:8]}"
    BATCHES[batch_id] = {"batch_id": batch_id, "source": source, "status": "running", "started_at": now_iso(),
                         "finished_at": None, "doc_ids": [], "records": [], "_t0": time.time()}
    return batch_id


def run_batch_sync(source: str, upload_paths: list | None = None, batch_id: str | None = None) -> str:
    batch_id = batch_id or new_batch(source)
    try:
        BATCH.invoke({"batch_id": batch_id, "source": source, "upload_paths": upload_paths or [], "doc_ids": []},
                     config={"max_concurrency": MAX_PARALLEL, "recursion_limit": 100})
    except Exception as e:
        BATCHES[batch_id].update(status="error", error=f"{type(e).__name__}: {e}", finished_at=now_iso())
        raise
    return batch_id


def run_batch_async(source: str, upload_paths: list | None = None) -> str:
    """Start a batch in a background thread and return its id immediately (used by POST /batch)."""
    batch_id = new_batch(source)
    threading.Thread(target=lambda: _quiet(run_batch_sync, source, upload_paths, batch_id), daemon=True).start()
    return batch_id


def _quiet(fn, *args):
    try:
        fn(*args)
    except Exception:
        pass  # recorded in BATCHES[batch_id]["error"]
