import json
import re


_MARKER_PATTERNS = [
    # Footnote marker by itself: 1, 2, 3, etc.
    re.compile(r"^\d{1,3}$"),

    # Standalone citation year: 1968, 1982, 2008, etc.
    re.compile(r"^(?:18|19|20)\d{2}$"),

    # Figure/reference debris: 1.1 1988 2008, 2.3 1999, etc.
    re.compile(r"^\d+(?:\.\d+)+(?:\s+(?:18|19|20)\d{2})+$"),

    # Multiple standalone years: 1988 2008
    re.compile(r"^(?:(?:18|19|20)\d{2})(?:\s+(?:18|19|20)\d{2})+$"),

    # OCR punctuation fragments / extraction debris
    re.compile(r"^[=\-–—_\s{}\[\]()]+$"),
]


def clean_intro_title(title: str) -> str:
    return title.strip()


def remove_duplicate_chapter_heading(body: str, chapter_title: str) -> str:
    body = body.strip()

    if chapter_title.strip():
        # Removes repeated first-line chapter heading if present
        pattern = re.escape(chapter_title.strip())
        body = re.sub(rf"^{pattern}\s*", "", body, flags=re.I)

    # Removes "CHAPTER 1 Computers as Creative Tools" style heading from body
    body = re.sub(
        r"^CHAPTER\s+\d+\s+[A-Z][A-Za-z0-9 ,:\-–—]+?\s+",
        "",
        body,
        flags=re.I,
    )

    return body.strip()


def is_standalone_marker(text: str) -> bool:
    """
    Detects tiny standalone OCR/PDF extraction markers that should not be narrated.

    Important: this only runs on isolated lines / isolated paragraphs. It does not
    remove numbers or years inside real sentences.
    """
    stripped = re.sub(r"\s+", " ", text.strip())

    if not stripped:
        return True

    return any(pattern.fullmatch(stripped) for pattern in _MARKER_PATTERNS)


def remove_standalone_marker_lines(text: str) -> str:
    """
    Final export safety filter.

    This catches isolated markers that slipped through earlier layout stages, such as:
        2
        1968
        1982
        1.1 1988 2008

    It keeps those values when they are part of actual prose.
    """
    # Work paragraph by paragraph so we can preserve intentional paragraph breaks.
    paragraphs = re.split(r"\n\s*\n", text.strip())
    cleaned_paragraphs = []

    for paragraph in paragraphs:
        lines = paragraph.splitlines()
        kept_lines = []

        for line in lines:
            if is_standalone_marker(line):
                continue
            kept_lines.append(line.rstrip())

        cleaned = "\n".join(kept_lines).strip()

        if not cleaned:
            continue

        # If the whole paragraph collapsed to a marker, skip it.
        if is_standalone_marker(cleaned):
            continue

        cleaned_paragraphs.append(cleaned)

    output = "\n\n".join(cleaned_paragraphs)

    # Collapse excessive vertical whitespace caused by removed marker paragraphs.
    output = re.sub(r"\n{3,}", "\n\n", output)

    return output.strip()


def write_narration_files(manifest, chapters_dir, narration_dir):
    narration_dir.mkdir(exist_ok=True)

    written = []

    for chapter in manifest["chapters"]:
        chapter_id = chapter["id"]

        chapter_files = sorted(chapters_dir.glob(f"chapter_{chapter_id:03d}_*.json"))

        if not chapter_files:
            continue

        with open(chapter_files[0], "r", encoding="utf-8") as f:
            chapter_data = json.load(f)

        intro = clean_intro_title(chapter_data.get("title", ""))
        body = chapter_data.get("speech_text", "")
        body = remove_duplicate_chapter_heading(body, intro)
        body = remove_standalone_marker_lines(body)

        narration_text = f"{intro}\n\n{body}".strip()
        narration_text = remove_standalone_marker_lines(narration_text)

        filename = f"narration_{chapter_id:03d}.txt"
        path = narration_dir / filename

        with open(path, "w", encoding="utf-8") as f:
            f.write(narration_text)

        written.append(str(path))

    return written
