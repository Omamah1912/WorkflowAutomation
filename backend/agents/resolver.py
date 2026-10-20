"""Resolver agent: for each critical rule failure, re-read the implicated fields on their source page.
  1) classical: OCR the page (if Tesseract exists and the page was read from its text layer)
  2) LLM: targeted re-read of that page (text, or the page image if it had no text)
A field is replaced only when the re-read gives a different value or unit AND its quote is on the page.
The orchestrator re-validates after a change; at most `resolver_max_loops` loops."""
import time

from rapidfuzz import fuzz

import llm
import prompts
from agents import extractor, validator
from state import Document, Evidence, FieldValue
from tools import audit, ocr, pdf_text, units
from tools.config import thresholds

DESCRIPTIONS = {
    "cash_dividend": "the cash dividend per share (Rs per share)",
    "cash_dividend_percent": "the cash dividend as a percentage",
    "bonus_shares": "the bonus share ratio (new shares per share held)",
}


def resolve(doc: Document) -> bool:
    """Returns True if any field changed (so the validator should run again)."""
    t0 = time.perf_counter()
    doc.resolver_loops += 1
    changed = False
    for track, rule in validator.critical_failures(doc):
        for name in rule.fields:
            field = track.get(name)
            if not field or name not in DESCRIPTIONS:
                continue
            if not field.evidence.page:
                audit.log(doc, "resolve", "resolver", track_id=track.track_id, rule_ids=[rule.rule_id],
                          method="none", status="warning", evidence=field.evidence,
                          decision=f"{name}: no source page to re-read (value came from {field.method}) -> unresolved")
                continue
            new = _reread(doc, field)
            if new and (new.value != field.value or new.unit_type != field.unit_type):
                track.put(new)
                changed = True
                audit.log(doc, "resolve", "resolver", track_id=track.track_id, rule_ids=[rule.rule_id],
                          method=new.method, confidence=new.confidence, evidence=new.evidence,
                          decision=f"{name}: {field.value} {field.unit} -> {new.value} {new.unit}")
            else:
                audit.log(doc, "resolve", "resolver", track_id=track.track_id, rule_ids=[rule.rule_id],
                          status="warning", decision=f"{name}: re-read confirms {field.value} {field.unit} -> unresolved")
    audit.log(doc, "resolve", "resolver", decision=f"loop {doc.resolver_loops}: {'changed' if changed else 'nothing fixed'}",
              duration_ms=audit.ms_since(t0))
    return changed


def _reread(doc: Document, field: FieldValue) -> FieldValue | None:
    page_no = field.evidence.page
    page = extractor.read_page(doc, page_no)
    if page["method"] == "text_layer" and ocr.available():
        result = ocr.ocr_page(doc.path, page_no)
        ocr_page = {"text": result["text"], "rows": pdf_text.rows_from_words(result["words"]), "method": "ocr_tesseract"}
        for hit in extractor.parse_page(ocr_page):
            if hit.name == field.name:
                return extractor.make_field(doc, page_no, ocr_page, hit)
    try:
        image = None if page["text"].strip() else pdf_text.render_png(doc.path, page_no)
        out, method = llm.call_llm(
            prompts.EXTRACT_FIELD.format(description=DESCRIPTIONS[field.name], page=page_no,
                                         text=extractor.flat_text(page)[:4000] or "(see image)"),
            prompts.FieldOut, "resolver", image_png=image, doc_id=doc.doc_id)
    except llm.LLMUnavailable as e:
        audit.log(doc, "resolve", "resolver", method="none", status="warning",
                  decision=f"{field.name}: LLM re-read unavailable ({str(e)[:100]})")
        return None
    if not out.found or out.value is None:
        return None
    if page["text"].strip() and fuzz.partial_ratio(out.source_text.lower(), extractor.flat_text(page).lower()) < 90:
        return None  # the LLM's quote is not on the page: do not trust it
    unit = out.unit or field.unit
    return FieldValue(name=field.name, value=out.value, unit=unit,
                      unit_type=units.unit_type_of(unit) if field.name != "cash_dividend_percent" else "percent",
                      confidence=thresholds()["field_confidence"]["llm"], method=method,
                      evidence=Evidence(doc_id=doc.doc_id, page=page_no, text=out.source_text[:300],
                                        bbox=pdf_text.find_bbox(doc.path, page_no, out.source_text)
                                        if page["method"] == "text_layer" else None))


def unresolved(doc: Document) -> bool:
    return bool(validator.critical_failures(doc))

