"""Transformer agent.
transform()       (before the batch barrier) split the raw fields into entity tracks, normalise units,
                  type every per-share figure, derive face value from 'Rs X per share i.e. Y%'.
apply_reference() (after the barrier) attach reference data (shares outstanding, face value) and
                  convert percent-only dividends to Rs per share - only with a known face value.
"""
import time

import llm
import prompts
from agents import extractor
from state import Document, Evidence, FieldValue, Track
from tools import audit, patterns, reference, units

ANNOUNCEMENT_FIELDS = {"cash_dividend", "cash_dividend_percent", "bonus_shares", "announcement_date",
                       "book_closure_from", "book_closure_to", "dividend_number", "declared_cash_dividend",
                       "eligible_shares", "shares_outstanding"}
PRIMARY_ORDER = ["unconsolidated", "standalone", "company", "consolidated"]  # who pays the dividend


def page_entities(doc: Document) -> dict[int, str]:
    """page -> entity label from statement headings; continuation pages inherit the previous label.
    Page 1 (cover letter) is the announcement."""
    labels, current = {}, None
    for page_no in range(2, doc.pages + 1):
        page = extractor.read_page(doc, page_no)
        top = " ".join(page["text"].split()[:40])  # heading area
        current = patterns.entity_label(top) or current
        if current:
            labels[page_no] = current
    return labels


def _unclear_boundaries(doc: Document, labels: dict[int, str]) -> bool:
    """The cover letter mentions several entities but we could not label any statement page."""
    cover = extractor.flat_text(extractor.read_page(doc, 1)).lower()
    mentions_many = "consolidated" in cover and ("standalone" in cover or "unconsolidated" in cover)
    return mentions_many and len(set(labels.values())) < 2


def _llm_split(doc: Document) -> tuple[dict[int, str], str]:
    """LLM fallback for entity boundaries, using the first lines of each readable page."""
    readable = {n: " ".join(extractor.read_page(doc, n)["text"].split()[:60]) for n in range(2, doc.pages + 1)
                if extractor.read_page(doc, n)["method"] != "unread"}
    if not readable:
        raise llm.LLMUnavailable("no readable statement pages")
    out, method = llm.call_llm(
        prompts.SPLIT_ENTITIES.format(pages="\n".join(f"Page {n}: {t}" for n, t in readable.items())),
        prompts.SplitOut, "transformer_split", doc_id=doc.doc_id)
    labels = {p.page: p.entity for p in out.pages if p.entity in ("unconsolidated", "consolidated", "standalone")}
    return labels, method


def transform(doc: Document) -> None:
    t0 = time.perf_counter()
    raw = doc.tracks[0].fields if doc.tracks else []
    labels, method = ({}, "classical")
    if doc.source != "fixture" and doc.pages > 1:
        labels = page_entities(doc)
        if _unclear_boundaries(doc, labels):
            try:
                labels, method = _llm_split(doc)
            except llm.LLMUnavailable as e:
                doc.complexity.append("entity boundaries unclear: cover mentions several entities, "
                                      f"statement pages could not be labelled ({str(e)[:80]})")

    entities = sorted(set(labels.values()), key=PRIMARY_ORDER.index) or ["company"]
    tracks = {e: Track(track_id=f"{doc.doc_id}/{e}", entity_label=e,
                       pages=sorted(p for p, lab in labels.items() if lab == e)) for e in entities}
    primary = tracks[entities[0]]
    for field in raw:
        field = _normalise(field)
        page = field.evidence.page
        target = tracks.get(labels.get(page)) if page and page in labels else None
        if field.name == "profit_after_tax" and target and target.get("profit_after_tax"):
            continue  # first profit row per entity is the income statement; later ones are other statements
        (target if (target and field.name not in ANNOUNCEMENT_FIELDS) else primary).put(field)
    doc.tracks = list(tracks.values())

    _derive_face_value(doc, primary)
    audit.log(doc, "transform", "transformer", method=method,
              decision=f"{len(doc.tracks)} track(s): {', '.join(t.entity_label + ' p' + str(t.pages or [1]) for t in doc.tracks)}",
              duration_ms=audit.ms_since(t0))


