import re
from typing import List


_CURRENCY_RE = re.compile(r"\bUS\$\s*([0-9][0-9,]*(?:\.\d+)?)")


def normalize_for_tts(text: str) -> str:
    """
    Normalize chunk text right before it is sent to Kokoro.

    Keep this layer light:
    - Do not rewrite book content.
    - Do not change parser/narration output files.
    - Only fix pronunciation and TTS pacing issues.
    """
    text = text or ""

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u00a0", " ")

    # Kokoro pronounced "US$432,500" awkwardly.
    # Safer TTS form: "432,500 dollars".
    text = _CURRENCY_RE.sub(r"\1 dollars", text)

    lines = []
    for raw_line in text.splitlines():
        line = raw_line.strip()

        if not line:
            lines.append("")
            continue

        if _looks_like_heading_line(line) and not _ends_with_sentence_punctuation(line):
            line += "."

        lines.append(line)

    text = "\n".join(lines)

    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def split_tts_segments(text: str) -> List[str]:
    """
    Split text into internal Kokoro segments.

    This is mainly to force audible pauses between:
    - chapter title
    - subtitle
    - first body paragraph

    Newlines alone were not producing enough separation in Kokoro, so kokoro.py
    generates each returned segment separately and inserts short silence between them.
    """
    normalized = normalize_for_tts(text)
    if not normalized:
        return []

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", normalized) if p.strip()]
    if not paragraphs:
        return [normalized]

    segments: List[str] = []

    # Keep the first heading-like paragraphs as separate TTS segments.
    # After those, merge body paragraphs into one segment for this smoke-test stage.
    body_start = 0
    for idx, paragraph in enumerate(paragraphs[:3]):
        compact = _single_line(paragraph)
        if idx == 0 and re.match(r"^Chapter\s+\d+\s*:", compact, re.I):
            segments.append(compact)
            body_start = idx + 1
            continue

        if idx <= 1 and _looks_like_heading_line(compact):
            segments.append(compact)
            body_start = idx + 1
            continue

        break

    body = "\n\n".join(paragraphs[body_start:]).strip()
    if body:
        segments.append(body)

    return [s.strip() for s in segments if s.strip()]


def _single_line(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


def _ends_with_sentence_punctuation(text: str) -> bool:
    return bool(re.search(r"[.!?]['\")\]]?$", text.strip()))


def _looks_like_heading_line(text: str) -> bool:
    """
    Conservative heading detector for TTS prep only.
    Used to add a period after chapter/title/subtitle lines.
    """
    stripped = _single_line(text)

    if not stripped:
        return False

    words = stripped.split()

    if re.match(r"^Chapter\s+\d+\s*:", stripped, re.I):
        return True

    if len(words) <= 12:
        if stripped.endswith(",") or stripped.endswith(";") or stripped.endswith(":"):
            return False

        alpha_words = [w for w in words if re.search(r"[A-Za-z]", w)]
        if not alpha_words:
            return False

        capitalized = sum(1 for w in alpha_words if w[:1].isupper())
        if capitalized / max(1, len(alpha_words)) >= 0.55:
            return True

    return False
