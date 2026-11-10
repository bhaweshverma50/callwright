"""The one USD precision: every amount is stored and quantized to $0.000001."""

from __future__ import annotations

from decimal import Decimal

SIX = Decimal("0.000001")
