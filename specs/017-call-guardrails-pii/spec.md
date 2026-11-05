# Feature specification: call guardrails and caller data protection (017)

Created: 2026-11-05. Status: Draft.

## Why
What an agent says reaches the caller before anyone can check it, and what the caller says is
kept everywhere.

- **Nothing checks a reply before it is spoken.** Every agent gets platform instructions such as
  "never promise something you cannot do", and the templates add an identity rule. The model can
  still say "your refund is done" when no tool ran, quote an amount no tool returned, or read a
  card number back aloud. Evaluators (007) can catch some of this after the call, when the caller
  has already heard it.
- **Caller data lands in logs, transcripts and recordings.** Logs hide secrets such as API keys
  and bearer tokens, but nothing hides caller data. Stored transcripts, tool arguments and
  results keep card numbers and security codes as spoken or keyed. When recording is on, it
  covers the whole call, card entry included.
- **What is written and what is spoken are mixed up.** The pronunciation dictionary (up to 200
  whole-word replacements per agent) changes only the speech, and the transcript keeps the
  original words. That part works. But numbers, amounts, dates and reference codes are left to
  the voice vendor to read, stage directions such as "*laughs*" can be spoken, and a builder
  cannot hear an entry before saving it.
- **Clips carry dead time.** Each synthesised clip can start and end with silence, which delays
  the first audio and leaves gaps between sentences.
- **Disclosures can be talked over.** A fixed greeting already cannot be interrupted, because it
  often carries the recording or AI notice. A generated opening line can be interrupted, an agent
  where the caller speaks first has no point where a disclosure is guaranteed, and a flow's Say
  step can be interrupted unless the builder turns that off.

This feature adds a per-sentence screen on every reply with a small time budget, masks caller
data before it is stored or logged, pauses the recording during card entry, separates spoken
text from display text, trims silence from synthesised audio, adds audition and suggestions to
the pronunciation dictionary, and makes the opening disclosure uninterruptible on every call.

## User scenarios and testing

### User story 1: the agent never says what it cannot back up (P1)
A caller asks for a refund. The model drafts "Your refund of $45.50 has been processed." No
refund tool ran on this call, so that sentence is held. The caller hears "Let me just check that
for you." instead, the model is told why, and it writes a correct reply ("I can't process the
refund on this call, but I can ..."). The same screen stops the agent from naming a figure no
tool, document or caller gave, from reading back a card number, security code or social security
number, and from claiming to be human when asked. Sentences that pass are spoken at once.

**Why this priority**: a false "done" or a wrong amount is the costliest thing an agent can say,
and reading a card number aloud is a compliance breach.

**Independent test**: replay a set of scripted model replies through a test call: the false
action claims, the invented figures and every card read-back are held and replaced by the holding
line, the correct sentences are spoken unchanged, and each hold appears in the call timeline.

**Acceptance scenarios**:
1. **Given** no booking tool has succeeded on the call, **When** the model writes "I've booked
   you for Tuesday at 3", **Then** that sentence is not spoken, the holding line is, and the
   model gets one chance to correct its reply.
2. **Given** the booking tool returned success for Tuesday at 3 pm, **When** the model writes
   "You're booked for Tuesday at 3", **Then** it is spoken without delay.
3. **Given** a tool returned a balance of 1,250.00, **When** the model says "your balance is
   1,520", **Then** the figure rule fires (held in block mode, recorded only in log mode).
4. **Given** any agent, **When** the model writes a sentence containing a card number that
   passes the card checksum, **Then** the sentence is always held, whatever the agent's settings.
5. **Given** the caller asked "am I talking to a real person?", **When** the model replies "Yes,
   I'm a real person", **Then** the sentence is held and the corrected reply says it is an AI
   assistant.
6. **Given** the corrected reply fails the screen again, **When** it is checked, **Then** the
   agent says a safe line ("I'm not able to confirm that right now.") and the turn ends normally.
7. **Given** a builder switches the figure rule to "log only" for an agent, **When** it fires,
   **Then** the sentence is spoken and the hit is recorded.

---

### User story 2: caller data stays out of logs and stored records (P1)
A caller gives a card number, security code and phone number. Logs and traces never contain the
caller's words, the agent's replies or a full phone number: content shows only as its kind,
length and a short hash, and phone numbers show only the last 4 digits. Stored transcripts, tool
records, exports and webhooks show the card as "card ending 1234" and the security code as
"[security code]". While the caller enters the card, by voice or keypad, the stored recording is
silent.

