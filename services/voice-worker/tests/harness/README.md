# Offline harness

Runs a scripted caller against an agent config with no network, keys or telephony (Principle
VII). The worker's own modules do the work: `plan_session` and the adapter registry (with fake
vendors), the call-behaviour timers on a virtual clock, pronunciation, `RuntimeCallControl` and
segment overrides, the latency tracker, usage meters, the event recorder and the event poster.
The fake internal API checks every posted event against `contracts/call_events.yaml`.

```bash
uv run pytest tests/harness                      # every script plus the latency gate
uv run python -m tests.harness.runner --config tests/harness/configs/default_agent.json \
  --script tests/harness/scripts/greeting.yaml   # one script, JSON summary, exit 1 on failure
uv run python -m tests.harness.bench.benchmark   # p50/p95 on fakes against bench/baseline.json
uv run python -m tests.harness.bench.benchmark --update-baseline
```

`--config` takes an exported agent version (`{"config": {...}}`) or a bare AgentConfig.

## Live benchmark (`--mode live`)

Fake mode prices a turn with the timing model below. Live mode measures it: real WebRTC rooms
on a LiveKit server, the production agent server and job entry (claim, `LiveCall`, Silero VAD,
the semantic turn detector, `AgentSession`, room I/O, the NC adapter), and a scripted caller
per call that publishes `bench/fixtures/turn_<n>.wav` as its microphone and timestamps the
first agent audio it receives. Only STT, LLM and TTS are fakes (`bench/live_fakes.py`), with
delays sampled from the call set's profiles; a local fake internal API answers the claim and
checks every events post against the contract.

```bash
docker run --rm -d --name lk-bench -p 7880:7880 -p 7881:7881 -p 7882:7882/udp \
  livekit/livekit-server --dev --bind 0.0.0.0          # key devkey, secret secret
uv run python -m tests.harness.bench.benchmark --mode live            # 20 x 6, 4 at a time
uv run python -m tests.harness.bench.benchmark --mode live --calls 2 --details /tmp/turns.json
uv run python -m tests.harness.bench.benchmark --mode live --update-baseline
docker stop lk-bench
```

`e2e_ms` is caller-side: last fixture sample out of the caller's audio source to the first
received agent frame above the onset threshold. The report also has the worker's own stored
`e2e_ms` and components for the same turns (`worker_minus_caller_median_ms` is how much the
stored latency under-reports what the caller hears: uplink, output buffering and downlink).
The baseline is `bench/baseline_live.json`. Fixtures are synthesized speech-like audio (no TTS,
no recordings): `python -m tests.harness.bench.synth` regenerates them from `callset.yaml`.

