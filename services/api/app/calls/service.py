"""Call admission, claim, runtime configuration and recording state (003 T018, T029, T032,
T051, T066, T113, T114; research R2, R3, R13, R18).

``admit()`` is the one admission path for every channel (FR-009). Checks run in the order of
FR-007: agent version resolvable (draft, published or an explicit version), account email
verified, every vendor supported by the worker, every component priced, balance above zero,
then the concurrency slot under a per-workspace advisory transaction lock, so two requests can
never both take the last slot. A refused request still writes a ``failed`` call with its reason
(FR-008) in the same transaction.

``claim()`` serves ``POST /v1/internal/calls/claim``: API-created calls are marked claimed by the
job; SIP and WhatsApp calls are routed by 010's inbound router and admitted here. The workspace
always comes from the call row (security-definer lookup), never from the request body (R19).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing import service as billing
from app.calls import components as comp
from app.calls import variables as variables_mod
from app.calls.catalog import AdapterCatalog
from app.calls.effects import START_RECORDING, Deferred
from app.calls.models import ACTIVE, Call
from app.calls.ports import AgentSnapshot, ObjectSigner, registry
from app.core.config import get_settings
from app.core.db import Database
from app.core.errors import ProblemError, not_found
from app.core.ids import is_valid_id, new_id
from app.pricing import service as pricing
from app.webhooks_out import service as webhooks
from app.workspaces.models import Workspace

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL_S = 10
CALLER_JOIN_TIMEOUT_S = 60
SIGNED_URL_TTL_S = 600
LIVE_CHANNELS = frozenset({"sip_inbound", "sip_outbound", "whatsapp"})
SIP_CHANNELS = frozenset({"sip_inbound", "whatsapp"})

# Refusal codes: problem status, problem code, disconnect reason (FR-008, contract sessions.yaml).
REFUSALS: dict[str, tuple[int, str]] = {
    "email_unverified": (403, "error"),
    "agent_not_published": (409, "error"),
    "flow_runtime_unavailable": (422, "error"),
    "flow_not_compiled": (409, "error"),
    "unsupported_vendor": (422, "error"),
    "pricing_unavailable": (422, "error"),
    "insufficient_credit": (402, "insufficient_credit"),
    "concurrency_limit": (429, "concurrency_limit"),
    "declined_by_webhook": (409, "error"),
}
_DETAILS = {
    "email_unverified": "Verify your email address before placing calls.",
    "agent_not_published": "This agent has no published version.",
    "flow_runtime_unavailable": "Flow agents cannot run calls yet.",
    "flow_not_compiled": "This flow has no compiled graph. Fix the problems the flow builder lists.",
    "unsupported_vendor": "The agent uses a speech or language vendor the platform does not support.",
    "pricing_unavailable": "The agent's configuration is not fully priced.",
    "insufficient_credit": "Your balance is too low to start a call. Add funds to continue.",
    "concurrency_limit": "Concurrent call limit reached. Try again when a call ends.",
    "declined_by_webhook": "The inbound webhook declined this call.",
}


@dataclass(frozen=True)
class AdmissionRequest:
    workspace_id: str
    agent_id: str
    channel: str
    direction: str
    version: str = "published"
    origin: str = "live"
    variables: Mapping[str, str] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    from_number: str | None = None
    to_number: str | None = None
    phone_number_id: str | None = None
    whatsapp_channel_id: str | None = None
    sip_call_id: str | None = None
    initiated_by_user_id: str | None = None
    idempotency_key: str | None = None
    simulation_run_id: str | None = None
    room_name: str | None = None
    timezone: str | None = None
    # 010: outbound ring timeout, routing outcome and an inbound decline by the operator's webhook.
    ring_timeout_s: int | None = None
    route_detail: str | None = None
    declined: bool = False
    call_id: str | None = None


@dataclass(frozen=True)
class Refusal:
    code: str
    status: int
    disconnect_reason: str
    diagnostic: str
    detail: str

    def problem(self, call_id: str | None) -> ProblemError:
        extra: dict[str, Any] = {"disconnect_reason": self.disconnect_reason, "diagnostic": self.diagnostic}
        if call_id:
            extra["call_id"] = call_id
        title = self.code.replace("_", " ").capitalize()
        return ProblemError(self.status, self.code, title, self.detail, extra=extra)


def refusal(code: str, diagnostic: str | None = None) -> Refusal:
    status, reason = REFUSALS[code]
    return Refusal(code, status, reason, diagnostic or code, _DETAILS[code])


@dataclass
class Admission:
    call: Call
    admitted: bool
    refusal: Refusal | None = None
    snapshot: AgentSnapshot | None = None
    deferred: Deferred = field(default_factory=Deferred)
    created: bool = True


# Pure rules -------------------------------------------------------------------------------


def resolve_recording(override: Any, workspace_default: bool) -> tuple[bool, str]:
    """FR-043: ``on``/``off`` on the agent win; ``inherit`` (or missing) uses the workspace."""
    value = override if override in ("inherit", "on", "off") else "inherit"
    if value == "inherit":
        return bool(workspace_default), "workspace"
    return value == "on", "agent"


def recording_override(config: Mapping[str, Any]) -> Any:
    advanced = config.get("advanced")
    return advanced.get("recording") if isinstance(advanced, Mapping) else None


def _int(value: Any, default: int, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return min(high, max(low, number))


def limits(config: Mapping[str, Any]) -> dict[str, int]:
    """Call limits from the version, clamped to the contract ranges (defence in depth)."""
    behavior = config.get("call_behavior")
    cb: Mapping[str, Any] = behavior if isinstance(behavior, Mapping) else {}
    return {
        "end_on_silence_s": _int(cb.get("end_on_silence_s"), 30, 10, 300),
        "max_duration_s": _int(cb.get("max_duration_s"), 600, 30, 3600),
        "ring_duration_ms": _int(cb.get("ring_duration_ms"), 5000, 0, 30000),
    }


# Admission ---------------------------------------------------------------------------------


async def _resolve_version(
    session: AsyncSession, request: AdmissionRequest
) -> tuple[AgentSnapshot | None, Refusal | None]:
    port = registry.agent_versions
    if not await port.agent_exists(session, request.agent_id):
        raise not_found("agent")
    version = "published" if request.channel in LIVE_CHANNELS else request.version
    if version == "draft":
        snapshot = await port.snapshot_for_test(session, request.agent_id)
        if snapshot is None:
            raise not_found("agent")
        return snapshot, None
    if version == "published":
        snapshot = await port.get_published(session, request.agent_id)
        return (snapshot, None) if snapshot is not None else (None, refusal("agent_not_published"))
    snapshot = await port.get_snapshot(session, version) if is_valid_id(version, "agv") else None
    if snapshot is None or snapshot.agent_id != request.agent_id:
        raise not_found("agent version")
    return snapshot, None


async def _active_calls(session: AsyncSession, workspace_id: str) -> int:
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(Call)
                # 008: simulated calls run as text and never hold a concurrent-call slot.
                .where(
                    Call.workspace_id == workspace_id,
                    Call.status.in_(tuple(ACTIVE)),
                    Call.origin != "simulation",
                )
            )
        ).scalar_one()
    )


async def _email_verified(session: AsyncSession, workspace_id: str) -> bool:
    return bool(
        (
            await session.execute(text("select app_workspace_owner_verified(:ws)"), {"ws": workspace_id})
        ).scalar()
    )


def _replayed_refusal(call: Call) -> Refusal:
    diagnostic = call.diagnostic or "error"
    code = diagnostic.split(":", 1)[0]
    if code not in REFUSALS:
        code = "unsupported_vendor" if diagnostic.startswith("stt_language") else "pricing_unavailable"
    status, _ = REFUSALS[code]
    return Refusal(code, status, call.disconnect_reason or "error", diagnostic, _DETAILS[code])


def _has_compiled_flow(config: Mapping[str, Any]) -> bool:
    flow = config.get("flow")
    compiled = flow.get("compiled") if isinstance(flow, Mapping) else None
    return isinstance(compiled, Mapping) and compiled.get("schema_version") == 1


async def _checks(
    session: AsyncSession, request: AdmissionRequest, snapshot: AgentSnapshot, catalog: AdapterCatalog
) -> Refusal | None:
    if snapshot.agent_type == "flow" and not registry.flow_runtime_available:
        return refusal("flow_runtime_unavailable")
    if snapshot.agent_type == "flow" and not _has_compiled_flow(snapshot.config):
        # The worker would fail the call with the same code after the caller joined (004).
        return refusal("flow_not_compiled")
    components = comp.resolve(snapshot.config, catalog)
    diagnostic = comp.unsupported(components, catalog)
    if diagnostic is None and request.origin != "simulation":
        diagnostic = comp.unconfigured(components, get_settings())
    if diagnostic is not None:
        return refusal("unsupported_vendor", diagnostic)
    try:
        quote = await pricing.quote(session, components.pricing())
    except pricing.CatalogUnavailable:
        return refusal("pricing_unavailable", "pricing_unavailable:no_catalog")
    if not quote.complete:
        unpriced = ",".join(line.component for line in quote.lines if line.status == "unpriced")
        return refusal("pricing_unavailable", f"pricing_unavailable:{unpriced}")
    if request.origin != "simulation" and await billing.get_balance(session, request.workspace_id) <= 0:
        return refusal("insufficient_credit")
    return None


async def _lock_admissions(session: AsyncSession, workspace_id: str) -> None:
    await session.execute(
        text("select pg_advisory_xact_lock(hashtextextended('admission:' || :ws, 0))"), {"ws": workspace_id}
    )


async def admit_in_session(
    session: AsyncSession,
    request: AdmissionRequest,
    *,
    catalog: AdapterCatalog,
    now: datetime | None = None,
    recordings_enabled: bool | None = None,
) -> Admission:
    """Admission inside the caller's workspace-scoped transaction (see ``admit``).

    ``recordings_enabled`` is the deployment switch (``RECORDINGS_ENABLED``, read from the settings
    when None): when false every call is admitted with recording off."""
    now = now or datetime.now(UTC)
    if recordings_enabled is None:
        recordings_enabled = get_settings().recordings_enabled
    if request.idempotency_key:
        existing = (
            await session.execute(
                select(Call).where(
                    Call.workspace_id == request.workspace_id, Call.idempotency_key == request.idempotency_key
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            snapshot = (
                await registry.agent_versions.get_snapshot(session, existing.agent_version_id)
                if existing.agent_version_id
                else None
            )
            refused = None
            if existing.status == "failed" and existing.claimed_at is None:
                refused = _replayed_refusal(existing)
            return Admission(existing, refused is None, refused, snapshot, created=False)
    snapshot, refused = await _resolve_version(session, request)
    if not await _email_verified(session, request.workspace_id):
        refused = refusal("email_unverified")
    if refused is None and snapshot is not None:
        refused = await _checks(session, request, snapshot, catalog)
    if refused is None and request.declined:
        refused = refusal("declined_by_webhook")
    if refused is None:
        await _lock_admissions(session, request.workspace_id)
        limit = int(
            (
                await session.execute(
                    select(Workspace.concurrency_limit).where(Workspace.id == request.workspace_id)
                )
            ).scalar_one()
        )
        if await _active_calls(session, request.workspace_id) >= limit:
            refused = refusal("concurrency_limit")
    call_id = request.call_id or new_id("call")
    config: Mapping[str, Any] = snapshot.config if snapshot is not None else {}
    workspace_default = bool(
        (
            await session.execute(
                select(Workspace.recording_default).where(Workspace.id == request.workspace_id)
            )
        ).scalar_one()
    )
    recording_enabled, source = resolve_recording(recording_override(config), workspace_default)
    # No egress on this deployment: the source still names where the setting came from.
    recording_enabled = recording_enabled and recordings_enabled
    builtins = variables_mod.builtin_values(
        call_id=call_id,
        channel=request.channel,
        direction=request.direction,
        from_number=request.from_number,
        to_number=request.to_number,
        timezone=request.timezone,
        now=now,
    )
    resolved = variables_mod.resolve(config, request.variables, builtins)
    call = Call(
        id=call_id,
        workspace_id=request.workspace_id,
        agent_id=request.agent_id,
        agent_version_id=snapshot.version_id if snapshot is not None else None,
        origin=request.origin,
        simulation_run_id=request.simulation_run_id,
        channel=request.channel,
        direction=request.direction,
        from_number=request.from_number,
        to_number=request.to_number,
        phone_number_id=request.phone_number_id,
        whatsapp_channel_id=request.whatsapp_channel_id,
        is_test=request.origin == "test",
        initiated_by_user_id=request.initiated_by_user_id,
        room_name=request.room_name if refused is None else None,
        sip_call_id=request.sip_call_id,
        status="queued" if refused is None else "failed",
        disconnect_reason=refused.disconnect_reason if refused else None,
        diagnostic=refused.diagnostic if refused else None,
        dynamic_variables=resolved.values,
        missing_variables=resolved.missing,
        ignored_overrides=resolved.ignored,
        metadata_=dict(request.metadata),
        idempotency_key=request.idempotency_key,
        created_at=now,
        usage={},
        usage_seq=0,
        recording_enabled=recording_enabled,
        recording_setting_source=source,
        recording_status="none" if recording_enabled else "not_recorded",
        pipeline_status="not_started",
        pipeline_warnings=[],
        billable_seconds=0 if refused else None,
        ring_timeout_s=request.ring_timeout_s,
        route_detail=request.route_detail,
    )
    session.add(call)
    await session.flush()
    admission = Admission(call, refused is None, refused, snapshot)
    if refused is not None:
        # A refused call never connected: only ``call_ended`` is sent (FR-035).
        await webhooks.enqueue_event(session, call, "call_ended", config=config, deferred=admission.deferred)
        logger.info("call %s refused: %s", call_id, refused.diagnostic)
    return admission


async def admit(
    db: Database,
    request: AdmissionRequest,
    *,
    catalog: AdapterCatalog,
    now: datetime | None = None,
    recordings_enabled: bool | None = None,
) -> Admission:
    """Run admission in its own transaction (committed even when the call is refused)."""
    async with db.transaction(workspace_id=request.workspace_id, user_id=request.initiated_by_user_id) as s:
        return await admit_in_session(
            s, request, catalog=catalog, now=now, recordings_enabled=recordings_enabled
        )


async def mark_failed(
    db: Database, workspace_id: str, call_id: str, diagnostic: str, *, deferred: Deferred | None = None
) -> bool:
    """Fail a call that never connected (room could not be created, dial error, ...)."""
    from app.calls.models import transition

    async with db.transaction(workspace_id=workspace_id) as session:
        changed = await transition(
            session,
            call_id,
            ("queued", "ringing"),
            "failed",
            disconnect_reason="error",
            diagnostic=diagnostic[:500],
            billable_seconds=0,
        )
        if changed and deferred is not None:
            call = await session.get(Call, call_id)
            assert call is not None
            snapshot = await _snapshot(session, call)
            await webhooks.enqueue_event(
                session, call, "call_ended", config=snapshot.config if snapshot else None, deferred=deferred
            )
    return changed


async def _snapshot(session: AsyncSession, call: Call) -> AgentSnapshot | None:
    if call.agent_version_id is None:
        return None
    return await registry.agent_versions.get_snapshot(session, call.agent_version_id)


# Claim --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ClaimInput:
    job_id: str
    room_name: str
    worker_id: str
    dispatch_metadata: Mapping[str, Any]
    sip: Mapping[str, Any] | None = None


@dataclass
class ClaimOutcome:
    body: dict[str, Any]
    deferred: Deferred = field(default_factory=Deferred)


def runtime_config(
    call: Call,
    snapshot: AgentSnapshot,
    catalog: AdapterCatalog,
    *,
    signer: ObjectSigner | None = None,
    media_bucket: str | None = None,
    outbound_dial: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Contract ``RuntimeConfig`` for the worker (calls.yaml)."""
    config = dict(snapshot.config)
    components = comp.resolve(config, catalog)
    background_url = None
    advanced = config.get("advanced")
    background = advanced.get("background_audio") if isinstance(advanced, Mapping) else None
    if isinstance(background, Mapping) and background.get("enabled"):
        source = background.get("source")
        if isinstance(source, Mapping) and source.get("kind") == "upload" and source.get("key"):
            if signer is not None and media_bucket:
                background_url = signer.presign_get(media_bucket, str(source["key"]), SIGNED_URL_TTL_S)
    agent_type = snapshot.agent_type if snapshot.agent_type in ("single_prompt", "flow") else "single_prompt"
    return {
        "channel": call.channel,
        "direction": call.direction,
        "from_number": call.from_number,
        "to_number": call.to_number,
        "agent_id": call.agent_id,
        "agent_version_id": snapshot.version_id,
        "agent_type": agent_type,
        "config": config,
        "variables": {k: str(v) for k, v in (call.dynamic_variables or {}).items()},
        "limits": limits(config),
        "background_audio_url": background_url,
        "caller_join_timeout_s": CALLER_JOIN_TIMEOUT_S,
        "outbound_dial": dict(outbound_dial) if outbound_dial else None,
        "heartbeat_interval_s": HEARTBEAT_INTERVAL_S,
        "recording_enabled": call.recording_enabled,
        "stt_resolved_model": components.stt.model,
    }


