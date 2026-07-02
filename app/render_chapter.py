from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

from bootstrap import bootstrap_command
from tts import get_tts
from audio_utils import concat_wavs
from pipeline_status import PipelineStatus


def _numeric_txt_files(chapter_chunks_dir: Path) -> List[Path]:
    txt_files = [p for p in chapter_chunks_dir.glob("*.txt") if p.stem.isdigit()]
    return sorted(txt_files, key=lambda p: int(p.stem))


def _wav_path_for_chunk(chunk_txt: Path, wav_dir: Path) -> Path:
    return wav_dir / f"{chunk_txt.stem}.wav"


def _read_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"Chunk text file is empty: {path}")
    return text


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


def _progress_bar(done: int, total: int, width: int = 28) -> str:
    if total <= 0:
        return "[" + "-" * width + "]"
    ratio = min(1.0, max(0.0, done / total))
    filled = int(round(width * ratio))
    return "[" + "#" * filled + "-" * (width - filled) + "]"


def _print(message: str, quiet: bool = False) -> None:
    if not quiet:
        print(message, flush=True)


def render_chapter(
    chapter_chunks_dir: str | Path,
    chapter_wav_dir: str | Path,
    chapter_output_wav: str | Path,
    voice: str | None = None,
    speed: float | None = None,
    force: bool = False,
    stitch_only: bool = False,
    gap_seconds: float = 0.0,
    no_stitch: bool = False,
    quiet: bool = False,
    status_root: str | Path | None = None,
) -> Dict[str, Any]:
    """Render all text chunks in one chapter and optionally stitch them into one WAV.

    Existing chunk WAVs are reused by default. Use force=True to regenerate all
    chunk WAVs before stitching.
    """
    chapter_chunks_dir = Path(chapter_chunks_dir)
    chapter_wav_dir = Path(chapter_wav_dir)
    chapter_output_wav = Path(chapter_output_wav)
    output_root = Path(status_root) if status_root else chapter_output_wav.parent.parent
    status = PipelineStatus(output_root)

    if not chapter_chunks_dir.exists():
        raise FileNotFoundError(f"Chapter chunks directory not found: {chapter_chunks_dir}")

    chunk_txt_files = _numeric_txt_files(chapter_chunks_dir)
    if not chunk_txt_files:
        raise FileNotFoundError(f"No numeric chunk .txt files found in: {chapter_chunks_dir}")

    chapter_wav_dir.mkdir(parents=True, exist_ok=True)
    chapter_output_wav.parent.mkdir(parents=True, exist_ok=True)

    wav_paths: List[Path] = [_wav_path_for_chunk(p, chapter_wav_dir) for p in chunk_txt_files]
    existing_count = sum(1 for p in wav_paths if p.exists())
    to_render_count = sum(1 for p in wav_paths if force or not p.exists())

    _print("\n===== Chapter Render =====\n", quiet)
    _print(f"Chunks found:      {len(chunk_txt_files)}", quiet)
    _print(f"Existing WAVs:     {existing_count}", quiet)
    _print(f"To render:         {to_render_count}", quiet)
    _print(f"Stitch enabled:    {not no_stitch}", quiet)
    _print(f"Chunks dir:        {chapter_chunks_dir}", quiet)
    _print(f"Chunk WAV dir:     {chapter_wav_dir}", quiet)
    _print(f"Chapter WAV:       {chapter_output_wav}", quiet)
    if force:
        _print("Mode:              force regenerate", quiet)
    elif stitch_only:
        _print("Mode:              stitch only", quiet)
    else:
        _print("Mode:              resume / reuse existing", quiet)
    _print("", quiet)

    status.start_stage(
        "Chapter Rendering",
        total=len(chunk_txt_files),
        message=f"Rendering chapter audio: {chapter_chunks_dir.name}",
        extra={
            "chapter_chunks_dir": str(chapter_chunks_dir),
            "chapter_wav_dir": str(chapter_wav_dir),
            "chapter_output_wav": str(chapter_output_wav),
            "chunks_found": len(chunk_txt_files),
            "existing_wavs": existing_count,
            "to_render": to_render_count,
            "force": bool(force),
            "stitch_only": bool(stitch_only),
            "no_stitch": bool(no_stitch),
        },
    )

    tts = None if stitch_only else get_tts("kokoro")

    rendered_items: List[Dict[str, Any]] = []
    rendered_count = 0
    skipped_count = 0
    render_start = time.time()

    for index, chunk_txt in enumerate(chunk_txt_files, start=1):
        wav_path = _wav_path_for_chunk(chunk_txt, chapter_wav_dir)
        progress = _progress_bar(index, len(chunk_txt_files))

        status.update(
            current=index - 1,
            total=len(chunk_txt_files),
            item=chunk_txt.name,
            message=f"Processing {chunk_txt.name}",
        )

        if wav_path.exists() and not force:
            skipped_count += 1
            _print(
                f"{progress} [{index:03d}/{len(chunk_txt_files):03d}] "
                f"SKIP existing {chunk_txt.name} -> {wav_path.name}",
                quiet,
            )
            status.update(
                current=index,
                total=len(chunk_txt_files),
                item=chunk_txt.name,
                message=f"Skipped existing {wav_path.name}",
            )
            rendered_items.append({
                "order": index,
                "input_txt": str(chunk_txt),
                "output_wav": str(wav_path),
                "status": "skipped_existing",
            })
            continue

        if stitch_only:
            raise FileNotFoundError(f"Missing WAV in stitch-only mode: {wav_path}")

        chunk_start = time.time()
        _print(
            f"{progress} [{index:03d}/{len(chunk_txt_files):03d}] "
            f"Rendering {chunk_txt.name} -> {wav_path.name}",
            quiet,
        )

        text = _read_text(chunk_txt)
        result = tts.generate(text, wav_path, voice=voice, speed=speed)
        elapsed = time.time() - chunk_start
        rendered_count += 1

        _print(
            f"{progress} [{index:03d}/{len(chunk_txt_files):03d}] "
            f"Done {wav_path.name} | chunk audio {result.get('duration_seconds', 'n/a')}s "
            f"| render {_format_duration(elapsed)}",
            quiet,
        )
        status.update(
            current=index,
            total=len(chunk_txt_files),
            item=chunk_txt.name,
            message=f"Rendered {wav_path.name}",
            extra={"last_chunk_render_seconds": round(elapsed, 2)},
        )

        rendered_items.append({
            "order": index,
            "input_txt": str(chunk_txt),
            "output_wav": str(wav_path),
            "status": "rendered",
            "render_seconds": round(elapsed, 2),
            "tts": result,
        })

    stitch_result: Dict[str, Any] | None = None
    stitch_start = time.time()

    if no_stitch:
        _print("\nStitch skipped by --no-stitch.", quiet)
    else:
        status.update(message=f"Stitching {len(wav_paths)} WAV files", extra={"stitching": True})
        _print(f"\nStitching {len(wav_paths)} WAV files...", quiet)
        stitch_result = concat_wavs(wav_paths, chapter_output_wav, gap_seconds=gap_seconds)
        _print(
            f"Stitch complete: {_format_duration(stitch_result['duration_seconds'])} "
            f"audio | {_format_duration(time.time() - stitch_start)} processing",
            quiet,
        )
        status.update(message="Chapter stitching complete", extra={"stitching": False, "stitch": stitch_result})

    total_elapsed = time.time() - render_start

    report = {
        "chapter_chunks_dir": str(chapter_chunks_dir),
        "chapter_wav_dir": str(chapter_wav_dir),
        "chapter_output_wav": str(chapter_output_wav),
        "chunks": len(chunk_txt_files),
        "existing_wavs_at_start": existing_count,
        "to_render_at_start": to_render_count,
        "rendered": rendered_count,
        "skipped_existing": skipped_count,
        "force": bool(force),
        "stitch_only": bool(stitch_only),
        "no_stitch": bool(no_stitch),
        "quiet": bool(quiet),
        "voice": voice,
        "speed": speed,
        "gap_seconds": float(gap_seconds),
        "elapsed_seconds": round(total_elapsed, 2),
        "elapsed_display": _format_duration(total_elapsed),
        "stitch": stitch_result,
        "items": rendered_items,
    }

    report_path = chapter_output_wav.with_suffix(".json")
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    report["report_file"] = str(report_path)

    status.finish_stage(
        message="Chapter render complete",
        extra={
            "chapter_report_file": str(report_path),
            "rendered": rendered_count,
            "skipped_existing": skipped_count,
            "elapsed_seconds": round(total_elapsed, 2),
        },
    )

    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render all Kokoro chunk WAVs for one chapter and optionally stitch them into a chapter WAV."
    )
    parser.add_argument("chapter_chunks_dir", help="Path to chunks/chapter_### directory")
    parser.add_argument("chapter_wav_dir", help="Path to wav/chapter_### output directory")
    parser.add_argument("chapter_output_wav", help="Path to final stitched chapter WAV")
    parser.add_argument("--voice", default=None, help="Kokoro voice name, e.g. af_heart")
    parser.add_argument("--speed", type=float, default=None, help="Speech speed")
    parser.add_argument("--force", action="store_true", help="Regenerate existing chunk WAV files")
    parser.add_argument(
        "--stitch-only",
        action="store_true",
        help="Do not synthesize; only stitch existing chunk WAV files",
    )
    parser.add_argument(
        "--no-stitch",
        action="store_true",
        help="Render missing chunk WAVs but do not create the stitched chapter WAV",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress progress output. Errors and final Python exceptions still print normally.",
    )
    parser.add_argument(
        "--gap-seconds",
        type=float,
        default=0.0,
        help="Optional silence inserted between chunk WAVs during stitching. Default: 0.0",
    )
    args = parser.parse_args()

    if args.stitch_only and args.no_stitch:
        print("Error: --stitch-only and --no-stitch cannot be used together.", file=sys.stderr)
        raise SystemExit(2)

    ctx = bootstrap_command(
        "render_chapter",
        None,
        None,
        args.chapter_chunks_dir,
        args.chapter_wav_dir,
        args.chapter_output_wav,
        show_banner=not args.quiet,
    )

    report = render_chapter(
        args.chapter_chunks_dir,
        args.chapter_wav_dir,
        args.chapter_output_wav,
        voice=args.voice,
        speed=args.speed,
        force=args.force,
        stitch_only=args.stitch_only,
        gap_seconds=args.gap_seconds,
        no_stitch=args.no_stitch,
        quiet=args.quiet,
        status_root=ctx.output_root,
    )

    if not args.quiet:
        print("\n===== Chapter Render Complete =====\n", flush=True)
        print(f"Chunks:            {report['chunks']}", flush=True)
        print(f"Rendered:          {report['rendered']}", flush=True)
        print(f"Skipped existing:  {report['skipped_existing']}", flush=True)
        print(f"Elapsed:           {report['elapsed_display']}", flush=True)
        if report.get("stitch"):
            print(f"Chapter WAV:       {report['chapter_output_wav']}", flush=True)
            print(f"Duration:          {_format_duration(report['stitch']['duration_seconds'])}", flush=True)
        else:
            print("Chapter WAV:       not created (--no-stitch)", flush=True)
        print(f"Report:            {report['report_file']}", flush=True)


if __name__ == "__main__":
    main()
