"""
Plain-text cleanup for AI-generated audiobook companion text.

Phase 6.5 — AI Companion v1.2.4

This layer prepares Ollama output before it is written to summary/*.txt.
It is intentionally separate from tts/text_normalizer.py:

- summary.text_cleanup cleans LLM formatting artifacts.
- tts.text_normalizer handles pronunciation and Kokoro-specific speech prep.

The output of clean_for_tts() should be safe to pass to the existing chunk
generator and then Kokoro.
"""

from __future__ import annotations

import re
import unicodedata


_HEADING_LABELS = {
    "executive summary",
    "quick summary",
    "detailed summary",
    "book review",
    "overview",
    "summary",
    "central argument",
    "key takeaway",
    "final takeaway",
    "conclusion",
    "final thoughts",
}


def clean_for_tts(text: str) -> str:
    """Return plain UTF-8 prose with markdown/TTS-hostile artifacts removed.

    This is intentionally aggressive. Ollama may still return markdown even when
    prompted not to. The summary files are later sent to Kokoro, so formatting
    characters such as *, #, bullets, and horizontal rules should not survive.
    """
    text = text or ""

    text = _normalize_unicode(text)
    text = _remove_hidden_reasoning(text)
    text = _strip_code_blocks(text)
    text = _replace_markdown_links(text)

    cleaned_lines: list[str] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()

        if not line:
            cleaned_lines.append("")
            continue

        # Remove pure decorative / markdown separator lines.
        if _is_separator_line(line):
            cleaned_lines.append("")
            continue

        line = _strip_markdown_prefixes(line)
        line = _strip_markdown_emphasis(line)
        line = _strip_standalone_labels(line)

        # Remove remaining characters that are inconvenient for TTS. This is the
        # hard guarantee requested for summary outputs.
        line = line.replace("*", "")
        line = line.replace("#", "")

        # Remove hyphen bullets/separators, but preserve useful word hyphens such
        # as "AI-generated" and "human-centered".
        line = re.sub(r"^\s*[-–—]+\s*", "", line)
        line = re.sub(r"\s+[-–—]{2,}\s+", " ", line)
        line = re.sub(r"[-–—]{3,}", " ", line)

        line = _strip_heading_punctuation(line)

        if not line:
            cleaned_lines.append("")
            continue

        if _is_standalone_heading_label(line):
            cleaned_lines.append("")
            continue

        cleaned_lines.append(line.strip())

    text = "\n".join(cleaned_lines)

    # Final hard cleanup pass across the entire output.
    text = text.replace("*", "")
    text = text.replace("#", "")
    text = text.replace("`", "")
    text = text.replace("_", "")
    text = text.replace("•", "")
    text = re.sub(r"(?m)^\s*[-–—]+\s*$", "", text)
    text = re.sub(r"[-–—]{3,}", " ", text)

    # Normalize spacing while preserving paragraph breaks.
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def _normalize_unicode(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u00a0", " ")
    text = text.replace("\u200b", "")
    text = text.replace("\u200c", "")
    text = text.replace("\u200d", "")
    text = text.replace("\ufeff", "")
    text = text.replace("“", '"').replace("”", '"')
    text = text.replace("‘", "'").replace("’", "'")
    text = text.replace("…", "...")
    return text


def _remove_hidden_reasoning(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"(?im)^\s*/?no_think\s*$", "", text)
    return text


def _strip_code_blocks(text: str) -> str:
    return re.sub(r"```.*?```", "", text, flags=re.DOTALL)


def _replace_markdown_links(text: str) -> str:
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    return text


def _is_separator_line(line: str) -> bool:
    compact = line.strip()
    return bool(re.fullmatch(r"[*#_=~\-.–—\s]{3,}", compact))


def _strip_markdown_prefixes(line: str) -> str:
    # Headings: ### Title -> Title
    line = re.sub(r"^\s*#{1,6}\s*", "", line)

    # Blockquotes.
    line = re.sub(r"^\s*>\s*", "", line)

    # Bullets.
    line = re.sub(r"^\s*[-*+•]\s+", "", line)

    # Numbered lists.
    line = re.sub(r"^\s*\d+[.)]\s+", "", line)

    return line.strip()


def _strip_markdown_emphasis(line: str) -> str:
    # Explicitly handle **Title** at beginning/end and emphasis inside prose.
    line = re.sub(r"\*\*([^*]+)\*\*", r"\1", line)
    line = re.sub(r"__([^_]+)__", r"\1", line)
    line = re.sub(r"\*([^*]+)\*", r"\1", line)
    line = re.sub(r"_([^_]+)_", r"\1", line)
    line = line.replace("`", "")
    return line.strip()


def _strip_standalone_labels(line: str) -> str:
    # "Executive Summary: The title" -> "The title"
    line = re.sub(
        r"(?i)^\s*(executive summary|quick summary|detailed summary|book review|overview|summary)\s*[:\-–—]\s*",
        "",
        line,
    )
    return line.strip()


def _strip_heading_punctuation(line: str) -> str:
    # Remove leftover heading-style wrapping after emphasis stripping.
    line = line.strip()
    line = re.sub(r"^\s*[:\-–—]+\s*", "", line)
    line = re.sub(r"\s*[:\-–—]+\s*$", "", line)
    return line.strip()


def _is_standalone_heading_label(line: str) -> bool:
    compact = re.sub(r"[^a-z0-9 ]+", "", line.lower()).strip()
    compact = re.sub(r"\s+", " ", compact)
    if compact in _HEADING_LABELS:
        return True

    # Common LLM-generated section labels. We remove these because they read
    # poorly as TTS, especially when the user wants continuous narration.
    common = {
        "a book that reimagines creativity in the age of ai",
        "redefining creativity from solitude to collaboration",
        "ai as a collaborator tools not replacements",
        "the promise and peril of ai in creativity",
        "a collaborative future redefining creativity",
        "the human touch beyond the algorithm",
        "ethics and ownership the unseen cost of innovation",
        "practical meaning a call to curiosity and vigilance",
        "a call to reimagine creativity",
    }
    return compact in common
