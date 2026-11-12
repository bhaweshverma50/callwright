"""Real PDF and DOCX bytes for the fake Drive (022), so synced files go through 005's extraction.

``make_docx`` is not byte-stable (python-docx stamps the core properties), which is exactly how
Google Docs exports behave; the sync's text check (research R2) has to see through it.
"""

from __future__ import annotations

import io


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_pdf(pages: list[list[str]]) -> bytes:
    """A small valid PDF with one Helvetica text line per entry."""
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    page_ids: list[int] = []
    for lines in pages:
        ops = ["BT", "/F1 11 Tf", "14 TL", "50 780 Td", *(f"({_escape(line)}) Tj T*" for line in lines), "ET"]
        stream = "\n".join(ops).encode("latin-1")
        objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        content_id = len(objects)
        objects.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 842] /Resources << /Font << /F1 3 0 R >> >> "
            b"/Contents %d 0 R >>" % content_id
        )
        page_ids.append(len(objects))
    kids = " ".join(f"{p} 0 R" for p in page_ids).encode()
    objects[1] = b"<< /Type /Pages /Kids [" + kids + b"] /Count %d >>" % len(page_ids)
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n" % number + body + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1))
    for offset in offsets:
        out.write(b"%010d 00000 n \n" % offset)
    out.write(b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref))
    return out.getvalue()


def make_docx(title: str, paragraphs: list[str]) -> bytes:
    from docx import Document

    doc = Document()
    doc.add_heading(title, level=1)
    for text in paragraphs:
        doc.add_paragraph(text)
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()