**Why this priority**: caller data in logs and recordings is the largest compliance exposure the
platform has, and it grows with every call.

**Independent test**: place 10 test calls where the caller speaks a card number and 10 where the
caller keys it; afterwards, a search of the logs, traces, transcripts, tool records, exports,
webhook payloads and recording audio finds no full card number, no security code and no full
phone number in the logs.

**Acceptance scenarios**:
1. **Given** a call from +91 98765 43210, **When** any log line or trace mentions the caller,
   **Then** it shows the number as ending 3210 and nothing more.
2. **Given** a caller says their card number, **When** the transcript is stored, **Then** the
   turn reads "card ending 1234" and the full number is not stored anywhere.
3. **Given** recording is on and a flow step is marked as sensitive entry, **When** the caller
   keys the card number, **Then** the recording is silent from the start of the step until it
   ends, and the playback timeline shows "Recording paused: card entry".
4. **Given** recording is on and no step is marked, **When** the caller starts speaking a
   card-like number, **Then** the recording is silenced from the start of that caller turn until
   the entry ends, including the digits already spoken in that turn.
5. **Given** a workspace adds a custom pattern for its customer IDs, **When** a caller says one,
   **Then** it is masked in stored transcripts with the workspace's label.

---

### User story 3: required disclosures are always heard in full (P2)
A builder sets a disclosure: "This call is recorded, and I'm a virtual assistant." On every call
it is spoken in full before or as part of the opening, and the caller cannot talk over it. If the
caller speaks during it, their words are kept and answered right after. The call record shows
that the disclosure was played.

**Why this priority**: some industries require the notice; today it is guaranteed only when the
agent opens with a fixed greeting.

**Independent test**: for three agents (fixed greeting, generated opening, caller speaks first),
place calls where the caller talks during the opening; each call plays the whole disclosure,
answers the caller afterwards, and records "disclosure played".

**Acceptance scenarios**:
1. **Given** an agent with a generated opening and a disclosure, **When** the call connects,
   **Then** the disclosure is spoken first and cannot be interrupted, and the generated opening
   follows.
2. **Given** an agent where the caller speaks first, **When** the caller says "Hi, I need help
   with my bill", **Then** the agent's first reply starts with the disclosure and then answers.
3. **Given** the caller's saved language is Hindi (012), **When** the call starts, **Then** the
   disclosure is spoken in Hindi, or in the original language if the translation is not ready
   in time.
4. **Given** the caller hangs up during the disclosure, **When** the call ends, **Then** the call
   records "disclosure not completed".

---

### User story 4: the agent says numbers, codes and names correctly (P2)
The model writes "Your order AB-1234 ships on 12/11 for $45.50." The transcript and the live view
show exactly that. The caller hears "Your order A B, one two three four, ships on the twelfth of
November for forty-five dollars and fifty cents." Stage directions, formatting and emoji are
never spoken. In the pronunciation dictionary the builder clicks play on an entry and hears it in
the agent's voice, and can accept entries the AI suggests from the prompt and knowledge base
(brand names, acronyms, product codes).

**Why this priority**: misread numbers and names make a good agent sound broken, and the builder
has no way to check them before going live.

**Independent test**: play 100 sentences with amounts, dates, times, phone numbers and codes
through the agent's voice; at least 95 are spoken correctly, none speaks a stage direction, and
the transcript shows the written form.

**Acceptance scenarios**:
1. **Given** a dictionary entry "Callwright" said as "call right", **When** the builder clicks
   play, **Then** a sample sentence is spoken in the agent's current voice within 2 seconds, with
   the replacement applied.
2. **Given** a prompt that mentions "UPI" and "Zyvo Pro", **When** the builder asks for
   suggestions, **Then** each suggestion shows the term, a proposed reading and why it was
   suggested, and nothing is added until the builder accepts it.
3. **Given** the model writes "*laughs* Sure!", **When** it is spoken, **Then** the caller hears
   "Sure!" and the transcript shows "Sure!".
4. **Given** a WhatsApp conversation (010), **When** the agent replies, **Then** the written form
   is sent and nothing is verbalised.

---

