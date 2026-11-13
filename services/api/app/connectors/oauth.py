"""Google sign-in for connections (022 research R4): authorization code with PKCE.

``start`` stores ``{workspace, user, PKCE verifier, connection}`` under a random single-use state
for 10 minutes and builds Google's authorization URL. Google sends the browser back to the web
app's callback page, which posts the code and state to ``POST /connections/google/complete``
with the user's normal bearer token; ``consume`` reads and deletes the state in one step.

In ``CONNECTORS_DRIVE_MODE=fake`` the URL points straight at the web app's callback with a fake
code (or Google's ``access_denied`` when the fake consent is set to decline), so the whole flow
runs locally with no Google account.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlencode

from app.core.config import Settings
from app.knowledge.sources.drive import SCOPES

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
STATE_PREFIX = "oauth_state:"
STATE_TTL_S = 600


class StateStore(Protocol):
    async def set(self, key: str, value: str, ex: int) -> Any: ...

    async def getdel(self, key: str) -> Any: ...


@dataclass(frozen=True)
class PendingAuth:
    workspace_id: str
    user_id: str
    verifier: str
    connection_id: str | None = None


def challenge(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


async def start(
    redis: StateStore,
    settings: Settings,
    *,
    workspace_id: str,
    user_id: str,
    connection_id: str | None = None,
) -> str:
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)  # 86 characters, inside PKCE's 43 to 128
    pending = {
        "workspace_id": workspace_id,
        "user_id": user_id,
        "verifier": verifier,
        "connection_id": connection_id,
    }
    await redis.set(f"{STATE_PREFIX}{state}", json.dumps(pending), ex=STATE_TTL_S)
    if settings.connectors_drive_mode == "fake":
        from app.knowledge.sources import drive_client
        from app.knowledge.sources.fake_drive import FakeDriveClient

        fake = drive_client()
        declined = isinstance(fake, FakeDriveClient) and fake.consent_decline
        outcome = {"error": "access_denied"} if declined else {"code": "fake-code"}
        return f"{settings.google_oauth_redirect_uri}?{urlencode({**outcome, 'state': state})}"
    query = {
        "client_id": settings.google_oauth_client_id,
        "redirect_uri": settings.google_oauth_redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
        "code_challenge": challenge(verifier),
        "code_challenge_method": "S256",
    }
    return f"{AUTHORIZE_URL}?{urlencode(query)}"


async def consume(redis: StateStore, state: str) -> PendingAuth | None:
    raw = await redis.getdel(f"{STATE_PREFIX}{state}")
    if raw is None:
        return None
    data = json.loads(raw)
    return PendingAuth(
        workspace_id=data["workspace_id"],
        user_id=data["user_id"],
        verifier=data["verifier"],
        connection_id=data.get("connection_id"),
    )
