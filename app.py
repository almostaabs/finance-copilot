"""Finance Copilot dashboard. UI wiring only (spec 2.2).

Every number on screen comes from pipeline.analyze(). This file formats,
lays out, and persists. It never computes a financial value.
"""

from __future__ import annotations

import hashlib
import html
import os
from dataclasses import asdict
from pathlib import Path

import pandas as pd
import pipeline
import streamlit as st

from fincopilot import views
from fincopilot.ai.client import OllamaClient
from fincopilot.extract.pdf import IngestionError
from fincopilot.store import Store
from fincopilot.types import Narrative, Unavailable

DB_PATH = Path(os.environ.get("FINCOPILOT_DB", "data/fincopilot.sqlite"))
SAMPLE_PDF = Path(__file__).parent / "tests" / "fixtures" / "golden_us.pdf"

STATUS_STYLE = {
    "ok": "background-color:#eaf6ee;",
    "low": "background-color:#fff6e0;",
    "warning": "background-color:#fff6e0;",
    "na": "background-color:#f0f0f0;color:#707070;font-style:italic;",
    "unavailable": "background-color:#f0f0f0;color:#707070;font-style:italic;",
    "not_evaluated": "background-color:#f0f0f0;color:#707070;font-style:italic;",
    "fired": "background-color:#fbe9e7;font-weight:600;",
    "passed": "background-color:#eaf6ee;",
    "clear": "background-color:#eaf6ee;",
}
CSS = """
<style>
.kpi {border:1px solid #d9dee5;border-radius:10px;padding:14px 16px;background:#fff;
  min-height:118px}
.kpi.ok {border-left:5px solid #2e8b57}
.kpi.low {border-left:5px solid #e0a100;background:#fffaf0}
.kpi.na {border:1px dashed #b5b5b5;background:#f5f5f5;color:#7a7a7a}
.kpi .label {font-size:0.8rem;color:#5b6675;text-transform:uppercase;letter-spacing:.04em}
.kpi .value {font-size:1.7rem;font-weight:600;margin:4px 0}
.kpi.na .value {font-size:1.3rem;font-style:italic}
.kpi .delta {font-size:0.85rem}
.kpi .note {font-size:0.75rem;color:#7a7a7a;margin-top:4px}
.up {color:#2e8b57} .down {color:#c0392b}
.badge {display:inline-block;padding:2px 10px;border-radius:12px;font-size:.8rem;font-weight:600}
.badge.info {background:#e3eefa;color:#1f4e79} .badge.warning {background:#fff1cc;color:#8a6100}
.badge.error {background:#fbe9e7;color:#a12c1e}
</style>
"""


# --- helpers (formatting and wiring only) ------------------------------------


@st.cache_data(show_spinner=False)
def _analyze(data: bytes, use_ai: bool, host: str, model: str):
    llm = OllamaClient(host=host, model=model) if use_ai else None
    return pipeline.analyze(data, llm=llm)


def _store() -> Store | None:
    try:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        return Store(DB_PATH)
    except Exception:
        return None


def _table(rows: list[dict], *, hide: tuple[str, ...] = ()) -> None:
    if not rows:
        st.caption("Nothing to show.")
        return
    df = pd.DataFrame(rows).drop(columns=list(hide), errors="ignore")
    styled = df.style.apply(
        lambda r: [STATUS_STYLE.get(str(r.get("status", "")), "")] * len(r), axis=1
    )
    st.dataframe(styled, width="stretch", hide_index=True)


def _kpi_html(c: views.Kpi) -> str:
    delta = ""
    if c.delta:
        cls = {"positive": "up", "negative": "down"}.get(c.delta_reads, "")
        delta = f'<div class="delta {cls}">{html.escape(c.delta)} vs prior year</div>'
    return (
        f'<div class="kpi {c.status}"><div class="label">{html.escape(c.label)}</div>'
        f'<div class="value">{html.escape(c.value)}</div>{delta}'
        f'<div class="note">{html.escape(c.note)}</div></div>'
    )


def _notice(n: views.Notice) -> None:
    {"info": st.info, "warning": st.warning, "error": st.error}[n.level](n.text)


# --- page --------------------------------------------------------------------


def _sidebar() -> tuple[bool, str, str]:
    st.sidebar.title("Finance Copilot")
    st.sidebar.caption("Local-first annual report analysis. Numbers come only from the PDF.")
    upload = st.sidebar.file_uploader("Annual report (PDF, max 50 MB)", type=["pdf"])
    st.sidebar.divider()
    use_ai = st.sidebar.toggle(
        "Local AI (Ollama)",
        value=False,
        help="Optional. Used only to pick unmatched rows and write a cited narrative. "
        "Never supplies a number.",
    )
    host = st.sidebar.text_input(
        "Ollama host", os.environ.get("FINCOPILOT_OLLAMA_HOST", "http://localhost:11434")
    )
    model = st.sidebar.text_input("Model", os.environ.get("FINCOPILOT_OLLAMA_MODEL", "qwen2.5:3b"))
    if upload is not None:
        _load(upload.name, upload.getvalue(), use_ai, host, model)
    elif st.sidebar.button("Load sample report", help="A synthetic US-style report used in tests."):
        if SAMPLE_PDF.is_file():
            _load(SAMPLE_PDF.name, SAMPLE_PDF.read_bytes(), use_ai, host, model)
        else:
            st.sidebar.error(
                "Sample not found. Run: uv run python tests/fixtures/build_fixtures.py"
            )
    return use_ai, host, model


