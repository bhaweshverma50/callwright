"""What one feature package contributes to the API and the jobs worker.

Each feature declares a ``FEATURE`` manifest in its ``install.py``; ``app/features.py`` lists them
once and both ``app.main`` and ``app.worker`` iterate that list, so a new feature is wired by
adding one line there. Core never imports a feature.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx
from arq.cron import CronJob
from fastapi import APIRouter

from app.core.config import Settings
from app.core.db import Database
from app.core.queue import JobQueue
from app.core.storage import ObjectSigner, ObjectStore

JobFunction = Callable[..., Awaitable[Any]]


@dataclass(frozen=True)
class Runtime:
    """What an ``install`` hook gets: the same values in the API process and the jobs worker."""

    role: Literal["api", "worker"]
    settings: Settings
    db: Database
    queue: JobQueue
    http: httpx.AsyncClient
    store: ObjectStore
    signer: ObjectSigner


@dataclass(frozen=True)
class Feature:
    """``jobs`` maps the name callers enqueue to the arq job function; ``job_timeouts`` gives a
    job a timeout in seconds other than arq's default (300). ``conditional_routers`` pairs a
    ``Settings`` flag with a router mounted only when the flag is true."""

    name: str
    routers: tuple[APIRouter, ...] = ()
    conditional_routers: tuple[tuple[str, APIRouter], ...] = ()
    install: Callable[[Runtime], Awaitable[None] | None] | None = None
    jobs: Mapping[str, JobFunction] = field(default_factory=dict)
    job_timeouts: Mapping[str, int] = field(default_factory=dict)
    crons: tuple[CronJob, ...] = ()
    id_prefixes: frozenset[str] = frozenset()
    secret_fields: tuple[str, ...] = ()
