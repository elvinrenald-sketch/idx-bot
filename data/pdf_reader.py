"""
data/pdf_reader.py — Extract text from IDX disclosure PDF documents
Lightweight: uses PyPDF2 (pure Python, no system deps).
"""
import io
import logging
from typing import Optional

from curl_cffi import requests

logger = logging.getLogger("idx_bot.pdf_reader")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}

# Max PDF size to download (5 MB)
MAX_PDF_SIZE = 5 * 1024 * 1024
# Max pages to extract
MAX_PAGES = 5
# Max chars to return (for Gemini context efficiency)
MAX_CHARS = 4000


def extract_pdf_text(url: str, max_pages: int = MAX_PAGES) -> Optional[str]:
    """
    Download a PDF from URL and extract text content.
    Returns extracted text (truncated to MAX_CHARS), or None on failure.
    """
    if not url or not url.strip():
        return None

    try:
        # Download PDF
        resp = requests.get(
            url,
            headers=HEADERS,
            impersonate="chrome120",
            timeout=30,
            allow_redirects=True,
        )

        if resp.status_code != 200:
            logger.warning("PDF download failed HTTP %s: %s", resp.status_code, url[:80])
            return None

        # Check content type
        content_type = resp.headers.get("content-type", "").lower()
        if "pdf" not in content_type and not url.lower().endswith(".pdf"):
            logger.debug("Not a PDF: %s (%s)", url[:80], content_type)
            return None

        # Check size
        if len(resp.content) > MAX_PDF_SIZE:
            logger.warning("PDF too large (%d bytes): %s", len(resp.content), url[:80])
            return None

        # Extract text with PyPDF2
        text = _extract_with_pypdf2(resp.content, max_pages)

        if not text or len(text.strip()) < 20:
            logger.debug("PDF text too short from: %s", url[:80])
            return None

        # Clean and truncate
        text = _clean_text(text)
        if len(text) > MAX_CHARS:
            text = text[:MAX_CHARS] + "…[truncated]"

        logger.info("Extracted %d chars from PDF: %s", len(text), url[:80])
        return text

    except ImportError:
        logger.warning("PyPDF2 not installed — skipping PDF extraction")
        return None
    except Exception as e:
        logger.warning("PDF extraction failed for %s: %s", url[:80], e)
        return None


def _extract_with_pypdf2(pdf_bytes: bytes, max_pages: int) -> str:
    """Extract text from PDF bytes using PyPDF2."""
    try:
        from PyPDF2 import PdfReader
    except ImportError:
        logger.warning("PyPDF2 not available")
        return ""

    reader = PdfReader(io.BytesIO(pdf_bytes))
    pages = min(len(reader.pages), max_pages)

    text_parts = []
    for i in range(pages):
        try:
            page_text = reader.pages[i].extract_text()
            if page_text:
                text_parts.append(page_text)
        except Exception as e:
            logger.debug("Failed to extract page %d: %s", i, e)

    return "\n\n".join(text_parts)


def _clean_text(text: str) -> str:
    """Clean extracted PDF text — remove excessive whitespace, headers/footers."""
    import re

    # Remove excessive newlines
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Remove excessive spaces
    text = re.sub(r" {3,}", " ", text)

    # Remove common PDF artifacts
    text = re.sub(r"Page \d+ of \d+", "", text)
    text = re.sub(r"(?i)halaman \d+ dari \d+", "", text)

    return text.strip()
