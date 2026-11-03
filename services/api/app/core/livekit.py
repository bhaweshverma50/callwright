"""LiveKit server access for the API (003 T012, research R1, R13, R17, R19).

The API is the only component that creates rooms, dispatches the voice worker, mints browser
join tokens and starts recordings; the worker never holds storage credentials.

* ``LiveKitClient`` (``LIVEKIT_MODE=live``) talks to the server with ``livekit-api``.
* ``FakeLiveKit`` (``LIVEKIT_MODE=fake``) records every call in memory; tests and offline
  development use it. Tokens and webhook signatures are real JWTs in both modes, so the same
  verification code runs everywhere.

Recordings are audio-only room-composite egress with ``DUAL_CHANNEL_AGENT`` mixing (agent on the
left channel, everyone else on the right) into an MP4 (AAC) object. Server-side encryption
(SSE-KMS) is enforced by the bucket's default encryption; the egress request carries no key.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Protocol

from livekit import api as lk

from app.core.config import Settings

logger = logging.getLogger(__name__)

JOIN_TOKEN_TTL_S = 15 * 60


class LiveKitError(Exception):
    """The media server refused or failed a request."""


class WebhookAuthError(Exception):
    """A LiveKit webhook's Authorization JWT or body hash does not verify."""


def http_url(url: str) -> str:
    """``ws://``/``wss://`` server URLs as the ``http://``/``https://`` form the API client uses."""
    if url.startswith("ws://"):
        return "http://" + url[len("ws://") :]
    if url.startswith("wss://"):
        return "https://" + url[len("wss://") :]
    return url


def mint_join_token(
    api_key: str,
    api_secret: str,
    *,
    room: str,
    identity: str,
    name: str | None = None,
    ttl_s: int = JOIN_TOKEN_TTL_S,
    metadata: str | None = None,
) -> str:
    """A browser credential for one room: join, publish the microphone and data, subscribe."""
    grants = lk.VideoGrants(
        room_join=True,
        room=room,
        can_publish=True,
        can_publish_sources=["microphone"],
        can_publish_data=True,
        can_subscribe=True,
        can_update_own_metadata=False,
    )
    token = (
        lk.AccessToken(api_key, api_secret)
        .with_identity(identity)
        .with_grants(grants)
        .with_ttl(timedelta(seconds=ttl_s))
    )
    if name:
        token = token.with_name(name)
    if metadata:
        token = token.with_metadata(metadata)
    return token.to_jwt()


def sign_webhook(api_key: str, api_secret: str, body: str) -> str:
    """The Authorization value LiveKit sends with a webhook (tests and fake mode)."""
    digest = base64.b64encode(hashlib.sha256(body.encode()).digest()).decode()
    return lk.AccessToken(api_key, api_secret).with_sha256(digest).to_jwt()


def verify_webhook(api_key: str, api_secret: str, body: str, authorization: str | None) -> dict[str, Any]:
    """Check the JWT signature and its ``sha256`` body claim; return the parsed JSON body."""
    if not authorization:
        raise WebhookAuthError("missing Authorization header")
    token = authorization.split(" ", 1)[1] if authorization.lower().startswith("bearer ") else authorization
    receiver = lk.WebhookReceiver(lk.TokenVerifier(api_key, api_secret))
    try:
        receiver.receive(body, token)
        parsed = json.loads(body)
    except Exception as exc:
        raise WebhookAuthError(str(exc)) from exc
    if not isinstance(parsed, dict):
        raise WebhookAuthError("body is not an object")
    return parsed


@dataclass(frozen=True)
class EgressTarget:
    """Where a recording goes: ``s3://{bucket}/{key}`` (credentials from settings)."""

    bucket: str
    key: str


