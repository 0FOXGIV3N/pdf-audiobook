import json
import os
import re
import subprocess
import tempfile
from collections import Counter
from dataclasses import dataclass, asdict, field
from pathlib import Path
from statistics import median
from difflib import SequenceMatcher

import fitz


@dataclass
class LayoutWord:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    block: int = -1
    line: int = -1
    word: int = -1


@dataclass
class LayoutLine:
    text: str
    words: list
    bbox: list
    page: int
    source: str = "words"
    meta: dict = field(default_factory=dict)


@dataclass
class LayoutElement:
    id: str
    page: int
    type: str
    text: str
    bbox: list
    narrate: bool
    confidence: float
    source: str = "unknown"
    raw_text: str = ""
    normalized_text: str = ""
    source_info: dict = field(default_factory=dict)


def normalize_text(text: str) -> str:
    text = text.replace("\u00a0", " ")
    text = text.replace("“", '"').replace("”", '"')
    text = text.replace("’", "'")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_block_text(text: str) -> str:
    text = text.replace("\u00a0", " ")
    # Repair line-break hyphenation inside a block: galler-\nies -> galleries
    text = re.sub(r"([A-Za-z])-\s*\n\s*([a-z])", r"\1\2", text)
    return normalize_text(text)


def bbox_union(items):
    return [
        min(i.bbox[0] if hasattr(i, "bbox") else i.x0 for i in items),
        min(i.bbox[1] if hasattr(i, "bbox") else i.y0 for i in items),
        max(i.bbox[2] if hasattr(i, "bbox") else i.x1 for i in items),
        max(i.bbox[3] if hasattr(i, "bbox") else i.y1 for i in items),
    ]


def similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def alpha_count(text: str) -> int:
    return sum(ch.isalpha() for ch in text or "")


def meaningful_word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z]{3,}", text or ""))


def point_in_bbox(x: float, y: float, bbox: list, pad: float = 1.5) -> bool:
    return (
        bbox[0] - pad <= x <= bbox[2] + pad and
        bbox[1] - pad <= y <= bbox[3] + pad
    )


