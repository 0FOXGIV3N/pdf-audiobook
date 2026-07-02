from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import fitz

try:
    import pytesseract
    from PIL import Image
except Exception:  # OCR remains optional; PyMuPDF text/PDF metadata still work.
    pytesseract = None
    Image = None


IDENTITY_VERSION = "phase5_book_identity_v1.0"


@dataclass
class IdentityCandidate:
    field: str
    value: str
    confidence: float
    source: str
    page: Optional[int] = None
    reason: str = ""


def extract_book_identity(
    book_root: str | Path,
    pdf_path: str | Path | None = None,
    max_pages: int = 4,
    force: bool = False,
    quiet: bool = False,
) -> Dict[str, Any]:
    """Extract title/subtitle/author into book_identity.json.

    This is intentionally separate from chapter detection. It focuses only on
    book identity/front-matter metadata using a layered strategy:
      1. existing book artifacts
      2. PDF metadata
      3. PyMuPDF text/visual blocks from first pages
      4. OCR text from first pages
      5. conservative heuristic ranking

    The output is diagnostic rather than destructive. It never changes parser
    output, chapter JSON, narration TXT, or chunks.
    """
    book_root = Path(book_root)
    reports_dir = book_root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    identity_path = book_root / "book_identity.json"
    report_path = reports_dir / "book_identity.json"

    if identity_path.exists() and not force:
        try:
            existing = json.loads(identity_path.read_text(encoding="utf-8"))
            if existing.get("title") or existing.get("author") or existing.get("subtitle"):
                if not quiet:
                    _print_summary(existing, identity_path, reused=True)
                return existing
        except Exception:
            pass

    start = time.time()
    resolved_pdf = _resolve_pdf_path(book_root, pdf_path)

    evidence: List[Dict[str, Any]] = []
    candidates: List[IdentityCandidate] = []

    # Existing artifacts are weak fallbacks because they often contain only a
    # filename-derived title, but they are useful when cover extraction fails.
    artifact_meta = _artifact_metadata(book_root)
    if artifact_meta.get("title"):
        candidates.append(IdentityCandidate("title", artifact_meta["title"], 0.42, artifact_meta.get("source", "artifact"), None, "existing artifact title"))
    if artifact_meta.get("author"):
        candidates.append(IdentityCandidate("author", artifact_meta["author"], 0.62, artifact_meta.get("source", "artifact"), None, "existing artifact author"))
    if artifact_meta.get("subtitle"):
        candidates.append(IdentityCandidate("subtitle", artifact_meta["subtitle"], 0.50, artifact_meta.get("source", "artifact"), None, "existing artifact subtitle"))

    pdf_metadata: Dict[str, Any] = {}
    page_lines: List[Dict[str, Any]] = []

    if resolved_pdf and resolved_pdf.exists():
        pdf_metadata, page_lines = _extract_first_page_lines(resolved_pdf, max_pages=max_pages)
        evidence.append({"source": "pdf", "path": str(resolved_pdf), "metadata": pdf_metadata, "lines": page_lines[:200]})

        meta_title = _clean(pdf_metadata.get("title", ""))
        meta_author = _clean(pdf_metadata.get("author", ""))
        if _is_plausible_identity_text(meta_title):
            candidates.append(IdentityCandidate("title", meta_title, 0.60, "pdf_metadata.title", None, "PDF metadata title"))
        if _looks_like_person_name(meta_author):
            candidates.append(IdentityCandidate("author", meta_author, 0.75, "pdf_metadata.author", None, "PDF metadata author"))

        candidates.extend(_rank_line_candidates(page_lines))

    selected = _select_identity(candidates, book_root)

    identity = {
        "identity_version": IDENTITY_VERSION,
        "generated_at": _now_iso(),
        "book_root": str(book_root),
        "source_pdf": str(resolved_pdf) if resolved_pdf else None,
        "title": selected.get("title", {}).get("value") or "",
        "subtitle": selected.get("subtitle", {}).get("value") or "",
        "author": selected.get("author", {}).get("value") or "",
        "confidence": {
            "title": selected.get("title", {}).get("confidence", 0.0),
            "subtitle": selected.get("subtitle", {}).get("confidence", 0.0),
            "author": selected.get("author", {}).get("confidence", 0.0),
        },
        "sources": {
            "title": selected.get("title", {}).get("source"),
            "subtitle": selected.get("subtitle", {}).get("source"),
            "author": selected.get("author", {}).get("source"),
        },
        "pages_scanned": max_pages,
        "elapsed_seconds": round(time.time() - start, 2),
        "candidates": [asdict(c) for c in sorted(candidates, key=lambda c: (-c.confidence, c.field, c.value))[:80]],
        "evidence": evidence,
    }

    _write_json(identity_path, identity)
    _write_json(report_path, identity)
    identity["identity_file"] = str(identity_path)
    identity["report_file"] = str(report_path)

    if not quiet:
        _print_summary(identity, identity_path, reused=False)

    return identity


