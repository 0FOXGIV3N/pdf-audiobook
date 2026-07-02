from __future__ import annotations

import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


METADATA_VERSION = "phase5_metadata_tags_v1.0"


def write_mp3_metadata(
    book_root: str | Path,
    mp3_file: str | Path,
    genre: str = "Audiobook",
    year: Optional[str] = None,
    comment: Optional[str] = None,
    quiet: bool = False,
) -> Dict[str, Any]:
    """Write audiobook metadata tags into an existing MP3 using FFmpeg.

    This intentionally runs after MP3 export so publishing and tagging stay
    separate, resumable stages. It rewrites the MP3 in-place through a temporary
    file, preserving the audio stream with ``-codec copy``.
    """
    book_root = Path(book_root)
    mp3_file = Path(mp3_file)

    if not book_root.exists():
        raise FileNotFoundError(f"Book output folder not found: {book_root}")
    if not mp3_file.exists():
        raise FileNotFoundError(f"MP3 file not found for metadata tagging: {mp3_file}")

    reports_dir = book_root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    identity = _read_json_if_exists(book_root / "book_identity.json")
    production_manifest = _read_json_if_exists(book_root / "books" / "manifest.json")
    book_section = production_manifest.get("book") if isinstance(production_manifest.get("book"), dict) else {}

    title = _clean(identity.get("title") or book_section.get("title") or book_root.name)
    subtitle = _clean(identity.get("subtitle") or book_section.get("subtitle") or "")
    author = _clean(identity.get("author") or book_section.get("author") or "")

    full_title = title
    if title and subtitle:
        full_title = f"{title}: {subtitle}"

    album = full_title or title or book_root.name
    artist = author or "Unknown Author"
    album_artist = artist

    if comment is None:
        if subtitle:
            comment = f"{title}. {subtitle}."
        else:
            comment = title

    tags = {
        "title": full_title or title,
        "artist": artist,
        "album": album,
        "album_artist": album_artist,
        "genre": genre or "Audiobook",
        "track": "1/1",
        "comment": _clean(comment or ""),
    }
    if subtitle:
        tags["subtitle"] = subtitle
    if author:
        tags["author"] = author
    if year:
        tags["date"] = str(year)
        tags["year"] = str(year)

    tmp_file = mp3_file.with_name(mp3_file.stem + ".metadata.tmp" + mp3_file.suffix)

    command = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error" if quiet else "info",
        "-i",
        str(mp3_file),
        "-map",
        "0:a",
        "-codec",
        "copy",
        "-id3v2_version",
        "3",
    ]

    for key, value in tags.items():
        if value is not None and str(value).strip():
            command.extend(["-metadata", f"{key}={value}"])

    command.append(str(tmp_file))

    if not quiet:
        print("\n============================================================", flush=True)
        print("MP3 Metadata Tags", flush=True)
        print("============================================================", flush=True)
        print(f"MP3:               {mp3_file}", flush=True)
        print(f"Title:             {tags.get('title', '')}", flush=True)
        print(f"Subtitle:          {tags.get('subtitle', '')}", flush=True)
        print(f"Author/Artist:     {tags.get('artist', '')}", flush=True)
        print(f"Genre:             {tags.get('genre', '')}", flush=True)
        if year:
            print(f"Year:              {year}", flush=True)
        print("============================================================\n", flush=True)

    start = time.time()
    result = subprocess.run(command, capture_output=True, text=True)
    elapsed = round(time.time() - start, 2)

    if result.returncode != 0:
        try:
            if tmp_file.exists():
                tmp_file.unlink()
        except Exception:
            pass
        raise RuntimeError(
            "FFmpeg MP3 metadata tagging failed.\n"
            f"Command: {' '.join(command)}\n"
            f"STDOUT: {result.stdout}\n"
            f"STDERR: {result.stderr}"
        )

    tmp_file.replace(mp3_file)

    report = {
        "metadata_version": METADATA_VERSION,
        "status": "complete",
        "generated_at": _now_iso(),
        "book_root": str(book_root),
        "mp3_file": str(mp3_file),
        "tags": tags,
        "source": {
            "book_identity": str(book_root / "book_identity.json") if (book_root / "book_identity.json").exists() else None,
            "production_manifest": str(book_root / "books" / "manifest.json") if (book_root / "books" / "manifest.json").exists() else None,
        },
        "elapsed_seconds": elapsed,
        "elapsed_display": _format_duration(elapsed),
        "command": command,
        "ffmpeg_stdout": result.stdout.strip(),
        "ffmpeg_stderr": result.stderr.strip(),
    }

    mp3_report_path = mp3_file.with_suffix(".metadata.json")
    reports_copy_path = reports_dir / "mp3_metadata.json"

    _write_json(mp3_report_path, report)
    _write_json(reports_copy_path, report)

    report["report_file"] = str(mp3_report_path)
    report["report_copy"] = str(reports_copy_path)

    if not quiet:
        print("\n============================================================", flush=True)
        print("MP3 Metadata Complete", flush=True)
        print("============================================================", flush=True)
        print(f"MP3:               {mp3_file}", flush=True)
        print(f"Report:            {mp3_report_path}", flush=True)
        print("============================================================\n", flush=True)

    return report


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


def _clean(text: Any) -> str:
    import re

    text = str(text or "").replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text).strip()
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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Write metadata tags into an MP3 audiobook deliverable.")
    parser.add_argument("book_root", help="Path to output/<BookName> folder")
    parser.add_argument("mp3_file", help="Path to MP3 file to tag")
    parser.add_argument("--genre", default="Audiobook", help="Genre tag. Default: Audiobook")
    parser.add_argument("--year", default=None, help="Optional year/date tag")
    parser.add_argument("--comment", default=None, help="Optional comment/description tag")
    parser.add_argument("--quiet", action="store_true", help="Suppress progress output")
    args = parser.parse_args()

    write_mp3_metadata(
        book_root=args.book_root,
        mp3_file=args.mp3_file,
        genre=args.genre,
        year=args.year,
        comment=args.comment,
        quiet=args.quiet,
    )


if __name__ == "__main__":
    main()
