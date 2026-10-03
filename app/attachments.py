"""Uploaded files: type checks, storage on disk, and what the model gets to see for each one.

Three kinds, decided from the bytes (never the client's filename or content type):
image (PNG, JPEG, GIF, WebP) goes to the model as an image, text (UTF-8) is inlined as text, and a PDF is
either inlined as its extracted text or sent as a native file, see Settings.openai_pdf_input.
"""
from pathlib import Path

import filetype
from pypdf import PdfReader
from pypdf.errors import PyPdfError

MB = 1024 * 1024
MAX_FILES = 5  # per message
LIMITS = {"image": 10 * MB, "pdf": 20 * MB, "text": 256 * 1024}  # bytes, per kind
MAX_TEXT_CHARS = 200_000  # what the model gets from one text file or PDF
IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
LABELS = {"image": "Images", "pdf": "PDFs", "text": "Text files"}


class Rejected(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def classify(data: bytes) -> tuple[str, str]:
    """(kind, mime) for an upload, or Rejected."""
    if not data:
        raise Rejected(422, "That file is empty.")
    guess = filetype.guess(data)
    if guess and guess.mime in IMAGE_TYPES:
        kind, mime = "image", guess.mime
    elif guess and guess.mime == "application/pdf":
        kind, mime = "pdf", guess.mime
    elif guess is None and _is_text(data):
        kind, mime = "text", "text/plain"
    else:
        raise Rejected(415, "Unsupported file type. Attach an image (PNG, JPEG, GIF, WebP), a PDF, or a text file.")
    if len(data) > LIMITS[kind]:
        raise Rejected(413, f"{LABELS[kind]} can be at most {LIMITS[kind] / MB:g} MB.")
    return kind, mime


def _is_text(data: bytes) -> bool:
    try:
        return "\x00" not in data.decode("utf-8")
    except UnicodeDecodeError:
        return False


def path(directory: str, aid: str) -> Path:
    return Path(directory) / aid


def save(directory: str, aid: str, data: bytes) -> None:
    Path(directory).mkdir(parents=True, exist_ok=True)
    path(directory, aid).write_bytes(data)


def delete_files(directory: str, ids: list[str]) -> None:
    for aid in ids:
        path(directory, aid).unlink(missing_ok=True)
        path(directory, aid).with_suffix(".txt").unlink(missing_ok=True)


def pdf_to_text(source, max_pages: int | None = None) -> str:
    """The text of a PDF (a path or a file object), the first `max_pages` pages of it if that is given. Rejected if
    it can't be read, is password-protected, or has no text."""
    try:
        reader = PdfReader(source)
        if reader.is_encrypted and not reader.decrypt(""):
            raise Rejected(422, "That PDF is password-protected.")
        pages = list(reader.pages) if max_pages is None else list(reader.pages[:max_pages])
        text = "\n\n".join(page.extract_text() for page in pages).strip()
        total = len(reader.pages)
    except PyPdfError as e:
        raise Rejected(422, "Couldn't read that PDF.") from e
    if not text:
        raise Rejected(422, "That PDF has no text to read (it may be scanned images).")
    if total > len(pages):
        text += f"\n\n[Only the first {len(pages)} of {total} pages were read.]"
    return text


def pdf_text(directory: str, aid: str) -> str:
    """The text of a stored PDF, extracted once and cached next to it. Rejected if there is none to read."""
    cache = path(directory, aid).with_suffix(".txt")
    if cache.exists():
        return cache.read_text(encoding="utf-8")
    text = pdf_to_text(path(directory, aid))
    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS] + "\n[Text truncated.]"
    cache.write_text(text, encoding="utf-8")
    return text


def for_model(attachment: dict, directory: str, pdf_input: str) -> dict:
    """One stored attachment as llm.py wants it: {"kind": "image" | "file" | "text", "name", ...}."""
    name, file = attachment["name"], path(directory, attachment["id"])
    try:
        match attachment["kind"]:
            case "image":
                return {"kind": "image", "name": name, "mime": attachment["mime"], "path": str(file)}
            case "pdf" if pdf_input == "file":
                return {"kind": "file", "name": name, "mime": attachment["mime"], "path": str(file)}
            case "pdf":
                return {"kind": "text", "name": name, "text": pdf_text(directory, attachment["id"])}
            case _:
                text = file.read_text(encoding="utf-8")
                if len(text) > MAX_TEXT_CHARS:
                    text = text[:MAX_TEXT_CHARS] + "\n[Text truncated.]"
                return {"kind": "text", "name": name, "text": text}
    except (OSError, Rejected):  # file gone from disk, or a PDF that can't be read: say so, don't fail the turn
        return {"kind": "text", "name": name, "text": "[This attachment is no longer available.]"}
