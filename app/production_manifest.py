from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from runtime_info import get_runtime_info

MANIFEST_VERSION = "1.0"
PIPELINE_VERSION = "phase5_metadata_tags_v1.0"


def update_production_manifest(
    book_root: str | Path,
    stage_results: Optional[List[Dict[str, Any]]] = None,
    quiet: bool = False,
) -> Dict[str, Any]:
    """Create or update the production manifest for a rendered audiobook.

    The production manifest is the stable, user-facing source of truth for the
    book output folder. It records produced assets, runtime details, tool
    versions, and pipeline run results without modifying parser/chapter outputs.
    """
    book_root = Path(book_root)
    if not book_root.exists():
        raise FileNotFoundError(f"Book output folder not found: {book_root}")

    reports_dir = book_root / "reports"
    books_dir = book_root / "books"
    reports_dir.mkdir(parents=True, exist_ok=True)
    books_dir.mkdir(parents=True, exist_ok=True)

    now = _now_iso()
    runtime = get_runtime_info(output_dir=book_root)

    book_info = _collect_book_info(book_root)
    outputs = _collect_outputs(book_root)
    metrics = _collect_metrics(book_root, stage_results=stage_results)

    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "pipeline_version": PIPELINE_VERSION,
        "generated_at": now,
        "book_root": str(book_root),
        "book": book_info,
        "runtime": {
            "app_version": runtime.get("app_version"),
            "python": runtime.get("python"),
            "platform": runtime.get("platform"),
            "pymupdf": runtime.get("pymupdf"),
            "pillow": runtime.get("pillow"),
            "tesseract": runtime.get("tesseract"),
            "ffmpeg": runtime.get("ffmpeg"),
            "kokoro": runtime.get("kokoro"),
            "gpu": runtime.get("gpu"),
        },
        "tts": _collect_tts_info(book_root, stage_results=stage_results),
        "outputs": outputs,
        "metrics": metrics,
        "publishing": _collect_publishing_info(book_root, stage_results=stage_results),
        "stage_results": stage_results or [],
        "known_future_outputs": {
            "book_m4b": None,
            "cover_image": None,
            "metadata": _path_if_exists(book_root / "reports" / "mp3_metadata.json"),
        },
    }

    manifest_path = books_dir / "manifest.json"
    report_path = reports_dir / "production_manifest.json"

    _write_json(manifest_path, manifest)
    _write_json(report_path, manifest)

    if not quiet:
        print("\n============================================================", flush=True)
        print("Production Manifest", flush=True)
        print("============================================================", flush=True)
        print(f"Manifest:          {manifest_path}", flush=True)
        print(f"Report copy:       {report_path}", flush=True)
        print("============================================================\n", flush=True)

    manifest["manifest_file"] = str(manifest_path)
    manifest["report_file"] = str(report_path)
    return manifest


def _collect_book_info(book_root: Path) -> Dict[str, Any]:
    book_identity = _read_json_if_exists(book_root / "book_identity.json")
    book_json = _read_json_if_exists(book_root / "book.json")
    old_manifest = _read_json_if_exists(book_root / "manifest.json")
    chunks_manifest = _read_json_if_exists(book_root / "chunks" / "manifest.json")

    title = (
        book_identity.get("title")
        or book_json.get("title")
        or old_manifest.get("title")
        or chunks_manifest.get("book")
        or book_root.name
    )
    subtitle = (
        book_identity.get("subtitle")
        or book_json.get("subtitle")
        or old_manifest.get("subtitle")
        or ""
    )
    author = (
        book_identity.get("author")
        or book_json.get("author")
        or old_manifest.get("author")
        or ""
    )

    chapter_dirs = sorted(
        [p for p in (book_root / "chunks").glob("chapter_*") if p.is_dir()],
        key=lambda p: p.name,
    )
    chapter_audio = sorted((book_root / "chapters_audio").glob("chapter_*.wav"))

    return {
        "title": title,
        "author": author,
        "subtitle": subtitle,
        "slug": book_root.name,
        "identity_confidence": book_identity.get("confidence", {}),
        "identity_sources": book_identity.get("sources", {}),
        "source_pdf": book_json.get("source_pdf") or old_manifest.get("source_pdf"),
        "total_pages": book_json.get("total_pages") or old_manifest.get("total_pages"),
        "total_words": book_json.get("total_words") or old_manifest.get("total_words"),
        "chapters_detected": len(chapter_dirs),
        "chapters_audio_rendered": len(chapter_audio),
    }


