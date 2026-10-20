"""Extractor agent: read each page (text layer -> Tesseract OCR -> LLM vision -> unread),
parse announcement fields and statement figures with regex, and attach provenance
(document, page, bbox, source text) to every value. LLM fallback when a critical field
or the company is not found classically."""
import re
import threading
import time

from rapidfuzz import fuzz, process, utils

import llm
import prompts
from state import Document, Evidence, FieldValue, Track
from tools import audit, ocr, patterns, pdf_text, reference
from tools.config import thresholds

PAGE_CACHE: dict[tuple[str, int], dict] = {}
_cache_lock = threading.Lock()

# Addressees / registrars that appear in every letter but are never the issuer.
NOT_ISSUER = ("stock exchange", "securities and exchange", "central depository", "clearing company",
              "registrar", "(pvt)", "(private)")
VISION_TIMEOUT_S = 90       # transcribing a dense statement page takes 30-60 s
CRITICAL = {"Financial Results": ["cash_dividend", "cash_dividend_percent"],
            "Dividend Credit Notice": ["cash_dividend"]}


# ---------------------------------------------------------------- page reading

def read_page(doc: Document, page_no: int) -> dict:
    """{'text', 'rows', 'method'} for one page, cached. method is how the text was obtained."""
    key = (doc.doc_id, page_no)
    with _cache_lock:
        if key in PAGE_CACHE:
            doc.page_methods[page_no] = PAGE_CACHE[key]["method"]  # a re-run creates a fresh Document
            return PAGE_CACHE[key]
    t0 = time.perf_counter()
    if pdf_text.has_text_layer(doc.path, page_no):
        words = pdf_text.page_words(doc.path, page_no)
        page = {"text": pdf_text.page_text(doc.path, page_no), "rows": pdf_text.rows_from_words(words),
                "method": "text_layer"}
    elif ocr.available():
        result = ocr.ocr_page(doc.path, page_no)
        page = {"text": result["text"], "rows": pdf_text.rows_from_words(result["words"]), "method": "ocr_tesseract"}
    else:
        page = _vision_or_unread(doc, page_no)
    doc.page_methods[page_no] = page["method"]
    if page["method"] != "text_layer":
        audit.log(doc, "extract", "extractor", method=_audit_method(page["method"]),
                  decision=f"page {page_no} has no text layer -> read via {page['method']}",
                  duration_ms=audit.ms_since(t0), status="ok" if page["method"] != "unread" else "warning")
    with _cache_lock:
        PAGE_CACHE[key] = page
    return page


def _vision_or_unread(doc: Document, page_no: int) -> dict:
    """No Tesseract: send the rendered page to the LLM (capped per document), else leave it unread."""
    used = sum(1 for m in doc.page_methods.values() if m.startswith("llm_"))
    if not llm.configured_providers() or used >= thresholds()["llm_vision_max_pages"]:
        return {"text": "", "rows": [], "method": "unread"}
    try:
        out, method = llm.call_llm(prompts.TRANSCRIBE_PAGE, prompts.TranscribeOut, "extractor_vision",
                                   image_png=pdf_text.render_png(doc.path, page_no), doc_id=doc.doc_id,
                                   timeout_s=VISION_TIMEOUT_S)
        # One row per transcribed line (no bboxes: the LLM does not give positions).
        rows = [{"text": line, "bbox": None, "words": [{"text": w, "bbox": None} for w in line.split()]}
                for line in out.text.splitlines() if line.strip()]
        return {"text": out.text, "rows": rows, "method": method}
    except llm.LLMUnavailable:
        return {"text": "", "rows": [], "method": "unread"}


def flat_text(page: dict) -> str:
    """Page text in natural reading order, whitespace collapsed."""
    return " ".join(page["text"].split())


def rows_text(page: dict) -> str:
    """Page text as visual rows (keeps a table label and its value together: 'CASH DIVIDEND ... NIL')."""
    return " ".join(row["text"] for row in page["rows"])


