"""views.py turns an AnalysisResult into plain rows for the dashboard. Pure, no Streamlit.

Rule under test (spec 11, Phase 10): N/A, warning, and low-confidence values are
marked with a status the UI renders distinctly. Verified values say 'ok'.
"""

from pathlib import Path

import pipeline
import pytest

from fincopilot import views
from fincopilot.types import CanonicalConcept as C
from fincopilot.types import Period

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
    latest = max(p.end_year for p in golden.periods.ordered)
    assert all(c.period == latest for c in cards)
    ok = [c for c in cards if c.status == "ok"]
    assert ok and all(c.value for c in ok)


def test_kpi_unavailable_is_marked_na_with_reason(hostile):
    cards = views.kpi_cards(hostile)
    na = [c for c in cards if c.status == "na"]
    assert na
    assert all(c.value == "N/A" and c.note for c in na)


P24 = Period(2024, "2024")


def test_value_rows_carry_provenance_and_status(golden):
    rows = views.value_rows(golden)
    assert len(rows) == len(golden.values)
    r = next(r for r in rows if r["concept"] == "Revenue")
    assert r["page"] == str(golden.metric_set.value(C.REVENUE, P24).source_page)
    assert r["source_row"] and r["status"] in {"ok", "low"}
    derived = [r for r in rows if r["concept"] == "Free cash flow"]
    assert derived and derived[0]["page"] == "" and "derived" in derived[0]["source_row"]


def test_metric_rows_include_unavailable_with_reason(hostile):
    rows = views.metric_rows(hostile)
    na = [r for r in rows if r["status"] == "na"]
    assert na and all(r["value"].startswith("N/A") for r in na)


def test_trend_rows_and_red_flag_rows(golden):
    trends = views.trend_rows(golden)
    assert trends and {"subject", "change", "direction", "reads_as"} <= trends[0].keys()
    flags = views.red_flag_rows(golden)
    assert len(flags) == 11
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


def test_kpi_delta_reads_by_economic_sense_not_sign(golden):
    cards = {c.name: c for c in views.kpi_cards(golden)}
    d2e = cards["debt_to_equity"]
    if d2e.delta.startswith("-"):
        assert d2e.delta_reads == "positive"  # less leverage is good news
    assert cards["roe"].value.endswith("%")


def test_history_metric_rows_format_like_live_metrics(golden, tmp_path):
    from fincopilot.store import Store

    store = Store(tmp_path / "h.sqlite")
    store.save(golden, name="g.pdf", data=b"%PDF")
    rows = views.history_metric_rows(store.load_metrics(golden.document_id))
    live = {(r["metric"], r["period"]): r["value"] for r in views.metric_rows(golden)}
    assert rows and all(live[(r["metric"], r["period"])] == r["value"] for r in rows)
    assert {r["status"] for r in rows} <= {"ok", "low"}


def test_concept_labels_are_human_readable(golden):
    from fincopilot.types import CanonicalConcept

    assert set(views.CONCEPT_LABEL) == {c.value for c in CanonicalConcept}
    rows = views.value_rows(golden)
    assert all("_" not in r["concept"] for r in rows)
    fcf = next(r for r in rows if r["concept"] == "Free cash flow")
    assert fcf["source_row"] == "derived from operating cash flow, capital expenditure"


def test_kpi_note_drops_what_the_card_already_says(hostile):
    na = [c for c in views.kpi_cards(hostile) if c.status == "na"]
    assert na
    for c in na:
        assert not c.note.startswith("N/A")
        assert f"{c.name} {c.period}:" not in c.note
        assert c.note


def test_rule_names_are_written_for_people(golden):
    from fincopilot.rules.redflags import RULES

    assert set(views.RULE_LABEL) == {r.rule_id for r in RULES}
    rows = views.red_flag_rows(golden)
    assert {"Earnings quality", "Low-confidence KPI"} <= {r["rule"] for r in rows}
    assert all("_" not in r["rule"] for r in rows)
