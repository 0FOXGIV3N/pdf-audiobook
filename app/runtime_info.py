import platform
import subprocess
import sys
from pathlib import Path

APP_VERSION = "0.9-layout-normalization"


def _cmd_version(command, args):
    try:
        result = subprocess.run([command, *args], capture_output=True, text=True, timeout=4)
        text = (result.stdout or result.stderr or "").strip().splitlines()
        return text[0].strip() if text else "Installed"
    except Exception:
        return "Not installed"


def _python_package_version(package_name):
    try:
        import importlib.metadata as metadata
        return metadata.version(package_name)
    except Exception:
        return "Unknown"


def print_startup_banner(pdf_path=None, output_dir=None):
    try:
        import fitz
        pymupdf_version = getattr(fitz, "version", None)
        if isinstance(pymupdf_version, tuple):
            pymupdf = " / ".join(str(v) for v in pymupdf_version)
        else:
            pymupdf = str(pymupdf_version or _python_package_version("pymupdf"))
    except Exception:
        pymupdf = "Not installed"

    tesseract = _cmd_version("tesseract", ["--version"])
    ffmpeg = _cmd_version("ffmpeg", ["-version"])

    try:
        import kokoro  # noqa: F401
        kokoro_status = "Installed"
    except Exception:
        kokoro_status = "Not installed"

    pdf_name = Path(pdf_path).name if pdf_path else "None"
    out = str(output_dir) if output_dir else "None"

    print("\n========================================")
    print(f"PDF Audiobook Generator v{APP_VERSION}")
    print("========================================")
    print(f"Python:      {platform.python_version()} ({platform.system()})")
    print(f"PyMuPDF:     {pymupdf}")
    print(f"Tesseract:   {tesseract}")
    print(f"FFmpeg:      {ffmpeg}")
    print(f"Kokoro:      {kokoro_status}")
    print("")
    print(f"PDF:         {pdf_name}")
    print(f"Output:      {out}")
    print("========================================\n")
