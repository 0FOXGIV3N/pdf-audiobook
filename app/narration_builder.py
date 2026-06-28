import json
import re

from narration_engine import NarrationEngine, build_postprocess_report
from element_cleaner import ElementCleaner, build_element_cleanup_report


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
    raw_dir = output_root / "narration_raw"
    raw_dir.mkdir(exist_ok=True)

    cleaner = ElementCleaner()
    engine = NarrationEngine()
    cleanup_stats_items = []
    stats_items = []
    written = []

    for chapter in manifest["chapters"]:
        chapter_id = chapter["id"]
        chapter_title = clean_intro_title(chapter.get("title", ""))

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

    cleanup_report_path = output_root / "element_cleanup_report.txt"
    with open(cleanup_report_path, "w", encoding="utf-8") as f:
        f.write(build_element_cleanup_report(cleanup_stats_items))

    report_path = output_root / "postprocess_report.txt"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(build_postprocess_report(stats_items))

    return written
