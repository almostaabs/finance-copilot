"""Phase 9: the narrative model is shown structured evidence and may only repeat it.

Rules under test:
- the prompt carries evidence IDs and display numbers, never raw PDF text
- every insight must cite at least one evidence ID that exists
- every number an insight mentions must be one the model was shown
- a broken, absent, or malicious model leaves the deterministic result intact
"""

from __future__ import annotations

import json
from pathlib import Path

import pipeline
import pytest

from fincopilot.ai.client import LLMError, NullMapper
from fincopilot.ai.narrative import (
    MAX_INSIGHTS,
    build_evidence,
    build_prompt,
    generate_narrative,
    validate_response,
)
from fincopilot.types import Narrative, Unavailable, UnavailableReason

GOLDEN_US = Path("tests/fixtures/golden_us.pdf")


@pytest.fixture(scope="module")
def result():
    return pipeline.analyze(GOLDEN_US.read_bytes())


@pytest.fixture(scope="module")
def evidence(result):
    return build_evidence(result)


class ScriptedClient:
    def __init__(self, response: str, model: str = "scripted") -> None:
        self.response = response
        self.model = model
        self.prompts: list[str] = []

    def complete_json(self, prompt: str, schema: dict) -> str:
        self.prompts.append(prompt)
        return self.response


class BrokenClient:
    model = "broken"

    def complete_json(self, prompt: str, schema: dict) -> str:
        raise LLMError("down")


def _ok_response(evidence) -> str:
    metric_id = next(i for i in evidence["ids"] if i.startswith("net_margin@"))
    shown = evidence["metrics"][metric_id]["display"]
    return json.dumps(
        {
            "summary": "Profitability held.",
            "insights": [{"text": f"Net margin was {shown}.", "cites": [metric_id]}],
        }
    )


# --- evidence -------------------------------------------------------------


def test_evidence_has_ids_for_metrics_flags_and_reconciliations(evidence):
    ids = set(evidence["ids"])
    assert any(i.startswith("net_margin@") for i in ids)
    assert any(i.startswith("assets_equal_liabilities_plus_equity@") for i in ids)
    assert any(i in evidence["red_flags"] for i in ids)


def test_evidence_carries_no_raw_pdf_text(result, evidence):
    blob = json.dumps(evidence)
    # Row labels are allowed (Phase 5 already shows them); page text is not.
    assert "Notes to the" not in blob
    assert len(blob) < 60_000


def test_prompt_contains_ids_and_grounding_rules(evidence):
    prompt = build_prompt(evidence)
    assert "must not calculate" in prompt.lower() or "do not calculate" in prompt.lower()
    for i in list(evidence["ids"])[:5]:
        assert i in prompt


# --- validation gate ------------------------------------------------------


def test_valid_response_passes(evidence):
    out = validate_response(_ok_response(evidence), evidence, model="m")
    assert isinstance(out, Narrative)
    assert out.insights[0].cites


def test_unknown_cite_drops_insight(evidence):
    raw = json.dumps(
        {"summary": "x", "insights": [{"text": "Margins rose.", "cites": ["made_up@2099"]}]}
    )
    out = validate_response(raw, evidence, model="m")
    assert isinstance(out, Unavailable)
    assert out.reason is UnavailableReason.CONFLICT


def test_uncited_insight_dropped(evidence):
    raw = json.dumps({"summary": "x", "insights": [{"text": "Margins rose.", "cites": []}]})
    assert isinstance(validate_response(raw, evidence, model="m"), Unavailable)


def test_invented_number_drops_insight(evidence):
    metric_id = next(i for i in evidence["ids"] if i.startswith("net_margin@"))
    raw = json.dumps(
        {
            "summary": "x",
            "insights": [{"text": "Net margin reached 99.9%.", "cites": [metric_id]}],
        }
    )
    assert isinstance(validate_response(raw, evidence, model="m"), Unavailable)


def test_number_in_summary_is_checked_too(evidence):
    raw = json.dumps({"summary": "Revenue was 123,456.", "insights": []})
    assert isinstance(validate_response(raw, evidence, model="m"), Unavailable)


