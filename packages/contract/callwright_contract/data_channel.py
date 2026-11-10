"""What the voice worker publishes on the call's LiveKit data channel (not HTTP), as in
``specs/003-voice-runtime/contracts/data_channel.yaml``: the browser test call panel's latency
chips and the flow builder's live node highlight. ``tests/test_spec_enums.py`` keeps these equal
to the spec."""

from __future__ import annotations

from typing import Final

# ``TurnLatencyMessage``: {turn_index, stt_ms, llm_ms, tts_ms, e2e_ms?}
LATENCY_TOPIC: Final = "cw.turn_latency"
LATENCY_FIELDS: Final = ("turn_index", "stt_ms", "llm_ms", "tts_ms", "e2e_ms")

# ``FlowNodeEnteredMessage``: {type: node_entered, node_id, at_ms}
FLOW_TOPIC: Final = "callwright.flow"
NODE_ENTERED: Final = "node_entered"
NODE_ENTERED_FIELDS: Final = ("type", "node_id", "at_ms")
