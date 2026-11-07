"""Calls (003 write side, 006 read side): admission, claim, the post-call pipeline, recordings.

``install`` gives 003's extension points the object signer, so worker runtime config, the
``call_analyzed`` webhook and evaluators get signed links to ambience and recordings.
"""

from __future__ import annotations

from arq import cron

from app.calls import ports
from app.calls.effects import RUN_PIPELINE, START_RECORDING
from app.calls.jobs import reap_stuck_calls, run_pipeline, settle_stuck_recordings, start_recording
from app.calls.read_router import router as read_router
from app.calls.router import router
from app.core.feature import Feature, Runtime
from app.core.storage import build_signer


def install(runtime: Runtime) -> None:
    ports.set_object_signer(build_signer(runtime.settings))


FEATURE = Feature(
    "calls",
    routers=(router, read_router),
    install=install,
    jobs={
        RUN_PIPELINE: run_pipeline,
        START_RECORDING: start_recording,
        "reap_stuck_calls": reap_stuck_calls,
        "settle_stuck_recordings": settle_stuck_recordings,
    },
    crons=(
        # 003 R16.
        cron(reap_stuck_calls, second={0, 15, 30, 45}, run_at_startup=False, unique=True),
        # Recordings whose egress_ended webhook was lost.
        cron(settle_stuck_recordings, second={50}, run_at_startup=False, unique=True),
    ),
    id_prefixes=frozenset({"call"}),
)
