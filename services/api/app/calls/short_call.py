"""Which calls are too short for AI analysis and judge checks (cost guard on post-call work)."""

from __future__ import annotations

from app.calls import transcript
from app.calls.models import Call, billable_seconds
from app.calls.origins import policy
from app.core.config import Settings


def too_short(call: Call, settings: Settings) -> bool:
    """True when the call is under the minimum duration (live and test calls) or the caller said
    fewer than the minimum number of characters. Text simulations have no real call time."""
    if settings.analysis_min_duration_s and policy(call.origin).has_real_audio:
        seconds = billable_seconds(call.connected_at, call.ended_at)
        if seconds < settings.analysis_min_duration_s:
            return True
    if settings.analysis_min_caller_chars:
        said = sum(len(m.text.strip()) for m in transcript.read(call).messages if m.role == "user")
        if said < settings.analysis_min_caller_chars:
            return True
    return False
