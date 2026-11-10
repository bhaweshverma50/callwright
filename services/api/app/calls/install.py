"""Calls (003 write side, 006 read side): admission, claim and the post-call pipeline.

``install`` gives 003's extension points the object signer, so worker
runtime config, the ``call_analyzed`` webhook and evaluators get signed links to ambience and
recordings.
"""

from __future__ import annotations

from arq import cron

from app.calls import ports
from app.calls.jobs import reap_stuck_calls, run_pipeline
from app.calls.lifecycle import RUN_PIPELINE
from app.calls.read_router import router as read_router
from app.calls.router import router
from app.core.feature import Feature, Runtime


def install(runtime: Runtime) -> None:
    ports.set_object_signer(runtime.signer)


FEATURE = Feature(
    "calls",
    routers=(router, read_router),
    install=install,
    jobs={RUN_PIPELINE: run_pipeline, "reap_stuck_calls": reap_stuck_calls},
    # 003 R16.
    crons=(cron(reap_stuck_calls, second={0, 15, 30, 45}, run_at_startup=False, unique=True),),
    id_prefixes=frozenset({"call"}),
)
