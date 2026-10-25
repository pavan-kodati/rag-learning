"""PDF text, character boxes and OCR (blueprint §7.2). pypdfium2 (Apache/BSD) + Tesseract (Apache).

Every page becomes `PageContent`: text plus one bounding box per character (top-left origin, PDF points),
which lets any character range (a chunk, a quote) be highlighted in the viewer.
"""

from __future__ import annotations

import io
import logging
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import pypdfium2 as pdfium

from ..errors import ParseError

log = logging.getLogger(__name__)
Rect = tuple[float, float, float, float]  # x0, y0, x1, y1 (top-left origin)

MAX_PAGES = 400


@dataclass
class PageContent:
    number: int
    text: str
    width: float
    height: float
    method: str = "DIGITAL"  # DIGITAL | OCR
    ocr_confidence: float | None = None
    char_rects: list[Rect | None] = field(default_factory=list)


def tesseract_available() -> bool:
    return shutil.which("tesseract") is not None


def open_pdf(source: bytes | str | Path) -> pdfium.PdfDocument:
    try:
        pdf = pdfium.PdfDocument(source)
    except pdfium.PdfiumError as e:
        msg = str(e).lower()
        if "password" in msg:
            raise ParseError("the PDF is password-protected; remove the password and upload again") from e
        raise ParseError("the file is not a readable PDF (corrupt or truncated)") from e
    if len(pdf) == 0:
        raise ParseError("the PDF has no pages")
    if len(pdf) > MAX_PAGES:
        raise ParseError(f"the PDF has {len(pdf)} pages; the limit is {MAX_PAGES}")
    return pdf


def _clean(raw: str) -> tuple[str, list[int]]:
    """Normalise line endings and drop control characters; returns text and raw index of each kept char."""
    out: list[str] = []
    idx: list[int] = []
    i, n = 0, len(raw)
    while i < n:
        ch = raw[i]
        if ch == "\r":
            if i + 1 < n and raw[i + 1] == "\n":
                i += 1
                continue
            ch = "\n"
        elif ch in " ":
            ch = " "
        elif ch < " " and ch not in "\n\t":
            i += 1
            continue
        out.append(ch)
        idx.append(i)
        i += 1
    return "".join(out), idx


def _page_digital(page: pdfium.PdfPage, number: int) -> PageContent:
    width, height = page.get_size()
    tp = page.get_textpage()
    try:
        raw = tp.get_text_range()
        text, raw_idx = _clean(raw)
        rects: list[Rect | None] = []
        for ri in raw_idx:
            try:
                left, b, r, t = tp.get_charbox(ri)
            except Exception:  # noqa: BLE001
                rects.append(None)
                continue
            if r - left <= 0.01 or t - b <= 0.01:
                rects.append(None)
            else:
                rects.append((left, height - t, r, height - b))
    finally:
        tp.close()
    return PageContent(number, text, width, height, "DIGITAL", None, rects)


def render_page_image(source: bytes | str | Path, page_number: int, scale: float = 2.0):  # noqa: ANN201
    """PIL image of one page (1-based)."""
    pdf = open_pdf(source)
    if not 1 <= page_number <= len(pdf):
        raise ParseError(f"page {page_number} out of range 1..{len(pdf)}")
    return pdf[page_number - 1].render(scale=scale).to_pil()


def _preprocess(img):  # noqa: ANN001, ANN202
    from PIL import ImageOps

    g = ImageOps.grayscale(img)
    g = ImageOps.autocontrast(g, cutoff=1)
    return g


def _page_ocr(page: pdfium.PdfPage, number: int, scale: float = 3.0, lang: str = "eng") -> PageContent:
    import pytesseract

    width, height = page.get_size()
    img = _preprocess(page.render(scale=scale).to_pil())
    data = pytesseract.image_to_data(img, lang=lang, config="--psm 6", output_type=pytesseract.Output.DICT)
    lines: dict[tuple[int, int, int], list[int]] = {}
    for i, word in enumerate(data["text"]):
        if not word.strip():
            continue
        lines.setdefault((data["block_num"][i], data["par_num"][i], data["line_num"][i]), []).append(i)
    text_parts: list[str] = []
    rects: list[Rect | None] = []
    confs: list[float] = []
    for key in sorted(lines):
        words = lines[key]
        for j, i in enumerate(words):
            w = data["text"][i]
            box: Rect = (
                data["left"][i] / scale, data["top"][i] / scale,
                (data["left"][i] + data["width"][i]) / scale, (data["top"][i] + data["height"][i]) / scale,
            )  # fmt: skip
            if j:
                text_parts.append(" ")
                rects.append(None)
            text_parts.append(w)
            rects.extend([box] * len(w))
            try:
                c = float(data["conf"][i])
                if c >= 0:
                    confs.append(c)
            except (TypeError, ValueError):
                pass
        text_parts.append("\n")
        rects.append(None)
    text = "".join(text_parts).rstrip("\n")
    rects = rects[: len(text)]
    conf = sum(confs) / len(confs) if confs else 0.0
    return PageContent(number, text, width, height, "OCR", round(conf, 1), rects)


