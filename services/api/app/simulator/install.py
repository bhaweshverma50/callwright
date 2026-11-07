"""Wire simulations into the app and the jobs worker: the run snapshot of a simulated call (003
port), offline fake replies for persona briefs, its arq jobs and crons."""

from __future__ import annotations

from arq import cron

from app.calls import ports
from app.core.feature import Feature, Runtime
from app.simulator import persona
from app.simulator.internal_router import router as internal_router
from app.simulator.jobs import (
    DISPATCH_SIMULATION,
    dispatch_simulation,
    purge_simulation_data,
    sweep_simulations,
)
from app.simulator.router import router
from app.simulator.service import run_snapshot


def install(runtime: Runtime) -> None:
    ports.set_run_snapshot(run_snapshot)
    persona.register_fakes()


FEATURE = Feature(
    "simulator",
    routers=(router, internal_router),
    install=install,
    jobs={
        DISPATCH_SIMULATION: dispatch_simulation,
        "sweep_simulations": sweep_simulations,
        "purge_simulation_data": purge_simulation_data,
    },
    crons=(
        cron(sweep_simulations, second={20}, run_at_startup=False, unique=True),
        cron(purge_simulation_data, hour={5}, minute={0}, run_at_startup=False),
    ),
    id_prefixes=frozenset({"exp", "srun"}),
)
