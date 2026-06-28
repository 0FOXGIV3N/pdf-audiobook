import re
from dataclasses import dataclass, field
from typing import Dict, List, Tuple


@dataclass
class ElementCleanupStats:
    chapter_id: int
    chapter_title: str
    elements_in: int = 0
    elements_out: int = 0
    empty_removed: int = 0
    marker_removed: int = 0
    duplicate_heading_removed: int = 0
    skipped_by_type: Dict[str, int] = field(default_factory=dict)


class ElementCleaner:
    """
    Phase 3 Element Cleanup.

    Cleans structured elements before narration rendering. This keeps cleanup at
    the document-element level instead of trying to patch already-rendered text.
    """

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

    HEADING_TYPES = {
        "heading",
        "subtitle",
        "chapter_title",
        "section_heading",
    }

    MARKER_PATTERNS = [
        re.compile(r"^\d{1,3}$"),
        re.compile(r"^(?:\d\s*){1,4}$"),
        re.compile(r"^(?:15|16|17|18|19|20)\d{2}$"),
        re.compile(r"^\d+(?:\.\d+)+(?:\s+(?:15|16|17|18|19|20)\d{2})+$"),
        re.compile(r"^(?:(?:15|16|17|18|19|20)\d{2})(?:\s+(?:15|16|17|18|19|20)\d{2})+$"),
        re.compile(r"^[=\-–—_\s{}\[\]().,;:]+$"),
    ]

    def clean_chapter_elements(
        self,
        elements: List[dict],
        chapter_id: int,
        chapter_title: str,
    ) -> Tuple[List[dict], ElementCleanupStats]:
        stats = ElementCleanupStats(
            chapter_id=chapter_id,
            chapter_title=chapter_title or "",
            elements_in=len(elements or []),
        )

        cleaned: List[dict] = []

        for element in elements or []:
            element = dict(element)
            element_type = element.get("type", "") or "unknown"
            text = self._element_text(element)

            if not text:
                stats.empty_removed += 1
                self._count(stats.skipped_by_type, "empty")
                continue

            if element.get("narrate") is False or element_type in self.SKIP_TYPES:
                self._count(stats.skipped_by_type, element_type)
                continue

            if self._is_marker(text):
                stats.marker_removed += 1
                self._count(stats.skipped_by_type, "marker")
                continue

            if element_type in self.HEADING_TYPES and self._is_duplicate_heading(text, chapter_title):
                stats.duplicate_heading_removed += 1
                self._count(stats.skipped_by_type, "duplicate_heading")
                continue

            # Store a normalized copy without destroying the original text fields.
            element["narration_text"] = text
            cleaned.append(element)

        stats.elements_out = len(cleaned)
        return cleaned, stats

    def _element_text(self, element: dict) -> str:
        text = (
            element.get("normalized_text")
            or element.get("narration_text")
            or element.get("text")
            or ""
        )
        return self._normalize_text(text)

    def _normalize_text(self, text: str) -> str:
        text = text or ""
        text = text.replace("\u00a0", " ")
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"\s*\n\s*", " ", text)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\s+([,.;:!?])", r"\1", text)
        text = re.sub(r"([([{])\s+", r"\1", text)
        text = re.sub(r"\s+([)\]}])", r"\1", text)
        return text.strip()

    def _compact_text(self, text: str) -> str:
        return re.sub(r"\s+", " ", (text or "").strip())

    def _norm_key(self, text: str) -> str:
        text = self._compact_text(text).lower()
        text = re.sub(r"[^a-z0-9]+", " ", text)
        return self._compact_text(text)

    def _is_marker(self, text: str) -> bool:
        stripped = self._compact_text(text)
        if not stripped:
            return True

        if any(pattern.fullmatch(stripped) for pattern in self.MARKER_PATTERNS):
            return True

        # Numeric-only marker material with punctuation/spacing artifacts.
        numeric_key = re.sub(r"[^0-9.]", "", stripped)
        if not numeric_key:
            return False

        if re.search(r"[A-Za-z]", stripped):
            return False

        if re.fullmatch(r"\d{1,3}\.?", numeric_key):
            return True

        if re.fullmatch(r"(?:15|16|17|18|19|20)\d{2}", numeric_key):
            return True

        if re.fullmatch(r"\d+(?:\.\d+)+(?:\.?(?:15|16|17|18|19|20)\d{2})*", numeric_key):
            return True

        return False

    def _is_duplicate_heading(self, heading: str, chapter_title: str) -> bool:
        h = self._norm_key(heading)
        title = self._norm_key(chapter_title)

        if not h or not title:
            return False

        if h == title:
            return True

        if len(h.split()) >= 2 and h in title:
            return True

        if re.fullmatch(r"chapter \d+", h) and h in title:
            return True

        return False

    def _count(self, counter: Dict[str, int], key: str) -> None:
        key = key or "unknown"
        counter[key] = counter.get(key, 0) + 1


def build_element_cleanup_report(stats_items: List[ElementCleanupStats]) -> str:
    total_in = sum(s.elements_in for s in stats_items)
    total_out = sum(s.elements_out for s in stats_items)
    total_empty = sum(s.empty_removed for s in stats_items)
    total_markers = sum(s.marker_removed for s in stats_items)
    total_duplicate_headings = sum(s.duplicate_heading_removed for s in stats_items)

    combined: Dict[str, int] = {}
    for stats in stats_items:
        for key, count in stats.skipped_by_type.items():
            combined[key] = combined.get(key, 0) + count

    lines = []
    lines.append("PDF Audiobook Generator - Phase 3 Element Cleanup Report")
    lines.append("=" * 62)
    lines.append("")
    lines.append(f"Chapters processed:          {len(stats_items)}")
    lines.append(f"Structured elements in:      {total_in}")
    lines.append(f"Structured elements out:     {total_out}")
    lines.append(f"Empty elements removed:      {total_empty}")
    lines.append(f"Markers removed:             {total_markers}")
    lines.append(f"Duplicate headings removed:  {total_duplicate_headings}")
    lines.append("")

    if combined:
        lines.append("Skipped element summary")
        lines.append("-" * 62)
        for key, count in sorted(combined.items()):
            lines.append(f"{key}: {count}")
        lines.append("")

    lines.append("Per chapter")
    lines.append("-" * 62)
    for stats in stats_items:
        lines.append(
            f"Chapter {stats.chapter_id:03d} | {stats.chapter_title} | "
            f"elements {stats.elements_in}->{stats.elements_out} | "
            f"markers {stats.marker_removed} | "
            f"duplicate headings {stats.duplicate_heading_removed}"
        )

    lines.append("")
    lines.append("Notes")
    lines.append("-" * 62)
    lines.append("Element cleanup runs before narration rendering.")
    lines.append("It does not modify layout.json or chapter JSON files.")

    return "\n".join(lines).strip() + "\n"
