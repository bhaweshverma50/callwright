"""Caller language (012)."""

from __future__ import annotations

from app.caller_language.router import internal_router, router
from app.core.feature import Feature

FEATURE = Feature("caller_language", routers=(router, internal_router), id_prefixes=frozenset({"cpf", "clg"}))
