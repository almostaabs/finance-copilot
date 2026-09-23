"""Gemini transport. Phase 15.

The hosted container has no model server, so the cloud client is what makes the
AI features reachable there. These tests never touch the network: the live
contract is marked `gemini` and deselected like the Ollama one.
"""

from __future__ import annotations

import io
import json
import re
import urllib.error
import urllib.request

import pytest

from fincopilot.ai.client import GeminiClient, LLMError, gemini_schema
from fincopilot.ai.llm_map import RESPONSE_SCHEMA


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _ok(text: str) -> _Resp:
    body = {"candidates": [{"content": {"parts": [{"text": text}]}}]}
    return _Resp(json.dumps(body).encode())


def test_schema_drops_what_gemini_rejects_and_marks_nullable():
    out = gemini_schema(RESPONSE_SCHEMA)
    assert "additionalProperties" not in out
    assert out["type"] == "OBJECT"
    row = out["properties"]["source_row_id"]
    assert row == {"type": "STRING", "nullable": True}
    assert out["properties"]["confidence"]["enum"] == ["high", "medium", "low"]
    assert out["required"] == ["source_row_id"]


def test_schema_recurses_into_arrays():
    out = gemini_schema(
        {"type": "object", "properties": {"xs": {"type": "array", "items": {"type": "string"}}}}
    )
    assert out["properties"]["xs"]["items"] == {"type": "STRING"}


def test_empty_key_is_refused_before_any_request():
    with pytest.raises(ValueError):
        GeminiClient(api_key="")


def test_sends_temperature_zero_json_schema_and_the_key_as_a_header(monkeypatch):
    captured = {}

    def fake(req, timeout):
        captured["body"] = json.loads(req.data)
        captured["headers"] = req.headers
        captured["url"] = req.full_url
        captured["timeout"] = timeout
        return _ok('{"source_row_id": null}')

    monkeypatch.setattr(urllib.request, "urlopen", fake)
    out = GeminiClient(api_key="k", model="m", timeout_s=3).complete_json("p", RESPONSE_SCHEMA)

    assert out == '{"source_row_id": null}'
    cfg = captured["body"]["generationConfig"]
    assert cfg["temperature"] == 0
    assert cfg["responseMimeType"] == "application/json"
    assert cfg["responseSchema"] == gemini_schema(RESPONSE_SCHEMA)
    assert captured["headers"]["X-goog-api-key"] == "k"
    assert "k" not in captured["url"]  # the key is never put in a URL
    assert captured["url"].endswith("/models/m:generateContent")
    assert captured["timeout"] == 3


def test_transport_failure_becomes_llmerror(monkeypatch):
    def boom(*a, **k):
        raise TimeoutError()

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    with pytest.raises(LLMError):
        GeminiClient(api_key="k", timeout_s=0.01).complete_json("p", {})


def test_http_error_carries_the_apis_own_message(monkeypatch):
    detail = json.dumps({"error": {"message": "use models/gemini-3.6-flash"}}).encode()

    def boom(*a, **k):
        raise urllib.error.HTTPError("u", 404, "Not Found", {}, io.BytesIO(detail))

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    with pytest.raises(LLMError, match=re.escape("gemini-3.6-flash")):
        GeminiClient(api_key="k").complete_json("p", {})


@pytest.mark.parametrize(
    ("field", "kwargs", "char"),
    [
        ("model name", {"api_key": "k", "model": "gemini\u20113.6\u2011flash"}, "U+2011"),
        ("model name", {"api_key": "k", "model": "gemini-3.6-flash\u00a0"}, "U+00A0"),
        ("API key", {"api_key": "k\u200b"}, "U+200B"),
    ],
)
def test_unsendable_model_or_key_is_named_before_any_request(monkeypatch, field, kwargs, char):
    # A pasted model name or key can carry a non-breaking hyphen, NBSP or zero-width
    # space. http.client cannot put those in a URL or header, and the failure used to
    # surface as an opaque "gemini request failed: UnicodeEncodeError".
    def must_not_send(*a, **k):
        raise AssertionError("request sent with an unsendable model or key")

    monkeypatch.setattr(urllib.request, "urlopen", must_not_send)
    with pytest.raises(LLMError, match=re.escape(field)) as err:
        GeminiClient(**kwargs).complete_json("p", {})
    assert char in str(err.value)
    assert "k\u200b" not in str(err.value)  # never echo the key


def test_response_without_text_is_a_decline_not_a_crash(monkeypatch):
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _Resp(b'{"candidates": []}'))
    with pytest.raises(LLMError):
        GeminiClient(api_key="k").complete_json("p", {})


@pytest.mark.gemini
def test_gemini_contract_live():
    """Deselected by default. Runs only with GEMINI_API_KEY set and -m gemini."""
    raw = GeminiClient.from_env().complete_json(
        "Which row is total revenue? Rows: r1 Cost of sales, r2 Total revenue.", RESPONSE_SCHEMA
    )
    assert set(json.loads(raw)) <= {"source_row_id", "confidence", "reasoning"}
