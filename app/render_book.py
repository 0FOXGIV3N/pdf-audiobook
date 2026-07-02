from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from bootstrap import bootstrap_command
from pipeline_manager import PipelineManager, StageResult
from production_manifest import update_production_manifest
from book_identity import extract_book_identity
from front_matter import default_front_matter_wav, render_front_matter
from publishers.mp3 import MP3Publisher
from metadata_writer import write_mp3_metadata
from render_book_audio import render_book_audio
from render_chapter import render_chapter


@dataclass
class BookRenderOptions:
    book_root: Path
    voice: Optional[str] = None
    speed: Optional[float] = None
    force: bool = False
    stitch_only: bool = False
    gap_seconds: float = 0.0
    no_stitch: bool = False
    no_book_stitch: bool = False
    chapter_gap_seconds: float = 0.5
    book_output_wav: Optional[Path] = None
    no_mp3: bool = False
    mp3_bitrate: str = "192k"
    mp3_output: Optional[Path] = None
    force_mp3: bool = False
    no_metadata: bool = False
    metadata_genre: str = "Audiobook"
    metadata_year: Optional[str] = None
    metadata_comment: Optional[str] = None
    no_book_identity: bool = False
    force_book_identity: bool = False
    book_identity_pages: int = 4
    source_pdf: Optional[Path] = None
    no_front_matter: bool = False
    force_front_matter: bool = False
    front_matter_wav: Optional[Path] = None
    quiet: bool = False
    chapters: Optional[List[int]] = None
    no_manifest: bool = False


class ChapterAudioStage:
    """Render and stitch all chapter audio files for an existing book output folder."""

    name = "Chapter Audio Rendering"

    def __init__(self, options: BookRenderOptions):
        self.options = options
        self.book_root = options.book_root
        self.chunks_root = self.book_root / "chunks"
        self.wav_root = self.book_root / "wav"
        self.chapters_audio_root = self.book_root / "chapters_audio"
        self.reports_root = self.book_root / "reports"

    def should_run(self) -> bool:
        return True

    def run(self) -> StageResult:
        start = time.time()

        if not self.book_root.exists():
            raise FileNotFoundError(f"Book output folder not found: {self.book_root}")
        if not self.chunks_root.exists():
            raise FileNotFoundError(f"Chunks folder not found: {self.chunks_root}")

        chapter_dirs = _chapter_chunk_dirs(self.chunks_root)
        if self.options.chapters:
            wanted = set(self.options.chapters)
            chapter_dirs = [d for d in chapter_dirs if _chapter_number(d) in wanted]

        if not chapter_dirs:
            raise FileNotFoundError(f"No chapter chunk folders found in: {self.chunks_root}")

        self.wav_root.mkdir(parents=True, exist_ok=True)
        self.chapters_audio_root.mkdir(parents=True, exist_ok=True)
        self.reports_root.mkdir(parents=True, exist_ok=True)

        chapter_reports: List[Dict[str, Any]] = []
        rendered_chunks = 0
        skipped_chunks = 0
        total_chunks = 0
        total_audio_seconds = 0.0

        _print("\n============================================================", self.options.quiet)
        _print("PDF Audiobook Generator", self.options.quiet)
        _print("Phase 5 — Metadata Tags v1.0", self.options.quiet)
        _print("============================================================", self.options.quiet)
        _print(f"Book root:        {self.book_root}", self.options.quiet)
        _print(f"Chapters found:   {len(chapter_dirs)}", self.options.quiet)
        _print(f"Mode:             {_mode_label(self.options)}", self.options.quiet)
        _print("============================================================\n", self.options.quiet)

        for index, chapter_dir in enumerate(chapter_dirs, start=1):
            chapter_num = _chapter_number(chapter_dir)
            chapter_name = f"chapter_{chapter_num:03d}"
            chapter_wav_dir = self.wav_root / chapter_name
            chapter_output_wav = self.chapters_audio_root / f"{chapter_name}.wav"

            _print("------------------------------------------------------------", self.options.quiet)
            _print(f"[{index}/{len(chapter_dirs)}] {chapter_name}", self.options.quiet)
            _print("------------------------------------------------------------", self.options.quiet)

            report = render_chapter(
                chapter_chunks_dir=chapter_dir,
                chapter_wav_dir=chapter_wav_dir,
                chapter_output_wav=chapter_output_wav,
                voice=self.options.voice,
                speed=self.options.speed,
                force=self.options.force,
                stitch_only=self.options.stitch_only,
                gap_seconds=self.options.gap_seconds,
                no_stitch=self.options.no_stitch,
                quiet=self.options.quiet,
                status_root=self.book_root,
            )

            chapter_reports.append(report)
            total_chunks += int(report.get("chunks", 0))
            rendered_chunks += int(report.get("rendered", 0))
            skipped_chunks += int(report.get("skipped_existing", 0))
            stitch = report.get("stitch") or {}
            total_audio_seconds += float(stitch.get("duration_seconds", 0.0) or 0.0)

            _print(
                f"\nChapter complete: {chapter_name} | "
                f"rendered {report.get('rendered', 0)} | "
                f"reused {report.get('skipped_existing', 0)} | "
                f"audio {_format_duration((report.get('stitch') or {}).get('duration_seconds'))}",
                self.options.quiet,
            )

        elapsed = round(time.time() - start, 2)
        summary = {
            "book_root": str(self.book_root),
            "chunks_root": str(self.chunks_root),
            "wav_root": str(self.wav_root),
            "chapters_audio_root": str(self.chapters_audio_root),
            "chapters": len(chapter_dirs),
            "chunks_total": total_chunks,
            "chunks_rendered": rendered_chunks,
            "chunks_reused": skipped_chunks,
            "audio_seconds": round(total_audio_seconds, 2),
            "audio_duration": _format_duration(total_audio_seconds),
            "elapsed_seconds": elapsed,
            "elapsed_display": _format_duration(elapsed),
            "force": bool(self.options.force),
            "stitch_only": bool(self.options.stitch_only),
            "no_stitch": bool(self.options.no_stitch),
            "gap_seconds": float(self.options.gap_seconds),
            "voice": self.options.voice,
            "speed": self.options.speed,
            "chapter_filter": self.options.chapters,
            "chapter_reports": chapter_reports,
        }

        report_path = self.reports_root / "render_book.json"
        report_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        summary["report_file"] = str(report_path)

        _print("\n============================================================", self.options.quiet)
        _print("Chapter Audio Stage Complete", self.options.quiet)
        _print("============================================================", self.options.quiet)
        _print(f"Chapters processed: {summary['chapters']}", self.options.quiet)
        _print(f"Chunks rendered:    {summary['chunks_rendered']}", self.options.quiet)
        _print(f"Chunks reused:      {summary['chunks_reused']}", self.options.quiet)
        _print(f"Audio duration:     {summary['audio_duration']}", self.options.quiet)
        _print(f"Elapsed:            {summary['elapsed_display']}", self.options.quiet)
        _print(f"Report:             {report_path}", self.options.quiet)
        _print("============================================================\n", self.options.quiet)

        return StageResult(
            name=self.name,
            status="complete",
            skipped=False,
            elapsed_seconds=elapsed,
            message="Chapter audio rendering complete",
            data=summary,
        )


