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

First baseline (2026-10-16, 20 x 6 calls, 4 concurrent, local `livekit-server` 1.13 in Docker
on macOS, fake vendors on the call set's profiles): caller `e2e_ms` p50 953 ms, p95 2,734 ms;
the worker stored p50 765 ms (183 ms under the caller); component medians end of turn 608 ms,
LLM first token 309 ms, TTS first audio 136 ms; no missed turns, no contract violations; about
3 minutes. The run fails the 800/1,500 ms budgets, for two reasons the timing model below does
not capture:

- The end-of-turn decision waits for Silero's end of speech (`min_silence_duration` 0.55 s by
  default) before the semantic model runs, so it is about 600 ms, not
  `max(stt_final, min_endpointing_delay)` = 400 ms.
- Turn 2 ("The account number is four four one nine.") always waits the full
  `max_endpointing_delay` (2.4 s at responsiveness 0.8): the semantic model reads a digit string
  as unfinished. That is the p95.

Both are turn-taking calibration questions (research R4), so the gate is reported, not tuned
here.

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
| `say: text` | `duration_ms`, `pause_ms` (500), `interrupt_after_ms` | Caller speaks after the agent finishes, or N ms after the agent's audio starts |
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
`expect_event` / `expect_no_event` (field match on events; transcript item fields are flattened,
the item's own type is `item_type`), `expect_meter` (`kind`, `provider`, `model`, `min`),
`expect_background` (`kind`, `ref`, `gain`).

A script that ends with the call still active ends with the caller hanging up.

## Timing model

Per caller turn: `first_audio = max(eos + eou, eos + stt_final + llm_ttft) + tool + tts_ttfb`,
with `eou = max(stt_final, min_endpointing_delay)`; the semantic turn detector waits
`max_endpointing_delay` for an utterance without closing punctuation, STT end of turn (Flux,
AssemblyAI) uses only the minimum. Interruptions register after `min_interruption_duration`
of caller speech with at least `min_interruption_words`; the transcript keeps the played words.
