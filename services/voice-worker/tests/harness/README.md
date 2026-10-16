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