def parse_page(page: dict) -> list[patterns.Hit]:
    """Natural reading order first; visual rows only fill in fields still missing
    (rows can scramble skewed OCR lines, so they are the second choice)."""
    hits = patterns.parse_announcement(flat_text(page))
    found = {h.name for h in hits}
    if page["rows"]:
        hits += [h for h in patterns.parse_announcement(rows_text(page)) if h.name not in found]
    return hits


def _audit_method(page_method: str) -> str:
    return {"text_layer": "classical", "unread": "none"}.get(page_method, page_method)


def _confidence(page_method: str) -> float:
    conf = thresholds()["field_confidence"]
    return conf["llm"] if page_method.startswith("llm_") else conf.get(page_method, 0.0)


def _bbox(doc: Document, page_no: int, page: dict, snippet: str) -> list[float] | None:
    """Locate the snippet on the page: PDF text search, falling back to its first 40 chars / first number."""
    number = re.search(r"\d[\d,.]*", snippet)
    if page["method"] == "text_layer":
        first_words = " ".join(snippet.split()[:2])
        for needle in (snippet, snippet[:40], number.group(0) if number else "", first_words):
            box = pdf_text.find_bbox(doc.path, page_no, needle)
            if box:
                return box
    elif page["method"] == "ocr_tesseract" and number:  # OCR words carry their own bboxes
        for row in page["rows"]:
            for w in row["words"]:
                if number.group(0) in w["text"]:
                    return w["bbox"]
    return None


def make_field(doc, page_no, page, hit: patterns.Hit, method=None, confidence=None) -> FieldValue:
    return FieldValue(
        name=hit.name, value=hit.value, unit=hit.unit, unit_type=hit.unit_type,
        confidence=confidence if confidence is not None else _confidence(page["method"]),
        method=method or _audit_method(page["method"]),
        evidence=Evidence(doc_id=doc.doc_id, page=page_no, bbox=_bbox(doc, page_no, page, hit.snippet),
                          text=hit.snippet[:300]))


# ---------------------------------------------------------------- company

def find_company(doc: Document, pages: list[tuple[int, dict]]) -> None:
    """1) '... Limited' line matched to company master  2) fuzzy scan  3) LLM (verified quote).
    Looks at the first two pages: names often appear only in the signature or statement header."""
    for page_no, page in pages:
        if _find_company_on_page(doc, page_no, page, use_llm=False):
            return
    _find_company_on_page(doc, pages[0][0], pages[0][1], use_llm=True)


