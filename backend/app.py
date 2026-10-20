"""GhostStop API (FastAPI). Run locally: uvicorn app:app --port 8000
Every response is computed live from the pipeline state; nothing is canned."""
import asyncio
import hashlib
import json
import os
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

import llm
import orchestrator
from agents import router, validator
from state import Evidence, FieldValue
from tools import audit, ledger, metrics, ocr, pdf_text, units
from tools.config import RUNTIME

app = FastAPI(title="GhostStop")

# Vercel preview/prod domains + local Vite dev server.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https://.*\.vercel\.app|http://localhost(:\d+)?|http://127\.0\.0\.1(:\d+)?",
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"ok": True, "ocr_tesseract": ocr.available(), "llm_providers": llm.configured_providers()}


# ---------------------------------------------------------------- batches

class BatchRequest(BaseModel):
    source: Literal["csv", "manifest", "fixture"]


@app.post("/batch")
async def start_batch(request: Request):
    """JSON {source: csv|manifest|fixture}, or multipart form with one or more PDFs in `files`."""
    if request.headers.get("content-type", "").startswith("multipart/form-data"):
        form = await request.form()
        uploads = []
        for f in form.getlist("files"):
            body = await f.read()
            folder = RUNTIME / "uploads"
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"{hashlib.sha256(body).hexdigest()[:16]}.pdf"
            path.write_bytes(body)
            uploads.append((str(path), f.filename or path.name))
        if not uploads:
            raise HTTPException(400, "no files uploaded (form field 'files')")
        return {"batch_id": orchestrator.run_batch_async("upload", uploads)}
    body = BatchRequest(**(await request.json()))
    return {"batch_id": orchestrator.run_batch_async(body.source)}


def _batch_or_404(batch_id: str) -> dict:
    if batch_id not in orchestrator.BATCHES:
        raise HTTPException(404, f"unknown batch {batch_id}")
    return orchestrator.BATCHES[batch_id]


def _public(batch: dict) -> dict:
    return {k: v for k, v in batch.items() if not k.startswith("_") and k != "records"}


@app.get("/batches")
def list_batches():
    return [_public(b) for b in orchestrator.BATCHES.values()]


@app.get("/batch/{batch_id}")
def get_batch(batch_id: str):
    batch = _batch_or_404(batch_id)
    docs = [orchestrator.DOCS[i] for i in batch["doc_ids"] if i in orchestrator.DOCS]
    return {**_public(batch), "documents": [{
        "doc_id": d.doc_id, "external_id": d.external_id, "source": d.source, "filename": d.filename,
        "doc_type": d.doc_type, "relevance": d.relevance, "stream": d.stream, "status": d.status, "route": d.route,
        "company": d.company.value if d.company else None, "label": d.label, "duplicate_of": d.duplicate_of,
        "timings": d.timings, "escalation_reasons": d.escalation_reasons,
    } for d in docs]}


@app.get("/stream/{batch_id}")
async def stream(batch_id: str, request: Request):
    """SSE of AuditEvents for the batch (replays history first, so late joiners see everything)."""
    _batch_or_404(batch_id)

    async def events():
        cursor = 0
        while True:
            if await request.is_disconnected():
                break
            new, cursor = audit.events_since(cursor, batch_id)
            for e in new:
                yield {"event": "audit", "data": e.model_dump_json()}
            if orchestrator.BATCHES[batch_id]["status"] != "running" and not new:
                yield {"event": "done", "data": json.dumps(_public(orchestrator.BATCHES[batch_id]))}
                break
            await asyncio.sleep(0.4)

    return EventSourceResponse(events())


# ---------------------------------------------------------------- documents

def _doc_or_404(doc_id: str):
    if doc_id not in orchestrator.DOCS:
        raise HTTPException(404, f"unknown document {doc_id}")
    return orchestrator.DOCS[doc_id]


