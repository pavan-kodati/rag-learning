"""S04: upload validation and conversion, including hostile and broken input."""

from __future__ import annotations

import io
import zipfile

import pytest

from legal_workspace.errors import ParseError, PayloadTooLarge, UnsupportedMedia, ValidationFailed
from legal_workspace.ingestion.convert import strip_quoted_replies, to_pdf
from legal_workspace.ingestion.pdfio import parse_pdf, tesseract_available
from legal_workspace.ingestion.validate import sanitize_filename, sniff
from tests.helpers import docx_bytes, encrypted_pdf, pdf, png_bytes, scanned_pdf

MAX = 5 * 1024 * 1024


# ------------------------------------------------------------------------------------ filenames
@pytest.mark.parametrize(
    "raw, expected",
    [
        ("agreement.pdf", "agreement.pdf"),
        ("../../etc/passwd", "passwd"),
        ("C:\\Users\\x\\notice.PDF", "notice.PDF"),
        ("a/b/c.docx", "c.docx"),
        ("  .hidden  ", "hidden"),
        ("na\x00me\x1f.pdf", "name.pdf"),
        ("", "document"),
        (None, "document"),
        ("...", "document"),
        ("weird<>|:name?.pdf", "weird_name_.pdf"),
        ("invoice (final) [2].pdf", "invoice (final) [2].pdf"),
    ],
)
def test_sanitize_filename(raw, expected):
    assert sanitize_filename(raw) == expected


def test_sanitize_filename_bounds_length_and_keeps_extension():
    out = sanitize_filename("x" * 500 + ".pdf")
    assert len(out) <= 120 and out.endswith(".pdf")


# --------------------------------------------------------------------------------------- sniff
def test_sniff_accepts_each_supported_kind():
    assert sniff(pdf("hello world"), "a.pdf", MAX).kind == "pdf"
    assert sniff(docx_bytes(["x"]), "a.docx", MAX).kind == "docx"
    assert sniff(b"plain text here", "a.txt", MAX).kind == "txt"
    assert sniff(b"# notes\ntext", "a.md", MAX).ext == "md"
    assert sniff(b"From: a@b.com\nSubject: hi\n\nbody", "mail.eml", MAX).kind == "eml"
    assert sniff(b"From: a@b.com\nSubject: hi\n\nbody", "mail", MAX).kind == "eml"
    assert sniff(png_bytes(), "scan.png", MAX).kind == "image"
    assert sniff(b"\xff\xd8\xff\xe0" + b"0" * 20, "scan.jpg", MAX).mime == "image/jpeg"
    assert sniff(b"II*\x00" + b"0" * 20, "scan.tif", MAX).mime == "image/tiff"


def test_sniff_trusts_content_not_extension_for_pdf_without_extension():
    assert sniff(pdf("x"), "noextension", MAX).kind == "pdf"


@pytest.mark.parametrize(
    "data, name",
    [
        (b"MZ\x90\x00" + b"0" * 100, "invoice.pdf"),  # Windows executable renamed
        (b"\x7fELF" + b"0" * 100, "report.pdf"),
        (b"#!/bin/sh\nrm -rf /", "notes.txt"),
        (b"\x00\x01\x02\x03" * 100, "data.bin"),  # binary garbage
    ],
)
def test_sniff_rejects_executables_and_binary(data, name):
    with pytest.raises(UnsupportedMedia):
        sniff(data, name, MAX)


def test_sniff_rejects_empty_and_oversized():
    with pytest.raises(ValidationFailed):
        sniff(b"", "a.pdf", MAX)
    with pytest.raises(PayloadTooLarge):
        sniff(b"a" * (MAX + 1), "a.txt", MAX)


def test_sniff_rejects_extension_content_mismatch():
    with pytest.raises(UnsupportedMedia):
        sniff(b"just text", "fake.pdf", MAX)
    with pytest.raises(UnsupportedMedia):
        sniff(pdf("x"), "actually.docx", MAX)


def test_sniff_rejects_other_zip_archives_and_corrupt_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("hello.txt", "x")
    with pytest.raises(UnsupportedMedia):
        sniff(buf.getvalue(), "archive.zip", MAX)
    with pytest.raises(UnsupportedMedia):
        sniff(b"PK\x03\x04garbage-not-a-zip", "a.docx", MAX)


# ------------------------------------------------------------------------------------- convert
def test_convert_pdf_passthrough_and_corrupt_pdf():
    data = pdf("some text")
    assert to_pdf(sniff(data, "a.pdf", MAX), data).pdf == data
    bad = b"%PDF-1.4\n garbage that is not a pdf"
    with pytest.raises(ParseError):
        to_pdf(sniff(bad, "a.pdf", MAX), bad)


def test_convert_encrypted_pdf_is_a_clear_error():
    data = encrypted_pdf()
    with pytest.raises(ParseError) as ei:
        to_pdf(sniff(data, "locked.pdf", MAX), data)
    assert "password" in ei.value.detail


def test_convert_text_gets_pages_and_keeps_rupee_sign():
    data = "AGREEMENT\n1. Price is ₹18,40,000.".encode()
    c = to_pdf(sniff(data, "a.txt", MAX), data)
    pages, _ = parse_pdf(c.pdf)
    assert "₹18,40,000" in pages[0].text or "Rs. 18,40,000" in pages[0].text


