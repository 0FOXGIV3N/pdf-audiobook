def estimate_minutes(word_count, words_per_minute=150):
    return round(word_count / words_per_minute, 2)


def build_manifest(book):
    total_words = sum(page["word_count"] for page in book["pages"])

    manifest = {
        "title": book.get("title", ""),
        "author": book.get("author", ""),
        "source_pdf": book["source_pdf"],
        "total_pages": book["total_pages"],
        "total_words": total_words,
        "estimated_minutes": estimate_minutes(total_words),
        "chapters": [
            {
                "id": 1,
                "title": "Full Book",
                "start_page": 1,
                "end_page": book["total_pages"],
                "word_count": total_words,
                "estimated_minutes": estimate_minutes(total_words),
                "status": "pending"
            }
        ]
    }

    return manifest
