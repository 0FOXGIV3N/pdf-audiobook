from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from audio_utils import concat_wavs
from bootstrap import bootstrap_command


def render_book_audio(
    chapters_audio_dir: str | Path,
    output_wav: str | Path,
    chapter_gap_seconds: float = 0.5,
    chapters: Optional[List[int]] = None,
    front_matter_wav: str | Path | None = None,
    quiet: bool = False,
) -> Dict[str, Any]:
    """Stitch front matter and chapter WAV files into one full-book WAV deliverable."""
    chapters_audio_dir = Path(chapters_audio_dir)
    output_wav = Path(output_wav)
    front_matter_path = Path(front_matter_wav) if front_matter_wav else None

    if not chapters_audio_dir.exists():
        raise FileNotFoundError(f"Chapters audio folder not found: {chapters_audio_dir}")

    chapter_wavs = _chapter_wav_files(chapters_audio_dir)
    if chapters:
        wanted = set(chapters)
        chapter_wavs = [p for p in chapter_wavs if _chapter_number(p) in wanted]

    if not chapter_wavs:
        raise FileNotFoundError(f"No chapter WAV files found in: {chapters_audio_dir}")

    ordered_wavs: List[Path] = []
    front_matter_included = False

    if front_matter_path:
        if not front_matter_path.exists():
            raise FileNotFoundError(f"Front matter WAV not found: {front_matter_path}")
        ordered_wavs.append(front_matter_path)
        front_matter_included = True

    ordered_wavs.extend(chapter_wavs)

    output_wav.parent.mkdir(parents=True, exist_ok=True)

    _print("\n============================================================", quiet)
    _print("Book Audio Stitching", quiet)
    _print("============================================================", quiet)
    _print(f"Front matter:      {'yes' if front_matter_included else 'no'}", quiet)
    if front_matter_included:
        _print(f"Front matter WAV:  {front_matter_path}", quiet)
    _print(f"Chapter WAVs:      {len(chapter_wavs)}", quiet)
    _print(f"Chapter gap:       {chapter_gap_seconds}s", quiet)
    _print(f"Output WAV:        {output_wav}", quiet)
    _print("============================================================\n", quiet)

    start = time.time()

    def progress(index: int, total: int, path: Path) -> None:
        label = "front_matter.wav" if front_matter_included and index == 1 else path.name
        _print(f"[{index:03d}/{total:03d}] {label}", quiet)

    stitch = concat_wavs(
        ordered_wavs,
        output_wav,
        gap_seconds=chapter_gap_seconds,
        crossfade_ms=0,
        progress_callback=progress,
    )

    elapsed = round(time.time() - start, 2)
    report = {
        "chapters_audio_dir": str(chapters_audio_dir),
        "front_matter_wav": str(front_matter_path) if front_matter_included else None,
        "front_matter_included": bool(front_matter_included),
        "output_wav": str(output_wav),
        "chapters": len(chapter_wavs),
        "inputs_total": len(ordered_wavs),
        "chapter_gap_seconds": float(chapter_gap_seconds),
        "elapsed_seconds": elapsed,
        "elapsed_display": _format_duration(elapsed),
        "audio_seconds": stitch["duration_seconds"],
        "audio_duration": _format_duration(stitch["duration_seconds"]),
        "stitch": stitch,
        "items": [str(p) for p in ordered_wavs],
        "chapter_items": [str(p) for p in chapter_wavs],
    }

    report_path = output_wav.with_suffix(".json")
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    report["report_file"] = str(report_path)

    _print("\n============================================================", quiet)
    _print("Book Audio Complete", quiet)
    _print("============================================================", quiet)
    _print(f"Output:            {output_wav}", quiet)
    _print(f"Duration:          {report['audio_duration']}", quiet)
    _print(f"Elapsed:           {report['elapsed_display']}", quiet)
    _print(f"Report:            {report_path}", quiet)
    _print("============================================================\n", quiet)

    return report


def _chapter_wav_files(chapters_audio_dir: Path) -> List[Path]:
    files = [p for p in chapters_audio_dir.glob("chapter_*.wav") if re.match(r"^chapter_\d+\.wav$", p.name)]
    return sorted(files, key=_chapter_number)


def _chapter_number(path: Path) -> int:
    match = re.search(r"chapter_(\d+)", path.name)
    if not match:
        raise ValueError(f"Could not determine chapter number from: {path}")
    return int(match.group(1))


def _parse_chapters(value: str | None) -> Optional[List[int]]:
    if not value:
        return None
    chapters: List[int] = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_text, end_text = part.split("-", 1)
            chapters.extend(range(int(start_text), int(end_text) + 1))
        else:
            chapters.append(int(part))
    return sorted(set(chapters))


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


def _print(message: str, quiet: bool = False) -> None:
    if not quiet:
        print(message, flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Stitch front matter and chapter WAV files into one full-book WAV.")
    parser.add_argument("chapters_audio_dir", help="Path to chapters_audio directory")
    parser.add_argument("output_wav", help="Path to final book WAV deliverable")
    parser.add_argument(
        "--front-matter-wav",
        default=None,
        help="Optional front matter WAV to prepend before chapter_001.wav.",
    )
    parser.add_argument(
        "--chapter-gap-seconds",
        type=float,
        default=0.5,
        help="Silence inserted between source WAVs. Default: 0.5",
    )
    parser.add_argument("--chapters", default=None, help="Optional chapter filter, e.g. 1,2,6 or 1-3,6")
    parser.add_argument("--quiet", action="store_true", help="Suppress progress output")
    args = parser.parse_args()

    output_wav = Path(args.output_wav)
    bootstrap_command(
        command="render_book_audio",
        output_root=output_wav.parent.parent,
        show_banner=not args.quiet,
    )

    render_book_audio(
        chapters_audio_dir=args.chapters_audio_dir,
        output_wav=output_wav,
        chapter_gap_seconds=args.chapter_gap_seconds,
        chapters=_parse_chapters(args.chapters),
        front_matter_wav=args.front_matter_wav,
        quiet=args.quiet,
    )


if __name__ == "__main__":
    main()