class BookIdentityStage:
    """Extract title/subtitle/author for spoken front matter and manifest."""

    name = "Book Identity"

    def __init__(self, options: BookRenderOptions):
        self.options = options
        self.book_root = options.book_root

    def should_run(self) -> bool:
        return (not self.options.no_book_identity) and self.options.chapters is None

    def run(self) -> StageResult:
        start = time.time()
        identity = extract_book_identity(
            book_root=self.book_root,
            pdf_path=self.options.source_pdf,
            max_pages=self.options.book_identity_pages,
            force=self.options.force_book_identity,
            quiet=self.options.quiet,
        )
        elapsed = round(time.time() - start, 2)
        return StageResult(
            name=self.name,
            status="complete",
            skipped=False,
            elapsed_seconds=elapsed,
            message="Book identity extracted",
            data=identity,
        )


class FrontMatterStage:
    """Generate and render the spoken book opening before Chapter 1."""

    name = "Front Matter"

    def __init__(self, options: BookRenderOptions):
        self.options = options
        self.book_root = options.book_root

    def should_run(self) -> bool:
        # Partial chapter renders are development outputs and should not include
        # the full audiobook opening unless explicitly handled later.
        return (not self.options.no_front_matter) and self.options.chapters is None

    def run(self) -> StageResult:
        start = time.time()
        output_wav = self.options.front_matter_wav or default_front_matter_wav(self.book_root)

        report = render_front_matter(
            book_root=self.book_root,
            output_wav=output_wav,
            voice=self.options.voice,
            speed=self.options.speed,
            force=self.options.force_front_matter,
            quiet=self.options.quiet,
        )

        elapsed = round(time.time() - start, 2)
        return StageResult(
            name=self.name,
            status="complete",
            skipped=report.get("status") == "skipped_existing",
            elapsed_seconds=elapsed,
            message="Front matter ready",
            data=report,
        )


