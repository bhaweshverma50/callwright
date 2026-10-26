"""Context strategies at a handoff (T079, research R12).

* ``inherit``: the next node sees the whole conversation.
* ``reset``: no earlier turns; captured variables are given as known facts.
* ``summarize``: the latest finished background summary plus the last 2 turns; when no summary
  is ready yet, the last 6 turns. The summary is refreshed after agent turns by
  :class:`BackgroundSummarizer` and is never awaited at a handoff (no audible gap).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)
Message = tuple[str, str]  # (role, text), role user or assistant
Summarize = Callable[[Sequence[Message], str | None], Awaitable[str]]
SUMMARY_TURNS = 2
FALLBACK_TURNS = 6


def last_turns(history: Sequence[Message], turns: int) -> list[Message]:
    """The messages of the last ``turns`` caller turns (a turn starts with a user message)."""
    starts = [i for i, (role, _) in enumerate(history) if role == "user"]
    if len(starts) <= turns:
        return list(history)
    return list(history[starts[-turns] :])


@dataclass(frozen=True)
class Handoff:
    messages: list[Message]
    summary: str | None
    facts: Mapping[str, Any]


def known_facts(variables: Mapping[str, Any]) -> str:
    lines = [f"- {k}: {v}" for k, v in variables.items() if v not in (None, "")]
    return "Known facts about this call:\n" + "\n".join(lines) if lines else ""


def handoff(
    strategy: str, history: Sequence[Message], summary: str | None, variables: Mapping[str, Any]
) -> Handoff:
    if strategy == "reset":
        return Handoff([], None, dict(variables))
    if strategy == "summarize":
        if summary:
            return Handoff(last_turns(history, SUMMARY_TURNS), summary, {})
        return Handoff(last_turns(history, FALLBACK_TURNS), None, {})
    return Handoff(list(history), None, {})


@dataclass
class BackgroundSummarizer:
    """Keeps a running summary up to date without blocking speech."""

    summarize: Summarize
    summary: str | None = None
    _task: asyncio.Task[None] | None = field(default=None, repr=False)

    def schedule(self, history: Sequence[Message]) -> None:
        if not history:
            return
        if self._task is not None and not self._task.done():
            self._task.cancel()
        snapshot = list(history)
        previous = self.summary

        async def run() -> None:
            try:
                text = await self.summarize(snapshot, previous)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.debug("background summary failed: %s", exc)
                return
            if text.strip():
                self.summary = text.strip()

        try:
            self._task = asyncio.get_running_loop().create_task(run())
        except RuntimeError:
            self._task = None

    async def aclose(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
