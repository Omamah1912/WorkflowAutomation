from tools.dedup import DedupIndex


def test_same_document_id_is_duplicate():
    idx = DedupIndex()
    assert idx.check_exact("JOB-00012", "FDOC-35032", None) == (None, "")
    dup, reason = idx.check_exact("JOB-00200", "FDOC-35032", None)
    assert dup == "JOB-00012" and "FDOC-35032" in reason


def test_same_sha256_is_duplicate():
    idx = DedupIndex()
    idx.check_exact("A", "", "abc123")
    assert idx.check_exact("B", "", "abc123")[0] == "A"


def test_shell_quarterly_filings_are_not_duplicates():
    idx = DedupIndex()
    for i, period in enumerate(["2022-03-31", "2023-03-31", "2024-03-31"]):
        assert idx.check_fuzzy(f"S{i}", "Shell Pakistan Limited", "Financial Results", period)[0] is None


def test_fuzzy_company_same_period_is_duplicate():
    idx = DedupIndex()
    idx.check_fuzzy("A", "Allied Bank Limited", "Dividend Credit Notice", "2026-12-31")
    dup, _ = idx.check_fuzzy("B", "ALLIED BANK LTD", "Dividend Credit Notice", "2026-12-31")
    assert dup is None  # 'LTD' vs 'Limited' is below the 90% bar on its own...
    dup, _ = idx.check_fuzzy("C", "Allied Bank Limited.", "Dividend Credit Notice", "2026-12-31")
    assert dup == "A"   # ...but punctuation / case noise matches


def test_unknown_company_never_fuzzy_matches():
    idx = DedupIndex()
    idx.check_fuzzy("A", None, "Financial Results", "2026-06-30")
    assert idx.check_fuzzy("B", None, "Financial Results", "2026-06-30")[0] is None