class BookAudioStage:
    """Stitch completed chapter WAV files into one full-book WAV deliverable."""

    name = "Book Audio Stitching"

    def __init__(self, options: BookRenderOptions):
        self.options = options
        self.book_root = options.book_root
        self.chapters_audio_root = self.book_root / "chapters_audio"
        self.books_root = self.book_root / "books"

    def should_run(self) -> bool:
        return not self.options.no_book_stitch

    def run(self) -> StageResult:
        start = time.time()
        output_wav = self.options.book_output_wav or _default_book_wav_path(self.options)

        front_matter_wav = None
        if (not self.options.no_front_matter) and self.options.chapters is None:
            candidate = self.options.front_matter_wav or default_front_matter_wav(self.book_root)
            if candidate.exists():
                front_matter_wav = candidate

        report = render_book_audio(
            chapters_audio_dir=self.chapters_audio_root,
            output_wav=output_wav,
            chapter_gap_seconds=self.options.chapter_gap_seconds,
            chapters=self.options.chapters,
            front_matter_wav=front_matter_wav,
            quiet=self.options.quiet,
        )

        elapsed = round(time.time() - start, 2)
        return StageResult(
            name=self.name,
            status="complete",
            skipped=False,
            elapsed_seconds=elapsed,
            message="Book audio stitching complete",
            data=report,
        )


class MP3ExportStage:
    """Publish the full-book WAV master as an MP3 deliverable."""

    name = "MP3 Export"

    def __init__(self, options: BookRenderOptions):
        self.options = options
        self.book_root = options.book_root

    def should_run(self) -> bool:
        return not self.options.no_mp3

    def run(self) -> StageResult:
        start = time.time()
        source_wav = self.options.book_output_wav or _default_book_wav_path(self.options)
        if not source_wav.exists():
            source_wav = _find_latest_book_wav(self.options)

        output_mp3 = self.options.mp3_output or _default_mp3_path(self.options, source_wav)
        publisher = MP3Publisher(bitrate=self.options.mp3_bitrate)
        report = publisher.publish(
            source_file=source_wav,
            output_file=output_mp3,
            force=self.options.force_mp3,
            quiet=self.options.quiet,
        )

        elapsed = round(time.time() - start, 2)
        return StageResult(
            name=self.name,
            status="complete",
            skipped=report.get("status") == "skipped_existing",
            elapsed_seconds=elapsed,
            message="MP3 export complete" if report.get("status") != "skipped_existing" else "MP3 export skipped; existing file reused",
            data=report,
        )



class MetadataTagsStage:
    """Write audiobook metadata tags into the MP3 deliverable."""

    name = "Metadata Tags"

    def __init__(self, options: BookRenderOptions):
        self.options = options
        self.book_root = options.book_root

    def should_run(self) -> bool:
        return (not self.options.no_metadata) and (not self.options.no_mp3) and self.options.chapters is None

    def run(self) -> StageResult:
        start = time.time()
        source_wav = self.options.book_output_wav or _default_book_wav_path(self.options)
        if source_wav.exists():
            default_mp3 = self.options.mp3_output or _default_mp3_path(self.options, source_wav)
        else:
            latest_wav = _find_latest_book_wav(self.options)
            default_mp3 = self.options.mp3_output or _default_mp3_path(self.options, latest_wav)

        if not default_mp3.exists():
            candidates = sorted((self.book_root / "books").glob("*.mp3"))
            if not candidates:
                raise FileNotFoundError(
                    f"No MP3 file found for metadata tagging in {self.book_root / 'books'}."
                )
            default_mp3 = candidates[-1]

        report = write_mp3_metadata(
            book_root=self.book_root,
            mp3_file=default_mp3,
            genre=self.options.metadata_genre,
            year=self.options.metadata_year,
            comment=self.options.metadata_comment,
            quiet=self.options.quiet,
        )

        elapsed = round(time.time() - start, 2)
        return StageResult(
            name=self.name,
            status="complete",
            skipped=False,
            elapsed_seconds=elapsed,
            message="MP3 metadata tags written",
            data=report,
        )


class ProductionManifestStage:
    """Create/update the production manifest after deliverables exist."""

    name = "Production Manifest"

    def __init__(self, options: BookRenderOptions):
        self.options = options
        self.book_root = options.book_root

    def should_run(self) -> bool:
        return not self.options.no_manifest

    def run(self) -> StageResult:
        start = time.time()
        manifest = update_production_manifest(
            book_root=self.book_root,
            stage_results=None,
            quiet=self.options.quiet,
        )
        elapsed = round(time.time() - start, 2)
        return StageResult(
            name=self.name,
            status="complete",
            skipped=False,
            elapsed_seconds=elapsed,
            message="Production manifest updated",
            data=manifest,
        )


