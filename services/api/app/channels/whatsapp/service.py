"""WhatsApp voice channels: create, setup, edit, delete, webhook and caller routes
(010 T052, T053, T058, T059, T084, research R10, R11).

Creation checks the access token against the business number first; a rejected token, an
unreachable WhatsApp or a number mismatch saves nothing. Then the row is saved and setup runs:
enable Calling with SIP delivery to our SIP host, read the SIP credentials Meta will use and
create the LiveKit inbound trunk (TLS media) and, when a default agent or any caller route
exists, the dispatch rule. A setup failure keeps the channel in ``error`` with compensation;
``retry-setup`` runs it again. The channel is ``setup_incomplete`` until WhatsApp's verification
request reaches the public webhook, then ``active``. Calls are routed in both states.

Secrets (access token, verify token, app secret, Meta SIP credentials) go through 001's
encrypted ``secrets`` table and are only ever shown as the last four characters.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import hooks as agent_hooks
from app.calls.models import Call
from app.channels import validation
from app.channels.provisioning import dispatch_spec
from app.channels.shared import (
    ChannelDeps,
    active_counts,
    agent_state,
    check_webhook_url,
    conflict,
    delete_or_drain,
    iso,
    require_published,
    sip_host,
    status_view,
)
from app.channels.sip import InboundTrunkSpec, SipError
from app.channels.whatsapp.graph_client import GraphError, WhatsAppGraph
from app.channels.whatsapp.models import WhatsAppCallerRoute, WhatsAppChannel
from app.channels.whatsapp.schemas import CallerRouteCreate, WhatsAppChannelCreate, WhatsAppChannelUpdate
from app.channels.whatsapp.signatures import verify_signature, verify_token_hash
from app.core.auth import Principal
from app.core.errors import ProblemError, field_error, not_found, validation_failed
from app.core.ids import new_id
from app.core.pagination import page_meta, page_window
from app.core.secrets import delete_secret, get_secret, put_secret

logger = logging.getLogger(__name__)

MAX_ROUTES = 1_000
SECRET = "whatsapp/{id}/{name}"  # noqa: S105 - secret names, not values
ROUTABLE = ("active", "setup_incomplete")


@dataclass
class WhatsAppDeps(ChannelDeps):
    graph: WhatsAppGraph | None = None


def _graph(deps: WhatsAppDeps) -> WhatsAppGraph:
    assert deps.graph is not None
    return deps.graph


def callback_url(deps: ChannelDeps) -> str:
    return f"{deps.settings.api_base_url.rstrip('/')}/v1/whatsapp/webhook"


def settings_view(deps: ChannelDeps) -> dict[str, Any]:
    return {
        "callback_url": callback_url(deps),
        "default_graph_api_version": deps.settings.whatsapp_graph_api_version,
        "telephony_enabled": deps.sip.live,
    }


def to_out(channel: WhatsAppChannel, active: int, routes: int) -> dict[str, Any]:
    return {
        "id": channel.id,
        "meta_phone_number_id": channel.meta_phone_number_id,
        "e164": channel.e164,
        "label": channel.label,
        "access_token_last4": channel.access_token_last4,
        "verify_token_last4": channel.verify_token_last4,
        "has_app_secret": True,
        "graph_api_version": channel.graph_api_version,
        "inbound_agent_id": channel.inbound_agent_id,
        "inbound_webhook_url": channel.inbound_webhook_url,
        "caller_route_count": routes,
        "status": status_view(channel.status),
        "status_detail": channel.status_detail,
        "credentials_verified_at": iso(channel.credentials_verified_at),
        "calling_enabled_at": iso(channel.calling_enabled_at),
        "webhook_verified_at": iso(channel.webhook_verified_at),
        "last_webhook_at": iso(channel.last_webhook_at),
        "active_call_count": active,
        "created_at": iso(channel.created_at),
        "updated_at": iso(channel.updated_at),
    }


async def _route_counts(session: AsyncSession, ids: list[str]) -> dict[str, int]:
    if not ids:
        return {}
    rows = await session.execute(
        select(WhatsAppCallerRoute.channel_id, func.count())
        .where(WhatsAppCallerRoute.channel_id.in_(ids))
        .group_by(WhatsAppCallerRoute.channel_id)
    )
    return {str(k): int(n) for k, n in rows.all()}


async def _out(session: AsyncSession, channel: WhatsAppChannel) -> dict[str, Any]:
    active = await active_counts(session, Call.whatsapp_channel_id, [channel.id])
    routes = await _route_counts(session, [channel.id])
    return to_out(channel, active.get(channel.id, 0), routes.get(channel.id, 0))


async def _load(session: AsyncSession, channel_id: str, *, lock: bool = False) -> WhatsAppChannel:
    query = select(WhatsAppChannel).where(
        WhatsAppChannel.id == channel_id, WhatsAppChannel.deleted_at.is_(None)
    )
    if lock:
        query = query.with_for_update()
    channel = (await session.execute(query)).scalar_one_or_none()
    if channel is None:
        raise not_found("WhatsApp channel")
    return channel


def _last4(value: str) -> str:
    return value[-4:] if len(value) >= 8 else "****"


def _graph_problem(exc: GraphError) -> ProblemError:
    if exc.kind == "unreachable":
        return ProblemError(
            502, "whatsapp_unreachable", "WhatsApp unreachable", f"{exc.message} Nothing was saved."
        )
    return ProblemError(
        422,
        "whatsapp_token_rejected",
        "WhatsApp rejected the credentials",
        f"WhatsApp said: {exc.message}",
        errors=[field_error("/access_token", "whatsapp_token_rejected", f"WhatsApp said: {exc.message}")],
    )


async def _check_credentials(deps: WhatsAppDeps, token: str, version: str, meta_id: str, e164: str) -> None:
    try:
        info = await _graph(deps).check_number(token, version, meta_id)
    except GraphError as exc:
        raise _graph_problem(exc) from None
    if info.display_phone_number is not None and validation.digits(
        info.display_phone_number
    ) != validation.digits(e164):
        reported = info.display_phone_number
        raise ProblemError(
            422,
            "whatsapp_number_mismatch",
            "Number does not match",
            f"WhatsApp reports {reported} for business phone number ID {meta_id}, not {e164}.",
            errors=[
                field_error("/e164", "whatsapp_number_mismatch", f"WhatsApp reports {reported} for this ID.")
            ],
        )


async def create_channel(
    deps: WhatsAppDeps, principal: Principal, body: WhatsAppChannelCreate
) -> dict[str, Any]:
    ws = principal.workspace_id
    version = body.graph_api_version or deps.settings.whatsapp_graph_api_version
    digest = verify_token_hash(body.verify_token)
    await check_webhook_url(deps.settings, body.inbound_webhook_url)
    async with deps.db.transaction(workspace_id=ws, user_id=principal.user_id) as s:
        await require_published(s, {"inbound_agent_id": body.inbound_agent_id})
        await _refuse_taken(s, body.meta_phone_number_id, digest)
    await _check_credentials(deps, body.access_token, version, body.meta_phone_number_id, body.e164)
    now = datetime.now(UTC)
    channel_id = new_id("wa")
    names = {n: SECRET.format(id=channel_id, name=n) for n in ("access_token", "verify_token", "app_secret")}
    async with deps.db.transaction(workspace_id=ws, user_id=principal.user_id) as s:
        channel = WhatsAppChannel(
            id=channel_id,
            workspace_id=ws,
            meta_phone_number_id=body.meta_phone_number_id,
            e164=body.e164,
            label=body.label,
            access_token_secret=names["access_token"],
            access_token_last4=_last4(body.access_token),
            verify_token_secret=names["verify_token"],
            verify_token_last4=_last4(body.verify_token),
            verify_token_hash=digest,
            app_secret_secret=names["app_secret"],
            graph_api_version=version,
            inbound_agent_id=body.inbound_agent_id,
            inbound_webhook_url=body.inbound_webhook_url,
            status="setup_incomplete",
            credentials_verified_at=now,
            created_at=now,
            updated_at=now,
        )
        s.add(channel)
        try:
            await s.flush()
        except IntegrityError:
            raise conflict(
                "whatsapp_number_already_connected",
                "This WhatsApp number is already connected to Callwright.",
            ) from None
        for name, value in (
            ("access_token", body.access_token),
            ("verify_token", body.verify_token),
            ("app_secret", body.app_secret),
        ):
            await put_secret(s, deps.wrapper, ws, names[name], value)
    return await _setup_and_store(deps, ws, channel_id)


async def _refuse_taken(
    session: AsyncSession, meta_id: str, digest: str | None, own_id: str | None = None
) -> None:
    if meta_id:
        taken = (
            await session.execute(text("select whatsapp_meta_id_in_use(:m)"), {"m": meta_id})
        ).scalar_one()
        if taken:
            raise conflict(
                "whatsapp_number_already_connected",
                "This WhatsApp number is already connected to Callwright.",
            )
    if digest:
        in_use = (
            await session.execute(text("select whatsapp_verify_hash_in_use(:h)"), {"h": digest})
        ).scalar_one()
        own = None
        if own_id:
            own = (
                await session.execute(
                    select(WhatsAppChannel.verify_token_hash).where(WhatsAppChannel.id == own_id)
                )
            ).scalar_one_or_none()
        if in_use and own != digest:
            raise conflict(
                "verify_token_in_use", "Another channel uses this verify token. Choose a different one."
            )


async def _secret(
    deps: ChannelDeps, session: AsyncSession, channel: WhatsAppChannel, name: str | None
) -> str | None:
    if not name:
        return None
    return await get_secret(session, deps.wrapper, channel.workspace_id, name)


async def _has_routes(session: AsyncSession, channel_id: str) -> bool:
    return bool(
        (
            await session.execute(
                select(func.count())
                .select_from(WhatsAppCallerRoute)
                .where(WhatsAppCallerRoute.channel_id == channel_id)
            )
        ).scalar_one()
    )


async def _setup_and_store(deps: WhatsAppDeps, workspace_id: str, channel_id: str) -> dict[str, Any]:
    """Enable calling, store Meta's SIP credentials, create the trunk and rule (R10)."""
    graph, sip = _graph(deps), deps.sip
    async with deps.db.transaction(workspace_id=workspace_id) as s:
        channel = await _load(s, channel_id)
        token = await _secret(deps, s, channel, channel.access_token_secret) or ""
        needs_rule = channel.inbound_agent_id is not None or await _has_routes(s, channel_id)
    created: list[tuple[str, str]] = []
    error: str | None = None
    credentials = None
    calling_enabled = False
    trunk_id, rule_id = channel.lk_inbound_trunk_id, channel.lk_dispatch_rule_id
    try:
        await graph.enable_calling(
            token, channel.graph_api_version, channel.meta_phone_number_id, sip_host(deps.settings)
        )
        calling_enabled = True
        credentials = await graph.sip_credentials(
            token, channel.graph_api_version, channel.meta_phone_number_id, channel.e164
        )
        if trunk_id is None:
            trunk_id = await sip.create_inbound_trunk(
                InboundTrunkSpec(
                    name=f"callwright {channel.id}",
                    numbers=[channel.e164],
                    auth_username=credentials.username if credentials else None,
                    auth_password=credentials.password if credentials else None,
                    require_media_encryption=True,
                    metadata=json.dumps({"whatsapp_channel_id": channel.id}),
                )
            )
            created.append(("trunk", trunk_id))
        if needs_rule and rule_id is None:
            rule_id = await sip.create_dispatch_rule(
                dispatch_spec(trunk_id, "whatsapp", channel.id, deps.settings.worker_agent_name)
            )
            created.append(("rule", rule_id))
    except GraphError as exc:
        error = ("Access token expired or rejected: " if exc.kind == "rejected" else "") + exc.message
    except SipError as exc:
        error = str(exc)
    if error is not None:
        for kind, object_id in reversed(created):
            try:
                if kind == "rule":
                    await sip.delete_dispatch_rule(object_id)
                else:
                    await sip.delete_trunk(object_id)
            except SipError:
                logger.warning("compensation could not delete %s %s", kind, object_id)
        created_ids = {object_id for _, object_id in created}
        trunk_id = None if trunk_id in created_ids else trunk_id
        rule_id = None if rule_id in created_ids else rule_id
    now = datetime.now(UTC)
    async with deps.db.transaction(workspace_id=workspace_id) as s:
        channel = await _load(s, channel_id, lock=True)
        channel.lk_inbound_trunk_id, channel.lk_dispatch_rule_id = trunk_id, rule_id
        if calling_enabled:
            channel.calling_enabled_at = channel.calling_enabled_at or now
        if credentials is not None:
            name = SECRET.format(id=channel.id, name="sip_credentials")
            await put_secret(
                s,
                deps.wrapper,
                workspace_id,
                name,
                json.dumps({"username": credentials.username, "password": credentials.password}),
            )
            channel.sip_credentials_secret = name
        if error is not None:
            channel.status, channel.status_detail = "error", error[:500]
        else:
            channel.status = "active" if channel.webhook_verified_at else "setup_incomplete"
            channel.status_detail = None
        channel.updated_at = now
        await s.flush()
        return await _out(s, channel)


