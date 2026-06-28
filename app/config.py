from pathlib import Path
import os

INPUT_DIR = Path(os.getenv("INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "/output"))

CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "1200"))
VOICE = os.getenv("VOICE", "af_heart")
SPEED = float(os.getenv("SPEED", "1.0"))
PAGES_PER_FILE = int(os.getenv("PAGES_PER_FILE", "10"))
MAX_CHAPTER_MINUTES = int(os.getenv("MAX_CHAPTER_MINUTES", "45"))
