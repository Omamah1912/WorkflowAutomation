"""Intake agent: turn a CSV row / manifest row / fixture / upload into a Document,
normalising IDs and dates, hashing files and checking for exact duplicates."""
import csv
import hashlib
import json
import time
from pathlib import Path

from state import Document
from tools import audit, pdf_text, units
from tools.config import DATA
from tools.dedup import DedupIndex


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _clean_id(value: str) -> str:
    return (value or "").strip().upper()


def from_ps01(row: dict) -> Document:
    meta = {k: (v or "").strip() for k, v in row.items()}
    meta["received_date"] = units.parse_date(meta.get("received_date", "")) or meta.get("received_date", "")
    doc_id = _clean_id(row["doc_id"])
    return Document(doc_id=doc_id, external_id=doc_id, source="csv_ps01", filename=meta["filename"],
                    metadata=meta, legacy_stream=meta.get("assigned_stream") or None)


def from_ps07(row: dict) -> Document:
    meta = {k: (v or "").strip() for k, v in row.items()}
    # Already ISO; keep the full timestamp but make sure the date part parses.
    if not units.parse_date(meta.get("ingestion_timestamp", "")[:10]):
        meta["ingestion_timestamp"] = ""
    return Document(doc_id=_clean_id(row["job_id"]), external_id=_clean_id(row["document_id"]),
                    source="csv_ps07", filename=meta["filename"], metadata=meta)


def from_manifest(row: dict) -> Document:
    path = DATA / "real_docs" / row["filename"]
    sha = _sha256(path)
    meta = dict(row)
    if row.get("sha256") and row["sha256"] != sha:
        meta["intake_note"] = "sha256 differs from manifest (file changed since download)"
    return Document(doc_id=f"PSX-{row['psx_doc_id']}", external_id=row["psx_doc_id"], source="manifest",
                    filename=row["filename"], path=str(path), sha256=sha, metadata=meta,
                    pages=pdf_text.page_count(str(path)))


def from_fixture(path: Path) -> Document:
    data = json.loads(path.read_text(encoding="utf-8"))
    return Document(doc_id=data["doc_id"], external_id=data["doc_id"], source="fixture", filename=path.name,
                    path=str(path), sha256=_sha256(path), metadata=data, label=data.get("label"))


def from_upload(path: Path, original_name: str) -> Document:
    sha = _sha256(path)
    if not path.read_bytes()[:4] == b"%PDF":
        return Document(doc_id=f"UPL-{sha[:10]}", source="upload", filename=original_name, path=str(path),
                        sha256=sha, status="rejected", metadata={"intake_error": "not a PDF"})
    return Document(doc_id=f"UPL-{sha[:10]}", external_id=f"UPL-{sha[:10]}", source="upload",
                    filename=original_name, path=str(path), sha256=sha, pages=pdf_text.page_count(str(path)))


def load_csv_rows() -> list[Document]:
    docs = []
    with open(DATA / "csv" / "ps01_documents_metadata.csv", encoding="utf-8") as f:
        docs += [from_ps01(r) for r in csv.DictReader(f)]
    with open(DATA / "csv" / "ps07_ingestion_queue.csv", encoding="utf-8") as f:
        docs += [from_ps07(r) for r in csv.DictReader(f)]
    return docs


def load_manifest() -> list[Document]:
    with open(DATA / "real_docs" / "manifest.csv", encoding="utf-8") as f:
        return [from_manifest(r) for r in csv.DictReader(f)]


def load_fixtures() -> list[Document]:
    return [from_fixture(p) for p in sorted((DATA / "fixtures").glob("*.json"))]


def accept(doc: Document, index: DedupIndex) -> None:
    """Exact-duplicate check (ID / sha256) and the intake audit event. Order matters: the
    first document seen is kept, later copies are held as duplicates and linked to it."""
    t0 = time.perf_counter()
    if doc.status == "rejected":
        audit.log(doc, "intake", "intake", decision="reject: " + doc.metadata.get("intake_error", ""),
                  duration_ms=audit.ms_since(t0), status="error")
        return
    duplicate_of, reason = index.check_exact(doc.doc_id, doc.external_id, doc.sha256)
    if duplicate_of:
        doc.duplicate_of, doc.duplicate_reason = duplicate_of, reason
        decision = f"hold duplicate of {duplicate_of} ({reason})"
    else:
        decision = "accepted"
    doc.status = "intake"
    audit.log(doc, "intake", "intake", decision=decision, confidence=1.0, duration_ms=audit.ms_since(t0),
              status="warning" if duplicate_of else "ok")
