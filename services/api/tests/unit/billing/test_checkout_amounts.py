"""Top-up amount rules (T047, T101, FR-008, US2.5)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.billing.service import validate_top_up_amount
from app.core.errors import ProblemError


@pytest.mark.parametrize("amount", ["5", "5.00", "25.00", "100", "999.99", "10000.00", "5.500000"])
def test_valid_amounts(amount: str) -> None:
    assert validate_top_up_amount(Decimal(amount)) == Decimal(amount).quantize(Decimal("0.01"))


@pytest.mark.parametrize(
    ("amount", "code", "message"),
    [
        ("4", "out_of_range", "minimum"),
        ("4.99", "out_of_range", "minimum"),
        ("0", "out_of_range", "minimum"),
        ("-25", "out_of_range", "minimum"),
        ("10000.01", "out_of_range", "maximum"),
        ("10001", "out_of_range", "maximum"),
        ("5.555", "too_precise", "cents"),
        ("25.001", "too_precise", "cents"),
        ("NaN", "invalid_format", "dollars"),
    ],
)
def test_invalid_amounts(amount: str, code: str, message: str) -> None:
    with pytest.raises(ProblemError) as info:
        validate_top_up_amount(Decimal(amount))
    problem = info.value
    assert problem.status == 422
    assert problem.errors is not None
    assert problem.errors[0]["pointer"] == "/amount_usd"
    assert problem.errors[0]["code"] == code
    assert message in problem.errors[0]["message"]
