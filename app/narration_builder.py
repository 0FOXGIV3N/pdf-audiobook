import json
import re

from narration_engine import NarrationEngine, build_postprocess_report
from element_cleaner import ElementCleaner, build_element_cleanup_report
from pipeline_status import PipelineStatus


def clean_intro_title(title: str) -> str:
    return (title or "").strip()


def _norm_key(text: str) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip()).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def ensure_chapter_title_prefix(text: str, chapter_title: str) -> str:
    """Force the manifest/chapter metadata title to be the first spoken block.

    This protects the real chapter title from element-level duplicate-heading
    cleanup. It also prevents the title from disappearing when the page's
    visual heading is removed as a duplicate.
    """
    text = (text or "").strip()
    chapter_title = clean_intro_title(chapter_title)
    if not chapter_title:
        return text

    first_block = re.split(r"\n\s*\n", text, maxsplit=1)[0].strip() if text else ""
    if _norm_key(first_block) == _norm_key(chapter_title):
        return text

    # If the title appears later as a standalone block, remove that duplicate
    # before prefixing it cleanly at the top.
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
    blocks = [b for b in blocks if _norm_key(b) != _norm_key(chapter_title)]
    return (chapter_title + "\n\n" + "\n\n".join(blocks)).strip()


def _ends_with_sentence_punctuation(text: str) -> bool:
    return bool(re.search(r"[.!?]['\")\]]?$", (text or "").strip()))


def _add_terminal_period(text: str) -> str:
    text = (text or "").strip()
    if text and not _ends_with_sentence_punctuation(text):
        return text + "."
    return text


def _looks_like_intro_subtitle(block: str) -> bool:
    """Conservative subtitle detector for the opening of a chapter.

    This is intentionally limited to the second spoken block after the
    chapter title has already been prefixed. It is not a general heading
    detector and it does not change parser output.
    """
    block = re.sub(r"\s+", " ", (block or "").strip())
    if not block:
        return False

    words = block.split()
    if len(words) > 18:
        return False

    if _ends_with_sentence_punctuation(block):
        return True

    # Avoid treating normal body openings as subtitles.
    body_starters = {
        "a", "an", "as", "at", "by", "for", "from", "if", "in",
        "it", "its", "on", "once", "the", "these", "this", "to",
        "we", "when", "while", "with"
    }
    first = re.sub(r"[^A-Za-z]", "", words[0]).lower() if words else ""
    if first in body_starters and len(words) > 8:
        return False

    alpha_words = [w for w in words if re.search(r"[A-Za-z]", w)]
    if not alpha_words:
        return False

    capitalized = sum(1 for w in alpha_words if w[:1].isupper())
    return (capitalized / max(1, len(alpha_words))) >= 0.45


def punctuate_chapter_opening(text: str, chapter_title: str) -> str:
    """Add TTS-friendly sentence punctuation to chapter opening blocks.

    Only affects the narration presentation text written to narration/.
    It does not modify parser output, chapter JSON elements, or extracted text.

    Rules:
    - First block is the chapter title and receives terminal punctuation.
    - Second block receives terminal punctuation only if it looks like a
      short subtitle/heading.
    - Body text is left alone.
    """
    text = (text or "").strip()
    if not text:
        return text

    blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
    if not blocks:
        return text

    chapter_title = clean_intro_title(chapter_title)

    # The title should already be first because ensure_chapter_title_prefix() ran,
    # but keep this guarded so the function is safe for legacy chapters.
    if chapter_title and _norm_key(blocks[0]) == _norm_key(chapter_title):
        blocks[0] = _add_terminal_period(blocks[0])
    elif re.match(r"^chapter\s+\d+\b", blocks[0], re.I):
        blocks[0] = _add_terminal_period(blocks[0])

    if len(blocks) > 1 and _looks_like_intro_subtitle(blocks[1]):
        blocks[1] = _add_terminal_period(blocks[1])

    return "\n\n".join(blocks).strip()


def final_presentation_cleanup(text: str) -> str:
    text = text or ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def remove_duplicate_chapter_heading(body: str, chapter_title: str) -> str:
    """Legacy fallback for chapters without structured elements."""
    body = (body or "").strip()

    if chapter_title.strip():
        pattern = re.escape(chapter_title.strip())
        body = re.sub(rf"^{pattern}\s*", "", body, flags=re.I)

    body = re.sub(
        r"^CHAPTER\s+\d+\s+[A-Z][A-Za-z0-9 ,:\-–—]+?\s+",
        "",
        body,
        flags=re.I,
    )

    return body.strip()


