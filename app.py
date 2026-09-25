"""Finance Copilot dashboard. UI wiring only (spec 2.2).

Every number on screen comes from pipeline.analyze(). This file formats,
lays out, and persists. It never computes a financial value.
"""

from __future__ import annotations

import hashlib
import html
import os
from pathlib import Path
from typing import NamedTuple

import pandas as pd
import pipeline
import streamlit as st

from fincopilot import __version__, charts, panel, views
from fincopilot.ai.client import (
    DEFAULT_TIMEOUT_S,
    GEMINI_DEFAULT_MODEL,
    GeminiClient,
    OllamaClient,
)
from fincopilot.extract.pdf import IngestionError
from fincopilot.store import Store
from fincopilot.types import Narrative, Unavailable

DB_PATH = Path(os.environ.get("FINCOPILOT_DB", "data/fincopilot.sqlite"))
# History is per-machine, and on a shared deployment one machine serves every
# visitor: without this, one person's uploaded report is listed for the next.
# Hosted demos set FINCOPILOT_HISTORY=off. Local runs keep it on.
HISTORY_ON = os.environ.get("FINCOPILOT_HISTORY", "on").strip().lower() not in {
    "off",
    "0",
    "false",
    "no",
}
SAMPLE_PDF = Path(__file__).parent / "tests" / "fixtures" / "golden_us.pdf"