def _resolve_pdf_path(book_root: Path, explicit_pdf: str | Path | None = None) -> Optional[Path]:
    if explicit_pdf:
        p = Path(explicit_pdf)
        if p.exists():
            return p

    book_json = _read_json(book_root / "book.json")
    old_manifest = _read_json(book_root / "manifest.json")
    source_pdf = book_json.get("source_pdf") or old_manifest.get("source_pdf")

    candidates: List[Path] = []
    if source_pdf:
        source = Path(str(source_pdf))
        if source.is_absolute():
            candidates.append(source)
        candidates.extend([
            Path("/input") / source.name,
            book_root.parent.parent / "input" / source.name if len(book_root.parents) > 1 else Path("/input") / source.name,
        ])

    # Fallback: if there is only one PDF in /input, use it.
    candidates.extend(sorted(Path("/input").glob("*.pdf")) if Path("/input").exists() else [])

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _artifact_metadata(book_root: Path) -> Dict[str, str]:
    sources = [
        ("book.json", book_root / "book.json"),
        ("manifest.json", book_root / "manifest.json"),
        ("chunks/manifest.json", book_root / "chunks" / "manifest.json"),
        ("books/manifest.json", book_root / "books" / "manifest.json"),
    ]
    out: Dict[str, str] = {}
    for source_name, path in sources:
        data = _read_json(path)
        if not data:
            continue
        book_section = data.get("book") if isinstance(data.get("book"), dict) else {}
        title = data.get("title") or book_section.get("title") or data.get("book")
        subtitle = data.get("subtitle") or book_section.get("subtitle")
        author = data.get("author") or book_section.get("author")
        if title and not out.get("title"):
            out["title"] = _clean(str(title))
            out["source"] = source_name
        if subtitle and not out.get("subtitle"):
            out["subtitle"] = _clean(str(subtitle))
            out["source"] = source_name
        if author and not out.get("author"):
            out["author"] = _clean(str(author))
            out["source"] = source_name
    return out


def _extract_first_page_lines(pdf_path: Path, max_pages: int) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    doc = fitz.open(pdf_path)
    metadata = dict(doc.metadata or {})
    page_count = min(max_pages, len(doc))
    lines: List[Dict[str, Any]] = []

    for page_index in range(page_count):
        page = doc[page_index]
        page_number = page_index + 1
        lines.extend(_extract_pymupdf_lines(page, page_number))
        if _ocr_enabled():
            lines.extend(_extract_ocr_lines(page, page_number))

    return metadata, lines


def _extract_pymupdf_lines(page, page_number: int) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    try:
        data = page.get_text("dict")
    except Exception:
        data = {}

    page_h = float(page.rect.height)
    page_w = float(page.rect.width)

    for block in data.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            text = _clean(" ".join(span.get("text", "") for span in spans))
            if not text:
                continue
            sizes = [float(span.get("size", 0.0)) for span in spans if span.get("text")]
            bbox = list(line.get("bbox", block.get("bbox", [0, 0, 0, 0])))
            out.append({
                "text": text,
                "page": page_number,
                "source": "pymupdf_text",
                "font_size": round(max(sizes), 2) if sizes else None,
                "avg_font_size": round(sum(sizes) / len(sizes), 2) if sizes else None,
                "bbox": bbox,
                "center_x_ratio": (((bbox[0] + bbox[2]) / 2) / page_w) if page_w else None,
                "y_ratio": (bbox[1] / page_h) if page_h else None,
                "width_ratio": ((bbox[2] - bbox[0]) / page_w) if page_w else None,
            })
    return out


def _extract_ocr_lines(page, page_number: int) -> List[Dict[str, Any]]:
    if pytesseract is None or Image is None:
        return []
    scale = float(os.getenv("IDENTITY_OCR_SCALE", "2.5"))
    psm = os.getenv("IDENTITY_OCR_PSM", "6")
    matrix = fitz.Matrix(scale, scale)
    pix = page.get_pixmap(matrix=matrix, alpha=False)

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        image_path = tmp.name
    try:
        pix.save(image_path)
        image = Image.open(image_path)
        text = pytesseract.image_to_string(image, config=f"--psm {psm}")
    except Exception:
        return []
    finally:
        try:
            os.unlink(image_path)
        except Exception:
            pass

    out = []
    for line in text.splitlines():
        cleaned = _clean(line)
        if cleaned:
            out.append({
                "text": cleaned,
                "page": page_number,
                "source": "ocr_text",
                "font_size": None,
                "avg_font_size": None,
                "bbox": None,
                "center_x_ratio": None,
                "y_ratio": None,
                "width_ratio": None,
            })
    return out


