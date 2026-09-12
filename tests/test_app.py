"""Phase 10: the dashboard renders, with and without a document, and never raises."""

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


def test_empty_state_renders():
    at = _run_with(None)
    assert at.title[0].value == "Finance Copilot"


def test_golden_renders_kpis_and_tabs():
    at = _run_with(GOLDEN_US)
    assert at.title[0].value == "golden_us.pdf"
    assert len(at.tabs) == 7
    body = " ".join(m.value for m in at.markdown)
    assert "Net margin" in body and 'class="kpi ok"' in body


def test_hostile_renders_na_cards_distinctly():
    at = _run_with(HOSTILE)
    body = " ".join(m.value for m in at.markdown)
    assert 'class="kpi na"' in body and "N/A" in body


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
    body = " ".join(m.value for m in at.markdown)
    assert "for 2022" not in body


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