class LiveKitGateway(Protocol):
    api_key: str

    def join_token(self, *, room: str, identity: str, name: str | None = None, ttl_s: int = ...) -> str: ...

    def verify_webhook(self, body: str, authorization: str | None) -> dict[str, Any]: ...

    async def create_room(self, name: str, *, metadata: str = "", empty_timeout_s: int = 300) -> None: ...

    async def delete_room(self, name: str) -> None: ...

    async def dispatch_agent(self, room: str, agent_name: str, metadata: dict[str, Any]) -> str: ...

    async def start_audio_recording(self, room: str, target: EgressTarget) -> str: ...

    async def egress_info(self, egress_id: str) -> dict[str, Any] | None: ...

    async def aclose(self) -> None: ...


class _TokenMixin:
    api_key: str
    _secret: str

    def join_token(
        self, *, room: str, identity: str, name: str | None = None, ttl_s: int = JOIN_TOKEN_TTL_S
    ) -> str:
        return mint_join_token(
            self.api_key, self._secret, room=room, identity=identity, name=name, ttl_s=ttl_s
        )

    def verify_webhook(self, body: str, authorization: str | None) -> dict[str, Any]:
        return verify_webhook(self.api_key, self._secret, body, authorization)

    def sign_webhook(self, body: str) -> str:
        return sign_webhook(self.api_key, self._secret, body)


class LiveKitClient(_TokenMixin):
    def __init__(self, settings: Settings) -> None:
        self.api_key = settings.livekit_api_key.get_secret_value()
        self._secret = settings.livekit_api_secret.get_secret_value()
        self._url = http_url(settings.livekit_url)
        self._settings = settings
        self._api: lk.LiveKitAPI | None = None

    def _client(self) -> lk.LiveKitAPI:
        # aiohttp needs a running loop, so the client is created on first use.
        if self._api is None:
            self._api = lk.LiveKitAPI(self._url, self.api_key, self._secret)
        return self._api

    async def create_room(self, name: str, *, metadata: str = "", empty_timeout_s: int = 300) -> None:
        try:
            await self._client().room.create_room(
                lk.CreateRoomRequest(
                    name=name, empty_timeout=empty_timeout_s, departure_timeout=20, metadata=metadata
                )
            )
        except Exception as exc:
            raise LiveKitError(f"create_room {name}: {exc}") from exc

    async def delete_room(self, name: str) -> None:
        try:
            await self._client().room.delete_room(lk.DeleteRoomRequest(room=name))
        except lk.TwirpError as exc:
            if exc.code == lk.TwirpErrorCode.NOT_FOUND:
                return
            raise LiveKitError(f"delete_room {name}: {exc}") from exc
        except Exception as exc:
            raise LiveKitError(f"delete_room {name}: {exc}") from exc

    async def dispatch_agent(self, room: str, agent_name: str, metadata: dict[str, Any]) -> str:
        try:
            dispatch = await self._client().agent_dispatch.create_dispatch(
                lk.CreateAgentDispatchRequest(agent_name=agent_name, room=room, metadata=json.dumps(metadata))
            )
        except Exception as exc:
            raise LiveKitError(f"dispatch {agent_name} to {room}: {exc}") from exc
        return str(dispatch.id)

    async def start_audio_recording(self, room: str, target: EgressTarget) -> str:
        s = self._settings
        if s.recordings_gcp_credentials:
            output = lk.EncodedFileOutput(
                file_type=lk.EncodedFileType.MP4,
                filepath=target.key,
                gcp=lk.GCPUpload(
                    credentials=s.recordings_gcp_credentials.get_secret_value(), bucket=target.bucket
                ),
            )
        else:
            # The general object store's key and endpoint stand in when no recordings-only ones are set.
            access = s.recordings_s3_access_key or s.s3_access_key_id
            secret = s.recordings_s3_secret_key or s.s3_secret_access_key
            endpoint = s.recordings_s3_endpoint or s.s3_endpoint_url
            s3 = lk.S3Upload(
                access_key=access.get_secret_value() if access else "",
                secret=secret.get_secret_value() if secret else "",
                region=s.recordings_s3_region,
                endpoint=endpoint or "",
                bucket=target.bucket,
                force_path_style=bool(endpoint),
            )
            output = lk.EncodedFileOutput(file_type=lk.EncodedFileType.MP4, filepath=target.key, s3=s3)
        request = lk.RoomCompositeEgressRequest(
            room_name=room,
            audio_only=True,
            audio_mixing=lk.AudioMixing.DUAL_CHANNEL_AGENT,
            advanced=lk.EncodingOptions(audio_codec=lk.AudioCodec.AAC),
            file_outputs=[output],
        )
        timeout = s.recordings_egress_timeout_s
        try:
            info = await asyncio.wait_for(self._client().egress.start_room_composite_egress(request), timeout)
        except TimeoutError as exc:
            raise LiveKitError(
                f"start egress for {room}: no egress service answered within {timeout:g} s"
            ) from exc
        except Exception as exc:
            raise LiveKitError(f"start egress for {room}: {exc}") from exc
        return str(info.egress_id)

    async def egress_info(self, egress_id: str) -> dict[str, Any] | None:
        """The egress as a webhook ``egressInfo`` body, or None when LiveKit no longer knows it."""
        try:
            res = await asyncio.wait_for(
                self._client().egress.list_egress(lk.ListEgressRequest(egress_id=egress_id)), 10
            )
        except Exception as exc:
            raise LiveKitError(f"list egress {egress_id}: {exc}") from exc
        if not res.items:
            return None
        info = res.items[0]
        return {
            "egressId": info.egress_id,
            "status": lk.EgressStatus.Name(info.status),
            "error": info.error,
            "fileResults": [{"filename": f.filename} for f in info.file_results],
        }

    async def aclose(self) -> None:
        if self._api is not None:
            await self._api.aclose()
            self._api = None


