"""Live benchmark mode (T102): real WebRTC rooms, the real worker, fake vendors.

Pieces, all in one process tree:

- A LiveKit server, external (``livekit-server --dev`` or the ``livekit/livekit-server``
  image, API key ``devkey``, secret ``secret``).
- A fake internal API (aiohttp on 127.0.0.1) answering ``/calls/claim`` with a RuntimeConfig
  built from the call set's agent config, and recording ``/calls/{id}/events`` with the same
  contract checks as the offline harness.
- The production agent server (:func:`worker.entry.create_server`) registered as
  ``callwright-bench``; each job runs the production ``job_entry`` (claim, ``LiveCall``,
  Silero VAD, semantic turn detector, ``AgentSession``, room I/O, noise-cancellation adapter)
  with the STT, LLM and TTS adapters swapped for the fakes in ``live_fakes`` (vendor delays
  sampled from the call set's profiles).
- A scripted caller per call: joins the room after an explicit agent dispatch (as the API does
  for a web call), publishes the WAV fixtures as its microphone in real time, and detects agent
  audio onset on the subscribed agent track.

Per caller turn, ``e2e_ms`` is measured at the caller: from the moment the last fixture sample
leaves the caller's audio source to the first received agent frame above the onset threshold.
That is the end-to-end time over the real transport, including uplink, VAD, turn detection,
fake vendor delays, the TTS adapter, room output and downlink jitter buffer. The worker's own
``turn`` events are collected too, so the report shows how close the worker's stored latency
is to what the caller experiences.

Real vendors are not used: there are no vendor keys in this environment. A real-vendor run
needs ``DEEPGRAM_API_KEY``, ``AZURE_OPENAI_API_KEY`` (plus endpoint and API version) and
``ELEVEN_API_KEY`` for the default stack, and a ``--vendors real`` switch that skips
:func:`~tests.harness.bench.live_fakes.live_registry` (not built yet).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import statistics
import time
import uuid
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import yaml
from aiohttp import web

from tests.harness.bench import synth
from tests.harness.bench.live_fakes import LiveFakeParams, frame_rms
from tests.harness.fakes import contract_errors
from tests.harness.runner import DEFAULT_CONFIG, build_runtime, deep_merge, load_agent_config

log = logging.getLogger("callwright.bench.live")

BENCH_DIR = Path(__file__).parent
DEFAULT_LIVE_BASELINE = BENCH_DIR / "baseline_live.json"
BENCH_AGENT_NAME = "callwright-bench"
SERVICE_TOKEN = "bench-service-token"


def percentile(values: Sequence[float], q: float) -> float:
    from tests.harness.bench.benchmark import percentile as nearest_rank

    return nearest_rank(values, q)


# --------------------------------------------------------------------------------------------
# Options and report


@dataclass
class LiveOptions:
    url: str = "ws://localhost:7880"
    api_key: str = "devkey"
    api_secret: str = "secret"
    calls: int | None = None
    concurrency: int | None = None
    onset_rms: float = 300.0
    quiet_s: float = 0.7
    turn_timeout_s: float = 10.0
    join_timeout_s: float = 45.0


@dataclass
class LiveReport:
    calls: int
    turns: int
    missed_turns: int
    e2e_p50_ms: float
    e2e_p95_ms: float
    e2e_max_ms: float
    worker_e2e_p50_ms: float | None
    worker_e2e_p95_ms: float | None
    worker_minus_caller_median_ms: float | None
    greeting_median_ms: float | None
    stt_final_median_ms: float | None
    eou_delay_median_ms: float | None
    llm_ttft_median_ms: float | None
    tts_ttfb_median_ms: float | None
    contract_violations: int
    wall_s: float
    cutoffs: int = 0
    mode: str = "live"
    vendors: str = "fake"
    caller_e2e_ms: list[float] = field(default_factory=list)
    details: list[dict[str, Any]] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("caller_e2e_ms")
        data.pop("details")
        return data


def _median(values: Sequence[float]) -> float | None:
    return float(statistics.median(values)) if values else None


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 1)


# --------------------------------------------------------------------------------------------
# Fake internal API


class FakeInternalApi:
    """``/v1/internal/calls/claim`` and ``/events`` for the bench calls, on 127.0.0.1."""

    def __init__(self, config: Mapping[str, Any], token: str = SERVICE_TOKEN) -> None:
        self.config = dict(config)
        self.token = token
        self.events: dict[str, list[dict[str, Any]]] = {}
        self.violations: list[str] = []
        self.ended: dict[str, asyncio.Event] = {}
        self.claims: list[str] = []
        self._runner: web.AppRunner | None = None
        self.url = ""

    def _authorized(self, request: web.Request) -> bool:
        return request.headers.get("Authorization") == f"Bearer {self.token}"

    def ended_event(self, call_id: str) -> asyncio.Event:
        return self.ended.setdefault(call_id, asyncio.Event())

    async def claim(self, request: web.Request) -> web.Response:
        if not self._authorized(request):
            return web.json_response({"title": "unauthorized"}, status=401)
        body = await request.json()
        call_id = str(body["dispatch_metadata"]["call_id"])
        self.claims.append(call_id)
        runtime = build_runtime(self.config, {"channel": "web"})
        return web.json_response(
            {"admitted": True, "call_id": call_id, "runtime": runtime.model_dump(mode="json")}
        )

    async def post_events(self, request: web.Request) -> web.Response:
        if not self._authorized(request):
            return web.json_response({"title": "unauthorized"}, status=401)
        call_id = request.match_info["call_id"]
        stored = self.events.setdefault(call_id, [])
        if self.ended_event(call_id).is_set():
            return web.json_response({"title": "call is terminal"}, status=409)
        body = await request.json()
        events = list(body.get("events") or [])
        last_seq = max((int(e.get("seq", 0)) for e in stored), default=0)
        for event in events:
            for error in contract_errors(event):
                self.violations.append(f"{call_id} seq {event.get('seq')}: {error}")
            if int(event.get("seq", 0)) <= last_seq:
                self.violations.append(f"{call_id} seq {event.get('seq')} not increasing")
            last_seq = max(last_seq, int(event.get("seq", 0)))
        stored.extend(events)
        if any(
            e.get("type") == "status" and e.get("status") in ("ended", "failed") for e in events
        ):
            self.ended_event(call_id).set()
        return web.json_response(
            {"accepted": len(events), "duplicates": 0, "control": {"action": "none"}}
        )

    async def start(self) -> str:
        app = web.Application()
        app.router.add_post("/v1/internal/calls/claim", self.claim)
        app.router.add_post("/v1/internal/calls/{call_id}/events", self.post_events)
        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]
        self.url = f"http://127.0.0.1:{port}/v1/internal"
        return self.url

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()


# --------------------------------------------------------------------------------------------
# Scripted caller


class AgentAudioMonitor:
    """Agent audio onsets at the caller (receipt time of the first loud frame after quiet)."""

    def __init__(self, threshold: float, min_gap_s: float = 0.15) -> None:
        self.threshold = threshold
        self.min_gap_s = min_gap_s
        self.onsets: list[float] = []
        self.last_loud_at = 0.0
        self.frames = 0

    def feed(self, rms: float, at: float) -> None:
        self.frames += 1
        if rms < self.threshold:
            return
        if at - self.last_loud_at > self.min_gap_s:
            self.onsets.append(at)
        self.last_loud_at = at

    async def onset_after(self, after: float, timeout_s: float) -> float | None:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            for onset in self.onsets:
                if onset > after:
                    return onset
            await asyncio.sleep(0.005)
        return None

    async def wait_quiet(self, quiet_s: float, timeout_s: float = 30.0) -> None:
        deadline = time.time() + timeout_s
        while time.time() < deadline and time.time() - self.last_loud_at < quiet_s:
            await asyncio.sleep(0.02)


class CallerMic:
    """Real-time microphone: utterances from WAV fixtures, low dither between them."""

    def __init__(self, rate: int, rtc: Any, seed: int = 0) -> None:
        self.rate = rate
        self.source = rtc.AudioSource(rate, 1, queue_size_ms=40)
        self._rtc = rtc
        self._utterances: deque[tuple[npt.NDArray[np.int16], asyncio.Future[float]]] = deque()
        self._rng = np.random.default_rng(seed)
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._pump())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def say(self, pcm: npt.NDArray[np.int16]) -> float:
        """Play ``pcm``; returns the wall time its last sample left the source."""
        done: asyncio.Future[float] = asyncio.get_running_loop().create_future()
        self._utterances.append((pcm, done))
        return await done

    def duration_s(self, pcm: npt.NDArray[np.int16]) -> float:
        return len(pcm) / self.rate

    async def _pump(self) -> None:
        step = self.rate // 100
        while True:
            if self._utterances:
                pcm, done = self._utterances.popleft()
                for start in range(0, len(pcm), step):
                    chunk = pcm[start : start + step]
                    if len(chunk) < step:
                        chunk = np.concatenate([chunk, np.zeros(step - len(chunk), np.int16)])
                    await self._capture(chunk)
                done.set_result(time.time() + self.source.queued_duration)
                continue
            await self._capture(self._rng.integers(-4, 5, step).astype(np.int16))

    async def _capture(self, chunk: npt.NDArray[np.int16]) -> None:
        frame = self._rtc.AudioFrame(chunk.tobytes(), self.rate, 1, len(chunk))
        await self.source.capture_frame(frame)


@dataclass
class CallResult:
    call_id: str
    caller_e2e_ms: list[float | None]
    events: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    cutoffs: list[bool] = field(default_factory=list)


def _token(options: LiveOptions, identity: str, room: str) -> str:
    from livekit import api

    return (
        api.AccessToken(options.api_key, options.api_secret)
        .with_identity(identity)
        .with_grants(api.VideoGrants(room_join=True, room=room))
        .to_jwt()
    )


async def run_caller(
    index: int,
    run_id: str,
    options: LiveOptions,
    fixtures: Sequence[npt.NDArray[np.int16]],
    rate: int,
    params: LiveFakeParams,
    fake_api: FakeInternalApi,
    lkapi: Any,
) -> CallResult:
    from livekit import api, rtc

    room_name = f"bench-{run_id}-{index:02d}"
    call_id = f"call_bench{run_id}{index:02d}"
    metadata = {"call_id": call_id, "bench": params.to_json()}
    await lkapi.agent_dispatch.create_dispatch(
        api.CreateAgentDispatchRequest(
            agent_name=BENCH_AGENT_NAME, room=room_name, metadata=json.dumps(metadata)
        )
    )
    room = rtc.Room()
    monitor = AgentAudioMonitor(options.onset_rms)
    readers: list[asyncio.Task[None]] = []
    streams: list[Any] = []

    def on_track(track: Any, publication: Any, participant: Any) -> None:
        if track.kind != rtc.TrackKind.KIND_AUDIO:
            return
        stream = rtc.AudioStream(track, sample_rate=48000, num_channels=1)
        streams.append(stream)

        async def read() -> None:
            async for event in stream:
                monitor.feed(frame_rms(event.frame), time.time())

        readers.append(asyncio.create_task(read()))

    room.on("track_subscribed", on_track)
    result = CallResult(call_id, [])
    mic = CallerMic(rate, rtc, seed=index)
    try:
        await room.connect(options.url, _token(options, f"caller-{index}", room_name))
        track = rtc.LocalAudioTrack.create_audio_track("caller-mic", mic.source)
        await room.local_participant.publish_track(
            track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
        )
        mic.start()
        joined = time.time()
        greeting = await monitor.onset_after(joined, options.join_timeout_s)
        if greeting is None:
            result.error = "no greeting audio from the agent"
            return result
        await monitor.wait_quiet(options.quiet_s)
        for pcm in fixtures:
            eos = await mic.say(pcm)
            # The agent talking before the caller's last sample is a cut-off: it took the turn
            # during a mid-sentence pause (or talked over the caller).
            started = eos - mic.duration_s(pcm)
            result.cutoffs.append(any(started < at < eos for at in monitor.onsets))
            onset = await monitor.onset_after(eos, options.turn_timeout_s)
            result.caller_e2e_ms.append(None if onset is None else (onset - eos) * 1000.0)
            await monitor.wait_quiet(options.quiet_s)
    except Exception as exc:  # report the call as failed, keep the run going
        result.error = f"{type(exc).__name__}: {exc}"
    finally:
        await mic.stop()
        await room.disconnect()
        for reader in readers:
            reader.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await reader
        for stream in streams:
            with contextlib.suppress(Exception):
                await stream.aclose()
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(fake_api.ended_event(call_id).wait(), timeout=20.0)
    result.events = list(fake_api.events.get(call_id, []))
    return result


# --------------------------------------------------------------------------------------------
# Run


def load_fixtures(callset: Mapping[str, Any]) -> tuple[list[npt.NDArray[np.int16]], int]:
    turns = list(callset["turns"])
    directory = synth.fixtures_dir(callset)
    paths = [directory / synth.fixture_name(i) for i in range(len(turns))]
    if not all(p.exists() for p in paths):
        synth.generate(turns, directory)
    loaded = [synth.read_wav(p) for p in paths]
    rates = {rate for _, rate in loaded}
    if len(rates) != 1:
        raise ValueError(f"fixtures must share one sample rate, got {sorted(rates)}")
    return [pcm for pcm, _ in loaded], rates.pop()


def scripted_transcripts(callset: Mapping[str, Any]) -> list[str]:
    """What the fake STT returns, in order: one final per said segment (R4 pause scenarios)."""
    return [part for raw in callset["turns"] for part in synth.Turn.parse(raw).segments]


def summarize(
    results: Sequence[CallResult], violations: int, wall_s: float, calls: int
) -> LiveReport:
    caller = [v for r in results for v in r.caller_e2e_ms if v is not None]
    missed = sum(1 for r in results for v in r.caller_e2e_ms if v is None) + sum(
        1 for r in results if r.error
    )
    turns = [
        e for r in results for e in r.events if e.get("type") == "turn" and e["turn_index"] > 0
    ]
    greetings = [
        float(e["e2e_ms"])
        for r in results
        for e in r.events
        if e.get("type") == "turn" and e["turn_index"] == 0 and e.get("e2e_ms") is not None
    ]
    worker = [float(e["e2e_ms"]) for e in turns if e.get("e2e_ms") is not None]
    gaps: list[float] = []
    for r in results:
        by_index = {
            e["turn_index"]: e
            for e in r.events
            if e.get("type") == "turn" and e["turn_index"] > 0 and e.get("e2e_ms") is not None
        }
        for i, value in enumerate(r.caller_e2e_ms, start=1):
            if value is not None and i in by_index:
                gaps.append(float(by_index[i]["e2e_ms"]) - value)

    def med(key: str) -> float | None:
        return _median([float(e[key]) for e in turns if e.get(key) is not None])

    if not caller:
        raise RuntimeError(
            "no caller turn got agent audio: "
            + "; ".join(r.error or "timeouts" for r in results)[:500]
        )
    return LiveReport(
        calls=calls,
        turns=len(caller),
        missed_turns=missed,
        e2e_p50_ms=round(percentile(caller, 50), 1),
        e2e_p95_ms=round(percentile(caller, 95), 1),
        e2e_max_ms=round(max(caller), 1),
        worker_e2e_p50_ms=percentile(worker, 50) if worker else None,
        worker_e2e_p95_ms=percentile(worker, 95) if worker else None,
        worker_minus_caller_median_ms=_round(_median(gaps)),
        greeting_median_ms=_median(greetings),
        stt_final_median_ms=med("stt_final_ms"),
        eou_delay_median_ms=med("eou_delay_ms"),
        llm_ttft_median_ms=med("llm_ttft_ms"),
        tts_ttfb_median_ms=med("tts_ttfb_ms"),
        contract_violations=violations,
        wall_s=round(wall_s, 1),
        cutoffs=sum(1 for r in results for cut in r.cutoffs if cut),
        caller_e2e_ms=caller,
        details=[call_details(r) for r in results],
    )


def call_details(result: CallResult) -> dict[str, Any]:
    """Per-turn caller and worker numbers for one call (``--details`` output)."""
    worker = {e["turn_index"]: e for e in result.events if e.get("type") == "turn"}
    keys = ("e2e_ms", "stt_final_ms", "eou_delay_ms", "llm_ttft_ms", "tts_ttfb_ms")
    turns = []
    for i, caller in enumerate(result.caller_e2e_ms, start=1):
        event = worker.get(i, {})
        turns.append(
            {
                "turn": i,
                "cutoff": result.cutoffs[i - 1] if i <= len(result.cutoffs) else False,
                "caller_e2e_ms": None if caller is None else round(caller, 1),
                **{f"worker_{k}": event.get(k) for k in keys},
            }
        )
    return {"call_id": result.call_id, "error": result.error, "turns": turns}


async def run_live(callset_path: Path, options: LiveOptions) -> LiveReport:
    from livekit import api

    from worker.entry import create_server
    from worker.settings import WorkerSettings

    callset = yaml.safe_load(callset_path.read_text())
    live_cfg = callset.get("live") or {}
    calls = int(options.calls or live_cfg.get("calls") or callset["calls"])
    concurrency = max(1, int(options.concurrency or live_cfg.get("concurrency") or 4))
    config = deep_merge(load_agent_config(DEFAULT_CONFIG), callset.get("config_overrides") or {})
    fixtures, rate = load_fixtures(callset)
    seed = int(callset.get("seed", 0))

    fake_api = FakeInternalApi(config)
    api_url = await fake_api.start()
    env = {
        "LIVEKIT_URL": options.url,
        "LIVEKIT_API_KEY": options.api_key,
        "LIVEKIT_API_SECRET": options.api_secret,
        "CALLWRIGHT_INTERNAL_API_URL": api_url,
        "CALLWRIGHT_SERVICE_TOKEN": SERVICE_TOKEN,
        "WORKER_AGENT_NAME": BENCH_AGENT_NAME,
    }
    saved = {k: os.environ.get(k) for k in env}
    os.environ.update(env)  # job processes read WorkerSettings from the environment
    from tests.harness.bench.live_worker import bench_job_entry

    server = create_server(
        WorkerSettings(), entrypoint=bench_job_entry, port=0, num_idle_processes=concurrency
    )
    registered = asyncio.Event()
    server.on("worker_registered", lambda *_: registered.set())
    server_task = asyncio.create_task(server.run(devmode=True))
    lkapi = api.LiveKitAPI(
        options.url.replace("ws", "http", 1), options.api_key, options.api_secret
    )
    run_id = uuid.uuid4().hex[:6]
    started = time.time()
    try:
        await asyncio.wait_for(registered.wait(), timeout=60.0)
        gate = asyncio.Semaphore(concurrency)

        async def one(i: int) -> CallResult:
            async with gate:
                params = LiveFakeParams(
                    turns=scripted_transcripts(callset),
                    profile=dict(callset["profile"]),
                    seed=seed + i,
                    **{k: v for k, v in (live_cfg.get("fakes") or {}).items()},
                )
                return await run_caller(i, run_id, options, fixtures, rate, params, fake_api, lkapi)

        results = await asyncio.gather(*(one(i) for i in range(calls)))
    finally:
        await lkapi.aclose()
        with contextlib.suppress(Exception):
            await server.aclose()
        server_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await server_task
        await fake_api.stop()
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    for r in results:
        if r.error:
            log.warning("call %s: %s", r.call_id, r.error)
    for violation in fake_api.violations[:20]:
        log.warning("contract: %s", violation)
    return summarize(results, len(fake_api.violations), time.time() - started, calls)
