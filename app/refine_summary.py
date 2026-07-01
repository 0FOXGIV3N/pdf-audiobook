#!/usr/bin/env python3
"""
Refine a Quick draft into a listener-facing natural overview.

Phase 6.5 / v1.3 / Batch 18

This command remains intentionally standalone so the second-stage retell runs
the same way as the manual workflow.

Inputs:
- summary/quick.txt

Outputs:
- summary/book_memories.txt

Changes:
- Reframed the refine prompt away from "book memories" language.
- Added fail-closed validation before writing book_memories.txt.
- Added automatic repair pass when Ollama returns academic/framework output.
- Rejects headings, references, recommendations, notes, and chatbot-style endings.
- Writes book_memories.txt only after output passes validation.
- Preserves title and author in the deterministic intro line.
- Uses deterministic Ollama generation options from summary.ollama.
- No pipeline integration changes.
"""



from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


from bootstrap import bootstrap_command
from summary.ollama import get_summary_provider
from summary.text_cleanup import clean_for_tts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Refine quick.txt into book_memories.txt."
    )
    parser.add_argument(
        "book_dir",
        type=str,
        help="Path to the completed book output directory.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate book_memories.txt even when it already exists.",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Optional Ollama model override. Defaults to OLLAMA_MODEL or provider default.",
    )
    parser.add_argument(
        "--base-url",
        type=str,
        default=None,
        help="Optional Ollama base URL override. Defaults to OLLAMA_BASE_URL or provider default.",
    )
    return parser.parse_args()


def read_book_identity(book_dir: Path) -> dict:
    identity_path = book_dir / "book_identity.json"
    if not identity_path.exists():
        return {}

    try:
        return json.loads(identity_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def book_title(book_dir: Path) -> str:
    identity = read_book_identity(book_dir)
    for key in ("title", "book_title", "name"):
        value = identity.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return book_dir.name


def book_author(book_dir: Path) -> str:
    identity = read_book_identity(book_dir)
    for key in ("author", "book_author", "authors", "creator"):
        value = identity.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, list):
            authors = [str(item).strip() for item in value if str(item).strip()]
            if authors:
                return ", ".join(authors)
    return "Unknown Author"


def system_prompt() -> str:
    return """
You are an experienced audiobook reteller.

Your only job is to produce the final listener-facing retell of a book.

Do not behave like a chatbot.
Do not answer with analysis.
Do not explain what you are doing.
Do not say "based on the provided text."
Do not say "here is" or "let me know."
Do not offer follow-up help.

Retell the book naturally, like a thoughtful friend answering:
"So...what was this book about?"

The writing should feel human, grounded, conversational, confident, and easy to listen to.

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


def refine_prompt(title: str, author: str, quick_draft: str) -> str:
    return f"""
Write a natural 2 to 4 paragraph overview of "{title}" by {author}.

The file will already begin with:
This is a quick overview of {title} by {author}.

Do not repeat that sentence.

Write like someone who just finished the audiobook and is telling a friend what the book was about.

Start directly with:
"If someone asked me what {title} is about, I'd tell them..."

Rules:
- Write 2 to 4 paragraphs.
- Use natural prose only.
- No headings.
- No title.
- No bullets.
- No numbered lists.
- No citations.
- No references.
- No bibliography.
- No recommendations.
- No notes.
- No questions.
- No "Conclusion."
- No "Introduction."
- No "Key Themes."
- No "Key Question."
- No "This paper."
- No "This work."
- No "Would you like."
- Do not sound academic.
- Do not organize the answer like an essay.
- Do not mention chapters or chunks.

Use the rough draft below only as source material.
Keep the central idea, the overall journey, the memorable examples, and the final feeling of the book.

Rough draft:

