from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict


class Publisher(ABC):
    """Base interface for final audiobook deliverable publishers.

    Publishers convert an existing production asset, such as the full-book WAV,
    into a user-facing deliverable such as MP3 or M4B. They should not modify
    parser, narration, chunk, or source audio files.
    """

    name: str

    @abstractmethod
    def publish(self, source_file: str | Path, output_file: str | Path, **kwargs: Any) -> Dict[str, Any]:
        """Publish source_file to output_file and return a report dictionary."""
        raise NotImplementedError
