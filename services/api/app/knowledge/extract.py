"""Content sniffing and text extraction for PDF and DOCX (T060, research R11, R12).

``sniff(data)`` decides the type from the bytes, never from the file name: ``%PDF-`` is a PDF, a
ZIP archive holding ``word/document.xml`` is a DOCX. ``extract(data, file_type)`` returns blocks
in reading order (headings, paragraphs and table rows) with their page numbers, or raises
:class:`ExtractError` with a permanent ``error_code``.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, field
from typing import Literal

BlockKind = Literal["heading", "text", "table_row"]
MIN_CHARS_PER_PAGE = 50
_SPACES = re.compile(r"[ \t ]+")


class ExtractError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Block:
    kind: BlockKind
    text: str
    page: int | None = None


@dataclass
class Extracted:
    file_type: str
    page_count: int | None
    blocks: list[Block] = field(default_factory=list)

    @property
    def char_count(self) -> int:
        return sum(len(b.text) for b in self.blocks)


def sniff(data: bytes) -> str | None:
    """``pdf``, ``docx`` or None for anything else."""
    if data[:1024].lstrip().startswith(b"%PDF-"):
        return "pdf"
    if data[:4] == b"PK\x03\x04":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                if "word/document.xml" in archive.namelist():
                    return "docx"
        except zipfile.BadZipFile:
            return None
    return None


def _clean(text: str) -> str:
    return _SPACES.sub(" ", text).strip()


def _looks_like_heading(line: str, next_line: str | None) -> bool:
    """PDF text has no styles: a short line without closing punctuation followed by text."""
    if not line or next_line is None or len(line) > 70 or len(line.split()) > 10:
        return False
    if line[-1] in ".,;:?!)" or line.startswith(("-", "*", "•")):
        return False
    return line[0].isupper() or line[0].isdigit()


def _pdf(data: bytes) -> Extracted:
    from pypdf import PdfReader
    from pypdf.errors import FileNotDecryptedError, PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            try:
                if not reader.decrypt(""):
                    raise ExtractError("encrypted_file", "The PDF is password protected.")
            except (FileNotDecryptedError, NotImplementedError) as exc:
                raise ExtractError("encrypted_file", "The PDF is password protected.") from exc
        pages = list(reader.pages)
        out = Extracted("pdf", len(pages))
        for number, page in enumerate(pages, start=1):
            text = page.extract_text() or ""
            lines = [_clean(raw) for raw in text.splitlines()]
            lines = [line for line in lines if line]
            paragraph: list[str] = []
            for i, line in enumerate(lines):
                following = lines[i + 1] if i + 1 < len(lines) else None
                if _looks_like_heading(line, following) and not paragraph:
                    out.blocks.append(Block("heading", line, number))
                    continue
                paragraph.append(line)
                if line.endswith((".", "?", "!", ":")) or following is None:
                    out.blocks.append(Block("text", " ".join(paragraph), number))
                    paragraph = []
            if paragraph:
                out.blocks.append(Block("text", " ".join(paragraph), number))
        return out
    except ExtractError:
        raise
    except FileNotDecryptedError as exc:
        raise ExtractError("encrypted_file", "The PDF is password protected.") from exc
    except (PdfReadError, ValueError, KeyError, TypeError, AttributeError, OSError) as exc:
        raise ExtractError("corrupt_file", "The PDF could not be read; it may be damaged.") from exc


def _docx(data: bytes) -> Extracted:
    from docx import Document as load_docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    try:
        document = load_docx(io.BytesIO(data))
    except Exception as exc:  # python-docx raises a variety of zip and XML errors
        raise ExtractError("corrupt_file", "The DOCX file could not be read; it may be damaged.") from exc
    out = Extracted("docx", None)
    body = document.element.body
    for child in body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            paragraph = Paragraph(child, document)
            text = _clean(paragraph.text)
            if not text:
                continue
            style = (paragraph.style.name if paragraph.style is not None else "") or ""
            kind: BlockKind = "heading" if style.startswith(("Heading", "Title")) else "text"
            out.blocks.append(Block(kind, text))
        elif tag == "tbl":
            table = Table(child, document)
            for row in table.rows:
                cells: list[str] = []
                for cell in row.cells:
                    value = _clean(cell.text)
                    if value and (not cells or cells[-1] != value):
                        cells.append(value)
                if cells:
                    out.blocks.append(Block("table_row", " | ".join(cells)))
    return out


def extract(data: bytes, file_type: str) -> Extracted:
    result = _pdf(data) if file_type == "pdf" else _docx(data)
    pages = result.page_count or 1
    if result.char_count / pages < MIN_CHARS_PER_PAGE:
        raise ExtractError(
            "no_extractable_text",
            "Too little text could be read. Scanned documents are not supported; upload a text PDF or DOCX.",
        )
    return result
