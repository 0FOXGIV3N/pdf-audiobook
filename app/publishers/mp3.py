from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any, Dict

from .base import Publisher


class MP3Publisher(Publisher):
    """FFmpeg-backed MP3 publisher.

    This stage converts the full-book WAV master into a distribution-friendly
    MP3 deliverable. It intentionally shells out to ffmpeg so the project avoids
    extra Python audio-encoding dependencies.
    """

    name = "MP3 Export"

    def __init__(self, bitrate: str = "192k", codec: str = "libmp3lame"):
        self.bitrate = bitrate
        self.codec = codec

    def publish(
        self,
        source_file: str | Path,
        output_file: str | Path,
        force: bool = False,
        quiet: bool = False,
        write_report: bool = True,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        source_file = Path(source_file)
        output_file = Path(output_file)

        if not source_file.exists():
            raise FileNotFoundError(f"Source WAV not found for MP3 export: {source_file}")

        output_file.parent.mkdir(parents=True, exist_ok=True)

        if output_file.exists() and not force:
            source_mtime = source_file.stat().st_mtime
            output_mtime = output_file.stat().st_mtime
            if output_mtime >= source_mtime:
                report = self._build_report(
                    source_file=source_file,
                    output_file=output_file,
                    status="skipped_existing",
                    elapsed_seconds=0.0,
                    command=[],
                )
                if write_report:
                    self._write_report(output_file, report)
                if not quiet:
                    print(f"MP3 already exists and is current, skipping: {output_file}", flush=True)
                return report
            if not quiet:
                print(f"MP3 exists but source WAV is newer; regenerating: {output_file}", flush=True)

        command = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error" if quiet else "info",
            "-i",
            str(source_file),
            "-vn",
            "-codec:a",
            self.codec,
            "-b:a",
            self.bitrate,
            str(output_file),
        ]

        start = time.time()
        if not quiet:
            print("\n============================================================", flush=True)
            print("MP3 Export", flush=True)
            print("============================================================", flush=True)
            print(f"Source WAV:        {source_file}", flush=True)
            print(f"Output MP3:        {output_file}", flush=True)
            print(f"Codec:             {self.codec}", flush=True)
            print(f"Bitrate:           {self.bitrate}", flush=True)
            print("============================================================\n", flush=True)

        result = subprocess.run(command, capture_output=True, text=True)
        elapsed = round(time.time() - start, 2)

        if result.returncode != 0:
            raise RuntimeError(
                "FFmpeg MP3 export failed.\n"
                f"Command: {' '.join(command)}\n"
                f"STDOUT: {result.stdout}\n"
                f"STDERR: {result.stderr}"
            )

        report = self._build_report(
            source_file=source_file,
            output_file=output_file,
            status="complete",
            elapsed_seconds=elapsed,
            command=command,
        )
        report["ffmpeg_stdout"] = result.stdout.strip()
        report["ffmpeg_stderr"] = result.stderr.strip()

        if write_report:
            self._write_report(output_file, report)

        if not quiet:
            print("\n============================================================", flush=True)
            print("MP3 Export Complete", flush=True)
            print("============================================================", flush=True)
            print(f"Output:            {output_file}", flush=True)
            print(f"Source size:       {_format_bytes(report['source_size_bytes'])}", flush=True)
            print(f"MP3 size:          {_format_bytes(report['output_size_bytes'])}", flush=True)
            print(f"Compression:       {report['compression_ratio']}", flush=True)
            print(f"Elapsed:           {_format_duration(elapsed)}", flush=True)
            print(f"Report:            {report['report_file']}", flush=True)
            print("============================================================\n", flush=True)

        return report

    def _build_report(
        self,
        source_file: Path,
        output_file: Path,
        status: str,
        elapsed_seconds: float,
        command: list[str],
    ) -> Dict[str, Any]:
        source_size = source_file.stat().st_size if source_file.exists() else 0
        output_size = output_file.stat().st_size if output_file.exists() else 0
        ratio = None
        if source_size and output_size:
            ratio = round(source_size / output_size, 2)

        report = {
            "publisher": self.name,
            "status": status,
            "source_file": str(source_file),
            "output_file": str(output_file),
            "codec": self.codec,
            "bitrate": self.bitrate,
            "source_size_bytes": source_size,
            "output_size_bytes": output_size,
            "compression_ratio": ratio,
            "elapsed_seconds": round(elapsed_seconds, 2),
            "elapsed_display": _format_duration(elapsed_seconds),
            "command": command,
        }
        report["report_file"] = str(output_file.with_suffix(".json"))
        return report

    @staticmethod
    def _write_report(output_file: Path, report: Dict[str, Any]) -> None:
        report_path = output_file.with_suffix(".json")
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")


def publish_mp3(
    source_file: str | Path,
    output_file: str | Path,
    bitrate: str = "192k",
    force: bool = False,
    quiet: bool = False,
) -> Dict[str, Any]:
    return MP3Publisher(bitrate=bitrate).publish(
        source_file=source_file,
        output_file=output_file,
        force=force,
        quiet=quiet,
    )


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


def _format_bytes(size: int | float | None) -> str:
    if not size:
        return "0 B"
    value = float(size)
    units = ["B", "KB", "MB", "GB", "TB"]
    index = 0
    while value >= 1024 and index < len(units) - 1:
        value /= 1024
        index += 1
    return f"{value:.2f} {units[index]}"
