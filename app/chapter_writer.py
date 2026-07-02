import json
import re

from speech_cleaner import build_speech_text_from_elements
from pipeline_status import PipelineStatus


def safe_filename(text):
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"\s+", "_", text.strip())
    return text[:80] or "Untitled"


def write_chapter_files(book, manifest, chapters_dir):
    written = []
    output_root = chapters_dir.parent
    status = PipelineStatus(output_root)
    chapters = manifest.get("chapters", [])

    status.start_stage(
        "Chapter JSON Writing",
        total=len(chapters),
        message="Writing chapter JSON files",
        extra={"chapters_dir": str(chapters_dir)},
    )

    for index, chapter in enumerate(chapters, start=1):
        chapter_id = chapter["id"]
        chapter_title = chapter.get("title", f"Chapter {chapter_id}")
        status.update(
            current=index - 1,
            total=len(chapters),
            item=f"chapter_{chapter_id:03d}",
            message=f"Preparing chapter {chapter_id}: {chapter_title}",
        )

        start = chapter["start_page"]
        end = chapter["end_page"]

        pages = [page for page in book["pages"] if start <= page["page"] <= end]

        page_speech_blocks = []
        chapter_elements = []

        for page in pages:
            elements = page.get("layout_elements", [])
            chapter_elements.extend(elements)

            if elements:
                speech = build_speech_text_from_elements(elements)
            else:
                speech = page.get("speech_text", "")

            if speech:
                # Page boundary is intentionally preserved so the last paragraph of one page
                # cannot merge with the first paragraph of the next page.
                page_speech_blocks.append(speech.strip())

        chapter_data = {
            **chapter,
            "pages": [p["page"] for p in pages],
            "elements": chapter_elements,
            "speech_text": "\n\n".join(page_speech_blocks).strip(),
            "narration_text": ""
        }

        filename = f"chapter_{chapter['id']:03d}_{safe_filename(chapter['title'])}.json"
        path = chapters_dir / filename

        with open(path, "w", encoding="utf-8") as f:
            json.dump(chapter_data, f, indent=2, ensure_ascii=False)

        written.append(str(path))
        status.update(
            current=index,
            total=len(chapters),
            item=f"chapter_{chapter_id:03d}",
            message=f"Wrote {filename}",
            extra={"last_chapter_file": str(path)},
        )

    status.finish_stage(
        message="Chapter JSON writing complete",
        extra={"chapter_files_written": len(written)},
    )
    return written
