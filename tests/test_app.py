"""Phase 10: the dashboard renders, with and without a document, and never raises."""

import os
from pathlib import Path

import pipeline
import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

GOLDEN_US = Path("tests/fixtures/golden_us.pdf")
HOSTILE = Path("tests/fixtures/hostile.pdf")
AMBIGUOUS = Path("tests/fixtures/ambiguous_periods.pdf")


@pytest.fixture(autouse=True)
def _tmp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("FINCOPILOT_DB", str(tmp_path / "t.sqlite"))


def _run_with(path: Path | None) -> AppTest:
    at = AppTest.from_file(
        str(Path(__file__).resolve().parent.parent / "app.py"), default_timeout=60
    )
    if path is not None:
        result = pipeline.analyze(path.read_bytes())
        at.session_state["current"] = {"name": path.name, "sha256": "x" * 64, "result": result}
    at.run()
    assert not at.exception, at.exception
    return at


def test_history_off_keeps_a_visitors_report_out_of_the_next_visitors_page(monkeypatch):
    """A shared deployment serves every visitor from one machine, so history is
    switched off there. Nothing may be written, and nothing may be listed."""
    monkeypatch.setenv("FINCOPILOT_HISTORY", "off")
    at = _run_with(GOLDEN_US)
    body = " ".join(c.value for c in at.caption)
    assert "History is switched off on this deployment" in body
    db = Path(os.environ["FINCOPILOT_DB"])
    assert not db.exists(), "an analysis was persisted with history switched off"


def test_history_on_by_default_records_the_analysis():
    at = _run_with(GOLDEN_US)
    assert Path(os.environ["FINCOPILOT_DB"]).exists()
    assert "History is switched off" not in " ".join(c.value for c in at.caption)


def test_empty_state_renders():
    at = _run_with(None)
    body = " ".join(m.value for m in at.markdown)
    assert "<h1>Finance Copilot</h1>" in body and "Recent analyses" in body


def test_golden_renders_kpis_and_tabs():
    at = _run_with(GOLDEN_US)
    assert at.title[0].value == "golden_us.pdf"
    assert len(at.tabs) == 6
    panel_html = _panel_html(at)
    assert "Net margin" in panel_html and 'class="card ok"' in panel_html


def test_hostile_renders_na_cards_distinctly():
    at = _run_with(HOSTILE)
    panel_html = _panel_html(at)
    assert 'class="card na"' in panel_html and "N/A" in panel_html


def test_ambiguous_periods_renders_error_not_crash():
    at = _run_with(AMBIGUOUS)
    assert at.error


def test_history_tab_renders_saved_document(tmp_path):
    from fincopilot.store import Store
    from fincopilot.types import Insight, Narrative

    result = pipeline.analyze(GOLDEN_US.read_bytes())
    store = Store(tmp_path / "t.sqlite")
    store.save(result, name="golden_us.pdf", data=GOLDEN_US.read_bytes())
    store.save_narrative(result.document_id, Narrative("Summary.", (Insight("P.", ("x",)),), "m"))
    store.close()
    at = _run_with(None)
    assert at.expander and "golden_us.pdf" in at.expander[0].label
    assert any("Summary." in m.value for m in at.markdown)


def test_kpi_cards_use_newest_period():
    at = _run_with(GOLDEN_US)
    assert "for 2022" not in _panel_html(at)


def test_load_rejects_bad_files_without_raising(monkeypatch):
    import app

    calls = []
    monkeypatch.setattr(app.st.sidebar, "error", lambda msg: calls.append(msg))
    monkeypatch.setattr(app.st, "session_state", {})
    app._load(
        "scanned.pdf", Path("tests/fixtures/scanned.pdf").read_bytes(), False, "http://x", "m"
    )
    app._load("junk.pdf", b"not a pdf at all", False, "http://x", "m")
    assert len(calls) == 2 and "current" not in app.st.session_state


def test_ollama_host_must_be_http():
    from fincopilot.ai.client import OllamaClient

    with pytest.raises(ValueError):
        OllamaClient(host="file:///etc/passwd")


def _of_type(at, kind: str) -> list:
    """AppTest has no typed accessor for vega_lite_chart or html; both land as
    UnknownElement carrying their proto name in `.type`."""
    return [e for e in at.main if type(e).__name__ == "UnknownElement" and e.type == kind]


def _chart_count(at) -> int:
    return len(_of_type(at, "vega_lite_chart"))


def _panel_html(at) -> str:
    return " ".join(e.proto.body for e in _of_type(at, "html"))


def test_results_tab_draws_a_chart_per_result_and_a_flag_grid():
    from fincopilot import charts

    result = pipeline.analyze(GOLDEN_US.read_bytes())
    at = _run_with(GOLDEN_US)
    panel_html = _panel_html(at)
    assert 'class="grid flags"' in panel_html and 'class="card clear"' in panel_html
    assert _chart_count(at) == len(charts.charts(result)) == 5


def test_charts_absent_when_periods_are_ambiguous():
    at = _run_with(AMBIGUOUS)
    assert _chart_count(at) == 0
    assert at.error
