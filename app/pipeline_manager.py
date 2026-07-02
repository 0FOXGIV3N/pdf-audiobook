from __future__ import annotations

import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

from pipeline_status import PipelineStatus


@dataclass
class StageResult:
    """Result returned by a pipeline stage."""

    name: str
    status: str
    skipped: bool = False
    elapsed_seconds: float = 0.0
    message: str = ""
    data: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        if payload["data"] is None:
            payload["data"] = {}
        return payload


class PipelineStage(Protocol):
    """Minimal protocol for future pipeline stages."""

    name: str

    def should_run(self) -> bool:
        ...

    def run(self) -> StageResult:
        ...


class PipelineManager:
    """Small orchestration helper for the PDF Audiobook Generator.

    The manager intentionally stays lightweight. Individual stages still own
    their real work. This class only provides consistent ordering, status
    updates, logs, elapsed timing, and error handling.
    """

    def __init__(
        self,
        output_root: str | Path,
        phase: str = "Phase 5 — Pipeline Orchestrator",
        quiet: bool = False,
    ):
        self.output_root = Path(output_root)
        self.phase = phase
        self.quiet = quiet
        self.status = PipelineStatus(self.output_root)
        self.results: List[StageResult] = []

    def run(self, stages: List[PipelineStage], message: str = "Pipeline started") -> List[StageResult]:
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.status.initialize(
            phase=self.phase,
            stage="Pipeline Orchestration",
            message=message,
            extra={"stages_total": len(stages)},
        )

        pipeline_start = time.time()

        try:
            for index, stage in enumerate(stages, start=1):
                self._print(f"\n[{index}/{len(stages)}] {stage.name}")
                self.status.start_stage(
                    stage.name,
                    total=1,
                    message=f"Starting {stage.name}",
                    extra={
                        "stage_index": index,
                        "stages_total": len(stages),
                    },
                )

                stage_start = time.time()

                if not stage.should_run():
                    result = StageResult(
                        name=stage.name,
                        status="skipped",
                        skipped=True,
                        elapsed_seconds=0.0,
                        message=f"Skipped {stage.name}",
                    )
                    self.results.append(result)
                    self.status.finish_stage(message=result.message, extra=result.to_dict())
                    self._print(f"SKIP {stage.name}")
                    continue

                result = stage.run()
                result.elapsed_seconds = round(time.time() - stage_start, 2)
                self.results.append(result)

                if result.status != "complete":
                    raise RuntimeError(result.message or f"Stage failed: {stage.name}")

                self.status.finish_stage(
                    message=result.message or f"Finished {stage.name}",
                    extra={
                        "stage_result": result.to_dict(),
                        "stage_index": index,
                        "stages_total": len(stages),
                    },
                )
                self._print(f"DONE {stage.name} | {self._format_duration(result.elapsed_seconds)}")

            total_elapsed = round(time.time() - pipeline_start, 2)
            self.status.complete(
                message="Pipeline complete",
                extra={
                    "elapsed_seconds": total_elapsed,
                    "elapsed_display": self._format_duration(total_elapsed),
                    "stage_results": [r.to_dict() for r in self.results],
                },
            )
            return self.results

        except Exception as exc:
            self.status.fail(str(exc), extra={"stage_results": [r.to_dict() for r in self.results]})
            raise

    def _print(self, message: str) -> None:
        if not self.quiet:
            print(message, flush=True)

    @staticmethod
    def _format_duration(seconds: float | int | None) -> str:
        if seconds is None:
            return "--:--"
        total = max(0, int(round(float(seconds))))
        hours = total // 3600
        minutes = (total % 3600) // 60
        secs = total % 60
        if hours:
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
        return f"{minutes:02d}:{secs:02d}"
