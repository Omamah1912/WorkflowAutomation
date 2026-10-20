"""Pure regex parsers for PSX announcement text (the format of Correspondence Manual Form-3/7/9).
Input is one page of text flattened into visual rows; output is a list of Hit tuples.
No I/O here, so every pattern can be unit-tested on a string."""
import re
from typing import NamedTuple

from rapidfuzz import fuzz

from tools import units

DATE = units.DATE_PATTERN
NUMBER = r"[\d,]*\.?\d+"


class Hit(NamedTuple):
    name: str
    value: object
    unit: str
    unit_type: str
    snippet: str          # exact text the value was read from (used for bbox lookup + evidence)


def _window(flat: str, start_pattern: str, size: int = 400) -> tuple[str, int]:
    m = re.search(start_pattern, flat, re.I)
    return (flat[m.start(): m.start() + size], m.start()) if m else ("", -1)


def cash_dividend(flat: str) -> list[Hit]:
    """'Rs. 10 per share (i.e. 100%)', 'Rs 6/- per share i.e. 60 percent', 'CASH DIVIDEND : NIL',
    'Rs. NIL per share', percent-only 'Cash Dividend 40%'."""
    window, _ = _window(flat, r"cash\s*dividend")
    if not window:
        return []
    rs = re.search(r"(?:rs\.?|rupees)\s*(" + NUMBER + r")\s*/?-?\s*per\s*share", window, re.I)
    if rs:
        hits = [Hit("cash_dividend", units.parse_number(rs.group(1)), "Rs per share", "currency_per_share", rs.group(0))]
        pct = re.match(r"\s*\(?\s*i\s*[.,]?\s*e\s*[.,]*\s*:?\s*(" + NUMBER + r")\s*(%|percent)", window[rs.end():], re.I)
        if pct:
            hits.append(Hit("cash_dividend_percent", units.parse_number(pct.group(1)), "%", "percent",
                            (rs.group(0) + window[rs.end():rs.end() + pct.end()]).strip()))
        return hits
    nil = re.search(r"cash\s*dividend\s*[:\-]?\s*nil\b|rs\.?\s*nil\s*per\s*share", window, re.I)
    if nil:
        return [Hit("cash_dividend", 0.0, "Rs per share (NIL)", "currency_per_share", nil.group(0))]
    pct_only = re.search(r"cash\s*dividend\s*[:\-]?\s*@?\s*(" + NUMBER + r")\s*(%|percent)", window, re.I)
    if pct_only:
        return [Hit("cash_dividend_percent", units.parse_number(pct_only.group(1)), "%", "percent", pct_only.group(0))]
    return []


def bonus_shares(flat: str) -> list[Hit]:
    window, _ = _window(flat, r"bonus\s*shares?", 300)
    if not window:
        return []
    ratio = re.search(r"proportion\s+of\s+(\d+)\s*shares?\s*(?:\(s\))?\s*for\s+every\s+(\d+)\s*shares?", window, re.I)
    if ratio:
        value = int(ratio.group(1)) / int(ratio.group(2))
        return [Hit("bonus_shares", value, f"{ratio.group(1)} share(s) for every {ratio.group(2)} share(s)",
                    "share_ratio", ratio.group(0))]
    nil = re.search(r"bonus\s*shares?\s*[:\-]?\s*nil\b|proportion\s+of\s+nil", window, re.I)
    if nil:
        return [Hit("bonus_shares", 0.0, "share(s) for every share(s) (NIL)", "share_ratio", nil.group(0))]
    return []


ITEMS = {
    "item_cash_dividend": r"cash\s*dividend",
    "item_bonus_shares": r"bonus\s*shares?",
    "item_right_shares": r"right\s*shares?",
    "item_other_entitlement": r"other\s*entitlement|corporate\s*action",
    "item_price_sensitive": r"price[\s-]*sensitive",
}


def announcement_items(flat: str) -> list[Hit]:
    hits = []
    for name, pattern in ITEMS.items():
        m = re.search(pattern, flat, re.I)
        if m:
            hits.append(Hit(name, True, "", "flag", m.group(0)))
    return hits