@dataclass
class FakeLiveKit(_TokenMixin):
    """In-memory media server for tests and offline development."""

    api_key: str = "devkey"
    _secret: str = "secret"  # noqa: S105
    rooms: dict[str, str] = field(default_factory=dict)
    deleted: list[str] = field(default_factory=list)
    dispatches: list[tuple[str, str, dict[str, Any]]] = field(default_factory=list)
    egresses: list[tuple[str, EgressTarget]] = field(default_factory=list)
    egress_infos: dict[str, dict[str, Any]] = field(default_factory=dict)
    fail_next: set[str] = field(default_factory=set)

    def _maybe_fail(self, op: str) -> None:
        if op in self.fail_next:
            self.fail_next.discard(op)
            raise LiveKitError(f"fake {op} failure")

    async def create_room(self, name: str, *, metadata: str = "", empty_timeout_s: int = 300) -> None:
        self._maybe_fail("create_room")
        self.rooms[name] = metadata

    async def delete_room(self, name: str) -> None:
        self._maybe_fail("delete_room")
        self.rooms.pop(name, None)
        self.deleted.append(name)

    async def dispatch_agent(self, room: str, agent_name: str, metadata: dict[str, Any]) -> str:
        self._maybe_fail("dispatch_agent")
        self.dispatches.append((room, agent_name, metadata))
        return f"AD_{len(self.dispatches)}"

    async def start_audio_recording(self, room: str, target: EgressTarget) -> str:
        self._maybe_fail("start_audio_recording")
        self.egresses.append((room, target))
        return f"EG_{len(self.egresses)}"

    async def egress_info(self, egress_id: str) -> dict[str, Any] | None:
        self._maybe_fail("egress_info")
        return self.egress_infos.get(egress_id)

    async def aclose(self) -> None:
        return None


def build_livekit(settings: Settings) -> LiveKitGateway:
    if settings.livekit_mode == "fake":
        return FakeLiveKit(
            api_key=settings.livekit_api_key.get_secret_value(),
            _secret=settings.livekit_api_secret.get_secret_value(),
        )
    return LiveKitClient(settings)
