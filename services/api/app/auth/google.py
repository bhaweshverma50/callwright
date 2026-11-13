"""Sign in with Google: authorization code flow with PKCE (S256) and a nonce.

``start`` stores ``{verifier, nonce}`` in Redis under a random state for 10 minutes; ``complete``
reads and deletes it in one step (GETDEL), so a state works once, then exchanges the code at
Google's token endpoint and returns the verified email.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from typing import Any
from urllib.parse import urlencode

import httpx
from redis.asyncio import Redis

from app.core.config import Settings
from app.core.errors import ProblemError

logger = logging.getLogger(__name__)

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105
ISSUERS = frozenset({"accounts.google.com", "https://accounts.google.com"})
STATE_TTL_S = 600
TIMEOUT_S = 10.0


def _state_key(state: str) -> str:
    return f"auth:google:state:{state}"


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _state_invalid() -> ProblemError:
    return ProblemError(
        400,
        "oauth_state_invalid",
        "Google sign-in expired",
        "This Google sign-in link is invalid, expired or already used. Start again.",
    )


def _unavailable() -> ProblemError:
    return ProblemError(
        502,
        "google_unavailable",
        "Google is unavailable",
        "Google sign-in is not available right now. Try again shortly or use your password.",
    )


def _unverified() -> ProblemError:
    return ProblemError(
        400,
        "google_email_unverified",
        "Google email not verified",
        "Google has not verified this email address, so we cannot sign you in with it.",
    )


def _client_credentials(settings: Settings) -> tuple[str, str]:
    assert settings.google_signin_client_id is not None
    assert settings.google_signin_client_secret is not None
    return settings.google_signin_client_id, settings.google_signin_client_secret.get_secret_value()


async def start(settings: Settings, redis: Redis) -> str:
    """Create the state, PKCE verifier and nonce, and return Google's authorization URL."""
    client_id, _ = _client_credentials(settings)
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    nonce = secrets.token_urlsafe(32)
    await redis.set(_state_key(state), json.dumps({"verifier": verifier, "nonce": nonce}), ex=STATE_TTL_S)
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
    query = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": settings.google_signin_redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "prompt": "select_account",
        }
    )
    return f"{AUTH_URL}?{query}"


async def _consume_state(redis: Redis, state: str) -> dict[str, str]:
    raw = await redis.getdel(_state_key(state))
    if raw is None:
        raise _state_invalid()
    try:
        stored = json.loads(raw)
        return {"verifier": str(stored["verifier"]), "nonce": str(stored["nonce"])}
    except (ValueError, KeyError, TypeError):
        raise _state_invalid() from None


async def _exchange(settings: Settings, code: str, verifier: str, client: httpx.AsyncClient | None) -> str:
    client_id, client_secret = _client_credentials(settings)
    data = {
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": settings.google_signin_redirect_uri,
        "grant_type": "authorization_code",
        "code_verifier": verifier,
    }
    try:
        if client is not None:
            resp = await client.post(TOKEN_URL, data=data)
        else:
            async with httpx.AsyncClient(timeout=TIMEOUT_S) as http:
                resp = await http.post(TOKEN_URL, data=data)
    except httpx.HTTPError:
        logger.warning("google token exchange unreachable", exc_info=True)
        raise _unavailable() from None
    if resp.status_code == 400:
        try:
            error = str(resp.json().get("error", ""))
        except ValueError:
            error = ""
        if error == "invalid_grant":  # the code is wrong, expired or already used
            raise _state_invalid()
    if resp.status_code != 200:
        logger.warning("google token exchange failed (%s)", resp.status_code)
        raise _unavailable()
    try:
        token = resp.json()["id_token"]
    except (ValueError, KeyError, TypeError):
        token = None
    if not isinstance(token, str):
        logger.warning("google token response has no id_token")
        raise _unavailable()
    return token


def _claims(id_token: str) -> dict[str, Any]:
    """Decode the id_token payload WITHOUT verifying its signature.

    That is acceptable under OpenID Connect Core section 3.1.3.7: the token came straight from
    Google's token endpoint over TLS in answer to our own request, so TLS server authentication
    stands in for the signature. The claims are still checked in ``_check_claims``.
    """
    try:
        payload = id_token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError):
        logger.warning("google id_token is malformed")
        raise _unavailable() from None
    if not isinstance(claims, dict):
        raise _unavailable()
    return claims


def _check_claims(claims: dict[str, Any], client_id: str, nonce: str) -> str:
    aud = claims.get("aud")
    audiences = aud if isinstance(aud, list) else [aud]
    exp = claims.get("exp")
    got_nonce = claims.get("nonce")
    if (
        client_id not in audiences
        or claims.get("iss") not in ISSUERS
        or isinstance(exp, bool)
        or not isinstance(exp, int | float)
        or exp <= time.time()
        or not isinstance(got_nonce, str)
        or not hmac.compare_digest(got_nonce.encode(), nonce.encode())
    ):
        logger.warning("google id_token claims rejected")
        raise _state_invalid()
    if claims.get("email_verified") not in (True, "true"):
        raise _unverified()
    email = claims.get("email")
    if not isinstance(email, str) or "@" not in email or len(email) > 254:
        raise _unverified()
    return email.strip().lower()


async def complete(
    settings: Settings, redis: Redis, code: str, state: str, client: httpx.AsyncClient | None = None
) -> str:
    """Consume the state, exchange the code, check the id_token and return the verified email."""
    stored = await _consume_state(redis, state)
    id_token = await _exchange(settings, code, stored["verifier"], client)
    client_id, _ = _client_credentials(settings)
    return _check_claims(_claims(id_token), client_id, stored["nonce"])
