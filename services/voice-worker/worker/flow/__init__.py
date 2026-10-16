"""Extension point for flow agents (003 plan, implemented by 004).

:class:`FlowRunner` builds the entry agent for a flow and drives handoffs, calling
``CallControl.apply_overrides`` for per-segment model, voice and STT overrides and
``CallControl.report_transition`` for transitions. Without 004 the :class:`NullFlowRunner`
refuses flow agents with diagnostic ``flow-runtime-unavailable`` (FR-024).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from worker.internal_api import RuntimeConfig
    from worker.tools import CallControl

FLOW_RUNTIME_UNAVAILABLE = "flow-runtime-unavailable"


class FlowRuntimeUnavailable(Exception):
    diagnostic = FLOW_RUNTIME_UNAVAILABLE


@runtime_checkable
class FlowRunner(Protocol):
    available: bool

    def build_agent(
        self, runtime: RuntimeConfig, control: CallControl, tools: Sequence[Any]
    ) -> Any:
        """Return the LiveKit ``Agent`` that starts the flow."""
        ...


class NullFlowRunner:
    available = False

    def build_agent(
        self, runtime: RuntimeConfig, control: CallControl, tools: Sequence[Any]
    ) -> Any:
        raise FlowRuntimeUnavailable("flow agents need the 004 flow runtime")


_runner: FlowRunner = NullFlowRunner()


def register_flow_runner(runner: FlowRunner) -> None:
    """Called by 004 at import time to install its runner."""
    global _runner
    _runner = runner


def get_flow_runner() -> FlowRunner:
    return _runner
