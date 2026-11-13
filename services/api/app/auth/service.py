"""Auth flows over the IdP adapter (T036; research R5 to R8, R18).

* Sign-in is throttled per account (5 failures in 15 minutes) and per client IP (20).
* Verification bootstraps the user, workspace and trial credit (R7).
* Sign-out revokes the IdP session and blocks the access token's session id in Redis (R8).
* Registration and reset requests never reveal whether an email is registered.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass

from redis.asyncio import Redis

from app.auth import idp as idp_mod
from app.auth.captcha import verify_captcha
from app.auth.disposable import check_email_allowed
from app.auth.idp import IdentityProvider, IdpSession
from app.core.auth import TokenClaims, revoke_session
from app.core.config import Settings
from app.core.db import Database
from app.core.errors import ProblemError, too_many_requests, unauthorized
from app.core.rate_limit import FailureCounter, RateLimiter
from app.workspaces.service import bootstrap_workspace

logger = logging.getLogger(__name__)


def account_key(email: str) -> str:
    return "auth:fail:" + hashlib.sha256(email.strip().lower().encode()).hexdigest()


def ip_key(ip: str) -> str:
    return f"auth:failip:{ip}"


def _idp_down() -> ProblemError:
    return ProblemError(
        503,
        "auth_unavailable",
        "Service unavailable",
        "Sign-in is temporarily unavailable. Try again shortly.",
    )


@dataclass
class AuthService:
    settings: Settings
    db: Database
    redis: Redis
    idp: IdentityProvider

    @property
    def failures(self) -> FailureCounter:
        return FailureCounter(self.redis)

    async def _email_rate_limit(self, ip: str) -> None:
        result = await RateLimiter(self.redis).hit(
            "auth_email", ip, limit=self.settings.auth_email_rate_limit_per_hour, window_s=3600
        )
        if not result.allowed:
            raise too_many_requests(result.retry_after_s, "Too many emails requested. Try again later.")

    async def register(
        self, email: str, password: str, ip: str, captcha_token: str | None = None
    ) -> IdpSession | None:
        """Create the account. Returns a session only with AUTH_AUTO_VERIFY_EMAIL (demo hosting):
        the account is confirmed at once and signed in through the normal sign-in path, which
        also bootstraps the workspace. Otherwise, or when that sign-in does not succeed (the
        email belongs to an account this password does not open, or the IdP still wants the
        email link), the caller answers ``verification_sent`` as usual."""
        await self._email_rate_limit(ip)
        check_email_allowed(self.settings, email)
        await verify_captcha(self.settings, captcha_token, ip)
        auto_verify = self.settings.auth_auto_verify_email
        try:
            await self.idp.sign_up(email, password, confirmed=auto_verify)
        except idp_mod.IdpRateLimited as exc:
            raise too_many_requests(60, "Too many sign-up attempts. Try again later.") from exc
        except idp_mod.IdpUnavailable as exc:
            raise _idp_down() from exc
        if not auto_verify:
            return None
        try:
            return await self.sign_in(email, password, ip)
        except ProblemError as exc:
            logger.info("registration auto-verify did not sign in (%s)", exc.code)
            return None

    async def resend_verification(self, email: str, ip: str) -> None:
        await self._email_rate_limit(ip)
        try:
            await self.idp.resend_verification(email)
        except idp_mod.IdpRateLimited as exc:
            raise too_many_requests(60, "Too many emails requested. Try again later.") from exc
        except idp_mod.IdpError:
            logger.info("resend verification failed", exc_info=True)

    async def verify_email(self, token_hash: str) -> IdpSession:
        try:
            session = await self.idp.verify_email(token_hash)
        except idp_mod.InvalidLink as exc:
            raise ProblemError(
                400,
                "invalid_link",
                "Link expired or already used",
                "This verification link is invalid, expired or already used.",
            ) from exc
        except idp_mod.IdpUnavailable as exc:
            raise _idp_down() from exc
        await bootstrap_workspace(
            self.db, self.settings, subject=session.user.subject, email=session.user.email, redis=self.redis
        )
        return session

    async def sign_in(self, email: str, password: str, ip: str) -> IdpSession:
        failures = self.failures
        akey, ikey = account_key(email), ip_key(ip)
        count, ttl = await failures.count(akey)
        if count >= self.settings.login_fail_limit:
            raise too_many_requests(ttl, f"Too many failed sign-ins. Try again in {_minutes(ttl)}.")
        ip_count, ip_ttl = await failures.count(ikey)
        if ip_count >= self.settings.login_fail_ip_limit:
            raise too_many_requests(ip_ttl, f"Too many failed sign-ins. Try again in {_minutes(ip_ttl)}.")
        try:
            session = await self.idp.sign_in(email, password)
        except idp_mod.InvalidCredentials as exc:
            window = self.settings.login_fail_window_s
            await failures.add(akey, window)
            await failures.add(ikey, window)
            raise ProblemError(
                401, "invalid_credentials", "Wrong email or password", "The email or password is not correct."
            ) from exc
        except idp_mod.EmailNotConfirmed as exc:
            raise ProblemError(
                403,
                "email_unverified",
                "Email not verified",
                "Verify your email address first. We can send the link again.",
                extra={"action": "resend_verification"},
            ) from exc
        except idp_mod.IdpRateLimited as exc:
            raise too_many_requests(60, "Too many sign-in attempts. Try again shortly.") from exc
        except idp_mod.IdpUnavailable as exc:
            raise _idp_down() from exc
        await failures.clear(akey)
        if session.user.email_confirmed:
            await bootstrap_workspace(
                self.db,
                self.settings,
                subject=session.user.subject,
                email=session.user.email,
                redis=self.redis,
            )
        return session

    async def refresh(self, refresh_token: str) -> IdpSession:
        try:
            return await self.idp.refresh(refresh_token)
        except idp_mod.InvalidRefreshToken as exc:
            raise unauthorized("Your session has ended. Sign in again.", "invalid_refresh_token") from exc
        except idp_mod.IdpUnavailable as exc:
            raise _idp_down() from exc

    async def sign_out(self, access_token: str, claims: TokenClaims) -> None:
        try:
            await self.idp.sign_out(access_token, claims)
        except idp_mod.IdpError:
            logger.warning("IdP sign-out failed; the session is still revoked locally", exc_info=True)
        await revoke_session(self.redis, claims.session_id, expires_at=claims.expires_at)

    async def request_password_reset(self, email: str, ip: str) -> None:
        await self._email_rate_limit(ip)
        try:
            await self.idp.request_password_reset(email)
        except idp_mod.IdpRateLimited as exc:
            raise too_many_requests(60, "Too many reset requests. Try again later.") from exc
        except idp_mod.IdpError:
            logger.info("password reset request failed", exc_info=True)

    async def confirm_password_reset(self, token_hash: str, new_password: str) -> None:
        try:
            revoked = await self.idp.confirm_password_reset(token_hash, new_password)
        except idp_mod.InvalidLink as exc:
            raise ProblemError(
                400,
                "invalid_link",
                "Link expired or already used",
                "This reset link is invalid, expired or already used.",
            ) from exc
        except idp_mod.IdpUnavailable as exc:
            raise _idp_down() from exc
        expires_at = int(time.time()) + self.settings.auth_access_token_ttl_s
        for session_id in revoked:
            await revoke_session(self.redis, session_id, expires_at=expires_at)


def _minutes(seconds: int) -> str:
    minutes = max(1, -(-seconds // 60))
    return f"{minutes} minute" + ("" if minutes == 1 else "s")