def _find_company_on_page(doc: Document, page_no: int, page: dict, use_llm: bool) -> bool:
    names = {sym: row["company"] for sym, row in reference.companies().items()}
    text, flat = page["text"], flat_text(page)
    method, symbol, name, snippet, confidence = None, None, None, "", 0.0

    for line in text.splitlines():
        line = re.sub(r"^(?:for and )?on behalf of\s+|^for\s+", "", " ".join(line.split()), flags=re.I)
        m = re.search(r"([A-Z][A-Za-z0-9&.,()'\- ]{2,80}?\b(?:Limited|LIMITED|Ltd\.?|LTD\.?|Modaraba))\b", line)
        if m and not any(w in m.group(1).lower() for w in NOT_ISSUER):
            best = process.extractOne(m.group(1), names, scorer=fuzz.token_sort_ratio, processor=utils.default_process)
            if best and best[1] >= 85:
                name, symbol, snippet = best[0], best[2], m.group(1)
                confidence, method = _confidence(page["method"]), _audit_method(page["method"])
                break
    if not symbol:
        for sym, master_name in names.items():
            al = fuzz.partial_ratio_alignment(master_name.lower(), flat.lower())
            if al and al.score >= 88:
                name, symbol, snippet = master_name, sym, flat[al.dest_start:al.dest_end]
                confidence, method = round(al.score / 100 * _confidence(page["method"]), 2), _audit_method(page["method"])
                break
    if not symbol and flat and use_llm:
        try:
            out, llm_method = llm.call_llm(prompts.COMPANY.format(text=flat[:4000]), prompts.CompanyOut,
                                           "extractor_company", doc_id=doc.doc_id)
            quote_ok = out.found and out.source_text and fuzz.partial_ratio(out.source_text.lower(), flat.lower()) >= 90
            if quote_ok:
                best = process.extractOne(out.company or out.source_text, names, scorer=fuzz.token_sort_ratio,
                                          processor=utils.default_process)
                # classical confirmation: the verbatim quote itself must resemble the master name
                if best and best[1] >= 85 and fuzz.partial_ratio(best[0].lower(), out.source_text.lower()) >= 75:
                    name, symbol = best[0], best[2]
                else:
                    name = out.company
                snippet, confidence, method = out.source_text, thresholds()["field_confidence"]["llm"], llm_method
        except llm.LLMUnavailable as e:
            audit.log(doc, "extract", "extractor", method="none", decision=f"company: LLM unavailable ({str(e)[:100]})",
                      status="warning")
    if not name:
        if use_llm:
            audit.log(doc, "extract", "extractor", decision="company not found -> needs_review", status="warning")
        return False
    if method.startswith("llm_") and symbol:
        confidence, snippet = _corroborate(doc, name, confidence, snippet)
    doc.symbol = symbol
    doc.company = FieldValue(name="company", value=name, unit_type="text", confidence=confidence, method=method,
                             evidence=Evidence(doc_id=doc.doc_id, page=page_no, text=snippet[:300],
                                               bbox=_bbox(doc, page_no, page, snippet) if method == "classical" else None))
    audit.log(doc, "extract", "extractor", method=method, confidence=confidence,
              decision=f"company = {name} ({symbol or 'not in company master'})", evidence=doc.company.evidence)
    return True


CORROBORATION_MIN = 75      # fuzzy % of the master name found in the page-1 text layer
CORROBORATED_CONFIDENCE = 0.85


def _corroborate(doc: Document, name: str, confidence: float, snippet: str) -> tuple[float, str]:
    """An LLM-read company name is trusted only if the page-1 text layer also shows it (even OCR-garbled,
    e.g. 'Attied Bank Umited' for 'Allied Bank Limited'). This is the classical confirmation."""
    first = read_page(doc, 1)
    if first["method"] != "text_layer":
        return confidence, snippet
    al = fuzz.partial_ratio_alignment(name.lower(), flat_text(first).lower())
    if al and al.score >= CORROBORATION_MIN:
        seen = flat_text(first)[al.dest_start:al.dest_end]
        return CORROBORATED_CONFIDENCE, f"{snippet} | corroborated on p1 text layer: '{seen}' ({al.score:.0f}%)"
    return confidence, snippet


# ---------------------------------------------------------------- main entry

def extract(doc: Document) -> None:
    if doc.source == "fixture":
        return extract_fixture(doc)
    t0 = time.perf_counter()
    doc.status = "extracting"
    fields: list[FieldValue] = []
    first = read_page(doc, 1)
    find_company(doc, [(n, read_page(doc, n)) for n in range(1, min(doc.pages, 2) + 1)])

    for hit in parse_page(first):
        if hit.name == "period":
            doc.period = make_field(doc, 1, first, hit)
        else:
            fields.append(make_field(doc, 1, first, hit))

    for page_no in range(1, doc.pages + 1):
        page = read_page(doc, page_no)
        row = patterns.profit_row(page["rows"], page["text"]) if page["rows"] else None
        if row:
            fields.append(FieldValue(
                name="profit_after_tax", value=row["value"], unit=f"Rs x {row['scale']}" if row["scale"] > 1 else "Rs",
                unit_type="amount", confidence=_confidence(page["method"]), method=_audit_method(page["method"]),
                evidence=Evidence(doc_id=doc.doc_id, page=page_no, bbox=row["word"]["bbox"], text=row["row_text"][:200])))

    _llm_fallback_for_critical(doc, first, fields)
    doc.tracks = [Track(track_id=f"{doc.doc_id}/raw", entity_label="raw", fields=fields)]
    for f in fields:
        audit.log(doc, "extract", "extractor", method=f.method, confidence=f.confidence,
                  decision=f"{f.name} = {f.value} {f.unit}".strip(), evidence=f.evidence)
    audit.log(doc, "extract", "extractor", decision=f"{len(fields)} fields; pages read: {_page_summary(doc)}",
              duration_ms=audit.ms_since(t0))


