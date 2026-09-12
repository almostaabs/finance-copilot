"""Phase 11: thin SQLite persistence. Stores results, never the PDF."""

from __future__ import annotations

import sqlite3
from decimal import Decimal
from pathlib import Path

import pipeline
import pytest

from fincopilot.store import Store
from fincopilot.types import Insight, Narrative

GOLDEN_US = Path("tests/fixtures/golden_us.pdf")


@pytest.fixture(scope="module")
def result():
    return pipeline.analyze(GOLDEN_US.read_bytes())


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "fc.sqlite")


def test_schema_has_only_the_five_thin_tables(store):
    names = {r[0] for r in store.conn.execute("select name from sqlite_master where type='table'")}
    assert names == {"documents", "financial_values", "calculated_metrics", "insights", "questions"}


def test_save_and_list(store, result):
    store.save(result, name="golden_us.pdf", data=GOLDEN_US.read_bytes())
    docs = store.list_documents()
    assert len(docs) == 1
    d = docs[0]
    assert d.document_id == result.document_id
    assert d.name == "golden_us.pdf"
    assert d.basis == result.basis.value
    assert len(d.sha256) == 64


def test_pdf_bytes_are_never_stored(store, result, tmp_path):
    store.save(result, name="golden_us.pdf", data=GOLDEN_US.read_bytes())
    store.conn.commit()
    raw = (tmp_path / "fc.sqlite").read_bytes()
    assert b"%PDF" not in raw


def test_values_round_trip_lossless(store, result):
    store.save(result, name="x.pdf", data=b"%PDF-1.4 fake")
    rows = store.load_values(result.document_id)
    assert len(rows) == len(result.values)
    by_key = {(r.concept, r.period): r for r in rows}
    for v in result.values:
        r = by_key[(v.concept.value, v.period.end_year)]
        assert Decimal(r.value) == v.value
        assert r.currency == v.currency
        assert r.source_page == (v.source_page if v.cell else None)


def test_metrics_round_trip(store, result):
    store.save(result, name="x.pdf", data=b"%PDF-1.4 fake")
    rows = store.load_metrics(result.document_id)
    assert {(r.name, r.period) for r in rows} == {
        (m.name, m.period.end_year) for m in result.metrics
    }
    assert all(Decimal(r.value) for r in rows)


def test_save_twice_replaces(store, result):
    store.save(result, name="x.pdf", data=b"%PDF-1.4 fake")
    store.save(result, name="x.pdf", data=b"%PDF-1.4 fake")
    assert len(store.list_documents()) == 1
    assert len(store.load_values(result.document_id)) == len(result.values)


def test_insights_saved_and_loaded(store, result):
    store.save(result, name="x.pdf", data=b"%PDF-1.4 fake")
    n = Narrative("Summary.", (Insight("Point.", ("net_margin@2024",)),), model="m")
    store.save_narrative(result.document_id, n)
    loaded = store.load_narrative(result.document_id)
    assert loaded == n


def test_narrative_for_unknown_document_is_none(store):
    assert store.load_narrative("nope") is None


def test_name_is_display_only_never_a_path(store, result):
    store.save(result, name="../../etc/passwd", data=b"%PDF-1.4 fake")
    assert store.list_documents()[0].name == "passwd"


def test_delete_cascades(store, result):
    store.save(result, name="x.pdf", data=b"%PDF-1.4 fake")
    store.save_narrative(result.document_id, Narrative("s", (), model="m"))
    store.delete(result.document_id)
    assert store.list_documents() == []
    assert store.load_values(result.document_id) == []
    assert store.load_narrative(result.document_id) is None


def test_corrupt_db_file_raises_clean_error(tmp_path):
    bad = tmp_path / "bad.sqlite"
    bad.write_bytes(b"not a database" * 100)
    with pytest.raises(sqlite3.DatabaseError):
        Store(bad)
