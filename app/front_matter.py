from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Dict, Optional

from tts import get_tts


def build_front_matter_text(book_root: str | Path) -> Dict[str, Any]:
    """Build the spoken opening for the audiobook from book identity metadata.

    Priority order:
      1. book_identity.json
      2. existing book/manifest artifacts

    This intentionally does not modify parser output, chapter JSON, narration
    TXT, or chunk TXT. It creates a separate front_matter asset that is
    prepended during book-level stitching.
    """
    book_root = Path(book_root)
    metadata = _collect_book_metadata(book_root)

    title = _clean_text(metadata.get("title") or book_root.name)
    subtitle = _clean_text(metadata.get("subtitle") or "")
    author = _clean_text(metadata.get("author") or "")

    blocks = []
    if title:
        blocks.append(_sentence(title))
    if subtitle and _norm(subtitle) != _norm(title):
        blocks.append(_sentence(subtitle))
    if author:
        blocks.append(_sentence(f"By {author}"))

    text = "\n\n".join(blocks).strip()

    return {
        "text": text,
        "title": title,
        "subtitle": subtitle,
        "author": author,
        "source": metadata.get("source"),
        "identity_file": metadata.get("identity_file"),
        "confidence": metadata.get("confidence", {}),
    }


def render_front_matter(
    book_root: str | Path,
    output_txt: str | Path | None = None,
    output_wav: str | Path | None = None,
    voice: Optional[str] = None,
    speed: Optional[float] = None,
    force: bool = False,
    quiet: bool = False,
) -> Dict[str, Any]:
    """Create front_matter.txt and front_matter.wav for a book output folder."""
    book_root = Path(book_root)
    front_matter_dir = book_root / "front_matter"
    output_txt = Path(output_txt) if output_txt else front_matter_dir / "front_matter.txt"
    output_wav = Path(output_wav) if output_wav else front_matter_dir / "front_matter.wav"

    output_txt.parent.mkdir(parents=True, exist_ok=True)
    output_wav.parent.mkdir(parents=True, exist_ok=True)

    built = build_front_matter_text(book_root)
    text = built["text"]

    if not text:
        raise ValueError("Could not build front matter text. Missing title/subtitle/author metadata.")

    previous_text = output_txt.read_text(encoding="utf-8") if output_txt.exists() else None
    text_changed = previous_text != text
    output_txt.write_text(text + "\n", encoding="utf-8")

    should_render = force or text_changed or not output_wav.exists()

    start = time.time()

    _print("\n============================================================", quiet)
    _print("Front Matter", quiet)
    _print("============================================================", quiet)
    _print(f"Title:             {built.get('title') or ''}", quiet)
    _print(f"Subtitle:          {built.get('subtitle') or ''}", quiet)
    _print(f"Author:            {built.get('author') or ''}", quiet)
    _print(f"Source:            {built.get('source') or ''}", quiet)
    _print(f"Text:              {output_txt}", quiet)
    _print(f"WAV:               {output_wav}", quiet)
    _print(f"Mode:              {'render' if should_render else 'reuse existing'}", quiet)
    _print("============================================================\n", quiet)

    tts_result: Dict[str, Any] | None = None
    status = "skipped_existing"

    if should_render:
        tts = get_tts("kokoro")
        tts_result = tts.generate(text, output_wav, voice=voice, speed=speed)
        status = "rendered"
    elif not output_wav.exists():
        raise FileNotFoundError(f"Front matter WAV was expected but does not exist: {output_wav}")

    elapsed = round(time.time() - start, 2)

    report = {
        "status": status,
        "book_root": str(book_root),
        "front_matter_dir": str(front_matter_dir),
        "output_txt": str(output_txt),
        "output_wav": str(output_wav),
        "title": built.get("title"),
        "subtitle": built.get("subtitle"),
        "author": built.get("author"),
        "metadata_source": built.get("source"),
        "identity_file": built.get("identity_file"),
        "confidence": built.get("confidence", {}),
        "text_changed": bool(text_changed),
        "force": bool(force),
        "voice": voice,
        "speed": speed,
        "elapsed_seconds": elapsed,
        "elapsed_display": _format_duration(elapsed),
        "tts": tts_result,
    }

    report_path = output_wav.with_suffix(".json")
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    report["report_file"] = str(report_path)

    _print("\n============================================================", quiet)
    _print("Front Matter Complete", quiet)
    _print("============================================================", quiet)
    _print(f"Status:            {status}", quiet)
    _print(f"Text:              {output_txt}", quiet)
    _print(f"WAV:               {output_wav}", quiet)
    _print(f"Report:            {report_path}", quiet)
    _print("============================================================\n", quiet)

    return report


def default_front_matter_wav(book_root: str | Path) -> Path:
    return Path(book_root) / "front_matter" / "front_matter.wav"


def _collect_book_metadata(book_root: Path) -> Dict[str, Any]:
    identity_path = book_root / "book_identity.json"
    identity = _read_json_if_exists(identity_path)
    if identity:
        return {
            "title": identity.get("title"),
            "subtitle": identity.get("subtitle"),
            "author": identity.get("author"),
            "source": "book_identity.json",
            "identity_file": str(identity_path),
            "confidence": identity.get("confidence", {}),
        }

    sources = [
        ("book.json", book_root / "book.json"),
        ("manifest.json", book_root / "manifest.json"),
        ("chunks/manifest.json", book_root / "chunks" / "manifest.json"),
        ("books/manifest.json", book_root / "books" / "manifest.json"),
    ]

    combined: Dict[str, Any] = {}
    first_source = None

    for source_name, path in sources:
        data = _read_json_if_exists(path)
        if not data:
            continue

        book_section = data.get("book") if isinstance(data.get("book"), dict) else {}
        title = data.get("title") or book_section.get("title") or data.get("book")
        subtitle = data.get("subtitle") or book_section.get("subtitle")
        author = data.get("author") or book_section.get("author")

        if title and not combined.get("title"):
            combined["title"] = title
            first_source = first_source or source_name
        if subtitle and not combined.get("subtitle"):
            combined["subtitle"] = subtitle
            first_source = first_source or source_name
        if author and not combined.get("author"):
            combined["author"] = author
            first_source = first_source or source_name

    combined["source"] = first_source
    return combined


def _read_json_if_exists(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    return text


def _sentence(text: str) -> str:
    text = _clean_text(text)
    if text and not re.search(r"[.!?]['\")\]]?$", text):
        return text + "."
    return text


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", (text or "").lower())).strip()


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
