"""Cloudflare Turnstile check for registration (TURNSTILE_SECRET_KEY; off when unset)."""

from __future__ import annotations

import logging

import httpx

from app.core.config import Settings
from app.core.errors import ProblemError

logger = logging.getLogger(__name__)

SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
TIMEOUT_S = 5.0


def _failed() -> ProblemError:
    return ProblemError(
        400,
        "captcha_failed",
        "Captcha check failed",
        "We could not confirm you are human. Reload the check and try again.",
    )


async def verify_captcha(
    settings: Settings, token: str | None, ip: str, client: httpx.AsyncClient | None = None
) -> None:
    """Raise 400 ``captcha_failed`` for a missing or rejected token and 503 when Cloudflare cannot
    be reached (fail closed). Does nothing when no secret is configured."""
    if settings.turnstile_secret_key is None:
        return
    if not token:
        raise _failed()
    data = {
        "secret": settings.turnstile_secret_key.get_secret_value(),
        "response": token,
        "remoteip": ip,
    }
    try:
        if client is not None:
            resp = await client.post(SITEVERIFY_URL, data=data)
        else:
            async with httpx.AsyncClient(timeout=TIMEOUT_S) as http:
                resp = await http.post(SITEVERIFY_URL, data=data)
        resp.raise_for_status()
        success = resp.json().get("success") is True
    except (httpx.HTTPError, ValueError):
        logger.warning("turnstile verification unavailable", exc_info=True)
        raise ProblemError(
            503,
            "auth_unavailable",
            "Service unavailable",
            "Sign-up is temporarily unavailable. Try again shortly.",
        ) from None
    if not success:
        raise _failed()
