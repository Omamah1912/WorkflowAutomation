"""Reference data: company master (from PSX) plus face values derived from filings.

Face value is never assumed. It comes from company_master.csv (PSX) if present, otherwise from
a filing that states both 'Rs X per share' and 'Y%' (X / Y% = face value), stored with
provenance and method 'derived_from_filing'. If neither exists it stays unknown.
"""
import csv
import json
import threading

from state import Evidence, FieldValue
from tools.config import DATA, RUNTIME

_lock = threading.Lock()
_DERIVED_PATH = RUNTIME / "face_values_derived.json"


def companies() -> dict[str, dict]:
    """symbol -> company_master row."""
    with open(DATA / "reference" / "company_master.csv", encoding="utf-8") as f:
        return {row["symbol"]: row for row in csv.DictReader(f)}


def shares_outstanding(symbol: str) -> FieldValue | None:
    row = companies().get(symbol or "")
    if not row or not row["shares_outstanding"]:
        return None
    return FieldValue(
        name="shares_outstanding", value=float(row["shares_outstanding"]), unit="shares", unit_type="count",
        confidence=0.95, method="classical",
        evidence=Evidence(source_url=row["source_url"],
                          text=f"PSX company page, Equity Profile 'Shares {int(row['shares_outstanding']):,}' "
                               f"(retrieved {row['retrieved_at']}; current figure, not as at the filing date)"))


def _load_derived() -> dict:
    if _DERIVED_PATH.exists():
        return json.loads(_DERIVED_PATH.read_text(encoding="utf-8"))
    return {}


def face_value(symbol: str) -> FieldValue | None:
    row = companies().get(symbol or "")
    if row and row["face_value_rs"]:
        return FieldValue(name="face_value", value=float(row["face_value_rs"]), unit="Rs per share",
                          unit_type="currency_per_share", confidence=0.95, method="classical",
                          evidence=Evidence(source_url=row["source_url"], text="PSX company page"))
    with _lock:
        derived = _load_derived().get(symbol or "")
    return FieldValue(**derived) if derived else None


def record_derived_face_value(symbol: str, field: FieldValue) -> str:
    """Store a face value derived from a filing. Returns 'new' | 'same' | 'conflict'."""
    with _lock:
        derived = _load_derived()
        existing = derived.get(symbol)
        if existing and abs(existing["value"] - field.value) > 0.01:
            return "conflict"   # keep the first one; the caller flags the document for review
        if existing:
            return "same"
        derived[symbol] = field.model_dump()
        RUNTIME.mkdir(parents=True, exist_ok=True)
        _DERIVED_PATH.write_text(json.dumps(derived, indent=2), encoding="utf-8")
        return "new"
