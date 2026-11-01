"""Text extraction for PDF (pdftotext) and PNG (tesseract OCR) evidence. Results are cached in memory."""
import functools
import shutil
import subprocess


@functools.lru_cache(maxsize=64)
def read_document(path):
    try:
        if path.lower().endswith(".pdf") and shutil.which("pdftotext"):
            return subprocess.run(["pdftotext", "-layout", path, "-"], capture_output=True, text=True, timeout=60).stdout
        if path.lower().endswith(".png") and shutil.which("tesseract"):
            return subprocess.run(["tesseract", path, "-"], capture_output=True, text=True, timeout=120).stdout
    except Exception:
        pass
    return ""
