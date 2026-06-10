"""Local resume text extraction — pdfplumber, optional pytesseract OCR.

OCR is ONLY available when the system `tesseract` binary is present (the
Docker image bakes it). The uvx path is PDF-only by design — never hard-fail
on missing OCR. NO model calls: the AGENT extracts skills from the text.
"""
import io
import logging
import os
import shutil
from pathlib import Path
from typing import Dict

import pdfplumber

logger = logging.getLogger(__name__)

_IMAGE_EXTS = {".png", ".jpg", ".jpeg"}


def ocr_available() -> bool:
    return shutil.which("tesseract") is not None


def extract_text(path: str) -> Dict:
    """Extract raw text from a local resume file.

    Returns {"text": str, "warnings": [str]}. The agent does the rest
    (skill extraction, building base resume JSON) — there is deliberately
    no LLM here.
    """
    p = Path(path).expanduser()
    if not p.exists():
        raise FileNotFoundError(f"Resume file not found: {p}")
    content = p.read_bytes()
    ext = p.suffix.lower()
    warnings = []

    if ext in _IMAGE_EXTS:
        if not ocr_available():
            return {
                "text": "",
                "warnings": [
                    "Image resumes need OCR, and the tesseract binary is not "
                    "installed (it is only baked into the Docker image). "
                    "Use a PDF resume, or run the MCP via Docker."
                ],
            }
        try:
            import pytesseract
            from PIL import Image
            text = pytesseract.image_to_string(Image.open(io.BytesIO(content)))
            return {"text": text, "warnings": warnings}
        except Exception as e:
            logger.warning("OCR failed: %s", e)
            return {"text": "", "warnings": [f"OCR failed: {e}"]}

    # PDF path (default)
    text = ""
    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
    except Exception as e:
        raise RuntimeError(f"Could not parse PDF: {e}")

    if not text.strip() and ocr_available():
        warnings.append("PDF had no text layer; consider an OCR pass or a text-based PDF.")
    return {"text": text, "warnings": warnings}
