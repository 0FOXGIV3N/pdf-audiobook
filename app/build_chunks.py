import argparse
from pathlib import Path

from bootstrap import bootstrap_command
from chunk_generator import build_chunks
from pipeline_status import PipelineStatus


def main():
    parser = argparse.ArgumentParser(description="Build Kokoro-ready speech chunks from narration text files.")
    parser.add_argument("narration_dir", help="Path to narration directory, e.g. /output/Book/narration")
    parser.add_argument("chunks_dir", help="Path to output chunks directory, e.g. /output/Book/chunks")
    parser.add_argument("--target-words", type=int, default=85)
    parser.add_argument("--min-words", type=int, default=50)
    parser.add_argument("--max-words", type=int, default=110)
    parser.add_argument("--wpm", type=int, default=160)
    parser.add_argument("--quiet", action="store_true", help="Suppress startup banner")
    args = parser.parse_args()

    narration_dir = Path(args.narration_dir)
    chunks_dir = Path(args.chunks_dir)
    ctx = bootstrap_command(
        "build_chunks",
        None,
        None,
        narration_dir,
        chunks_dir,
        show_banner=not args.quiet,
    )

    status = PipelineStatus(ctx.output_root) if ctx.output_root else None
    if status:
        status.start_stage(
            "Chunk Generation",
            message="Building Kokoro-ready chunks",
            extra={
                "narration_dir": str(narration_dir),
                "chunks_dir": str(chunks_dir),
            },
        )

    try:
        manifest = build_chunks(
            narration_dir,
            chunks_dir,
            target_words=args.target_words,
            min_words=args.min_words,
            max_words=args.max_words,
            words_per_minute=args.wpm,
        )
        if status:
            status.finish_stage(
                message="Chunk generation complete",
                extra={
                    "chapters": manifest.get("chapters"),
                    "total_chunks": manifest.get("total_chunks"),
                    "estimated_minutes": manifest.get("estimated_minutes"),
                },
            )
    except Exception as exc:
        if status:
            status.fail(str(exc))
        raise

    print("\n===== Chunk Generator =====\n")
    print(f"Chapters:          {manifest['chapters']}")
    print(f"Total chunks:      {manifest['total_chunks']}")
    print(f"Estimated minutes: {manifest['estimated_minutes']}")
    print(f"Manifest:          {chunks_dir / 'manifest.json'}")
    print(f"Report:            {chunks_dir / 'chunks_report.txt'}")


if __name__ == "__main__":
    main()