def _normalise(field: FieldValue) -> FieldValue:
    """Rs '000 -> Rs; type every per-share unit from its text (the DIV-01 input)."""
    if field.name == "profit_after_tax" and field.unit.startswith("Rs x "):
        scale = int(field.unit.split("x ")[1])
        field = field.model_copy(update={"value": units.to_rupees(field.value, scale), "unit": "Rs",
                                         "derived_from": [f"profit_after_tax (Rs '{scale:,}'s)"]})
    if field.name in ("cash_dividend", "declared_cash_dividend", "bonus_shares"):
        field = field.model_copy(update={"unit_type": units.unit_type_of(field.unit)})
    elif field.name in ("eligible_shares", "shares_outstanding"):
        field = field.model_copy(update={"unit_type": "count"})
    elif field.name == "cash_dividend_percent":
        field = field.model_copy(update={"unit_type": "percent"})
    return field


def _derive_face_value(doc: Document, track: Track) -> None:
    """'Rs 6 per share i.e. 60%' -> face value Rs 10, stored with provenance (method derived_from_filing)."""
    rs, pct = track.get("cash_dividend"), track.get("cash_dividend_percent")
    if not (rs and pct and rs.value and pct.value and rs.unit_type == "currency_per_share"):
        return
    face = units.face_value_from(rs.value, pct.value)
    field = FieldValue(name="face_value", value=face, unit="Rs per share", unit_type="currency_per_share",
                       confidence=min(rs.confidence, pct.confidence), method="derived_from_filing",
                       evidence=Evidence(doc_id=doc.doc_id, page=pct.evidence.page, bbox=pct.evidence.bbox,
                                         text=pct.evidence.text),
                       derived_from=["cash_dividend", "cash_dividend_percent"])
    if not doc.symbol:
        audit.log(doc, "transform", "transformer", method="derived_from_filing", evidence=field.evidence,
                  decision=f"face value Rs {face:g} derivable but company unknown -> not stored", status="warning")
        return
    outcome = reference.record_derived_face_value(doc.symbol, field)
    if outcome == "conflict":
        doc.complexity.append(f"face value Rs {face:g} from this filing conflicts with the stored value")
    audit.log(doc, "transform", "transformer", method="derived_from_filing", confidence=field.confidence,
              evidence=field.evidence, status="warning" if outcome == "conflict" else "ok",
              decision=f"face value {doc.symbol} = Rs {rs.value:g} / {pct.value:g}% = Rs {face:g} ({outcome})")


def apply_reference(doc: Document) -> None:
    """Attach shares outstanding + face value from reference data; convert percent-only dividends."""
    if doc.source == "fixture" or not doc.tracks:
        return
    t0 = time.perf_counter()
    primary = doc.tracks[0]
    notes = []
    shares = reference.shares_outstanding(doc.symbol)
    if shares and not primary.get("shares_outstanding"):
        primary.put(shares)
        notes.append(f"shares outstanding {shares.value:,.0f}")
    face = reference.face_value(doc.symbol)
    if face:
        primary.put(face)
        notes.append(f"face value Rs {face.value:g} ({face.method}, from {face.evidence.doc_id or face.evidence.source_url})")
    pct, rs = primary.get("cash_dividend_percent"), primary.get("cash_dividend")
    if pct and pct.value and not rs:
        if face:
            converted = units.percent_to_rs_per_share(pct.value, face.value)
            primary.put(FieldValue(
                name="cash_dividend", value=converted, unit="Rs per share", unit_type="currency_per_share",
                confidence=min(pct.confidence, face.confidence), method="classical", evidence=pct.evidence,
                derived_from=["cash_dividend_percent", "face_value"]))
            notes.append(f"converted {pct.value:g}% x Rs {face.value:g} = Rs {converted:g} per share")
        else:
            doc.complexity.append(f"percent-only dividend ({pct.value:g}%) and face value unknown")
            notes.append("percent-only dividend; face value unknown -> cannot convert")
    audit.log(doc, "transform", "transformer", decision="reference: " + ("; ".join(notes) or "nothing to attach"),
              duration_ms=audit.ms_since(t0), status="warning" if "cannot convert" in " ".join(notes) else "ok")