def _rank_line_candidates(lines: List[Dict[str, Any]]) -> List[IdentityCandidate]:
    cleaned_lines = []
    for line in lines:
        text = _clean(line.get("text", ""))
        if not _is_plausible_identity_text(text):
            continue
        item = dict(line)
        item["text"] = text
        cleaned_lines.append(item)

    if not cleaned_lines:
        return []

    font_sizes = [l.get("font_size") for l in cleaned_lines if isinstance(l.get("font_size"), (int, float))]
    max_font = max(font_sizes) if font_sizes else None

    candidates: List[IdentityCandidate] = []

    # Author by explicit "by" signal.
    for line in cleaned_lines:
        text = line["text"]
        m = re.match(r"^(?:by|edited by|written by)\s+(.+)$", text, re.I)
        if m:
            name = _clean(m.group(1))
            if _looks_like_person_name(name):
                candidates.append(IdentityCandidate("author", name, 0.90, line["source"], line["page"], "explicit by-line"))

    # Rank possible title/subtitle and author lines.
    for line in cleaned_lines:
        text = line["text"]
        page = int(line.get("page") or 0)
        source = line.get("source", "unknown")
        font = line.get("font_size")
        y_ratio = line.get("y_ratio")
        center = line.get("center_x_ratio")

        title_score = 0.35
        subtitle_score = 0.20
        author_score = 0.20

        words = text.split()
        word_count = len(words)

        if page == 1:
            title_score += 0.15
            subtitle_score += 0.10
            author_score += 0.05
        elif page <= 3:
            title_score += 0.05
            subtitle_score += 0.05

        if max_font and font:
            ratio = font / max_font
            if ratio >= 0.92:
                title_score += 0.35
            elif ratio >= 0.72:
                subtitle_score += 0.25
                title_score += 0.10

        if y_ratio is not None:
            if 0.12 <= y_ratio <= 0.58:
                title_score += 0.10
                subtitle_score += 0.08
            if y_ratio > 0.45:
                author_score += 0.08

        if center is not None and abs(center - 0.5) < 0.22:
            title_score += 0.08
            subtitle_score += 0.05
            author_score += 0.03

        if 1 <= word_count <= 7:
            title_score += 0.12
        if 4 <= word_count <= 14:
            subtitle_score += 0.12
        if word_count > 16:
            title_score -= 0.25
            subtitle_score -= 0.10
            author_score -= 0.20

        if _looks_like_person_name(text):
            author_score += 0.45
            title_score -= 0.15
            subtitle_score -= 0.10

        if _looks_like_subtitle(text):
            subtitle_score += 0.25

        if _is_title_caseish(text):
            title_score += 0.08
            subtitle_score += 0.08

        if _looks_like_publisher_or_noise(text):
            title_score -= 0.5
            subtitle_score -= 0.5
            author_score -= 0.5

        if title_score >= 0.55:
            candidates.append(IdentityCandidate("title", text, round(min(title_score, 0.98), 2), source, page, "ranked title line"))
        if subtitle_score >= 0.50:
            candidates.append(IdentityCandidate("subtitle", text, round(min(subtitle_score, 0.95), 2), source, page, "ranked subtitle line"))
        if author_score >= 0.62:
            candidates.append(IdentityCandidate("author", _strip_by_prefix(text), round(min(author_score, 0.98), 2), source, page, "ranked author line"))

    return candidates


def _select_identity(candidates: List[IdentityCandidate], book_root: Path) -> Dict[str, Dict[str, Any]]:
    selected: Dict[str, Dict[str, Any]] = {}

    by_field: Dict[str, List[IdentityCandidate]] = {"title": [], "subtitle": [], "author": []}
    for c in candidates:
        if c.field in by_field and c.value:
            by_field[c.field].append(c)

    for field in by_field:
        unique: Dict[str, IdentityCandidate] = {}
        for c in sorted(by_field[field], key=lambda x: x.confidence, reverse=True):
            key = _norm(c.value)
            if not key:
                continue
            # Prefer the highest-confidence version of a normalized string.
            if key not in unique:
                unique[key] = c

        ordered = sorted(unique.values(), key=lambda x: x.confidence, reverse=True)
        if not ordered:
            continue

        if field == "subtitle":
            # Subtitle should not duplicate title or author.
            title_norm = _norm(selected.get("title", {}).get("value", ""))
            author_norm = _norm(selected.get("author", {}).get("value", ""))
            ordered = [c for c in ordered if _norm(c.value) not in {title_norm, author_norm}]
            if not ordered:
                continue

        best = ordered[0]
        selected[field] = asdict(best)

    # If title is still missing, use sanitized folder name as last resort.
    if "title" not in selected:
        selected["title"] = asdict(IdentityCandidate("title", _clean_slug(book_root.name), 0.25, "book_root", None, "folder name fallback"))

    return selected