def _page_summary(doc: Document) -> str:
    counts: dict[str, int] = {}
    for m in doc.page_methods.values():
        counts[m] = counts.get(m, 0) + 1
    return ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))


def _llm_fallback_for_critical(doc: Document, page: dict, fields: list[FieldValue]) -> None:
    critical = CRITICAL.get(doc.doc_type, [])
    if not critical or any(f.name in critical for f in fields) or not flat_text(page):
        return
    try:
        out, method = llm.call_llm(
            prompts.EXTRACT_FIELD.format(description="the cash dividend per share declared or credited "
                                         "(Rs per share; if it says NIL return 0; if only a % is given return the % with unit '%')",
                                         page=1, text=flat_text(page)[:4000]),
            prompts.FieldOut, "extractor_field", doc_id=doc.doc_id)
    except llm.LLMUnavailable as e:
        audit.log(doc, "extract", "extractor", method="none", status="warning",
                  decision=f"cash dividend not found classically; LLM unavailable ({str(e)[:100]})")
        return
    if not out.found or out.value is None:
        audit.log(doc, "extract", "extractor", method=method, decision="cash dividend: LLM also found nothing", status="warning")
        return
    quote_ok = bool(out.source_text) and fuzz.partial_ratio(out.source_text.lower(), flat_text(page).lower()) >= 90
    is_percent = "%" in out.unit or "percent" in out.unit.lower()
    hit = patterns.Hit("cash_dividend_percent" if is_percent else "cash_dividend", out.value,
                       "%" if is_percent else (out.unit or "Rs per share"),
                       "percent" if is_percent else "currency_per_share", out.source_text)
    field = make_field(doc, 1, page, hit, method=method,
                       confidence=thresholds()["field_confidence"]["llm"] if quote_ok else 0.3)
    fields.append(field)
    audit.log(doc, "extract", "extractor", method=method, confidence=field.confidence, evidence=field.evidence,
              decision=f"{hit.name} = {out.value} from LLM ({'quote found on page' if quote_ok else 'QUOTE NOT ON PAGE'})",
              status="warning")


def extract_fixture(doc: Document) -> None:
    """Fixture values come from public reporting (cited in the fixture), never from a PDF."""
    t0 = time.perf_counter()
    data = doc.metadata
    fields = []
    for f in data["fields"]:
        fields.append(FieldValue(name=f["name"], value=f["value"], unit=f.get("unit", ""), unit_type="text",
                                 confidence=0.95, method="fixture",
                                 evidence=Evidence(doc_id=doc.doc_id, text=f["evidence"], source_url=f.get("source_url"))))
    doc.company = FieldValue(name="company", value=data["company"], unit_type="text", confidence=0.95, method="fixture",
                             evidence=Evidence(doc_id=doc.doc_id, text=data["company"]))
    doc.tracks = [Track(track_id=f"{doc.doc_id}/raw", entity_label="raw", fields=fields)]
    audit.log(doc, "extract", "extractor", method="fixture",
              decision=f"{len(fields)} fields loaded from labelled reconstruction", duration_ms=audit.ms_since(t0))
