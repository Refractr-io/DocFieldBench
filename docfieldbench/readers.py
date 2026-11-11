"""Reading steps: how a document reaches a system. The benchmark ships original files only; a reading step is part of
the system under test and is named in every result label.

  native         the file as it is (PDF, image, HTML or text). For systems that read files themselves.
  pages_png      PDF pages rasterised to PNG (150 dpi), for vision models that take images but not PDF.
  text           text only, for text models: plain text and HTML as they are, a PDF's text layer, and OCR for
                 images and PDFs without a text layer: Tesseract 5 with its default settings (the `tesseract` binary
                 and its eng, deu, fra, nld and spa language data must be installed).
"""
from __future__ import annotations

import io
import shutil
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path

READERS = ("native", "pages_png", "text")
TEXTUAL = ("text/plain", "text/html")


@dataclass
class Document:
    """What an adapter receives: either files (media type, bytes) or text."""
    files: list[tuple[str, bytes, str]] = field(default_factory=list)   # (media_type, data, filename)
    text: str | None = None
    reader: str = "native"


_PDFIUM = threading.Lock()          # PDFium is not thread-safe; runs with --concurrency share it


def _pdf_text_layer(data: bytes) -> list[str]:
    import pypdfium2 as pdfium
    with _PDFIUM:
        pdf = pdfium.PdfDocument(data)
        try:
            return [pdf[i].get_textpage().get_text_range() for i in range(len(pdf))]
        finally:
            pdf.close()


def _pdf_pages_png(data: bytes, dpi: int = 150) -> list[bytes]:
    with _PDFIUM:
        return _render_pages(data, dpi)


def _render_pages(data: bytes, dpi: int) -> list[bytes]:
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(data)
    out = []
    try:
        for i in range(len(pdf)):
            img = pdf[i].render(scale=dpi / 72).to_pil()
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            out.append(buf.getvalue())
    finally:
        pdf.close()
    return out


OCR_LANGS = "eng+deu+fra+nld+spa"


def _ocr_image(data: bytes) -> str:
    """Tesseract with default settings (LSTM engine, automatic page segmentation), the image on stdin."""
    exe = shutil.which("tesseract")
    if exe is None:
        raise RuntimeError("the text reader needs Tesseract for this document: install tesseract-ocr")
    r = subprocess.run([exe, "stdin", "stdout", "-l", OCR_LANGS], input=data, capture_output=True, check=True)
    return r.stdout.decode("utf-8", errors="replace")


def ocr_version() -> str | None:
    exe = shutil.which("tesseract")
    if exe is None:
        return None
    r = subprocess.run([exe, "--version"], capture_output=True, text=True)
    return (r.stdout or r.stderr).splitlines()[0].strip()


def read(path: Path, media_type: str, reader: str) -> Document:
    data = path.read_bytes()
    if reader == "native":
        if media_type in TEXTUAL:                       # text and HTML go in as text: no chat API takes them as files
            return Document(text=data.decode("utf-8"), reader=reader)
        return Document(files=[(media_type, data, path.name)], reader=reader)
    if reader == "pages_png":
        if media_type == "application/pdf":
            pages = _pdf_pages_png(data)
            return Document(files=[("image/png", p, f"{path.stem}_p{i + 1}.png") for i, p in enumerate(pages)],
                            reader=reader)
        if media_type in TEXTUAL:
            return Document(text=data.decode("utf-8"), reader=reader)
        return Document(files=[(media_type, data, path.name)], reader=reader)
    if reader == "text":
        if media_type in TEXTUAL:
            return Document(text=data.decode("utf-8"), reader=reader)
        if media_type == "application/pdf":
            pages = _pdf_text_layer(data)
            if sum(len(p.strip()) for p in pages) >= 20:
                return Document(text="\n\n".join(pages), reader=reader)
            return Document(text="\n\n".join(_ocr_image(p) for p in _pdf_pages_png(data, dpi=200)), reader=reader)
        return Document(text=_ocr_image(data), reader=reader)
    raise ValueError(f"unknown reader {reader!r}; one of {READERS}")
