"""Integration fixtures (006 T010): the two-workspace seeded call history."""

from tests.calls_support import seeded_calls
from tests.fakes.livekit_fake import channels  # 010: in-memory SIP and WhatsApp per test

__all__ = ["channels", "seeded_calls"]
