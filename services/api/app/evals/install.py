"""Wire 007 into the app and the jobs worker (T004, T022, T038, T040).

* offline fake replies for judges and analysis (``evals.fakes``);
* the 003 pipeline handlers for ``analyze`` and ``evaluate``;
* 006's ``CallQualityPort``;
* the built-in evaluator catalog sync (API only: the jobs worker does not touch the database at
  start-up and relies on the API or the ``migrate`` role having synced it).
"""

from __future__ import annotations

from app.analysis_vars.jobs import pipeline_handler as analyze
from app.calls import ports
from app.core.feature import Feature, Runtime
from app.evals import fakes
from app.evals.jobs import EVALUATE_CALL, evaluate_call
from app.evals.jobs import pipeline_handler as evaluate
from app.evals.quality_port import QualityPort
from app.evals.router import router
from app.evaluators.registry import sync_builtins


def install_handlers() -> None:
    ports.set_step_handler("analyze", analyze)
    ports.set_step_handler("evaluate", evaluate)


async def install(runtime: Runtime) -> None:
    fakes.register_fakes()
    install_handlers()
    ports.set_quality_port(QualityPort())
    if runtime.role == "api":
        await sync_builtins(runtime.db, runtime.settings)


FEATURE = Feature(
    "evals",
    routers=(router,),
    install=install,
    jobs={EVALUATE_CALL: evaluate_call},
    id_prefixes=frozenset({"evr"}),
)
