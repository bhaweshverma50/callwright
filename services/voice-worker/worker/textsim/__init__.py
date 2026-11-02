"""Text-mode simulations (008, research R1): the ``textsim`` process role of the voice worker.

Simulated conversations run through the same session code as live calls (``pipeline.py``,
``flow/``, ``tools/``) on a LiveKit ``AgentSession`` with text input and output instead of
STT and TTS. The API owns all state; this package fetches run specs, drives the conversation
and posts events and results back over the internal API.

- ``entry``: the arq consumer (queue :data:`QUEUE_NAME`, jobs ``run_single_turn`` and
  ``run_simulation``), started with ``WORKER_ROLE=textsim`` (``python -m worker.entry``) or
  ``python -m worker.textsim.entry``.
- ``runner``: the text session and the two job flows (single-turn test case, simulation).
- ``replay_caller`` and ``persona_caller``: who speaks for the caller (R5, R6).
- ``mock_tools``: how HTTP tools and webhook nodes answer without network (R4).
- ``llm``: model construction for the agent, the simulated caller and tool stand-ins, with
  the deterministic offline fallback used when the worker holds no key for the provider.
- ``api_client``: the internal endpoints (service token).
"""

from __future__ import annotations

QUEUE_NAME = "arq:textsim"
ANSWER_SOURCES = ("mock", "recorded", "synthesized", "error")
