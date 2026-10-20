"""Phase 0 — download rulebooks and real PSX filings, build manifest + company master.

Run from anywhere:  python backend/scripts/fetch_data.py
Re-runs reuse files already in data/_cache/ (no re-download).
Nothing here invents data: anything we cannot read from a source is left blank
and flagged needs_review.
"""
import csv
import hashlib
import html
import re
import time
import urllib.error
import urllib.request
from datetime import date, datetime
from pathlib import Path

import fitz  # PyMuPDF
from rapidfuzz import fuzz, process, utils

BACKEND = Path(__file__).resolve().parents[1]
DATA = BACKEND / "data"
CACHE = DATA / "_cache"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
TIMEOUT_S = 30
RETRIES = 3
PAUSE_S = 2

RULEBOOKS = [
    ("rulebooks/psx", "https://www.psx.com.pk/psx/themes/psx/uploads/PSX-Regulations-February-09-2026.pdf"),
    ("rulebooks/psx", "https://www.psx.com.pk/psx/themes/psx/uploads/Correspondance-Manual-CM-final-version-01.pdf"),
]
SECP_PAGE = "https://www.secp.gov.pk/document/the-companies-act-2017/"

REAL_DOCS = [
    ("financial_results_dividend", "https://dps.psx.com.pk/download/document/282260.pdf"),
    ("financial_results_dividend", "https://dps.psx.com.pk/download/document/215429.pdf"),
    ("financial_results_dividend", "https://dps.psx.com.pk/download/document/283228.pdf"),
    ("dividend_credit_notice", "https://dps.psx.com.pk/download/document/282504.pdf"),
    ("dividend_credit_notice", "https://dps.psx.com.pk/download/document/236785.pdf"),
    ("multi_entity_results", "https://dps.psx.com.pk/download/document/283440.pdf"),
    ("multi_entity_results", "https://dps.psx.com.pk/download/document/281401.pdf"),
    ("scanned_results", "https://dps.psx.com.pk/download/document/240718.pdf"),
    ("template_filings", "https://dps.psx.com.pk/download/document/185483.pdf"),
    ("template_filings", "https://dps.psx.com.pk/download/document/207953.pdf"),
    ("template_filings", "https://dps.psx.com.pk/download/document/230000.pdf"),
    ("regulatory_notice", "https://dps.psx.com.pk/download/attachment/266509-1.pdf"),
]

HOOK_ARTICLES = [
    "https://www.khan.co.kr/en/article/202608121706037",
    "https://www.koreajoongangdaily.com/business/samsung-securities-ordered-to-pay-19-billion-won-over-2018-ghost-stock-error/12820504",
    "https://www.koreajoongangdaily.com/business/samsung-securities-ceo-resigns-over-blunder/10435625",
    "https://www.irishexaminer.com/breakingnews/business/samsung-in-270m-fat-finger-bungle-836736.html",
    "https://www.brecorder.com/news/amp/40419729",
]

SCREENER_URL = "https://dps.psx.com.pk/screener"
COMPANY_URL = "https://dps.psx.com.pk/company/{symbol}"

# Names that appear in filings as the addressee/regulator, never as the filing company.
NOT_ISSUERS = ("stock exchange", "securities and exchange", "central depository", "clearing company")

