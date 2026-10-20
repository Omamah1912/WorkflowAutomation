"""Unit parsing and conversion. The core Samsung lesson lives here: a 'per share' figure is
either money per share or shares per share, and the two must never be confused."""
import re
from datetime import date

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}

CURRENCY_WORDS = r"(?:rs\.?|rupees?|pkr|krw|won|usd|\$)"


def parse_number(text: str) -> float | None:
    """'1,234.5' -> 1234.5, '(1,234)' -> -1234 (accounting negative), 'NIL'/'-' -> None."""
    if text is None:
        return None
    t = str(text).strip().replace("—", "-").replace("–", "-")
    negative = t.startswith("(") and t.endswith(")")
    t = re.sub(r"[^\d.]", "", t)
    if not t or t.count(".") > 1:
        return None
    value = float(t)
    return -value if negative else value


def scale_from_header(text: str) -> int:
    """Statement scale: "(Rupees in '000)" / "Rs '000" -> 1000, "Rs in million" -> 1_000_000, else 1."""
    t = text.lower().replace("‘", "'").replace("’", "'")
    if re.search(r"(?:rupees|rs\.?)\s*(?:in\s*)?'?\s*000|'000", t):
        return 1000
    if re.search(r"(?:rupees|rs\.?)\s*in\s*million", t):
        return 1_000_000
    return 1


def to_rupees(value: float, scale: int) -> float:
    """Rs '000 -> Rs (scale=1000)."""
    return value * scale


def percent_to_rs_per_share(percent: float, face_value_rs: float) -> float:
    """PSX dividends are quoted as % of face value: 40% of Rs 10 = Rs 4.00 per share."""
    return round(percent / 100.0 * face_value_rs, 4)


def face_value_from(rs_per_share: float, percent: float) -> float | None:
    """'Rs 6 per share i.e. 60%' -> face value Rs 10. None if percent is zero/missing."""
    if not percent:
        return None
    return round(rs_per_share / (percent / 100.0), 4)


def unit_type_of(unit_text: str) -> str:
    """Classify the unit of a per-share figure.
    'Rs. per share' / 'KRW per share' -> currency_per_share
    'shares per share' / 'share(s) for every N' -> share_ratio
    '%' -> percent."""
    t = unit_text.lower()
    if re.search(r"shares?\s*(?:\(s\))?\s*(?:per|for every|for each)\s*(?:\d+\s*)?shares?", t):
        return "share_ratio"
    if re.search(CURRENCY_WORDS, t):
        return "currency_per_share" if "per share" in t or "/share" in t else "amount"
    if "%" in t or "percent" in t:
        return "percent"
    return "text"


def parse_date(raw: str) -> str | None:
    """Many filing date styles -> ISO 'YYYY-MM-DD' (None if not parseable):
    'June 30, 2026', 'September25, 2026', '22nd September, 2023', '30 JUNE 2023',
    '24-10-2023' (DD-MM-YYYY), '24/01/2026' (DD/MM/YYYY), '2026-05-19'."""
    if not raw:
        return None
    t = raw.strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", t)
    if m:
        return _iso(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.match(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})", t)
    if m:  # Pakistani filings and ps01 use day-first
        return _iso(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    t = t.replace(",", " ")
    m = re.match(r"([A-Za-z]{3,9})\.?\s*(\d{1,2})(?:st|nd|rd|th)?\s+(\d{4})", t)
    if m:
        return _iso(int(m.group(3)), MONTHS.get(m.group(1)[:3].lower()), int(m.group(2)))
    m = re.match(r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?\s+(\d{4})", t)
    if m:
        return _iso(int(m.group(3)), MONTHS.get(m.group(2)[:3].lower()), int(m.group(1)))
    return None


def _iso(year: int, month: int | None, day: int) -> str | None:
    if not month:
        return None
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


# Regex fragment matching the date styles parse_date understands (used by the extractor).
DATE_PATTERN = (
    r"(?:[A-Z][a-z]{2,8}\.?\s*\d{1,2}(?:st|nd|rd|th)?,?\s*\d{4}"
    r"|\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]{3,9},?\s+\d{4}"
    r"|\d{1,2}-\d{1,2}-\d{4})"
)