async def list_channels(deps: ChannelDeps, workspace_id: str, *, page: int, page_size: int) -> dict[str, Any]:
    async with deps.db.transaction(workspace_id=workspace_id) as s:
        query = select(WhatsAppChannel).where(WhatsAppChannel.deleted_at.is_(None))
        total = int((await s.execute(select(func.count()).select_from(query.subquery()))).scalar_one())
        rows = list(
            (
                await s.execute(
                    query.order_by(WhatsAppChannel.created_at.desc(), WhatsAppChannel.id.desc()).slice(
                        *page_window(page, page_size)
                    )
                )
            ).scalars()
        )
        ids = [c.id for c in rows]
        active = await active_counts(s, Call.whatsapp_channel_id, ids)
        routes = await _route_counts(s, ids)
    return {
        "items": [to_out(c, active.get(c.id, 0), routes.get(c.id, 0)) for c in rows],
        **page_meta(total, page, page_size),
    }


async def get_channel(deps: ChannelDeps, workspace_id: str, channel_id: str) -> dict[str, Any]:
    async with deps.db.transaction(workspace_id=workspace_id) as s:
        return await _out(s, await _load(s, channel_id))


async def retry_setup(deps: WhatsAppDeps, workspace_id: str, channel_id: str) -> dict[str, Any]:
    async with deps.db.transaction(workspace_id=workspace_id) as s:
        channel = await _load(s, channel_id)
        if channel.status == "draining":
            raise conflict("channel_draining", "This channel is being deleted.")
        token = await _secret(deps, s, channel, channel.access_token_secret) or ""
        version, meta_id, e164 = channel.graph_api_version, channel.meta_phone_number_id, channel.e164
    try:
        await _check_credentials(deps, token, version, meta_id, e164)
    except ProblemError as problem:
        async with deps.db.transaction(workspace_id=workspace_id) as s:
            channel = await _load(s, channel_id, lock=True)
            channel.status = "error"
            channel.status_detail = (problem.detail or problem.title)[:500]
            channel.updated_at = datetime.now(UTC)
            await s.flush()
            return await _out(s, channel)
    async with deps.db.transaction(workspace_id=workspace_id) as s:
        channel = await _load(s, channel_id, lock=True)
        channel.credentials_verified_at = datetime.now(UTC)
    return await _setup_and_store(deps, workspace_id, channel_id)


