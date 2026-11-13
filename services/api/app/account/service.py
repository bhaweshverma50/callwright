"""Scheduling and cancelling account deletion (30-day grace period).

Scheduling re-authenticates the owner (their password, or for an account created through Google
their email), records ``deletion_scheduled_at``, ends every session and emails a confirmation.
While scheduled the API refuses every route except ``GET /me`` and cancelling (``core.auth``).
The erase job (``app.account.erase``) removes the account once the date has passed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import Request
from sqlalchemy import select, update

from app.auth.service import auth_service
from app.core.auth import Principal, TokenClaims, bearer_token
from app.core.client_ip import client_ip
from app.core.errors import field_error, validation_failed
from app.workspaces.models import User, Workspace

logger = logging.getLogger(__name__)

GRACE = timedelta(days=30)


@dataclass(frozen=True)
class Scheduled:
    requested_at: datetime
    scheduled_at: datetime


def _date(value: datetime) -> str:
    return f"{value.strftime('%B')} {value.day}, {value.year}"


async def schedule_deletion(
    request: Request,
    principal: Principal,
    claims: TokenClaims,
    *,
    confirm_workspace_name: str,
    password: str | None,
    confirm_email: str | None,
) -> Scheduled:
    db = request.app.state.db
    async with db.transaction(workspace_id=principal.workspace_id, user_id=principal.user_id) as session:
        name = (
            await session.execute(select(Workspace.name).where(Workspace.id == principal.workspace_id))
        ).scalar_one()
        subject = (
            await session.execute(select(User.idp_subject).where(User.id == principal.user_id))
        ).scalar_one()
    if confirm_workspace_name != name:
        raise validation_failed(
            [field_error("/confirm_workspace_name", "mismatch", "Type the workspace name exactly as shown.")]
        )
    auth = auth_service(request)
    if await auth.has_password(subject):
        if not password:
            raise validation_failed([field_error("/password", "required", "Enter your password.")])
        await auth.reauthenticate(subject, principal.email, password, client_ip(request))
    elif (confirm_email or "").strip().lower() != principal.email.lower():
        raise validation_failed(
            [field_error("/confirm_email", "mismatch", "Type your account email to confirm.")]
        )
    requested = datetime.now(UTC)
    scheduled = requested + GRACE
    async with db.transaction(workspace_id=principal.workspace_id, user_id=principal.user_id) as session:
        await session.execute(
            update(User)
            .where(User.id == principal.user_id)
            .values(deletion_requested_at=requested, deletion_scheduled_at=scheduled)
        )
    await auth.sign_out(bearer_token(request), claims)
    await auth.idp.notify(
        principal.email,
        "deletion_scheduled",
        "Your Callwright account will be deleted",
        f"Your Callwright account and its workspace will be deleted on {_date(scheduled)}.\n\n"
        "Until then you can sign in and choose Keep my account to cancel. After that date your "
        "agents, calls, recordings and knowledge are erased, your phone numbers are released and "
        "any remaining credit is forfeited.\n\nIf this wasn't you, sign in and choose Keep my "
        "account, then change your password.\n",
    )
    logger.info("account deletion scheduled for workspace %s", principal.workspace_id)
    return Scheduled(requested, scheduled)


async def cancel_deletion(request: Request, principal: Principal) -> None:
    async with request.app.state.db.transaction(
        workspace_id=principal.workspace_id, user_id=principal.user_id
    ) as session:
        await session.execute(
            update(User)
            .where(User.id == principal.user_id)
            .values(deletion_requested_at=None, deletion_scheduled_at=None)
        )
    if principal.deletion_scheduled_at is None:
        return
    await auth_service(request).idp.notify(
        principal.email,
        "deletion_cancelled",
        "Your Callwright account deletion was cancelled",
        "You chose to keep your Callwright account, so it will not be deleted. Nothing was "
        "erased.\n\nIf this wasn't you, change your password.\n",
    )
    logger.info("account deletion cancelled for workspace %s", principal.workspace_id)
