"""Duplicate detection: exact external ID, exact sha256, or fuzzy company + same type + same period.

Why fuzzy only on the company name: periods differ by one character between years
('2022-03-31' vs '2023-03-31'), so a fuzzy match over the whole key would wrongly merge
Shell's quarterly filings. The company name is fuzzy (OCR noise); type and period must be equal.
"""
from rapidfuzz import fuzz, utils

COMPANY_MATCH_MIN = 90


class DedupIndex:
    def __init__(self):
        self.by_id: dict[str, str] = {}      # external_id -> first doc_id
        self.by_sha: dict[str, str] = {}     # sha256 -> first doc_id
        self.keys: list[tuple[str, str, str, str]] = []  # (company, doc_type, period, doc_id)

    def check_exact(self, doc_id: str, external_id: str, sha256: str | None) -> tuple[str | None, str]:
        """Returns (duplicate_of, reason) and registers the doc if it is new."""
        if external_id and external_id in self.by_id:
            return self.by_id[external_id], f"same document_id {external_id}"
        if sha256 and sha256 in self.by_sha:
            return self.by_sha[sha256], f"same sha256 {sha256[:12]}"
        if external_id:
            self.by_id[external_id] = doc_id
        if sha256:
            self.by_sha[sha256] = doc_id
        return None, ""

    def check_fuzzy(self, doc_id: str, company: str | None, doc_type: str | None,
                    period: str | None) -> tuple[str | None, str]:
        """Same company (fuzzy), same type and same period -> duplicate. Unknown parts never match."""
        if not (company and doc_type and period):
            return None, ""
        for other_company, other_type, other_period, other_id in self.keys:
            if other_type != doc_type or other_period != period:
                continue
            score = fuzz.token_sort_ratio(company, other_company, processor=utils.default_process)
            if score >= COMPANY_MATCH_MIN:
                return other_id, f"same company ({score:.0f}% match), type and period {period}"
        self.keys.append((company, doc_type, period, doc_id))
        return None, ""
