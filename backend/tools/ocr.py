"""Tesseract OCR for pages without a text layer. Optional: if the tesseract binary is not
installed (e.g. local Windows dev), available() is False and callers use the LLM vision fallback."""
import io
import shutil
from functools import lru_cache

from tools import pdf_text

OCR_ZOOM = 2.0  # render at 144 dpi; bboxes are scaled back to PDF points


@lru_cache(maxsize=1)
def available() -> bool:
    return shutil.which("tesseract") is not None


def ocr_page(path: str, page_no: int) -> dict:
    """OCR one page. Returns {'text': str, 'words': [{'text', 'bbox'}]} with bboxes in PDF points."""
    import pytesseract
    from PIL import Image

    image = Image.open(io.BytesIO(pdf_text.render_png(path, page_no, zoom=OCR_ZOOM)))
    data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
    words, lines, current_key = [], [], None
    for i, word in enumerate(data["text"]):
        if not word.strip() or float(data["conf"][i]) < 0:
            continue
        x, y, w, h = (data[k][i] / OCR_ZOOM for k in ("left", "top", "width", "height"))
        words.append({"text": word, "bbox": [round(x, 1), round(y, 1), round(x + w, 1), round(y + h, 1)]})
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        if key != current_key:
            lines.append([])
            current_key = key
        lines[-1].append(word)
    return {"text": "\n".join(" ".join(line) for line in lines), "words": words}
