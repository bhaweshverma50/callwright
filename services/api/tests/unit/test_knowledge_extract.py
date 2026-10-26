"""Content sniffing and extraction (005 T053)."""

from __future__ import annotations

import pytest

from app.knowledge.extract import ExtractError, extract, sniff
from tests.fixtures import knowledge as fx


def test_sniffing_uses_content_not_name() -> None:
    assert sniff(fx.refund_policy_pdf()) == "pdf"
    assert sniff(fx.policies_docx()) == "docx"
    assert sniff(fx.notes_renamed_pdf()) == "docx"
    assert sniff(b"plain text that is not a document") is None
    assert sniff(b"PK\x03\x04 not really a zip") is None


def test_pdf_pages_and_headings() -> None:
    result = extract(fx.refund_policy_pdf(), "pdf")
    assert result.page_count == 2
    headings = [(b.text, b.page) for b in result.blocks if b.kind == "heading"]
    assert headings == [("Refund Policy", 1), ("Cancellations", 2)]
    assert any("14 days" in b.text and b.page == 1 for b in result.blocks)


def test_docx_headings_and_table_rows() -> None:
    result = extract(fx.policies_docx(), "docx")
    kinds = [(b.kind, b.text) for b in result.blocks]
    assert ("heading", "Prices") in kinds
    assert ("table_row", "Cleaning | 90 dollars") in kinds
    assert kinds.index(("heading", "Prices")) < kinds.index(("table_row", "Cleaning | 90 dollars"))


@pytest.mark.parametrize(
    ("data", "file_type", "code"),
    [
        (fx.scanned_pdf(), "pdf", "no_extractable_text"),
        (fx.encrypted_pdf(), "pdf", "encrypted_file"),
        (b"%PDF-1.4\nthis is not a pdf body", "pdf", "corrupt_file"),
        (b"PK\x03\x04broken", "docx", "corrupt_file"),
    ],
)
def test_permanent_errors(data: bytes, file_type: str, code: str) -> None:
    with pytest.raises(ExtractError) as info:
        extract(data, file_type)
    assert info.value.code == code
