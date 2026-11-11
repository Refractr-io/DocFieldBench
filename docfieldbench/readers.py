"""Reading steps: how a document reaches a system. The benchmark ships original files only; a reading step is part of
the system under test and is named in every result label.

  native         the file as it is (PDF, image, HTML or text). For systems that read files themselves.
  pages_png      PDF pages rasterised to PNG (150 dpi), for vision models that take images but not PDF.
  text           text only, for text models: plain text and HTML as they are, a PDF's text layer, and OCR for
                 images and PDFs without a text layer (needs the `ocr` extra).
"""
from __future__ import annotations

import io
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


def _pdf_text_layer(data: bytes) -> list[str]:
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(data)
    try:
        return [pdf[i].get_textpage().get_text_range() for i in range(len(pdf))]
    finally:
        pdf.close()


def _pdf_pages_png(data: bytes, dpi: int = 150) -> list[bytes]:
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


_OCR = None


def _ocr_image(data: bytes) -> str:
    global _OCR
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as e:  # pragma: no cover - optional extra
        raise RuntimeError("the text reader needs OCR for this document: pip install 'docfieldbench[ocr]'") from e
    if _OCR is None:
        _OCR = RapidOCR()
    result, _ = _OCR(data)
    return "\n".join(r[1] for r in result or [])


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
