"""Call recordings (003 egress, 006 signed links)."""

from __future__ import annotations

from arq import cron

from app.calls.lifecycle import START_RECORDING
from app.core.feature import Feature
from app.recordings.egress import settle_stuck_recordings, start_recording
from app.recordings.router import router

FEATURE = Feature(
    "recordings",
    routers=(router,),
    jobs={START_RECORDING: start_recording, "settle_stuck_recordings": settle_stuck_recordings},
    # Recordings whose egress_ended webhook was lost.
    crons=(cron(settle_stuck_recordings, second={50}, run_at_startup=False, unique=True),),
)
