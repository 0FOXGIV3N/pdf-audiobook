from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from runtime_info import print_startup_banner


@dataclass
class BootstrapContext:
    """Shared startup context for command-line entry points.

    The bootstrap layer keeps runtime diagnostics, output-root inference, and
    future startup checks in one place so individual scripts do not each need
    their own banner/status setup logic.
    """

    command: str
    pdf_path: Optional[Path]
    output_root: Optional[Path]
    banner_printed: bool = False


def infer_output_root(*paths: str | Path | None) -> Optional[Path]:
    """Best-effort inference for output/<BookName> from common project paths.

    Examples:
    - /output/Book/chunks/chapter_006 -> /output/Book
    - /output/Book/wav/chapter_006 -> /output/Book
    - /output/Book/chapters_audio/chapter_006.wav -> /output/Book
    - /output/Book/layout.json -> /output/Book
    """
    marker_names = {
        "chapters",
        "narration",
        "narration_raw",
        "chunks",
        "wav",
        "chapters_audio",
        "reports",
        "books",
    }

    for value in paths:
        if value is None:
            continue
        path = Path(value)
        parts = path.parts

        for index, part in enumerate(parts):
            if part in marker_names and index > 0:
                return Path(*parts[:index])

        # Common direct files under the book root.
        if path.name in {"layout.json", "book.json", "manifest.json"}:
            return path.parent

        # A path like /output/BookName.
        if len(parts) >= 3 and parts[-2] == "output":
            return path

    return None


def bootstrap_command(
    command: str,
    pdf_path: str | Path | None = None,
    output_root: str | Path | None = None,
    *related_paths: str | Path | None,
    show_banner: bool = True,
) -> BootstrapContext:
    """Run shared startup behavior for CLI scripts.

    This currently prints the runtime banner. Future startup checks should be
    added here rather than duplicated across scripts.
    """
    pdf = Path(pdf_path) if pdf_path else None
    root = Path(output_root) if output_root else infer_output_root(*related_paths)

    banner_printed = False
    if show_banner:
        print_startup_banner(pdf_path=pdf, output_dir=root)
        banner_printed = True

    return BootstrapContext(
        command=command,
        pdf_path=pdf,
        output_root=root,
        banner_printed=banner_printed,
    )
