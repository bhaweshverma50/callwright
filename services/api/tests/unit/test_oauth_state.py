"""OAuth state and PKCE for Google connections (022 T021, research R4)."""

from __future__ import annotations

import base64
import hashlib
from urllib.parse import parse_qs, urlsplit

import pytest

from app.connectors import oauth
from tests.conftest import make_settings


class MemoryRedis:
    """The three Redis calls the OAuth state uses."""

    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}
        self.ttls: dict[str, int] = {}

    async def set(self, key: str, value: str, ex: int) -> None:
        self.values[key] = value.encode()
        self.ttls[key] = ex

    async def getdel(self, key: str) -> bytes | None:
        self.ttls.pop(key, None)
        return self.values.pop(key, None)

    async def ttl(self, key: str) -> int:
        return self.ttls.get(key, -2)


@pytest.fixture
def redis() -> MemoryRedis:
    return MemoryRedis()


async def test_authorization_url_carries_scopes_pkce_and_redirect(redis: MemoryRedis) -> None:
    settings = make_settings(connectors_drive_mode="live")
    url = await oauth.start(redis, settings, workspace_id="ws_1", user_id="usr_1")
    parts = urlsplit(url)
    assert parts.netloc == "accounts.google.com"
    q = {k: v[0] for k, v in parse_qs(parts.query).items()}
    assert q["scope"].split() == [
        "openid",
        "email",
        "https://www.googleapis.com/auth/drive.readonly",
        "https://www.googleapis.com/auth/spreadsheets",
    ]
    assert q["access_type"] == "offline" and q["prompt"] == "consent"
    assert q["include_granted_scopes"] == "true"
    assert q["redirect_uri"] == settings.google_oauth_redirect_uri
    assert q["client_id"] == settings.google_oauth_client_id
    assert q["code_challenge_method"] == "S256"
    pending = await oauth.consume(redis, q["state"])
    assert pending is not None
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(pending.verifier.encode()).digest()).rstrip(b"=").decode()
    )
    assert q["code_challenge"] == expected
    assert 43 <= len(pending.verifier) <= 128


async def test_state_is_single_use_and_bound(redis: MemoryRedis) -> None:
    settings = make_settings(connectors_drive_mode="live")
    url = await oauth.start(redis, settings, workspace_id="ws_1", user_id="usr_1", connection_id="conn_1")
    state = parse_qs(urlsplit(url).query)["state"][0]
    pending = await oauth.consume(redis, state)
    assert pending is not None
    assert (pending.workspace_id, pending.user_id, pending.connection_id) == ("ws_1", "usr_1", "conn_1")
    assert await oauth.consume(redis, state) is None


async def test_state_expires_after_ten_minutes(redis: MemoryRedis) -> None:
    settings = make_settings(connectors_drive_mode="live")
    url = await oauth.start(redis, settings, workspace_id="ws_1", user_id="usr_1")
    state = parse_qs(urlsplit(url).query)["state"][0]
    ttl = await redis.ttl(f"{oauth.STATE_PREFIX}{state}")
    assert 590 <= ttl <= oauth.STATE_TTL_S


async def test_fake_mode_returns_straight_to_the_callback(redis: MemoryRedis) -> None:
    settings = make_settings()
    url = await oauth.start(redis, settings, workspace_id="ws_1", user_id="usr_1")
    parts = urlsplit(url)
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == settings.google_oauth_redirect_uri
    q = parse_qs(parts.query)
    assert q["code"] == ["fake-code"] and q["state"]