### User story 5: no dead air at the start and between sentences (P3)
Synthesised clips start and stop on speech, not on padding, so the caller hears the agent sooner
and sentences flow without gaps.

**Why this priority**: a small but free latency gain; it builds on the voice path, not on safety.

**Independent test**: on the benchmark call set, first-audio p50 drops by at least 100 ms with
trimming on, and a listening check of 100 clips finds no clipped word starts.

**Acceptance scenarios**:
1. **Given** a clip with 300 ms of leading silence, **When** it is played, **Then** at most 50 ms
   of leading silence is left.
2. **Given** a sentence that starts with a soft sound ("f", "h", "s"), **When** it is trimmed,
   **Then** the sound is kept whole.

### Edge cases
- The model writes an action claim in the future or as an offer ("I can book that"): it passes.
- The model repeats a figure the caller said ("you said 4,000?"): it passes, because the caller's
  words count as a source.
- Today's date and time, counting numbers 1 to 10, and figures from the agent's own prompt or
  dynamic variables are allowed sources.
- A reply arrives as one long sentence: the screen splits on clause boundaries after 30 words so
  that speech does not wait for the whole reply.
- The AI claim check (for unclear cases) does not answer within 1 second: the rule's mode
  decides (hold in block mode, speak in log mode).
- The screen itself fails or takes longer than 100 ms on a sentence: the sentence is spoken (fail
  open), except for the card, security code and social security number rule, which holds it (fail
  closed); each failure is counted.
- A caller speaks a 16-digit number that fails the card checksum: it is not masked as a card,
  unless a workspace pattern matches it.
- Card entry runs longer than 60 seconds with no end signal: the recording pause ends after 60
  seconds and the call records that it timed out.
- A caller interrupts a held sentence's holding line: normal barge-in applies to the holding line,
  but never to a disclosure.
- The disclosure is longer than 40 words: the editor refuses to save it.
- Masking runs before the data is stored; data stored before this feature is not changed.
- A tool needs the full card number to work: it gets it during the call; only the stored copy is
  masked.
- Languages other than English: the card, security code, social security number, figure and AI
  denial rules work in every language; the action-claim word lists start with English, and other
  languages rely on the AI claim check.

## Requirements

### Functional requirements

Per-sentence reply screen
- **FR-001**: Every agent reply MUST be checked one sentence at a time before it is spoken. A
  sentence that passes MUST be spoken without waiting for the rest of the reply. Sentences longer
  than 30 words MUST be split on clause boundaries.
- **FR-002**: Rule "unbacked action": a sentence that states an action as done (refunded, booked,
  cancelled, scheduled, transferred, sent, updated, paid, reset, and similar) MUST fire when no
  tool performing that action succeeded earlier in the call. Offers and future statements MUST
  pass.
- **FR-003**: Rule "unsupported figure": a sentence with an amount, date, time, percentage,
  quantity or reference number MUST fire when that figure, after normalising its format, appears
  in none of: tool results on this call, knowledge passages retrieved on this call, the caller's
  words, the agent's prompt, greeting and dynamic variables, or the current date and time.
  Counting numbers 1 to 10 MUST be exempt.
- **FR-004**: Rule "sensitive read-back": a sentence MUST fire when it contains a card number
  that passes the card checksum (13 to 19 digits, any grouping), a 3- or 4-digit security code in
  a card context, or a US social security number pattern.
- **FR-005**: Rule "AI denial": after a caller asks whether they are talking to a person or a
  machine, a sentence that claims the agent is human MUST fire.
- **FR-006**: Each rule MUST have a mode per agent: block, log only or off. Defaults: sensitive
  read-back block, AI denial block, unbacked action block, unsupported figure log only. Sensitive
  read-back and AI denial MUST NOT be set below block.
- **FR-007**: Unclear cases for the action and figure rules MUST go to an AI claim check limited
  to 1 second. If it confirms the problem or does not answer in time, the rule's mode applies.
- **FR-008**: A held sentence MUST NOT be spoken. The agent MUST say a holding line instead, and
  the model MUST receive a private note naming the rule and get one chance to correct its reply.
  If the correction also fails, the agent MUST say a safe line and the turn MUST end. An agent
  MUST say at most 1 holding line per turn.
- **FR-009**: Holding lines and the safe line MUST have defaults in every language the agent
  offers, and the builder MUST be able to edit them.
