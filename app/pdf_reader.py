import os
import tempfile

import fitz

from cleaner import clean_text
from layout_engine import build_layout_json
from speech_cleaner import build_speech_text_from_elements


def safe_page_text(page, mode="text"):
    """Suppress noisy MuPDF parser warnings while preserving extraction output."""
    old_stderr = os.dup(2)
    tmp = tempfile.TemporaryFile(mode="w+b")
    try:
        os.dup2(tmp.fileno(), 2)
        result = page.get_text(mode)
        os.dup2(old_stderr, 2)
        return result
    finally:
        try:
            os.dup2(old_stderr, 2)
        except OSError:
            pass
        os.close(old_stderr)
        tmp.close()


def extract_pdf(pdf_path, layout_output_path=None):
    doc = fitz.open(pdf_path)

    layout = None
    if layout_output_path is not None:
        layout = build_layout_json(pdf_path, layout_output_path)

    book = {
        "source_pdf": pdf_path.name,
        "title": "",
        "author": "",
        "total_pages": len(doc),
        "pages": []
    }

    for index, page in enumerate(doc, start=1):
        raw_text = safe_page_text(page)
        elements = []

        if layout:
            layout_page = layout["pages"][index - 1]
            elements = layout_page.get("elements", [])
            speech = build_speech_text_from_elements(elements)
            cleaned = clean_text("\n\n".join(e.get("text", "") for e in elements))
        else:
            cleaned = clean_text(raw_text)
            speech = cleaned

        book["pages"].append({
            "page": index,
            "chapter": None,
            "word_count": len(speech.split()),
            "character_count": len(speech),
            "raw_text": raw_text,
            "clean_text": cleaned,
            "speech_text": speech,
            "narration_text": "",
            "layout_elements": elements,
        })

    return book
