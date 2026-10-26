"""Extension point for flow agents (003 plan, implemented by 004).

:class:`FlowRunner` builds the entry agent for a flow; node agents then hand the call to each
other and report every move through ``CallControl.report_transition``. 004's runner
(``worker.flow.runtime``) is loaded on first use. :class:`NullFlowRunner` refuses flow agents
with diagnostic ``flow-runtime-unavailable`` (FR-024) when the runtime cannot be loaded.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from worker.internal_api import RuntimeConfig
    from worker.tools import CallControl

FLOW_RUNTIME_UNAVAILABLE = "flow-runtime-unavailable"
FLOW_NOT_COMPILED = "flow_not_compiled"
log = logging.getLogger(__name__)


class FlowRuntimeUnavailable(Exception):
    def __init__(self, message: str = "", *, diagnostic: str = FLOW_RUNTIME_UNAVAILABLE) -> None:
        super().__init__(message)
        self.diagnostic = diagnostic


@runtime_checkable
class FlowRunner(Protocol):
    available: bool

    def build_agent(
        self, runtime: RuntimeConfig, control: CallControl, tools: Sequence[Any], **options: Any
    ) -> Any:
        """Return the LiveKit ``Agent`` that starts the flow. ``options`` carries the session
        ``plan``, ``on_tts_text``, ``extra_instructions`` and ``components``."""
        ...


class NullFlowRunner:
    available = False

    def build_agent(
        self, runtime: RuntimeConfig, control: CallControl, tools: Sequence[Any], **options: Any
    ) -> Any:
        raise FlowRuntimeUnavailable("flow agents need the 004 flow runtime")


_runner: FlowRunner | None = None


def register_flow_runner(runner: FlowRunner) -> None:
    """Install a runner (tests; 004's own runner is loaded by :func:`get_flow_runner`)."""
    global _runner
    _runner = runner


def get_flow_runner() -> FlowRunner:
    global _runner
    if _runner is None:
        try:
            from worker.flow.runtime import RUNNER
        except ImportError:  # pragma: no cover - a build without the runtime
            log.exception("flow runtime unavailable")
            _runner = NullFlowRunner()
        else:
            _runner = RUNNER
    return _runner
