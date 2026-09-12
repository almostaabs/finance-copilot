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