async def sync_rule(deps: ChannelDeps, session: AsyncSession, channel: WhatsAppChannel) -> None:
    """Keep the dispatch rule present exactly when a default agent or a caller route exists."""
    if channel.lk_inbound_trunk_id is None or channel.status not in ROUTABLE:
        return
    wanted = channel.inbound_agent_id is not None or await _has_routes(session, channel.id)
    try:
        if wanted and channel.lk_dispatch_rule_id is None:
            channel.lk_dispatch_rule_id = await deps.sip.create_dispatch_rule(
                dispatch_spec(
                    channel.lk_inbound_trunk_id, "whatsapp", channel.id, deps.settings.worker_agent_name
                )
            )
        elif not wanted and channel.lk_dispatch_rule_id is not None:
            await deps.sip.delete_dispatch_rule(channel.lk_dispatch_rule_id)
            channel.lk_dispatch_rule_id = None
    except SipError as exc:
        raise ProblemError(
            502, "routing_update_failed", "Routing update failed", f"Nothing was changed. {exc}"
        ) from None


async def update_channel(
    deps: WhatsAppDeps, principal: Principal, channel_id: str, body: WhatsAppChannelUpdate
) -> dict[str, Any]:
    fields = set(body.model_fields_set)
    if not fields:
        raise validation_failed([field_error("/", "required", "Change at least one field.")])
    for name in ("label", "verify_token", "app_secret", "graph_api_version"):
        if name in fields and getattr(body, name) is None:
            raise validation_failed([field_error(f"/{name}", "required", "This field cannot be null.")])
    if "inbound_webhook_url" in fields:
        await check_webhook_url(deps.settings, body.inbound_webhook_url)
    ws = principal.workspace_id
    new_token = (body.access_token or "").strip() or None
    digest = verify_token_hash(body.verify_token) if body.verify_token else None
    async with deps.db.transaction(workspace_id=ws, user_id=principal.user_id) as s:
        channel = await _load(s, channel_id)
        if channel.status == "draining":
            raise conflict("channel_draining", "This channel is being deleted; it can no longer be changed.")
        if body.inbound_agent_id is not None:
            await require_published(s, {"inbound_agent_id": body.inbound_agent_id})
        await _refuse_taken(s, "", digest, own_id=channel.id)
        version = body.graph_api_version or channel.graph_api_version
        meta_id, e164 = channel.meta_phone_number_id, channel.e164
    if new_token or "graph_api_version" in fields:
        async with deps.db.transaction(workspace_id=ws) as s:
            token = (
                new_token
                or await _secret(deps, s, await _load(s, channel_id), channel.access_token_secret)
                or ""
            )
        await _check_credentials(deps, token, version, meta_id, e164)
    async with deps.db.transaction(workspace_id=ws, user_id=principal.user_id) as s:
        channel = await _load(s, channel_id, lock=True)
        now = datetime.now(UTC)
        if body.label is not None:
            channel.label = body.label.strip()
        if body.graph_api_version is not None:
            channel.graph_api_version = body.graph_api_version
        if new_token:
            await put_secret(s, deps.wrapper, ws, channel.access_token_secret, new_token)
            channel.access_token_last4 = _last4(new_token)
            channel.credentials_verified_at = now
        if body.verify_token and digest != channel.verify_token_hash:
            await put_secret(s, deps.wrapper, ws, channel.verify_token_secret, body.verify_token)
            channel.verify_token_last4 = _last4(body.verify_token)
            channel.verify_token_hash = digest or channel.verify_token_hash
            # WhatsApp must verify the callback again with the new token.
            channel.webhook_verified_at = None
            if channel.status == "active":
                channel.status = "setup_incomplete"
        if body.app_secret:
            await put_secret(s, deps.wrapper, ws, channel.app_secret_secret, body.app_secret)
        if "inbound_webhook_url" in fields:
            channel.inbound_webhook_url = body.inbound_webhook_url
        if "inbound_agent_id" in fields:
            channel.inbound_agent_id = body.inbound_agent_id
            await sync_rule(deps, s, channel)
        channel.updated_at = now
        try:
            await s.flush()
        except IntegrityError:
            raise conflict("verify_token_in_use", "Another channel uses this verify token.") from None
        return await _out(s, channel)