{quick_draft}
""".strip()



BANNED_OUTPUT_PATTERNS = (
    r"(?im)^\s*title\s*:",
    r"(?im)^\s*introduction\s*$",
    r"(?im)^\s*conclusion\s*$",
    r"(?im)^\s*references\s*$",
    r"(?im)^\s*bibliography\s*$",
    r"(?im)^\s*examples\s*$",
    r"(?im)^\s*key themes?\s*$",
    r"(?im)^\s*key questions?\s*:",
    r"(?im)^\s*key question\s*:",
    r"(?im)^\s*recommendations?\s*$",
    r"(?im)^\s*next steps\s*$",
    r"(?im)^\s*note\s*:",
    r"(?i)\bthis paper\b",
    r"(?i)\bthis work\b",
    r"(?i)\bstructured framework\b",
    r"(?i)\bcritical synthesis\b",
    r"(?i)\bwould you like\b",
    r"(?i)\blet me know\b",
    r"(?i)\bdoi\.org\b",
    r"(?i)\bet al\.",
    r"\([A-Z][A-Za-z-]+,\s*\d{4}[a-z]?\)",
)


def validation_errors(text: str) -> list[str]:
    errors: list[str] = []
    cleaned = text.strip()

    if not cleaned:
        errors.append("empty output")
        return errors

    body = re.sub(r"^This is a quick overview of .*? by .*?\.\s*", "", cleaned, flags=re.DOTALL)
    paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]
    if len(paragraphs) < 2 or len(paragraphs) > 4:
        errors.append(f"expected 2 to 4 paragraphs, found {len(paragraphs)}")

    for pattern in BANNED_OUTPUT_PATTERNS:
        if re.search(pattern, cleaned):
            errors.append(f"banned pattern: {pattern}")

    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    heading_like = [
        line for line in lines
        if len(line) <= 80
        and not line.endswith(".")
        and not line.endswith("?")
        and not line.startswith("This is a quick overview")
    ]
    if heading_like:
        errors.append(f"heading-like lines: {heading_like[:3]}")

    return errors


def repair_prompt(title: str, author: str, bad_output: str) -> str:
    return f"""
Rewrite the text below into the correct final format.

Required format:
- Exactly 2 to 4 natural paragraphs.
- No title.
- No headings.
- No labels.
- No bullets.
- No numbered lists.
- No citations.
- No references.
- No bibliography.
- No recommendations.
- No notes.
- No questions.
- No academic framing.

The file will already begin with:
This is a quick overview of {title} by {author}.

Do not repeat that sentence.

Start immediately with the story.

Do not use conversational framing like:
"If someone asked me..."
"I'd tell them..."

Begin as though you're already in the middle of explaining the book to a friend.

Make it sound like a thoughtful friend retelling the book from memory.

Bad output to rewrite:

{bad_output}
""".strip()


def generate_valid_refined(
    provider,
    title: str,
    author: str,
    quick_draft: str,
    max_attempts: int = 3,
) -> str:
    prompt = refine_prompt(title, author, quick_draft)

    for attempt in range(1, max_attempts + 1):
        print(f"Refine attempt {attempt}/{max_attempts}...")
        refined = provider.generate(
            prompt,
            system=system_prompt(),
        )
        refined = clean_for_tts(refined)
        refined = ensure_intro(refined, title, author)

        errors = validation_errors(refined)
        if not errors:
            return refined

        print("Refine output rejected:")
        for error in errors:
            print(f"  - {error}")

        prompt = repair_prompt(title, author, refined)

    raise RuntimeError("Refine failed validation after all attempts.")


def intro_line(title: str, author: str) -> str:
    return f"This is a quick overview of {title} by {author}."


def ensure_intro(text: str, title: str, author: str) -> str:
    intro = intro_line(title, author)
    cleaned = text.strip()
    if cleaned.startswith(intro):
        return cleaned
    return f"{intro}\n\n{cleaned}" if cleaned else intro


def write_text(path: Path, text: str) -> None:
    cleaned = clean_for_tts(text).strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(cleaned + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()

    book_dir = Path(args.book_dir).resolve()
    if not book_dir.exists():
        print(f"ERROR: Book directory does not exist: {book_dir}")
        return 1

    summary_dir = book_dir / "summary"
    quick_path = summary_dir / "quick.txt"
    book_memories_path = summary_dir / "book_memories.txt"

    if not quick_path.exists():
        print(f"ERROR: Quick draft does not exist: {quick_path}")
        print("Run build_summary first to generate quick.txt.")
        return 1

    if book_memories_path.exists() and not args.force:
        print("Book memories already exist. Use --force to regenerate.")
        print(f"Book memories: {book_memories_path}")
        return 0

    bootstrap_command(
        command="refine_summary",
        output_root=book_dir,
        show_banner=True,
    )

    provider = get_summary_provider(
        model=args.model,
        base_url=args.base_url,
    )

    status = provider.status()
    if not status.available:
        print("ERROR: AI companion provider is not available.")
        if status.reason:
            print(f"Reason: {status.reason}")
        return 1

    if hasattr(provider, "generation_options"):
        print(f"Ollama generation options: {provider.generation_options()}")

    title = book_title(book_dir)
    author = book_author(book_dir)
    quick_draft = quick_path.read_text(encoding="utf-8").strip()

    print("Refining Quick draft into natural overview...")
    refined = generate_valid_refined(
        provider=provider,
        title=title,
        author=author,
        quick_draft=quick_draft,
    )

    write_text(book_memories_path, refined)

    print("Done.")
    print(f"Book memories: {book_memories_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
