"""PDF access for build-time checks: page count, embedded files, and the text layer (never shipped as an input)."""
from __future__ import annotations

from pathlib import Path


def _open(path: Path):
    import pypdfium2 as pdfium

    return pdfium.PdfDocument(str(path))


def page_count(path: Path) -> int:
    pdf = _open(path)
    try:
        return len(pdf)
    finally:
        pdf.close()


def attachments(path: Path) -> list[tuple[str, bytes]]:
    """(file name, bytes) of every embedded file, e.g. an e-invoice's XML."""
    pdf = _open(path)
    try:
        out = []
        for i in range(pdf.count_attachments()):
            att = pdf.get_attachment(i)
            out.append((att.get_name(), bytes(att.get_data())))
        return out
    finally:
        pdf.close()


def page_texts(path: Path, max_pages: int = 10) -> list[str]:
    """The text layer of each page (empty strings for pages without one)."""
    pdf = _open(path)
    try:
        return [pdf[i].get_textpage().get_text_range() for i in range(min(len(pdf), max_pages))]
    finally:
        pdf.close()
