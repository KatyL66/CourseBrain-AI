import base64
import logging

import fitz

logger = logging.getLogger("coursebrain")


def parse_pdf_base64(content_base64: str) -> list[tuple[int, str]]:
    pdf_bytes = base64.b64decode(content_base64)
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception:
        logger.warning("skipping attachment that is not a readable PDF")
        return []
    try:
        pages: list[tuple[int, str]] = []
        for i, page in enumerate(doc):
            text = page.get_text().strip()
            if text:
                pages.append((i + 1, text))
        return pages
    finally:
        doc.close()
