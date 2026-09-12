"""Finance Copilot dashboard. UI wiring only (spec 2.2).

Every number on screen comes from pipeline.analyze(). This file formats,
lays out, and persists. It never computes a financial value.
"""

from __future__ import annotations

import hashlib
import html
import os
from pathlib import Path

import pandas as pd
import pipeline
import streamlit as st

from fincopilot import __version__, views
from fincopilot.ai.client import OllamaClient
from fincopilot.extract.pdf import IngestionError
from fincopilot.store import Store
from fincopilot.types import Narrative, Unavailable

DB_PATH = Path(os.environ.get("FINCOPILOT_DB", "data/fincopilot.sqlite"))
SAMPLE_PDF = Path(__file__).parent / "tests" / "fixtures" / "golden_us.pdf"

STATUS_PILL = {
    "ok": ("Verified", "#e6f4ea", "#1e6b3a"),
    "passed": ("Passed", "#e6f4ea", "#1e6b3a"),
    "clear": ("Clear", "#e6f4ea", "#1e6b3a"),
    "low": ("Lower confidence", "#fff4d6", "#8a5a00"),
    "warning": ("Warning", "#fff4d6", "#8a5a00"),
    "fired": ("Fired", "#fde8e6", "#9b2c20"),
    "na": ("Not available", "#eef0f3", "#5b6675"),
    "unavailable": ("Not available", "#eef0f3", "#5b6675"),
    "not_evaluated": ("Not evaluated", "#eef0f3", "#5b6675"),
}
ROW_TINT = {
    "ok": "#f4faf6",
    "passed": "#f4faf6",
    "clear": "#f4faf6",
    "low": "#fffaf0",
    "warning": "#fffaf0",
    "fired": "#fdf3f2",
    "na": "#f7f8fa",
    "unavailable": "#f7f8fa",
    "not_evaluated": "#f7f8fa",
}
COLUMN_TITLES = {
    "concept": "Concept",
    "period": "Year",
    "value": "Value",
    "page": "Page",
    "source_row": "Row in report",
    "how_found": "How matched",
    "ref_id": "Cell id",
    "status": "Status",
    "metric": "Metric",
    "inputs": "Inputs",
    "subject": "Item",
    "from": "From",
    "to": "To",
    "change": "Change",
    "direction": "Direction",
    "reads_as": "Reads as",
    "check": "Check",
    "detail": "Detail",
    "refs": "Cells",
    "rule": "Rule",
    "severity": "Severity",
    "message": "Finding",
}

