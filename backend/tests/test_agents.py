"""One test per agent, each on a real PSX document (classical path, no LLM keys)."""
import csv

import pytest

from agents import classifier, extractor, intake, resolver, router, transformer, validator
from tools.config import DATA
from tools.dedup import DedupIndex


def manifest_doc(psx_id: str):
    with open(DATA / "real_docs" / "manifest.csv", encoding="utf-8") as f:
        row = next(r for r in csv.DictReader(f) if r["psx_doc_id"] == psx_id)
    return intake.from_manifest(row)


def through_transform(psx_id: str):
    doc = manifest_doc(psx_id)
    intake.accept(doc, DedupIndex())
    classifier.classify(doc)
    extractor.extract(doc)
    transformer.transform(doc)
    return doc


def test_intake_holds_ps07_duplicate():
    idx = DedupIndex()
    docs = [d for d in intake.load_csv_rows() if d.external_id == "FDOC-35032"]
    for d in docs:
        intake.accept(d, idx)
    assert [d.doc_id for d in docs] == ["JOB-00012", "JOB-00200"]
    assert docs[0].duplicate_of is None and docs[1].duplicate_of == "JOB-00012"


def test_intake_normalises_ps01_date():
    doc = next(d for d in intake.load_csv_rows() if d.doc_id == "DOC-0001")
    assert doc.metadata["received_date"] == "2026-01-24"


def test_classifier_on_real_docs():
    pso = manifest_doc("283440")
    classifier.classify(pso)
    assert pso.doc_type == "Financial Results" and pso.relevance and pso.doc_type_confidence >= 0.8
    notice = manifest_doc("266509-1")
    classifier.classify(notice)
    assert notice.doc_type == "Regulatory Notice" and notice.relevance is False
    credit = manifest_doc("282504")
    classifier.classify(credit)
    assert credit.doc_type == "Dividend Credit Notice"


def test_extractor_pso_with_provenance():
    doc = manifest_doc("283440")
    classifier.classify(doc)
    extractor.extract(doc)
    f = {x.name: x for x in doc.tracks[0].fields}
    assert f["cash_dividend"].value == 10 and f["cash_dividend_percent"].value == 100
    assert f["cash_dividend"].evidence.page == 1 and f["cash_dividend"].evidence.bbox
    assert "per share" in f["cash_dividend"].evidence.text
    assert doc.company.value == "Pakistan State Oil Company Limited" and doc.symbol == "PSO"
    assert doc.period.value == "2026-06-30"


def test_transformer_splits_pso_and_derives_face_value():
    doc = through_transform("283440")
    labels = [t.entity_label for t in doc.tracks]
    assert labels == ["unconsolidated", "consolidated"]
    unconsolidated, consolidated = doc.tracks
    assert unconsolidated.value("cash_dividend") == 10          # dividend sits with the paying entity
    assert consolidated.value("profit_after_tax") == 34_581_820_000  # Rs '000 -> Rs
    from tools import reference
    face = reference.face_value("PSO")
    assert face.value == 10 and face.method == "derived_from_filing" and face.evidence.doc_id == "PSX-283440"


def test_validator_flags_percent_only_dividend():
    doc = through_transform("215429")      # Pakistan Paper Products: "Cash Dividend 40%"
    transformer.apply_reference(doc)
    validator.validate(doc, [])
    div04 = next(r for r in doc.tracks[0].rule_results if r.rule_id == "DIV-04")
    assert div04.status == "fail"
    assert any("percent-only" in c for c in doc.complexity)


@pytest.fixture
def samsung():
    doc = intake.load_fixtures()[0]
    intake.accept(doc, DedupIndex())
    classifier.classify(doc)
    extractor.extract(doc)
    transformer.transform(doc)
    validator.validate(doc, [])
    return doc


def test_resolver_cannot_fix_samsung(samsung):
    assert {r.rule_id for _, r in validator.critical_failures(samsung)} == {"DIV-01", "DIV-02"}
    assert resolver.resolve(samsung) is False
    assert resolver.unresolved(samsung)


def test_router_escalates_samsung(samsung):
    resolver.resolve(samsung)
    router.route(samsung)
    assert samsung.route == "needs_review"
    assert samsung.label == "Reconstruction from public reporting"
    packet = samsung.review_packet
    assert {r["rule_id"] for r in packet["rules"]} >= {"DIV-01", "DIV-02"}
    assert "31.6x" in packet["computed_consequence"]
    assert packet["suggested_fix"][0].startswith("Declared: 1,000 KRW per share")
