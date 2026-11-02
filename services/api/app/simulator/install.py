"""Wire 008 into the app and the jobs worker: offline fake replies for the model calls it makes
(test case drafting and judging, persona briefs), its arq jobs and crons."""

from __future__ import annotations

from typing import Any

from arq import cron
from arq.cron import CronJob


def install() -> None:
    from app.simulator import persona
    from app.test_cases import generate
    from app.test_runs import judge

    generate.register_fakes()
    judge.register_fakes()
    persona.register_fakes()


def job_functions() -> list[Any]:
    from app.simulator.jobs import dispatch_simulation, purge_simulation_data, sweep_simulations
    from app.test_runs.jobs import dispatch_test_case, judge_result

    return [dispatch_simulation, dispatch_test_case, judge_result, sweep_simulations, purge_simulation_data]


def crons() -> list[CronJob]:
    from app.simulator.jobs import purge_simulation_data, sweep_simulations

    return [
        cron(sweep_simulations, second={20}, run_at_startup=False, unique=True),
        cron(purge_simulation_data, hour={5}, minute={0}, run_at_startup=False),
    ]
