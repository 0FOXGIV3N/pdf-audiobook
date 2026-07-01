"""
Summary provider base abstractions.

Phase 6.5 — AI Companion v1.0

This module mirrors the existing TTS provider style: providers expose
availability checks, runtime status, and a generation interface without tying
the rest of the pipeline to a specific backend.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol


@dataclass(frozen=True)
class SummaryProviderStatus:
    """Runtime status for an offline summary provider."""

    provider: str
    installed: bool
    running: bool
    version: Optional[str]
    model: str
    model_available: bool
    available: bool
    reason: str = ""


class SummaryProvider(Protocol):
    """Drop-in interface for offline summary providers."""

    provider_name: str
    model: str

    def status(self) -> SummaryProviderStatus:
        """Return provider availability and runtime details."""
        ...

    def is_available(self) -> bool:
        """Return True when the provider can generate summaries."""
        ...

    def generate(self, prompt: str, *, system: Optional[str] = None) -> str:
        """Generate text from a prompt."""
        ...
