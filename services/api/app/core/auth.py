"""Access-token verification and request principals (T012).

Tokens are JWTs issued by the identity provider. They are verified locally: with the shared
HS256 secret (local dev IdP, Supabase legacy secret) or against the IdP JWKS (asymmetric keys,
cached 10 minutes). A token whose ``session_id`` was signed out is rejected through the Redis key
``auth:revoked:{session_id}`` (R8). The IdP subject is mapped to our user and workspace by the
``app_resolve_subject`` security-definer function, so no RLS context is needed for the lookup.
"""

from __future__ import annotations

import asyncio
import hmac
import time
from dataclasses import dataclass
from typing import Annotated, Any

import jwt
from fastapi import Depends, Request
from opentelemetry import trace
from redis.asyncio import Redis
from sqlalchemy import text

from app.core.config import Settings
from app.core.db import Database
from app.core.errors import ProblemError, forbidden, unauthorized

REVOKED_KEY = "auth:revoked:{session_id}"


@dataclass(frozen=True)
class TokenClaims:
    subject: str
    email: str | None
    session_id: str
    expires_at: int


class TokenVerifier:
    def __init__(self, settings: Settings) -> None:
        self.audience = settings.auth_jwt_audience
        self.issuer = settings.auth_jwt_issuer
        self.secret = settings.auth_jwt_secret.get_secret_value()
        self.jwks: jwt.PyJWKClient | None = (
            jwt.PyJWKClient(settings.auth_jwks_url, cache_keys=True, lifespan=600)
            if settings.auth_jwks_url
            else None
        )

    async def verify(self, token: str) -> TokenClaims:
        try:
            header = jwt.get_unverified_header(token)
            alg = str(header.get("alg", ""))
            key: Any
            if alg == "HS256":
                key = self.secret
            elif self.jwks is not None and alg in {"RS256", "ES256"}:
                key = (await asyncio.to_thread(self.jwks.get_signing_key_from_jwt, token)).key
            else:
                raise jwt.InvalidAlgorithmError(alg)
            options = {"require": ["exp", "sub"]}
            claims = jwt.decode(
                token,
                key,
                algorithms=[alg],
                audience=self.audience,
                issuer=self.issuer,
                options=options,  # type: ignore[arg-type]
                leeway=5,
            )
        except jwt.ExpiredSignatureError as exc:
            raise unauthorized("Your session has expired. Sign in again.", "token_expired") from exc
        except (jwt.PyJWTError, ValueError) as exc:
            raise unauthorized("The access token is not valid.", "invalid_token") from exc
        session_id = str(
            claims.get("session_id") or claims.get("jti") or f"{claims['sub']}:{claims.get('iat')}"
        )
        return TokenClaims(
            subject=str(claims["sub"]),
            email=claims.get("email"),
            session_id=session_id,
            expires_at=int(claims["exp"]),
        )


@dataclass(frozen=True)
class Principal:
    user_id: str
    workspace_id: str
    email: str
    email_verified: bool
    is_admin: bool
    session_id: str
    token_expires_at: int


@dataclass(frozen=True)
class SubjectRow:
    user_id: str
    workspace_id: str | None
    email: str
    email_verified: bool
    is_admin: bool


async def resolve_subject(db: Database, subject: str) -> SubjectRow | None:
    async with db.transaction() as session:
        row = (
            await session.execute(
                text(
                    "select user_id, workspace_id, email, email_verified, is_admin "
                    "from app_resolve_subject(:sub)"
                ),
                {"sub": subject},
            )
        ).first()
    if row is None:
        return None
    return SubjectRow(
        user_id=row.user_id,
        workspace_id=row.workspace_id,
        email=row.email,
        email_verified=bool(row.email_verified),
        is_admin=bool(row.is_admin),
    )


async def revoke_session(redis: Redis, claims: TokenClaims) -> None:
    ttl = max(1, claims.expires_at - int(time.time()) + 5)
    await redis.set(REVOKED_KEY.format(session_id=claims.session_id), "1", ex=ttl)


def bearer_token(request: Request) -> str:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise unauthorized()
    return token.strip()


async def current_claims(request: Request) -> TokenClaims:
    verifier: TokenVerifier = request.app.state.verifier
    redis: Redis = request.app.state.redis
    claims = await verifier.verify(bearer_token(request))
    if await redis.exists(REVOKED_KEY.format(session_id=claims.session_id)):
        raise unauthorized("This session was signed out. Sign in again.", "session_revoked")
    return claims


async def current_principal(
    request: Request, claims: Annotated[TokenClaims, Depends(current_claims)]
) -> Principal:
    row = await resolve_subject(request.app.state.db, claims.subject)
    if row is None:
        # A valid signature for a user that no longer exists (deleted account, reset database):
        # the session is dead, so 401 lets clients refresh or sign out instead of looping on 403.
        raise unauthorized("This session is no longer valid. Sign in again.", "session_invalid")
    if row.workspace_id is None:
        raise ProblemError(
            403, "email_unverified", "Email not verified", "Verify your email address to continue."
        )
    principal = Principal(
        user_id=row.user_id,
        workspace_id=row.workspace_id,
        email=row.email,
        email_verified=row.email_verified,
        is_admin=row.is_admin,
        session_id=claims.session_id,
        token_expires_at=claims.expires_at,
    )
    request.state.principal = principal
    trace.get_current_span().set_attribute("workspace_id", principal.workspace_id)
    return principal


async def require_admin(principal: Annotated[Principal, Depends(current_principal)]) -> Principal:
    if not principal.is_admin:
        raise forbidden("This action needs a platform administrator.", "admin_required")
    return principal


async def require_service(request: Request) -> None:
    """Static service token for /v1/internal/* endpoints (voice worker)."""
    token = bearer_token(request)
    expected = request.app.state.settings.service_token.get_secret_value()
    if not hmac.compare_digest(token.encode(), expected.encode()):
        raise unauthorized("Service token is not valid.", "invalid_service_token")


CurrentClaims = Annotated[TokenClaims, Depends(current_claims)]
CurrentPrincipal = Annotated[Principal, Depends(current_principal)]
AdminPrincipal = Annotated[Principal, Depends(require_admin)]
