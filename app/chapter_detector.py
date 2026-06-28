def detect_front_matter(page):
    text = page.get("speech_text", "").lower()

    labels = []

    if "copyright" in text or "isbn" in text:
        labels.append("copyright")

    if "contents" in text or "table of contents" in text:
        labels.append("table_of_contents")

    if "acknowledg" in text:
        labels.append("acknowledgements")

    if "preface" in text:
        labels.append("preface")

    if "foreword" in text:
        labels.append("foreword")

    return labels


def build_chapters_from_toc(book):
    toc = book.get("metadata", {}).get("toc", [])

    top_level = [
        item for item in toc
        if item.get("level") == 1 and item.get("page")
    ]

    if not top_level:
        return [
            {
                "id": 1,
                "title": "Full Book",
                "start_page": 1,
                "end_page": book["total_pages"],
                "type": "fallback",
                "word_count": sum(p["word_count"] for p in book["pages"]),
                "status": "pending"
            }
        ]

    chapters = []

    for i, item in enumerate(top_level):
        start_page = item["page"]

        if i + 1 < len(top_level):
            end_page = top_level[i + 1]["page"] - 1
        else:
            end_page = book["total_pages"]

        pages = [
            p for p in book["pages"]
            if start_page <= p["page"] <= end_page
        ]

        chapters.append({
            "id": i + 1,
            "title": item["title"],
            "start_page": start_page,
            "end_page": end_page,
            "type": "toc",
            "word_count": sum(p["word_count"] for p in pages),
            "status": "pending"
        })

    return chapters


def tag_pages(book):
    for page in book["pages"]:
        page["front_matter"] = detect_front_matter(page)

    return book
