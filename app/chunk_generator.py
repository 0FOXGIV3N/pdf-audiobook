import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Dict, Any, Optional


@dataclass
class Chunk:
    id: str
    chapter: int
    order: int
    input_file: str
    status: str
    words: int
    estimated_seconds: int
    text_preview: str


@dataclass
class TextUnit:
    text: str
    kind: str = "body"  # "heading" or "body"


class ChunkGenerator:
    """
    Build Kokoro-ready speech chunks from narration text.

    v4.0:
    - Preserves chapter-opening structure inside chunk TXT files.
    - Keeps short heading/subtitle units separated by blank lines.
    - Keeps body sentence units joined normally for natural chunk sizes.
    - Fixes flattened first chunks such as:
        Chapter 1: Title Subtitle Body...
      by writing:
        Chapter 1: Title

        Subtitle

        Body...
    """

    def __init__(self, target_words=85, min_words=50, max_words=110, words_per_minute=160):
        self.target_words = target_words
        self.min_words = min_words
        self.max_words = max_words
        self.words_per_minute = words_per_minute

    def build_from_narration_dir(self, narration_dir, chunks_dir):
        narration_dir = Path(narration_dir)
        chunks_dir = Path(chunks_dir)
        chunks_dir.mkdir(parents=True, exist_ok=True)

        narration_files = sorted(narration_dir.glob("narration_*.txt"))
        global_manifest = {
            "book": chunks_dir.parent.name,
            "source": str(narration_dir),
            "chapters": 0,
            "total_chunks": 0,
            "estimated_minutes": 0,
            "tts_engine": None,
            "status": "pending",
            "chapter_manifests": [],
        }

        report_lines = [
            "Chunk Generator Report",
            "=" * 48,
            f"Source narration: {narration_dir}",
            f"Output chunks:    {chunks_dir}",
            "",
        ]

        total_seconds = 0

        for narration_file in narration_files:
            chapter_id = self._chapter_id_from_filename(narration_file.name)
            text = narration_file.read_text(encoding="utf-8").strip()
            chapter_dir = chunks_dir / f"chapter_{chapter_id:03d}"
            chapter_dir.mkdir(parents=True, exist_ok=True)

            # Clean old chunks for this chapter so reruns do not leave stale files.
            for old in chapter_dir.glob("*.txt"):
                old.unlink()
            for old in chapter_dir.glob("*.json"):
                old.unlink()

            chunk_texts = self.chunk_text(text)
            chunks = []
            chapter_seconds = 0

            for index, chunk_text in enumerate(chunk_texts, start=1):
                chunk_id = f"{chapter_id:03d}_{index:03d}"
                txt_name = f"{index:03d}.txt"
                json_name = f"{index:03d}.json"
                txt_path = chapter_dir / txt_name
                json_path = chapter_dir / json_name

                words = self.word_count(chunk_text)
                estimated_seconds = self.estimate_seconds(words)
                chapter_seconds += estimated_seconds

                txt_path.write_text(chunk_text.strip() + "\n", encoding="utf-8")

                chunk = Chunk(
                    id=chunk_id,
                    chapter=chapter_id,
                    order=index,
                    input_file=txt_name,
                    status="pending",
                    words=words,
                    estimated_seconds=estimated_seconds,
                    text_preview=self.preview(chunk_text),
                )
                json_path.write_text(json.dumps(asdict(chunk), indent=2, ensure_ascii=False), encoding="utf-8")
                chunks.append(asdict(chunk))

            chapter_manifest = {
                "chapter": chapter_id,
                "source_file": narration_file.name,
                "chunks": len(chunks),
                "estimated_seconds": chapter_seconds,
                "estimated_minutes": round(chapter_seconds / 60, 2),
                "status": "pending",
                "items": chunks,
            }
            (chapter_dir / "manifest.json").write_text(
                json.dumps(chapter_manifest, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

            global_manifest["chapters"] += 1
            global_manifest["total_chunks"] += len(chunks)
            global_manifest["chapter_manifests"].append(str(Path(f"chapter_{chapter_id:03d}") / "manifest.json"))
            total_seconds += chapter_seconds

            report_lines.append(
                f"Chapter {chapter_id:03d}: {len(chunks):>3} chunks | {round(chapter_seconds / 60, 2):>6} min | {narration_file.name}"
            )

        global_manifest["estimated_minutes"] = round(total_seconds / 60, 2)

        (chunks_dir / "manifest.json").write_text(
            json.dumps(global_manifest, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        report_lines.extend([
            "",
            "Totals",
            "-" * 48,
            f"Chapters:          {global_manifest['chapters']}",
            f"Chunks:            {global_manifest['total_chunks']}",
            f"Estimated minutes: {global_manifest['estimated_minutes']}",
            "",
            "Rules",
            "-" * 48,
            f"Target words:      {self.target_words}",
            f"Min words:         {self.min_words}",
            f"Max words:         {self.max_words}",
            f"Words per minute:  {self.words_per_minute}",
            "",
            "Structure",
            "-" * 48,
            "Heading/subtitle units are preserved with blank lines inside chunks.",
        ])

        (chunks_dir / "chunks_report.txt").write_text("\n".join(report_lines).strip() + "\n", encoding="utf-8")
        return global_manifest

    def chunk_text(self, text: str) -> List[str]:
        units = self._split_into_units(text)
        if not units:
            return []

        chunks: List[List[TextUnit]] = []
        current: List[TextUnit] = []
        current_words = 0

        for unit in units:
            unit_words = self.word_count(unit.text)

            if not current:
                current.append(unit)
                current_words = unit_words
                continue

            would_words = current_words + unit_words

            if current_words >= self.min_words and would_words > self.target_words:
                chunks.append(current)
                current = [unit]
                current_words = unit_words
            elif would_words > self.max_words:
                chunks.append(current)
                current = [unit]
                current_words = unit_words
            else:
                current.append(unit)
                current_words = would_words

        if current:
            chunks.append(current)

        chunk_texts = [self._join_units(chunk_units) for chunk_units in chunks]
        return self._merge_tiny_tail_chunks(chunk_texts)

    def _split_into_units(self, text: str) -> List[TextUnit]:
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]
        units: List[TextUnit] = []

        for paragraph in paragraphs:
            compact = self._compact(paragraph)
            if not compact:
                continue

            # Preserve short headings/subtitles as standalone structural units.
            # This is intentionally generic and is not book-specific.
            if self._looks_like_heading_unit(compact):
                units.append(TextUnit(text=compact, kind="heading"))
                continue

            sentences = self._split_sentences(compact)
            if sentences:
                units.extend(TextUnit(text=s, kind="body") for s in sentences)
            else:
                units.append(TextUnit(text=compact, kind="body"))

        return units

    def _split_sentences(self, paragraph: str) -> List[str]:
        # Simple sentence splitter that avoids splitting on common abbreviations.
        protected = paragraph
        abbreviations = {
            "Fig.": "Fig<dot>",
            "Dr.": "Dr<dot>",
            "Mr.": "Mr<dot>",
            "Ms.": "Ms<dot>",
            "Prof.": "Prof<dot>",
            "e.g.": "e<dot>g<dot>",
            "i.e.": "i<dot>e<dot>",
            "etc.": "etc<dot>",
        }
        for src, repl in abbreviations.items():
            protected = protected.replace(src, repl)

        parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'])", protected)
        restored = []
        for part in parts:
            for src, repl in abbreviations.items():
                part = part.replace(repl, src)
            part = part.strip()
            if part:
                restored.append(part)
        return restored

    def _merge_tiny_tail_chunks(self, chunks: List[str]) -> List[str]:
        if len(chunks) < 2:
            return chunks

        last_words = self.word_count(chunks[-1])
        if last_words < self.min_words:
            combined = chunks[-2].strip() + "\n\n" + chunks[-1].strip()
            if self.word_count(combined) <= self.max_words + 25:
                return chunks[:-2] + [combined]
        return chunks

    def _join_units(self, units: List[TextUnit]) -> str:
        """
        Join units while preserving heading/subtitle boundaries.

        Body units are joined with spaces so sentence-level chunking remains compact.
        Heading units are separated from following content by blank lines so Kokoro's
        text_normalizer.split_tts_segments() can synthesize them separately.
        """
        blocks: List[str] = []
        body_buffer: List[str] = []

        def flush_body():
            nonlocal body_buffer
            if body_buffer:
                blocks.append(" ".join(body_buffer).strip())
                body_buffer = []

        for unit in units:
            text = unit.text.strip()
            if not text:
                continue

            if unit.kind == "heading":
                flush_body()
                blocks.append(text)
            else:
                body_buffer.append(text)

        flush_body()
        return "\n\n".join(block for block in blocks if block).strip()

    def _compact(self, text: str) -> str:
        text = text.replace("\u00a0", " ")
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _looks_like_heading_unit(self, text: str) -> bool:
        stripped = self._compact(text)
        if not stripped:
            return False

        words = stripped.split()

        # Chapter labels are structural even when they include a title after a colon.
        if re.match(r"^Chapter\s+\d+\s*:", stripped, re.I):
            return True

        # Short title/subtitle lines from narration should stay as their own units.
        # Avoid treating complete normal sentences as headings.
        if len(words) <= 12 and not self._looks_like_sentence(stripped):
            return True

        return False

    def _looks_like_sentence(self, text: str) -> bool:
        return bool(re.search(r"[.!?]['\")\]]?$", text.strip()))

    def _chapter_id_from_filename(self, filename: str) -> int:
        match = re.search(r"narration_(\d+)", filename)
        if not match:
            raise ValueError(f"Could not determine chapter id from {filename}")
        return int(match.group(1))

    def word_count(self, text: str) -> int:
        return len(re.findall(r"\b[\w'-]+\b", text or ""))

    def estimate_seconds(self, words: int) -> int:
        return max(1, round((words / self.words_per_minute) * 60))

    def preview(self, text: str, limit: int = 160) -> str:
        text = self._compact(text)
        if len(text) <= limit:
            return text
        return text[:limit].rstrip() + "..."


def build_chunks(narration_dir, chunks_dir, target_words=85, min_words=50, max_words=110, words_per_minute=160):
    generator = ChunkGenerator(
        target_words=target_words,
        min_words=min_words,
        max_words=max_words,
        words_per_minute=words_per_minute,
    )
    return generator.build_from_narration_dir(narration_dir, chunks_dir)
