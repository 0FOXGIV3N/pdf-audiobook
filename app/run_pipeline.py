from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from bootstrap import bootstrap_command
from chunk_generator import build_chunks
from pipeline_manager import PipelineManager, StageResult
from render_book import BookRenderOptions, render_book


PIPELINE_VERSION = "phase6_one_command_pipeline_v1.2"
DEFAULT_OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "/output"))
DEFAULT_INPUT_DIR = Path(os.getenv("INPUT_DIR", "/input"))


@dataclass
class PipelineOptions:
    pdf_path: Path
    output_base: Path
    book_root: Path
    quiet: bool = False
    force_initial: bool = False
    force_chunks: bool = False
    force_audio: bool = False
    force_book_identity: bool = False
    force_front_matter: bool = False
    force_mp3: bool = False
    no_mp3: bool = False
    no_metadata: bool = False
    mp3_bitrate: str = "192k"
    voice: Optional[str] = None
    speed: Optional[float] = None
    target_words: int = 85
    min_words: int = 50
    max_words: int = 110
    wpm: int = 160
    book_identity_pages: int = 4


class InitialBuildStage:
    """Run the existing PDF-to-narration build stage.

    This intentionally delegates to the current app entry point, pdf_to_mp3.py,
    instead of duplicating parser/chapter/narration internals here. That keeps
    this one-command pipeline compatible with the existing architecture.
    """

    name = "Initial PDF Build"

    def __init__(self, options: PipelineOptions):
        self.options = options

    def should_run(self) -> bool:
        if self.options.force_initial:
            return True
        return not _initial_outputs_ready(self.options.book_root)

    def run(self) -> StageResult:
        start = time.time()
        app_entry = Path("/app/pdf_to_mp3.py")
        if not app_entry.exists():
            raise FileNotFoundError(
                "Could not find /app/pdf_to_mp3.py. The one-command pipeline "
                "expects the existing initial build entry point to remain in app/."
            )

        self.options.output_base.mkdir(parents=True, exist_ok=True)

        env = os.environ.copy()
        env["PDF_FILE"] = str(self.options.pdf_path)
        env["OUTPUT_DIR"] = str(self.options.output_base)

        command = [sys.executable, str(app_entry)]
        _print("\n============================================================", self.options.quiet)
        _print("Initial PDF Build", self.options.quiet)
        _print("============================================================", self.options.quiet)
        _print(f"PDF:               {self.options.pdf_path}", self.options.quiet)
        _print(f"Output base:       {self.options.output_base}", self.options.quiet)
        _print(f"Expected book:     {self.options.book_root}", self.options.quiet)
        _print("============================================================\n", self.options.quiet)

        result = subprocess.run(command, env=env, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Initial PDF build failed with exit code {result.returncode}.")

        # The existing entry point may sanitize the book folder name differently.
        resolved_root = _find_book_root(self.options.output_base, self.options.pdf_path, self.options.book_root)
        if resolved_root != self.options.book_root:
            self.options.book_root = resolved_root

        elapsed = round(time.time() - start, 2)
        return StageResult(
            name=self.name,
            status="complete",
            skipped=False,
            elapsed_seconds=elapsed,
            message="Initial PDF build complete",
            data={
                "pdf_path": str(self.options.pdf_path),
                "output_base": str(self.options.output_base),
                "book_root": str(self.options.book_root),
                "elapsed_seconds": elapsed,
            },
        )


class ChunkGenerationStage:
    """Build Kokoro-ready chunks from narration files."""

    name = "Chunk Generation"

    def __init__(self, options: PipelineOptions):
        self.options = options

    def should_run(self) -> bool:
        if self.options.force_chunks:
            return True
        manifest = self.options.book_root / "chunks" / "manifest.json"
        chunks_dir = self.options.book_root / "chunks"
        return not (manifest.exists() and any(chunks_dir.glob("chapter_*/*.txt")))

    def run(self) -> StageResult:
        start = time.time()
        narration_dir = self.options.book_root / "narration"
        chunks_dir = self.options.book_root / "chunks"

        if not narration_dir.exists():
            raise FileNotFoundError(f"Narration folder not found: {narration_dir}")

        _print("\n============================================================", self.options.quiet)
        _print("Chunk Generation", self.options.quiet)
        _print("============================================================", self.options.quiet)
        _print(f"Narration:         {narration_dir}", self.options.quiet)
        _print(f"Chunks:            {chunks_dir}", self.options.quiet)
        _print("============================================================\n", self.options.quiet)

        manifest = build_chunks(
            narration_dir,
            chunks_dir,
            target_words=self.options.target_words,
            min_words=self.options.min_words,
            max_words=self.options.max_words,
            words_per_minute=self.options.wpm,
        )

        elapsed = round(time.time() - start, 2)
        return StageResult(
            name=self.name,
            status="complete",
            skipped=False,
            elapsed_seconds=elapsed,
            message="Chunk generation complete",
            data={
                "narration_dir": str(narration_dir),
                "chunks_dir": str(chunks_dir),
                "chapters": manifest.get("chapters"),
                "total_chunks": manifest.get("total_chunks"),
                "estimated_minutes": manifest.get("estimated_minutes"),
                "elapsed_seconds": elapsed,
            },
        )


class BookRenderStage:
    """Render chapter audio, book audio, MP3, metadata, and manifest."""

    name = "Book Rendering & Publishing"

    def __init__(self, options: PipelineOptions):
        self.options = options

    def should_run(self) -> bool:
        # render_book.py already has current/up-to-date checks for chunk WAVs,
        # front matter, MP3 source timestamps, metadata, and manifest. Always run
        # this orchestration stage so it can reuse completed artifacts safely.
        return True

    def run(self) -> StageResult:
        start = time.time()
        book_options = BookRenderOptions(
            book_root=self.options.book_root,
            voice=self.options.voice,
            speed=self.options.speed,
            force=self.options.force_audio,
            force_book_identity=self.options.force_book_identity,
            source_pdf=self.options.pdf_path,
            book_identity_pages=self.options.book_identity_pages,
            force_front_matter=self.options.force_front_matter,
            no_mp3=self.options.no_mp3,
            force_mp3=self.options.force_mp3,
            no_metadata=self.options.no_metadata,
            mp3_bitrate=self.options.mp3_bitrate,
            quiet=self.options.quiet,
        )
        result = render_book(book_options)
        elapsed = round(time.time() - start, 2)
        return StageResult(
            name=self.name,
            status="complete",
            skipped=False,
            elapsed_seconds=elapsed,
            message="Book render and publishing complete",
            data={
                "book_root": str(self.options.book_root),
                "render_book": result,
                "elapsed_seconds": elapsed,
            },
        )


def run_pipeline(options: PipelineOptions) -> Dict[str, Any]:
    """Run the full audiobook pipeline.

    Important architecture note:
    The initial PDF build is the source of truth for the final book_root.
    When the caller does not provide an explicit --book-root, this function
    avoids creating a guessed output/<BookName> folder before the initial build
    has had a chance to create its own canonical folder. This prevents duplicate
    folders such as:

        /output/AI Revolution_DVG_2025
        /output/AI_Revolution_DVG_2025

    The temporary orchestration status root is /output until a real book_root is
    known. Final reports are always written to the resolved book_root.
    """
    status_root = options.book_root if _initial_outputs_ready(options.book_root) else options.output_base

    bootstrap_command(
        command="run_pipeline",
        pdf_path=options.pdf_path,
        output_root=status_root,
        show_banner=not options.quiet,
    )

    manager = PipelineManager(
        output_root=status_root,
        phase="Phase 6 — One Command Pipeline",
        quiet=options.quiet,
    )

    stages = [
        InitialBuildStage(options),
        ChunkGenerationStage(options),
        BookRenderStage(options),
    ]

    results = manager.run(stages, message="One-command audiobook pipeline started")

    # At this point InitialBuildStage has resolved options.book_root to the
    # actual folder created by the existing parser/build entry point.
    report = {
        "pipeline_version": PIPELINE_VERSION,
        "pdf_path": str(options.pdf_path),
        "output_base": str(options.output_base),
        "book_root": str(options.book_root),
        "status_root": str(status_root),
        "results": [r.to_dict() for r in results],
    }

    reports_dir = options.book_root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / "run_pipeline.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    report["report_file"] = str(report_path)

    _print("\n============================================================", options.quiet)
    _print("One-Command Pipeline Complete", options.quiet)
    _print("============================================================", options.quiet)
    _print(f"Book root:         {options.book_root}", options.quiet)
    _print(f"Books folder:      {options.book_root / 'books'}", options.quiet)
    _print(f"Report:            {report_path}", options.quiet)
    _print("============================================================\n", options.quiet)

    return report


def _initial_outputs_ready(book_root: Path) -> bool:
    return (
        (book_root / "book.json").exists()
        and (book_root / "manifest.json").exists()
        and (book_root / "chapters").exists()
        and any((book_root / "chapters").glob("chapter_*.json"))
        and (book_root / "narration").exists()
        and any((book_root / "narration").glob("narration_*.txt"))
    )


def _discover_pdf(input_dir: Path, explicit_pdf: Optional[str | Path] = None) -> Path:
    if explicit_pdf:
        path = Path(explicit_pdf)
        if not path.exists():
            raise FileNotFoundError(f"PDF not found: {path}")
        return path

    env_pdf = os.getenv("PDF_FILE", "").strip()
    if env_pdf:
        env_path = Path(env_pdf)
        if env_path.exists():
            return env_path

    pdfs = sorted(input_dir.glob("*.pdf")) if input_dir.exists() else []
    if len(pdfs) == 1:
        return pdfs[0]
    if not pdfs:
        raise FileNotFoundError(
            f"No PDF found. Put one PDF in {input_dir}, set PDF_FILE, or pass a PDF path."
        )

    lines = [f"Found {len(pdfs)} PDFs. Please specify one:", ""]
    for pdf in pdfs:
        lines.append(f"  python /app/run_pipeline.py \"{pdf}\"")
    raise RuntimeError("\n".join(lines))


def _safe_book_folder_name(pdf_path: Path) -> str:
    stem = pdf_path.stem.strip() or "Book"
    stem = re.sub(r"[^A-Za-z0-9._ -]+", "", stem)
    stem = re.sub(r"\s+", "_", stem)
    return stem or "Book"


def _find_book_root(output_base: Path, pdf_path: Path, expected: Path) -> Path:
    """Resolve the canonical output folder created by the initial build.

    Do not treat an existing empty/report-only expected folder as valid. The
    PipelineManager may create a status directory before the parser runs, so the
    only valid book_root is a folder that contains the initial build outputs.
    """
    if _initial_outputs_ready(expected):
        return expected

    candidates = []
    if output_base.exists():
        for path in output_base.iterdir():
            if path.is_dir() and _initial_outputs_ready(path):
                candidates.append(path)
    if not candidates:
        return expected

    expected_norm = _norm(expected.name)
    pdf_norm = _norm(pdf_path.stem)
    for candidate in candidates:
        c_norm = _norm(candidate.name)
        if c_norm == expected_norm or c_norm == pdf_norm or expected_norm in c_norm or pdf_norm in c_norm:
            return candidate

    return sorted(candidates, key=lambda p: p.stat().st_mtime)[-1]


def _find_existing_book_root(output_base: Path, pdf_path: Path, explicit_book_root: Optional[Path] = None) -> Optional[Path]:
    """Find an already-built book folder before the orchestrator starts."""
    if explicit_book_root and _initial_outputs_ready(explicit_book_root):
        return explicit_book_root

    if not output_base.exists():
        return None

    candidates = [p for p in output_base.iterdir() if p.is_dir() and _initial_outputs_ready(p)]
    if not candidates:
        return None

    pdf_norm = _norm(pdf_path.stem)
    for candidate in candidates:
        if _norm(candidate.name) == pdf_norm or pdf_norm in _norm(candidate.name):
            return candidate

    return sorted(candidates, key=lambda p: p.stat().st_mtime)[-1]


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def _print(message: str, quiet: bool = False) -> None:
    if not quiet:
        print(message, flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the full PDF Audiobook Generator pipeline from PDF to tagged MP3."
    )
    parser.add_argument("pdf", nargs="?", default=None, help="Optional source PDF path. If omitted, uses PDF_FILE or auto-discovers one PDF in /input.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Base output directory. Default: /output")
    parser.add_argument("--book-root", default=None, help="Optional explicit output/<BookName> folder")
    parser.add_argument("--quiet", action="store_true", help="Suppress most progress output")
    parser.add_argument("--force-initial", action="store_true", help="Regenerate parser/chapter/narration outputs")
    parser.add_argument("--force-chunks", action="store_true", help="Regenerate chunks")
    parser.add_argument("--force-audio", action="store_true", help="Regenerate chunk WAV files")
    parser.add_argument("--force-book-identity", action="store_true", help="Re-extract title/subtitle/author")
    parser.add_argument("--force-front-matter", action="store_true", help="Regenerate front matter WAV")
    parser.add_argument("--force-mp3", action="store_true", help="Regenerate MP3 even if current")
    parser.add_argument("--no-mp3", action="store_true", help="Skip MP3 export")
    parser.add_argument("--no-metadata", action="store_true", help="Skip MP3 metadata tagging")
    parser.add_argument("--mp3-bitrate", default="192k", help="MP3 bitrate. Default: 192k")
    parser.add_argument("--voice", default=None, help="Kokoro voice override")
    parser.add_argument("--speed", type=float, default=None, help="Kokoro speed override")
    parser.add_argument("--target-words", type=int, default=85)
    parser.add_argument("--min-words", type=int, default=50)
    parser.add_argument("--max-words", type=int, default=110)
    parser.add_argument("--wpm", type=int, default=160)
    parser.add_argument("--book-identity-pages", type=int, default=4)
    args = parser.parse_args()

    output_base = Path(args.output_dir)
    pdf_path = _discover_pdf(DEFAULT_INPUT_DIR, args.pdf)

    explicit_book_root = Path(args.book_root) if args.book_root else None
    if explicit_book_root:
        book_root = explicit_book_root
    else:
        # Prefer an existing completed initial-build folder. If none exists yet,
        # use /output as a temporary placeholder; InitialBuildStage will resolve
        # the canonical book_root after pdf_to_mp3.py creates it.
        book_root = _find_existing_book_root(output_base, pdf_path) or output_base

    options = PipelineOptions(
        pdf_path=pdf_path,
        output_base=output_base,
        book_root=book_root,
        quiet=args.quiet,
        force_initial=args.force_initial,
        force_chunks=args.force_chunks,
        force_audio=args.force_audio,
        force_book_identity=args.force_book_identity,
        force_front_matter=args.force_front_matter,
        force_mp3=args.force_mp3,
        no_mp3=args.no_mp3,
        no_metadata=args.no_metadata,
        mp3_bitrate=args.mp3_bitrate,
        voice=args.voice,
        speed=args.speed,
        target_words=args.target_words,
        min_words=args.min_words,
        max_words=args.max_words,
        wpm=args.wpm,
        book_identity_pages=args.book_identity_pages,
    )

    run_pipeline(options)


if __name__ == "__main__":
    main()
