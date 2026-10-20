from state import Document, Evidence, FieldValue, Track
from tools import rules_engine
from tools.config import thresholds

RULES = "rules/dividend_rules.yaml"


def _ctx(fields, doc_type="Corporate Action Instruction", records=None, **doc_kwargs):
    doc = Document(doc_id="T-1", source="fixture", filename="t.json", doc_type=doc_type, **doc_kwargs)
    track = Track(track_id="T-1/main", entity_label="company", fields=fields)
    return {"doc": doc, "track": track, "records": records or [], "thresholds": thresholds()}


def _by_id(results):
    return {r.rule_id: r for r in results}


def test_samsung_2018_ghost_shares_fail_div01_and_div02():
    # Public figures: 1,000 KRW per share declared; entered as 1,000 shares per share
    # on 2,812,950 employee-held shares; ~89,000,000 shares outstanding.
    fields = [
        FieldValue(name="cash_dividend", value=1000, unit="shares per share", unit_type="share_ratio"),
        FieldValue(name="eligible_shares", value=2_812_950, unit="shares", unit_type="count"),
        FieldValue(name="shares_outstanding", value=89_000_000, unit="shares", unit_type="count"),
    ]
    r = _by_id(rules_engine.evaluate(RULES, _ctx(fields)))
    assert r["DIV-01"].status == "fail" and r["DIV-01"].severity == "critical"
    assert r["DIV-02"].status == "fail" and r["DIV-02"].severity == "critical"
    assert r["DIV-02"].actual == 2_812_950_000
    assert "~31.6x" in r["DIV-02"].message


def test_correct_samsung_entry_passes():
    fields = [
        FieldValue(name="cash_dividend", value=1000, unit="KRW per share", unit_type="currency_per_share"),
        FieldValue(name="eligible_shares", value=2_812_950, unit="shares", unit_type="count"),
        FieldValue(name="shares_outstanding", value=89_000_000, unit="shares", unit_type="count"),
    ]
    r = _by_id(rules_engine.evaluate(RULES, _ctx(fields)))
    assert r["DIV-01"].status == "pass"
    assert r["DIV-02"].status == "pass"


def test_div03_and_div04():
    face_from_other_doc = FieldValue(name="face_value", value=10, unit="Rs per share", unit_type="currency_per_share",
                                     evidence=Evidence(doc_id="OTHER"))
    ok = [FieldValue(name="cash_dividend", value=4.0, unit="Rs per share", unit_type="currency_per_share"),
          FieldValue(name="cash_dividend_percent", value=40, unit="%", unit_type="percent"), face_from_other_doc]
    bad = [FieldValue(name="cash_dividend", value=40.0, unit="Rs per share", unit_type="currency_per_share"),
           FieldValue(name="cash_dividend_percent", value=40, unit="%", unit_type="percent"), face_from_other_doc]
    assert _by_id(rules_engine.evaluate(RULES, _ctx(ok, "Financial Results")))["DIV-03"].status == "pass"
    assert _by_id(rules_engine.evaluate(RULES, _ctx(bad, "Financial Results")))["DIV-03"].status == "fail"

    percent_only = [FieldValue(name="cash_dividend_percent", value=40, unit="%", unit_type="percent")]
    r = _by_id(rules_engine.evaluate(RULES, _ctx(percent_only, "Financial Results")))
    assert r["DIV-04"].status == "fail" and r["DIV-04"].severity == "warning"


def test_div05_not_applicable_without_a_declaration():
    fields = [FieldValue(name="cash_dividend", value=4.0, unit="Rs per share", unit_type="currency_per_share")]
    period = FieldValue(name="period", value="2026-12-31")
    r = _by_id(rules_engine.evaluate(RULES, _ctx(fields, "Dividend Credit Notice", symbol="ABL", period=period)))
    assert r["DIV-05"].status == "not_applicable" and r["DIV-05"].passed is None


def test_div05_and_div08_cross_record():
    fields = [FieldValue(name="cash_dividend", value=4.0, unit="Rs per share", unit_type="currency_per_share")]
    period = FieldValue(name="period", value="2026-12-31")
    records = [
        {"doc_id": "DECL", "symbol": "ABL", "period": "2026-12-31", "doc_type": "Financial Results", "cash_dividend": 5.0},
        {"doc_id": "OLD", "symbol": "ABL", "period": "2024-12-31", "doc_type": "Dividend Credit Notice", "cash_dividend": 1.0},
    ]
    r = _by_id(rules_engine.evaluate(RULES, _ctx(fields, "Dividend Credit Notice", records, symbol="ABL", period=period)))
    assert r["DIV-05"].status == "fail"          # credited 4.00 vs declared 5.00
    assert r["DIV-08"].status == "fail"          # 4x the previous period


def test_div10_book_closure_order():
    fields = [FieldValue(name="announcement_date", value="2026-09-25", unit_type="date"),
              FieldValue(name="book_closure_from", value="2026-10-21", unit_type="date"),
              FieldValue(name="book_closure_to", value="2026-10-28", unit_type="date")]
    assert _by_id(rules_engine.evaluate(RULES, _ctx(fields, "Financial Results")))["DIV-10"].status == "pass"
    fields[1] = FieldValue(name="book_closure_from", value="2026-09-01", unit_type="date")
    assert _by_id(rules_engine.evaluate(RULES, _ctx(fields, "Financial Results")))["DIV-10"].status == "fail"


def test_rules_have_required_keys():
    for path in (RULES, "rules/csv_rules.yaml"):
        for rule in rules_engine.load_rules(path)["rules"]:
            assert {"id", "description", "severity", "check", "params", "source_clause"} <= rule.keys()
            assert rule["check"] in rules_engine.CHECKS
