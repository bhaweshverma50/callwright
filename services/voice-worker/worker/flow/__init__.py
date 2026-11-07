"""The flow runtime port (004).

:class:`FlowRunner` gives a flow call its opening (who speaks first and the greeting) and builds
its entry agent; node agents then hand the call to each other and report every move through
``CallControl.report_transition``. A turn-boundary swap rebuilds the current node's agent
through the runner, and the call releases its flow state when it ends. ``worker.flow.runtime``
implements it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from callwright_contract.protocol import RuntimeConfig

    from worker.adapters.registry import AdapterRegistry, VendorSpec
    from worker.agent import SessionPlan, TtsTextHook
    from worker.flow.nodes.start import Opening
    from worker.tools import CallControl
    from worker.tools.registry import CallTools

FLOW_RUNTIME_UNAVAILABLE = "flow-runtime-unavailable"
FLOW_NOT_COMPILED = "flow_not_compiled"


class FlowRuntimeUnavailable(Exception):
    def __init__(self, message: str = "", *, diagnostic: str = FLOW_RUNTIME_UNAVAILABLE) -> None:
        super().__init__(message)
        self.diagnostic = diagnostic


@dataclass(frozen=True)
class FlowComponents:
    """How the runtime builds a node's own LLM, TTS or STT, and where it reports flow timings
    (``engine_ms``, ``transition_llm_ms``) for the current turn."""

    registry: AdapterRegistry
    build: Callable[[VendorSpec], Any]
    on_timing: Callable[[str, int], None] | None = None


class FlowRunner(Protocol):
    def opening(self, runtime: RuntimeConfig) -> Opening:
        """The call's opening from the Start node and the Say nodes right after it. Raises
        :class:`FlowRuntimeUnavailable` when the claim carries no runnable compiled flow."""
        ...

    def build_agent(
        self,
        runtime: RuntimeConfig,
        control: CallControl,
        plan: SessionPlan,
        tools: CallTools,
        *,
        extra_tools: Sequence[Any] = (),
        extra_instructions: str = "",
        on_tts_text: TtsTextHook | None = None,
        components: FlowComponents | None = None,
    ) -> Any:
        """The LiveKit ``Agent`` that starts the flow call ``control.call_id``."""
        ...

    def rebuild(self, call_id: str, plan: SessionPlan, components: Mapping[str, Any]) -> Any:
        """After a turn-boundary swap: the current node's agent rebuilt with the new plan and
        components, keeping its conversation; None between nodes."""
        ...

    def visited_nodes(self, call_id: str) -> list[str]: ...

    def release(self, call_id: str) -> None:
        """Forget the call's flow state (the call ended)."""
        ...
