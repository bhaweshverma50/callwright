"""Workspace bootstrap and settings (T037, T038, T089; research R7)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.billing import service as billing
from app.core.auth import Principal, resolve_subject
from app.core.config import Settings
from app.core.db import Database
from app.core.ids import new_id
from app.workspaces.models import User, Workspace


@dataclass(frozen=True)
class Bootstrapped:
    user_id: str
    workspace_id: str
    created: bool


def default_workspace_name(email: str) -> str:
    local = email.split("@", 1)[0] or "My"
    return f"{local}'s workspace"[:80]


async def bootstrap_workspace(db: Database, settings: Settings, *, subject: str, email: str) -> Bootstrapped:
    """Create the user, workspace and trial grant in one transaction, once per IdP subject.

    Called on email verification (and on sign-in when a verified IdP user has no workspace yet).
    """
    row = await resolve_subject(db, subject)
    if row is not None and row.workspace_id is not None:
        return Bootstrapped(row.user_id, row.workspace_id, created=False)
    user_id = row.user_id if row is not None else new_id("usr")
    workspace_id = new_id("ws")
    try:
        async with db.transaction(workspace_id=workspace_id, user_id=user_id) as session:
            if row is None:
                session.add(
                    User(
                        id=user_id,
                        idp_subject=subject,
                        email=email.lower(),
                        email_verified_at=datetime.now(UTC),
                        is_admin=False,
                    )
                )
                await session.flush()
            session.add(
                Workspace(
                    id=workspace_id,
                    name=default_workspace_name(email),
                    owner_user_id=user_id,
                    concurrency_limit=settings.default_concurrency,
                    recording_default=True,
                )
            )
            await session.flush()
            if settings.trial_credit_usd > 0:
                await billing.post_transaction(
                    session,
                    workspace_id=workspace_id,
                    type="trial_grant",
                    amount_usd=Decimal(settings.trial_credit_usd).quantize(Decimal("0.000001")),
                    description="Trial credit",
                )
    except IntegrityError:
        # A concurrent verification won the race; return what it created.
        again = await resolve_subject(db, subject)
        if again is None or again.workspace_id is None:
            raise
        return Bootstrapped(again.user_id, again.workspace_id, created=False)
    return Bootstrapped(user_id, workspace_id, created=True)


@dataclass(frozen=True)
class MeView:
    user: User
    workspace: Workspace
    balance_usd: Decimal


async def get_me(db: Database, principal: Principal) -> MeView:
    async with db.transaction(workspace_id=principal.workspace_id, user_id=principal.user_id) as session:
        user = (await session.execute(select(User).where(User.id == principal.user_id))).scalar_one()
        workspace = (
            await session.execute(select(Workspace).where(Workspace.id == principal.workspace_id))
        ).scalar_one()
        balance = await billing.get_balance(session, principal.workspace_id)
    return MeView(user, workspace, balance)


async def update_workspace(
    db: Database, principal: Principal, *, name: str | None, recording_default: bool | None
) -> Workspace:
    async with db.transaction(workspace_id=principal.workspace_id, user_id=principal.user_id) as session:
        workspace = (
            await session.execute(select(Workspace).where(Workspace.id == principal.workspace_id))
        ).scalar_one()
        if name is not None:
            workspace.name = name
        if recording_default is not None:
            workspace.recording_default = recording_default
        await session.flush()
        return workspace
