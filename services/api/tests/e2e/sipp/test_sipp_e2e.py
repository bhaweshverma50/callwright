"""Optional SIPp end-to-end checks for phone numbers (010 T067, quickstart section 6).

Skipped unless ``SIPP_E2E=1``: they need Docker, a running local stack (API, jobs worker, voice
worker, LiveKit) with ``LIVEKIT_SIP_HOST`` set, livekit-sip started by ``run.sh up``, numbers set
up as README.md describes and ``CALLWRIGHT_TOKEN``. CI never sets the flag.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

RUN = Path(__file__).with_name("run.sh")

pytestmark = pytest.mark.skipif(
    os.environ.get("SIPP_E2E") != "1", reason="set SIPP_E2E=1 to run SIPp scenarios"
)


@pytest.mark.parametrize("scenario", ["inbound_answer", "outbound_busy"])
def test_sipp_scenario(scenario: str) -> None:
    result = subprocess.run([str(RUN), scenario], capture_output=True, text=True, timeout=180, check=False)
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-3000:]
    assert f"PASS {scenario}" in result.stdout
