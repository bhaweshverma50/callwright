"""Write the compiled-flow JSON Schema for the voice worker (004 T040).

``uv run python -m app.flows.export_schema`` writes
``services/voice-worker/worker/flow/compiled_schema.json``; ``--check`` exits 1 when the
committed file is stale (run in CI and by ``tests/unit/flows/test_compiled_schema.py``).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.flows.compiled import CompiledFlow

TARGET = Path(__file__).resolve().parents[3] / "voice-worker" / "worker" / "flow" / "compiled_schema.json"


def render() -> str:
    return json.dumps(CompiledFlow.model_json_schema(), indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    text = render()
    if args.check:
        current = TARGET.read_text() if TARGET.exists() else ""
        if current != text:
            print(f"{TARGET} is stale; run python -m app.flows.export_schema", file=sys.stderr)
            return 1
        return 0
    TARGET.write_text(text)
    print(f"wrote {TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
