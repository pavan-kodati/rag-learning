"""Plain text -> paginated PDF, so every document (TXT, EML, DOCX fallback, synthetic matters) has pages to cite.

Deterministic output (reportlab `invariant=1`). Uses DejaVu Sans when installed (it has the rupee sign);
otherwise Helvetica with the rupee sign spelled "Rs.".
"""

from __future__ import annotations

import io
import threading
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

_FONT_CANDIDATES = (
    (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ),
    ("/usr/share/fonts/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"),
    ("/Library/Fonts/DejaVuSans.ttf", "/Library/Fonts/DejaVuSans-Bold.ttf"),
)
_lock = threading.Lock()
_fonts: tuple[str, str, bool] | None = None


def _register_fonts() -> tuple[str, str, bool]:
    """(regular, bold, supports_rupee)"""
    global _fonts
    with _lock:
        if _fonts is None:
            for reg, bold in _FONT_CANDIDATES:
                if Path(reg).exists() and Path(bold).exists():
                    pdfmetrics.registerFont(TTFont("LW-Sans", reg))
                    pdfmetrics.registerFont(TTFont("LW-Sans-Bold", bold))
                    _fonts = ("LW-Sans", "LW-Sans-Bold", True)
                    break
            else:
                _fonts = ("Helvetica", "Helvetica-Bold", False)
        return _fonts


def _safe(text: str, rupee_ok: bool) -> str:
    if not rupee_ok:
        text = text.replace("₹", "Rs. ")
        text = text.encode("latin-1", "replace").decode("latin-1")
    return text


def text_to_pdf(text: str, *, title: str = "", footer: bool = True, font_size: float = 10.0) -> bytes:
    """Render `text` (one logical line per input line; long lines wrap) onto A4 pages."""
    regular, bold, rupee_ok = _register_fonts()
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4, invariant=1, pageCompression=0)
    c.setTitle(title or "document")
    width, height = A4
    left, right, top, bottom = 56.0, 56.0, 60.0, 64.0
    leading = font_size * 1.45
    usable = width - left - right
    y = height - top
    page_no = 1

    def new_page() -> None:
        nonlocal y, page_no
        if footer:
            c.setFont(regular, 8)
            c.drawCentredString(width / 2, 32, f"Page {page_no}")
        c.showPage()
        page_no += 1
        y = height - top

    for raw in (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        heading = raw.startswith("# ")
        line = _safe(raw[2:] if heading else raw, rupee_ok)
        font = bold if heading else regular
        size = font_size + (2 if heading else 0)
        pieces = simpleSplit(line, font, size, usable) if line.strip() else [""]
        for piece in pieces:
            if y < bottom:
                new_page()
            c.setFont(font, size)
            c.drawString(left, y, piece)
            y -= leading if piece or not heading else leading
    if footer:
        c.setFont(regular, 8)
        c.drawCentredString(width / 2, 32, f"Page {page_no}")
    c.showPage()
    c.save()
    return buf.getvalue()
