"""Every LLM prompt in one place, with the Pydantic schema its reply must match.
Prompts always ask for a verbatim `source_text` so the caller can check the answer against the
page (an LLM value whose quote is not on the page is treated as unconfirmed)."""
from typing import Optional

from pydantic import BaseModel


class ClassifyOut(BaseModel):
    doc_type: str
    confidence: float
    reason: str


CLASSIFY = """Classify this document into exactly one of these types:
{types}

Filename: {filename}
First-page text (may be OCR noise or a placeholder):
---
{text}
---
If the text does not let you decide, pick the closest type and give a low confidence (< 0.5)."""


class FieldOut(BaseModel):
    found: bool
    value: Optional[float] = None
    unit: str = ""
    source_text: str = ""


EXTRACT_FIELD = """From the page text below, extract: {description}
Return value as a number (no commas), unit as written (e.g. "Rs per share", "%", "shares per share"),
and source_text as the exact words from the page that contain the value (copy them verbatim).
If it is not on the page, return found=false.
Page {page} text:
---
{text}
---"""


class CompanyOut(BaseModel):
    found: bool
    company: Optional[str] = None
    source_text: str = ""


COMPANY = """Which listed company issued this letter to the stock exchange? Ignore the addressee
(Pakistan Stock Exchange, SECP) and the share registrar. Copy the company name exactly as written
into source_text. If no company name is written in the text, return found=false.
Text:
---
{text}
---"""


class TranscribeOut(BaseModel):
    text: str


TRANSCRIBE_PAGE = """This is a scanned page of a stock-exchange filing. Transcribe all text on it,
keeping each table row on its own line with its numbers in order. Do not add anything that is not
on the page. Return the transcription in `text`."""


class PageEntity(BaseModel):
    page: int
    entity: str          # unconsolidated | consolidated | standalone | announcement


class SplitOut(BaseModel):
    pages: list[PageEntity]


SPLIT_ENTITIES = """A filing contains financial statements for more than one reporting entity.
For each page below, say which entity its statements belong to: one of
unconsolidated, consolidated, standalone, announcement (cover letter / no statements).
{pages}"""


class ConsequenceOut(BaseModel):
    sentence: str


CONSEQUENCE = """Write ONE plain-English sentence (max 40 words) telling a reviewer what would happen
if this entry were approved as-is. Use only the facts below; do not add numbers that are not given.
Document: {doc}
Failed checks:
{failures}"""