- **FR-010**: Each hit MUST be recorded as a call event (rule, mode, action taken, the sentence
  masked per FR-016, time taken), shown in the call timeline, and counted per rule and agent.
- **FR-011**: Platform instructions MUST be added to every agent: say it is an AI assistant when
  asked, never state an action as done without the tool that does it, never read back card data.
  Agents MUST NOT be able to remove them.
- **FR-012**: Text the builder wrote (fixed greeting, Say steps, holding lines, disclosure) MUST
  skip the action and figure rules.

Time budget
- **FR-013**: The rule checks other than the AI claim check MUST add at most 30 ms per turn at
  the 95th percentile, with a target of 15 to 25 ms. This time MUST be recorded as its own
  latency part (015).
- **FR-014**: If the screen errors or takes longer than 100 ms on a sentence, the sentence MUST be
  spoken, except for the sensitive read-back rule, which MUST hold it. Each such failure MUST be
  counted and MUST feed an alert rule (014).

Caller data masking
- **FR-015**: Logs and traces from the API, the jobs worker and the voice worker MUST show phone
  numbers only by their last 4 digits and email addresses only by their domain. Caller words,
  agent replies, tool arguments and tool results MUST appear only as kind, character length and
  a 12-character hash.
- **FR-016**: Before anything is stored, card numbers MUST be replaced by "card ending" plus
  their last 4 digits, security codes by "[security code]" and social security numbers by "[SSN
  ending]" plus their last 4 digits. This applies to transcripts, call events, stored tool
  arguments and results, analysis results, exports, customer webhooks, evaluator inputs,
  long-call summaries (015) and live call views.
- **FR-017**: Workspaces MUST be able to add their own masking patterns, each with a label and a
  test box that shows what a sample text becomes. Workspace patterns are tenant data under
  row-level security.
- **FR-018**: Call records MUST keep the full caller and dialled numbers, because callbacks
  (011), caller language (012) and outbound rules (010) need them. FR-015 applies to logs,
  traces and alerts.

Recording pause during card entry
- **FR-019**: When card entry starts, the stored recording MUST be silent on both the caller and
  agent sides until it ends. Entry starts when a flow step marked "sensitive entry" begins, when
  a tool parameter marked sensitive is being collected, or when the caller starts speaking or
  keying a card-like number; in the last case the silence MUST cover that whole caller turn.
- **FR-020**: Entry ends when the marked step is left, the tool runs, or 60 seconds pass. Keypad
  tones during entry MUST be silenced too.
- **FR-021**: The playback timeline MUST show each paused span as "Recording paused: card entry"
  with its length, and the call MUST record why each pause ended.

Spoken text and display text
- **FR-022**: Each agent sentence MUST have a display form (transcript, live view, text channels)
  and a spoken form (sent to the voice). The spoken form MUST drop stage directions, formatting
  and emoji, shorten web addresses to their domain, and say numbers, amounts, dates, times, phone
  numbers and reference codes in the call's language (codes letter by letter and digits in
  groups). The display form MUST keep the written text without stage directions.
- **FR-023**: The pronunciation dictionary MUST apply after numbers and codes are verbalised, and
  an entry MUST win over the default reading.
- **FR-024**: Text channels MUST receive only the display form.

Pronunciation dictionary
- **FR-025**: Each entry MUST have a play button that speaks a sample sentence with the agent's
  current voice, with and without the entry. The builder MUST also be able to play the greeting
  and the disclosure as they will be spoken.
- **FR-026**: Each entry MUST have a kind: "say as" (replacement text), "spell out" (letter by
  letter) or "say as digits", and MAY be limited to one language (012). The limit stays at 200
  entries per agent.
- **FR-027**: The builder MUST be able to ask for suggestions. The AI MUST draft entries from the
  agent's prompt, greeting, knowledge base titles and tool names (brand names, acronyms, codes,
  unusual names), each with its reason. Nothing MUST be added until the builder accepts it.
- **FR-028**: Audition clips MUST be cached per voice and text so replays are free, and MUST be
  limited to 100 new clips per workspace per day.

Silence trimming
- **FR-029**: Each synthesised clip MUST keep at most 50 ms of leading silence and at most 150 ms
  of trailing silence, with a short fade so word starts and ends are never cut.
- **FR-030**: Where the voice vendor offers raw audio at the call's sample rate, it MUST be
  requested, to skip decoding.