Baselines (2026-10-16, 20 x 6 calls, 4 concurrent, local `livekit-server` 1.13 in Docker on
macOS, fake vendors on the call set's profiles):

| Calibration | p50 caller | p95 caller | worker p50 | end of turn (median) |
|---|---|---|---|---|
| v1 (VAD 0.55 s, max delay 2.45 s) | 953 ms | 2,734 ms | 765 ms | 608 ms |
| v2, research R4 (`baseline_live.json`) | 770 ms | 1,402 ms | 597 ms | 400 ms |

v1 failed the 800/1,500 ms budgets because Silero's 0.55 s end-of-speech window, not
`min_endpointing_delay`, bounded every end of turn, and the digit turn always waited the 2.45 s
max delay. v2 (research R4) shortens the VAD window to 0.3 s, maps responsiveness 0.8 to
0.40 s / 1.22 s, runs the TTS preemptively and holds a trailing digit string as unfinished. Now
five of six turns are bound by the vendor chain (STT final, LLM first token, TTS first byte)
plus about 180 ms of transport, which puts the p50 floor near 700 ms and the measured p50 at
770 ms (runs vary by about 30 ms); the digit turn sets p95 at `max_endpointing_delay` plus
transport. No missed turns, cut-offs or contract violations; about 3 minutes.

### Pause scenarios (cut-offs)

`bench/callset_pauses.yaml` says six turns with 0.6 to 1.0 s pauses in the middle of a sentence
and between digit groups (`"I would like to | change the address on my account."`). The fixture
has real silence between the parts and the fake STT returns one final per part, so the real
multilingual model and endpointing decide whether the turn ends in the pause. The caller counts a
cut-off when agent audio starts before its last sample; any cut-off fails the run (the main call
set too). Half of these turns end in digit strings and wait the unfinished-turn delay on purpose,
so this call set gates on p95 and cut-offs, not p50. Result with v2: 0 cut-offs in 48 turns, p95
1,427 ms. With the mapping alone (no digit-string rule) the model took the turn in the pause
after "my account number is four four one" in 8 of 8 calls.

```bash
uv run python -m tests.harness.bench.benchmark --mode live \
  --callset tests/harness/bench/callset_pauses.yaml
uv run python -m tests.harness.bench.synth --callset tests/harness/bench/callset_pauses.yaml
```

Real vendors are not part of live mode yet (no keys here). A real-vendor run needs
`DEEPGRAM_API_KEY`, `AZURE_OPENAI_API_KEY` with `AZURE_OPENAI_ENDPOINT` and
`AZURE_OPENAI_API_VERSION`, and `ELEVEN_API_KEY`, plus a switch in `bench/live.py` that dispatches
to the production `job_entry` without the fake registry; the fake STT's scripted transcripts then
give way to the real transcription of the fixtures, which are not intelligible speech, so a real
run also needs recorded or TTS-made fixtures.

## Script format

```yaml
name: greeting                 # used as the pytest id
config: {...}                  # deep-merged over the agent config (any AgentConfig field)
config_file: other.json        # optional, relative to scripts/
runtime:                       # RuntimeConfig fields; channel web by default
  channel: sip_outbound
  variables: {customer_name: Priya}
fakes:                         # fake vendor behaviour, all optional
  stt_final_ms: 150
  llm_ttft_ms: 280
  tts_ttfb_ms: 120
  ms_per_char: 55              # agent speech duration
  preemptive_generation: true
  vendors: {"tts/cartesia": {tts_ttfb_ms: 90}}
  default_reply: "Sure, I can help with that."
  greeting_reply: "..."        # generated opening when begin_message is empty
  rules:                       # first rule whose match is in the caller text wins
    - {match: order, reply: "...", tool: lookup_order, tool_ms: 400,
       transition: n_status, end_call: false}
api:
  end_call_on_post: 2          # the 2nd events post returns control.end_call
  end_call_reason: insufficient_credit
steps: [...]
```

Action steps (one key each, plus options):

| Step | Options | Effect |
|---|---|---|
| `say: text` | `duration_ms`, `pause_ms` (500), `interrupt_after_ms`, `segment_pause_ms` (800) | Caller speaks after the agent finishes, or N ms after the agent's audio starts. `"a \| b"` is said with `segment_pause_ms` of silence between the parts |
| `machine_greeting: text` | as `say` | Answering machine audio (voicemail detection) |
| `silence_s: N` | | Nobody speaks for N seconds |
| `dtmf: "1234#"` | `digit_interval_ms` (300) | Keypad digits |
| `override: {...}` | | `CallControl.apply_overrides` (llm, tts, stt, language) |
| `hangup: true` | | Caller leaves (`user_hangup`) |
| `wait_idle: true` | | Let the agent finish |

Expectations (checked when reached, after the agent's reply finishes):
`expect_agent_says` (transcript text, substring), `expect_agent_speaks` (text sent to TTS),
`expect_user_says`, `expect_tool`, `expect_transition`, `expect_end_reason` (`none` = still
active), `expect_within_ms` (last turn `e2e_ms`), `expect_interrupted`, `expect_turns`,
`expect_cutoffs` (turns committed in a mid-sentence pause so far),
`expect_event` / `expect_no_event` (field match on events; transcript item fields are flattened,
the item's own type is `item_type`), `expect_meter` (`kind`, `provider`, `model`, `min`),
`expect_background` (`kind`, `ref`, `gain`).

A script that ends with the call still active ends with the caller hanging up.

## Timing model

Per caller turn (research R4): preemptive generation runs the LLM and the TTS on the final
transcript, so `first_audio = max(eos + eou, eos + stt_final + llm_ttft + tts_ttfb)`; a turn with
a tool call runs the tool after the turn commits
(`max(eos + eou, eos + stt_final + llm_ttft) + tool + llm_ttft + tts_ttfb`). With the semantic
turn detector `eou = max(stt_final, VAD_MIN_SILENCE_S, min_endpointing_delay)`, or
`max_endpointing_delay` for an utterance it sees as unfinished (no closing punctuation, or a
trailing digit string); STT end of turn (Flux, AssemblyAI) uses
`max(stt_final, min_endpointing_delay)`. In a `"a | b"` turn, a part whose pause is shorter than
its `eou` continues the turn; a longer pause commits the turn (a cut-off) and the rest is a new
caller turn that barges in on the reply. Interruptions register after `min_interruption_duration`
of caller speech with at least `min_interruption_words`; the transcript keeps the played words.
