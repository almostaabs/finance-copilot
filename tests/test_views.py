"""views.py turns an AnalysisResult into plain rows for the dashboard. Pure, no Streamlit.

Rule under test (spec 11, Phase 10): N/A, warning, and low-confidence values are
marked with a status the UI renders distinctly. Verified values say 'ok'.
"""

from pathlib import Path

import pipeline
import pytest

from fincopilot import views

GOLDEN_US = Path("tests/fixtures/golden_us.pdf")
HOSTILE = Path("tests/fixtures/hostile.pdf")
AMBIGUOUS = Path("tests/fixtures/ambiguous_periods.pdf")
STANDALONE = Path("tests/fixtures/standalone_only.pdf")


@pytest.fixture(scope="module")
def golden():
    return pipeline.analyze(GOLDEN_US.read_bytes())


@pytest.fixture(scope="module")
def hostile():
    return pipeline.analyze(HOSTILE.read_bytes())


def test_kpis_cover_latest_period_with_status(golden):
    cards = views.kpi_cards(golden)
    assert [c.name for c in cards] == list(views.KPI_ORDER)
    latest = golden.periods.ordered[-1].end_year
    assert all(c.period == latest for c in cards)
    ok = [c for c in cards if c.status == "ok"]
    assert ok and all(c.value for c in ok)


def test_kpi_unavailable_is_marked_na_with_reason(hostile):
    cards = views.kpi_cards(hostile)
    na = [c for c in cards if c.status == "na"]
    assert na
    assert all(c.value == "N/A" and c.note for c in na)


def test_value_rows_carry_provenance_and_status(golden):
    rows = views.value_rows(golden)
    assert len(rows) == len(golden.values)
    r = next(r for r in rows if r["concept"] == "revenue")
    assert r["page"] and r["source_row"] and r["status"] in {"ok", "low"}
    derived = [r for r in rows if r["concept"] == "free_cash_flow"]
    assert derived and derived[0]["page"] == "" and "derived" in derived[0]["source_row"]


def test_metric_rows_include_unavailable_with_reason(hostile):
    rows = views.metric_rows(hostile)
    na = [r for r in rows if r["status"] == "na"]
    assert na and all(r["value"].startswith("N/A") for r in na)


def test_trend_rows_and_red_flag_rows(golden):
    trends = views.trend_rows(golden)
    assert trends and {"subject", "change", "direction", "reads_as"} <= trends[0].keys()
    flags = views.red_flag_rows(golden)
    assert len(flags) == 10
    assert {f["status"] for f in flags} <= {"fired", "clear", "not_evaluated"}


def test_reconciliation_rows(golden):
    rows = views.reconciliation_rows(golden)
    assert rows and {r["status"] for r in rows} <= {"passed", "warning", "unavailable"}


def test_provenance_lookup(golden):
    rev = next(v for v in golden.values if v.concept.value == "revenue")
    p = views.provenance(golden, rev.cell.ref.ref_id)
    assert p["page"] == rev.source_page
    assert p["raw_text"] == rev.cell.raw_token
    assert views.provenance(golden, "no_such_ref") is None


def test_basis_notice_levels():
    ok = views.basis_notice(pipeline.analyze(GOLDEN_US.read_bytes()))
    assert ok.level == "info"
    fallback = views.basis_notice(pipeline.analyze(STANDALONE.read_bytes()))
    assert fallback.level == "warning" and "standalone" in fallback.text.lower()


def test_ambiguous_periods_still_render():
    result = pipeline.analyze(AMBIGUOUS.read_bytes())
    assert views.kpi_cards(result) == []
    assert views.period_notice(result) is not None
    assert views.value_rows(result) == []
