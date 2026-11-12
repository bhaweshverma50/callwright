"""Drive sources for knowledge bases (022): the Drive client, the sync engine and its routes.

``install(settings, http)`` runs from the connectors feature's ``install`` in the API and the jobs
worker and picks the client: ``HttpDriveClient`` for ``CONNECTORS_DRIVE_MODE=live``, the
process-wide ``FakeDriveClient`` for ``fake``. Tests swap it with ``install(..., client=fake)``.
"""

from __future__ import annotations

import httpx

from app.core.config import Settings, get_settings
from app.knowledge.sources.drive import DriveClient

_client: DriveClient | None = None


def install(
    settings: Settings, http: httpx.AsyncClient | None = None, *, client: DriveClient | None = None
) -> DriveClient:
    global _client
    if client is not None:
        _client = client
    elif settings.connectors_drive_mode == "fake":
        from app.knowledge.sources.fake_drive import shared_fake

        _client = shared_fake()
    else:
        from app.knowledge.sources.http_drive import HttpDriveClient

        _client = HttpDriveClient(
            http or httpx.AsyncClient(follow_redirects=False),
            settings.google_oauth_client_id,
            settings.google_oauth_client_secret.get_secret_value(),
        )
    return _client


def drive_client() -> DriveClient:
    return _client or install(get_settings())
