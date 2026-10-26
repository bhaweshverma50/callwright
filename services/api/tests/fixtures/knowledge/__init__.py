"""Knowledge fixtures (005 T004), built in code so no binary files are checked in.

* ``refund_policy_pdf()``: two text pages with a "14 days" refund clause under a heading.
* ``policies_docx()``: headings, paragraphs and a price table.
* ``scanned_pdf()``: pages without a text layer (``no_extractable_text``).
* ``encrypted_pdf()``: password protected (``encrypted_file``).
* ``notes_renamed_pdf()``: a DOCX named ``.pdf`` (sniffed by content, so it is a DOCX).
* ``oversize(size)``: a PDF header followed by padding, 21 MB by default (``make_oversize.py``).
"""

from __future__ import annotations

import io

REFUND_PAGES = [
    [
        "Refund Policy",
        "Patients may request a refund for prepaid treatment plans within 14 days of purchase.",
        "Refunds are paid to the original card and take up to five business days to arrive.",
        "Opened hygiene kits cannot be refunded once they leave the clinic.",
    ],
    [
        "Cancellations",
        "Appointments cancelled with less than 24 hours notice are charged a 40 dollar fee.",
        "The fee is waived for medical emergencies when a note from a doctor is provided.",
    ],
]


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_pdf(pages: list[list[str]]) -> bytes:
    """A small valid PDF with one Helvetica text line per entry."""
    objects: list[bytes] = []
    page_ids: list[int] = []
    font_id = 3
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(b"")  # pages tree, filled below
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for lines in pages:
        ops = ["BT", "/F1 11 Tf", "14 TL", "50 780 Td"]
        for line in lines:
            ops.append(f"({_escape(line)}) Tj T*")
        ops.append("ET")
        stream = "\n".join(ops).encode("latin-1")
        objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        content_id = len(objects)
        objects.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 842] /Resources << /Font << /F1 %d 0 R >> >> "
            b"/Contents %d 0 R >>" % (font_id, content_id)
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


def refund_policy_pdf() -> bytes:
    return make_pdf(REFUND_PAGES)


def scanned_pdf() -> bytes:
    return make_pdf([[], [], ["p3"]])


def encrypted_pdf() -> bytes:
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    for page in PdfReader(io.BytesIO(refund_policy_pdf())).pages:
        writer.add_page(page)
    writer.encrypt(user_password="open-sesame", owner_password="owner")
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def policies_docx(extra: str = "") -> bytes:
    from docx import Document

    document = Document()
    document.add_heading("Clinic Policies", level=1)
    document.add_paragraph(
        "These policies apply to every patient of the Maple Street dental clinic. " + extra
    )
    document.add_heading("Opening Hours", level=2)
    document.add_paragraph("The clinic opens at 8 in the morning and closes at 6 in the evening on weekdays.")
    document.add_heading("Prices", level=2)
    table = document.add_table(rows=3, cols=2)
    for row, (service, price) in zip(
        table.rows,
        [("Service", "Price"), ("Cleaning", "90 dollars"), ("Whitening", "250 dollars")],
        strict=True,
    ):
        row.cells[0].text = service
        row.cells[1].text = price
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def notes_renamed_pdf() -> bytes:
    return policies_docx("Notes saved with the wrong extension.")


def oversize(size: int = 21 * 1024 * 1024) -> bytes:
    head = b"%PDF-1.4\n"
    return head + b"0" * (size - len(head))