def _refused_body(call_id: str, reason: str, diagnostic: str) -> dict[str, Any]:
    return {
        "admitted": False,
        "call_id": call_id,
        "refusal": {"disconnect_reason": reason, "diagnostic": diagnostic},
    }


async def _claim_existing(
    db: Database,
    workspace_id: str,
    call_id: str,
    request: ClaimInput,
    *,
    catalog: AdapterCatalog,
    media_bucket: str | None,
    now: datetime,
) -> ClaimOutcome:
    outcome = ClaimOutcome(body={})
    async with db.transaction(workspace_id=workspace_id) as session:
        call = (await session.execute(select(Call).where(Call.id == call_id).with_for_update())).scalar_one()
        same_job = call.worker_job_id == request.job_id
        if call.worker_job_id is not None and not same_job:
            raise ProblemError(
                409, "call_already_claimed", "Already claimed", "Another job claimed this call."
            )
        if call.status == "failed" and call.room_name is None and call.worker_job_id is None:
            # Refused at admission (inbound path): the worker hangs up without speaking.
            outcome.body = _refused_body(call.id, call.disconnect_reason or "error", call.diagnostic or "")
            return outcome
        if call.status not in ACTIVE and not same_job:
            raise ProblemError(409, "call_not_claimable", "Call is closed", "This call has already ended.")
        snapshot = await _snapshot(session, call)
        if snapshot is None:
            raise ProblemError(409, "call_not_claimable", "Call is closed", "The call has no agent version.")
        outbound: Mapping[str, Any] | None = None
        if call.channel == "sip_outbound":
            provider = registry.outbound_dial
            dial = await provider.dial_spec(session, call) if provider is not None else None
            if dial is None:
                from app.calls.models import transition

                await transition(
                    session,
                    call.id,
                    ("queued", "ringing"),
                    "failed",
                    disconnect_reason="error",
                    diagnostic="outbound_unavailable",
                    billable_seconds=0,
                )
                outcome.body = _refused_body(call.id, "error", "outbound_unavailable")
                return outcome
            outbound = {
                "sip_trunk_id": dial.sip_trunk_id,
                "to_number": dial.to_number,
                "from_number": dial.from_number,
                "ring_timeout_s": dial.ring_timeout_s,
            }
        if not same_job:
            call.worker_job_id = request.job_id
            call.claimed_at = now
            if call.room_name is None:
                call.room_name = request.room_name
            await session.flush()
            if call.recording_enabled and call.recording_status == "none":
                outcome.deferred.add(START_RECORDING, workspace_id, call.id)
        runtime = runtime_config(
            call, snapshot, catalog, signer=registry.signer, media_bucket=media_bucket, outbound_dial=outbound
        )
    outcome.body = {"admitted": True, "call_id": call_id, "runtime": runtime}
    return outcome