def period_end(flat: str) -> list[Hit]:
    m = re.search(r"(?:quarter|year|period|months)\s+(?:ended|ending)\s+(?:on\s+)?(" + DATE + ")", flat, re.I)
    if m and units.parse_date(m.group(1)):
        return [Hit("period", units.parse_date(m.group(1)), "", "date", m.group(0))]
    return []


def announcement_date(flat: str) -> list[Hit]:
    """Letter date: an explicit 'Date: ...', else the first date before 'Dear Sir' that is not a period end."""
    explicit = re.search(r"date\s*:\s*(" + DATE + ")", flat, re.I)
    if explicit and units.parse_date(explicit.group(1)):
        return [Hit("announcement_date", units.parse_date(explicit.group(1)), "", "date", explicit.group(0))]
    salutation = re.search(r"dear\s+s", flat, re.I)
    header = flat[: salutation.start()] if salutation else flat
    for m in re.finditer(DATE, header, re.I):
        before = header[max(0, m.start() - 20): m.start()].lower()
        if "ended" not in before and "ending" not in before and units.parse_date(m.group(0)):
            return [Hit("announcement_date", units.parse_date(m.group(0)), "", "date", m.group(0))]
    return []


def book_closure(flat: str) -> list[Hit]:
    day = r"(?:[a-z]+day,?\s+)?"
    m = re.search(r"closed\s*(?:\([^)]*\)\s*)?from\s+" + day + "(" + DATE + r")\s*(?:to|till|until)\s+" + day +
                  "(" + DATE + ")", flat, re.I)
    if not m:
        return []
    start, end = units.parse_date(m.group(1)), units.parse_date(m.group(2))
    if not (start and end):
        return []
    return [Hit("book_closure_from", start, "", "date", m.group(0)), Hit("book_closure_to", end, "", "date", m.group(0))]


def dividend_number(flat: str) -> list[Hit]:
    m = re.search(r"\(\s*D\s*-\s*(\d+)\s*\)", flat)
    return [Hit("dividend_number", f"D-{m.group(1)}", "", "text", m.group(0))] if m else []


ANNOUNCEMENT_PARSERS = [cash_dividend, bonus_shares, announcement_items, period_end, announcement_date,
                        book_closure, dividend_number]


def parse_announcement(flat: str) -> list[Hit]:
    return [hit for parser in ANNOUNCEMENT_PARSERS for hit in parser(flat)]


# ---------------------------------------------------------------- statements

PROFIT_LABELS = ["profit for the year", "profit for the period", "profit after taxation", "profit after tax"]
STATEMENT_PAGE = r"profit\s*(?:or|and|&)\s*loss|income\s*statement|statement\s*of\s*income|financial\s*results"
NUMBER_TOKEN = re.compile(r"^\(?[\d,]{3,}(?:\.\d+)?\)?$")


def profit_row(rows: list[dict], page_text: str) -> dict | None:
    """Find the 'Profit for the year/period' row and its first number (current period).
    Labels are matched fuzzily because statement pages are often OCR'd ('Profit for the yoar').
    Returns {'value', 'scale', 'label', 'word'} or None."""
    if not re.search(STATEMENT_PAGE, page_text, re.I):
        return None
    for row in rows:
        words = row["words"]
        first_num = next((i for i, w in enumerate(words) if NUMBER_TOKEN.match(w["text"].strip("“\"'"))), None)
        if first_num is None or first_num == 0:
            continue
        label = " ".join(w["text"] for w in words[:first_num]).lower()
        if max(fuzz.ratio(label, target) for target in PROFIT_LABELS) >= 88:
            word = words[first_num]
            return {"value": units.parse_number(word["text"].strip("“\"'")),
                    "scale": units.scale_from_header(page_text), "label": label, "word": word,
                    "row_text": row["text"]}
    return None


def entity_label(top_text: str) -> str | None:
    """Which entity a statement page belongs to, from its heading (fuzzy for OCR: 'Unconsolldated')."""
    labels = ["unconsolidated", "consolidated", "standalone"]
    for word in re.findall(r"[a-z]{8,}", top_text.lower()):
        # Best-scoring label wins: 'consolidated' is a 92% match for 'unconsolidated' too.
        score, label = max((fuzz.ratio(word, label), label) for label in labels)
        if score >= 88:
            return label
    return None
