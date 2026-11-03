"""Anthropic Claude LLM (003 T069), built on the LiveKit Anthropic plugin.

Catalog models (002 data-model section 8.2): ``claude-haiku-5-5`` (fast, the voice choice) and
``claude-sonnet-5-5`` (stronger). Both take no sampling parameters, so the agent's temperature is
never sent (the catalog marks it fixed), and both reject assistant prefill, so the plugin is told
to end every request on a user turn. Thinking is turned off for voice: it would delay the first
token of every reply. Haiku takes ``disabled``; Sonnet 5.5 rejects that and takes
``between_tools`` instead.

Without a platform key (``ANTHROPIC_API_KEY``) the provider is not available on this deployment:
``build`` raises :class:`VendorNotConfigured`, the call fails with
``unsupported_vendor:llm/anthropic`` before the caller hears anything, and the API refuses live
calls at admission for the same reason (``app/calls/components.py``). Text simulations use the
offline scripts instead (``worker/textsim/llm.py``).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from worker.adapters.registry import VendorNotConfigured, VendorSpec

DEFAULT_MODEL = "claude-haiku-5-5"

# Request fields per model family that keep thinking off (first matching prefix wins).
THINKING_OFF: tuple[tuple[str, Mapping[str, Any]], ...] = (
    ("claude-sonnet-5", {"type": "between_tools"}),
    ("claude-", {"type": "disabled"}),
)

# Model families that reject a trailing assistant message (prefill).
NO_PREFILL = ("claude-haiku-5", "claude-sonnet-5")

# Spoken replies are short; this caps a runaway answer without cutting a normal one.
MAX_TOKENS = 1024


def thinking_for(model: str) -> Mapping[str, Any] | None:
    for prefix, value in THINKING_OFF:
        if model.startswith(prefix):
            return value
    return None


def _disable_prefill(plugin_llm: Any) -> None:
    """Register our models with the plugin's no-prefill list (it only knows the 4.6 family)."""
    patterns = tuple(getattr(plugin_llm, "_NO_PREFILL_PATTERNS", ()))
    missing = tuple(p for p in NO_PREFILL if p not in patterns)
    if missing:
        plugin_llm._NO_PREFILL_PATTERNS = patterns + missing


def build(spec: VendorSpec, creds: Mapping[str, str]) -> Any:
    api_key = creds.get("api_key", "")
    if not api_key:
        raise VendorNotConfigured("llm", "anthropic")

    from livekit.agents.types import NOT_GIVEN
    from livekit.plugins import anthropic
    from livekit.plugins.anthropic import llm as plugin_llm

    _disable_prefill(plugin_llm)
    model = spec.model or DEFAULT_MODEL
    thinking = thinking_for(model)
    extra_body: dict[str, Any] = {"thinking": dict(thinking)} if thinking else {}

    class VoiceLLM(anthropic.LLM):
        """The plugin's LLM with the voice request fields added to every chat request."""

        def chat(self, *, extra_kwargs: Any = NOT_GIVEN, **kwargs: Any) -> Any:
            merged: dict[str, Any] = dict(extra_kwargs) if isinstance(extra_kwargs, dict) else {}
            if extra_body:
                merged["extra_body"] = {**extra_body, **(merged.get("extra_body") or {})}
            return super().chat(extra_kwargs=merged or NOT_GIVEN, **kwargs)

    return VoiceLLM(model=model, api_key=api_key, max_tokens=MAX_TOKENS, caching="ephemeral")
