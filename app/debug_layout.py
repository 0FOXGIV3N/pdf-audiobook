import argparse
import json
from pathlib import Path

import fitz


PALETTE = [
    (0.10, 0.45, 0.95),
    (0.10, 0.75, 0.35),
    (0.95, 0.65, 0.10),
    (0.90, 0.15, 0.15),
    (0.60, 0.25, 0.90),
    (0.00, 0.70, 0.75),
]


def rect_to_list(rect):
    return [round(rect.x0, 2), round(rect.y0, 2), round(rect.x1, 2), round(rect.y1, 2)]


def block_to_dict(index, block):
    x0, y0, x1, y1, text, block_no, block_type = block[:7]
    text = (text or "").strip()

    return {
        "index": index,
        "block_no": block_no,
        "block_type": block_type,
        "bbox": [round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)],
        "text": text,
        "preview": text[:300],
    }


def word_to_dict(index, word):
    x0, y0, x1, y1, text, block_no, line_no, word_no = word[:8]
    return {
        "index": index,
        "text": text,
        "bbox": [round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)],
        "block_no": block_no,
        "line_no": line_no,
        "word_no": word_no,
    }


def save_page_png(page, path, zoom=2.0):
    matrix = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=matrix, alpha=False)
    pix.save(path)


def save_overlay_png(page, blocks, path, zoom=2.0, show_words=False):
    doc = fitz.open()
    new_page = doc.new_page(width=page.rect.width, height=page.rect.height)
    new_page.show_pdf_page(page.rect, page.parent, page.number)

    for i, block in enumerate(blocks):
        x0, y0, x1, y1 = block["bbox"]
        rect = fitz.Rect(x0, y0, x1, y1)
        color = PALETTE[i % len(PALETTE)]

        new_page.draw_rect(rect, color=color, width=1.25)
        label_rect = fitz.Rect(x0, max(0, y0 - 11), min(x0 + 95, page.rect.width), y0)
        new_page.draw_rect(label_rect, color=color, fill=color, width=0)
        new_page.insert_text(
            (x0 + 2, max(7, y0 - 3)),
            f"B{i}",
            fontsize=7,
            color=(1, 1, 1),
        )

    if show_words:
        for word in page.get_text("words"):
            x0, y0, x1, y1 = word[:4]
            new_page.draw_rect(fitz.Rect(x0, y0, x1, y1), color=(0.8, 0.8, 0.8), width=0.25)

    matrix = fitz.Matrix(zoom, zoom)
    pix = new_page.get_pixmap(matrix=matrix, alpha=False)
    pix.save(path)
    doc.close()


def extract_dict_summary(page):
    raw = page.get_text("dict")
    summary_blocks = []

    for b_index, block in enumerate(raw.get("blocks", [])):
        item = {
            "index": b_index,
            "type": block.get("type"),
            "bbox": [round(v, 2) for v in block.get("bbox", [])],
            "lines": [],
        }

        for l_index, line in enumerate(block.get("lines", [])):
            line_text = "".join(span.get("text", "") for span in line.get("spans", [])).strip()
            spans = []
            for s_index, span in enumerate(line.get("spans", [])):
                spans.append({
                    "index": s_index,
                    "text": span.get("text", ""),
                    "font": span.get("font", ""),
                    "size": round(span.get("size", 0), 2),
                    "flags": span.get("flags"),
                    "bbox": [round(v, 2) for v in span.get("bbox", [])],
                })

            item["lines"].append({
                "index": l_index,
                "bbox": [round(v, 2) for v in line.get("bbox", [])],
                "text": line_text,
                "spans": spans,
            })

        summary_blocks.append(item)

    return summary_blocks


def write_text_report(output_dir, page_number, blocks, words_count):
    report_path = output_dir / "report.txt"

    with open(report_path, "w", encoding="utf-8") as f:
        f.write(f"Layout Debug Report - PDF page {page_number}\n")
        f.write("=" * 60 + "\n\n")
        f.write(f"Blocks: {len(blocks)}\n")
        f.write(f"Words:  {words_count}\n\n")

        for block in blocks:
            f.write("-" * 60 + "\n")
            f.write(f"BLOCK {block['index']}\n")
            f.write(f"bbox: {block['bbox']}\n")
            f.write(f"block_type: {block['block_type']}\n")
            f.write("text:\n")
            f.write(block["text"] + "\n\n")

    return report_path


def main():
    parser = argparse.ArgumentParser(description="Debug PyMuPDF page layout extraction.")
    parser.add_argument("pdf", help="Path to source PDF")
    parser.add_argument("--page", type=int, required=True, help="1-based PDF page number to inspect")
    parser.add_argument("--out", default="/output/debug", help="Output debug directory")
    parser.add_argument("--words", action="store_true", help="Also draw word boxes on overlay")
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    output_root = Path(args.out)

    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    doc = fitz.open(pdf_path)

    if args.page < 1 or args.page > len(doc):
        raise ValueError(f"Page must be between 1 and {len(doc)}. Got {args.page}")

    page = doc[args.page - 1]
    output_dir = output_root / f"page_{args.page:03d}"
    output_dir.mkdir(parents=True, exist_ok=True)

    blocks = [block_to_dict(i, block) for i, block in enumerate(page.get_text("blocks"))]
    words = [word_to_dict(i, word) for i, word in enumerate(page.get_text("words"))]
    dict_summary = extract_dict_summary(page)

    with open(output_dir / "blocks.json", "w", encoding="utf-8") as f:
        json.dump(blocks, f, indent=2, ensure_ascii=False)

    with open(output_dir / "words.json", "w", encoding="utf-8") as f:
        json.dump(words, f, indent=2, ensure_ascii=False)

    with open(output_dir / "dict_summary.json", "w", encoding="utf-8") as f:
        json.dump(dict_summary, f, indent=2, ensure_ascii=False)

    save_page_png(page, output_dir / "page.png")
    save_overlay_png(page, blocks, output_dir / "overlay.png", show_words=args.words)
    report_path = write_text_report(output_dir, args.page, blocks, len(words))

    print("\nDebug layout written:")
    print(f"  {output_dir / 'page.png'}")
    print(f"  {output_dir / 'overlay.png'}")
    print(f"  {output_dir / 'blocks.json'}")
    print(f"  {output_dir / 'words.json'}")
    print(f"  {output_dir / 'dict_summary.json'}")
    print(f"  {report_path}")

    doc.close()


if __name__ == "__main__":
    main()
