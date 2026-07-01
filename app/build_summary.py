#!/usr/bin/env python3
"""
Build offline audiobook summary chain for a completed book output folder.

Phase 6.5 / v1.3 / Batch 17

Runs the full summary chain with one command while preserving the same behavior
as manually running build_summary.py and refine_summary.py one after the other.

Chain:
1. summary.builder generates summary/quick.txt
2. build_summary.py launches refine_summary.py as a separate subprocess
3. refine_summary.py generates summary/book_memories.txt

Changes:
- build_summary.py now triggers refine_summary.py as a separate Python process.
- This mirrors the manual workflow more closely than importing refine logic.
- Added a short filesystem settle delay before launching refine_summary.py.
- Existing CLI options are preserved and forwarded.
- Uses deterministic Ollama generation options from summary.ollama.
- No pipeline integration changes.
"""


from __future__ import annotations

import argparse
import subprocess
import time
import sys
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


from bootstrap import bootstrap_command
from summary.builder import SummaryBuilder
from summary.ollama import get_summary_provider


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build and refine offline audiobook summary files for a completed book."
    )
    parser.add_argument(
        "book_dir",
        type=str,
        help="Path to the completed book output directory.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate summary files even when outputs already exist.",
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


def main() -> int:
    args = parse_args()

    book_dir = Path(args.book_dir).resolve()
    if not book_dir.exists():
        print(f"ERROR: Book directory does not exist: {book_dir}")
        return 1

    bootstrap_command(
        command="build_summary",
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

    builder = SummaryBuilder(
        book_dir=book_dir,
        provider=provider,
        force=args.force,
    )

    builder.build()

    print("Stage 2: Refining Quick draft with standalone refine_summary.py...")
    time.sleep(2)

    refine_cmd = [
        sys.executable,
        str(APP_DIR / "refine_summary.py"),
        str(book_dir),
    ]

    if args.force:
        refine_cmd.append("--force")
    if args.model:
        refine_cmd.extend(["--model", args.model])
    if args.base_url:
        refine_cmd.extend(["--base-url", args.base_url])

    result = subprocess.run(refine_cmd)
    return int(result.returncode)


if __name__ == "__main__":
    sys.exit(main())
