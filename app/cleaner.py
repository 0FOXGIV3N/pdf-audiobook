import re


def clean_text(text: str) -> str:
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def speech_normalize(text: str) -> str:
    text = text.replace("\u00a0", " ")

    # Fix hyphenated line breaks: crea-
    # tivity -> creativity
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)

    # Preserve paragraph breaks temporarily
    text = re.sub(r"\n{2,}", "<<<PARAGRAPH>>>", text)

    # Convert single line breaks into spaces
    text = text.replace("\n", " ")

    # Restore paragraph breaks
    text = text.replace("<<<PARAGRAPH>>>", "\n\n")

    # Normalize spacing
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()