Uninterruptible opening and disclosure
- **FR-031**: An agent MUST be able to set a required disclosure of up to 40 words. It MUST be
  spoken in full and MUST NOT be interruptible: before or as part of a fixed greeting, before a
  generated opening, and at the start of the first reply when the caller speaks first.
- **FR-032**: A fixed greeting MUST stay uninterruptible as today. A generated opening's first
  sentence MUST be uninterruptible too, for at most 15 seconds; after that, normal barge-in
  applies.
- **FR-033**: Caller speech during an uninterruptible line MUST be transcribed and answered right
  after the line ends.
- **FR-034**: In the caller's saved language (012), the disclosure MUST be spoken in that
  language, translated while the call starts like the greeting. If the translation is not ready,
  the original text MUST be spoken.
- **FR-035**: Each call MUST record whether the disclosure was played in full, and when. The call
  list MUST allow filtering on "disclosure not completed".
- **FR-036**: In flow agents, a Say step marked as the disclosure MUST be uninterruptible and MUST
  count as the call's disclosure.

### Key entities
- **Guardrail setting**: agent, rule, mode (block, log only, off), locked or not.
- **Guardrail hit**: call, turn, rule, mode, action taken, masked sentence, time taken, claim
  check result.
- **Holding lines**: agent, language, holding line, safe line.
- **Masking pattern**: workspace, label, pattern, enabled, built in or custom.
- **Recording pause**: call, start, end, trigger (marked step, sensitive tool parameter,
  detected number), end reason.
- **Pronunciation entry**: word, kind, replacement, language (optional), source (builder or
  accepted suggestion).
- **Pronunciation suggestion**: agent, term, proposed reading, reason, status (open, accepted,
  dismissed).
- **Required disclosure**: agent, text, translations.
- **Disclosure record**: call, played in full or not, start and end time, language.

## Success criteria

- **SC-001**: On a red-team set of at least 200 scripted replies with false action claims,
  invented figures and sensitive read-backs, at least 95% of violations in block mode are never
  heard by the caller, and 100% of card, security code and social security number read-backs are
  held.
- **SC-002**: On at least 500 ordinary replies taken from real call transcripts, no more than 2%
  of sentences are held by mistake.
- **SC-003**: The screen adds at most 30 ms per turn at the 95th percentile, and turn latency p50
  rises by no more than 50 ms with the screen on.
- **SC-004**: A scan of 7 days of logs and traces finds no full phone number, no caller or agent
  sentence and no card number.
- **SC-005**: Across 20 test calls with spoken and keyed card numbers, stored transcripts, tool
  records, exports, webhooks and recordings contain no recoverable card number or security code.
- **SC-006**: In a listening test of 100 sentences with numbers, amounts, dates, times and codes,
  at least 95 are spoken correctly, and no stage direction is spoken.
- **SC-007**: A builder can add an entry and hear it in the agent's voice in under 1 minute; the
  first play starts within 2 seconds.
- **SC-008**: Silence trimming lowers first-audio p50 by at least 100 ms on the benchmark call
  set, with no clipped word starts in a listening check of 100 clips.
- **SC-009**: For agents with a required disclosure, 100% of calls that last longer than the
  disclosure record it as played in full before any other agent speech.

## Assumptions
- The action-claim word list starts with English; other languages use the AI claim check for that
  rule until their lists exist.
- The built-in national ID pattern is the US social security number; other national IDs (for
  example Indian ones) are added as workspace patterns.
- Callwright has no payment tool of its own; card entry happens through keypad collection, a
  flow step or a customer's own tool, so the builder marks the step or the tool parameter as
  sensitive. A new "sensitive" mark on tool parameters is part of this feature.
- During the call the model still sees what the caller said, so a tool can receive the card
  number; only stored and logged copies are masked.
- Masking applies to new data only. Cleaning data stored before this feature is a separate task.
- The AI claim check uses a small, fast model already available to the platform.
- Audition clips are charged at the voice rate against the workspace's usage, within the daily
  limit.
- Flow agents (004) get the screen, masking, disclosure and spoken-form rules the same way as
  single-prompt agents.

## Out of scope
- Swapping card numbers for stored tokens (a token vault) and payment card industry
  certification.
- Masking what is sent to AI vendors during the call.
- Showing or hiding full phone numbers by user role.
- Live human review of held sentences.
- Changing data stored before this feature.
