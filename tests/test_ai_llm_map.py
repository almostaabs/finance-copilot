"""Phase 5: injected client, six rejection paths, failure isolation. Spec 6.3."""

import json
from pathlib import Path

import pytest

from fincopilot.ai.client import LLMError, NullMapper, OllamaClient
from fincopilot.ai.llm_map import (
    RESPONSE_SCHEMA,
    build_prompt,
    candidate_rows,
    fill_unmapped,
    validate_response,
)
from fincopilot.extract.locate import locate_statements
from fincopilot.extract.pdf import extract_pdf, validate_input
from fincopilot.extract.periods import detect_periods
from fincopilot.extract.units import normalize_document
from fincopilot.mapping.synonyms import map_rows
from fincopilot.mapping.validate import validate_mappings
from fincopilot.types import (
    AnalyticalConfidence,
    CanonicalConcept,
    ExtractionConfidence,
    Period,
    UnavailableReason,
    is_unavailable,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def indian():
    data = (FIXTURES / "golden_indian.pdf").read_bytes()
    doc = extract_pdf(data, validate_input(data))
    statements = locate_statements(doc)
    periods = detect_periods(statements)
    normalized = normalize_document(statements, periods, doc)
    return doc, periods, normalized, map_rows(normalized)


class ScriptedClient:
    """Returns canned raw text per concept named in the prompt. Records prompts."""

    def __init__(self, answers: dict[str, str]):
        self.answers = answers
        self.prompts: list[str] = []

    def complete_json(self, prompt: str, schema: dict) -> str:
        self.prompts.append(prompt)
        concept = prompt.split("Concept: ")[1].splitlines()[0]
        return self.answers.get(concept, json.dumps({"source_row_id": None}))


class BrokenClient:
    def complete_json(self, prompt: str, schema: dict) -> str:
        raise LLMError("connection refused")


def _other_income_ref(normalized) -> str:
    row = next(r for r in normalized.income.table.rows if r.label == "Other income")
    return row.ref.ref_id


def test_null_mapper_declines_and_pipeline_is_unchanged(indian):
    doc, _periods, normalized, mappings = indian
    out = fill_unmapped(mappings, normalized, doc.refs, NullMapper())
    assert out == mappings


def test_prompt_never_contains_a_financial_number(indian):
    doc, _periods, normalized, mappings = indian
    client = ScriptedClient({})
    fill_unmapped(mappings, normalized, doc.refs, client)
    assert client.prompts  # gross_profit and others were asked
    tokens = {c for t in normalized.income.table.rows for c in t.cells[1:]}
    tokens |= {c for t in normalized.balance.table.rows for c in t.cells[1:]}
    for prompt in client.prompts:
        for token in tokens:
            assert token not in prompt, token


def test_candidates_exclude_already_claimed_rows_and_cap_at_forty(indian):
    _doc, _periods, normalized, mappings = indian
    claimed = {m.ref_id for m in mappings}
    cands = candidate_rows(normalized.income, claimed)
    ids = {c[0] for c in cands}
    assert not ids & claimed
    assert len(cands) <= 40
    assert "Total income" in {c[1] for c in cands}


def test_valid_pick_becomes_llm_mapped_and_python_takes_the_number(indian):
    doc, periods, normalized, mappings = indian
    target = _other_income_ref(normalized)
    client = ScriptedClient({"gross_profit": json.dumps({"source_row_id": target})})
    out = fill_unmapped(mappings, normalized, doc.refs, client)
    added = [m for m in out if m.concept is CanonicalConcept.GROSS_PROFIT]
    assert len(added) == 1
    assert added[0].extraction_confidence is ExtractionConfidence.LLM_MAPPED
    report = validate_mappings(out, normalized, periods)
    fv = report.get(CanonicalConcept.GROSS_PROFIT, Period(2024, "2024"))
    assert fv.value == 3205000000  # 320.50 crore from the row Python looked up
    assert fv.analytical_confidence is AnalyticalConfidence.MEDIUM  # capped


def test_broken_ollama_leaves_concept_unmapped_and_pipeline_intact(indian):
    doc, _periods, normalized, mappings = indian
    out = fill_unmapped(mappings, normalized, doc.refs, BrokenClient())
    assert out == mappings


# --- the six rejection paths, each explicit


def _gate(raw, indian):
    doc, _periods, normalized, mappings = indian
    cands = {c[0] for c in candidate_rows(normalized.income, {m.ref_id for m in mappings})}
    already = {m.ref_id: m.concept for m in mappings}
    return validate_response(
        raw,
        concept=CanonicalConcept.GROSS_PROFIT,
        candidate_ids=cands,
        refs=doc.refs,
        already_mapped=already,
    )


def test_path_1_invalid_json_is_rejected(indian):
    r = _gate("{not json", indian)
    assert is_unavailable(r) and r.reason is UnavailableReason.UNPARSEABLE


def test_path_2_schema_violation_is_rejected(indian):
    assert is_unavailable(_gate(json.dumps({"row": "page_41_table_0_row_1"}), indian))
    assert is_unavailable(_gate(json.dumps({"source_row_id": ["x"]}), indian))
    assert is_unavailable(_gate(json.dumps({"source_row_id": None, "confidence": "sure"}), indian))
    assert is_unavailable(_gate(json.dumps({"source_row_id": None, "extra": "field"}), indian))


def test_path_3_unknown_ref_is_rejected(indian):
    r = _gate(json.dumps({"source_row_id": "page_99_table_0_row_0"}), indian)
    assert is_unavailable(r) and r.reason is UnavailableReason.CONFLICT


def test_path_4_ref_from_wrong_statement_is_rejected(indian):
    _doc, _periods, normalized, _mappings = indian
    bs_ref = normalized.balance.table.rows[0].ref.ref_id
    r = _gate(json.dumps({"source_row_id": bs_ref}), indian)
    assert is_unavailable(r) and "scope" in r.detail


def test_path_5_already_mapped_row_is_a_conflict(indian):
    _doc, _periods, _normalized, mappings = indian
    revenue_ref = next(m.ref_id for m in mappings if m.concept is CanonicalConcept.REVENUE)
    r = _gate(json.dumps({"source_row_id": revenue_ref}), indian)
    assert is_unavailable(r) and r.reason is UnavailableReason.CONFLICT


def test_path_6_numeric_field_is_rejected_as_contract_violation(indian, caplog):
    raw = json.dumps({"source_row_id": None, "confidence": "high", "value": 12450.0})
    r = _gate(raw, indian)
    assert is_unavailable(r)
    assert "contract violation" in caplog.text


def test_explicit_decline_is_none_not_an_error(indian):
    assert _gate(json.dumps({"source_row_id": None}), indian) is None


def test_prompt_and_schema_offer_the_null_decline():
    assert RESPONSE_SCHEMA["properties"]["source_row_id"]["type"] == ["string", "null"]
    assert "null" in build_prompt(CanonicalConcept.REVENUE, [("page_1_table_0_row_0", "Sales")])


# --- Ollama transport


def test_ollama_client_maps_transport_failure_to_llmerror(monkeypatch):
    import urllib.request

    def boom(*a, **k):
        raise TimeoutError()

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    with pytest.raises(LLMError):
        OllamaClient(host="http://127.0.0.1:1", timeout_s=0.01).complete_json("p", {})


def test_ollama_client_sends_schema_temperature_zero_and_seed(monkeypatch):
    import io
    import urllib.request

    captured = {}

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake(req, timeout):
        captured["body"] = json.loads(req.data)
        captured["timeout"] = timeout
        return Resp(json.dumps({"response": '{"source_row_id": null}'}).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    out = OllamaClient(timeout_s=3).complete_json("prompt", RESPONSE_SCHEMA)
    assert out == '{"source_row_id": null}'
    assert captured["body"]["format"] == RESPONSE_SCHEMA
    assert captured["body"]["options"]["temperature"] == 0
    assert "seed" in captured["body"]["options"]
    assert captured["timeout"] == 3


@pytest.mark.ollama
def test_ollama_contract_live():
    """Deselected by default. Runs only with a live Ollama and -m ollama."""
    client = OllamaClient.from_env()
    raw = client.complete_json(
        build_prompt(CanonicalConcept.REVENUE, [("page_1_table_0_row_0", "Net sales")]),
        RESPONSE_SCHEMA,
    )
    data = json.loads(raw)
    assert set(data) <= {"source_row_id", "confidence", "reasoning"}
