"""SIP specifics for phone and WhatsApp calls (003 entry helpers; 010 T020, T033, research R5, R6).

* ``sip_attributes`` reads the SIP participant attributes for the claim; ``dtmf_code`` maps
  keypad digits to RFC 4733 event codes for ``publish_dtmf``.
* ``ring_phase``: an inbound call posts ``ringing``, waits the agent's ring duration (the API has
  already run the inbound webhook inside the claim, overlapping this wait) and only then counts
  as answered. A caller who hangs up while it rings never connects, so the call is ``failed``
  and never billed.
* ``dial_outbound``: posts ``ringing``, asks LiveKit to call the destination through the
  number's outbound trunk and waits for the answer. A refusal is mapped from the SIP status code
  (``map_sip_status``) to ``busy``, ``no_answer`` or ``failed`` with a ``sip_<code>``
  diagnostic; none of them is billed (billing starts at ``in_progress``).
"""

from __future__ import annotations

import array
import asyncio
import contextlib
import math
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Literal, Protocol

from callwright_contract.protocol import OutboundDial, SipAttributes

from worker import telemetry

# LiveKit SIP participant attribute names.
SIP_ATTR_CALL_ID = "sip.callID"
SIP_ATTR_TRUNK_ID = "sip.trunkID"
SIP_ATTR_TRUNK_NUMBER = "sip.trunkPhoneNumber"
SIP_ATTR_CALLER_NUMBER = "sip.phoneNumber"

DTMF_CODES: Mapping[str, int] = {**{str(d): d for d in range(10)}, "*": 10, "#": 11}

CALLEE_IDENTITY = "callee"
ANSWER_GRACE_S = 10.0  # the answered callee joining the room after the dial returns

FailStatus = Literal["busy", "no_answer", "failed"]


class DialFailed(Exception):
    """The destination did not answer; ``status`` is the call status to post."""

    def __init__(
        self, status: FailStatus, diagnostic: str, sip_status_code: int | None = None
    ) -> None:
        super().__init__(f"{status}: {diagnostic}")
        self.status: FailStatus = status
        self.diagnostic = diagnostic
        self.sip_status_code = sip_status_code


class SipDialError(Exception):
    """Raised by a ``SipDialer``: the SIP status code when the far end answered with one."""

    def __init__(
        self, sip_status_code: int | None, message: str = "", *, timed_out: bool = False
    ) -> None:
        super().__init__(message or f"sip {sip_status_code}")
        self.sip_status_code = sip_status_code
        self.timed_out = timed_out


class SipDialer(Protocol):
    async def call(
        self,
        *,
        room_name: str,
        trunk_id: str,
        to_number: str,
        from_number: str,
        identity: str,
        ring_timeout_s: int,
    ) -> None: ...


def sip_attributes(attributes: Mapping[str, str], identity: str | None = None) -> SipAttributes:
    """Claim ``sip`` block from a SIP participant's attributes (contract ``SipAttributes``)."""
    return SipAttributes(
        call_id=attributes.get(SIP_ATTR_CALL_ID),
        trunk_id=attributes.get(SIP_ATTR_TRUNK_ID),
        trunk_phone_number=attributes.get(SIP_ATTR_TRUNK_NUMBER),
        caller_number=attributes.get(SIP_ATTR_CALLER_NUMBER),
        participant_identity=identity,
    )


def dtmf_code(digit: str) -> int:
    try:
        return DTMF_CODES[digit]
    except KeyError:
        raise ValueError(f"invalid keypad digit {digit!r}") from None


def map_sip_status(code: int | None, *, timed_out: bool = False) -> tuple[FailStatus, str]:
    """Research R6: busy (486, 600), no answer (408, 480, 487, ring timeout), auth failures,
    unreachable trunks, a destination that cannot be reached at all (410: the lab PBX's answer
    for a softphone that is not registered), and every other 4xx/5xx/6xx as failed with
    ``sip_<code>``."""
    if timed_out:
        return "no_answer", "ring_timeout"
    if code is None:
        return "failed", "trunk_unreachable"
    if code in (486, 600):
        return "busy", f"sip_{code}"
    if code in (408, 480, 487):
        return "no_answer", f"sip_{code}"
    if code in (401, 407):
        return "failed", "trunk_auth_failed"
    if code == 410:
        return "failed", "destination_unreachable"
    return "failed", f"sip_{code}"


# Inbound ------------------------------------------------------------------------------------

# livekit-sip answers the SIP call as soon as the caller is in the room, so the phone network's
# own ringback stops then; the ring phase plays one instead. ponytail: one tone, the double ring
# used in India and the UK (400 + 450 Hz; 0.4 s on, 0.2 off, 0.4 on, 2 s off). A per-country tone
# can follow the number's country if callers elsewhere ask for it.
RINGBACK_RATE = 16000
RINGBACK_FRAME_MS = 20
_RINGBACK_BURSTS = ((0.0, 0.4), (0.6, 1.0))
_RINGBACK_CYCLE_S = 3.0
_RINGBACK_LEVEL = 0.12  # of full scale, about -18 dBFS


def ringback_cycle(rate: int = RINGBACK_RATE) -> array.array[int]:
    """One 3 s ringback cycle as 16-bit mono PCM."""
    samples = array.array("h", bytes(2 * int(rate * _RINGBACK_CYCLE_S)))
    amp = 32767 * _RINGBACK_LEVEL / 2
    ramp = int(rate * 0.005)  # 5 ms fades, no clicks
    for start, end in _RINGBACK_BURSTS:
        a, b = int(start * rate), int(end * rate)
        for i in range(a, b):
            edge = min(1.0, (i - a) / ramp, (b - 1 - i) / ramp)
            t = i / rate
            value = math.sin(2 * math.pi * 400 * t) + math.sin(2 * math.pi * 450 * t)
            samples[i] = int(amp * edge * value)
    return samples


