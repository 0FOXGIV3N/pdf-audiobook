import json
import re

from speech_cleaner import build_speech_text_from_elements


def safe_filename(text):
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"\s+", "_", text.strip())
    return text[:80] or "Untitled"


def write_chapter_files(book, manifest, chapters_dir):
    written = []

    for chapter in manifest["chapters"]:
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

    return written
