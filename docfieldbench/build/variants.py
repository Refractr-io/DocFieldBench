"""Scan and photo variants of single-page born-digital PDFs. Each base document gets one variant (a seeded draw of
scan or photo); it keeps the base's gold, and is reported by condition, never in the headline score.

  scan   rendered at 200 dpi in greyscale, a small skew, sensor noise, slight contrast jitter; shipped as an
         image-only PDF (no text layer)
  photo  rendered at 160 dpi, a perspective warp, the page on a desk-coloured background, uneven light, a little
         blur; shipped as a JPEG

A field whose printed text would be too small after the transform (glyphs under MIN_GLYPH_PX pixels high) is
excluded in the variant, not counted wrong.
"""
from __future__ import annotations

import copy
import io
import random
import time

import numpy as np
from PIL import Image, ImageFilter

MIN_GLYPH_PX = 9.0
DPI = {"scan": 200, "photo": 160}


def _render(pdf_bytes: bytes, dpi: int, grey: bool) -> Image.Image:
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(pdf_bytes)
    img = doc[0].render(scale=dpi / 72, grayscale=grey).to_pil()
    doc.close()
    return img.convert("L" if grey else "RGB")


def scan(pdf_bytes: bytes, rng: random.Random) -> bytes:
    img = _render(pdf_bytes, DPI["scan"], True)
    img = img.rotate(rng.uniform(-1.2, 1.2), resample=Image.BICUBIC, expand=False, fillcolor=255)
    a = np.asarray(img, dtype=np.float32)
    a = (a - 128) * rng.uniform(0.9, 1.1) + 128 + rng.uniform(-8, 8)
    nrng = np.random.default_rng(rng.randrange(2**32))
    a += nrng.normal(0, rng.uniform(4, 9), a.shape)
    out = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), "L")
    buf = io.BytesIO()
    fixed = time.strptime("2026-11-01", "%Y-%m-%d")                          # no build time in the file
    out.save(buf, format="PDF", resolution=DPI["scan"], creationDate=fixed, modDate=fixed)
    return buf.getvalue()


def _coeffs(src, dst):
    m = []
    for (x, y), (u, v) in zip(dst, src, strict=True):
        m.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        m.append([0, 0, 0, x, y, 1, -v * x, -v * y])
    return np.linalg.solve(np.array(m, dtype=float), np.array(src, dtype=float).reshape(8)).tolist()


def photo(pdf_bytes: bytes, rng: random.Random) -> bytes:
    page = _render(pdf_bytes, DPI["photo"], False)
    w, h = page.size
    pad = int(0.08 * max(w, h))
    bg_col = tuple(int(c) for c in rng.choice([(122, 92, 64), (180, 170, 155), (60, 62, 66), (205, 200, 190)]))
    W, H = w + 2 * pad, h + 2 * pad
    canvas = Image.new("RGB", (W, H), bg_col)
    canvas.paste(page, (pad, pad))
    j = 0.05 * min(w, h)
    corners = [(pad, pad), (pad + w, pad), (pad + w, pad + h), (pad, pad + h)]
    moved = [(x + rng.uniform(-j, j), y + rng.uniform(-j, j)) for x, y in corners]
    warped = canvas.transform((W, H), Image.PERSPECTIVE, _coeffs(corners, moved), Image.BICUBIC, fillcolor=bg_col)
    a = np.asarray(warped, dtype=np.float32)
    gx = np.linspace(rng.uniform(0.75, 0.95), rng.uniform(0.98, 1.08), W)[None, :, None]
    gy = np.linspace(rng.uniform(0.85, 1.0), rng.uniform(0.95, 1.05), H)[:, None, None]
    tint = np.array([1.0, rng.uniform(0.97, 1.0), rng.uniform(0.9, 0.98)])[None, None, :]
    out = Image.fromarray(np.clip(a * gx * gy * tint, 0, 255).astype(np.uint8), "RGB")
    out = out.filter(ImageFilter.GaussianBlur(rng.uniform(0.4, 0.9)))
    buf = io.BytesIO()
    out.save(buf, format="JPEG", quality=rng.choice([78, 82, 86]), optimize=False)
    return buf.getvalue()


def glyph_px(pdf_bytes: bytes, needle: str, dpi: int) -> float | None:
    """Height in pixels, at this dpi, of the smallest glyph of the first printed occurrence of `needle`."""
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(pdf_bytes)
    try:
        tp = doc[0].get_textpage()
        text = tp.get_text_range()
        i = text.find(needle)
        if i < 0 or not needle.strip():
            return None
        hs = []
        for k in range(i, i + len(needle)):
            if text[k].isalnum():
                _l, b, _r, t = tp.get_charbox(k)
                hs.append(t - b)
        return min(hs) * dpi / 72 if hs else None
    finally:
        doc.close()


def printed_token(kind: str, value, line: str) -> str | None:
    """The shortest run of words in `line` that prints `value` (so the label beside it isn't measured)."""
    from .visibility import TextIndex
    words = line.split()
    for n in range(1, 6):
        for i in range(len(words) - n + 1):
            cand = " ".join(words[i:i + n])
            if TextIndex([cand]).visible(kind, value):
                return cand
    return None


def make_variant(task: dict, pdf_bytes: bytes, seed: str) -> tuple[dict, bytes]:
    rng = random.Random(f"{seed}-{task['task_id']}-variant")
    cond = rng.choice(["scan", "photo"])
    data = scan(pdf_bytes, rng) if cond == "scan" else photo(pdf_bytes, rng)
    scale = DPI[cond] if cond == "scan" else DPI["photo"] * 0.95
    v = copy.deepcopy(task)
    v["task_id"] = v["doc_id"] = f"{task['task_id']}-{cond}"
    v["variant_of"] = task["task_id"]
    ext, media = ("pdf", "application/pdf") if cond == "scan" else ("jpg", "image/jpeg")
    v["document"] = {"path": f"docs/{v['task_id']}.{ext}", "media_type": media, "pages": 1, "condition": cond}
    v["variant"] = {"condition": cond, "seed": f"{seed}-{task['task_id']}-variant", "dpi": DPI[cond]}
    for p, r in v["fields"].items():
        if r["status"] != "present":
            continue
        ev = (r.get("evidence") or {}).get("text") or ""
        if r["match"] in ("array_objects", "array_scalars", "boolean") or not ev:
            continue
        needle = printed_token(r["match"], r.get("value"), ev)
        px = glyph_px(pdf_bytes, needle, scale) if needle else None
        if px is not None and px < MIN_GLYPH_PX:
            v["fields"][p] = {"status": "excluded", "value": None, "match": r["match"],
                              **({"item_match": r["item_match"]} if "item_match" in r else {}),
                              "provenance": r.get("provenance"),
                              "reason": f"printed {px:.1f} px high in the {cond}: too small to read"}
    return v, data
