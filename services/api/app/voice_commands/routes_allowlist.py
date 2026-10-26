"""Pages a voice command may navigate to (006 T076), mirrored from apps/web/src/app/router.tsx.

Record pages (an agent, a call) are reached through their list pages; ``/calls`` also takes the
filter params below.
"""

from __future__ import annotations

ROUTES: dict[str, str] = {
    "/dashboard": "Dashboard",
    "/calls": "Calls",
    "/agents": "Agents",
    "/agents/new": "New agent",
    "/agents/templates": "Agent templates",
    "/knowledge-base": "Knowledge",
    "/phone-numbers": "Channels",
    "/datasets": "Datasets",
    "/simulations": "Simulations",
    "/review": "Review",
    "/calibration": "Calibration",
    "/issues": "Issues",
    "/billing": "Billing",
    "/settings": "Settings",
}

CALL_FILTER_VALUES: dict[str, frozenset[str]] = {
    "status": frozenset(
        {
            "queued",
            "ringing",
            "in_progress",
            "ended",
            "processing",
            "completed",
            "failed",
            "no_answer",
            "busy",
            "voicemail",
        }
    ),
    "channel": frozenset({"web", "sip_inbound", "sip_outbound", "whatsapp"}),
    "sentiment": frozenset({"positive", "neutral", "negative", "unknown"}),
}
DATE_RANGES = frozenset({"today", "yesterday", "this_week", "last_7_days"})
COPILOTS = frozenset({"analytics_chat", "prompt_builder", "flow_builder"})