STATUS_PILL = {
    "ok": ("#10301f", "#3ddc97"),
    "passed": ("#10301f", "#3ddc97"),
    "clear": ("#10301f", "#3ddc97"),
    "low": ("#33260c", "#ffb454"),
    "warning": ("#33260c", "#ffb454"),
    "fired": ("#3a1517", "#ff6b6b"),
    "na": ("#1b222e", "#8b96a8"),
    "unavailable": ("#1b222e", "#8b96a8"),
    "not_evaluated": ("#1b222e", "#8b96a8"),
}
ROW_TINT = {
    "ok": "#0f1a16",
    "passed": "#0f1a16",
    "clear": "#0f1a16",
    "low": "#1c1810",
    "warning": "#1c1810",
    "fired": "#1e1214",
    "na": "#11151d",
    "unavailable": "#11151d",
    "not_evaluated": "#11151d",
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
:root {
  --bg:#0b0e14; --surface:#151b26; --surface-2:#1b2331; --line:#232c3b;
  --ink:#e6ebf2; --muted:#8b96a8; --faint:#5d6878;
  --accent:#4da3ff; --pos:#3ddc97; --neg:#ff6b6b; --warn:#ffb454;
  --mono: ui-monospace, "SF Mono", "Cascadia Mono", "Segoe UI Mono", "Roboto Mono", monospace;
}
#MainMenu, footer {visibility:hidden; height:0;}
/* The header holds the expand-sidebar button: hiding it strands a collapsed sidebar. */
header[data-testid="stHeader"] {background:transparent;}
.stApp {background:var(--bg);}
.block-container {padding-top:1.4rem; padding-bottom:4rem; max-width:1320px;}
section[data-testid="stSidebar"] {background:var(--surface); border-right:1px solid var(--line);}
h1,h2,h3,h4 {letter-spacing:-.02em;}
/* Every figure in the product is monospaced and tabular, so digits line up
   column to column and a value never jitters as it changes. */
.num, .kpi .value, .fact b, .cite {font-variant-numeric:tabular-nums; font-family:var(--mono);}

.brand {font-size:1.3rem; font-weight:700; letter-spacing:-.02em; color:var(--ink);}
.brand small {display:block; font-size:.74rem; font-weight:400; color:var(--muted); margin-top:3px;
  letter-spacing:0;}
.doc-title {font-size:1.9rem; font-weight:700; letter-spacing:-.03em; margin:0 0 .2rem;}
.facts {display:flex; gap:8px; flex-wrap:wrap; margin:0 0 1.1rem;}
.fact {background:var(--surface); border:1px solid var(--line); border-radius:7px;
  padding:5px 11px; font-size:.79rem; color:var(--muted);}
.fact b {color:var(--ink); font-weight:600;}
.badge {display:inline-block; padding:4px 11px; border-radius:999px; font-size:.7rem;
  font-weight:700; letter-spacing:.09em; text-transform:uppercase;}
.badge.info {background:#10243a; color:#7ab8ff}
.badge.warning {background:#33260c; color:var(--warn)}
.badge.error {background:#3a1517; color:var(--neg)}

.eyebrow {font-size:.68rem; font-weight:700; letter-spacing:.14em; text-transform:uppercase;
  color:var(--faint); margin-bottom:3px;}
.section {margin:2rem 0 .5rem;}
.section h3 {margin:0 0 .3rem; font-size:1.1rem; color:var(--ink);}
.section p {margin:0; font-size:.85rem; color:var(--muted); max-width:780px; line-height:1.5;}
.missing {font-size:.78rem; color:var(--warn); background:#1c1810; border:1px solid #3a2f14;
  border-radius:8px; padding:8px 12px; margin:.3rem 0 0;}
.legend {font-size:.77rem; color:var(--faint); margin:.5rem 0 1rem;}
.legend span {display:inline-block; width:9px; height:9px; border-radius:2px; margin:0 5px 0 14px;
  vertical-align:middle;}
.card {border:1px solid var(--line); border-radius:12px; padding:18px 20px;
  background:var(--surface); margin-bottom:12px;}
.card p {color:var(--ink);}
.cite {display:inline-block; font-size:.68rem; background:var(--surface-2); color:var(--muted);
  border:1px solid var(--line); border-radius:4px; padding:1px 6px; margin:2px 3px 0 0;}
.hero {padding:3rem 0 1.4rem;}
.hero h1 {font-size:2.6rem; letter-spacing:-.035em; margin:0 0 .5rem; color:var(--ink);}
.hero p {font-size:1.02rem; color:var(--muted); max-width:700px; margin:0 0 1.6rem;
  line-height:1.6;}
.feature {border:1px solid var(--line); border-radius:12px; padding:16px 18px;
  background:var(--surface); min-height:152px;}
.feature h4 {margin:0 0 .45rem; font-size:.92rem; color:var(--accent);}
.feature p {margin:0; font-size:.84rem; color:var(--muted); line-height:1.5;}
.foot {margin-top:2.5rem; padding-top:1rem; border-top:1px solid var(--line); font-size:.74rem;
  color:var(--faint);}
[data-testid="stDataFrame"] {border:1px solid var(--line); border-radius:10px;}
.stTabs [data-baseweb="tab"] {font-size:.9rem;}
</style>
"""


# --- helpers (formatting and wiring only) ------------------------------------


class AiSettings(NamedTuple):
    """What the sidebar chose. Hashable, so it can key the analysis cache."""

    on: bool
    provider: str
    host: str
    model: str


def _gemini_key() -> str:
    """Streamlit secrets first, then the environment. Never written to disk."""
    try:
        key = st.secrets.get("GEMINI_API_KEY", "")
    except Exception:
        key = ""
    return str(key or os.environ.get("GEMINI_API_KEY", "")).strip()


def _client(ai: AiSettings, timeout_s: float):
    if not ai.on:
        return None
    if ai.provider == "gemini":
        return GeminiClient(api_key=_gemini_key(), model=ai.model, timeout_s=timeout_s)
    return OllamaClient(host=ai.host, model=ai.model, timeout_s=timeout_s)


@st.cache_data(show_spinner=False)
def _analyze(data: bytes, ai: AiSettings):
    return pipeline.analyze(data, llm=_client(ai, DEFAULT_TIMEOUT_S))


def _store() -> Store | None:
    if not HISTORY_ON:
        return None
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
    has_status = "status" in df.columns
    if has_status:
        df["status"] = df["status"].map(lambda s: views.STATUS_WORD.get(s, s))
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


def _load(name: str, data: bytes, ai: AiSettings) -> None:
    sha = hashlib.sha256(data).hexdigest()
    if st.session_state.get("current", {}).get("sha256") == sha:
        return
    try:
        with st.spinner("Reading the statements. Large reports take a minute or two."):
            result = _analyze(data, ai)
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


def _sidebar() -> AiSettings:
    sb = st.sidebar
    sb.markdown(
        '<div class="brand">Finance Copilot'
        "<small>Annual report analysis, local-first</small></div>",
        unsafe_allow_html=True,
    )
    sb.markdown("")
    upload = sb.file_uploader("Annual report (PDF, up to 50 MB)", type=["pdf"])
    # Gemini needs only a key, so it works on a host with no model server.
    # Ollama needs a running daemon, which a hosted container does not have.
    has_gemini = bool(_gemini_key())
    providers = (["gemini"] if has_gemini else []) + ["ollama"]
    sb.markdown("**AI assist**")
    use_ai = sb.toggle(
        "AI assist",
        value=False,
        help="Optional. Picks rows the exact-match tables could not name and writes a "
        "cited narrative. It never supplies a number.",
        label_visibility="collapsed",
    )
    with sb.expander("AI settings", expanded=False):
        provider = st.radio(
            "Provider",
            providers,
            format_func=lambda p: "Gemini (cloud)" if p == "gemini" else "Ollama (this machine)",
            horizontal=True,
        )
        if provider == "gemini":
            host = ""
            model = st.text_input(
                "Model", os.environ.get("FINCOPILOT_GEMINI_MODEL", GEMINI_DEFAULT_MODEL)
            )
            st.caption("Your PDF text is sent to Google for the rows it is asked about.")
        else:
            host = st.text_input(
                "Ollama host", os.environ.get("FINCOPILOT_OLLAMA_HOST", "http://localhost:11434")
            )
            model = st.text_input("Model", os.environ.get("FINCOPILOT_OLLAMA_MODEL", "qwen2.5:3b"))
            if not has_gemini:
                st.caption("Needs Ollama running on the machine serving this page.")
    ai = AiSettings(on=use_ai, provider=provider, host=host, model=model)
    if upload is not None:
        _load(upload.name, upload.getvalue(), ai)
    elif sb.button("Load sample report", help="A synthetic US-style report used in tests."):
        if SAMPLE_PDF.is_file():
            _load(SAMPLE_PDF.name, SAMPLE_PDF.read_bytes(), ai)
        else:
            sb.error("Sample not found. Run: uv run python -m tests.fixtures.build_fixtures")
    sb.markdown(
        f'<div class="foot">Every figure links to the page and row it came from. '
        f"No AI ever supplies a number.<br>v{__version__}</div>",
        unsafe_allow_html=True,
    )
    return ai


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
        ("Optional AI", "Picks unmatched rows and writes a cited narrative. Never a number."),
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
    st.html(panel.kpi_html(cards))
    st.markdown(
        '<div class="legend">Latest year. <span style="background:#3ddc97"></span>verified '
        '<span style="background:#ffb454"></span>lower confidence '
        '<span style="background:#232c3b"></span>not available, reason shown</div>',
        unsafe_allow_html=True,
    )


def _narrative(result, ai: AiSettings) -> None:
    st.markdown("#### Plain-English reading")
    if not ai.on:
        st.caption("Switch on AI assist in the sidebar to generate a cited narrative. Optional.")
        return
    if "narrative" not in st.session_state and st.button("Generate narrative", type="primary"):
        with st.spinner("Asking the model. This can take a minute."):
            st.session_state["narrative"] = pipeline.narrate(result, _client(ai, 240))
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
    if not HISTORY_ON:
        st.caption(
            "History is switched off on this deployment. Everyone shares one machine "
            "here, so one visitor's analysis would otherwise be listed for the next. "
            "Run it locally and your analyses are kept in a SQLite file on your disk."
        )
        return
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
    for note in p["notes"]:
        st.markdown(f'<div class="missing">{html.escape(note)}</div>', unsafe_allow_html=True)
    with st.expander("Raw record"):
        st.json(p)


def _section(eyebrow: str, title: str, body: str) -> None:
    st.markdown(
        f'<div class="section"><div class="eyebrow">{html.escape(eyebrow)}</div>'
        f"<h3>{html.escape(title)}</h3><p>{html.escape(body)}</p></div>",
        unsafe_allow_html=True,
    )


def _chart(c: charts.Chart, eyebrow: str) -> None:
    """A chart, what it cannot show, and the exact numbers one click away."""
    _section(eyebrow, c.title, c.subtitle)
    st.vega_lite_chart(c.spec, width="stretch", theme=None)
    if c.missing:
        st.markdown(
            '<div class="missing">Not shown, because the report did not give it: '
            + html.escape("; ".join(c.missing[:6]))
            + ("; and more" if len(c.missing) > 6 else "")
            + "</div>",
            unsafe_allow_html=True,
        )
    with st.expander("Show the numbers behind this chart"):
        st.dataframe(
            pd.DataFrame([{k: str(v) for k, v in r.items()} for r in c.rows]),
            width="stretch",
            hide_index=True,
        )


def _flag_grid(result) -> None:
    rows = views.red_flag_rows(result)
    fired = sum(1 for r in rows if r["status"] == "fired")
    clear = sum(1 for r in rows if r["status"] == "clear")
    body = (
        f"{fired} of {len(rows)} rules fired. A rule that could not be evaluated is not a pass."
        if fired
        else f"No rule fired. {clear} rules were checked and came back clean."
    )
    _section("Verdict", "Red flags", body)
    st.html(panel.flag_html(rows))


def _results(result, ai: AiSettings) -> None:
    _flag_grid(result)
    if w := views.warning_count(result):
        st.warning(f"{w} cross-check did not tie out. The chart below shows by how much.")
    _narrative(result, ai)
    eyebrows = {
        "performance": "Scale",
        "margins": "Profitability",
        "balance": "Balance sheet",
        "cash": "Cash",
        "reconciliation": "Does it add up",
    }
    drawn = charts.charts(result)
    if not drawn:
        st.info("No chart can be drawn: the periods in this document could not be determined.")
        return
    for c in drawn:
        _chart(c, eyebrows.get(c.key, "Result"))


def _document(current: dict, ai: AiSettings) -> None:
    result = current["result"]
    _header(current, result)
    _kpis(result)
    names = ["Results", "Values", "Metrics & changes", "Red flags", "Provenance", "History"]
    tabs = st.tabs(names)
    with tabs[0]:
        _results(result, ai)
    with tabs[1]:
        st.caption("Every figure the pipeline used, in the report's own units, with its source.")
        _table(views.value_rows(result), hide=("ref_id",))
    with tabs[2]:
        st.markdown("#### Ratios")
        _table(views.metric_rows(result))
        st.markdown("#### Year-over-year change")
        st.caption("'Reads as' says whether the movement is good or bad for the business.")
        _table(views.trend_rows(result))
        st.markdown("#### Cross-checks")
        _table(views.reconciliation_rows(result))
    with tabs[3]:
        _table(views.red_flag_rows(result))
    with tabs[4]:
        _provenance(result)
    with tabs[5]:
        _history()


def main() -> None:
    st.set_page_config(page_title="Finance Copilot", page_icon="📊", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)
    ai = _sidebar()
    current = st.session_state.get("current")
    if current is None:
        _landing()
    else:
        _document(current, ai)


if __name__ == "__main__":
    main()