async def claim(
    db: Database,
    request: ClaimInput,
    *,
    catalog: AdapterCatalog,
    media_bucket: str | None = None,
    now: datetime | None = None,
) -> ClaimOutcome:
    now = now or datetime.now(UTC)
    metadata = request.dispatch_metadata
    call_id = metadata.get("call_id")
    if isinstance(call_id, str):
        if not is_valid_id(call_id, "call"):
            raise not_found("call")
        async with db.transaction() as session:
            workspace_id = (
                await session.execute(text("select calls_workspace_for(:id)"), {"id": call_id})
            ).scalar()
        if workspace_id is None:
            raise not_found("call")
        return await _claim_existing(
            db, str(workspace_id), call_id, request, catalog=catalog, media_bucket=media_bucket, now=now
        )
    channel = metadata.get("channel")
    if channel not in SIP_CHANNELS:
        raise ProblemError(
            422, "invalid_dispatch", "Invalid dispatch", "Dispatch metadata needs call_id or a SIP channel."
        )
    router = registry.inbound_routers.get(str(channel))
    sip = dict(request.sip or {})
    route = await router.resolve(str(channel), sip, metadata.get("route_ref")) if router else None
    if route is None:
        # No router (010 not installed) or no agent for the number: nothing to bill or record.
        diagnostic = "no_inbound_router" if router is None else "no_agent_for_caller"
        return ClaimOutcome(body=_refused_body(new_id("call"), "error", diagnostic))
    admission = await admit(
        db,
        AdmissionRequest(
            workspace_id=route.workspace_id,
            agent_id=route.agent_id,
            channel=str(channel),
            direction="inbound",
            version="published",
            variables=dict(route.variables),
            from_number=route.from_number or sip.get("caller_number"),
            to_number=route.to_number or sip.get("trunk_phone_number"),
            phone_number_id=route.phone_number_id,
            whatsapp_channel_id=route.whatsapp_channel_id,
            sip_call_id=sip.get("call_id"),
            idempotency_key=f"job:{request.job_id}",
            room_name=request.room_name,
            metadata=dict(route.metadata),
            route_detail=route.route_detail,
            declined=route.declined,
            call_id=route.call_id,
        ),
        catalog=catalog,
        now=now,
    )
    if not admission.admitted:
        assert admission.refusal is not None
        outcome = ClaimOutcome(
            body=_refused_body(
                admission.call.id, admission.refusal.disconnect_reason, admission.refusal.diagnostic
            )
        )
        outcome.deferred.extend(admission.deferred)
        return outcome
    outcome = await _claim_existing(
        db,
        route.workspace_id,
        admission.call.id,
        request,
        catalog=catalog,
        media_bucket=media_bucket,
        now=now,
    )
    outcome.deferred.extend(admission.deferred)
    return outcome