MONTHS = {m.lower(): i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"], start=1)}

_last_request_at = 0.0


# ---------------------------------------------------------------- HTTP

def http_get(url: str) -> bytes:
    """GET with browser UA, 30 s timeout, 3 retries with exponential backoff, 2 s spacing."""
    global _last_request_at
    last_error = None
    for attempt in range(RETRIES):
        wait = PAUSE_S - (time.time() - _last_request_at)
        if wait > 0:
            time.sleep(wait)
        _last_request_at = time.time()
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/pdf,*/*",
                "Accept-Language": "en-US,en;q=0.9",
            })
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            last_error = f"HTTP {e.code}"
            if e.code in (403, 404):  # retrying will not help
                break
        except Exception as e:  # timeouts, connection resets
            last_error = f"{type(e).__name__}: {e}"
        time.sleep(2 ** attempt)
    raise RuntimeError(f"{url} failed: {last_error}")


def cached_get(url: str) -> bytes:
    """Download once into data/_cache/, then reuse the cached copy."""
    CACHE.mkdir(parents=True, exist_ok=True)
    key = re.sub(r"[^A-Za-z0-9._-]", "_", url.split("://", 1)[-1])[-150:]
    path = CACHE / key
    if path.exists():
        return path.read_bytes()
    body = http_get(url)
    path.write_bytes(body)
    return body


# ---------------------------------------------------------------- PDF inspection

def inspect_pdf(body: bytes) -> dict:
    """Check %PDF magic, open with PyMuPDF, return pages / text-layer / first-pages text."""
    if not body.startswith(b"%PDF"):
        raise ValueError("not a PDF (missing %PDF header)")
    doc = fitz.open(stream=body, filetype="pdf")
    page_texts = [page.get_text() for page in doc]
    # A page "has text" if it carries at least 50 non-space characters.
    # Many PSX filings are a typed cover letter + scanned statements, so we track pages individually.
    scanned_pages = [i + 1 for i, t in enumerate(page_texts) if len(re.sub(r"\s", "", t)) < 50]
    return {
        "pages": doc.page_count,
        "has_text_layer": len(scanned_pages) < doc.page_count,  # at least one page has real text
        "scanned_pages": scanned_pages,
        "head_text": "\n".join(page_texts[:3]),
        "sha256": hashlib.sha256(body).hexdigest(),
    }


def find_company(text: str) -> str:
    """First line that looks like an issuer name ('... Limited'), skipping addressees,
    share registrars and private companies (which cannot be the listed issuer)."""
    skip = ("registrar", "(pvt)", "(private)") + NOT_ISSUERS
    for line in text.splitlines():
        line = " ".join(line.split())
        line = re.sub(r"^(?:for and )?on behalf of\s+|^for\s+", "", line, flags=re.I)
        m = re.search(r"([A-Z][A-Za-z0-9&.,()'\- ]{2,80}?\b(?:Limited|LIMITED|Ltd\.?|LTD\.?|Modaraba|MODARABA))\b", line)
        if m and not any(word in m.group(1).lower() for word in skip):
            return m.group(1).strip(" ,.")
    return ""


def parse_date(raw: str) -> str:
    """'June 30, 2026' / '30 June 2026' / '30th June, 2026' -> '2026-06-30'; '' if unparseable."""
    raw = raw.replace(",", " ")
    m = re.match(r"([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?\s+(\d{4})", raw.strip())
    if m:
        month, day, year = m.group(1), m.group(2), m.group(3)
    else:
        m = re.match(r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(\d{4})", raw.strip())
        if not m:
            return ""
        day, month, year = m.group(1), m.group(2), m.group(3)
    month_num = MONTHS.get(month.lower())
    if not month_num:
        return ""
    try:
        return date(int(year), month_num, int(day)).isoformat()
    except ValueError:
        return ""


def find_period(text: str) -> str:
    """Reporting period end date from '... (quarter|year|period) ended <date>'."""
    flat = " ".join(text.split())
    date_pat = r"([A-Za-z]+\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}|\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+,?\s+\d{4})"
    m = re.search(r"(?:quarter|year|period|months)\s+(?:ended|ending)\s+(?:on\s+)?" + date_pat, flat, re.I)
    return parse_date(m.group(1)) if m else ""


def compact_ranges(pages: list) -> str:
    """[2,3,4,7] -> '2-4,7'"""
    runs = [[pages[0], pages[0]]]
    for p in pages[1:]:
        if p == runs[-1][1] + 1:
            runs[-1][1] = p          # extend the current run
        else:
            runs.append([p, p])      # start a new run
    return ",".join(str(a) if a == b else f"{a}-{b}" for a, b in runs)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "unknown"


# ---------------------------------------------------------------- PSX reference data

def load_screener() -> dict:
    """symbol -> company name, scraped from the PSX screener table."""
    page = cached_get(SCREENER_URL).decode("utf-8", errors="replace")
    pairs = re.findall(r'href="/company/([A-Z0-9-]+)"\s+data-title="([^"]+)"', page)
    return {sym: html.unescape(name) for sym, name in pairs}


def match_symbol(company: str, screener: dict) -> tuple[str, str, float]:
    """Fuzzy-match a company name to a PSX symbol. Returns (symbol, psx_name, score)."""
    if not company or not screener:
        return "", "", 0.0
    # default_process lower-cases and strips punctuation, so "PAKISTAN PAPER ... LIMITED" matches.
    best = process.extractOne(company, screener, scorer=fuzz.token_sort_ratio,
                              processor=utils.default_process)
    if not best:
        return "", "", 0.0
    psx_name, score, symbol = best
    return symbol, psx_name, score


def company_profile(symbol: str) -> dict:
    """Shares outstanding (and face value if the page shows it) from dps.psx.com.pk/company/<SYMBOL>."""
    page = cached_get(COMPANY_URL.format(symbol=symbol)).decode("utf-8", errors="replace")
    flat = re.sub(r"<script.*?</script>", " ", page, flags=re.S)
    flat = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", flat)))
    shares = re.search(r"\bShares\s+([\d,]{4,})", flat)
    face = re.search(r"Face Value\s*(?:\(Rs\.?\))?\s*([\d.]+)", flat, re.I)
    return {
        "shares_outstanding": shares.group(1).replace(",", "") if shares else "",
        "face_value_rs": face.group(1) if face else "",
    }


# ---------------------------------------------------------------- main steps

def fetch_rulebooks(summary: list) -> list:
    sources = []
    for folder, url in RULEBOOKS:
        name = url.rsplit("/", 1)[-1]
        try:
            info = inspect_pdf(cached_get(url))
            (DATA / folder).mkdir(parents=True, exist_ok=True)
            (DATA / folder / name).write_bytes(cached_get(url))
            summary.append((f"{folder}/{name}", "ok", f"{info['pages']} pages"))
            sources.append((f"{folder}/{name}", url, f"{info['pages']} pages, sha256 {info['sha256'][:12]}"))
        except Exception as e:
            summary.append((f"{folder}/{name}", "failed", str(e)))
            sources.append((f"{folder}/{name}", url, f"NOT DOWNLOADED: {e}"))

    # Companies Act: find the PDF link on the SECP page.
    target = "rulebooks/secp/companies_act_2017.pdf"
    try:
        page = cached_get(SECP_PAGE).decode("utf-8", errors="replace")
        links = re.findall(r'href="([^"]+?(?:\.pdf|wpdmdl=\d+)[^"]*)"', page)
        if not links:
            raise RuntimeError("no PDF link found on SECP page")
        pdf_url = html.unescape(links[0])
        body = cached_get(pdf_url)
        info = inspect_pdf(body)
        (DATA / "rulebooks/secp").mkdir(parents=True, exist_ok=True)
        (DATA / target).write_bytes(body)
        summary.append((target, "ok", f"{info['pages']} pages"))
        sources.append((target, pdf_url, f"{info['pages']} pages, linked from {SECP_PAGE}"))
    except Exception as e:
        summary.append((target, "failed", f"{e} — download manually from {SECP_PAGE}"))
        sources.append((target, SECP_PAGE, f"NOT DOWNLOADED: {e}"))
    return sources


def fetch_real_docs(summary: list, screener: dict) -> list:
    rows = []
    today = date.today().isoformat()
    # Names depend on parsed text, so clear old copies to avoid stale duplicates on re-runs.
    for old in (DATA / "real_docs").glob("*/*.pdf"):
        old.unlink()
    for category, url in REAL_DOCS:
        psx_doc_id = re.search(r"/(\d+(?:-\d+)?)\.pdf$", url).group(1)
        try:
            body = cached_get(url)
            info = inspect_pdf(body)
        except Exception as e:
            summary.append((f"{category}/{psx_doc_id}", "failed", str(e)))
            continue

        notes = []
        company = find_company(info["head_text"])
        period = find_period(info["head_text"])
        if not info["has_text_layer"]:
            notes.append("no text layer on any page (scanned) - needs OCR")
        elif info["scanned_pages"]:
            notes.append(f"pages without text layer (need OCR): {compact_ranges(info['scanned_pages'])}")
        if not company:
            notes.append("company not found in text")
        if not period:
            notes.append("period not found in text")

        # Only trust a company name that matches a PSX listing; otherwise blank + needs_review.
        symbol, psx_name, score = match_symbol(company, screener)
        if company and score >= 85:
            notes.append(f"matched PSX symbol {symbol} (score {score:.0f})")
            company = psx_name
        else:
            if company:
                notes.append(f"text candidate '{company}' has no confident PSX match (best {symbol} {score:.0f})")
            company, symbol = "", ""

        needs_review = not (company and period)
        filename = f"psx_{category}_{slug(company) if company else 'unknown'}_{period or 'unknown'}_{psx_doc_id}.pdf"
        out_dir = DATA / "real_docs" / category
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / filename).write_bytes(body)

        rows.append({
            "filename": f"{category}/{filename}",
            "original_url": url,
            "psx_doc_id": psx_doc_id,
            "category": category,
            "organisation": "psx",
            "company": company,
            "period": period,
            "pages": info["pages"],
            "has_text_layer": info["has_text_layer"],
            "sha256": info["sha256"],
            "download_date": today,
            "needs_review": needs_review,
            "notes": "; ".join(notes),
            "symbol": symbol,  # used for company_master only, dropped from manifest
        })
        summary.append((f"{category}/{filename}", "needs_review" if needs_review else "ok", "; ".join(notes)))
    return rows


