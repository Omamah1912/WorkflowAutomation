"""Classifier agent: filename regex -> keyword dictionary on first-page text -> fuzzy name match.
LLM fallback only when the classical confidence is below the threshold."""
import re
import time

from rapidfuzz import fuzz, process, utils

import llm
import prompts
from agents import extractor
from state import Document
from tools import audit
from tools.config import doc_types, thresholds

AGREE_CONFIDENCE = 0.97      # filename and keywords point to the same type
FILENAME_ONLY = 0.90
KEYWORD_ONLY = 0.85
CONFLICT = 0.50              # filename and keywords disagree -> needs the LLM or a human


def evidence_text(doc: Document) -> str:
    """The text we classify on: first PDF page, the CSV snippet, ps07's upstream label, or the fixture description."""
    if doc.source == "csv_ps01":
        return doc.metadata.get("ocr_text_snippet", "")
    if doc.source == "csv_ps07":
        return doc.metadata.get("document_type_detected", "")
    if doc.source == "fixture":
        return doc.metadata.get("description", "")
    return extractor.read_page(doc, 1)["text"] if doc.pages else ""


def _by_filename(filename: str) -> tuple[dict | None, str]:
    """Most specific (longest) filename pattern wins, so 'press_release_-_financial' beats 'press_release_\\d'."""
    best, best_len = None, 0
    for t in doc_types():
        for pattern in t["filename"]:
            if re.search(pattern, filename.lower()) and len(pattern) > best_len:
                best, best_len = t, len(pattern)
    return best, (f"filename matches '{best_len}'-char pattern" if best else "")


def _by_keywords(text: str) -> tuple[dict | None, str]:
    """Longest keyword found in the text wins (more specific phrase)."""
    flat = " ".join(text.lower().split())
    best, best_kw = None, ""
    for t in doc_types():
        for kw in t["keywords"]:
            if kw in flat and len(kw) > len(best_kw):
                best, best_kw = t, kw
    return best, best_kw


def classify(doc: Document) -> None:
    t0 = time.perf_counter()
    text = evidence_text(doc)
    by_name, _ = _by_filename(doc.metadata.get("original_url", "") + " " + doc.filename)
    by_kw, keyword = _by_keywords(text)

    if by_name and by_kw:
        chosen = by_kw  # the document's own words beat its filename
        confidence = AGREE_CONFIDENCE if by_name["name"] == by_kw["name"] else CONFLICT
        reason = f"filename -> {by_name['name']}, keyword '{keyword}' -> {by_kw['name']}"
    elif by_name or by_kw:
        chosen = by_name or by_kw
        confidence = FILENAME_ONLY if by_name else KEYWORD_ONLY
        reason = f"filename -> {by_name['name']}" if by_name else f"keyword '{keyword}'"
    else:  # fuzzy: compare the filename stem with type names
        names = {t["name"]: t for t in doc_types()}
        stem = re.sub(r"[_\d]+", " ", doc.filename.rsplit(".", 1)[0])
        name, score, _ = process.extractOne(stem, list(names), scorer=fuzz.token_set_ratio, processor=utils.default_process)
        chosen, confidence, reason = names[name], round(score / 100 * 0.8, 2), f"fuzzy filename match {score:.0f}%"
    confidence = min(confidence, chosen.get("max_confidence", 1.0))
    method = "classical"

    if confidence < thresholds()["classifier_confidence_min"]:
        try:
            out, method = llm.call_llm(
                prompts.CLASSIFY.format(types="\n".join(f"- {t['name']}" for t in doc_types()),
                                        filename=doc.filename, text=text[:3000]),
                prompts.ClassifyOut, "classifier", doc_id=doc.doc_id)
            llm_type = next((t for t in doc_types() if t["name"] == out.doc_type), None)
            if llm_type:
                chosen, confidence = llm_type, round(min(max(out.confidence, 0.0), 1.0), 2)
                reason += f"; LLM: {out.reason[:200]}"
            else:
                reason += f"; LLM returned unknown type '{out.doc_type}'"
        except llm.LLMUnavailable as e:
            reason += f"; LLM unavailable ({str(e)[:120]}) -> stays low confidence"

    doc.doc_type, doc.doc_type_confidence = chosen["name"], confidence
    doc.relevance, doc.stream = chosen["relevant"], chosen["stream"]
    doc.status = "classified"
    audit.log(doc, "classify", "classifier", method=method, confidence=confidence,
              decision=f"{doc.doc_type} | relevant={doc.relevance} | stream={doc.stream} | {reason}",
              duration_ms=audit.ms_since(t0),
              status="ok" if confidence >= thresholds()["classifier_confidence_min"] else "warning")