def _collect_outputs(book_root: Path) -> Dict[str, Any]:
    books_dir = book_root / "books"
    full_wavs = sorted(books_dir.glob("*_full.wav"))
    any_wavs = sorted(books_dir.glob("*.wav"))
    mp3s = sorted(books_dir.glob("*.mp3"))
    m4bs = sorted(books_dir.glob("*.m4b"))

    return {
        "book_identity": _path_if_exists(book_root / "book_identity.json"),
        "book_identity_report": _path_if_exists(book_root / "reports" / "book_identity.json"),
        "book_json": _path_if_exists(book_root / "book.json"),
        "source_manifest": _path_if_exists(book_root / "manifest.json"),
        "layout_json": _path_if_exists(book_root / "layout.json"),
        "chapters_dir": _path_if_exists(book_root / "chapters"),
        "narration_dir": _path_if_exists(book_root / "narration"),
        "chunks_dir": _path_if_exists(book_root / "chunks"),
        "chunk_manifest": _path_if_exists(book_root / "chunks" / "manifest.json"),
        "front_matter_dir": _path_if_exists(book_root / "front_matter"),
        "front_matter_txt": _path_if_exists(book_root / "front_matter" / "front_matter.txt"),
        "front_matter_wav": _path_if_exists(book_root / "front_matter" / "front_matter.wav"),
        "front_matter_report": _path_if_exists(book_root / "front_matter" / "front_matter.json"),
        "wav_dir": _path_if_exists(book_root / "wav"),
        "chapters_audio_dir": _path_if_exists(book_root / "chapters_audio"),
        "books_dir": _path_if_exists(books_dir),
        "book_wav": str(full_wavs[-1]) if full_wavs else (str(any_wavs[-1]) if any_wavs else None),
        "book_mp3": str(mp3s[-1]) if mp3s else None,
        "book_mp3_report": _path_if_exists(mp3s[-1].with_suffix(".json")) if mp3s else None,
        "book_mp3_metadata_report": _path_if_exists(mp3s[-1].with_suffix(".metadata.json")) if mp3s else None,
        "metadata_report": _path_if_exists(book_root / "reports" / "mp3_metadata.json"),
        "book_m4b": str(m4bs[-1]) if m4bs else None,
        "reports_dir": _path_if_exists(book_root / "reports"),
        "render_book_report": _path_if_exists(book_root / "reports" / "render_book.json"),
        "pipeline_status": _path_if_exists(book_root / "reports" / "pipeline_status.json"),
        "pipeline_log": _path_if_exists(book_root / "reports" / "pipeline.log"),
    }