async def delete_channel(
    deps: WhatsAppDeps, workspace_id: str, channel_id: str, *, when_idle: bool
) -> tuple[int, dict[str, Any] | None]:
    async with deps.db.transaction(workspace_id=workspace_id) as s:
        channel = await _load(s, channel_id, lock=True)
        active = (await active_counts(s, Call.whatsapp_channel_id, [channel.id])).get(channel.id, 0)
        if channel.status == "draining":
            return 202, await _out(s, channel)
        if active and not when_idle:
            raise ProblemError(
                409,
                "channel_has_active_calls",
                "Channel has active calls",
                f"{active} call(s) are using this channel. Delete when idle to remove it after they end.",
                extra={"active_call_count": active},
            )

        async def calling_off() -> None:
            token = await _secret(deps, s, channel, channel.access_token_secret) or ""
            await _disable_calling(deps, channel, token)

        if not await delete_or_drain(
            deps.sip, s, channel, active=active, finish=finish_delete, after_rule=calling_off
        ):
            return 202, await _out(s, channel)
    return 204, None


async def _disable_calling(deps: WhatsAppDeps, channel: WhatsAppChannel, token: str) -> None:
    """Best effort (FR-030): a failure is logged, never blocks the delete."""
    try:
        await _graph(deps).disable_calling(token, channel.graph_api_version, channel.meta_phone_number_id)
    except GraphError as exc:
        logger.warning("could not turn off WhatsApp calling for %s: %s", channel.id, exc.kind)


