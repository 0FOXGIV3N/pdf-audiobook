from __future__ import annotations

from pathlib import Path
from typing import Optional

from pipeline_status import PipelineStatus


class PipelineLogger:
    """Tiny wrapper around PipelineStatus logging.

    Kept separate so future GUI/terminal formatting can evolve without changing
    individual pipeline stages.
    """

    def __init__(self, output_root: str | Path, enabled: bool = True):
        self.status = PipelineStatus(output_root, enabled=enabled)

    def info(self, message: str, stage: Optional[str] = None, item: Optional[str] = None) -> None:
        self.status.log(message, stage=stage, item=item)

    def error(self, message: str, stage: Optional[str] = None, item: Optional[str] = None) -> None:
        self.status.log(f"ERROR: {message}", stage=stage, item=item)
