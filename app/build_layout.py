import sys
from pathlib import Path

from layout_engine import build_layout_json


def main():
    if len(sys.argv) < 3:
        print("Usage: python app/build_layout.py input/book.pdf output/BookName/layout.json")
        sys.exit(1)

    pdf_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])

    build_layout_json(pdf_path, output_path)
    print(f"Layout JSON written to: {output_path}")


if __name__ == "__main__":
    main()