async def finish_delete(session: AsyncSession, channel: WhatsAppChannel) -> None:
    now = datetime.now(UTC)
    for name in (
        channel.access_token_secret,
        channel.verify_token_secret,
        channel.app_secret_secret,
        channel.sip_credentials_secret,
    ):
        if name:
            await delete_secret(session, channel.workspace_id, name)
    channel.sip_credentials_secret = None
    channel.status = "deleted"
    channel.deleted_at = now
    channel.updated_at = now
    channel.lk_dispatch_rule_id = channel.lk_inbound_trunk_id = None
    await session.flush()


async def verify_challenge(
    deps: ChannelDeps, mode: str | None, token: str | None, challenge: str | None
) -> str | None:
    """The challenge to echo, or None (403) when no channel has this verify token."""
    if mode != "subscribe" or not token or challenge is None:
        return None
    async with deps.db.transaction() as s:
        row = (
            await s.execute(
                text("select channel_id, workspace_id from lookup_whatsapp_channel_by_verify_hash(:h)"),
                {"h": verify_token_hash(token)},
            )
        ).first()
    if row is None:
        return None
    async with deps.db.transaction(workspace_id=row.workspace_id) as s:
        channel = await _load(s, row.channel_id, lock=True)
        stored = await _secret(deps, s, channel, channel.verify_token_secret) or ""
        import hmac

        if not hmac.compare_digest(stored.encode(), token.encode()):
            return None
        now = datetime.now(UTC)
        channel.webhook_verified_at = now
        if channel.status == "setup_incomplete":
            channel.status = "active"
        channel.updated_at = now
    return challenge


