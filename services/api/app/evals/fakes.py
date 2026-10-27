"""Offline replies for the fake model adapter (no vendor key): call analysis and judges.

Deterministic and simple, so local development and the mock quickstart show plausible results.
Both read only the AGENT lines of the data block (and the variable list), so words a caller
speaks never steer them. Real deployments use the configured vendor model.
"""

from __future__ import annotations

import json
import re

from app.llms.adapters.base import ChatMessage
from app.llms.adapters.fake import PURPOSE_REPLIES

_LINE = re.compile(r"^\[(\d+)\] (AGENT|CALLER): (.*)$")
_WORD = re.compile(r"[a-z0-9]+")
_CLOSING = ("anything else", "have a good", "thanks for calling", "booked", "done", "confirmed", "all set")
_POSITIVE = ("thank", "great", "perfect", "awesome", "appreciate", "wonderful")
_NEGATIVE = ("angry", "frustrat", "terrible", "awful", "cancel", "complain", "useless", "ridiculous")


def _lines(data: str) -> list[tuple[int, str, str]]:
    out = []
    for raw in data.splitlines():
        match = _LINE.match(raw.strip())
        if match:
            out.append((int(match.group(1)), match.group(2), match.group(3)))
    return out


def _words(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if len(w) > 3}


def _last_user(messages: list[ChatMessage]) -> str:
    return next((m.content for m in reversed(messages) if m.role == "user"), "")


def analysis_reply(messages: list[ChatMessage], system: str | None) -> str:
    lines = _lines(_last_user(messages))
    agent = [t for _, who, t in lines if who == "AGENT"]
    caller = [t for _, who, t in lines if who == "CALLER"]
    spoken = " ".join(t for _, _, t in lines).lower()
    summary = "No conversation was recorded."
    if caller:
        summary = f"The caller said: {caller[0][:200]}"
        if agent:
            summary += f" The agent closed with: {agent[-1][:200]}"
    mood = " ".join(caller).lower()
    sentiment = (
        "negative"
        if any(w in mood for w in _NEGATIVE)
        else "positive"
        if any(w in mood for w in _POSITIVE)
        else "neutral"
    )
    values: dict[str, object] = {}
    spec = re.search(r"<variables>\n(.*?)\n</variables>", system or "", re.DOTALL)
    for var in json.loads(spec.group(1)) if spec else []:
        name, kind = str(var["name"]), var["type"]
        if kind == "boolean":
            parts = [p[:4] for p in name.split("_") if len(p) > 2]
            values[name] = bool(parts) and all(p in spoken for p in parts)
        elif kind == "choice":
            values[name] = next((c for c in var.get("choices") or [] if c.lower() in spoken), None)
        elif kind == "number":
            number = re.search(r"\b\d+(?:\.\d+)?\b", spoken)
            values[name] = float(number.group(0)) if number else None
        else:
            values[name] = None
    return json.dumps({"summary": summary[:600], "sentiment": sentiment, "values": values})


def judge_reply(messages: list[ChatMessage], system: str | None) -> str:
    lines = _lines(_last_user(messages))
    agent = [(i, t) for i, who, t in lines if who == "AGENT"]
    system = system or ""
    if "SCORE: agent lines" in system:
        wanted = [int(t) for t in re.findall(r"\d+", system.split("SCORE: agent lines ")[1].split("\n")[0])]
        texts = dict(agent)
        turns = []
        for t in wanted:
            text = texts.get(t, "").lower()
            turn_score = -1 if ("sorry" in text and "cannot" in text) else (1 if len(text) > 25 else 0)
            reason = "Moves the call forward." if turn_score == 1 else "Holds the call in place."
            turns.append(
                {
                    "turn": t,
                    "score": turn_score,
                    "rationale": reason if turn_score >= 0 else "Refuses without a way forward.",
                }
            )
        return json.dumps({"turns": turns})
    if not agent:
        return json.dumps(
            {
                "verdict_hint": "fail",
                "score": 0.0,
                "rationale": "The agent never spoke.",
                "evidence_turns": [],
            }
        )
    question = re.search(r"QUESTION: (.*)", system)
    if question:
        wanted_words = _words(question.group(1)) - {"agent", "caller", "call", "does", "did", "they", "that"}
        hit = next(((i, t) for i, t in agent if wanted_words & _words(t)), None)
        if hit:
            return json.dumps(
                {
                    "verdict_hint": "pass",
                    "score": 1.0,
                    "rationale": f'Yes: the agent said "{hit[1][:120]}".',
                    "evidence_turns": [hit[0]],
                }
            )
        last = agent[-1]
        return json.dumps(
            {
                "verdict_hint": "fail",
                "score": 0.0,
                "rationale": f'No agent line addresses it; the last was "{last[1][:120]}".',
                "evidence_turns": [last[0]],
            }
        )
    last_i, last_t = agent[-1]
    closed = any(c in last_t.lower() for c in _CLOSING) or len(agent) >= 3
    score = 0.85 if closed else 0.35
    verdict = "met" if closed else "not clearly met"
    return json.dumps(
        {
            "verdict_hint": "pass" if closed else "fail",
            "score": score,
            "rationale": f'The goal looks {verdict}: the agent ended with "{last_t[:120]}".',
            "evidence_turns": [last_i],
        }
    )


def register() -> None:
    PURPOSE_REPLIES.setdefault("call_analysis", analysis_reply)
    PURPOSE_REPLIES.setdefault("eval_judge", judge_reply)
