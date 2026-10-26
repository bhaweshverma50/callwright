"""Do-not-call normalisation and CSV parsing (010 T072, FR-035)."""

from __future__ import annotations

import pytest

from app.outbound import dnc


def test_e164_and_national_formats_with_region() -> None:
    parsed = dnc.parse_csv(b"number,note\n+14155550199,vip\n(415) 555-0100,\n0207 183 8750,uk\n", "US")
    assert parsed.rows == 3
    # The UK national number is not valid with region US.
    assert set(parsed.numbers) == {"+14155550199", "+14155550100"}
    assert parsed.numbers["+14155550199"] == "vip" and parsed.numbers["+14155550100"] is None
    assert parsed.invalid_count == 1 and parsed.invalid[0]["row"] == 3


def test_without_region_national_numbers_are_invalid() -> None:
    parsed = dnc.parse_csv(b"number\n(415) 555-0100\n+442071838750\n")
    assert list(parsed.numbers) == ["+442071838750"]
    assert parsed.invalid == [
        {"row": 1, "value": "(415) 555-0100", "error": "Add the country code, or choose a default region."}
    ]


def test_duplicates_in_file_counted_once() -> None:
    parsed = dnc.parse_csv(b"Number\n+14155550199\n+1 415 555 0199\n4155550199\n", "US")
    assert list(parsed.numbers) == ["+14155550199"]
    assert parsed.duplicates_in_file == 2


def test_invalid_rows_carry_row_numbers_and_blank_lines_are_skipped() -> None:
    parsed = dnc.parse_csv(b"note,number\nx,abc\n\n,+14155550199\nlong," + b"9" * 40 + b"\n", "US")
    assert parsed.rows == 3
    assert [r["row"] for r in parsed.invalid] == [1, 3]
    assert parsed.invalid_count == 2


def test_bom_and_utf8() -> None:
    parsed = dnc.parse_csv("﻿number,note\n+14155550199,café\n".encode())
    assert parsed.numbers == {"+14155550199": "café"}


def test_missing_number_header() -> None:
    with pytest.raises(dnc.CsvError) as exc:
        dnc.parse_csv(b"phone\n+14155550199\n")
    assert exc.value.status == 422 and exc.value.code == "invalid_csv"


def test_not_utf8() -> None:
    with pytest.raises(dnc.CsvError) as exc:
        dnc.parse_csv(b"number\n\xff\xfe+1415\n")
    assert exc.value.code == "invalid_csv"


def test_row_and_size_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dnc, "MAX_ROWS", 3)
    with pytest.raises(dnc.CsvError) as rows:
        dnc.parse_csv(b"number\n" + b"+14155550199\n" * 4)
    assert rows.value.status == 413
    monkeypatch.setattr(dnc, "MAX_BYTES", 10)
    with pytest.raises(dnc.CsvError) as size:
        dnc.parse_csv(b"number\n+14155550199\n")
    assert size.value.status == 413 and size.value.code == "file_too_large"


def test_invalid_report_is_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dnc, "MAX_REPORTED", 2)
    parsed = dnc.parse_csv(b"number\nx\ny\nz\n")
    assert parsed.invalid_count == 3 and len(parsed.invalid) == 2


def test_long_note_is_invalid() -> None:
    parsed = dnc.parse_csv(b"number,note\n+14155550199," + b"n" * 201 + b"\n")
    assert parsed.invalid_count == 1 and not parsed.numbers
