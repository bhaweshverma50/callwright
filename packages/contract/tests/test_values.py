from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from callwright_contract.values import E164, KEYPAD_DIGITS, PRESS_DIGITS_PATTERN, spoken_time

KOLKATA = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 11, 3, 14, 5, tzinfo=KOLKATA)  # a Tuesday


def test_spoken_time() -> None:
    assert spoken_time(datetime(2026, 11, 3, 17, 0, tzinfo=KOLKATA), NOW) == "today at 5:00 pm"
    assert spoken_time(datetime(2026, 11, 4, 0, 30, tzinfo=KOLKATA), NOW) == (
        "tomorrow, Wednesday 4 November, at 12:30 am"
    )
    assert spoken_time(datetime(2026, 11, 6, 9, 0, tzinfo=KOLKATA), NOW) == ("Friday 6 November at 9:00 am")
    assert spoken_time(datetime(2026, 11, 6, 12, 15, tzinfo=KOLKATA), NOW) == (
        "Friday 6 November at 12:15 pm"
    )


def test_e164() -> None:
    assert E164.match("+14155550123")
    assert not E164.match("14155550123")
    assert not E164.match("+0123456789")
    assert not E164.match("+1234")


def test_keypad() -> None:
    import re

    assert set("0123456789*#") == KEYPAD_DIGITS
    assert re.match(PRESS_DIGITS_PATTERN, "12#*")
    assert not re.match(PRESS_DIGITS_PATTERN, "1" * 21)
    assert not re.match(PRESS_DIGITS_PATTERN, "12a")
