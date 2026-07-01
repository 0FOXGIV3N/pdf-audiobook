"""
Offline audiobook companion summary package.

Phase 6.5 — AI Companion
"""

from .base import SummaryProvider, SummaryProviderStatus
from .builder import SummaryBuilder
from .ollama import OllamaSummaryProvider, get_summary_provider

__all__ = [
    "SummaryProvider",
    "SummaryProviderStatus",
    "SummaryBuilder",
    "OllamaSummaryProvider",
    "get_summary_provider",
]
