"""Google connections (022 US1; research R4, R5, R6).

A connection is one Google account's access granted to a workspace. Its refresh token lives only
in ``secrets`` (001) under ``conn:{id}:refresh``; access tokens are exchanged per operation and
never stored. Health comes from tests and real use: a refused refresh marks the connection
``revoked`` and every source using it ``needs_attention / access_lost`` (sources are never
emptied because access went away).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors import activity, oauth
from app.connectors.models import Connection
from app.core.config import Settings
from app.core.errors import ProblemError, forbidden, not_found
from app.core.ids import new_id
from app.core.secrets import KeyWrapper, delete_secret, get_secret, put_secret
from app.knowledge.sources.drive import (
    SCOPE_DRIVE,
    SCOPE_SHEETS,
    AccessToken,
    DriveClient,
    GoogleTemporary,
    OAuthExchangeFailed,
    TokenRevoked,
)
from app.workspaces.models import Workspace


@dataclass(frozen=True)
class ConnectorDeps:
    settings: Settings
    redis: Any
    wrapper: KeyWrapper
    drive: DriveClient


def now() -> datetime:
    return datetime.now(UTC)


def mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}" if domain else "***"


def unavailable() -> ProblemError:
    return ProblemError(
        503,
        "connector_unavailable",
        "Google Drive is not configured",
        "Google Drive is not configured on this server.",
    )


def ensure_configured(settings: Settings) -> None:
    if not settings.google_configured:
        raise unavailable()


def revoked_problem() -> ProblemError:
    return ProblemError(
        409,
        "connection_revoked",
        "Connection revoked",
        "Google access was revoked or expired. Reconnect the Google account.",
    )


def _oauth_problem(code: str, detail: str) -> ProblemError:
    return ProblemError(400, code, "Google sign-in failed", detail)


async def require_owner(session: AsyncSession, workspace_id: str, user_id: str) -> None:
    """FR-007: only the workspace owner manages connections."""
    owner = (
        await session.execute(select(Workspace.owner_user_id).where(Workspace.id == workspace_id))
    ).scalar_one_or_none()
    if owner != user_id:
        raise forbidden("Only the workspace owner can manage connections.")


async def get_connection(session: AsyncSession, connection_id: str) -> Connection:
    conn = await session.get(Connection, connection_id)
    if conn is None:
        raise not_found("connection")
    return conn


async def complete(
    session: AsyncSession,
    deps: ConnectorDeps,
    *,
    workspace_id: str,
    user_id: str,
    state: str,
    code: str | None,
    error: str | None,
) -> tuple[Connection, bool]:
    """Finish Google sign-in. Returns the connection and whether it is new."""
    pending = await oauth.consume(deps.redis, state)
    if pending is None or pending.workspace_id != workspace_id or pending.user_id != user_id:
        raise _oauth_problem(
            "oauth_state_invalid", "This sign-in link expired or belongs to someone else. Start again."
        )
    if error or not code:
        raise _oauth_problem("oauth_declined", "Google access was not granted, so no connection was made.")
    try:
        grant = await deps.drive.exchange_code(
            code, pending.verifier, deps.settings.google_oauth_redirect_uri
        )
    except (OAuthExchangeFailed, GoogleTemporary) as exc:
        raise _oauth_problem(
            "oauth_exchange_failed", exc.message or "Google refused the sign-in. Try again."
        ) from exc
    if SCOPE_DRIVE not in grant.scopes:
        await deps.drive.revoke(grant.refresh_token)
        raise _oauth_problem(
            "oauth_scope_missing",
            "Read-only Google Drive access is required for knowledge sync. Connect again and allow it.",
        )
    conn: Connection | None
    if pending.connection_id:
        conn = await get_connection(session, pending.connection_id)
        if conn.account_subject != grant.subject:
            await deps.drive.revoke(grant.refresh_token)
            raise _oauth_problem(
                "oauth_account_mismatch",
                f"This connection belongs to {mask_email(conn.account_email)}. "
                "Sign in with that account, or add a new connection.",
            )
    else:
        conn = (
            await session.execute(
                select(Connection).where(
                    Connection.provider == "google", Connection.account_subject == grant.subject
                )
            )
        ).scalar_one_or_none()
    created = conn is None
    if conn is None:
        conn_id = new_id("conn")
        conn = Connection(
            id=conn_id,
            workspace_id=workspace_id,
            provider="google",
            kind="oauth",
            account_subject=grant.subject,
            account_email=grant.email,
            secret_name=f"conn:{conn_id}:refresh",
            created_by=user_id,
        )
        session.add(conn)
    conn.account_email = grant.email or conn.account_email
    conn.scopes = list(grant.scopes)
    conn.sheets_access = SCOPE_SHEETS in grant.scopes
    conn.health = "healthy"
    conn.health_reason = None
    conn.last_success_at = conn.last_checked_at = now()
    conn.updated_at = now()
    await session.flush()
    await put_secret(session, deps.wrapper, workspace_id, conn.secret_name, grant.refresh_token)
    await activity.record(
        session,
        workspace_id=workspace_id,
        action="connection_added" if created else "connection_reconnected",
        subject_type="connection",
        subject_id=conn.id,
        actor_user_id=user_id,
        detail={"account_email": grant.email},
    )
    if not created:
        await resume_sources(session, conn)
    return conn, created


async def resume_sources(session: AsyncSession, conn: Connection) -> list[str]:
    """After a reconnect, sources that lost access through this connection's token go back to
    waiting and are due at once (022 T079). Returns their ids."""
    rows = await session.execute(
        update(_sources())
        .where(text("connection_id = :c AND state = 'needs_attention' AND attention_reason = 'access_lost'"))
        .values(state="pending", attention_reason=None, next_sync_at=now())
        .returning(text("id")),
        {"c": conn.id},
    )
    return [str(r[0]) for r in rows.all()]


def _sources() -> Any:
    from app.knowledge.models import KnowledgeSource

    return KnowledgeSource.__table__


async def mark_revoked(session: AsyncSession, conn: Connection, reason: str = "invalid_grant") -> None:
    conn.health = "revoked"
    conn.health_reason = reason
    conn.last_checked_at = conn.updated_at = now()
    await session.execute(
        update(_sources())
        .where(text("connection_id = :c"))
        .values(state="needs_attention", attention_reason="access_lost"),
        {"c": conn.id},
    )
    await session.flush()


async def access_token(session: AsyncSession, deps: ConnectorDeps, conn: Connection) -> AccessToken:
    """A fresh access token for one operation. Raises ``TokenRevoked`` (after marking the
    connection and its sources) or ``GoogleTemporary``."""
    refresh = await get_secret(session, deps.wrapper, conn.workspace_id, conn.secret_name)
    if refresh is None:
        await mark_revoked(session, conn, "token_missing")
        raise TokenRevoked("The connection has no stored Google access")
    try:
        token = await deps.drive.refresh(refresh)
    except TokenRevoked:
        await mark_revoked(session, conn)
        raise
    except GoogleTemporary:
        conn.health = "failing"
        conn.health_reason = "google_unavailable"
        conn.last_checked_at = now()
        raise
    conn.health = "healthy"
    conn.health_reason = None
    conn.last_success_at = conn.last_checked_at = now()
    return token


async def test(session: AsyncSession, deps: ConnectorDeps, conn: Connection) -> Connection:
    """FR-003: a live check; health is updated either way and the check is never an error."""
    try:
        await access_token(session, deps, conn)
    except (TokenRevoked, GoogleTemporary):
        pass
    await session.flush()
    return conn


async def users_of(session: AsyncSession, connection_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    if not connection_ids:
        return {}
    rows = await session.execute(
        text("""
        SELECT s.connection_id, s.id, s.kb_id, k.name, s.root_name
          FROM kb_sources s JOIN knowledge_bases k ON k.id = s.kb_id
         WHERE s.connection_id = ANY(CAST(:ids AS text[]))
         ORDER BY k.name, s.root_name
        """),
        {"ids": connection_ids},
    )
    out: dict[str, list[dict[str, Any]]] = {}
    for conn_id, source_id, kb_id, kb_name, root_name in rows.all():
        out.setdefault(str(conn_id), []).append(
            {"source_id": source_id, "kb_id": kb_id, "kb_name": kb_name, "root_name": root_name}
        )
    return out


async def remove(session: AsyncSession, deps: ConnectorDeps, conn: Connection, user_id: str) -> str | None:
    """Delete the connection and its secret. Returns the refresh token so the caller can revoke
    it at Google after the transaction commits (best effort)."""
    users = (await users_of(session, [conn.id])).get(conn.id, [])
    if users:
        raise ProblemError(
            409,
            "connection_in_use",
            "Connection in use",
            "Remove the knowledge sources that use this connection first.",
            extra={"users": users},
        )
    refresh = await get_secret(session, deps.wrapper, conn.workspace_id, conn.secret_name)
    await delete_secret(session, conn.workspace_id, conn.secret_name)
    await activity.record(
        session,
        workspace_id=conn.workspace_id,
        action="connection_removed",
        subject_type="connection",
        subject_id=conn.id,
        actor_user_id=user_id,
        detail={"account_email": conn.account_email},
    )
    await session.delete(conn)
    await session.flush()
    return refresh


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def view(conn: Connection, source_count: int) -> dict[str, Any]:
    return {
        "id": conn.id,
        "provider": conn.provider,
        "kind": conn.kind,
        "account_email": conn.account_email,
        "scopes": list(conn.scopes),
        "sheets_access": conn.sheets_access,
        "health": conn.health,
        "health_reason": conn.health_reason,
        "last_success_at": _iso(conn.last_success_at),
        "last_checked_at": _iso(conn.last_checked_at),
        "source_count": source_count,
        "created_at": conn.created_at.isoformat(),
    }


async def list_views(session: AsyncSession) -> list[dict[str, Any]]:
    conns = list((await session.execute(select(Connection).order_by(Connection.created_at))).scalars())
    users = await users_of(session, [c.id for c in conns])
    return [view(c, len(users.get(c.id, []))) for c in conns]


async def detail_view(session: AsyncSession, conn: Connection) -> dict[str, Any]:
    users = (await users_of(session, [conn.id])).get(conn.id, [])
    source_ids = [u["source_id"] for u in users]
    entries = await activity.recent(session, [conn.id, *source_ids])
    return {
        **view(conn, len(users)),
        "users": users,
        "activity": [
            {
                "action": a.action,
                "actor_user_id": a.actor_user_id,
                "detail": a.detail,
                "created_at": a.created_at.isoformat(),
            }
            for a in entries
        ],
    }