async def play_ringback(room: Any) -> None:
    """Publish the ringback tone into the room until cancelled, then unpublish it."""
    from livekit import rtc

    source = rtc.AudioSource(RINGBACK_RATE, 1)
    track = rtc.LocalAudioTrack.create_audio_track("ringback", source)
    options = rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
    publication = await room.local_participant.publish_track(track, options)
    cycle = ringback_cycle()
    step = RINGBACK_RATE * RINGBACK_FRAME_MS // 1000
    try:
        while True:
            for i in range(0, len(cycle), step):
                chunk = cycle[i : i + step]
                await source.capture_frame(
                    rtc.AudioFrame(chunk.tobytes(), RINGBACK_RATE, 1, len(chunk))
                )
    finally:
        with contextlib.suppress(Exception):
            await asyncio.shield(room.local_participant.unpublish_track(publication.sid))
        with contextlib.suppress(Exception):
            await source.aclose()


async def ring_phase(
    room: Any,
    recorder: Any,
    ring_duration_ms: int,
    caller_identity: str,
    *,
    sleep: Callable[[float], Any] = asyncio.sleep,
    ringback: Callable[[], Awaitable[None]] | None = None,
) -> bool:
    """Post ``ringing`` and wait ``ring_duration_ms`` while ``ringback`` plays the tone. False
    when the caller hung up meanwhile."""
    recorder.status("ringing")
    tone = (
        asyncio.ensure_future(ringback()) if ringback is not None and ring_duration_ms > 0 else None
    )
    left = asyncio.Event()

    def on_left(participant: Any) -> None:
        if getattr(participant, "identity", None) == caller_identity:
            left.set()

    room.on("participant_disconnected", on_left)
    try:
        with telemetry.span("ring_phase", {"ring_duration_ms": ring_duration_ms}):
            waiter = asyncio.ensure_future(left.wait())
            timer = asyncio.ensure_future(sleep(max(0, ring_duration_ms) / 1000.0))
            _done, pending = await asyncio.wait(
                {waiter, timer}, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
    finally:
        if tone is not None:
            tone.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await tone
        with contextlib.suppress(Exception):
            room.off("participant_disconnected", on_left)
    remote = getattr(room, "remote_participants", None)
    gone = isinstance(remote, Mapping) and caller_identity not in remote
    return not left.is_set() and not gone


# Outbound -----------------------------------------------------------------------------------


class LiveKitSipDialer:
    """``CreateSIPParticipant`` through the job's LiveKit API client (research R6)."""

    def __init__(self, api: Any) -> None:
        self.api = api

    async def call(
        self,
        *,
        room_name: str,
        trunk_id: str,
        to_number: str,
        from_number: str,
        identity: str,
        ring_timeout_s: int,
    ) -> None:
        from google.protobuf.duration_pb2 import Duration
        from livekit import api

        request = api.CreateSIPParticipantRequest(
            sip_trunk_id=trunk_id,
            sip_call_to=to_number,
            sip_number=from_number,
            room_name=room_name,
            participant_identity=identity,
            participant_name="Callee",
            wait_until_answered=True,
            ringing_timeout=Duration(seconds=ring_timeout_s),
        )
        try:
            await asyncio.wait_for(
                self.api.sip.create_sip_participant(request, timeout=ring_timeout_s + 10),
                ring_timeout_s + 15,
            )
        except TimeoutError as exc:
            raise SipDialError(None, "ring timeout", timed_out=True) from exc
        except api.TwirpError as exc:
            metadata = exc.metadata or {}
            raw = metadata.get("sip_status_code") or metadata.get("sip_status")
            code = int(raw) if raw and str(raw).isdigit() else None
            if code is None and exc.code in ("deadline_exceeded",):
                raise SipDialError(None, exc.message, timed_out=True) from exc
            raise SipDialError(code, exc.message) from exc


async def dial(
    dialer: SipDialer,
    recorder: Any,
    spec: OutboundDial,
    room_name: str,
    wait_for_callee: Callable[[], Any],
) -> Any:
    """Post ``ringing``, dial and wait for the answer; ``DialFailed`` when it is not answered."""
    recorder.status("ringing")
    with telemetry.span(
        "dial", {"sip.trunk_id": spec.sip_trunk_id, "ring_timeout_s": spec.ring_timeout_s}
    ):
        try:
            await dialer.call(
                room_name=room_name,
                trunk_id=spec.sip_trunk_id,
                to_number=spec.to_number,
                from_number=spec.from_number,
                identity=CALLEE_IDENTITY,
                ring_timeout_s=spec.ring_timeout_s,
            )
        except SipDialError as exc:
            status, diagnostic = map_sip_status(exc.sip_status_code, timed_out=exc.timed_out)
            raise DialFailed(status, diagnostic, exc.sip_status_code) from exc
        try:
            return await asyncio.wait_for(wait_for_callee(), ANSWER_GRACE_S)
        except TimeoutError as exc:
            raise DialFailed("failed", "callee_never_joined") from exc


async def dial_outbound(
    ctx: Any, spec: OutboundDial, recorder: Any, dialer: SipDialer | None = None
) -> Any:
    """``dial`` for a job: LiveKit's SIP API and the job's room."""
    return await dial(
        dialer or LiveKitSipDialer(ctx.api),
        recorder,
        spec,
        ctx.room.name,
        lambda: ctx.wait_for_participant(identity=CALLEE_IDENTITY),
    )
