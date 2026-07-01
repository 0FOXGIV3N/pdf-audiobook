"""
Ollama summary provider.

Ollama is expected to be installed and running on the host machine.
Docker connects to the host through:

    http://host.docker.internal:11434

Phase 6.5 / v1.3 / Batch 17

Batch 17 adds deterministic generation options so repeated summary runs are
much more stable.

Defaults:
- seed: 12345
- temperature: 0.0
- top_p: 0.8
- repeat_penalty: 1.1

Environment overrides:
- OLLAMA_SEED
- OLLAMA_TEMPERATURE
- OLLAMA_TOP_P
- OLLAMA_REPEAT_PENALTY

This provider detects and uses Ollama only.
It does not install, manage, or start Ollama.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional

from .base import SummaryProviderStatus


DEFAULT_OLLAMA_BASE_URL = "http://host.docker.internal:11434"
DEFAULT_OLLAMA_MODEL = "qwen3:8b"

DEFAULT_OLLAMA_SEED = 98765
DEFAULT_OLLAMA_TEMPERATURE = 0.0
DEFAULT_OLLAMA_TOP_P = 0.8
DEFAULT_OLLAMA_REPEAT_PENALTY = 1.1


@dataclass
class OllamaSummaryProvider:
    model: str = DEFAULT_OLLAMA_MODEL
    base_url: str = DEFAULT_OLLAMA_BASE_URL
    timeout: int = 600
    seed: int = DEFAULT_OLLAMA_SEED
    temperature: float = DEFAULT_OLLAMA_TEMPERATURE
    top_p: float = DEFAULT_OLLAMA_TOP_P
    repeat_penalty: float = DEFAULT_OLLAMA_REPEAT_PENALTY

    provider_name: str = "Ollama"

    def generation_options(self) -> dict:
        return {
            "seed": self.seed,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "repeat_penalty": self.repeat_penalty,
        }

    def status(self) -> SummaryProviderStatus:
        installed = False
        running = False
        version: Optional[str] = None
        model_available = False
        reason = ""

        try:
            version_payload = self._get_json("/api/version", timeout=10)
            installed = True
            running = True
            raw_version = version_payload.get("version")
            version = str(raw_version) if raw_version else "Installed"
        except Exception as exc:
            reason = f"Ollama is not reachable at {self.base_url}: {exc}"
            return SummaryProviderStatus(
                provider=self.provider_name,
                installed=installed,
                running=running,
                version=version,
                model=self.model,
                model_available=model_available,
                available=False,
                reason=reason,
            )

        try:
            tags_payload = self._get_json("/api/tags", timeout=10)
            models = tags_payload.get("models", [])
            model_names = {
                item.get("name")
                for item in models
                if isinstance(item, dict) and item.get("name")
            }
            model_available = self.model in model_names
            if not model_available:
                reason = f"Ollama model is not available: {self.model}"
        except Exception as exc:
            reason = f"Could not read Ollama model list: {exc}"

        return SummaryProviderStatus(
            provider=self.provider_name,
            installed=installed,
            running=running,
            version=version,
            model=self.model,
            model_available=model_available,
            available=running and model_available,
            reason=reason,
        )

    def is_available(self) -> bool:
        return self.status().available

    def generate(self, prompt: str, *, system: Optional[str] = None) -> str:
        status = self.status()
        if not status.available:
            raise RuntimeError(status.reason or "Ollama summary provider is not available.")

        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": self.generation_options(),
        }

        if system:
            payload["system"] = system

        try:
            result = self._post_json("/api/generate", payload, timeout=self.timeout)
        except urllib.error.HTTPError as exc:
            message = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Ollama request failed: HTTP {exc.code}: {message}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Ollama request failed: {exc}") from exc

        text = result.get("response", "")
        if not isinstance(text, str):
            raise RuntimeError("Ollama response did not contain a valid text response.")

        return text.strip()

    def _get_json(self, path: str, *, timeout: int) -> dict:
        request = urllib.request.Request(
            f"{self.base_url.rstrip('/')}{path}",
            method="GET",
        )

        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")

        return json.loads(body)

    def _post_json(self, path: str, payload: dict, *, timeout: int) -> dict:
        data = json.dumps(payload).encode("utf-8")

        request = urllib.request.Request(
            f"{self.base_url.rstrip('/')}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")

        return json.loads(body)


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return float(value)
    except ValueError:
        return default


def get_summary_provider(
    model: Optional[str] = None,
    base_url: Optional[str] = None,
) -> OllamaSummaryProvider:
    return OllamaSummaryProvider(
        model=model or os.getenv("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL),
        base_url=base_url or os.getenv("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL),
        seed=_env_int("OLLAMA_SEED", DEFAULT_OLLAMA_SEED),
        temperature=_env_float("OLLAMA_TEMPERATURE", DEFAULT_OLLAMA_TEMPERATURE),
        top_p=_env_float("OLLAMA_TOP_P", DEFAULT_OLLAMA_TOP_P),
        repeat_penalty=_env_float("OLLAMA_REPEAT_PENALTY", DEFAULT_OLLAMA_REPEAT_PENALTY),
    )
