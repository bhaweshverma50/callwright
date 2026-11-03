"""Extension points for tools and call control (003 plan, implemented by 005).

- :class:`ToolProvider` returns the LLM function tools for a call (end_call, transfer,
  press_digit, http, kb_search) built from the version snapshot. Without 005 installed the
  :class:`NullToolProvider` returns no tools.
- :class:`CallControl` is what tools and flows (004) use to act on the call without vendor
  details: hang up with a reason, speak, send keypad tones, report tool and flow activity, and
  apply per-segment overrides (FR-046). The worker implements it in ``worker.control``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, TypedDict, runtime_checkable

if TYPE_CHECKING:
    from worker.internal_api import RuntimeConfig


class LlmOverride(TypedDict, total=False):
    provider: str
    model: str
    temperature: float


class TtsOverride(TypedDict, total=False):
    provider: str
    model: str
    voice_id: str
    speed: float
    expressiveness: float
    volume: float
    stability: float


class SttOverride(TypedDict, total=False):
    provider: str
    model: str | None  # None = Auto, re-resolved for the segment language
    language: str


class LanguageSwitch(TypedDict, total=False):
    """012 ``set_language``: the call's new language, its label for the reply-language line
    and the voice model for it (a multilingual one when the agent's is English only)."""

    code: str
    label: str
    tts_model: str | None


class SegmentOverrides(TypedDict, total=False):
    """Per-segment overrides from a flow node (004 data-model ``Overrides``); null = inherit."""

    llm: LlmOverride | None
    tts: TtsOverride | None
    stt: SttOverride | None
    language: str | None
    switch_language: LanguageSwitch | None


@dataclass(frozen=True)
class ClampedValue:
    path: str
    requested: float
    applied: float


@dataclass(frozen=True)
class OverrideResult:
    """What ``apply_overrides`` accepted. Changes take effect at the next turn boundary."""

    applied_paths: tuple[str, ...] = ()
    clamped: tuple[ClampedValue, ...] = ()
    rejected: tuple[str, ...] = ()  # unsupported vendor or model, kept at the previous value
    pending: bool = False


@dataclass(frozen=True)
class ToolActivity:
    name: str
    ref: str | None = None
    arguments: dict[str, Any] = field(default_factory=dict)
    output: str | None = None
    is_error: bool = False
    duration_ms: int | None = None
    # 005 event fields (data-model section 7): tool_type, error_code, dispatch_overhead_ms, ...
    extra: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class CallControl(Protocol):
    """Call-control capability offered to tools (005) and flows (004)."""

    @property
    def call_id(self) -> str: ...

    @property
    def room(self) -> Any:
        """The LiveKit room (``None`` in the offline harness)."""
        ...

    async def hang_up(self, reason: str, *, diagnostic: str | None = None) -> bool:
        """End the call. First writer wins: returns False when a reason was already set."""
        ...

    async def say(self, text: str, *, allow_interruptions: bool = True) -> None: ...

    async def send_dtmf(self, digits: str) -> None: ...

    def report_tool(self, activity: ToolActivity) -> None: ...

    def report_transition(
        self,
        to_node_id: str,
        *,
        from_node_id: str | None = None,
        label: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        """Record a flow move; ``details`` carries 004's payload (labels, trigger, timing)."""
        ...

    async def apply_overrides(self, overrides: SegmentOverrides) -> OverrideResult: ...


@runtime_checkable
class ToolProvider(Protocol):
    def tools_for(self, runtime: RuntimeConfig, control: CallControl) -> Sequence[Any]:
        """LiveKit function tools for this call."""
        ...


class NullToolProvider:
    """Default without 005: single-prompt agents run with no tools."""

    def tools_for(self, runtime: RuntimeConfig, control: CallControl) -> Sequence[Any]:
        return []


_provider: ToolProvider = NullToolProvider()


def register_tool_provider(provider: ToolProvider) -> None:
    """Called by 005 at import time to install its provider."""
    global _provider
    _provider = provider


def get_tool_provider() -> ToolProvider:
    return _provider