def test_convert_whitespace_only_text_is_rejected():
    with pytest.raises(ParseError):
        to_pdf(sniff(b"   \n\n  ", "a.txt", MAX), b"   \n\n  ")


def test_convert_cp1252_text():
    data = "Caf\xe9 payment of Rs. 5,000".encode("cp1252")
    pages, _ = parse_pdf(to_pdf(sniff(data, "a.txt", MAX), data).pdf)
    assert "Caf" in pages[0].text


def test_convert_long_text_paginates():
    data = ("line of text\n" * 200).encode()
    pages, _ = parse_pdf(to_pdf(sniff(data, "a.txt", MAX), data).pdf)
    assert len(pages) >= 3


def test_convert_docx_falls_back_or_converts():
    data = docx_bytes(["MASTER SERVICES AGREEMENT", "1. Delivery on 30 June 2024."])
    c = to_pdf(sniff(data, "a.docx", MAX), data)
    pages, _ = parse_pdf(c.pdf)
    assert "30 June 2024" in "".join(p.text for p in pages)


def test_convert_empty_docx_yields_no_text():
    """An empty Word file converts to a blank PDF (or is rejected); either way no text reaches the pipeline."""
    data = docx_bytes([])
    try:
        pages, _ = parse_pdf(to_pdf(sniff(data, "a.docx", MAX), data).pdf, ocr_enabled=False)
    except ParseError:
        return
    assert sum(len(p.text.strip()) for p in pages) < 20


EML = b"""From: Rao <rao@vardhan.example>
To: Mehta <mehta@kestrel.example>
Date: Mon, 20 May 2024 10:00:00 +0530
Subject: Revised delivery date
MIME-Version: 1.0
Content-Type: text/plain

Please confirm delivery moves to 15 August 2024.

> On 19 May Mehta wrote:
> Delivery is 30 June.
"""


def test_convert_eml_strips_quoted_replies_and_keeps_headers():
    c = to_pdf(sniff(EML, "m.eml", MAX), EML)
    text = parse_pdf(c.pdf)[0][0].text
    assert "Subject: Revised delivery date" in text and "15 August 2024" in text
    assert "Delivery is 30 June" not in text


def test_convert_eml_with_attachment_returns_it():
    import email.message

    m = email.message.EmailMessage()
    m["From"], m["To"], m["Subject"] = "a@x.com", "b@y.com", "see attached"
    m.set_content("Attached is the invoice.")
    m.add_attachment(pdf("INVOICE INV-014"), maintype="application", subtype="pdf", filename="../../inv.pdf")
    c = to_pdf(sniff(m.as_bytes(), "m.eml", MAX), m.as_bytes())
    assert [n for n, _ in c.attachments] == ["inv.pdf"]  # path traversal stripped


def test_convert_html_only_email():
    import email.message

    m = email.message.EmailMessage()
    m["From"], m["Subject"] = "a@x.com", "html"
    m.set_content(
        "<html><body><p>Pay <b>Rs. 5,000</b> now</p><script>evil()</script></body></html>", subtype="html"
    )
    text = parse_pdf(to_pdf(sniff(m.as_bytes(), "m.eml", MAX), m.as_bytes()).pdf)[0][0].text
    assert "Rs. 5,000" in text and "evil" not in text


@pytest.mark.parametrize(
    "body, kept",
    [
        ("Hi\n> old\n> older\nBye", "Hi\nBye"),
        ("New text\n\nOn Tue, 3 Jan 2023, X <x@y> wrote:\n> old", "New text"),
        ("Reply\n-----Original Message-----\nFrom: a", "Reply"),
        ("", ""),
    ],
)
def test_strip_quoted_replies(body, kept):
    assert strip_quoted_replies(body) == kept


@pytest.mark.skipif(not tesseract_available(), reason="tesseract not installed")
def test_ocr_reads_a_scanned_page_and_reports_confidence():
    data = scanned_pdf("# INVOICE\nInvoice No. INV-014\nAmount payable Rs. 18,40,000\nDue date 30 April 2025")
    pages, warnings = parse_pdf(data)
    assert pages[0].method == "OCR" and pages[0].ocr_confidence and pages[0].ocr_confidence > 50
    text = pages[0].text.upper()
    assert "INV" in text and "18,40,000" in pages[0].text
    # every OCR character maps to a box (or None for spaces / newlines)
    assert len(pages[0].char_rects) == len(pages[0].text)
    assert warnings == []


@pytest.mark.skipif(not tesseract_available(), reason="tesseract not installed")
def test_image_upload_goes_through_ocr():
    data = png_bytes("# NOTICE\nPlease pay Rs. 6,00,000 within 30 days")
    c = to_pdf(sniff(data, "scan.png", MAX), data)
    pages, _ = parse_pdf(c.pdf)
    assert "6,00,000" in pages[0].text


def test_scanned_page_without_ocr_is_flagged_not_crashed():
    data = scanned_pdf("# INVOICE\nInvoice No. INV-014")
    pages, warnings = parse_pdf(data, ocr_enabled=False)
    assert pages[0].text.strip() == "" and pages[0].ocr_confidence == 0.0
    assert warnings and "OCR" in warnings[0]


def test_blank_pdf_page_yields_empty_text_not_an_error():
    pages, _ = parse_pdf(pdf(""), ocr_enabled=False)
    assert len(pages) == 1
