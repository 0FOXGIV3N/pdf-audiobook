import fitz


def extract_metadata(pdf_path):
    doc = fitz.open(pdf_path)

    raw_metadata = doc.metadata or {}
    toc = doc.get_toc(simple=True)

    metadata = {
        "title": raw_metadata.get("title") or "",
        "author": raw_metadata.get("author") or "",
        "subject": raw_metadata.get("subject") or "",
        "keywords": raw_metadata.get("keywords") or "",
        "creator": raw_metadata.get("creator") or "",
        "producer": raw_metadata.get("producer") or "",
        "creation_date": raw_metadata.get("creationDate") or "",
        "modification_date": raw_metadata.get("modDate") or "",
        "toc": []
    }

    for item in toc:
        level, title, page = item
        metadata["toc"].append({
            "level": level,
            "title": title.strip(),
            "page": page
        })

    return metadata
