"""Development-only routes (see ``dev/router.py``), mounted by settings flag."""

from __future__ import annotations

from app.core.feature import Feature
from app.core.storage import dev_router as storage_router
from app.dev.fake_drive import router as fake_drive_router
from app.dev.router import checkout_router, router

FEATURE = Feature(
    "dev",
    conditional_routers=(
        ("dev_routes_enabled", router),
        ("dev_routes_enabled", storage_router),
        ("fake_checkout_enabled", checkout_router),
        ("fake_drive_routes_enabled", fake_drive_router),
    ),
)