def _meta_ids(payload: Any) -> list[str]:
    ids: list[str] = []
    if not isinstance(payload, dict):
        return ids
    for entry in payload.get("entry") or []:
        for change in (entry or {}).get("changes") or [] if isinstance(entry, dict) else []:
            value = change.get("value") if isinstance(change, dict) else None
            meta = value.get("metadata") if isinstance(value, dict) else None
            meta_id = meta.get("phone_number_id") if isinstance(meta, dict) else None
            if isinstance(meta_id, str) and meta_id not in ids:
                ids.append(meta_id)
    return ids


async def receive_notification(deps: ChannelDeps, body: bytes, signature: str | None) -> int:
    """200 for accepted or unknown numbers, 401 when the signature does not match."""
    try:
        payload = json.loads(body)
    except ValueError:
        return 200
    for meta_id in _meta_ids(payload):
        async with deps.db.transaction() as s:
            row = (
                await s.execute(
                    text("select channel_id, workspace_id from lookup_whatsapp_channel_by_meta_id(:m)"),
                    {"m": meta_id},
                )
            ).first()
        if row is None:
            continue
        async with deps.db.transaction(workspace_id=row.workspace_id) as s:
            channel = await _load(s, row.channel_id, lock=True)
            secret = await _secret(deps, s, channel, channel.app_secret_secret) or ""
            if not verify_signature(secret, body, signature):
                return 401
            channel.last_webhook_at = datetime.now(UTC)
        logger.info("WhatsApp notification for %s", row.channel_id)
    return 200


def route_out(route: WhatsAppCallerRoute, published: bool) -> dict[str, Any]:
    return {
        "id": route.id,
        "channel_id": route.channel_id,
        "caller_number": route.caller_e164,
        "agent_id": route.agent_id,
        "agent_published": published,
        "created_at": iso(route.created_at),
    }


async def list_routes(
    deps: ChannelDeps, workspace_id: str, channel_id: str, *, page: int, page_size: int, caller: str | None
) -> dict[str, Any]:
    async with deps.db.transaction(workspace_id=workspace_id) as s:
        await _load(s, channel_id)
        query = select(WhatsAppCallerRoute).where(WhatsAppCallerRoute.channel_id == channel_id)
        digits = validation.digits(caller)
        if digits and (caller or "").strip().startswith("+"):
            query = query.where(WhatsAppCallerRoute.caller_e164.startswith("+" + digits, autoescape=True))
        elif digits:
            query = query.where(WhatsAppCallerRoute.caller_e164.contains(digits, autoescape=True))
        total = int((await s.execute(select(func.count()).select_from(query.subquery()))).scalar_one())
        rows = list(
            (
                await s.execute(
                    query.order_by(
                        WhatsAppCallerRoute.created_at.desc(), WhatsAppCallerRoute.id.desc()
                    ).slice(*page_window(page, page_size))
                )
            ).scalars()
        )
        states = {a: await agent_state(s, a) for a in {r.agent_id for r in rows}}
    return {
        "items": [route_out(r, states.get(r.agent_id) == "published") for r in rows],
        **page_meta(total, page, page_size),
    }