def write_manifest(rows: list) -> None:
    cols = ["filename", "original_url", "psx_doc_id", "category", "organisation", "company", "period",
            "pages", "has_text_layer", "sha256", "download_date", "needs_review", "notes"]
    with open(DATA / "real_docs" / "manifest.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_company_master(rows: list, screener: dict, summary: list) -> None:
    cols = ["symbol", "company", "face_value_rs", "shares_outstanding", "source_url", "retrieved_at", "needs_review"]
    out = []
    seen = set()
    for row in rows:
        symbol = row["symbol"]
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        url = COMPANY_URL.format(symbol=symbol)
        try:
            profile = company_profile(symbol)
        except Exception as e:
            profile = {"shares_outstanding": "", "face_value_rs": ""}
            summary.append((f"company_master/{symbol}", "failed", str(e)))
        out.append({
            "symbol": symbol,
            "company": screener.get(symbol, row["company"]),
            "face_value_rs": profile["face_value_rs"],
            "shares_outstanding": profile["shares_outstanding"],
            "source_url": url,
            "retrieved_at": datetime.now().isoformat(timespec="seconds"),
            "needs_review": not (profile["face_value_rs"] and profile["shares_outstanding"]),
        })
    (DATA / "reference").mkdir(parents=True, exist_ok=True)
    with open(DATA / "reference" / "company_master.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=cols)
        writer.writeheader()
        writer.writerows(out)


def write_sources(rulebook_sources: list, rows: list) -> None:
    lines = [
        "# Data sources",
        "",
        f"Generated by `scripts/fetch_data.py` on {date.today().isoformat()}.",
        "",
        "## Provided datasets (hackathon)",
        "- `csv/ps01_documents_metadata.csv` — 200 rows of document metadata (placeholder OCR snippets).",
        "- `csv/ps07_ingestion_queue.csv` — 250 rows, manual analyst baseline.",
        "",
        "## Rulebooks",
    ]
    lines += [f"- `{path}` — {url} ({note})" for path, url, note in rulebook_sources]
    lines += ["", "## Real PSX filings (see `real_docs/manifest.csv`)"]
    lines += [f"- `real_docs/{r['filename']}` — {r['original_url']}" for r in rows]
    lines += [
        "",
        "## Company reference data",
        f"- Symbol list: {SCREENER_URL}",
        f"- Shares outstanding: {COMPANY_URL.format(symbol='<SYMBOL>')} (Equity Profile → Shares)",
        "",
        "## Samsung Securities 2018 hook (linked only, not downloaded)",
        "Used for the labelled reconstruction in `fixtures/samsung_2018_replay.json`.",
    ]
    lines += [f"- {url}" for url in HOOK_ARTICLES]
    (DATA / "SOURCES.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    summary = []
    rulebook_sources = fetch_rulebooks(summary)
    try:
        screener = load_screener()
    except Exception as e:
        screener = {}
        summary.append(("screener", "failed", str(e)))
    rows = fetch_real_docs(summary, screener)
    write_manifest(rows)
    write_company_master(rows, screener, summary)
    write_sources(rulebook_sources, rows)

    print(f"\n{'file':<95} {'status':<13} reason")
    print("-" * 160)
    for name, status, reason in summary:
        print(f"{name:<95} {status:<13} {reason}")


if __name__ == "__main__":
    main()