class LayoutEngine:
    """
    Layout Engine V11.

    V4 proved that rawdict character reconstruction can recover text, but it can
    corrupt glyph ordering in styled headings. V5 used stable PyMuPDF blocks plus
    orphan words. V6/V7 added targeted OCR recovery. V8 normalizes all recovered
    text before narration and captures parser warnings into layout_report.txt.

    This specifically targets the academic-book failure we found: indented body
    paragraphs that are visible as words but are not exposed as normal blocks.

    Flow per page:
      1. Extract normal PyMuPDF text blocks.
      2. Extract all words.
      3. Remove words already covered by normal text blocks.
      4. Reconstruct orphan words into lines/paragraphs.
      5. Sort all elements by visual position.
      6. Classify, never discard.
    """

    def __init__(self, pdf_path):
        self.pdf_path = Path(pdf_path)
        self.parser_warnings = []

    def extract(self):
        doc = fitz.open(self.pdf_path)
        pages = []

        for page_index, page in enumerate(doc):
            page_number = page_index + 1

            block_elements, block_bboxes = self._extract_block_elements(page, page_number)
            words = self._extract_words(page)
            orphan_words = self._find_orphan_words(words, block_bboxes)
            orphan_lines = self._words_to_lines(orphan_words, page_number, source="orphan_words")
            orphan_elements = self._lines_to_elements(orphan_lines, page_number, page.rect, source="orphan_words")

            elements = block_elements + orphan_elements

            # OCR is a recovery layer only. It looks for visible text lines that
            # are not represented by PyMuPDF blocks/words. This is specifically
            # for indented academic paragraphs that render on screen but are not
            # exposed by the normal text extraction APIs.
            ocr_elements = self._extract_ocr_recovery_elements(page, page_number, elements)
            elements = elements + ocr_elements

            elements = self._sort_and_reindex(elements, page_number)
            self._mark_standalone_reference_markers(elements)

            pages.append({
                "page_number": page_number,
                "width": page.rect.width,
                "height": page.rect.height,
                "elements": [asdict(e) for e in elements],
            })

            print(f"Structured page {page_number}/{len(doc)}")

        self._classify_repeating_headers_footers(pages)
        self._apply_final_narration_flags(pages)

        return {
            "source_pdf": self.pdf_path.name,
            "engine": "layout_engine_v11_marker_dedup",
            "parser_warnings": self.parser_warnings,
            "pages": pages,
        }

    def save(self, output_path):
        data = self.extract()
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        self.write_report(data, output_path.with_name("layout_report.txt"))
        if self.parser_warnings:
            print(f"PDF parser warnings: {len(self.parser_warnings)}. See layout_report.txt for details.")
        return data

    def write_report(self, layout, output_path):
        counts = Counter()
        narrated = Counter()
        source_counts = Counter()
        samples = []

        for page in layout.get("pages", []):
            for el in page.get("elements", []):
                counts[el["type"]] += 1
                source_counts[el.get("source", "unknown")] += 1
                if el.get("narrate"):
                    narrated[el["type"]] += 1
                if len(samples) < 180:
                    samples.append(
                        f"p{page['page_number']:03d} | {el['type']:<18} | narrate={str(el.get('narrate')):<5} | {el.get('source',''):<14} | {el['text'][:220]}"
                    )

        lines = [
            f"Layout report for: {layout.get('source_pdf', '')}",
            f"Engine: {layout.get('engine', '')}",
            "",
            "Element counts:",
        ]

        for key, value in sorted(counts.items()):
            lines.append(f"  {key:<18} {value:>6}   narrated: {narrated.get(key, 0):>6}")

        lines.append("")
        lines.append("Source counts:")
        for key, value in sorted(source_counts.items()):
            lines.append(f"  {key:<18} {value:>6}")

        parser_warnings = layout.get("parser_warnings", [])
        lines.append("")
        lines.append(f"PDF parser warnings: {len(parser_warnings)}")
        warning_counts = Counter(w.get("message", "") for w in parser_warnings)
        for message, count in warning_counts.most_common(20):
            lines.append(f"  {count:>4} × {message}")
        if parser_warnings:
            lines.append("")
            lines.append("Parser warning pages:")
            for w in parser_warnings[:200]:
                lines.append(f"  page {w.get('page')}: {w.get('message')}")

        lines.extend(["", "First elements sample:", *samples])

        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    # ------------------------------------------------------------------
    # MuPDF warning capture
    # ------------------------------------------------------------------

    def _record_parser_warning(self, page_number, warning_text):
        warning_text = (warning_text or "").strip()
        if not warning_text:
            return
        # MuPDF sometimes emits the same warning multiple times during one page.
        for line in warning_text.splitlines():
            line = line.strip()
            if not line:
                continue
            self.parser_warnings.append({
                "page": page_number,
                "message": line,
            })

    def _safe_get_text(self, page, mode, page_number):
        """Call page.get_text while capturing noisy MuPDF stderr warnings.

        Some PDFs emit messages like:
        "MuPDF error: format error: No common ancestor in structure tree".
        Those messages are useful for the report, but they make the normal Docker
        output noisy. This captures them and stores them in layout_report.txt.
        """
        import os
        import tempfile

        old_stderr = os.dup(2)
        tmp = tempfile.TemporaryFile(mode="w+b")
        try:
            os.dup2(tmp.fileno(), 2)
            result = page.get_text(mode)
            os.dup2(old_stderr, 2)
            tmp.seek(0)
            warning_text = tmp.read().decode("utf-8", errors="replace")
            self._record_parser_warning(page_number, warning_text)
            return result
        finally:
            try:
                os.dup2(old_stderr, 2)
            except OSError:
                pass
            os.close(old_stderr)
            tmp.close()

    # ------------------------------------------------------------------
    # Primary extraction: text blocks
    # ------------------------------------------------------------------

    def _extract_block_elements(self, page, page_number):
        elements = []
        text_block_bboxes = []

        for block_index, block in enumerate(self._safe_get_text(page, "blocks", page_number)):
            x0, y0, x1, y1, text, *rest = block
            raw_text = (text or "").strip()
            text = normalize_block_text(text or "")
            if not text:
                continue

            bbox = [float(x0), float(y0), float(x1), float(y1)]
            element_type = self._classify_element(text, bbox, [], page.rect)

            # Keep these bboxes as "covered" regions. The orphan-word layer
            # should only recover words outside normal text block coverage.
            text_block_bboxes.append(bbox)

            elements.append(LayoutElement(
                id=f"p{page_number:04d}_e{len(elements):04d}",
                page=page_number,
                type=element_type,
                text=text,
                bbox=bbox,
                narrate=True,
                confidence=0.82,
                source="block",
                raw_text=raw_text,
                normalized_text=text,
                source_info={"pymupdf_block": True, "orphan_words": False, "ocr": False},
            ))

        return elements, text_block_bboxes

    # ------------------------------------------------------------------
    # Recovery extraction: orphan words
    # ------------------------------------------------------------------

    def _extract_words(self, page):
        words = []
        try:
            raw_words = self._safe_get_text(page, "words", getattr(page, "number", -1) + 1)
        except Exception:
            return words

        for item in raw_words:
            x0, y0, x1, y1, text, block, line, word = item[:8]
            text = normalize_text(text)
            if not text:
                continue
            words.append(LayoutWord(
                text=text,
                x0=float(x0), y0=float(y0), x1=float(x1), y1=float(y1),
                block=int(block), line=int(line), word=int(word)
            ))

        return sorted(words, key=lambda w: (w.y0, w.x0))

    def _find_orphan_words(self, words, block_bboxes):
        orphan_words = []

        for word in words:
            cx = (word.x0 + word.x1) / 2
            cy = (word.y0 + word.y1) / 2
            covered = any(point_in_bbox(cx, cy, bbox, pad=2.0) for bbox in block_bboxes)
            if not covered:
                orphan_words.append(word)

        return orphan_words

    def _words_to_lines(self, words, page_number, source="words"):
        if not words:
            return []

        heights = [w.y1 - w.y0 for w in words]
        y_tolerance = max(2.2, median(heights) * 0.50)
        grouped = []

        for word in sorted(words, key=lambda w: (w.y0, w.x0)):
            target = None
            for line_words in grouped:
                line_y = median([w.y0 for w in line_words])
                if abs(word.y0 - line_y) <= y_tolerance:
                    target = line_words
                    break
            if target is None:
                grouped.append([word])
            else:
                target.append(word)

        lines = []
        for line_words in grouped:
            line_words = sorted(line_words, key=lambda w: w.x0)
            text = normalize_text(" ".join(w.text for w in line_words))
            if not text:
                continue
            lines.append(LayoutLine(
                text=text,
                words=line_words,
                bbox=bbox_union(line_words),
                page=page_number,
                source=source,
            ))

        return sorted(lines, key=lambda l: (l.bbox[1], l.bbox[0]))

    def _lines_to_elements(self, lines, page_number, page_rect, source="words"):
        if not lines:
            return []

        elements = []
        current = []
        line_heights = [l.bbox[3] - l.bbox[1] for l in lines]
        med_h = median(line_heights) if line_heights else 10
        if source == "ocr_recovery":
            # OCR line boxes are often shorter than real text boxes, so normal
            # line spacing looks like a large gap. Use a looser gap so one OCR
            # paragraph does not become one element per line.
            normal_gap = med_h * 5.50
        else:
            normal_gap = med_h * 1.45

        for i, line in enumerate(lines):
            prev = lines[i - 1] if i > 0 else None

            if not current:
                current.append(line)
                continue

            gap = line.bbox[1] - prev.bbox[3]
            left_delta = abs(line.bbox[0] - prev.bbox[0])
            new_element = False

            if gap > normal_gap:
                new_element = True

            # Preserve first-line indents/hanging indents as paragraph breaks,
            # but do not split every wrapped line with tiny coordinate drift.
            if source != "ocr_recovery" and left_delta > 24 and gap >= -med_h * 0.20:
                new_element = True

            if self._looks_like_heading(line, page_rect) or self._looks_like_heading(prev, page_rect):
                new_element = True

            if self._in_footer_band(line, page_rect) or self._in_footer_band(prev, page_rect):
                new_element = True

            if new_element:
                elements.append(self._make_element(current, page_number, len(elements), page_rect, source))
                current = [line]
            else:
                current.append(line)

        if current:
            elements.append(self._make_element(current, page_number, len(elements), page_rect, source))

        return elements

    def _make_element(self, lines, page_number, index, page_rect, source):
        raw_text = "\n".join(line.text.strip() for line in lines if line.text.strip())
        text = self._merge_lines(lines)
        bbox = bbox_union(lines)
        element_type = self._classify_element(text, bbox, lines, page_rect)
        source_info = {
            "pymupdf_block": source == "block",
            "orphan_words": source == "orphan_words",
            "ocr": source == "ocr_recovery",
        }

        return LayoutElement(
            id=f"p{page_number:04d}_e{index:04d}",
            page=page_number,
            type=element_type,
            text=text,
            bbox=bbox,
            narrate=True,
            confidence=0.62 if source == "ocr_recovery" else (0.70 if source == "orphan_words" else 0.75),
            source=source,
            raw_text=raw_text,
            normalized_text=text,
            source_info=source_info,
        )

    def _merge_lines(self, lines):
        output = ""
        for i, line in enumerate(lines):
            text = line.text.strip()
            if i == 0:
                output = text
                continue

            # galler- + ies => galleries
            if output.endswith("-") and re.search(r"[A-Za-z]-$", output) and re.match(r"^[a-z]", text):
                output = output[:-1] + text
            else:
                output += " " + text
        return normalize_text(output)

    def _sort_and_reindex(self, elements, page_number):
        # Reading order for single-column academic pages: top-to-bottom first,
        # left-to-right second. This also puts recovered orphan paragraphs in
        # their visual location among regular blocks.
        elements = sorted(elements, key=lambda e: (e.bbox[1], e.bbox[0]))
        for i, el in enumerate(elements):
            el.id = f"p{page_number:04d}_e{i:04d}"
        return elements

    # ------------------------------------------------------------------
    # Final recovery extraction: OCR for text not exposed by PyMuPDF
    # ------------------------------------------------------------------

    def _ocr_enabled_for_page(self, page_number):
        setting = os.getenv("OCR_RECOVERY", "1").strip().lower()
        if setting in {"0", "false", "no", "off"}:
            return False

        pages_setting = os.getenv("OCR_RECOVERY_PAGES", "").strip()
        if not pages_setting:
            return True

        wanted = set()
        for part in pages_setting.split(","):
            part = part.strip()
            if not part:
                continue
            if "-" in part:
                a, b = part.split("-", 1)
                try:
                    wanted.update(range(int(a), int(b) + 1))
                except ValueError:
                    continue
            else:
                try:
                    wanted.add(int(part))
                except ValueError:
                    continue
        return page_number in wanted

    def _extract_ocr_recovery_elements(self, page, page_number, existing_elements):
        """Recover missing visible body text using OCR line bands.

        V9 grouped OCR by Tesseract paragraph. That was too coarse: when
        Tesseract bundled already-extracted text together with a missing
        indented paragraph, the whole group looked like a duplicate and got
        rejected.

        V10 treats OCR as a line-level evidence layer:
          1. OCR the page.
          2. Reject OCR lines already represented by PyMuPDF text.
          3. Keep OCR lines that sit in visual/body gaps or only overlap weak
             extraction artifacts.
          4. Group the kept lines back into logical paragraphs.

        This is aimed at academic PDFs where indented paragraphs render visibly
        but are absent from blocks/words extraction.
        """
        if not self._ocr_enabled_for_page(page_number):
            return []

        try:
            ocr_lines = self._page_to_ocr_lines(page, page_number)
        except Exception as exc:
            print(f"OCR recovery skipped on page {page_number}: {exc}")
            return []

        if not ocr_lines:
            return []

        existing_bboxes = [e.bbox for e in existing_elements]
        existing_texts = [e.text for e in existing_elements if e.text]
        existing_joined = " ".join(existing_texts).lower()

        candidate_lines = []

        for line in ocr_lines:
            line_text = self._normalize_ocr_recovered_text(line.text)
            if not self._is_viable_ocr_line(line_text):
                continue

            # Do not OCR-recover headers, footers, page numbers, publisher noise,
            # URLs or DOI lines. They are useful in layout.json from PyMuPDF, but
            # not useful as fallback narration text.
            line_type = self._classify_element(line_text, line.bbox, [line], page.rect)
            if line_type in {
                "empty", "page_number", "url", "doi", "footer", "footer_candidate",
                "header", "header_candidate", "extraction_artifact"
            }:
                continue

            # If the exact line is already present in normal extraction, skip it.
            # This is much safer than V9's paragraph-wide duplicate test.
            if line_text.lower() in existing_joined:
                continue

            covered_indexes = set()
            covered_words = 0
            for word in line.words:
                cx = (word.x0 + word.x1) / 2
                cy = (word.y0 + word.y1) / 2
                for idx, bbox in enumerate(existing_bboxes):
                    if point_in_bbox(cx, cy, bbox, pad=1.0):
                        covered_words += 1
                        covered_indexes.add(idx)
                        break

            coverage = covered_words / max(1, len(line.words))
            covered_text = " ".join(existing_elements[i].text for i in sorted(covered_indexes) if existing_elements[i].text)

            # If the line is almost fully covered by a normal text block and adds
            # no real alphabetic content, skip. But if the covering text is just
            # a bad fragment such as "1.1 1988 2008", keep the OCR line.
            covered_alpha = alpha_count(covered_text)
            line_alpha = alpha_count(line_text)
            covered_is_fragment = meaningful_word_count(covered_text) < max(3, meaningful_word_count(line_text) // 3)

            if coverage >= 0.80 and not covered_is_fragment:
                # Avoid duplicate OCR lines caused by the OCR reading the same
                # PyMuPDF paragraph with slightly different wrapping.
                if line_alpha <= covered_alpha + 16:
                    continue
                if similar(line_text, covered_text) > 0.72:
                    continue

            # Avoid line duplicates where OCR wording differs only slightly.
            if any(similar(line_text, existing) > 0.90 for existing in existing_texts):
                continue

            line.text = line_text
            line.meta["ocr_coverage"] = round(coverage, 3)
            line.meta["covered_text_alpha"] = covered_alpha
            candidate_lines.append(line)

        if not candidate_lines:
            return []

        groups = self._group_ocr_gap_lines(candidate_lines, page.rect)
        recovered = []

        for group in groups:
            group = sorted(group, key=lambda l: (l.bbox[1], l.bbox[0]))
            raw_text = "\n".join(l.text for l in group)
            normalized = self._normalize_ocr_recovered_text(self._merge_lines(group))

            if len(normalized) < 24:
                continue
            if meaningful_word_count(normalized) < 5:
                continue
            if any(similar(normalized, existing) > 0.88 for existing in existing_texts):
                continue

            bbox = bbox_union(group)
            element_type = self._classify_element(normalized, bbox, group, page.rect)
            if element_type in {"page_number", "url", "doi", "footer", "footer_candidate", "header", "header_candidate", "extraction_artifact", "empty"}:
                continue
            if element_type == "paragraph":
                element_type = "recovered_ocr_paragraph"

            recovered.append(LayoutElement(
                id=f"p{page_number:04d}_e{len(recovered):04d}",
                page=page_number,
                type=element_type,
                text=normalized,
                bbox=bbox,
                narrate=True,
                confidence=0.68,
                source="ocr_recovery",
                raw_text=raw_text,
                normalized_text=normalized,
                source_info={
                    "pymupdf_block": False,
                    "orphan_words": False,
                    "ocr": True,
                    "ocr_strategy": "v10_body_gap_lines",
                    "line_count": len(group),
                    "avg_coverage": round(sum(l.meta.get("ocr_coverage", 0) for l in group) / max(1, len(group)), 3),
                },
            ))

        if recovered:
            print(f"OCR recovered {len(recovered)} element(s) on page {page_number}")
        return recovered

    def _is_viable_ocr_line(self, text: str) -> bool:
        text = (text or "").strip()
        if len(text) < 6:
            return False
        if alpha_count(text) < 4:
            return False
        if meaningful_word_count(text) < 2:
            return False
        # OCR artifacts that commonly appear in small markers or decoration.
        if re.fullmatch(r"[=\-–—_\s\}]+", text):
            return False
        return True

    def _group_ocr_gap_lines(self, lines, page_rect):
        """Group recovered OCR lines into paragraphs using visual bands."""
        if not lines:
            return []

        lines = sorted(lines, key=lambda l: (l.bbox[1], l.bbox[0]))
        heights = [l.bbox[3] - l.bbox[1] for l in lines]
        med_h = median(heights) if heights else 8
        max_gap = med_h * 2.8

        groups = []
        current = []

        for line in lines:
            if not current:
                current = [line]
                continue

            prev = current[-1]
            gap = line.bbox[1] - prev.bbox[3]
            left_delta = abs(line.bbox[0] - prev.bbox[0])

            new_group = False
            if gap > max_gap:
                new_group = True

            # A very large left jump with a positive gap usually means a new
            # paragraph/section/caption. Do not use this for ordinary first-line
            # indents; those are exactly what we need to preserve.
            if gap > med_h * 0.55 and left_delta > page_rect.width * 0.22:
                new_group = True

            # Captions and footnotes should not merge into body paragraphs.
            if re.match(r"^(fig\.|figure|table)\s+\d+", line.text.strip(), re.I):
                new_group = True
            if re.match(r"^footnote\.\s*\d+\b", line.text.strip(), re.I):
                new_group = True

            if new_group:
                groups.append(current)
                current = [line]
            else:
                current.append(line)

        if current:
            groups.append(current)

        return groups

    def _normalize_ocr_recovered_text(self, text: str) -> str:
        text = normalize_text(text)
        # Common OCR-only cleanup. Keep this conservative: this is narration
        # normalization, not content rewriting.
        text = re.sub(r"\s+([,.;:!?])", r"\1", text)
        text = re.sub(r"([A-Za-z])-\s+([a-z])", r"\1\2", text)
        text = re.sub(r"\bcon-\s*temporary\b", "contemporary", text, flags=re.I)
        text = re.sub(r"\bsolv-\s*ing\b", "solving", text, flags=re.I)
        text = re.sub(r"\bcomput-\s*ers\b", "computers", text, flags=re.I)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _page_to_ocr_lines(self, page, page_number):
        # Use a moderate scale: high enough for small academic text, not so high
        # that OCR becomes painfully slow.
        scale = float(os.getenv("OCR_SCALE", "3.0"))
        matrix = fitz.Matrix(scale, scale)
        pix = page.get_pixmap(matrix=matrix, alpha=False)

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            image_path = tmp.name
        try:
            pix.save(image_path)
            cmd = [
                "tesseract",
                image_path,
                "stdout",
                "--psm",
                os.getenv("OCR_PSM", "6"),
                "tsv",
            ]
            result = subprocess.run(cmd, check=False, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or "tesseract failed")
            return self._parse_tesseract_tsv(result.stdout, page_number, scale)
        finally:
            try:
                os.unlink(image_path)
            except OSError:
                pass

    def _parse_tesseract_tsv(self, tsv_text, page_number, scale):
        groups = {}
        lines = tsv_text.splitlines()
        if not lines:
            return []

        header = lines[0].split("\t")
        index = {name: i for i, name in enumerate(header)}
        required = ["level", "block_num", "par_num", "line_num", "word_num", "left", "top", "width", "height", "conf", "text"]
        if not all(name in index for name in required):
            return []

        for row in lines[1:]:
            cols = row.split("\t")
            if len(cols) < len(header):
                continue
            try:
                level = int(cols[index["level"]])
            except ValueError:
                continue
            if level != 5:
                continue

            text = normalize_text(cols[index["text"]])
            if not text:
                continue

            try:
                conf = float(cols[index["conf"]])
            except ValueError:
                conf = -1
            if conf < float(os.getenv("OCR_MIN_CONF", "35")):
                continue

            try:
                left = float(cols[index["left"]]) / scale
                top = float(cols[index["top"]]) / scale
                width = float(cols[index["width"]]) / scale
                height = float(cols[index["height"]]) / scale
                block_num = int(cols[index["block_num"]])
                par_num = int(cols[index["par_num"]])
                line_num = int(cols[index["line_num"]])
                word_num = int(cols[index["word_num"]])
            except ValueError:
                continue

            key = (block_num, par_num, line_num)
            groups.setdefault(key, []).append(LayoutWord(
                text=text,
                x0=left,
                y0=top,
                x1=left + width,
                y1=top + height,
                block=block_num,
                line=line_num,
                word=word_num,
            ))

        layout_lines = []
        for key, words in groups.items():
            words = sorted(words, key=lambda w: w.x0)
            text = normalize_text(" ".join(w.text for w in words))
            if not text:
                continue
            layout_lines.append(LayoutLine(
                text=text,
                words=words,
                bbox=bbox_union(words),
                page=page_number,
                source="ocr_recovery",
                meta={
                    "block_num": key[0],
                    "par_num": key[1],
                    "line_num": key[2],
                },
            ))

        return sorted(layout_lines, key=lambda l: (l.bbox[1], l.bbox[0]))


    def _is_standalone_reference_marker(self, text: str) -> bool:
        """Return True for tiny visual markers that should not become narration.

        These show up when bold/blue citation markers or footnote markers are
        extracted as their own element even though the same marker is already
        present inside the real paragraph or footnote. Examples from the Chapter
        1 test case: "2", "1982", "1968", "1.1 1988 2008".
        """
        stripped = normalize_text(text or "")
        if not stripped:
            return False

        # Plain footnote marker / page-like marker.
        if re.fullmatch(r"\d{1,3}", stripped):
            return True

        # Standalone citation year or a small cluster of citation years.
        if re.fullmatch(r"(?:1[5-9]\d{2}|20\d{2})(?:\s+(?:1[5-9]\d{2}|20\d{2})){0,3}", stripped):
            return True

        # Figure/section marker plus citation years, e.g. "1.1 1988 2008".
        if re.fullmatch(r"\d+(?:\.\d+){1,3}(?:\s+(?:1[5-9]\d{2}|20\d{2})){1,4}", stripped):
            return True

        # Other tiny numeric-only citation fragments.
        if alpha_count(stripped) == 0 and len(stripped) <= 18 and re.fullmatch(r"[\d\s\.\,;:()\-–—]+", stripped):
            return True

        return False

    def _mark_standalone_reference_markers(self, elements):
        """Classify isolated citation/footnote markers as non-narrated.

        The marker itself is not deleted from layout.json. It is preserved as a
        structured element for debugging, but it cannot create a narration block
        or a visible gap in transcript/narration output.
        """
        for el in elements:
            if self._is_standalone_reference_marker(el.text):
                el.type = "duplicate_marker"
                el.narrate = False
                el.confidence = max(el.confidence, 0.92)
                el.source_info = dict(el.source_info or {})
                el.source_info["marker_dedup"] = True

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    def _classify_element(self, text, bbox, lines, page_rect):
        stripped = text.strip()

        if not stripped:
            return "empty"

        if re.fullmatch(r"\d+", stripped):
            return "page_number"

        # Short numeric/citation artifacts can appear when a visual paragraph is
        # present but PyMuPDF only exposes footnote markers or years. Keep them
        # classified so they can be skipped after OCR supplies the real text.
        if alpha_count(stripped) == 0 and re.fullmatch(r"[\d\s\.\,\-–—]+", stripped):
            return "extraction_artifact"

        if re.search(r"https?://|www\.", stripped, re.I):
            return "url"

        if re.search(r"\bdoi\b|10\.\d{4,9}/", stripped, re.I):
            return "doi"

        if self._looks_like_publisher_footer(stripped):
            return "footer"

        if self._in_header_band_bbox(bbox, page_rect):
            return "header_candidate"

        if self._in_footer_band_bbox(bbox, page_rect):
            if self._looks_like_footnote(stripped, bbox, page_rect):
                return "footnote"
            return "footer_candidate"

        if re.match(r"^(figure|fig\.|table)\s+\d+", stripped, re.I):
            return "figure_caption"

        if self._looks_like_footnote(stripped, bbox, page_rect):
            return "footnote"

        if lines and self._looks_like_true_table(lines):
            return "table_candidate"

        first_line = lines[0] if lines else None
        if self._looks_like_heading(first_line, page_rect, fallback_text=stripped, fallback_bbox=bbox):
            return "heading"

        return "paragraph"

    def _looks_like_heading(self, line, page_rect, fallback_text=None, fallback_bbox=None):
        if line is None:
            if fallback_text is None or fallback_bbox is None:
                return False
            text = fallback_text.strip()
            bbox = fallback_bbox
        else:
            text = line.text.strip()
            bbox = line.bbox

        words = text.split()
        width = bbox[2] - bbox[0]
        center = (bbox[0] + bbox[2]) / 2
        page_center = page_rect.width / 2

        if not text or len(text) > 120:
            return False

        if re.match(r"^(chapter|part)\s+([ivxlcdm]+|\d+|one|two|three|four|five|six|seven|eight|nine|ten)\b", text, re.I):
            return True

        # Avoid treating citation-start paragraph fragments as headings.
        if re.match(r"^[\(\[]?\d{4}", text):
            return False

        if len(words) <= 12 and abs(center - page_center) < page_rect.width * 0.16 and not text.endswith("."):
            return True

        if len(text) < 70 and not text.endswith(".") and width < page_rect.width * 0.62:
            if text[:1].isupper():
                return True

        return False

    def _looks_like_footnote(self, text, bbox, page_rect):
        if bbox[1] > page_rect.height * 0.68 and re.match(r"^\d+\s+", text):
            return True
        if bbox[1] > page_rect.height * 0.68 and re.match(r"^\d+[\.]", text):
            return True
        return False

    def _looks_like_publisher_footer(self, text):
        lower = text.lower()
        if text.startswith("©"):
            return True
        if "springer nature" in lower:
            return True
        if "switzerland ag" in lower:
            return True
        return False

    def _looks_like_true_table(self, lines):
        if len(lines) < 3:
            return False

        tableish = 0
        for line in lines:
            words = line.words
            if len(words) < 4:
                continue
            gaps = [words[i + 1].x0 - words[i].x1 for i in range(len(words) - 1)]
            large_gaps = [g for g in gaps if g > 18]
            numeric_tokens = sum(bool(re.search(r"\d", w.text)) for w in words)
            if len(large_gaps) >= 2 and numeric_tokens >= 2:
                tableish += 1

        return tableish >= 3

    def _in_header_band(self, line, page_rect):
        return line is not None and self._in_header_band_bbox(line.bbox, page_rect)

    def _in_footer_band(self, line, page_rect):
        return line is not None and self._in_footer_band_bbox(line.bbox, page_rect)

    def _in_header_band_bbox(self, bbox, page_rect):
        return bbox[1] < page_rect.height * 0.075

    def _in_footer_band_bbox(self, bbox, page_rect):
        return bbox[3] > page_rect.height * 0.88

    def _classify_repeating_headers_footers(self, pages):
        candidates = []
        for page in pages:
            for el in page["elements"]:
                if el["type"] in {"header_candidate", "footer_candidate"}:
                    candidates.append(el)

        for el in candidates:
            matches = [
                other for other in candidates
                if other is not el
                and el["type"] == other["type"]
                and similar(el["text"], other["text"]) > 0.82
            ]

            if len(matches) >= 2:
                el["type"] = "header" if el["type"] == "header_candidate" else "footer"
                el["confidence"] = 0.9
            else:
                el["confidence"] = 0.55

    def _apply_final_narration_flags(self, pages):
        skip_types = {
            "empty",
            "header",
            "header_candidate",
            "footer",
            "footer_candidate",
            "page_number",
            "extraction_artifact",
            "duplicate_marker",
            "duplicate_heading_fragment",
            "url",
            "doi",
        }

        for page in pages:
            previous_headings = []
            for el in page["elements"]:
                if el["type"] == "heading":
                    text = el["text"].strip().lower()
                    # Remove title suffix fragments like "as Creative Tools" when
                    # the full heading "Computers as Creative Tools" already
                    # appeared on the page.
                    if any(text and len(text) > 6 and h.endswith(text) and h != text for h in previous_headings):
                        el["type"] = "duplicate_heading_fragment"
                        el["narrate"] = False
                        el["confidence"] = 0.9
                        continue
                    previous_headings.append(text)

                if el["type"] == "footnote":
                    el["narrate"] = True
                elif el["type"] == "table_candidate":
                    el["narrate"] = True
                elif el["type"] == "recovered_ocr_paragraph":
                    el["narrate"] = True
                else:
                    el["narrate"] = el["type"] not in skip_types


def build_layout_json(pdf_path, output_path):
    engine = LayoutEngine(pdf_path)
    return engine.save(output_path)
