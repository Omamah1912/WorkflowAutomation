"""PyMuPDF helpers: per-page text, words with bounding boxes, rows, search, rendering."""
import re
from functools import lru_cache

import pymupdf

MIN_TEXT_CHARS = 50  # a page with fewer non-space characters is treated as having no text layer


@lru_cache(maxsize=32)
def open_pdf(path: str) -> pymupdf.Document:
    return pymupdf.open(path)


def page_count(path: str) -> int:
    return open_pdf(path).page_count


def page_text(path: str, page_no: int) -> str:
    """Text of a 1-based page from the PDF text layer."""
    return open_pdf(path)[page_no - 1].get_text()


def has_text_layer(path: str, page_no: int) -> bool:
    return len(re.sub(r"\s", "", page_text(path, page_no))) >= MIN_TEXT_CHARS


def page_size(path: str, page_no: int) -> tuple[float, float]:
    rect = open_pdf(path)[page_no - 1].rect
    return rect.width, rect.height


def page_words(path: str, page_no: int) -> list[dict]:
    """Words with bboxes: [{'text', 'bbox': [x0,y0,x1,y1]}] in reading order."""
    words = open_pdf(path)[page_no - 1].get_text("words")
    return [{"text": w[4], "bbox": [round(v, 1) for v in w[:4]]} for w in words]


def rows_from_words(words: list[dict], tolerance: float = 3.0) -> list[dict]:
    """Group words into visual rows by vertical centre, so a table label and its numbers
    (often separate text blocks) end up on the same row. Returns [{'text', 'bbox', 'words'}]."""
    rows: list[dict] = []
    for w in sorted(words, key=lambda w: ((w["bbox"][1] + w["bbox"][3]) / 2, w["bbox"][0])):
        centre = (w["bbox"][1] + w["bbox"][3]) / 2
        if rows and abs(rows[-1]["centre"] - centre) <= tolerance:
            rows[-1]["words"].append(w)
        else:
            rows.append({"centre": centre, "words": [w]})
    out = []
    for r in rows:
        ws = sorted(r["words"], key=lambda w: w["bbox"][0])
        out.append({
            "text": " ".join(w["text"] for w in ws),
            "bbox": [min(w["bbox"][0] for w in ws), min(w["bbox"][1] for w in ws),
                     max(w["bbox"][2] for w in ws), max(w["bbox"][3] for w in ws)],
            "words": ws,
        })
    return out


def find_bbox(path: str, page_no: int, needle: str) -> list[float] | None:
    """Bounding box of the first occurrence of needle on the page (None if not found)."""
    if not needle.strip():
        return None
    hits = open_pdf(path)[page_no - 1].search_for(needle.strip()[:120])
    if not hits:
        return None
    r = hits[0]
    for extra in hits[1:]:  # a needle wrapping onto the next line returns several rects
        if extra.y0 - r.y1 < 15:
            r |= extra
        else:
            break
    return [round(r.x0, 1), round(r.y0, 1), round(r.x1, 1), round(r.y1, 1)]


def render_png(path: str, page_no: int, zoom: float = 1.5) -> bytes:
    """Rendered page image (used for the UI overlay and for OCR / LLM vision)."""
    pix = open_pdf(path)[page_no - 1].get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
    return pix.tobytes("png")