def write_narration_files(manifest, chapters_dir, narration_dir):
    """
    Phase 3 narration export.

    Writes two versions:
    - narration_raw/: readable structured narration before cleanup
    - narration/: final narration after Narration Engine cleanup

    Also writes:
    - postprocess_report.txt
    """
    narration_dir.mkdir(exist_ok=True)

    output_root = narration_dir.parent
    status = PipelineStatus(output_root)
    raw_dir = output_root / "narration_raw"
    raw_dir.mkdir(exist_ok=True)

    cleaner = ElementCleaner()
    engine = NarrationEngine()
    cleanup_stats_items = []
    stats_items = []
    written = []

    chapters = manifest.get("chapters", [])
    status.start_stage(
        "Narration Generation",
        total=len(chapters),
        message="Writing narration TXT files",
        extra={"narration_dir": str(narration_dir)},
    )

    for chapter_index, chapter in enumerate(chapters, start=1):
        chapter_id = chapter["id"]
        chapter_title = clean_intro_title(chapter.get("title", ""))
        status.update(
            current=chapter_index - 1,
            total=len(chapters),
            item=f"chapter_{chapter_id:03d}",
            message=f"Building narration for chapter {chapter_id}: {chapter_title}",
        )

        chapter_files = sorted(chapters_dir.glob(f"chapter_{chapter_id:03d}_*.json"))
        if not chapter_files:
            continue

        with open(chapter_files[0], "r", encoding="utf-8") as f:
            chapter_data = json.load(f)

        intro = clean_intro_title(chapter_data.get("title") or chapter_title)
        elements = chapter_data.get("elements") or []

        if elements:
            cleaned_elements, cleanup_stats = cleaner.clean_chapter_elements(
                elements,
                chapter_id=chapter_id,
                chapter_title=intro,
            )
            cleanup_stats_items.append(cleanup_stats)

            raw_narration_text = engine.render_raw_chapter_elements(elements, intro)
            final_narration_text, stats = engine.process_chapter_elements(
                cleaned_elements,
                chapter_id=chapter_id,
                chapter_title=intro,
            )

            raw_narration_text = ensure_chapter_title_prefix(raw_narration_text, intro)
            final_narration_text = ensure_chapter_title_prefix(final_narration_text, intro)
        else:
            body = chapter_data.get("speech_text", "")
            body = remove_duplicate_chapter_heading(body, intro)
            raw_narration_text = f"{intro}\n\n{body}".strip()
            final_narration_text, stats = engine.process_chapter_text(
                raw_narration_text,
                chapter_id=chapter_id,
                chapter_title=intro,
            )

            raw_narration_text = ensure_chapter_title_prefix(raw_narration_text, intro)
            final_narration_text = ensure_chapter_title_prefix(final_narration_text, intro)

        raw_narration_text = punctuate_chapter_opening(raw_narration_text, intro)
        final_narration_text = punctuate_chapter_opening(final_narration_text, intro)

        stats.raw_characters = len(raw_narration_text)
        stats_items.append(stats)

        filename = f"narration_{chapter_id:03d}.txt"
        raw_path = raw_dir / filename
        final_path = narration_dir / filename

        raw_narration_text = final_presentation_cleanup(raw_narration_text)
        final_narration_text = final_presentation_cleanup(final_narration_text)

        with open(raw_path, "w", encoding="utf-8") as f:
            f.write(raw_narration_text)

        with open(final_path, "w", encoding="utf-8") as f:
            f.write(final_narration_text)

        written.append(str(final_path))
        status.update(
            current=chapter_index,
            total=len(chapters),
            item=f"chapter_{chapter_id:03d}",
            message=f"Wrote {filename}",
            extra={"last_narration_file": str(final_path)},
        )

    cleanup_report_path = output_root / "element_cleanup_report.txt"
    with open(cleanup_report_path, "w", encoding="utf-8") as f:
        f.write(build_element_cleanup_report(cleanup_stats_items))

    report_path = output_root / "postprocess_report.txt"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(build_postprocess_report(stats_items))

    status.finish_stage(
        message="Narration generation complete",
        extra={"narration_files_written": len(written)},
    )
    return written
