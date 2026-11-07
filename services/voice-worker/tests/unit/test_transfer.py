"""Transfer tool (005 T018): static, dynamic with allow-list, cold, warm private and public,
ring timeout failure and non-SIP channels."""

from __future__ import annotations

import json
from typing import Any

from tests.unit.tool_support import make, tool
from worker.tools.transfer import TransferError


class FakeTransfer:
    def __init__(self, *, answer: bool = True, refer_ok: bool = True) -> None:
        self.answer = answer
        self.refer_ok = refer_ok
        self.log: list[tuple[str, Any]] = []

    async def cold(self, number: str) -> None:
        self.log.append(("cold", number))
        if not self.refer_ok:
            raise TransferError("refused")

    async def dial(self, number: str, *, private: bool, ring_timeout_s: int) -> str:
        self.log.append(("dial", (number, private, ring_timeout_s)))
        if not self.answer:
            raise TransferError("no answer")
        return "room-consult" if private else "room"

    async def brief_private(self, room_name: str, text: str) -> None:
        self.log.append(("brief", (room_name, text)))

    async def move_to_caller(self, room_name: str) -> None:
        self.log.append(("move", room_name))

    async def compose_briefing(self, instructions: str) -> str:
        self.log.append(("compose", instructions))
        return "Caller Ana wants to move her appointment."


STATIC = {"routing_type": "static", "number": "+14155550100", "hold_message": "Please hold."}


async def test_cold_static_transfer() -> None:
    backend = FakeTransfer()
    h = make([tool("transfer_call", "transfer", STATIC)], transfer_backend=backend)
    payload = await h.tools.dispatch("transfer", {})
    assert json.loads(payload) == {"transferred": True}
    assert backend.log == [("cold", "+14155550100")]
    assert h.backend.said == ["Please hold."] and h.backend.ended == ["call_transfer"]


async def test_dynamic_with_allow_list() -> None:
    config = {
        "routing_type": "dynamic",
        "routing_instructions": "Sales +14155550100, support +14155550111",
        "allowed_numbers": ["+14155550100", "+14155550111"],
    }
    backend = FakeTransfer()
    h = make([tool("transfer_call", "route", config)], transfer_backend=backend)
    refused = json.loads(await h.tools.dispatch("route", {"destination": "+19005550199"}))
    assert refused["error"] == "invalid_arguments" and backend.log == []
    await h.tools.dispatch("route", {"destination": "+14155550111"})
    assert backend.log == [("cold", "+14155550111")]


async def test_dynamic_without_allow_list_takes_any_e164() -> None:
    config = {"routing_type": "dynamic", "routing_instructions": "Any branch"}
    backend = FakeTransfer()
    h = make([tool("transfer_call", "route", config)], transfer_backend=backend)
    await h.tools.dispatch("route", {"destination": "+442071234567"})
    assert backend.log == [("cold", "+442071234567")]


async def test_warm_private_briefs_then_moves() -> None:
    warm = {
        **STATIC,
        "transfer_type": "warm",
        "ring_timeout_s": 20,
        "warm_transfer": {
            "handoff_type": "private",
            "briefing_message_type": "static",
            "briefing_message": "VIP caller.",
        },
    }
    backend = FakeTransfer()
    h = make([tool("transfer_call", "transfer", warm)], transfer_backend=backend)
    await h.tools.dispatch("transfer", {})
    assert backend.log == [
        ("dial", ("+14155550100", True, 20)),
        ("brief", ("room-consult", "VIP caller.")),
        ("move", "room-consult"),
    ]
    assert h.backend.ended == ["call_transfer"]


async def test_warm_public_briefs_in_the_call_with_a_written_line() -> None:
    warm = {
        **STATIC,
        "transfer_type": "warm",
        "warm_transfer": {
            "handoff_type": "public",
            "briefing_message_type": "prompt",
            "briefing_message": "Summarise why the caller is calling.",
        },
    }
    backend = FakeTransfer()
    h = make([tool("transfer_call", "transfer", warm)], transfer_backend=backend)
    await h.tools.dispatch("transfer", {})
    assert ("compose", "Summarise why the caller is calling.") in backend.log
    assert h.backend.said == ["Please hold.", "Caller Ana wants to move her appointment."]


async def test_ring_timeout_returns_to_the_llm() -> None:
    warm = {
        **STATIC,
        "transfer_type": "warm",
        "warm_transfer": {
            "handoff_type": "private",
            "briefing_message_type": "static",
            "briefing_message": "x",
        },
    }
    h = make([tool("transfer_call", "transfer", warm)], transfer_backend=FakeTransfer(answer=False))
    payload = json.loads(await h.tools.dispatch("transfer", {}))
    assert payload["error"] == "transfer_failed" and h.backend.ended == []
    assert h.events()[0]["error_code"] == "transfer_failed"


async def test_refused_refer() -> None:
    h = make(
        [tool("transfer_call", "transfer", STATIC)], transfer_backend=FakeTransfer(refer_ok=False)
    )
    assert json.loads(await h.tools.dispatch("transfer", {}))["error"] == "transfer_failed"


async def test_web_calls_cannot_transfer() -> None:
    backend = FakeTransfer()
    h = make([tool("transfer_call", "transfer", STATIC)], channel="web", transfer_backend=backend)
    payload = json.loads(await h.tools.dispatch("transfer", {}))
    assert payload["error"] == "channel_unsupported" and backend.log == [] and h.backend.said == []
