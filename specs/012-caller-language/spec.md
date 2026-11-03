# Feature specification: caller language (012)

Created: 2026-11-03. Status: implemented on branch `w8-language`.

## Why
Callers in India and elsewhere often prefer to talk in their own language. An English agent could
only keep answering in English, with English speech recognition, and the next call started over.
The default voice also sounded flat (Flash v2.5, stability 0.55, no style).

## User stories
1. **Caller switches language (P1).** The caller asks "can we speak Hindi?" (or clearly speaks
   Hindi). The agent switches speech recognition, its replies and its voice to Hindi for the rest
   of the call and confirms the switch in Hindi.
2. **Caller is remembered (P1).** On phone calls the choice is saved for the caller's number; the
   next call from or to that number (callbacks included) starts in Hindi, with a greeting that
   means the same as the agent's fixed greeting.
3. **Operator controls and sees it (P2).** The agent editor turns switching on or off and can limit
   the languages; the call view shows the language used, each switch with its time, and the
   caller's saved language with a way to forget it.
4. **More natural default voice (P1).** New agents use ElevenLabs Multilingual v2 with the
   expressive delivery (stability 0.35, similarity 0.75, style 0.3, speaker boost).

## Requirements
- FR-001: `advanced.language_switching: {enabled (default true), languages (empty = all)}` in the
  agent config (002). Older versions read as enabled with every language. Unknown or repeated
  codes are errors; a code the agent's speech recognition and voice cannot handle is a warning.
- FR-002: A language is offered when the agent's speech recognition provider has a model for it
  (the agent's model, else Auto's pick, else the provider's first model covering it) and its voice
  speaks it (the agent's model, else that model's multilingual version). One code per base
  language when the list is empty; the agent's own language first; never other variants of it.
- FR-003: The claim's `RuntimeConfig` (003) carries `language_options` (empty when switching is
  off or there is nothing to switch to; flow agents included since 2026-11-03) and, on phone calls, `caller_language` when the saved
  language is offered and differs from the agent's.
- FR-004: Single-prompt agents with options get a built-in `set_language` tool whose `language`
  enum is the offered codes, and an instruction saying when to use it and to confirm in the new
  language. A switch stages speech recognition and voice for the next turn boundary, adds "reply
  only in <language>" to the instructions at once, records a `tool_call` event and a
  `language_switched` system item, and reports `POST /v1/internal/calls/{id}/language`.
- FR-005: The API records every switch on the call and saves the language per workspace and E.164
  number only for live phone calls (the caller inbound, the dialled number outbound). Browser test
  calls, WhatsApp and simulations never save.
- FR-006: A call that starts in the caller's language uses that language's speech recognition and
  voice models, the reply-language instruction and a greeting with the same meaning as the fixed
  greeting (translated by the agent's model while the session starts and the phone rings, then
  pre-synthesised; the model writes it live if the translation is not back in 4 s).
- FR-007: Text simulations (008) offer `set_language` from the spec's `language_options`; it
  switches the instructions only and never reaches the API.
- FR-008: Public `GET /v1/caller-preferences`, `DELETE /v1/caller-preferences/{id}`,
  `GET /v1/calls/{id}/language`. Preferences and call languages are tenant data under row-level
  security.
- FR-009: New agents and the seed templates default to `eleven_multilingual_v2` ($0.09/min);
  existing agents keep their saved model. Expressiveness 0.9 (the default) maps to stability 0.35
  and style 0.3 with speaker boost; style is sent only to Multilingual v2.

## Out of scope
Switching the speech recognition provider, per-caller voices,
detecting the language from audio before the model asks, WhatsApp preferences.