def _load(name: str, data: bytes, use_ai: bool, host: str, model: str) -> None:
    sha = hashlib.sha256(data).hexdigest()
    if st.session_state.get("current", {}).get("sha256") == sha:
        return
    try:
        with st.spinner("Reading statements..."):
            result = _analyze(data, use_ai, host, model)
    except IngestionError as exc:
        st.sidebar.error(f"Cannot analyse this file: {exc}")
        return
    except Exception as exc:
        st.sidebar.error(f"Analysis failed ({type(exc).__name__}). Nothing was saved.")
        return
    st.session_state["current"] = {"name": name, "sha256": sha, "result": result}
    st.session_state.pop("narrative", None)
    if (store := _store()) is not None:
        store.save(result, name=name, data=data)
        store.close()


def _history_tab() -> None:
    store = _store()
    if store is None:
        st.caption("History unavailable (database could not be opened).")
        return
    docs = store.list_documents()
    if not docs:
        st.caption("No documents analysed yet.")
    for d in docs:
        periods = ", ".join(map(str, d.periods)) or "no periods"
        with st.expander(f"{d.name}  ·  {d.basis}  ·  {periods}  ·  {d.analyzed_at}"):
            st.caption(
                f"sha256 {d.sha256[:16]}…  ·  {d.size_bytes:,} bytes  ·  PDF itself is not stored"
            )
            metrics = store.load_metrics(d.document_id)
            if metrics:
                st.dataframe(
                    pd.DataFrame([asdict(m) for m in metrics]), width="stretch", hide_index=True
                )
            if (n := store.load_narrative(d.document_id)) is not None:
                st.markdown(f"**AI summary ({n.model}):** {n.summary}")
            if st.button("Delete from history", key=f"del_{d.document_id}"):
                store.delete(d.document_id)
                st.rerun()
    store.close()


def _narrative_section(result, use_ai: bool, host: str, model: str, doc_id: str) -> None:
    st.subheader("Plain-English reading")
    if not use_ai:
        st.caption("Enable Local AI in the sidebar to generate a cited narrative. Optional.")
        return
    if "narrative" not in st.session_state and st.button("Generate narrative"):
        with st.spinner("Asking the local model..."):
            st.session_state["narrative"] = pipeline.narrate(
                result, OllamaClient(host=host, model=model)
            )
        n = st.session_state["narrative"]
        if isinstance(n, Narrative) and (store := _store()) is not None:
            store.save_narrative(doc_id, n)
            store.close()
    n = st.session_state.get("narrative")
    if n is None:
        return
    if isinstance(n, Unavailable):
        st.warning(f"No narrative: {n.detail}. The figures above are unaffected.")
        return
    st.markdown(n.summary)
    for ins in n.insights:
        st.markdown(f"- {ins.text}")
        st.caption(f"cites: {', '.join(ins.cites)}")
    st.caption(
        f"Generated by {n.model}. Every number and citation was checked against the analysis."
    )


def main() -> None:
    st.set_page_config(page_title="Finance Copilot", page_icon="📊", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)
    use_ai, host, model = _sidebar()
    current = st.session_state.get("current")
    if current is None:
        st.title("Finance Copilot")
        st.markdown(
            "Upload an annual report to see verified financial values, ratios, "
            "year-over-year changes, reconciliation checks, and red flags. "
            "Every figure links back to the page and row it came from."
        )
        st.markdown("**History**")
        _history_tab()
        return

    result = current["result"]
    basis = views.basis_notice(result)
    st.title(current["name"])
    label = html.escape(result.basis.value.replace("_", " "))
    st.markdown(f'<span class="badge {basis.level}">{label}</span>', unsafe_allow_html=True)
    if basis.level != "info":
        _notice(basis)
    if (pn := views.period_notice(result)) is not None:
        _notice(pn)

    cards = views.kpi_cards(result)
    if cards:
        cols = st.columns(len(cards))
        for col, c in zip(cols, cards, strict=True):
            col.markdown(_kpi_html(c), unsafe_allow_html=True)
    st.caption(
        "Green: verified. Amber: usable but lower confidence. Grey: not available, with the reason."
    )

    names = [
        "Overview",
        "Values",
        "Metrics & changes",
        "Reconciliation",
        "Red flags",
        "Provenance",
        "History",
    ]
    tabs = st.tabs(names)
    with tabs[0]:
        fired = [r for r in views.red_flag_rows(result) if r["status"] == "fired"]
        st.subheader(f"Red flags fired: {len(fired)}")
        _table(fired)
        if w := views.warning_count(result):
            st.warning(f"{w} reconciliation check(s) did not tie out. See the Reconciliation tab.")
        _narrative_section(result, use_ai, host, model, result.document_id)
    with tabs[1]:
        _table(views.value_rows(result))
    with tabs[2]:
        st.subheader("Ratios")
        _table(views.metric_rows(result))
        st.subheader("Year-over-year change")
        _table(views.trend_rows(result))
    with tabs[3]:
        _table(views.reconciliation_rows(result))
    with tabs[4]:
        _table(views.red_flag_rows(result))
    with tabs[5]:
        refs = [r["ref_id"] for r in views.value_rows(result) if r["ref_id"]]
        if not refs:
            st.caption("No mapped cells.")
        else:
            pick = st.selectbox(
                "Cell",
                refs,
                format_func=lambda r: f"{r}  ({views.provenance(result, r)['concept']})",
            )
            st.json(views.provenance(result, pick))
    with tabs[6]:
        _history_tab()


main()
