import re
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional


@dataclass
class NarrationStats:
    chapter_id: int
    chapter_title: str
    raw_characters: int = 0
    final_characters: int = 0
    elements_in: int = 0
    elements_out: int = 0
    paragraphs_out: int = 0
    markers_removed: int = 0
    duplicate_headings_removed: int = 0
    skipped_elements: Dict[str, int] = field(default_factory=dict)
    suspicious_short_fragments: List[str] = field(default_factory=list)


class NarrationEngine:
    """
    Phase 3 Narration Engine V3.

    V3 works from structured layout/chapter elements instead of flattening the
    whole chapter into one string first. This preserves document semantics:
    headings stay separated from paragraphs, footnotes stay footnotes, and
    isolated marker debris can be filtered without affecting real paragraphs.
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

    MARKER_PATTERNS = [
        # Footnote marker by itself: 1, 2, 3, etc.
        re.compile(r"^\d{1,3}$"),

        # OCR sometimes spaces marker digits apart: 1 9 8 2, 2, etc.
        re.compile(r"^(?:\d\s*){1,4}$"),

        # Standalone citation year: 1968, 1982, 2008, etc.
        re.compile(r"^(?:15|16|17|18|19|20)\d{2}$"),

        # Figure/reference debris: 1.1 1988 2008, 2.3 1999, etc.
        re.compile(r"^\d+(?:\.\d+)+(?:\s+(?:15|16|17|18|19|20)\d{2})+$"),

        # Multiple standalone years: 1988 2008
        re.compile(r"^(?:(?:15|16|17|18|19|20)\d{2})(?:\s+(?:15|16|17|18|19|20)\d{2})+$"),

        # OCR punctuation fragments / extraction debris
        re.compile(r"^[=\-–—_\s{}\[\]().,;:]+$"),
    ]

    HEADING_TYPES = {
        "heading",
        "subtitle",
        "chapter_title",
        "section_heading",
    }

    FOOTNOTE_RE = re.compile(r"^(?:footnote\.?\s*)?(\d{1,3})[\.)]?\s+(.*)$", re.I)

    def process_chapter_elements(
        self,
        elements: List[dict],
        chapter_id: int,
        chapter_title: str,
    ) -> Tuple[str, NarrationStats]:
        stats = NarrationStats(
            chapter_id=chapter_id,
            chapter_title=chapter_title,
            elements_in=len(elements or []),
        )

        rendered_blocks: List[str] = []

        title = self._compact_text(chapter_title or "")
        if title:
            rendered_blocks.append(title)

        for element in elements or []:
            rendered = self._render_element(element, chapter_title, stats)
            if rendered:
                rendered_blocks.append(rendered)
                stats.elements_out += 1

        # Final structured safety pass. Some OCR/body-gap fragments make it this
        # far as plain blocks even when their element type is not reliable.
        # This removes only whole standalone marker blocks, never numbers inside
        # real sentences.
        rendered_blocks = self._remove_marker_blocks(rendered_blocks, stats)

        final_text = self._render_blocks(rendered_blocks)
        stats.final_characters = len(final_text)
        stats.paragraphs_out = len([b for b in rendered_blocks if b.strip()])
        return final_text, stats

    def render_raw_chapter_elements(
        self,
        elements: List[dict],
        chapter_title: str,
    ) -> str:
        """
        Debug/raw export from structured elements before Narration Engine cleanup.
        This is intentionally light-touch but still readable.
        """
        blocks = []
        title = self._compact_text(chapter_title or "")
        if title:
            blocks.append(title)

        for element in elements or []:
            text = element.get("raw_text") or element.get("normalized_text") or element.get("text") or ""
            text = self._normalize_paragraph_text(text)
            if not text:
                continue
            element_type = element.get("type", "")
            if element_type == "footnote":
                blocks.append(self._format_footnote(text))
            else:
                blocks.append(text)

        return self._render_blocks(blocks)

    def process_chapter_text(
        self,
        raw_text: str,
        chapter_id: int,
        chapter_title: str,
    ) -> Tuple[str, NarrationStats]:
        """
        Legacy fallback for chapters without structured elements.
        Keeps old string mode available, but avoids aggressive merging.
        """
        stats = NarrationStats(
            chapter_id=chapter_id,
            chapter_title=chapter_title,
            raw_characters=len(raw_text or ""),
        )
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", raw_text or "") if p.strip()]
        stats.elements_in = len(paragraphs)

        blocks = []
        for p in paragraphs:
            compact = self._normalize_paragraph_text(p)
            if self._is_marker(compact):
                stats.markers_removed += 1
                continue
            blocks.append(compact)

        final_text = self._render_blocks(blocks)
        stats.final_characters = len(final_text)
        stats.elements_out = len(blocks)
        stats.paragraphs_out = len(blocks)
        return final_text, stats

    def _render_element(self, element: dict, chapter_title: str, stats: NarrationStats) -> str:
        element_type = element.get("type", "")
        text = element.get("normalized_text") or element.get("text") or ""
        text = self._normalize_paragraph_text(text)

        if not text:
            self._count_skip(stats, "empty")
            return ""

        if element.get("narrate") is False or element_type in self.SKIP_TYPES:
            self._count_skip(stats, element_type or "non_narratable")
            return ""

        if self._is_marker(text):
            stats.markers_removed += 1
            self._count_skip(stats, "marker")
            return ""

        if element_type in self.HEADING_TYPES:
            if self._is_duplicate_heading(text, chapter_title):
                stats.duplicate_headings_removed += 1
                self._count_skip(stats, "duplicate_heading")
                return ""
            return text

        if element_type == "footnote":
            return self._format_footnote(text)

        if element_type == "figure_caption":
            return self._format_figure_caption(text)

        if len(text.split()) <= 3 and not self._is_marker(text):
            stats.suspicious_short_fragments.append(text)

        return text

    def _format_footnote(self, text: str) -> str:
        text = self._normalize_paragraph_text(text)
        text = re.sub(r"^Footnote\.\s*", "", text, flags=re.I).strip()

        match = self.FOOTNOTE_RE.match(text)
        if match:
            number, rest = match.groups()
            rest = self._normalize_paragraph_text(rest)
            return f"Footnote {number}. {rest}".strip()

        return f"Footnote. {text}".strip()

    def _format_figure_caption(self, text: str) -> str:
        text = self._normalize_paragraph_text(text)
        if re.match(r"^(figure|fig\.)\s+\d", text, re.I):
            return text
        return f"Figure caption. {text}".strip()

    def _normalize_paragraph_text(self, text: str) -> str:
        text = text or ""
        text = text.replace("\u00a0", " ")
        text = text.replace("\r\n", "\n").replace("\r", "\n")

        # Remove hidden control characters that can create large visual gaps
        # in terminal viewers without looking like normal blank lines.
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", text)

        # Join OCR line leftovers into a logical paragraph.
        text = re.sub(r"\s*\n\s*", " ", text)

        # Normalize OCR / extraction spacing.
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\s+([,.;:!?])", r"\1", text)
        text = re.sub(r"([([{])\s+", r"\1", text)
        text = re.sub(r"\s+([)\]}])", r"\1", text)

        # Repair common OCR split words caused by soft wraps.
        text = re.sub(r"\bcom-\s+puter", "computer", text, flags=re.I)
        text = re.sub(r"\bcomput-\s+ers", "computers", text, flags=re.I)
        text = re.sub(r"\bcon-\s+temporary", "contemporary", text, flags=re.I)

        return text.strip()

    def _remove_marker_blocks(self, blocks: List[str], stats: NarrationStats) -> List[str]:
        cleaned = []
        for block in blocks:
            normalized = self._normalize_paragraph_text(block)
            if not normalized:
                continue
            if self._is_marker(normalized):
                stats.markers_removed += 1
                self._count_skip(stats, "marker_block")
                continue
            cleaned.append(normalized)
        return cleaned

    def _render_blocks(self, blocks: List[str]) -> str:
        cleaned = []
        for block in blocks:
            block = self._normalize_paragraph_text(block)
            # Defensive final filter: remove whole marker blocks only.
            if block and not self._is_marker(block):
                cleaned.append(block)

        text = "\n\n".join(cleaned).strip()
        # Presentation-only cleanup. This does not merge paragraphs; it only
        # removes accidental empty/hidden gap lines after element filtering.
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", text)
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n[ \t]+", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
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

        # Direct marker match.
        if any(pattern.fullmatch(stripped) for pattern in self.MARKER_PATTERNS):
            return True

        # OCR can produce marker blocks with odd spacing or punctuation, e.g.
        # "1 9 8 2", "( 1968 )", or "2.". Normalize those only when the
        # entire block is numeric marker material.
        numeric_key = re.sub(r"[^0-9.]", "", stripped)
        if not numeric_key:
            return False

        # Standalone footnote number after punctuation cleanup.
        if re.fullmatch(r"\d{1,3}\.?", numeric_key):
            return True

        # Standalone citation year after punctuation cleanup.
        if re.fullmatch(r"(?:15|16|17|18|19|20)\d{2}", numeric_key):
            return True

        # Figure/reference debris like 1.1 plus years; only if the original
        # contains no alphabetic characters.
        if not re.search(r"[A-Za-z]", stripped) and re.fullmatch(r"\d+(?:\.\d+)+(?:\.?(?:15|16|17|18|19|20)\d{2})*", numeric_key):
            return True

        return False

    def _is_duplicate_heading(self, heading: str, chapter_title: str) -> bool:
        h = self._norm_key(heading)
        title = self._norm_key(chapter_title)

        if not h or not title:
            return False

        if h == title:
            return True

        # Handles fragments like "as Creative Tools" and full repeated titles.
        if len(h.split()) >= 2 and h in title:
            return True

        # Handles "Chapter 1" when title is "Chapter 1: Computers as Creative Tools".
        if re.fullmatch(r"chapter \d+", h) and h in title:
            return True

        return False

    def _count_skip(self, stats: NarrationStats, reason: str) -> None:
        reason = reason or "unknown"
        stats.skipped_elements[reason] = stats.skipped_elements.get(reason, 0) + 1


def build_postprocess_report(stats_items: List[NarrationStats]) -> str:
    total_final = sum(s.final_characters for s in stats_items)
    total_elements_in = sum(s.elements_in for s in stats_items)
    total_elements_out = sum(s.elements_out for s in stats_items)
    total_markers = sum(s.markers_removed for s in stats_items)
    total_duplicate_headings = sum(s.duplicate_headings_removed for s in stats_items)

    combined_skips: Dict[str, int] = {}
    for stats in stats_items:
        for reason, count in stats.skipped_elements.items():
            combined_skips[reason] = combined_skips.get(reason, 0) + count

    lines = []
    lines.append("PDF Audiobook Generator - Phase 3 Narration Engine Report")
    lines.append("=" * 62)
    lines.append("")
    lines.append(f"Chapters processed:          {len(stats_items)}")
    lines.append(f"Structured elements in:      {total_elements_in}")
    lines.append(f"Structured elements spoken:  {total_elements_out}")
    lines.append(f"Final characters:            {total_final}")
    lines.append(f"Markers removed:             {total_markers}")
    lines.append(f"Duplicate headings removed:  {total_duplicate_headings}")
    lines.append("")

    if combined_skips:
        lines.append("Skipped element summary")
        lines.append("-" * 62)
        for reason, count in sorted(combined_skips.items()):
            lines.append(f"{reason}: {count}")
        lines.append("")

    lines.append("Per chapter")
    lines.append("-" * 62)

    for stats in stats_items:
        lines.append(
            f"Chapter {stats.chapter_id:03d} | {stats.chapter_title} | "
            f"elements {stats.elements_in}->{stats.elements_out} | "
            f"markers {stats.markers_removed} | "
            f"duplicate headings {stats.duplicate_headings_removed} | "
            f"chars {stats.final_characters}"
        )

        if stats.suspicious_short_fragments:
            preview = "; ".join(stats.suspicious_short_fragments[:8])
            lines.append(f"  Review short fragments: {preview}")

    lines.append("")
    lines.append("Notes")
    lines.append("-" * 62)
    lines.append("narration_raw/ contains a readable structured export before Narration Engine cleanup.")
    lines.append("narration/ contains the final text intended for Kokoro.")
    lines.append("This stage does not modify layout.json or chapter JSON files.")

    return "\n".join(lines).strip() + "\n"
