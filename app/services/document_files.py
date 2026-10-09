"""
Rules for files uploaded in a workflow's file steps: which types are
allowed (checked from the file's content, not just its name), the size
limit, safe filenames, and how a file may be served back.

Only PDF, PNG and JPEG are shown in the browser ("viewable"); everything
else is always served as a download of an opaque type, so an uploaded file
can never run in the dashboard.
"""
from __future__ import annotations

import io
import re
import unicodedata
import zipfile
from dataclasses import dataclass
from urllib.parse import quote

MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB
MAX_UPLOAD_LABEL = "20 MB"

PDF = "application/pdf"
PNG = "image/png"
JPEG = "image/jpeg"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
CSV = "text/csv"

# Extension -> the type the file's content must be.
ALLOWED_EXTENSIONS = {
    ".pdf": PDF,
    ".png": PNG,
    ".jpg": JPEG,
    ".jpeg": JPEG,
    ".docx": DOCX,
    ".xlsx": XLSX,
    ".csv": CSV,
}
ALLOWED_LABEL = "PDF, PNG, JPEG, Word (.docx), Excel (.xlsx) or CSV"

# Shown in the browser's viewer; everything else is downloaded.
VIEWABLE_TYPES = frozenset({PDF, PNG, JPEG})

MAX_FILENAME_LENGTH = 150


class UploadRejected(ValueError):
    """The file can't be accepted; the message is shown to the user."""


@dataclass(frozen=True)
class CheckedUpload:
    filename: str
    content_type: str


def safe_filename(name: str | None) -> str:
    """
    The uploaded file's name without any folder, control characters or
    characters that are awkward in a download header; at most 150
    characters, keeping the extension.
    """
    name = (name or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = unicodedata.normalize("NFC", name)
    name = "".join(ch for ch in name if unicodedata.category(ch)[0] != "C")
    name = re.sub(r'[<>:"|?*]', "_", name).strip().strip(".")
    if not name:
        return "upload"
    stem, dot, extension = name.rpartition(".")
    if not dot:
        return name[:MAX_FILENAME_LENGTH]
    return f"{stem[: MAX_FILENAME_LENGTH - len(extension) - 1]}.{extension}"


def _extension(filename: str) -> str:
    _, dot, extension = filename.rpartition(".")
    return f".{extension.lower()}" if dot else ""


def _office_type(content: bytes) -> str | None:
    """DOCX or XLSX (zip archives with a word/ or xl/ part), else None."""
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            names = archive.namelist()
    except zipfile.BadZipFile:
        return None
    if "[Content_Types].xml" not in names:
        return None
    if any(name.startswith("word/") for name in names):
        return DOCX
    if any(name.startswith("xl/") for name in names):
        return XLSX
    return None


def _is_text(content: bytes) -> bool:
    if b"\x00" in content:
        return False
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            content.decode(encoding)
            return True
        except UnicodeDecodeError:
            continue
    return False


def detected_type(content: bytes) -> str | None:
    """The file's real type from its content, if it's one we accept."""
    if content.startswith(b"%PDF-"):
        return PDF
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return PNG
    if content.startswith(b"\xff\xd8\xff"):
        return JPEG
    if content.startswith(b"PK\x03\x04"):
        return _office_type(content)
    if content and _is_text(content):
        return CSV
    return None


def check_upload(filename: str | None, content: bytes) -> CheckedUpload:
    """
    Accept the file only if its extension is allowed, its content is that
    type, and it's within the size limit. Its stored type comes from this
    check, never from what the browser claimed.
    """
    name = safe_filename(filename)
    if not content:
        raise UploadRejected("The file is empty.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise UploadRejected(f"The file is larger than {MAX_UPLOAD_LABEL}.")
    expected = ALLOWED_EXTENSIONS.get(_extension(name))
    if expected is None:
        raise UploadRejected(f"Upload a {ALLOWED_LABEL} file.")
    if detected_type(content) != expected:
        raise UploadRejected(
            f"The file's content doesn't match its name ({_extension(name)}). Upload a {ALLOWED_LABEL} file."
        )
    return CheckedUpload(filename=name, content_type=expected)


def is_viewable(content_type: str | None) -> bool:
    return content_type in VIEWABLE_TYPES


def content_disposition(disposition: str, filename: str) -> str:
    """A Content-Disposition header with an ASCII fallback and the UTF-8 name (RFC 6266)."""
    fallback = unicodedata.normalize("NFKD", filename).encode("ascii", "ignore").decode() or "download"
    fallback = re.sub(r'["\\\r\n]', "_", fallback)
    return f"{disposition}; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename, safe='')}"


# Headers on every served file: the browser must use the given type, may not
# run anything in it, and must not keep a copy.
FILE_RESPONSE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "sandbox; default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'",
    "Cache-Control": "private, no-store",
}
