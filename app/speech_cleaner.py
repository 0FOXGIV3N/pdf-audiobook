import re


SKIP_TYPES = {
    "header",
    "header_candidate",
    "footer",
    "footer_candidate",
    "page_number",
    "url",
    "doi",
    "extraction_artifact",
    "duplicate_marker",
    "duplicate_heading_fragment",
}


def normalize_for_speech(text: str) -> str:
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def compact_marker_text(text: str) -> str:
    """Normalize a tiny standalone marker for matching only."""
    text = normalize_for_speech(text or "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def is_standalone_reference_marker(text: str) -> bool:
    """
    True only for marker-only elements/lines.

    Examples skipped:
    - 2
    - 1968
    - 1982
    - 1.1 1988 2008

    Real sentences containing these numbers are not skipped.
    """
    text = compact_marker_text(text)
    if not text:
        return False

    # Single footnote/page/citation marker.
    if re.fullmatch(r"\d{1,3}", text):
        return True

    # One or more standalone citation years.
    if re.fullmatch(r"(?:1[5-9]\d{2}|20\d{2})(?:\s+(?:1[5-9]\d{2}|20\d{2})){0,4}", text):
        return True

    # Figure/table/section marker plus years: "1.1 1988 2008".
    if re.fullmatch(r"\d+(?:\.\d+){1,3}(?:\s+(?:1[5-9]\d{2}|20\d{2})){1,5}", text):
        return True

    # Very small numeric-only fragments.
    if not any(ch.isalpha() for ch in text) and len(text) <= 24:
        if re.fullmatch(r"[\d\s\.\,;:()\-–—]+", text):
            return True

    return False


def remove_standalone_marker_lines(text: str) -> str:
    """
    Final safety pass: remove marker-only paragraphs/lines even if they slipped
    through as narratable OCR text.
    """
    text = normalize_for_speech(text or "")
    if not text:
        return ""

    cleaned_lines = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if is_standalone_reference_marker(line):
            continue
        cleaned_lines.append(raw_line)

    cleaned = "\n".join(cleaned_lines)

    # Remove marker-only paragraphs after line cleanup.
    paragraphs = re.split(r"\n\s*\n", cleaned)
    kept = []
    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if is_standalone_reference_marker(paragraph):
            continue
        kept.append(paragraph)

    return "\n\n".join(kept).strip()


def should_narrate_element(element: dict) -> bool:
    if element.get("narrate") is False:
        return False
    if element.get("type") in SKIP_TYPES:
        return False

    text = element.get("normalized_text") or element.get("text", "")
    text = remove_standalone_marker_lines(text)

    if not text:
        return False
    if is_standalone_reference_marker(text):
        return False
    return True


def element_to_speech(element: dict) -> str:
    text = element.get("normalized_text") or element.get("text", "")
    text = remove_standalone_marker_lines(text)
    if not text:
        return ""

    if element.get("type") == "footnote":
        # Avoid "Footnote. Footnote. 2 ..." if already formatted upstream.
        if re.match(r"^Footnote\.\s*", text, re.I):
            return text
        return f"Footnote. {text}"

    return text


def build_speech_text_from_elements(elements: list) -> str:
    parts = []
    for element in elements:
        if should_narrate_element(element):
            speech = element_to_speech(element)
            speech = remove_standalone_marker_lines(speech)
            if speech:
                parts.append(speech)

    final_text = "\n\n".join(parts).strip()
    return remove_standalone_marker_lines(final_text)


# Legacy compatibility for old imports.
def remove_page_noise_lines(text: str) -> str:
    return remove_standalone_marker_lines(text)


def build_speech_text(clean_text: str) -> str:
    return remove_standalone_marker_lines(clean_text)
