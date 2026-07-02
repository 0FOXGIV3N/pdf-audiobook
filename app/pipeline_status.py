from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


class PipelineStatus:
    """Small shared status writer for the PDF Audiobook Generator.

    The status file is intentionally simple JSON so it can be consumed by:
    - terminal scripts today
    - render_book.py next
    - a GUI/dashboard later

    This module is dependency-free and safe to import from any pipeline stage.
    """

    def __init__(self, output_root: str | Path, enabled: bool = True):
        self.output_root = Path(output_root)
        self.enabled = bool(enabled)
        self.reports_dir = self.output_root / "reports"
        self.status_path = self.reports_dir / "pipeline_status.json"
        self.log_path = self.reports_dir / "pipeline.log"
        self.stage_started_at: Optional[float] = None
        self.pipeline_started_at: Optional[float] = None

        if self.enabled:
            self.reports_dir.mkdir(parents=True, exist_ok=True)

    def initialize(
        self,
        phase: str,
        stage: str,
        message: str = "Pipeline started",
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.pipeline_started_at = time.time()
        self.stage_started_at = self.pipeline_started_at
        payload = {
            "pipeline": "PDF Audiobook Generator",
            "phase": phase,
            "status": "running",
            "current_stage": stage,
            "current_item": None,
            "message": message,
            "current": 0,
            "total": None,
            "percent": 0.0,
            "elapsed_seconds": 0.0,
            "eta_seconds": None,
            "last_update": self._now_iso(),
            "output_root": str(self.output_root),
        }
        if extra:
            payload.update(extra)
        self._write(payload)
        self.log(message, stage=stage)

    def start_stage(
        self,
        stage: str,
        total: Optional[int] = None,
        message: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.stage_started_at = time.time()
        payload = self._read_current()
        payload.update({
            "status": "running",
            "current_stage": stage,
            "current_item": None,
            "message": message or f"Starting {stage}",
            "current": 0,
            "total": total,
            "percent": 0.0 if total else None,
            "stage_elapsed_seconds": 0.0,
            "eta_seconds": None,
            "last_update": self._now_iso(),
        })
        if extra:
            payload.update(extra)
        self._write(payload)
        self.log(payload["message"], stage=stage)

    def update(
        self,
        current: Optional[int] = None,
        total: Optional[int] = None,
        item: Optional[str] = None,
        message: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        now = time.time()
        payload = self._read_current()

        if current is not None:
            payload["current"] = int(current)
        if total is not None:
            payload["total"] = int(total)
        if item is not None:
            payload["current_item"] = item
        if message is not None:
            payload["message"] = message

        current_value = payload.get("current")
        total_value = payload.get("total")
        if isinstance(current_value, int) and isinstance(total_value, int) and total_value > 0:
            payload["percent"] = round((current_value / total_value) * 100, 2)
            elapsed = now - (self.stage_started_at or now)
            payload["stage_elapsed_seconds"] = round(elapsed, 2)
            if current_value > 0 and current_value < total_value:
                seconds_per_item = elapsed / current_value
                payload["eta_seconds"] = round(seconds_per_item * (total_value - current_value), 2)
            else:
                payload["eta_seconds"] = 0.0 if current_value >= total_value else None

        if self.pipeline_started_at:
            payload["elapsed_seconds"] = round(now - self.pipeline_started_at, 2)
        elif "elapsed_seconds" not in payload:
            payload["elapsed_seconds"] = None

        payload["last_update"] = self._now_iso()
        if extra:
            payload.update(extra)

        self._write(payload)
        if message:
            self.log(message, stage=payload.get("current_stage"), item=item)

    def finish_stage(self, message: Optional[str] = None, extra: Optional[Dict[str, Any]] = None) -> None:
        payload = self._read_current()
        total = payload.get("total")
        if isinstance(total, int) and total > 0:
            payload["current"] = total
            payload["percent"] = 100.0
            payload["eta_seconds"] = 0.0
        payload["message"] = message or f"Finished {payload.get('current_stage', 'stage')}"
        payload["last_update"] = self._now_iso()
        if self.stage_started_at:
            payload["stage_elapsed_seconds"] = round(time.time() - self.stage_started_at, 2)
        if extra:
            payload.update(extra)
        self._write(payload)
        self.log(payload["message"], stage=payload.get("current_stage"))

    def complete(self, message: str = "Pipeline complete", extra: Optional[Dict[str, Any]] = None) -> None:
        payload = self._read_current()
        payload.update({
            "status": "complete",
            "message": message,
            "percent": 100.0,
            "eta_seconds": 0.0,
            "last_update": self._now_iso(),
        })
        if self.pipeline_started_at:
            payload["elapsed_seconds"] = round(time.time() - self.pipeline_started_at, 2)
        if extra:
            payload.update(extra)
        self._write(payload)
        self.log(message, stage=payload.get("current_stage"))

    def fail(self, error: str, extra: Optional[Dict[str, Any]] = None) -> None:
        payload = self._read_current()
        payload.update({
            "status": "failed",
            "message": error,
            "error": error,
            "last_update": self._now_iso(),
        })
        if extra:
            payload.update(extra)
        self._write(payload)
        self.log(f"ERROR: {error}", stage=payload.get("current_stage"))

    def log(self, message: str, stage: Optional[str] = None, item: Optional[str] = None) -> None:
        if not self.enabled:
            return
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        prefix = self._now_iso()
        parts = [prefix]
        if stage:
            parts.append(f"[{stage}]")
        if item:
            parts.append(f"[{item}]")
        parts.append(str(message))
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(" ".join(parts).rstrip() + "\n")

    def _read_current(self) -> Dict[str, Any]:
        if self.enabled and self.status_path.exists():
            try:
                return json.loads(self.status_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {
            "pipeline": "PDF Audiobook Generator",
            "status": "running",
            "output_root": str(self.output_root),
        }

    def _write(self, payload: Dict[str, Any]) -> None:
        if not self.enabled:
            return
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = self.status_path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp_path.replace(self.status_path)

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def get_status(output_root: str | Path | None, enabled: bool = True) -> PipelineStatus | None:
    if output_root is None or not enabled:
        return None
    return PipelineStatus(output_root, enabled=enabled)