def _collect_metrics(book_root: Path, stage_results: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    render_book_report = _read_json_if_exists(book_root / "reports" / "render_book.json")
    pipeline_status = _read_json_if_exists(book_root / "reports" / "pipeline_status.json")

    chapter_audio_files = sorted((book_root / "chapters_audio").glob("chapter_*.wav"))
    chunk_txt_files = sorted((book_root / "chunks").glob("chapter_*/*.txt"))
    chunk_wav_files = sorted((book_root / "wav").glob("chapter_*/*.wav"))
    front_matter_report = _read_json_if_exists(book_root / "front_matter" / "front_matter.json")

    audio_seconds = None
    audio_duration = None

    # Prefer the book audio stage result if available.
    for result in stage_results or []:
        data = result.get("data") or {}
        if "audio_seconds" in data:
            audio_seconds = data.get("audio_seconds")
            audio_duration = data.get("audio_duration")

    if audio_seconds is None:
        audio_seconds = render_book_report.get("audio_seconds")
        audio_duration = render_book_report.get("audio_duration")

    return {
        "chapters_audio_files": len(chapter_audio_files),
        "chunk_text_files": len(chunk_txt_files),
        "chunk_wav_files": len(chunk_wav_files),
        "front_matter_generated": bool(_path_if_exists(book_root / "front_matter" / "front_matter.wav")),
        "front_matter_status": front_matter_report.get("status"),
        "chunks_rendered_last_run": render_book_report.get("chunks_rendered"),
        "chunks_reused_last_run": render_book_report.get("chunks_reused"),
        "audio_seconds": audio_seconds,
        "audio_duration": audio_duration,
        "pipeline_elapsed_seconds": pipeline_status.get("elapsed_seconds"),
        "pipeline_elapsed_display": pipeline_status.get("elapsed_display"),
        "stage_results_count": len(stage_results or []),
    }


def _collect_tts_info(book_root: Path, stage_results: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    voice = None
    speed = None

    for result in stage_results or []:
        data = result.get("data") or {}
        voice = voice or data.get("voice")
        speed = speed if speed is not None else data.get("speed")

    render_book_report = _read_json_if_exists(book_root / "reports" / "render_book.json")
    voice = voice or render_book_report.get("voice")
    speed = speed if speed is not None else render_book_report.get("speed")

    return {
        "provider": "kokoro",
        "voice": voice,
        "speed": speed,
        "sample_rate": _infer_sample_rate(book_root),
    }


def _infer_sample_rate(book_root: Path) -> Optional[int]:
    # Avoid importing soundfile here; the audio utilities validate sample rates.
    report = _read_json_if_exists(book_root / "books" / f"{book_root.name}_full.json")
    stitch = report.get("stitch") or {}
    sr = stitch.get("sample_rate")
    return int(sr) if isinstance(sr, int) else None


def _collect_publishing_info(book_root: Path, stage_results: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Collect information about user-facing published deliverables."""
    books_dir = book_root / "books"
    mp3s = sorted(books_dir.glob("*.mp3"))
    mp3_reports = []

    for mp3_path in mp3s:
        report = _read_json_if_exists(mp3_path.with_suffix(".json"))
        mp3s_item = {
            "file": str(mp3_path),
            "size_bytes": mp3_path.stat().st_size if mp3_path.exists() else None,
            "report_file": _path_if_exists(mp3_path.with_suffix(".json")),
            "metadata_report_file": _path_if_exists(mp3_path.with_suffix(".metadata.json")),
        }
        metadata_report = _read_json_if_exists(mp3_path.with_suffix(".metadata.json"))
        if metadata_report:
            mp3s_item["metadata"] = {
                "status": metadata_report.get("status"),
                "tags": metadata_report.get("tags", {}),
                "report_file": _path_if_exists(mp3_path.with_suffix(".metadata.json")),
            }
        if report:
            mp3s_item.update({
                "codec": report.get("codec"),
                "bitrate": report.get("bitrate"),
                "source_file": report.get("source_file"),
                "source_size_bytes": report.get("source_size_bytes"),
                "output_size_bytes": report.get("output_size_bytes"),
                "compression_ratio": report.get("compression_ratio"),
                "status": report.get("status"),
            })
        mp3_reports.append(mp3s_item)

    latest_mp3_stage = None
    latest_metadata_stage = None
    for result in stage_results or []:
        if result.get("name") == "MP3 Export":
            latest_mp3_stage = result.get("data") or {}
        if result.get("name") == "Metadata Tags":
            latest_metadata_stage = result.get("data") or {}

    return {
        "mp3": {
            "latest": str(mp3s[-1]) if mp3s else None,
            "items": mp3_reports,
            "last_stage": latest_mp3_stage,
            "metadata_last_stage": latest_metadata_stage,
        },
        "m4b": {
            "latest": str(sorted(books_dir.glob("*.m4b"))[-1]) if sorted(books_dir.glob("*.m4b")) else None,
        },
    }


def _read_json_if_exists(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp_path.replace(path)


def _path_if_exists(path: Path) -> Optional[str]:
    return str(path) if path.exists() else None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
