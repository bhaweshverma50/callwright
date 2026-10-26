"""Transfer-call tool (005 T027, research R8, R10).

Flow: pick the number (static, or the LLM's ``destination`` checked against the allow-list),
speak the hold message, then:

* cold: SIP REFER on the caller's leg; the agent leaves with ``call_transfer``;
* warm, public: dial the destination into the caller's room, brief with both listening, leave;
* warm, private: dial the destination into a consult room, brief there, move the destination
  into the caller's room, leave.

A failure (no answer within ``ring_timeout_s``, REFER refused) goes back to the LLM as
``transfer_failed`` and the call continues. Non-SIP channels answer ``channel_unsupported``.
All telephony goes through :class:`TransferBackend` (LiveKit server API live, a fake in tests).
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from collections.abc import AsyncIterator, Callable, Mapping
from typing import Any, Protocol

from worker.tools.base import ToolContext, ToolResult, ToolSpecView

log = logging.getLogger(__name__)
E164 = re.compile(r"^\+[1-9]\d{6,14}$")
DESTINATION_IDENTITY = "transfer-destination"


class TransferError(Exception):
    pass


class TransferBackend(Protocol):
    async def cold(self, number: str) -> None:
        """SIP REFER the caller to ``number``; raises :class:`TransferError`."""
        ...

    async def dial(self, number: str, *, private: bool, ring_timeout_s: int) -> str:
        """Dial ``number`` into a consult room (private) or the caller's room; returns the room
        the destination is in. Raises :class:`TransferError` when nobody answers."""
        ...

    async def brief_private(self, room_name: str, text: str) -> None: ...

    async def move_to_caller(self, room_name: str) -> None: ...

    async def compose_briefing(self, instructions: str) -> str:
        """One short line written by the LLM from the briefing instructions."""
        ...

    async def hang_up_destination(self, room_name: str) -> None: ...


class TransferExecutor:
    def __init__(self, backend: TransferBackend | None) -> None:
        self.backend = backend

    def _number(self, config: Mapping[str, Any], arguments: Mapping[str, Any]) -> str | None:
        if config.get("routing_type") == "dynamic":
            return str(arguments.get("destination") or "").strip()
        return str(config.get("number") or "").strip()

    async def execute(
        self, spec: ToolSpecView, arguments: Mapping[str, Any], ctx: ToolContext
    ) -> ToolResult:
        config = spec.config
        number = self._number(config, arguments) or ""
        if not E164.match(number):
            return ToolResult.error("invalid_arguments", "The destination must be a +E.164 number.")
        allowed = [str(n) for n in config.get("allowed_numbers") or []]
        if config.get("routing_type") == "dynamic" and allowed and number not in allowed:
            return ToolResult.error(
                "invalid_arguments", "That number is not allowed for transfers."
            )
        if ctx.simulation:
            await ctx.control.hang_up("call_transfer")
            return ToolResult(llm_payload='{"transferred":true}', output=number, mocked=True)
        if not ctx.is_sip or self.backend is None:
            return ToolResult.error(
                "channel_unsupported", "Transfers work on phone calls only; offer another option."
            )
        hold = str(config.get("hold_message") or "").strip()
        if hold:
            await ctx.speak(hold)
        ring_timeout = int(config.get("ring_timeout_s") or 30)
        try:
            if config.get("transfer_type") != "warm":
                await self.backend.cold(number)
            else:
                await self._warm(config, number, ring_timeout, ctx)
        except TransferError as exc:
            log.info("transfer of %s failed: %s", ctx.call_id, exc)
            return ToolResult.error(
                "transfer_failed",
                "The transfer did not go through; tell the caller and offer help.",
            )
        await ctx.control.hang_up("call_transfer")
        return ToolResult(llm_payload='{"transferred":true}', output=number)

    async def _warm(
        self, config: Mapping[str, Any], number: str, ring_timeout: int, ctx: ToolContext
    ) -> None:
        assert self.backend is not None
        warm = config.get("warm_transfer") or {}
        private = warm.get("handoff_type", "private") == "private"
        room = await self.backend.dial(number, private=private, ring_timeout_s=ring_timeout)
        briefing = str(warm.get("briefing_message") or "").strip()
        if warm.get("briefing_message_type") == "prompt" and briefing:
            try:
                briefing = await self.backend.compose_briefing(briefing)
            except Exception:  # the instructions themselves are a usable briefing
                log.warning("briefing generation failed for %s", ctx.call_id)
        if private:
            if briefing:
                await self.backend.brief_private(room, briefing)
            await self.backend.move_to_caller(room)
        elif briefing:
            await ctx.speak(briefing)


# Live backend --------------------------------------------------------------------------------

Synthesize = Callable[[str], AsyncIterator[Any]]
Compose = Callable[[str], Any]


class LiveKitTransferBackend:
    """LiveKit SIP and room APIs. ``SIP_OUTBOUND_TRUNK_ID`` (or the call's outbound trunk) is
    used to dial the destination."""

    def __init__(
        self,
        *,
        url: str,
        api_key: str,
        api_secret: str,
        room_name: str,
        caller_identity: Callable[[], str | None],
        trunk_id: str | None = None,
        synthesize: Synthesize | None = None,
        compose: Compose | None = None,
    ) -> None:
        self.url = url
        self.api_key = api_key
        self.api_secret = api_secret
        self.room_name = room_name
        self.caller_identity = caller_identity
        self.trunk_id = trunk_id or os.environ.get("SIP_OUTBOUND_TRUNK_ID")
        self.synthesize = synthesize
        self.compose = compose

    def _api(self) -> Any:
        from livekit import api

        http_url = self.url.replace("wss://", "https://").replace("ws://", "http://")
        return api.LiveKitAPI(http_url, self.api_key, self.api_secret)

    async def cold(self, number: str) -> None:
        from livekit import api

        identity = self.caller_identity()
        if not identity:
            raise TransferError("no caller participant")
        client = self._api()
        try:
            await client.sip.transfer_sip_participant(
                api.TransferSIPParticipantRequest(
                    room_name=self.room_name,
                    participant_identity=identity,
                    transfer_to=f"tel:{number}",
                    play_dialtone=False,
                )
            )
        except Exception as exc:
            raise TransferError(f"refer refused: {type(exc).__name__}") from exc
        finally:
            await client.aclose()

    async def dial(self, number: str, *, private: bool, ring_timeout_s: int) -> str:
        from livekit import api

        if not self.trunk_id:
            raise TransferError("no outbound SIP trunk configured")
        room = f"{self.room_name}-consult" if private else self.room_name
        client = self._api()
        try:
            await asyncio.wait_for(
                client.sip.create_sip_participant(
                    api.CreateSIPParticipantRequest(
                        sip_trunk_id=self.trunk_id,
                        sip_call_to=number,
                        room_name=room,
                        participant_identity=DESTINATION_IDENTITY,
                        participant_name="Transfer",
                        wait_until_answered=True,
                    )
                ),
                ring_timeout_s,
            )
        except Exception as exc:
            raise TransferError(f"no answer: {type(exc).__name__}") from exc
        finally:
            await client.aclose()
        return room

    async def brief_private(self, room_name: str, text: str) -> None:
        """Join the consult room as an announcer and play the briefing to the destination."""
        if self.synthesize is None:
            return
        from livekit import api, rtc

        token = (
            api.AccessToken(self.api_key, self.api_secret)
            .with_identity("agent-briefing")
            .with_grants(api.VideoGrants(room_join=True, room=room_name))
            .to_jwt()
        )
        room = rtc.Room()
        await room.connect(self.url, token)
        try:
            source = rtc.AudioSource(24000, 1)
            track = rtc.LocalAudioTrack.create_audio_track("briefing", source)
            await room.local_participant.publish_track(track)
            async for chunk in self.synthesize(text):
                frame: Any = getattr(chunk, "frame", None) or chunk
                await source.capture_frame(frame)
            await source.wait_for_playout()
        finally:
            await room.disconnect()

    async def move_to_caller(self, room_name: str) -> None:
        from livekit import api

        client = self._api()
        try:
            await client.room.move_participant(
                api.MoveParticipantRequest(
                    room=room_name, identity=DESTINATION_IDENTITY, destination_room=self.room_name
                )
            )
        except Exception as exc:
            raise TransferError(f"move failed: {type(exc).__name__}") from exc
        finally:
            await client.aclose()

    async def compose_briefing(self, instructions: str) -> str:
        if self.compose is None:
            return instructions
        text = await self.compose(instructions)
        return str(text or instructions)

    async def hang_up_destination(self, room_name: str) -> None:
        from livekit import api

        client = self._api()
        try:
            await client.room.remove_participant(
                api.RoomParticipantIdentity(room=room_name, identity=DESTINATION_IDENTITY)
            )
        finally:
            await client.aclose()
