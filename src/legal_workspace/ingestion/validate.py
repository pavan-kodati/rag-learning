"""Upload validation: size, content sniffing (not just extensions), filename safety."""

from __future__ import annotations

import io
import re
import unicodedata
import zipfile
from dataclasses import dataclass

from ..errors import PayloadTooLarge, UnsupportedMedia, ValidationFailed

MAX_ZIP_UNCOMPRESSED = 300 * 1024 * 1024
ALLOWED_DESCRIPTION = "PDF, DOCX, TXT/MD, EML or a PNG/JPEG/TIFF scan"


@dataclass(frozen=True)
class UploadInfo:
    kind: str  # pdf | docx | txt | eml | image
    mime: str
    ext: str
    clean_name: str


def sanitize_filename(name: str | None) -> str:
    """Basename only; no path separators, control characters or leading dots; bounded length."""
    base = (name or "").replace("\\", "/").split("/")[-1]
    base = unicodedata.normalize("NFKC", base)
    base = re.sub(r"[\x00-\x1f\x7f]", "", base)
    base = re.sub(r"[^\w.\- ()\[\]]+", "_", base, flags=re.UNICODE).strip(" .")
    if not base:
        return "document"
    stem, dot, ext = base.rpartition(".")
    if not dot:
        return base[:120]
    return (stem[: 120 - len(ext) - 1] + "." + ext) if len(base) > 120 else base


_EXECUTABLE_MAGIC = (b"MZ", b"\x7fELF", b"#!", b"\xca\xfe\xba\xbe", b"\xfe\xed\xfa", b"\xcf\xfa\xed\xfe")
_HEADER = re.compile(rb"(?im)^(from|to|subject|date|message-id|mime-version):")


def _looks_text(data: bytes) -> bool:
    if b"\x00" in data[:4096]:
        return False
    sample = data[:20000]
    try:
        sample.decode("utf-8")
        return True
    except UnicodeDecodeError:
        try:
            sample.decode("cp1252")
            return True
        except UnicodeDecodeError:
            return False


def sniff(data: bytes, filename: str | None, max_bytes: int) -> UploadInfo:
    name = sanitize_filename(filename)
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if not data:
        raise ValidationFailed("the file is empty")
    if len(data) > max_bytes:
        raise PayloadTooLarge(
            f"the file is {len(data) // (1024 * 1024)} MB; the limit is {max_bytes // (1024 * 1024)} MB"
        )
    head = data[:2048]
    if any(head.startswith(m) for m in _EXECUTABLE_MAGIC):
        raise UnsupportedMedia(
            f"executable or script content is not accepted. Allowed: {ALLOWED_DESCRIPTION}"
        )
    if b"%PDF-" in data[:1024]:
        if ext not in ("pdf", ""):
            raise UnsupportedMedia(f"{name!r} contains a PDF but is named .{ext}")
        return UploadInfo("pdf", "application/pdf", "pdf", name)
    if head.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                if sum(i.file_size for i in z.infolist()) > MAX_ZIP_UNCOMPRESSED:
                    raise UnsupportedMedia("the archive expands to an unreasonable size")
                names = set(z.namelist())
        except zipfile.BadZipFile as e:
            raise UnsupportedMedia("the file is a corrupt archive") from e
        if "word/document.xml" in names:
            return UploadInfo(
                "docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "docx",
                name,
            )
        raise UnsupportedMedia(
            f"archives and other Office formats are not accepted. Allowed: {ALLOWED_DESCRIPTION}"
        )
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return UploadInfo("image", "image/png", "png", name)
    if head.startswith(b"\xff\xd8\xff"):
        return UploadInfo("image", "image/jpeg", "jpg", name)
    if head[:4] in (b"II*\x00", b"MM\x00*"):
        return UploadInfo("image", "image/tiff", "tiff", name)
    if _looks_text(data):
        if ext in ("pdf", "docx", "png", "jpg", "jpeg", "tif", "tiff"):
            raise UnsupportedMedia(f"{name!r} is named .{ext} but its content is plain text")
        if ext == "eml" or (_HEADER.search(head) and ext in ("", "txt", "eml")):
            return UploadInfo("eml", "message/rfc822", "eml", name)
        return UploadInfo("txt", "text/plain", "txt" if ext != "md" else "md", name)
    raise UnsupportedMedia(f"unrecognised file content. Allowed: {ALLOWED_DESCRIPTION}")
