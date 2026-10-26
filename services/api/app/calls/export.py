"""CSV export of the filtered and sorted call list (006 T091, FR-035).

Same filters and order as the list, at most 10,000 rows, never transcript text. Columns come
from ``columns`` in display order (unknown keys dropped); the default is every list column.
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Callable, Iterator, Mapping, Sequence
from typing import Any

EXPORT_LIMIT = 10_000


def _quality(key: str) -> Callable[[Mapping[str, Any]], Any]:
    return lambda row: row["quality"][key]


COLUMNS: dict[str, tuple[str, Callable[[Mapping[str, Any]], Any]]] = {
    "call_id": ("Call ID", lambda r: r["call_id"]),
    "started_at": ("Start time", lambda r: r["started_at"]),
    "agent_id": ("Agent ID", lambda r: r["agent"]["id"]),
    "agent_name": ("Agent", lambda r: r["agent"]["name"] + (" (deleted)" if r["agent"]["deleted"] else "")),
    "from_number": ("From", lambda r: r["from_number"]),
    "to_number": ("To", lambda r: r["to_number"]),
    "channel": ("Channel", lambda r: r["channel"]),
    "origin": ("Origin", lambda r: r["origin"]),
    "disconnect_reason": ("Disconnect reason", lambda r: r["disconnect_reason"]),
    "duration_s": ("Duration (s)", lambda r: r["duration_s"]),
    "status": ("Status", lambda r: r["status"]),
    "cost_usd": ("Cost (USD)", lambda r: None if r["cost_usd"] is None else f"{r['cost_usd']:.6f}"),
    "latency_avg_ms": ("Avg latency (ms)", lambda r: r["latency_avg_ms"]),
    "has_recording": ("Recording", lambda r: "yes" if r["has_recording"] else "no"),
    "summary": ("Summary", lambda r: r["summary"]),
    "sentiment": ("Sentiment", lambda r: r["sentiment"]),
    "analysis_values": (
        "Analysis",
        lambda r: json.dumps(r["analysis_values"], ensure_ascii=False) if r["analysis_values"] else None,
    ),
    "eval_status": ("Evaluation", _quality("eval_status")),
    "label": ("Your label", _quality("label")),
}


def pick_columns(raw: str | None) -> list[str]:
    chosen = [c.strip() for c in (raw or "").split(",") if c.strip() in COLUMNS]
    return list(dict.fromkeys(chosen)) or list(COLUMNS)


def _cell(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    # Spreadsheet formula injection: a leading =, +, - or @ is read as a formula.
    return "'" + text if text[:1] in ("=", "+", "-", "@") and not text[1:2].isdigit() else text


def csv_lines(rows: Sequence[Mapping[str, Any]], columns: Sequence[str]) -> Iterator[str]:
    buffer = io.StringIO()
    writer = csv.writer(buffer)

    def flush() -> str:
        value = buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)
        return value

    writer.writerow([COLUMNS[c][0] for c in columns])
    yield flush()
    for row in rows:
        writer.writerow([_cell(COLUMNS[c][1](row)) for c in columns])
        yield flush()