def parse_pdf(
    source: bytes | str | Path, ocr_min_chars: int = 25, ocr_enabled: bool = True
) -> tuple[list[PageContent], list[str]]:
    """Parse all pages. Returns (pages, warnings). Pages with almost no text layer are OCR'd when possible."""
    pdf = open_pdf(source)
    pages: list[PageContent] = []
    warnings: list[str] = []
    can_ocr = ocr_enabled and tesseract_available()
    for i in range(len(pdf)):
        page = pdf[i]
        pc = _page_digital(page, i + 1)
        if len(re.sub(r"\s", "", pc.text)) < ocr_min_chars:
            if can_ocr:
                try:
                    ocr = _page_ocr(page, i + 1)
                    if len(ocr.text.strip()) >= len(pc.text.strip()):
                        pc = ocr
                except Exception as e:  # noqa: BLE001
                    log.warning("OCR failed on page %d: %s", i + 1, e)
                    warnings.append(f"page {i + 1}: OCR failed ({e.__class__.__name__})")
                    pc.ocr_confidence = 0.0
            else:
                warnings.append(f"page {i + 1} has no text layer and OCR is unavailable (install Tesseract)")
                pc.ocr_confidence = 0.0
        pages.append(pc)
    return pages, warnings


def rects_for_range(page: PageContent, start: int, end: int) -> list[dict[str, float | int]]:
    """Merge character boxes of text[start:end] into one rectangle per visual line (top-left origin, points)."""
    start = max(0, start)
    end = min(end, len(page.char_rects))
    rows: list[list[float]] = []
    for r in page.char_rects[start:end]:
        if r is None:
            continue
        x0, y0, x1, y1 = r
        for row in rows:
            if min(y1, row[3]) - max(y0, row[1]) > 0.5 * min(y1 - y0, row[3] - row[1]):  # same visual line
                row[0], row[1], row[2], row[3] = (
                    min(row[0], x0),
                    min(row[1], y0),
                    max(row[2], x1),
                    max(row[3], y1),
                )
                break
        else:
            rows.append([x0, y0, x1, y1])
    return [
        {"page": page.number, "x0": round(a, 1), "y0": round(b, 1), "x1": round(c, 1), "y1": round(d, 1)}
        for a, b, c, d in sorted(rows, key=lambda r: (r[1], r[0]))
    ]


def page_png(source: bytes | str | Path, page_number: int, scale: float = 1.6) -> bytes:
    img = render_page_image(source, page_number, scale)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _norm_with_map(text: str) -> tuple[str, list[int]]:
    out: list[str] = []
    idx: list[int] = []
    prev_space = True
    for i, ch in enumerate(text):
        if ch.isspace():
            if not prev_space:
                out.append(" ")
                idx.append(i)
            prev_space = True
        else:
            out.append(ch.lower())
            idx.append(i)
            prev_space = False
    return "".join(out), idx


def find_quote_span(page_text: str, quote: str, threshold: int = 85) -> tuple[int, int] | None:
    """Character range of `quote` in `page_text`, ignoring case and whitespace differences; fuzzy for small OCR errors."""
    from rapidfuzz import fuzz

    t, idx = _norm_with_map(page_text)
    q = " ".join((quote or "").lower().split())
    if len(q) < 4 or not t:
        return None
    pos = t.find(q)
    if pos >= 0:
        return idx[pos], idx[pos + len(q) - 1] + 1
    al = fuzz.partial_ratio_alignment(q, t)
    if al and al.score >= threshold and al.dest_end > al.dest_start:
        return idx[al.dest_start], idx[min(al.dest_end, len(idx)) - 1] + 1
    return None


def highlight_rects(source: bytes | str | Path, page_number: int, quote: str) -> dict:
    """Rectangles (PDF points, top-left origin) covering `quote` on a digital page, plus the page size."""
    pdf = open_pdf(source)
    if not 1 <= page_number <= len(pdf):
        raise ParseError(f"page {page_number} out of range 1..{len(pdf)}")
    pc = _page_digital(pdf[page_number - 1], page_number)
    span = find_quote_span(pc.text, quote)
    rects = rects_for_range(pc, span[0], span[1]) if span else []
    return {"width": pc.width, "height": pc.height, "rects": rects, "found": bool(rects)}
