"""Persona caller (008 T072, research R6).

A model plays the caller from a persona brief (goal, known facts, temperament, speaking style,
constraints, optional opening line). It sees the conversation from the caller's side (the
agent's lines as ``user`` messages, its own as ``assistant``), has one tool, ``hang_up(reason)``,
and runs at temperature :data:`PERSONA_TEMPERATURE` where the model allows it. It speaks only as
the caller: speaker labels and lines written for the agent are removed before a line is sent.

The run stops when the caller hangs up (``caller_hung_up``), the agent ends or transfers the
call, or after ``max_caller_turns`` caller turns (default 20, at most 50: ``turn_limit_reached``).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from worker.textsim.conversation import Conversation, EndReason, Outcome, agent_end_reason
from worker.textsim.llm import complete

HANG_UP = "hang_up"
PERSONA_TEMPERATURE = 0.7
DEFAULT_MAX_TURNS = 20
MAX_TURNS = 50
CONNECTED = "[The call has just connected and the agent has not spoken yet. Say your first line.]"

SYSTEM = (
    "You are role-playing a caller phoning a business's voice agent, as part of a test. Speak "
    "only as the caller, in the first person, one short spoken turn at a time, the way a real "
    "person talks on the phone. Never write the agent's lines, never add speaker labels, stage "
    "directions or notes. Stay in character and follow the brief. Share a known fact only when "
    "it is asked for or useful. When your goal is met, the agent has clearly finished, or you "
    "would hang up in real life, call hang_up with a short reason instead of speaking."
)

HANG_UP_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"reason": {"type": "string", "description": "Why you are hanging up"}},
    "required": ["reason"],
}

_AGENT_LABEL = re.compile(r"^\s*(agent|assistant|representative|receptionist)\s*:", re.I)
_CALLER_LABEL = re.compile(r"^\s*(caller|user|customer|me)\s*:\s*", re.I)
_DIRECTION = re.compile(r"\[[^\]]*\]|\*[^*]*\*")


def clamp_turns(value: int | None) -> int:
    return max(1, min(MAX_TURNS, int(value or DEFAULT_MAX_TURNS)))


def instructions(brief: Mapping[str, Any]) -> str:
    parts = [SYSTEM, "", f"Your goal: {str(brief.get('goal') or '').strip()}"]
    facts = [str(f).strip() for f in brief.get("known_facts") or [] if str(f).strip()]
    if facts:
        parts.append("Facts you know:\n" + "\n".join(f"- {f}" for f in facts))
    for key, label in (("temperament", "Temperament"), ("speaking_style", "Speaking style")):
        value = str(brief.get(key) or "").strip()
        if value:
            parts.append(f"{label}: {value}")
    rules = [str(c).strip() for c in brief.get("constraints") or [] if str(c).strip()]
    if rules:
        parts.append("Constraints:\n" + "\n".join(f"- {c}" for c in rules))
    return "\n".join(parts).strip()


def caller_view(transcript: Sequence[tuple[str, str]]) -> list[tuple[str, str]]:
    """The conversation as the caller model sees it: the agent is ``user``, the caller is
    ``assistant``. Starts with a connection note when the agent has not spoken."""
    out = [("assistant" if who == "caller" else "user", text) for who, text in transcript]
    if not out or out[0][0] != "user":
        out.insert(0, ("user", CONNECTED))
    return out


def clean_caller_text(text: str) -> str:
    """Only the caller's words: lines written for the agent are dropped, labels and stage
    directions removed."""
    kept: list[str] = []
    for line in text.splitlines():
        if not line.strip() or _AGENT_LABEL.match(line):
            continue
        line = _CALLER_LABEL.sub("", line)
        line = _DIRECTION.sub("", line)
        line = " ".join(line.split())
        if line:
            kept.append(line)
    return " ".join(kept).strip().strip('"').strip()


def hang_up_tool() -> Any:
    from worker.flow.llm_ops import raw_tool

    return raw_tool(
        HANG_UP,
        "End the call as the caller (goal met, the agent finished, or you would hang up).",
        HANG_UP_SCHEMA,
    )


class PersonaCaller:
    def __init__(self, llm: Any, brief: Mapping[str, Any], *, max_turns: int | None = None):
        self.llm = llm
        self.brief = dict(brief)
        self.max_turns = clamp_turns(max_turns)
        self.system = instructions(self.brief)
        self.hang_up_reason: str | None = None

    async def next_line(self, transcript: Sequence[tuple[str, str]]) -> str | None:
        """The caller's next line, or None when the caller hangs up."""
        opening = str(self.brief.get("opening_line") or "").strip()
        if opening and not any(who == "caller" for who, _ in transcript):
            return clean_caller_text(opening) or opening
        for _ in range(2):  # one retry when the model only wrote lines for the agent
            result = await complete(
                self.llm, self.system, caller_view(transcript), [hang_up_tool()]
            )
            for name, args in result.tool_calls:
                if name == HANG_UP:
                    self.hang_up_reason = str(args.get("reason") or "") or None
                    return None
            text = clean_caller_text(result.text)
            if text:
                return text
        self.hang_up_reason = "no_reply"
        return None

    async def drive(self, conversation: Conversation) -> Outcome:
        transcript: list[tuple[str, str]] = []
        opening = await conversation.start()
        transcript += [("agent", t) for t in opening.texts]
        turns = 0
        end: EndReason | None = None
        while conversation.disconnect_reason is None:
            if turns >= self.max_turns:
                end = "turn_limit_reached"
                break
            line = await self.next_line(transcript)
            if line is None:
                end = "caller_hung_up"
                break
            turns += 1
            transcript.append(("caller", line))
            turn = await conversation.send(line)
            transcript += [("agent", t) for t in turn.texts]
        ended = agent_end_reason(conversation.disconnect_reason)
        return Outcome(
            end_reason=ended or end or "caller_hung_up",
            caller_turns=turns,
            hang_up_reason=self.hang_up_reason,
        )
