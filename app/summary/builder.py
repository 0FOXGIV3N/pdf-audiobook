"""
Offline companion summary builder.

Phase 6.5 / v1.3 / Batch 14

Batch 14 restores builder.py as the first-stage Quick draft generator.

Changes:
- builder.py now generates summary/quick.txt only.
- quick.txt is built from narration_*.txt files in natural order.
- Removed book_memories.txt generation from builder.py.
- Removed final retell/refinement from builder.py.
- The second-stage retell now belongs to refine_summary.py.
- No provider changes.
- No pipeline integration changes.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable, List

from .base import SummaryProvider
from .text_cleanup import clean_for_tts


class SummaryBuilder:
    def __init__(
        self,
        book_dir: Path,
        provider: SummaryProvider,
        force: bool = False,
    ) -> None:
        self.book_dir = Path(book_dir)
        self.provider = provider
        self.force = force

        self.narration_dir = self.book_dir / "narration"
        self.summary_dir = self.book_dir / "summary"

        self.quick_path = self.summary_dir / "quick.txt"

    def build(self) -> None:
        self._validate()

        self.summary_dir.mkdir(parents=True, exist_ok=True)

        if self._outputs_exist() and not self.force:
            print("Quick draft already exists. Use --force to regenerate.")
            print(f"Quick: {self.quick_path}")
            return

        print("Generating Quick draft from narration files...")
        quick = self._build_quick_draft()
        self._write_text(self.quick_path, quick)

        print("Done.")

    def _validate(self) -> None:
        if not self.book_dir.exists():
            raise FileNotFoundError(f"Book directory does not exist: {self.book_dir}")

        if not self.narration_dir.exists():
            raise FileNotFoundError(f"Narration directory does not exist: {self.narration_dir}")

        narration_files = list(self._narration_files())
        if not narration_files:
            raise FileNotFoundError(f"No narration files found in: {self.narration_dir}")

    def _outputs_exist(self) -> bool:
        return self.quick_path.exists()

    def _narration_files(self) -> Iterable[Path]:
        def natural_key(path: Path) -> list[object]:
            parts = re.split(r"(\d+)", path.name)
            return [int(part) if part.isdigit() else part.lower() for part in parts]

        return sorted(self.narration_dir.glob("narration_*.txt"), key=natural_key)

    def _read_book_identity(self) -> dict:
        identity_path = self.book_dir / "book_identity.json"
        if not identity_path.exists():
            return {}

        try:
            return json.loads(identity_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _book_title(self) -> str:
        identity = self._read_book_identity()
        for key in ("title", "book_title", "name"):
            value = identity.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return self.book_dir.name

    def _book_author(self) -> str:
        identity = self._read_book_identity()
        for key in ("author", "book_author", "authors", "creator"):
            value = identity.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, list):
                authors = [str(item).strip() for item in value if str(item).strip()]
                if authors:
                    return ", ".join(authors)
        return "Unknown Author"

    def _build_quick_draft(self) -> str:
        parts: List[str] = []
        narration_files = list(self._narration_files())
        total = len(narration_files)

        for index, narration_path in enumerate(narration_files, start=1):
            print(f"  [{index}/{total}] Drafting from {narration_path.name}...")

            narration = narration_path.read_text(encoding="utf-8").strip()
            if not narration:
                print(f"  [{index}/{total}] Skipped empty narration.")
                continue

            prompt = self._quick_draft_prompt(
                part_number=index,
                total_parts=total,
                narration=narration,
            )

            part = self.provider.generate(
                prompt,
                system=self._system_prompt(),
            )
            part = clean_for_tts(part)

            if part:
                part = self._clean_quick_part(part)
                if part:
                    parts.append(part)

            print(f"  [{index}/{total}] Quick draft part complete.")

        return "\n\n".join(parts).strip()

    def _quick_draft_prompt(
        self,
        part_number: int,
        total_parts: int,
        narration: str,
    ) -> str:
        title = self._book_title()
        author = self._book_author()

        return f"""
You just listened to part {part_number} of {total_parts} from "{title}" by {author}.

Write exactly ONE short plain paragraph that captures what this part contributes to the book.

This is an intermediate draft for a later retell.
Do not try to summarize the whole book.
Do not analyze the section.
Do not create an outline.
Do not use headings.
Do not use labels.
Do not use bullets.
Do not use numbered lists.
Do not use citations.
Do not mention sources, dates, page numbers, footers, references, bibliography entries, or index material.
Do not mention chapter numbers.
Do not say "based on the text."
Do not say "this section explores."
Do not offer help.

Write like a person remembering what stuck from this part of the audiobook.
Focus only on the durable idea, shift, example, or moment that helps someone understand the book later.
Ignore extracted PDF artifacts, page footers, source labels, and reference material.

Audiobook part:

{narration}
""".strip()

    def _clean_quick_part(self, text: str) -> str:
        banned_prefixes = (
            "book order",
            "source file",
            "chapter",
            "references",
            "bibliography",
            "works cited",
            "key themes",
            "core themes",
            "main themes",
            "conclusion",
            "summary",
            "analysis",
            "synthesis",
            "structure of the book",
            "key questions",
            "implications",
            "next steps",
            "recommendations",
        )
        out: List[str] = []
        for line in text.splitlines():
            s = line.strip()
            if not s:
                continue
            low = s.lower()
            if any(low.startswith(prefix) for prefix in banned_prefixes):
                continue
            if re.match(r"^\d+[.)]\s+", s):
                continue
            if re.match(r"^[a-zA-Z][\w\s]{0,60}:$", s):
                continue
            out.append(s)

        cleaned = " ".join(out)
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned.strip()

    def _system_prompt(self) -> str:
        return """
You are helping build an offline audiobook companion draft.

Your job is to remember what matters from one part of a book.

Do not behave like a chatbot.
Do not answer with analysis.
Do not explain what you are doing.
Do not say "based on the provided text."
Do not say "here is" or "let me know."
Do not offer follow-up help.

Write like a person remembering what stuck after listening.

Never sound like:
- a presentation
- lecture notes
- an academic paper
- a book report
- a Wikipedia article
- an AI assistant
- a research proposal
- an index summary
- a thematic analysis

Ignore non-book artifacts such as:
- index pages
- references
- bibliography pages
- works cited
- page numbers
- page footers
- copyright pages
- extracted PDF noise
- "answer" tags
- chat-style instructions
- offers to help

Do not review, critique, improve, expand, restructure, or analyze the book.
Do not add references, citations, bibliography entries, APA entries, works cited, suggested research questions, or recommendations.

Use plain text only.
Never use markdown.
Never mention prompts, source text, or your writing process.
Never invent information not supported by the provided material.
""".strip()

    def _write_text(self, path: Path, text: str) -> None:
        cleaned = clean_for_tts(text).strip()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(cleaned + "\n", encoding="utf-8")