async def create_route(
    deps: ChannelDeps, workspace_id: str, channel_id: str, body: CallerRouteCreate
) -> dict[str, Any]:
    try:
        caller = validation.normalize_whatsapp_caller(body.caller_number)
    except validation.InvalidValue as exc:
        raise validation_failed([field_error("/caller_number", "invalid_format", str(exc))]) from None
    async with deps.db.transaction(workspace_id=workspace_id) as s:
        channel = await _load(s, channel_id, lock=True)
        if channel.status == "draining":
            raise conflict("channel_draining", "This channel is being deleted.")
        await require_published(s, {"agent_id": body.agent_id})
        count = int(
            (
                await s.execute(
                    select(func.count())
                    .select_from(WhatsAppCallerRoute)
                    .where(WhatsAppCallerRoute.channel_id == channel_id)
                )
            ).scalar_one()
        )
        if count >= MAX_ROUTES:
            raise conflict("route_limit_reached", "A channel holds at most 1,000 caller routes.")
        exists = (
            await s.execute(
                select(WhatsAppCallerRoute.id).where(
                    WhatsAppCallerRoute.channel_id == channel_id, WhatsAppCallerRoute.caller_e164 == caller
                )
            )
        ).scalar_one_or_none()
        if exists:
            raise conflict("duplicate_caller_route", f"{caller} already has a route on this channel.")
        now = datetime.now(UTC)
        route = WhatsAppCallerRoute(
            id=new_id("wcr"),
            workspace_id=workspace_id,
            channel_id=channel_id,
            caller_e164=caller,
            agent_id=body.agent_id,
            created_at=now,
            updated_at=now,
        )
        s.add(route)
        await s.flush()
        await sync_rule(deps, s, channel)
        return route_out(route, True)


async def _load_route(session: AsyncSession, channel_id: str, route_id: str) -> WhatsAppCallerRoute:
    route = (
        await session.execute(
            select(WhatsAppCallerRoute).where(
                WhatsAppCallerRoute.id == route_id, WhatsAppCallerRoute.channel_id == channel_id
            )
        )
    ).scalar_one_or_none()
    if route is None:
        raise not_found("caller route")
    return route


async def update_route(
    deps: ChannelDeps, workspace_id: str, channel_id: str, route_id: str, agent_id: str
) -> dict[str, Any]:
    async with deps.db.transaction(workspace_id=workspace_id) as s:
        await _load(s, channel_id)
        route = await _load_route(s, channel_id, route_id)
        await require_published(s, {"agent_id": agent_id})
        route.agent_id = agent_id
        route.updated_at = datetime.now(UTC)
        await s.flush()
        return route_out(route, True)


async def delete_route(deps: ChannelDeps, workspace_id: str, channel_id: str, route_id: str) -> None:
    async with deps.db.transaction(workspace_id=workspace_id) as s:
        channel = await _load(s, channel_id, lock=True)
        route = await _load_route(s, channel_id, route_id)
        await s.delete(route)
        await s.flush()
        await sync_rule(deps, s, channel)


async def attachments_for_agent(ctx: agent_hooks.UsageContext) -> list[agent_hooks.Attachment]:
    out: list[agent_hooks.Attachment] = []
    channels = (
        await ctx.session.execute(
            select(WhatsAppChannel).where(
                WhatsAppChannel.deleted_at.is_(None), WhatsAppChannel.inbound_agent_id == ctx.agent_id
            )
        )
    ).scalars()
    for channel in channels:
        out.append(
            agent_hooks.Attachment(
                "whatsapp_channel", channel.id, f"{channel.label} (WhatsApp default agent)"
            )
        )
    routes = (
        await ctx.session.execute(
            select(WhatsAppCallerRoute.channel_id, func.count())
            .where(WhatsAppCallerRoute.agent_id == ctx.agent_id)
            .group_by(WhatsAppCallerRoute.channel_id)
        )
    ).all()
    for channel_id, count in routes:
        out.append(
            agent_hooks.Attachment(
                "whatsapp_caller_route", str(channel_id), f"{count} WhatsApp caller route(s)"
            )
        )
    return out
