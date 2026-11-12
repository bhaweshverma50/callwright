"""Content gates (022 T052, research R2): a re-exported Google Doc with the same words is not new
content; changed words are."""

from __future__ import annotations

from app.knowledge.sources.fake_content import make_docx, make_pdf
from app.knowledge.sources.sync import text_hash


def test_same_text_in_different_docx_bytes_hashes_the_same() -> None:
    a = make_docx("Hours", ["Open 9 to 7.", "Closed Sunday."])
    b = make_docx("Hours", ["Open  9 to 7.", "Closed   Sunday."])
    assert text_hash(a) == text_hash(b)


def test_changed_text_hashes_differently() -> None:
    assert text_hash(make_docx("Hours", ["Open 9 to 7."])) != text_hash(make_docx("Hours", ["Open 9 to 8."]))


def test_pdf_text_hash_and_unreadable_bytes() -> None:
    assert text_hash(make_pdf([["Refunds within 14 days."]]), "pdf")
    assert text_hash(b"not a document") is None
