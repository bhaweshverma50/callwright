"""GET /v1/health (contracts/core.yaml)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter(tags=["core"])


class Health(BaseModel):
    status: Literal["ok"] = "ok"
    version: str


@router.get("/health", response_model=Health)
async def get_health(request: Request) -> Health:
    return Health(version=request.app.state.settings.version)
