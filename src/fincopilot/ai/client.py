"""LLM client behind an injectable Protocol. Spec 2.2, 6.3.

The deterministic pipeline never imports Ollama. It receives an LLMClient
and calls one method. NullMapper is the Phase 8 client: it always declines,
performs no I/O, and proves the pipeline runs with Ollama uninstalled.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Protocol

DEFAULT_HOST = "http://localhost:11434"
DEFAULT_MODEL = "qwen2.5:3b"
DEFAULT_TIMEOUT_S = 10.0
FIXED_SEED = 7


class LLMError(Exception):
    """Any transport, timeout, or protocol failure. Callers treat it as decline."""


class LLMClient(Protocol):
    def complete_json(self, prompt: str, schema: dict[str, Any]) -> str:
        """Return the raw model text for a schema-constrained completion."""
        ...


class NullMapper:
    """Always declines. No I/O. The client the golden deterministic test uses."""

    def complete_json(self, prompt: str, schema: dict[str, Any]) -> str:
        return json.dumps({"source_row_id": None})


class OllamaClient:
    """Plain HTTP to a local Ollama. temperature 0, fixed seed, JSON schema format."""

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        model: str = DEFAULT_MODEL,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        if not host.startswith(("http://", "https://")):
            raise ValueError("Ollama host must start with http:// or https://")
        self.host = host.rstrip("/")
        self.model = model
        self.timeout_s = timeout_s

    @classmethod
    def from_env(cls) -> OllamaClient:
        return cls(
            host=os.environ.get("FINCOPILOT_OLLAMA_HOST", DEFAULT_HOST),
            model=os.environ.get("FINCOPILOT_OLLAMA_MODEL", DEFAULT_MODEL),
            timeout_s=float(os.environ.get("FINCOPILOT_LLM_TIMEOUT_S", DEFAULT_TIMEOUT_S)),
        )

    def complete_json(self, prompt: str, schema: dict[str, Any]) -> str:
        body = json.dumps(
            {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "format": schema,
                "options": {"temperature": 0, "seed": FIXED_SEED},
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{self.host}/api/generate",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            raise LLMError(f"ollama request failed: {type(exc).__name__}") from exc
        text = payload.get("response") if isinstance(payload, dict) else None
        if not isinstance(text, str):
            raise LLMError("ollama response carried no text")
        return text


GEMINI_DEFAULT_MODEL = "gemini-3.6-flash"
GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models"

_GEMINI_KEYS = ("type", "properties", "required", "items", "enum", "nullable")


def gemini_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Rewrite a JSON Schema into the OpenAPI subset Gemini accepts.

    Gemini rejects `additionalProperties` and union types. `["string", "null"]`
    becomes a plain string marked nullable; anything else it does not know is
    dropped rather than sent and refused.
    """
    out: dict[str, Any] = {}
    for key, value in schema.items():
        if key not in _GEMINI_KEYS:
            continue
        if key == "type" and isinstance(value, list):
            rest = [t for t in value if t != "null"]
            out["type"] = (rest[0] if rest else "string").upper()
            if len(rest) != len(value):
                out["nullable"] = True
        elif key == "type":
            out["type"] = value.upper()
        elif key == "properties":
            out["properties"] = {k: gemini_schema(v) for k, v in value.items()}
        elif key == "items":
            out["items"] = gemini_schema(value)
        else:
            out[key] = value
    return out


def _http_detail(exc: urllib.error.HTTPError) -> str:
    """The API's own message, which names the replacement when a model retires."""
    try:
        return str(json.loads(exc.read().decode("utf-8"))["error"]["message"])[:200]
    except Exception:
        return ""


class GeminiClient:
    """Google Generative Language API over plain HTTP. temperature 0, JSON out.

    The same contract as OllamaClient: return the model's raw text, raise
    LLMError on anything else, so callers treat a failure as a decline. The key
    is read from the environment and never written to disk by this module.
    """

    def __init__(
        self,
        api_key: str,
        model: str = GEMINI_DEFAULT_MODEL,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        if not api_key:
            raise ValueError("Gemini API key is empty")
        self.api_key = api_key
        self.model = model
        self.timeout_s = timeout_s

    @classmethod
    def from_env(cls) -> GeminiClient:
        return cls(
            api_key=os.environ.get("GEMINI_API_KEY", ""),
            model=os.environ.get("FINCOPILOT_GEMINI_MODEL", GEMINI_DEFAULT_MODEL),
            timeout_s=float(os.environ.get("FINCOPILOT_LLM_TIMEOUT_S", DEFAULT_TIMEOUT_S)),
        )

    def complete_json(self, prompt: str, schema: dict[str, Any]) -> str:
        body = json.dumps(
            {
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0,
                    "responseMimeType": "application/json",
                    "responseSchema": gemini_schema(schema),
                },
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{GEMINI_ENDPOINT}/{self.model}:generateContent",
            data=body,
            headers={"Content-Type": "application/json", "x-goog-api-key": self.api_key},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise LLMError(f"gemini request failed: HTTP {exc.code} {_http_detail(exc)}") from exc
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            raise LLMError(f"gemini request failed: {type(exc).__name__}") from exc
        try:
            text = payload["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("gemini response carried no text") from exc
        if not isinstance(text, str):
            raise LLMError("gemini response carried no text")
        return text