def test_year_mentions_allowed(evidence):
    metric_id = next(i for i in evidence["ids"] if i.startswith("net_margin@"))
    year = metric_id.split("@")[1]
    raw = json.dumps(
        {
            "summary": f"In {year} margins held.",
            "insights": [{"text": "Held.", "cites": [metric_id]}],
        }
    )
    assert isinstance(validate_response(raw, evidence, model="m"), Narrative)


def test_invalid_json_and_wrong_shape(evidence):
    for raw in ("not json", "[]", '{"summary": 1}', '{"summary": "x", "insights": "no"}'):
        assert isinstance(validate_response(raw, evidence, model="m"), Unavailable)


def test_too_many_insights_rejected(evidence):
    metric_id = next(i for i in evidence["ids"] if i.startswith("net_margin@"))
    raw = json.dumps(
        {
            "summary": "x",
            "insights": [{"text": "Held.", "cites": [metric_id]}] * (MAX_INSIGHTS + 1),
        }
    )
    assert isinstance(validate_response(raw, evidence, model="m"), Unavailable)


def test_oversized_response_rejected(evidence):
    raw = json.dumps({"summary": "x" * 200_000, "insights": []})
    assert isinstance(validate_response(raw, evidence, model="m"), Unavailable)


def test_deeply_nested_response_does_not_raise(evidence):
    raw = "[" * 5000 + "]" * 5000
    assert isinstance(validate_response(raw, evidence, model="m"), Unavailable)


# --- end to end -----------------------------------------------------------


def test_generate_with_scripted_client(result, evidence):
    client = ScriptedClient(_ok_response(evidence))
    out = generate_narrative(result, client)
    assert isinstance(out, Narrative)
    assert out.model == "scripted"
    assert "%PDF" not in client.prompts[0]


def test_generate_with_broken_client_is_unavailable(result):
    out = generate_narrative(result, BrokenClient())
    assert isinstance(out, Unavailable)
    assert out.reason is UnavailableReason.MISSING_INPUT


def test_generate_with_null_mapper_is_unavailable(result):
    assert isinstance(generate_narrative(result, NullMapper()), Unavailable)


def test_generate_never_mutates_result(result, evidence):
    before = (result.values, result.metrics, result.red_flags)
    generate_narrative(result, ScriptedClient(_ok_response(evidence)))
    assert (result.values, result.metrics, result.red_flags) == before


@pytest.mark.parametrize(
    "text",
    ["[click](http://evil)", "![i](http://x)", "<b>bold</b>", "*emph*", "`code`", "a | b", "#h"],
)
def test_markup_in_text_is_rejected(evidence, text):
    metric_id = next(i for i in evidence["ids"] if i.startswith("net_margin@"))
    raw = json.dumps({"summary": "x", "insights": [{"text": text, "cites": [metric_id]}]})
    assert isinstance(validate_response(raw, evidence, model="m"), Unavailable)
    assert isinstance(
        validate_response(json.dumps({"summary": text, "insights": []}), evidence, model="m"),
        Unavailable,
    )


def test_too_many_cites_rejected(evidence):
    metric_id = next(i for i in evidence["ids"] if i.startswith("net_margin@"))
    raw = json.dumps({"summary": "x", "insights": [{"text": "ok", "cites": [metric_id] * 13}]})
    assert isinstance(validate_response(raw, evidence, model="m"), Unavailable)


def test_client_returning_non_string_is_unavailable(result):
    class Weird:
        model = "w"

        def complete_json(self, prompt, schema):
            return None

    assert isinstance(generate_narrative(result, Weird()), Unavailable)


def test_evidence_is_ascii_so_small_models_cannot_mangle_it():
    indian = pipeline.analyze(Path("tests/fixtures/golden_indian.pdf").read_bytes())
    blob = json.dumps(build_evidence(indian), ensure_ascii=False)
    assert "₹" not in blob and "INR " in blob
