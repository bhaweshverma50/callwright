"""Write a 21 MB file for manual upload checks (``python -m tests.fixtures.knowledge.make_oversize``)."""

from __future__ import annotations

import sys
from pathlib import Path

from tests.fixtures.knowledge import oversize

if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "oversize.pdf")
    target.write_bytes(oversize())
    print(f"wrote {target} ({target.stat().st_size} bytes)")