@app.get("/doc/{doc_id}")
def get_doc(doc_id: str):
    doc = _doc_or_404(doc_id)
    return {**doc.model_dump(exclude={"metadata"}),
            "metadata": {k: v for k, v in doc.metadata.items() if not k.startswith("_")},
            "audit": [e.model_dump() for e in audit.for_doc(doc_id)],
            "ledger": ledger.entries(doc_id)}


@app.get("/doc/{doc_id}/page/{n}.png")
def page_png(doc_id: str, n: int):
    doc = _doc_or_404(doc_id)
    if not doc.path or not doc.path.endswith(".pdf") or not (1 <= n <= doc.pages):
        raise HTTPException(404, "no such page")
    return Response(pdf_text.render_png(doc.path, n, zoom=1.0), media_type="image/png",
                    headers={"X-Page-Width-Pt": str(pdf_text.page_size(doc.path, n)[0])})


class ReviewRequest(BaseModel):
    action: Literal["approve", "edit", "reject"]
    reviewer: str
    edits: Optional[dict] = None     # {field_name: value} or {field_name: {"value": .., "unit": ..}}
    track_id: Optional[str] = None   # which track the edits apply to (default: the primary track)
    note: str = ""


@app.post("/review/{doc_id}")
def review(doc_id: str, body: ReviewRequest):
    doc = _doc_or_404(doc_id)
    if doc.route != "needs_review":
        raise HTTPException(409, f"{doc_id} is '{doc.route}', not awaiting review")
    if body.edits:
        track = next((t for t in doc.tracks if t.track_id == body.track_id), doc.tracks[0])
        for name, value in body.edits.items():
            _apply_edit(doc, track, name, value, body.reviewer)
        batch = orchestrator.BATCHES.get(doc.batch_id, {})
        validator.validate(doc, batch.get("records", []))   # show the reviewer the effect of the edit
    still_failing = [r.rule_id for _, r in validator.critical_failures(doc)]
    written = 0
    if body.action == "approve":
        doc.route, doc.status = "auto_approve", "done"
        written = router.enter(doc, approved_by=f"human:{body.reviewer}")
    elif body.action == "reject":
        doc.route, doc.status = "reject", "rejected"
    audit.log(doc, "review", "human", method="human", status="warning" if still_failing and body.action == "approve" else "ok",
              decision=f"{body.action} by {body.reviewer}" + (f" (critical still failing: {still_failing})" if still_failing else "")
                       + (f" | note: {body.note}" if body.note else ""))
    return {"doc_id": doc_id, "route": doc.route, "status": doc.status, "ledger_rows_written": written,
            "critical_still_failing": still_failing, "rule_results": [r.model_dump() for t in doc.tracks for r in t.rule_results]}


def _apply_edit(doc, track, name: str, value, reviewer: str) -> None:
    """Replace one field with the reviewer's value, keeping the original page/bbox as evidence."""
    old = track.get(name)
    new_value, unit = (value.get("value"), value.get("unit")) if isinstance(value, dict) else (value, None)
    unit = unit if unit is not None else (old.unit if old else "")
    unit_type = units.unit_type_of(unit) if name in ("cash_dividend", "bonus_shares") else (old.unit_type if old else "text")
    track.put(FieldValue(
        name=name, value=new_value, unit=unit, unit_type=unit_type, confidence=1.0, method="human",
        evidence=Evidence(doc_id=doc.doc_id, page=old.evidence.page if old else None,
                          bbox=old.evidence.bbox if old else None,
                          text=f"edited by {reviewer}; was {old.value if old else None} {old.unit if old else ''}".strip())))


# ---------------------------------------------------------------- metrics / transparency

@app.get("/metrics")
def get_metrics():
    return metrics.compute(list(orchestrator.DOCS.values()), list(orchestrator.BATCHES.values()), audit.all_events())


@app.get("/llm-log")
def llm_log():
    return llm.LLM_LOG


@app.get("/ledger")
def get_ledger():
    return ledger.entries()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