def render_book(options: BookRenderOptions) -> Dict[str, Any]:
    manager = PipelineManager(
        output_root=options.book_root,
        phase="Phase 5 — Metadata Tags",
        quiet=options.quiet,
    )
    stages = [ChapterAudioStage(options)]
    if (not options.no_book_identity) and options.chapters is None:
        stages.append(BookIdentityStage(options))
    if (not options.no_front_matter) and options.chapters is None:
        stages.append(FrontMatterStage(options))
    if not options.no_book_stitch:
        stages.append(BookAudioStage(options))
    if not options.no_mp3:
        stages.append(MP3ExportStage(options))
    if (not options.no_metadata) and (not options.no_mp3) and options.chapters is None:
        stages.append(MetadataTagsStage(options))
    if not options.no_manifest:
        stages.append(ProductionManifestStage(options))

    results = manager.run(
        stages=stages,
        message="Book render started",
    )

    # Refresh the production manifest with final stage results so it contains
    # the complete run history, including publishing and the manifest stage.
    if not options.no_manifest:
        update_production_manifest(
            book_root=options.book_root,
            stage_results=[r.to_dict() for r in results],
            quiet=True,
        )

    return {
        "book_root": str(options.book_root),
        "results": [r.to_dict() for r in results],
    }


def _chapter_chunk_dirs(chunks_root: Path) -> List[Path]:
    dirs = [p for p in chunks_root.iterdir() if p.is_dir() and re.match(r"^chapter_\d+$", p.name)]
    return sorted(dirs, key=_chapter_number)


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
            start = int(start_text)
            end = int(end_text)
            chapters.extend(range(start, end + 1))
        else:
            chapters.append(int(part))
    return sorted(set(chapters))


def _chapter_filter_label(chapters: Optional[List[int]]) -> str:
    if not chapters:
        return "full"
    if len(chapters) == 1:
        return f"chapter_{chapters[0]:03d}"
    return "chapters_" + "_".join(f"{chapter:03d}" for chapter in chapters[:6]) + ("_plus" if len(chapters) > 6 else "")


def _default_book_wav_path(options: BookRenderOptions) -> Path:
    books_root = options.book_root / "books"
    label = _chapter_filter_label(options.chapters)
    if label == "full":
        filename = f"{options.book_root.name}_full.wav"
    else:
        filename = f"{options.book_root.name}_{label}.wav"
    return books_root / filename


def _find_latest_book_wav(options: BookRenderOptions) -> Path:
    books_root = options.book_root / "books"
    label = _chapter_filter_label(options.chapters)
    if label == "full":
        candidates = sorted(books_root.glob("*_full.wav"))
    else:
        candidates = sorted(books_root.glob(f"*_{label}.wav"))
    if not candidates:
        candidates = sorted(books_root.glob("*.wav"))
    if not candidates:
        raise FileNotFoundError(
            f"No source book WAV found in {books_root}. Run without --no-book-stitch first, or pass --book-output-wav."
        )
    return candidates[-1]


def _default_mp3_path(options: BookRenderOptions, source_wav: Path) -> Path:
    stem = source_wav.stem
    if stem.endswith("_full"):
        stem = stem[:-5]
    return source_wav.with_name(stem + ".mp3")


