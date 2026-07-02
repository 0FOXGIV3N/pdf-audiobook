from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict


class TTSProvider(ABC):
    """
    Base class for TTS providers.

    This keeps the Kokoro provider import-compatible while giving us
    a simple shared interface for future providers.
    """

    @abstractmethod
    def generate(self, text: str, output_file: str | Path) -> Dict[str, Any]:
        """
        Generate audio from text and write it to output_file.
        Implementations should return metadata about the generated audio.
        """
        raise NotImplementedError


# Backwards-compatible alias in case older code referenced BaseTTS.
BaseTTS = TTSProvider
