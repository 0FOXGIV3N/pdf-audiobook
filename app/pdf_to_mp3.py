import json
from narration_builder import write_narration_files
from chapter_writer import write_chapter_files
from config import INPUT_DIR, OUTPUT_DIR
from pdf_reader import extract_pdf
from metadata import extract_metadata
from manifest import build_manifest
from chapter_detector import tag_pages, build_chapters_from_toc
from runtime_info import print_startup_banner


pdfs = sorted(INPUT_DIR.glob("*.pdf"))

if not pdfs:
    print("No PDF found in /input")
    raise SystemExit(1)

pdf_path = pdfs[0]
book_name = pdf_path.stem
book_output_dir = OUTPUT_DIR / book_name

print_startup_banner(pdf_path=pdf_path, output_dir=book_output_dir)
print(f"Opening: {pdf_path.name}")

book_output_dir.mkdir(parents=True, exist_ok=True)
(book_output_dir / "chapters").mkdir(exist_ok=True)
(book_output_dir / "chunks").mkdir(exist_ok=True)
(book_output_dir / "wav").mkdir(exist_ok=True)
(book_output_dir / "mp3").mkdir(exist_ok=True)
(book_output_dir / "narration").mkdir(exist_ok=True)

try:
    metadata = extract_metadata(pdf_path)
    book = extract_pdf(pdf_path, book_output_dir / "layout.json")

    book["title"] = metadata.get("title", "")
    book["author"] = metadata.get("author", "")
    book["metadata"] = metadata

    book = tag_pages(book)

    manifest = build_manifest(book)
    manifest["chapters"] = build_chapters_from_toc(book)

except Exception as e:
    print("\nExtraction failed.")
    print(e)
    raise

chapter_files = write_chapter_files(
    book,
    manifest,
    book_output_dir / "chapters"
)

narration_files = write_narration_files(
    manifest,
    book_output_dir / "chapters",
    book_output_dir / "narration"
)

book_json_path = book_output_dir / "book.json"
manifest_path = book_output_dir / "manifest.json"
txt_path = book_output_dir / "transcript.txt"

with open(book_json_path, "w", encoding="utf-8") as f:
    json.dump(book, f, indent=2, ensure_ascii=False)

with open(manifest_path, "w", encoding="utf-8") as f:
    json.dump(manifest, f, indent=2, ensure_ascii=False)

with open(txt_path, "w", encoding="utf-8") as f:
    for page in book["pages"]:
        f.write(f"\n\n===== PAGE {page['page']} =====\n\n")
        f.write(page.get("speech_text", ""))

print("\nDone.")
print(f"Book JSON:     {book_json_path}")
print(f"Manifest JSON: {manifest_path}")
print(f"Transcript:    {txt_path}")
print(f"Chapter files: {len(chapter_files)}")
print(f"Narration files: {len(narration_files)}")