def _mode_label(options: BookRenderOptions) -> str:
    if options.force:
        return "force regenerate"
    if options.stitch_only:
        return "stitch only"
    if options.no_stitch:
        return "render chunks only"
    return "resume / reuse existing"


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
    parser = argparse.ArgumentParser(
        description="Render all chapters for an existing PDF Audiobook Generator book output folder."
    )
    parser.add_argument(
        "book_root",
        help="Path to output/<BookName> folder containing chunks/, e.g. /output/AI Revolution_DVG_2025",
    )
    parser.add_argument("--voice", default=None, help="Kokoro voice name, e.g. af_heart")
    parser.add_argument("--speed", type=float, default=None, help="Speech speed")
    parser.add_argument("--force", action="store_true", help="Regenerate existing chunk WAV files")
    parser.add_argument("--stitch-only", action="store_true", help="Only stitch existing chunk WAV files")
    parser.add_argument("--no-stitch", action="store_true", help="Render chunks but do not stitch chapter WAVs")
    parser.add_argument("--no-book-stitch", action="store_true", help="Skip final full-book WAV stitching")
    parser.add_argument("--no-mp3", action="store_true", help="Skip MP3 export")
    parser.add_argument("--force-mp3", action="store_true", help="Regenerate MP3 even if it already exists")
    parser.add_argument("--no-metadata", action="store_true", help="Skip MP3 metadata tagging")
    parser.add_argument("--metadata-genre", default="Audiobook", help="MP3 genre tag. Default: Audiobook")
    parser.add_argument("--metadata-year", default=None, help="Optional year/date tag")
    parser.add_argument("--metadata-comment", default=None, help="Optional MP3 comment/description tag")
    parser.add_argument("--no-book-identity", action="store_true", help="Skip automatic title/subtitle/author extraction")
    parser.add_argument("--force-book-identity", action="store_true", help="Re-extract book identity even if book_identity.json exists")
    parser.add_argument("--book-identity-pages", type=int, default=4, help="Number of first PDF pages to inspect for title/subtitle/author. Default: 4")
    parser.add_argument("--source-pdf", default=None, help="Optional explicit source PDF path for book identity extraction")
    parser.add_argument("--no-front-matter", action="store_true", help="Skip spoken title/subtitle/author front matter")
    parser.add_argument("--force-front-matter", action="store_true", help="Regenerate front matter WAV even if it already exists")
    parser.add_argument(
        "--front-matter-wav",
        default=None,
        help="Optional explicit output path for front_matter.wav.",
    )
    parser.add_argument("--quiet", action="store_true", help="Suppress progress output")
    parser.add_argument("--no-manifest", action="store_true", help="Skip production manifest update")
    parser.add_argument(
        "--gap-seconds",
        type=float,
        default=0.0,
        help="Optional silence inserted between chunk WAVs during chapter stitching. Default: 0.0",
    )
    parser.add_argument(
        "--chapter-gap-seconds",
        type=float,
        default=0.5,
        help="Silence inserted between chapter WAVs during full-book stitching. Default: 0.5",
    )
    parser.add_argument(
        "--book-output-wav",
        default=None,
        help="Optional explicit output path for the full-book WAV.",
    )
    parser.add_argument(
        "--mp3-output",
        default=None,
        help="Optional explicit output path for the MP3 deliverable.",
    )
    parser.add_argument(
        "--mp3-bitrate",
        default="192k",
        help="MP3 bitrate passed to FFmpeg/libmp3lame. Default: 192k",
    )
    parser.add_argument(
        "--chapters",
        default=None,
        help="Optional comma/range chapter filter, e.g. 1,2,6 or 1-3,6",
    )
    args = parser.parse_args()

    if args.stitch_only and args.no_stitch:
        print("Error: --stitch-only and --no-stitch cannot be used together.", file=sys.stderr)
        raise SystemExit(2)
    if args.no_book_stitch and args.book_output_wav is not None and not Path(args.book_output_wav).exists():
        print("Error: --no-book-stitch was used with a --book-output-wav that does not exist.", file=sys.stderr)
        raise SystemExit(2)

    book_root = Path(args.book_root)
    bootstrap_command(
        command="render_book",
        output_root=book_root,
        show_banner=not args.quiet,
    )

    options = BookRenderOptions(
        book_root=book_root,
        voice=args.voice,
        speed=args.speed,
        force=args.force,
        stitch_only=args.stitch_only,
        gap_seconds=args.gap_seconds,
        no_stitch=args.no_stitch,
        no_book_stitch=args.no_book_stitch,
        chapter_gap_seconds=args.chapter_gap_seconds,
        book_output_wav=Path(args.book_output_wav) if args.book_output_wav else None,
        no_mp3=args.no_mp3,
        mp3_bitrate=args.mp3_bitrate,
        mp3_output=Path(args.mp3_output) if args.mp3_output else None,
        force_mp3=args.force_mp3,
        no_metadata=args.no_metadata,
        metadata_genre=args.metadata_genre,
        metadata_year=args.metadata_year,
        metadata_comment=args.metadata_comment,
        no_book_identity=args.no_book_identity,
        force_book_identity=args.force_book_identity,
        book_identity_pages=args.book_identity_pages,
        source_pdf=Path(args.source_pdf) if args.source_pdf else None,
        no_front_matter=args.no_front_matter,
        force_front_matter=args.force_front_matter,
        front_matter_wav=Path(args.front_matter_wav) if args.front_matter_wav else None,
        quiet=args.quiet,
        chapters=_parse_chapters(args.chapters),
        no_manifest=args.no_manifest,
    )
    render_book(options)


if __name__ == "__main__":
    main()
