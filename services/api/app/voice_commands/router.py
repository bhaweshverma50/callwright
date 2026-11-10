"""``/v1/voice-commands/*`` (006 T078, FR-028 to FR-033, contracts/voice_commands.yaml).

``stream-token`` mints a 60 s transcription-only credential (30 a minute per user). When the vendor
fails it answers 503 ``stt_unavailable`` and the browser records the clip and calls ``transcribe``
instead; without a vendor key (``DEEPGRAM_API_KEY``) both answer 503 ``stt_not_configured`` and
the browser offers typing.
``interpret`` validates every proposal before returning it, logs the command for 30 days and
records feature usage ``voice_copilot`` (billable amount from the catalog, zero by default).
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import JSONResponse

from app.core.auth import CurrentPrincipal
from app.core.errors import ProblemError, problem_responses, too_many_requests
from app.core.money import SIX
from app.core.rate_limit import RateLimiter
from app.llms.adapters.base import estimate_tokens
from app.llms.adapters.fake import FakeAdapter
from app.llms.charges import charge_tokens
from app.llms.client import ModelError, ModelRef, ModelTimeout, token_cost
from app.llms.runtime import runtime
from app.voice_commands.interpreter import keyword_interpret, model_interpret, validate
from app.voice_commands.models import VoiceCommandLog
from app.voice_commands.schemas import InterpretRequest
from app.voice_commands.stt.base import FakeSttAdapter, SttCommandAdapter, SttNotConfigured, SttUnavailable
from app.voice_commands.stt.deepgram import DeepgramSttAdapter

router = APIRouter(tags=["voice-commands"])
MAX_CLIP_BYTES = 2 * 1024 * 1024
CLIP_TYPES = ("audio/webm", "audio/ogg", "audio/mp4", "audio/wav", "audio/mpeg", "text/plain")
TOKEN_TTL_S = 60


def stt_adapter(request: Request) -> SttCommandAdapter:
    override = getattr(request.app.state, "copilot_stt", None)
    if override is not None:
        adapter: SttCommandAdapter = override
        return adapter
    s = request.app.state.settings
    if s.copilot_stt_provider == "deepgram" and s.deepgram_api_key:
        return DeepgramSttAdapter(s.deepgram_api_key.get_secret_value())
    return FakeSttAdapter()


async def _limit(request: Request, bucket: str, user_id: str) -> None:
    s = request.app.state.settings
    result = await RateLimiter(request.app.state.redis).hit(
        bucket, user_id, limit=s.voice_command_rate_limit_per_min, window_s=60
    )
    if not result.allowed:
        raise too_many_requests(result.retry_after_s, "Too many voice commands. Try again in a minute.")


def stt_not_configured() -> ProblemError:
    return ProblemError(
        503,
        "stt_not_configured",
        "Voice input is not set up",
        "Speech transcription is not configured on this server. Type the command instead.",
    )


def stt_unavailable(detail: str) -> ProblemError:
    return ProblemError(503, "stt_unavailable", "Transcription unavailable", detail)


@router.post("/voice-commands/stream-token", responses=problem_responses(401, 429, 503))
async def stream_token(request: Request, principal: CurrentPrincipal) -> JSONResponse:
    await _limit(request, "voice_token", principal.user_id)
    try:
        credential = await stt_adapter(request).mint_stream_credential(TOKEN_TTL_S)
    except SttNotConfigured as exc:
        raise stt_not_configured() from exc
    except SttUnavailable as exc:
        raise stt_unavailable("Live transcription is not available; record the clip instead.") from exc
    return JSONResponse(credential, headers={"Cache-Control": "no-store"})


@router.post("/voice-commands/transcribe", responses=problem_responses(401, 413, 503))
async def transcribe(
    request: Request, principal: CurrentPrincipal, audio: Annotated[UploadFile, File()]
) -> dict[str, str]:
    await _limit(request, "voice_transcribe", principal.user_id)
    data = await audio.read(MAX_CLIP_BYTES + 1)
    mime = (audio.content_type or "audio/webm").split(";")[0]
    if len(data) > MAX_CLIP_BYTES:
        raise ProblemError(
            413, "clip_too_large", "Clip too large", "Voice commands are limited to 30 seconds (2 MB)."
        )
    if mime not in CLIP_TYPES:
        raise ProblemError(
            413, "clip_unsupported", "Clip not supported", "Send the clip as WebM or Ogg Opus audio."
        )
    try:
        text = await stt_adapter(request).transcribe(data, mime)
    except SttNotConfigured as exc:
        raise stt_not_configured() from exc
    except SttUnavailable as exc:
        raise stt_unavailable("Try again, or type the command.") from exc
    return {"transcript": text}


@router.post("/voice-commands/interpret", responses=problem_responses(401, 422))
async def interpret(body: InterpretRequest, request: Request, principal: CurrentPrincipal) -> dict[str, Any]:
    state = request.app.state
    await _limit(request, "voice_interpret", principal.user_id)
    ref = ModelRef.parse(state.settings.voice_command_model)
    client = runtime().llm
    tokens = (estimate_tokens(body.transcript) + 300, 40)
    if isinstance(client.adapter_for(ref.provider), FakeAdapter):
        raw = keyword_interpret(body)
    else:
        try:
            raw, completion = await model_interpret(client, ref, body)
            tokens = (completion.input_tokens, completion.output_tokens)
        except (ModelError, ModelTimeout):
            raw = keyword_interpret(body)
    result, downgraded = validate(raw, body)
    raw_cost = token_cost(ref.model, *tokens).quantize(SIX)
    async with state.db.transaction(
        workspace_id=principal.workspace_id, user_id=principal.user_id
    ) as session:
        session.add(
            VoiceCommandLog(
                workspace_id=principal.workspace_id,
                user_id=principal.user_id,
                route=body.visual_state.current_route[:300],
                transcript=body.transcript[:1000],
                action=result["action"],
                downgraded=downgraded,
                raw_cost_usd=raw_cost,
            )
        )
        await charge_tokens(
            session,
            workspace_id=principal.workspace_id,
            feature_key="voice_copilot",
            tokens=sum(tokens),
            raw_cost_usd=raw_cost,
            billable=False,
            idempotency_key=f"voice_copilot:{uuid.uuid4().hex}",
        )
    return result
