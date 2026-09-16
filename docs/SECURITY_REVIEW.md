# Security Review (Phases 13 and 14)

Reviewed against spec section 13 plus the surfaces Phases 9-11 added. Date 2026-09-12,
extended 2026-09-17 for the public deployment.

**Original threat model (Phase 13):** a hostile PDF, a hostile or broken local model, a
careless local user. The app was local-first and single-user.

**Revised threat model (Phase 14):** the app is now also reachable by anyone at
<https://finance-copilot-almostaabs.streamlit.app>, with no authentication, where a
single container serves every visitor. That adds two classes of concern the original
review did not cover: one visitor's data reaching another, and an anonymous stranger
being able to spend the container's resources. The section at the end covers both. The
local posture below is unchanged and still applies.

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


## Phase 14: the public deployment

### Found and fixed before going public

**One visitor's analysis was listed on the next visitor's page.** The history feature
writes every analysis to a SQLite file on the machine running the app. Locally that is
the feature; on a shared container it means an anonymous stranger's uploaded report —
its filename, its financial values, its red flags — appears in the sidebar for whoever
loads the page next. Fixed before the first public link existed: `FINCOPILOT_HISTORY=off`
is set in the host's secrets, `_store()` returns `None` under it so nothing is ever
written, and `_history()` prints a plain explanation rather than an empty list. Both
directions are covered by tests, including an assertion that the database file is never
even created. See `tests/test_app.py`.

**The package could not be imported by a pip-based host.** Not a security issue, but it
is why `requirements.txt` exists; noted so nobody deletes it as redundant.

### Accepted on the public deployment

**Anyone can upload anything.** There is no authentication, no rate limit, and no
account. The mitigations are the ones already in the ingestion gate — 50 MB cap,
1000-page cap, magic-byte check, no execution of uploaded content, no `subprocess` and no
`eval` anywhere in `src/` or `app.py` — plus whatever Streamlit Community Cloud applies
in front of it. A determined visitor can still occupy the container by repeatedly
uploading large reports: there is no worker queue, so a second analysis waits behind the
first. Accepted, because the container holds no credentials, no persistent user data, and
nothing whose loss would matter; the worst outcome is that the demo is slow or restarts.

**Uploaded PDFs are held in memory on a machine the user does not control.** They are
never written to disk and never persisted (history is off), but they are processed on
Streamlit's infrastructure rather than the visitor's laptop. That is stated in the README
so nobody uploads a confidential draft report under the impression it stays local. Anyone
who needs the original local-only guarantee runs it locally, which is unchanged and is
still the primary mode.

**The analysis cache is process-wide, not per-visitor.** `_analyze` is wrapped in
`st.cache_data`, keyed on the exact uploaded bytes plus the AI settings. On a shared
container that cache spans visitors: if two people upload byte-identical files, the
second gets the first's cached result. This is not a disclosure — the key *is* the file,
so a visitor can only reach a cached entry for a document they already hold in full — and
it cannot be enumerated or listed from the UI. Recorded because the property changes
meaning between the local and hosted cases, and a future cache key that is not the whole
document would break the argument.

**No model server is reachable from the deployment.** Both AI features therefore stay
unavailable there, which removes the hostile-model surface entirely on the public
instance. If a hosted LLM client is added later, its key belongs in the host's secrets
and the existing response gates — six rejection paths for the row picker, the grounding
gate for the narrative — apply unchanged, because the pipeline receives a client through
a Protocol and does not care who implements it.

### Secrets audit before publishing

The repository was checked before it was made public. It contains `.env.example`
(localhost defaults and upload limits, no values that are secret) and
`.streamlit/config.toml` (theme, `maxUploadSize`, `headless`). `.streamlit/secrets.toml`
is gitignored and has never been committed. No API keys, tokens, or credentials exist in
the history. The five real annual reports used for validation were committed once by
mistake and then removed from the history entirely, before the repository was published,
because they are the publishers' documents; `tests/fixtures/real/README.md` records where
to download each one instead.