CSS = """
<style>
#MainMenu, footer, header[data-testid="stHeader"] {visibility: hidden; height: 0;}
.block-container {padding-top: 1.6rem; padding-bottom: 3rem; max-width: 1280px;}
section[data-testid="stSidebar"] {border-right: 1px solid #e6e9ee;}
.brand {font-size: 1.35rem; font-weight: 700; letter-spacing: -.01em; color: #1f4e79;}
.brand small {display:block; font-size:.78rem; font-weight:400; color:#5b6675; margin-top:2px}
.doc-title {font-size: 1.9rem; font-weight: 700; letter-spacing: -.02em; margin: 0 0 .2rem 0;}
.facts {display:flex; gap:10px; flex-wrap:wrap; margin: 0 0 1.2rem 0;}
.fact {background:#f5f7fa; border:1px solid #e6e9ee; border-radius:8px; padding:6px 12px;
  font-size:.82rem; color:#3a4656;}
.fact b {color:#1c2430; font-weight:600;}
.badge {display:inline-block; padding:3px 10px; border-radius:999px; font-size:.78rem;
  font-weight:600; letter-spacing:.02em; text-transform:uppercase;}
.badge.info {background:#e3eefa; color:#1f4e79}
.badge.warning {background:#fff1cc; color:#8a5a00}
.badge.error {background:#fde8e6; color:#9b2c20}
.kpi {border:1px solid #e6e9ee; border-radius:12px; padding:16px 18px; background:#fff;
  min-height:132px; box-shadow:0 1px 2px rgba(16,24,40,.04);}
.kpi.ok {border-top:4px solid #2e8b57}
.kpi.low {border-top:4px solid #e0a100; background:#fffdf7}
.kpi.na {border:1px dashed #c4c9d1; border-top:4px dashed #c4c9d1; background:#f7f8fa;
  color:#5b6675}
.kpi {display:flex; flex-direction:column;}
.kpi .label {font-size:.72rem; color:#5b6675; text-transform:uppercase; letter-spacing:.06em;
  font-weight:600; min-height:2.2em; line-height:1.1;}
.kpi .value {font-size:1.85rem; font-weight:700; margin:6px 0 2px; letter-spacing:-.02em;}
.kpi.na .value {font-size:1.25rem; font-style:italic; font-weight:500;}
.kpi .delta {font-size:.82rem; font-weight:600;}
.kpi .note {font-size:.74rem; color:#7a8594; margin-top:auto; padding-top:6px; line-height:1.3;}
.up {color:#1e6b3a} .down {color:#9b2c20} .flat {color:#5b6675}
.legend {font-size:.78rem; color:#7a8594; margin:.6rem 0 1.2rem;}
.legend span {display:inline-block; width:10px; height:10px; border-radius:3px;
  margin:0 4px 0 12px; vertical-align:middle;}
.card {border:1px solid #e6e9ee; border-radius:12px; padding:18px 20px; background:#fff;
  margin-bottom:12px;}
.card h4 {margin:0 0 .5rem; font-size:1rem;}
.cite {display:inline-block; font-family:ui-monospace, Menlo, monospace; font-size:.7rem;
  background:#f0f3f7; color:#3a4656; border-radius:4px; padding:1px 6px; margin:0 2px;}
.hero {padding: 2.5rem 0 1rem;}
.hero h1 {font-size:2.4rem; letter-spacing:-.03em; margin:0 0 .4rem;}
.hero p {font-size:1.05rem; color:#3a4656; max-width:720px; margin:0 0 1.4rem;}
.feature {border:1px solid #e6e9ee; border-radius:12px; padding:16px 18px; background:#fff;
  min-height:150px;}
.feature h4 {margin:0 0 .4rem; font-size:.95rem; color:#1f4e79;}
.feature p {margin:0; font-size:.85rem; color:#3a4656; line-height:1.45;}
.foot {margin-top:3rem; padding-top:1rem; border-top:1px solid #e6e9ee; font-size:.76rem;
  color:#7a8594;}
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


def _pill(status: str) -> str:
    _, bg, fg = STATUS_PILL.get(status, (status, "#eef0f3", "#5b6675"))
    return f"background:{bg};color:{fg};font-weight:600;border-radius:999px;padding:2px 10px;"


def _table(rows: list[dict], *, hide: tuple[str, ...] = ()) -> None:
    if not rows:
        st.caption("Nothing to show.")
        return
    df = pd.DataFrame(rows).drop(columns=list(hide), errors="ignore")
    has_status = "status" in df.columns
    if has_status:
        df["status"] = df["status"].map(lambda s: STATUS_PILL.get(s, (s,))[0])
        raw = pd.DataFrame(rows)["status"].tolist()

    def tint(row):
        s = raw[row.name] if has_status else ""
        return [f"background-color:{ROW_TINT.get(s, '#fff')}"] * len(row)

    styled = df.style.apply(tint, axis=1)
    if has_status:
        styled = styled.map(lambda _: "", subset=["status"])
    st.dataframe(
        styled,
        width="stretch",
        hide_index=True,
        column_config={k: st.column_config.Column(v) for k, v in COLUMN_TITLES.items()},
    )


def _kpi_html(c: views.Kpi) -> str:
    delta = ""
    if c.delta:
        cls = {"positive": "up", "negative": "down"}.get(c.delta_reads, "flat")
        delta = f'<div class="delta {cls}">{html.escape(c.delta)} vs prior year</div>'
    return (
        f'<div class="kpi {c.status}"><div class="label">{html.escape(c.label)}</div>'
        f'<div class="value">{html.escape(c.value)}</div>{delta}'
        f'<div class="note">{html.escape(c.note)}</div></div>'
    )


def _size(n: int) -> str:
    return f"{n / 1_048_576:.1f} MB" if n >= 1_048_576 else f"{n / 1024:.0f} KB"


def _notice(n: views.Notice) -> None:
    {"info": st.info, "warning": st.warning, "error": st.error}[n.level](n.text)


def _load(name: str, data: bytes, use_ai: bool, host: str, model: str) -> None:
    sha = hashlib.sha256(data).hexdigest()
    if st.session_state.get("current", {}).get("sha256") == sha:
        return
    try:
        with st.spinner("Reading the statements. Large reports take a minute or two."):
            result = _analyze(data, use_ai, host, model)
    except IngestionError as exc:
        st.sidebar.error(f"Cannot analyse this file: {exc}")
        return
    except Exception as exc:
        st.sidebar.error(f"Analysis failed ({type(exc).__name__}). Nothing was saved.")
        return
    st.session_state["current"] = {"name": name, "sha256": sha, "result": result, "size": len(data)}
    st.session_state.pop("narrative", None)
    if (store := _store()) is not None:
        store.save(result, name=name, data=data)
        store.close()


# --- sidebar -----------------------------------------------------------------


def _sidebar() -> tuple[bool, str, str]:
    sb = st.sidebar
    sb.markdown(
        '<div class="brand">Finance Copilot'
        "<small>Annual report analysis, local-first</small></div>",
        unsafe_allow_html=True,
    )
    sb.markdown("")
    upload = sb.file_uploader("Annual report (PDF, up to 50 MB)", type=["pdf"])
    sb.markdown("**Local AI**")
    use_ai = sb.toggle(
        "Local AI (Ollama)",
        value=False,
        help="Optional. Picks rows the exact-match tables could not name and writes a "
        "cited narrative. It never supplies a number.",
        label_visibility="collapsed",
    )
    with sb.expander("AI settings", expanded=False):
        host = st.text_input(
            "Ollama host", os.environ.get("FINCOPILOT_OLLAMA_HOST", "http://localhost:11434")
        )
        model = st.text_input("Model", os.environ.get("FINCOPILOT_OLLAMA_MODEL", "qwen2.5:3b"))
    if upload is not None:
        _load(upload.name, upload.getvalue(), use_ai, host, model)
    elif sb.button("Load sample report", help="A synthetic US-style report used in tests."):
        if SAMPLE_PDF.is_file():
            _load(SAMPLE_PDF.name, SAMPLE_PDF.read_bytes(), use_ai, host, model)
        else:
            sb.error("Sample not found. Run: uv run python -m tests.fixtures.build_fixtures")
    sb.markdown(
        f'<div class="foot">Every figure links to the page and row it came from. '
        f"No AI ever supplies a number.<br>v{__version__}</div>",
        unsafe_allow_html=True,
    )
    return use_ai, host, model


# --- sections ----------------------------------------------------------------


def _landing() -> None:
    st.markdown(
        '<div class="hero"><h1>Finance Copilot</h1>'
        "<p>Upload an annual report and get verified financial values, ratios, year-over-year "
        "changes, reconciliation checks and red flags. Every figure links back to the page "
        "and row it came from. Nothing is guessed.</p></div>",
        unsafe_allow_html=True,
    )
    cols = st.columns(4)
    features = (
        (
            "Numbers from the document only",
            "A value cannot exist without the PDF cell it came from.",
        ),
        ("Nothing guessed", "What cannot be determined is shown as unavailable, with the reason."),
        (
            "Checks that add up",
            "Assets against liabilities and equity, gross profit, free cash flow.",
        ),
        ("Optional local AI", "Picks unmatched rows and writes a cited narrative. Never a number."),
    )
    for col, (h, p) in zip(cols, features, strict=True):
        col.markdown(f'<div class="feature"><h4>{h}</h4><p>{p}</p></div>', unsafe_allow_html=True)
    st.markdown("")
    st.markdown("Use **Upload** or **Load sample report** in the sidebar to begin.")
    st.markdown("#### Recent analyses")
    _history()


def _header(current: dict, result) -> None:
    basis = views.basis_notice(result)
    st.title(current["name"])
    periods = (
        ""
        if isinstance(result.periods, Unavailable)
        else ", ".join(str(p.end_year) for p in result.periods.ordered)
    )
    currency = next((v.currency for v in result.values), "")
    label = html.escape(result.basis.value.replace("_", " "))
    facts = [
        f'<span class="badge {basis.level}">{label}</span>',
        f"<span class='fact'>Years <b>{html.escape(periods) or 'not determined'}</b></span>",
        f"<span class='fact'>Values found <b>{len(result.values)}</b></span>",
        f"<span class='fact'>Size <b>{_size(current.get('size', 0))}</b></span>",
    ]
    if currency:
        facts.insert(2, f"<span class='fact'>Currency <b>{html.escape(currency)}</b></span>")
    st.markdown(f'<div class="facts">{"".join(facts)}</div>', unsafe_allow_html=True)
    if basis.level != "info":
        _notice(basis)
    if (pn := views.period_notice(result)) is not None:
        _notice(pn)


def _kpis(result) -> None:
    cards = views.kpi_cards(result)
    if not cards:
        return
    cols = st.columns(len(cards))
    for col, c in zip(cols, cards, strict=True):
        col.markdown(_kpi_html(c), unsafe_allow_html=True)
    st.markdown(
        '<div class="legend">Latest year. <span style="background:#2e8b57"></span>verified '
        '<span style="background:#e0a100"></span>lower confidence '
        '<span style="background:#c4c9d1"></span>not available, reason shown</div>',
        unsafe_allow_html=True,
    )


def _narrative(result, use_ai: bool, host: str, model: str) -> None:
    st.markdown("#### Plain-English reading")
    if not use_ai:
        st.caption("Switch on Local AI in the sidebar to generate a cited narrative. Optional.")
        return
    if "narrative" not in st.session_state and st.button("Generate narrative", type="primary"):
        with st.spinner("Asking the local model. About a minute."):
            st.session_state["narrative"] = pipeline.narrate(
                result, OllamaClient(host=host, model=model, timeout_s=240)
            )
        n = st.session_state["narrative"]
        if isinstance(n, Narrative) and (store := _store()) is not None:
            store.save_narrative(result.document_id, n)
            store.close()
    n = st.session_state.get("narrative")
    if n is None:
        return
    if isinstance(n, Unavailable):
        st.warning(f"No narrative: {n.detail}. The figures above are unaffected.")
        return
    items = "".join(
        f"<li>{html.escape(i.text)}<br>"
        + "".join(f'<span class="cite">{html.escape(c)}</span>' for c in i.cites)
        + "</li>"
        for i in n.insights
    )
    st.markdown(
        f'<div class="card"><p>{html.escape(n.summary)}</p><ul>{items}</ul>'
        f'<div class="legend">Written by {html.escape(n.model)}. Every number and citation was '
        f"checked against the analysis; a narrative with one unverifiable figure is discarded "
        f"whole.</div></div>",
        unsafe_allow_html=True,
    )


def _history() -> None:
    store = _store()
    if store is None:
        st.caption("History unavailable (database could not be opened).")
        return
    docs = store.list_documents()
    if not docs:
        st.caption("No documents analysed yet.")
    for d in docs:
        periods = ", ".join(map(str, d.periods)) or "no periods"
        when = d.analyzed_at.replace("T", " ")[:16]
        title = f"{d.name}  ·  {d.basis.replace('_', ' ')}  ·  {periods}  ·  {when}"
        with st.expander(title, expanded=False):
            st.caption(f"SHA-256 {d.sha256[:16]}…  ·  {d.size_bytes:,} bytes  ·  PDF not stored")
            _table(views.history_metric_rows(store.load_metrics(d.document_id)))
            if (n := store.load_narrative(d.document_id)) is not None:
                st.markdown(f"**AI summary ({n.model}):** {n.summary}")
            if st.button("Remove from history", key=f"del_{d.document_id}"):
                store.delete(d.document_id)
                st.rerun()
    store.close()


def _provenance(result) -> None:
    refs = [r["ref_id"] for r in views.value_rows(result) if r["ref_id"]]
    if not refs:
        st.caption("No mapped cells.")
        return

    def name(r: str) -> str:
        p = views.provenance(result, r)
        return f"{p['concept']} {p['period']}  ·  {r}"

    p = views.provenance(result, st.selectbox("Choose a figure", refs, format_func=name))
    a, b = st.columns(2)
    where = f"**Page {p['page']}**, table {p['table']}, row {p['row']}"
    if p["column"] is not None:
        where += f", column {p['column']}"
    a.markdown(where)
    a.markdown(f"Row label: `{p['row_label']}`")
    a.markdown(f"Printed text: `{p['raw_text']}`")
    b.markdown(f"Scale: {p['scale']}  ·  Currency: {p['currency']}")
    b.markdown(f"Value in base units: `{p['value_in_base_units']}`")
    if p["dash_zero"]:
        b.warning("This cell was a dash, read as zero by the dash rule.")
    with st.expander("Raw record"):
        st.json(p)


def _document(current: dict, use_ai: bool, host: str, model: str) -> None:
    result = current["result"]
    _header(current, result)
    _kpis(result)
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
        flags = views.red_flag_rows(result)
        fired = [r for r in flags if r["status"] == "fired"]
        st.markdown(f"#### Red flags fired: {len(fired)}")
        if fired:
            _table(fired, hide=("refs",))
        else:
            clear = sum(1 for r in flags if r["status"] == "clear")
            st.caption(f"None of the {clear} rules that could be evaluated fired.")
        if w := views.warning_count(result):
            st.warning(f"{w} reconciliation check(s) did not tie out. See the Reconciliation tab.")
        st.markdown("")
        _narrative(result, use_ai, host, model)
    with tabs[1]:
        st.caption("Every figure the pipeline used, in the report's own units, with its source.")
        _table(views.value_rows(result), hide=("ref_id",))
    with tabs[2]:
        st.markdown("#### Ratios")
        _table(views.metric_rows(result))
        st.markdown("#### Year-over-year change")
        st.caption("'Reads as' says whether the movement is good or bad for the business.")
        _table(views.trend_rows(result))
    with tabs[3]:
        _table(views.reconciliation_rows(result))
    with tabs[4]:
        _table(views.red_flag_rows(result))
    with tabs[5]:
        _provenance(result)
    with tabs[6]:
        _history()


def main() -> None:
    st.set_page_config(page_title="Finance Copilot", page_icon="📊", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)
    use_ai, host, model = _sidebar()
    current = st.session_state.get("current")
    if current is None:
        _landing()
    else:
        _document(current, use_ai, host, model)


if __name__ == "__main__":
    main()
