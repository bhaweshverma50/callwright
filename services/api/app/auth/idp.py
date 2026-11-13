"""Identity provider adapters (T035, research R5).

The API wraps the IdP so it can throttle sign-ins, bootstrap workspaces and sign out globally.
Two adapters implement ``IdentityProvider``:

* ``LocalIdentityProvider`` (``AUTH_PROVIDER=local``): an offline IdP for development and tests.
  Users, one-time tokens and refresh sessions live in the ``local_idp`` schema; access tokens
  are HS256 JWTs shaped like Supabase's (``sub``, ``email``, ``session_id``, ``aud``).
  Verification and reset "emails" are logged to the console and kept in an in-memory outbox
  served by ``GET /v1/dev/mail``.
* ``SupabaseIdentityProvider`` (``AUTH_PROVIDER=supabase``): Supabase Auth (GoTrue) REST API.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import logging
import secrets
import smtplib
import time
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from typing import Any, Protocol

import httpx
import jwt
from sqlalchemy import text

from app.core.auth import TokenClaims
from app.core.config import Settings
from app.core.db import Database

logger = logging.getLogger("app.auth.idp")

VERIFY_TTL = timedelta(hours=24)
RECOVERY_TTL = timedelta(minutes=60)


class IdpError(Exception):
    pass


class InvalidCredentials(IdpError):
    pass


class EmailNotConfirmed(IdpError):
    pass


class InvalidLink(IdpError):
    """One-time link unknown, used or expired."""


class InvalidRefreshToken(IdpError):
    pass


class IdpRateLimited(IdpError):
    pass


class IdpUnavailable(IdpError):
    pass


@dataclass(frozen=True)
class IdpUser:
    subject: str
    email: str
    email_confirmed: bool


@dataclass(frozen=True)
class IdpSession:
    access_token: str
    refresh_token: str
    expires_in: int
    user: IdpUser


@dataclass(frozen=True)
class OutboxMessage:
    to: str
    kind: str
    link: str
    token_hash: str
    sent_at: datetime


class IdentityProvider(Protocol):
    name: str

    async def sign_up(self, email: str, password: str, *, confirmed: bool = False) -> None:
        """Create the account. ``confirmed`` (AUTH_AUTO_VERIFY_EMAIL) skips the verification
        email where the adapter can; Supabase decides through its own "Confirm email" setting."""
        ...

    async def resend_verification(self, email: str) -> None: ...

    async def verify_email(self, token_hash: str) -> IdpSession: ...

    async def sign_in(self, email: str, password: str) -> IdpSession: ...

    async def refresh(self, refresh_token: str) -> IdpSession: ...

    async def sign_out(self, access_token: str, claims: TokenClaims) -> None: ...

    async def request_password_reset(self, email: str) -> None: ...

    async def confirm_password_reset(self, token_hash: str, new_password: str) -> list[str]:
        """Set the new password and revoke the user's sessions; returns revoked session ids
        (when known) so their access tokens can be blocked until expiry."""
        ...


def _mask_email(address: str) -> str:
    local, _, domain = address.partition("@")
    return f"{local[:1]}***@{domain}"


def _send_smtp(settings: Settings, to: str, subject: str, body: str) -> None:
    """Blocking SMTP send with STARTTLS (call through ``asyncio.to_thread``)."""
    message = EmailMessage()
    message["From"] = settings.smtp_from or settings.smtp_username or "noreply@localhost"
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    assert settings.smtp_host is not None
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
        smtp.starttls()
        if settings.smtp_username and settings.smtp_password:
            smtp.login(settings.smtp_username, settings.smtp_password.get_secret_value())
        smtp.send_message(message)


_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**14, 8, 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P)
    return f"scrypt${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def check_password(password: str, stored: str) -> bool:
    try:
        _, salt_b64, digest_b64 = stored.split("$")
        salt, expected = base64.b64decode(salt_b64), base64.b64decode(digest_b64)
    except ValueError:
        return False
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P)
    return hmac.compare_digest(digest, expected)


_DUMMY_HASH = hash_password("timing-equaliser-not-a-password")


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class LocalIdentityProvider:
    name = "local"

    def __init__(self, settings: Settings, db: Database) -> None:
        self.db = db
        self.secret = settings.auth_jwt_secret.get_secret_value()
        self.audience = settings.auth_jwt_audience
        self.issuer = settings.auth_jwt_issuer
        self.ttl = settings.auth_access_token_ttl_s
        self.web_base_url = settings.web_base_url.rstrip("/")
        self.settings = settings
        self.outbox: deque[OutboxMessage] = deque(maxlen=200)

    def _access_token(self, subject: str, email: str, session_id: str) -> str:
        now = int(time.time())
        claims: dict[str, Any] = {
            "sub": subject,
            "email": email,
            "session_id": session_id,
            "aud": self.audience,
            "role": "authenticated",
            "iat": now,
            "exp": now + self.ttl,
        }
        if self.issuer:
            claims["iss"] = self.issuer
        return jwt.encode(claims, self.secret, algorithm="HS256")

    async def _new_session(self, user_id: str, email: str) -> IdpSession:
        session_id = str(uuid.uuid4())
        refresh = secrets.token_urlsafe(32)
        async with self.db.transaction() as s:
            await s.execute(
                text(
                    "insert into local_idp.sessions (id, user_id, refresh_token_hash) values (:id, :uid, :h)"
                ),
                {"id": session_id, "uid": user_id, "h": _sha256(refresh)},
            )
        return IdpSession(
            access_token=self._access_token(user_id, email, session_id),
            refresh_token=refresh,
            expires_in=self.ttl,
            user=IdpUser(user_id, email, True),
        )

    async def _issue_token(self, user_id: str, email: str, kind: str) -> None:
        raw = secrets.token_urlsafe(32)
        ttl = VERIFY_TTL if kind == "verify_email" else RECOVERY_TTL
        async with self.db.transaction() as s:
            await s.execute(
                text(
                    "insert into local_idp.one_time_tokens (token_hash, user_id, kind, expires_at) "
                    "values (:h, :uid, :kind, :exp)"
                ),
                {"h": _sha256(raw), "uid": user_id, "kind": kind, "exp": datetime.now(UTC) + ttl},
            )
        path = "verify-email" if kind == "verify_email" else "reset-password"
        link = f"{self.web_base_url}/{path}?token_hash={raw}"
        self.outbox.append(OutboxMessage(email, kind, link, raw, datetime.now(UTC)))
        subject = "Verify your email" if kind == "verify_email" else "Reset your password"
        if self.settings.smtp_host:
            await self._email(email, subject, kind, link)
        else:
            logger.warning("[dev mail] to=%s subject=%r link=%s", email, subject, link)

    async def _email(self, to: str, subject: str, kind: str, link: str) -> None:
        """Send the outbox message by SMTP. Never raises: the caller already answered
        ``verification_sent`` and the user can ask for the link again."""
        action = "verify your email address" if kind == "verify_email" else "reset your password"
        body = f"Open this link to {action}:\n\n{link}\n\nIf you did not ask for this, ignore this email.\n"
        try:
            await asyncio.to_thread(_send_smtp, self.settings, to, subject, body)
        except Exception as exc:
            # The exception text can echo the message, so log its type only.
            logger.warning("could not email %s to %s (%s)", kind, _mask_email(to), type(exc).__name__)

    async def _user_by_email(self, email: str) -> Any:
        async with self.db.transaction() as s:
            return (
                await s.execute(
                    text(
                        "select id, email::text as email, password_hash, email_confirmed_at "
                        "from local_idp.users where email = :e"
                    ),
                    {"e": email.lower()},
                )
            ).first()

    async def _consume(self, token_hash: str, kind: str) -> Any:
        async with self.db.transaction() as s:
            row = (
                await s.execute(
                    text(
                        "update local_idp.one_time_tokens t set used_at = now() "
                        "from local_idp.users u "
                        "where t.token_hash = :h and t.kind = :kind and t.used_at is null "
                        "and t.expires_at > now() and u.id = t.user_id "
                        "returning u.id, u.email::text as email"
                    ),
                    {"h": _sha256(token_hash), "kind": kind},
                )
            ).first()
        if row is None:
            raise InvalidLink(kind)
        return row

    async def sign_up(self, email: str, password: str, *, confirmed: bool = False) -> None:
        existing = await self._user_by_email(email)
        if existing is not None:
            if existing.email_confirmed_at is None:
                # Auto-verify confirms an unverified account only for the password that made it.
                if confirmed and check_password(password, existing.password_hash):
                    await self._confirm(existing.id)
                else:
                    await self._issue_token(existing.id, existing.email, "verify_email")
            return
        user_id = str(uuid.uuid4())
        async with self.db.transaction() as s:
            await s.execute(
                text(
                    "insert into local_idp.users (id, email, password_hash, email_confirmed_at) "
                    "values (:id, :e, :p, case when :confirmed then now() end) "
                    "on conflict (email) do nothing"
                ),
                {"id": user_id, "e": email.lower(), "p": hash_password(password), "confirmed": confirmed},
            )
        if not confirmed:
            await self._issue_token(user_id, email.lower(), "verify_email")

    async def _confirm(self, user_id: str) -> None:
        async with self.db.transaction() as s:
            await s.execute(
                text(
                    "update local_idp.users set email_confirmed_at = coalesce(email_confirmed_at, now()) "
                    "where id = :id"
                ),
                {"id": user_id},
            )

    async def resend_verification(self, email: str) -> None:
        user = await self._user_by_email(email)
        if user is not None and user.email_confirmed_at is None:
            await self._issue_token(user.id, user.email, "verify_email")

    async def verify_email(self, token_hash: str) -> IdpSession:
        row = await self._consume(token_hash, "verify_email")
        await self._confirm(row.id)
        return await self._new_session(row.id, row.email)

    async def sign_in(self, email: str, password: str) -> IdpSession:
        user = await self._user_by_email(email)
        if user is None:
            check_password(password, _DUMMY_HASH)
            raise InvalidCredentials()
        if not check_password(password, user.password_hash):
            raise InvalidCredentials()
        if user.email_confirmed_at is None:
            raise EmailNotConfirmed()
        return await self._new_session(user.id, user.email)

    async def sign_in_external(self, email: str) -> IdpSession:
        """Sign in an email an external provider (Google) has verified; no password involved.

        * No such user: create one, confirmed, with an unusable password (a random hash nobody
          knows); a real password can be set later through password reset.
        * Confirmed user: sign in.
        * Unconfirmed user: someone may have registered this email with their own password and
          never verified it. Confirm the user, replace the password hash with an unusable one so
          that password stops working, and revoke their sessions and outstanding one-time tokens
          (a pending verification link must not open the account either).
        """
        email = email.strip().lower()
        user_id = str(uuid.uuid4())
        unusable = hash_password(secrets.token_urlsafe(32))
        async with self.db.transaction() as s:
            created = (
                await s.execute(
                    text(
                        "insert into local_idp.users (id, email, password_hash, email_confirmed_at) "
                        "values (:id, :e, :p, now()) on conflict (email) do nothing returning id"
                    ),
                    {"id": user_id, "e": email, "p": unusable},
                )
            ).first()
            if created is None:
                row = (
                    await s.execute(
                        text(
                            "select id::text as id, email::text as email, email_confirmed_at "
                            "from local_idp.users where email = :e for update"
                        ),
                        {"e": email},
                    )
                ).one()
                user_id, email = row.id, row.email
                if row.email_confirmed_at is None:
                    await s.execute(
                        text(
                            "update local_idp.users set password_hash = :p, email_confirmed_at = now() "
                            "where id = :id"
                        ),
                        {"p": unusable, "id": user_id},
                    )
                    await s.execute(
                        text(
                            "update local_idp.sessions set revoked_at = now() "
                            "where user_id = :id and revoked_at is null"
                        ),
                        {"id": user_id},
                    )
                    await s.execute(
                        text(
                            "update local_idp.one_time_tokens set used_at = now() "
                            "where user_id = :id and used_at is null"
                        ),
                        {"id": user_id},
                    )
        return await self._new_session(user_id, email)

    async def refresh(self, refresh_token: str) -> IdpSession:
        new_refresh = secrets.token_urlsafe(32)
        async with self.db.transaction() as s:
            row = (
                await s.execute(
                    text(
                        "update local_idp.sessions s set refresh_token_hash = :new "
                        "from local_idp.users u "
                        "where s.refresh_token_hash = :old and s.revoked_at is null and u.id = s.user_id "
                        "returning s.id, u.id as user_id, u.email::text as email"
                    ),
                    {"old": _sha256(refresh_token), "new": _sha256(new_refresh)},
                )
            ).first()
        if row is None:
            raise InvalidRefreshToken()
        return IdpSession(
            access_token=self._access_token(row.user_id, row.email, row.id),
            refresh_token=new_refresh,
            expires_in=self.ttl,
            user=IdpUser(row.user_id, row.email, True),
        )

    async def sign_out(self, access_token: str, claims: TokenClaims) -> None:
        async with self.db.transaction() as s:
            await s.execute(
                text(
                    "update local_idp.sessions set revoked_at = now() "
                    "where user_id = :uid and revoked_at is null"
                ),
                {"uid": claims.subject},
            )

    async def request_password_reset(self, email: str) -> None:
        user = await self._user_by_email(email)
        if user is not None:
            await self._issue_token(user.id, user.email, "recovery")

    async def confirm_password_reset(self, token_hash: str, new_password: str) -> list[str]:
        row = await self._consume(token_hash, "recovery")
        async with self.db.transaction() as s:
            await s.execute(
                text(
                    "update local_idp.users set password_hash = :p, "
                    "email_confirmed_at = coalesce(email_confirmed_at, now()) where id = :id"
                ),
                {"p": hash_password(new_password), "id": row.id},
            )
            revoked = (
                await s.execute(
                    text(
                        "update local_idp.sessions set revoked_at = now() "
                        "where user_id = :id and revoked_at is null returning id"
                    ),
                    {"id": row.id},
                )
            ).scalars()
            return [str(r) for r in revoked]

    def latest_message(self, to: str, kind: str) -> OutboxMessage | None:
        for message in reversed(self.outbox):
            if message.to == to.lower() and message.kind == kind:
                return message
        return None


class SupabaseIdentityProvider:
    """Supabase Auth (GoTrue) over its REST API. Verification and recovery emails use templates
    that link to the web app with ``token_hash`` (``/verify-email`` and ``/reset-password``)."""

    name = "supabase"

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        if not settings.supabase_url:
            raise ValueError("SUPABASE_URL is required")
        anon = settings.supabase_anon_key.get_secret_value() if settings.supabase_anon_key else ""
        self.web_base_url = settings.web_base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(
            base_url=f"{settings.supabase_url.rstrip('/')}/auth/v1", timeout=10.0
        )
        self._headers = {"apikey": anon}

    async def _post(
        self,
        path: str,
        json: dict[str, Any] | None = None,
        *,
        bearer: str | None = None,
        params: dict[str, str] | None = None,
    ) -> httpx.Response:
        headers = dict(self._headers)
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"
        try:
            response = await self._client.post(path, json=json or {}, headers=headers, params=params)
        except httpx.HTTPError as exc:
            raise IdpUnavailable(str(exc)) from exc
        if response.status_code == 429:
            raise IdpRateLimited()
        if response.status_code >= 500:
            raise IdpUnavailable(f"identity provider returned {response.status_code}")
        return response

    @staticmethod
    def _error_code(response: httpx.Response) -> str:
        try:
            body = response.json()
        except ValueError:
            return ""
        return str(body.get("error_code") or body.get("code") or body.get("error") or "")

    @staticmethod
    def _session(body: dict[str, Any]) -> IdpSession:
        user = body.get("user") or {}
        return IdpSession(
            access_token=str(body["access_token"]),
            refresh_token=str(body["refresh_token"]),
            expires_in=int(body.get("expires_in", 3600)),
            user=IdpUser(
                subject=str(user.get("id", "")),
                email=str(user.get("email", "")).lower(),
                email_confirmed=bool(user.get("email_confirmed_at") or user.get("confirmed_at")),
            ),
        )

    async def sign_up(self, email: str, password: str, *, confirmed: bool = False) -> None:
        # ``confirmed`` is decided by the project's "Confirm email" setting in Supabase.
        response = await self._post(
            "/signup",
            {"email": email, "password": password},
            params={"redirect_to": f"{self.web_base_url}/verify-email"},
        )
        if response.status_code >= 400 and self._error_code(response) not in {
            "user_already_exists",
            "email_exists",
        }:
            raise IdpError(f"sign-up failed ({response.status_code})")

    async def resend_verification(self, email: str) -> None:
        await self._post("/resend", {"type": "signup", "email": email})

    async def verify_email(self, token_hash: str) -> IdpSession:
        response = await self._post("/verify", {"type": "email", "token_hash": token_hash})
        if response.status_code >= 400:
            raise InvalidLink("verify_email")
        return self._session(response.json())

    async def sign_in(self, email: str, password: str) -> IdpSession:
        response = await self._post(
            "/token", {"email": email, "password": password}, params={"grant_type": "password"}
        )
        if response.status_code >= 400:
            if self._error_code(response) == "email_not_confirmed":
                raise EmailNotConfirmed()
            raise InvalidCredentials()
        return self._session(response.json())

    async def refresh(self, refresh_token: str) -> IdpSession:
        response = await self._post(
            "/token", {"refresh_token": refresh_token}, params={"grant_type": "refresh_token"}
        )
        if response.status_code >= 400:
            raise InvalidRefreshToken()
        return self._session(response.json())

    async def sign_out(self, access_token: str, claims: TokenClaims) -> None:
        await self._post("/logout", bearer=access_token, params={"scope": "global"})

    async def request_password_reset(self, email: str) -> None:
        await self._post(
            "/recover", {"email": email}, params={"redirect_to": f"{self.web_base_url}/reset-password"}
        )

    async def confirm_password_reset(self, token_hash: str, new_password: str) -> list[str]:
        response = await self._post("/verify", {"type": "recovery", "token_hash": token_hash})
        if response.status_code >= 400:
            raise InvalidLink("recovery")
        session = self._session(response.json())
        headers = dict(self._headers) | {"Authorization": f"Bearer {session.access_token}"}
        try:
            update = await self._client.put("/user", json={"password": new_password}, headers=headers)
        except httpx.HTTPError as exc:
            raise IdpUnavailable(str(exc)) from exc
        if update.status_code >= 400:
            raise IdpError(f"password update failed ({update.status_code})")
        await self._post("/logout", bearer=session.access_token, params={"scope": "global"})
        return []


def build_idp(settings: Settings, db: Database) -> LocalIdentityProvider | SupabaseIdentityProvider:
    if settings.auth_provider == "supabase":
        return SupabaseIdentityProvider(settings)
    return LocalIdentityProvider(settings, db)