# Recording state (for 006) -----------------------------------------------------------------


def recording_state(
    call: Call,
    *,
    signer: ObjectSigner | None = None,
    bucket: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Contract ``CallRecordingState``: ``not_recorded`` (never a URL) is distinct from ``failed``."""
    url = None
    expires = None
    if (
        call.recording_enabled
        and call.recording_status == "available"
        and call.recording_key
        and signer is not None
        and bucket
    ):
        url = signer.presign_get(bucket, call.recording_key, SIGNED_URL_TTL_S)
        from datetime import timedelta

        expires = ((now or datetime.now(UTC)) + timedelta(seconds=SIGNED_URL_TTL_S)).isoformat()
    return {
        "call_id": call.id,
        "recording_enabled": call.recording_enabled,
        "recording_setting_source": call.recording_setting_source,
        "recording_status": call.recording_status,
        "recording_url": url,
        "expires_at": expires,
    }


async def config_for(session: AsyncSession, call: Call) -> Mapping[str, Any] | None:
    snapshot = await _snapshot(session, call)
    return snapshot.config if snapshot is not None else None


async def set_analysis(
    session: AsyncSession,
    call_id: str,
    *,
    summary: str | None,
    sentiment: str | None,
    values: Mapping[str, Any] | None,
) -> None:
    """Write post-call analysis onto the call (007 research R11): the owner module performs the
    write; 007 keeps its own metadata (model, variable snapshot, cost) in ``call_analyses``."""
    call = await session.get(Call, call_id)
    if call is None:
        raise not_found("call")
    call.summary = summary
    call.sentiment = sentiment
    call.analysis = dict(values) if values is not None else None
    await session.flush()
