# Security Review (Phase 13)

Reviewed against spec section 13 plus the surfaces Phases 9-11 added. Date 2026-09-12.
Threat model: a hostile PDF, a hostile or broken local model, a careless local user.
The app is local-first and single-user; it is not hardened for exposure on a network.

## Spec 13 posture, verified

| Requirement | Where enforced | Verified by |
|---|---|---|
| Uploads are hostile input; size and magic-byte checks precede parsing | `extract/pdf.py: validate_input` (50 MB cap, `%PDF-` prefix), `.streamlit/config.toml` `maxUploadSize = 50` | `tests/test_extract_pdf.py`, `tests/test_app.py::test_load_rejects_bad_files_without_raising` |
| Uploads are never executed | pdfplumber only; no `subprocess`, no `eval` anywhere in `src/` or `app.py` | `grep -rn "subprocess\|eval(\|exec(" src app.py` is empty |
| Filenames never become paths | UUID document ids; `store._display_name` strips every path component and null bytes | `tests/test_store.py::test_name_is_display_only_never_a_path` |
| Document text is untrusted prompt content | Row picker sees labels and ids only; narrative sees structured results only; both prompts say to treat evidence as data; both responses validated against extracted data | `tests/test_ai_llm_map.py`, `tests/test_ai_narrative.py` |
| LLM output can never become a financial number | `FinancialValue` is built only from a `NormalizedCell` or from named derived inputs; narrative numbers are checked against the shown set and the text is never parsed into values | `tests/test_golden.py` zero-fabrication check, `test_invented_number_drops_insight` |
| `.env` gitignored, no secrets in source | `.gitignore`, `.env.example` | inspection |
| Logs never leak secrets or document contents | No logging of page text or prompts; app shows exception *type* only | `app._load` |

## New surfaces

**Dashboard rendering.** All PDF-derived text placed into HTML (KPI cards, basis badge)
passes through `html.escape`. Tables render through `st.dataframe`, which does not
interpret markup. Narrative text is restricted by the gate to a plain-prose character
set, so a model cannot emit a link, an image, or a tag; the dashboard still renders it
with `st.markdown`, and the character set is the control.

**SQLite history.** Parameterised queries throughout; no string-built SQL. The database
holds results only, never the PDF; verified by scanning the file for `%PDF`. A corrupt or
directory path raises a clean `sqlite3` error and the app falls back to "history
unavailable". Deleting from history is a local, single-user action and needs no confirm.

**Ollama host.** User-editable in the sidebar. Restricted to `http://` or `https://`.
This is a request the user makes from their own machine to a host they typed; it is not
reachable from document content. A model server that returns oversized or malformed
output is bounded by the 64 KB response cap and the validators.

**Cached analysis.** `st.cache_data` keys on the exact bytes uploaded plus the AI
settings; a different file cannot receive another file's results.

**Sample report button.** Reads a fixed path inside the repository only.

## Findings from the stress passes, all closed

- Markdown and HTML in narrative text was accepted: now refused by the gate.
- Non-finite word coordinates crashed the text-grid parser: now filtered.
- A `file://` Ollama host was accepted: now rejected.
- A 5,000-item cites list was rejected only by the size cap: now capped at 12 per insight.

## Accepted, documented

- Streamlit serves on all interfaces by default. For anything other than personal use,
  bind it to localhost and put authentication in front of it.
- History holds financial values from documents the user uploaded, in plain SQLite.
  That is the feature; protect the file as you would the PDFs.
- A 480-page PDF takes about 90 seconds to analyse. There is no worker queue; a second
  upload during that time waits. Page and size caps bound the work.
