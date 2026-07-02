import sys
from pathlib import Path

from bootstrap import bootstrap_command
from layout_engine import build_layout_json
from pipeline_status import PipelineStatus


def main():
    if len(sys.argv) < 3:
        print("Usage: python app/build_layout.py input/book.pdf output/BookName/layout.json")
        sys.exit(1)

    pdf_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])
    output_root = output_path.parent

    bootstrap_command(
        command="build_layout",
        pdf_path=pdf_path,
        output_root=output_root,
    )

    status = PipelineStatus(output_root)
    status.initialize(
        phase="Phase 5 — Bootstrap",
        stage="Layout Extraction",
        message=f"Building layout JSON from {pdf_path.name}",
        extra={
            "source_pdf": str(pdf_path),
            "layout_output": str(output_path),
        },
    )

    try:
        status.update(current=0, total=1, item=pdf_path.name, message="Starting MuPDF/OCR layout extraction")
        build_layout_json(pdf_path, output_path)
        status.update(current=1, total=1, item=output_path.name, message="Layout JSON written")
        status.finish_stage(
            message="Layout extraction complete",
            extra={"layout_output": str(output_path)},
        )
        print(f"Layout JSON written to: {output_path}")
        print(f"Pipeline status: {status.status_path}")
    except Exception as exc:
        status.fail(str(exc))
        raise


if __name__ == "__main__":
    main()