def _ocr_enabled() -> bool:
    return os.getenv("BOOK_IDENTITY_OCR", "1").strip().lower() not in {"0", "false", "no", "off"}


def _is_plausible_identity_text(text: str) -> bool:
    text = _clean(text)
    if len(text) < 2 or len(text) > 120:
        return False
    if alpha_count(text) < 2:
        return False
    if _looks_like_publisher_or_noise(text):
        return False
    if re.search(r"\b(chapter|contents|preface|acknowledg|references|bibliography|index)\b", text, re.I):
        return False
    return True


def _looks_like_publisher_or_noise(text: str) -> bool:
    lower = text.lower()
    patterns = [
        "isbn", "doi", "copyright", "©", "all rights reserved", "springer",
        "palgrave", "routledge", "press", "published", "www.", "http",
        "library of congress", "catalog", "printed", "edition", "volume"
    ]
    if any(p in lower for p in patterns):
        return True
    if re.fullmatch(r"[\d\s\-\–—:.,/]+", text):
        return True
    return False


def _looks_like_person_name(text: str) -> bool:
    text = _strip_by_prefix(_clean(text))
    if not text or len(text) > 80:
        return False
    if _looks_like_publisher_or_noise(text):
        return False
    words = [re.sub(r"[^A-Za-zÀ-ÖØ-öø-ÿ'.-]", "", w) for w in text.split()]
    words = [w for w in words if w]
    if not (2 <= len(words) <= 5):
        return False
    small = {"de", "del", "da", "dos", "van", "von", "der", "la", "le", "y"}
    caps = 0
    for w in words:
        if w.lower() in small:
            continue
        if w[:1].isupper():
            caps += 1
    return caps >= 2


def _looks_like_subtitle(text: str) -> bool:
    text = _clean(text)
    if ":" in text or "—" in text or "–" in text:
        return True
    words = text.split()
    return 5 <= len(words) <= 14 and not _looks_like_person_name(text)


def _is_title_caseish(text: str) -> bool:
    words = [w for w in re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ'-]*", text)]
    if not words:
        return False
    lower_words = {"and", "or", "of", "the", "a", "an", "to", "in", "for", "with", "by"}
    cap = sum(1 for w in words if w[:1].isupper() or w.lower() in lower_words)
    return cap / max(1, len(words)) >= 0.70


def _strip_by_prefix(text: str) -> str:
    return re.sub(r"^(?:by|edited by|written by)\s+", "", _clean(text), flags=re.I)


def alpha_count(text: str) -> int:
    return sum(ch.isalpha() for ch in text or "")


def _clean(text: str) -> str:
    text = (text or "").replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    text = text.strip(" \t\r\n|")
    return text


def _clean_slug(text: str) -> str:
    text = text.replace("_", " ").replace("-", " ")
    text = re.sub(r"\b\d{4}\b", "", text)
    return _clean(text)


def _norm(text: str) -> str:
    text = re.sub(r"[^a-z0-9]+", " ", (text or "").lower())
    return re.sub(r"\s+", " ", text).strip()


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _print_summary(identity: Dict[str, Any], identity_path: Path, reused: bool = False) -> None:
    print("\n============================================================", flush=True)
    print("Book Identity", flush=True)
    print("============================================================", flush=True)
    print(f"Status:            {'reused existing' if reused else 'extracted'}", flush=True)
    print(f"Title:             {identity.get('title') or ''}", flush=True)
    print(f"Subtitle:          {identity.get('subtitle') or ''}", flush=True)
    print(f"Author:            {identity.get('author') or ''}", flush=True)
    print(f"Identity:          {identity_path}", flush=True)
    print("============================================================\n", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract book title/subtitle/author for audiobook front matter.")
    parser.add_argument("book_root", help="Path to output/<BookName> folder")
    parser.add_argument("--pdf", default=None, help="Optional explicit source PDF path")
    parser.add_argument("--pages", type=int, default=4, help="Number of first pages to inspect. Default: 4")
    parser.add_argument("--force", action="store_true", help="Re-extract even if book_identity.json already exists")
    parser.add_argument("--quiet", action="store_true", help="Suppress progress output")
    args = parser.parse_args()

    extract_book_identity(
        book_root=args.book_root,
        pdf_path=args.pdf,
        max_pages=args.pages,
        force=args.force,
        quiet=args.quiet,
    )


if __name__ == "__main__":
    main()
