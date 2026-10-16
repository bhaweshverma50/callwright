# Feature Specification: Agent Builder

**Feature Branch**: `002-agent-builder`
**Created**: 2026-10-16
**Status**: Draft
**Input**: User description: "Single-prompt agents and the shared agent configuration (language model choice and temperature rules, prompt, greeting, who speaks first, dynamic variables, speech recognition, voice and noise cancellation chosen from a platform-provided catalog, call behaviour, advanced settings including webhook, voicemail, keypad input, background audio, pronunciation dictionary and analysis model), validation, an agent type chooser where the type cannot change later, agent list with search, duplicate and delete, versioning (snapshot on save, list, compare, publish, restore; calls reference the version they ran), templates grouped by industry, a live cost estimate, and AI-assisted prompt writing."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Create and configure a single-prompt agent (Priority: P1)

An operator clicks "New agent", picks the agent type (single-prompt or flow) on a chooser that
explains each and warns that the type cannot be changed later, and for single-prompt starts from
a blank agent. They fill in a name and language, choose a language model and temperature, write
the system prompt, set a greeting and who speaks first, and declare dynamic variables with
default values. They pick speech recognition, a voice (browsing and previewing voices from the
catalog), and noise cancellation; adjust call behaviour (silence timeout, maximum duration, ring
time, interruption sensitivity, responsiveness); and optionally set a webhook, voicemail
handling, keypad input, background audio, pronunciation fixes and an analysis model. They save,
and the agent exists with its first saved version.

**Why this priority**: Without a saved agent there is nothing to call, test, publish or measure.

**Independent Test**: From an empty workspace, create a single-prompt agent with a prompt that
uses `{{customer_name}}`, a default for that variable, a chosen voice and a webhook; save; reopen
it and confirm every value persisted and version 1 exists.

**Acceptance Scenarios**:

1. **Given** the type chooser, **When** the operator picks single-prompt and continues, **Then**
   they reach the template picker with "Start from scratch" first, and the chooser states that
   the type cannot be changed later.
2. **Given** a new blank agent, **When** the form opens, **Then** every field shows the platform
   default (for example language English (US), greeting set, agent speaks first, silence timeout
   30 s, maximum duration 10 minutes) and the defaults come from the platform catalog.
3. **Given** a model whose temperature is fixed by its provider, **When** the operator selects
   it, **Then** the temperature control shows the fixed value, is locked, and explains why.
4. **Given** a prompt containing `{{customer_name}}` and `{{order_id}}`, **When** the operator
   types it, **Then** both names appear in the variables list automatically, each with an empty
   default and a hint that calls must supply a value or a default is used.
5. **Given** an empty name, an empty prompt, no voice and a webhook URL `ftp://x`, **When** the
   operator saves, **Then** nothing is saved and one summary lists all four problems, each
   linked to its field.
6. **Given** a valid form, **When** the operator saves, **Then** the agent is stored, version 1
   is recorded, a confirmation appears, and the editor stays open on the saved agent.
7. **Given** unsaved changes, **When** the operator tries to leave the page, **Then** they are
   asked to stay or leave without saving.
8. **Given** a flow agent, **When** someone opens it in the single-prompt editor, **Then** they
   are told it is a flow agent and offered a link to the flow builder.

---

### User Story 2 - Find and manage agents (Priority: P1)

An operator sees all agents in the workspace as cards showing name, type badge, model, voice,
language, published version and last updated date. They search by name or agent ID, filter by
type, open an agent, duplicate it to start a variant, or delete one they no longer need.

**Why this priority**: Operators need to get back to their agents and keep the list usable once
there are more than a handful.

**Independent Test**: Create three agents, search for one by part of its name and another by its
full ID, duplicate one, delete one, and confirm the list reflects each action.

**Acceptance Scenarios**:

1. **Given** 25 agents, **When** the operator types part of a name, **Then** only matching agents
   show, and typing a full agent ID shows exactly that agent.
2. **Given** an agent, **When** the operator duplicates it, **Then** a new agent named
   "<name> (copy)" of the same type is created with the same draft configuration, its own
   version 1, no published version, and no copied history.
3. **Given** an agent, **When** the operator deletes it and confirms, **Then** it disappears from
   the list and search, and past calls that ran on it still show their configuration.
4. **Given** a workspace with no agents, **When** the list opens, **Then** an empty state invites
   the operator to create their first agent.

---

### User Story 3 - Track, compare, publish and restore versions (Priority: P2)

Every save records an immutable version with a number, timestamp, author and optional note. The
operator opens version history, compares any version with the current draft or with another
version (changes shown with readable field names such as "System prompt" and "Voice speed"),
publishes a version so live calls use it, and restores an older version as the new draft (as a
new version, never by rewriting history). Every call records which version it ran.

**Why this priority**: Safe iteration and quality measurement depend on knowing exactly what
configuration produced a call, and on rolling back quickly.

**Independent Test**: Save an agent three times with different prompts, compare versions 1 and 3,
publish version 2, restore version 1, and confirm history shows 4 versions with version 2 still
published.

**Acceptance Scenarios**:

1. **Given** an agent saved twice with different prompts, **When** the operator opens history,
   **Then** two versions show newest first, with number, time, author, note, and a "Published"
   badge on the published one if any.
2. **Given** two versions, **When** the operator compares them, **Then** each changed field shows
   its readable name, old value and new value; long text shows a line-by-line difference.
3. **Given** a save with no actual change, **When** the operator saves, **Then** no new version
   is created and they are told nothing changed.
4. **Given** version 2 is selected, **When** the operator publishes it, **Then** new live calls
   use version 2 and calls already in progress keep the version they started with.
5. **Given** version 1, **When** the operator restores it, **Then** the draft takes version 1's
   configuration, a new version records the restore ("restored from version 1"), and the
   published version is unchanged unless the operator chose "restore and publish".
6. **Given** an agent with no published version, **When** a live channel tries to use it,
   **Then** the call is refused because the agent is not published.
7. **Given** a version whose components are no longer offered or priced, **When** the operator
   tries to publish it, **Then** publishing is refused with the list of components to replace.

---

### User Story 4 - See what a minute will cost while configuring (Priority: P2)

While editing, a cost card shows the price per minute for speech recognition, language model,
voice, noise cancellation and the platform fee, with the total, and updates as soon as any of
those selections change. It explains that heavier calls can surcharge and warns when the prompt
is long enough that a typical call would likely exceed the included model usage. Model and voice
pickers show each option's price per minute.

**Why this priority**: Cost often decides the model and voice; seeing it at the point of choice
avoids surprises on the bill.

**Independent Test**: Switch the voice model between two options with different rates and confirm
the voice line and total change within a second; select a component with no price and confirm it
shows "price unavailable".

**Acceptance Scenarios**:

1. **Given** a blank agent with default selections, **When** the editor opens, **Then** the card
   shows five lines and a total that equals their sum.
2. **Given** the card, **When** the operator turns noise cancellation off, **Then** that line
   disappears and the total drops by its rate.
3. **Given** a component without a catalog price, **When** it is selected, **Then** its line says
   "price unavailable", the total is marked incomplete, and the agent can be saved but not
   published.
4. **Given** a system prompt of about 4,000 words, **When** the card updates, **Then** it shows a
   surcharge-risk notice that names the language model input allowance.

---

### User Story 5 - Start from an industry template (Priority: P2)

On the template picker the operator filters by industry (for example healthcare, banking,
insurance, retail, telecom, automotive, real estate, hospitality, general support), reads each
template's purpose, previews its prompt and greeting, and uses one. The new agent opens in the
editor pre-filled from the template, named after it, ready to adjust and save.

**Why this priority**: Templates cut time to a first working agent and show good prompt practice.

**Independent Test**: Filter by "Healthcare", preview a template, use it, and confirm the editor
opens with the template's prompt, greeting and language and the platform defaults for everything
the template does not set.

**Acceptance Scenarios**:

1. **Given** the picker, **When** it loads, **Then** "Start from scratch" comes first, then
   templates with industry filter chips headed by "All".
2. **Given** a template that names a voice no longer in the catalog, **When** it is used,
   **Then** the agent gets the default voice for its language and a notice says so.
3. **Given** a template, **When** it is used, **Then** the resulting agent's version 1 notes that
   it was created from that template.

---

### User Story 6 - Write the prompt with AI help (Priority: P3)

In the editor's assistant panel the operator describes the agent they want, or asks for changes
to the current prompt, in a chat. The assistant answers and, when it has a proposal, shows a
proposed prompt (and optionally a greeting and variables) with the differences from the current
prompt. "Apply" puts the proposal into the editor as an unsaved change that the operator can
undo or edit before saving.

**Why this priority**: Helpful for new operators, but every agent can be built without it.

**Independent Test**: Ask the assistant for "a receptionist for a dental clinic that books
appointments", apply the proposal, confirm the editor shows it as unsaved, undo, and confirm the
original prompt is back.

**Acceptance Scenarios**:

1. **Given** an existing prompt, **When** the operator asks "make it more concise", **Then** the
   proposal is based on the existing prompt and shown as a difference against it.
2. **Given** a proposal, **When** the operator applies it, **Then** the editor content changes but
   nothing is saved until the operator saves.
3. **Given** a workspace with no credit, **When** the operator sends a request, **Then** it is
   refused with a message to add funds.
4. **Given** a request, **When** it completes, **Then** its cost appears in the workspace usage
   under prompt generation.

---

### Edge Cases

- Two tabs edit the same agent: the second save is refused because the draft changed since it was
  opened; the operator can reload or open a comparison with the newer draft.
- The operator switches to a model with a narrower temperature range: the value is clamped to the
  new range and a notice says so.
- The prompt contains malformed placeholders such as `{{ name` or `{{1abc}}`: they are flagged as
  invalid variable names and not added to the variable list.
- A dynamic variable uses a built-in name (for example `current_time`): it is flagged as reserved
  and cannot have a default.
- A default is set for a variable that no longer appears in the prompt or greeting: it is kept
  and marked unused, so it can be removed deliberately.
- The voice catalog of a provider cannot be loaded: the picker says so with a retry, and the
  currently selected voice stays valid.
- A provider has exactly one speech recognition model: it is selected automatically and the model
  field is read-only.
- "Agent speaks first" with an empty greeting: allowed; the agent generates its opening line from
  the prompt, and the form says so.
- Voicemail "leave a message" with an empty message: blocked with a field error.
- Pronunciation dictionary rows with an empty word or replacement are dropped on save; duplicate
  words (ignoring case) are flagged.
- Webhook URL that points to a private or local network address: refused.
- Deleting an agent that a phone number, WhatsApp channel or outbound campaign uses: refused with
  the list of attachments to remove first.
- Restoring a version that references a deleted tool or knowledge base: the restore succeeds and
  the missing references are listed as problems to fix before publishing.
- A catalog component used by the published version is withdrawn: the agent list and editor show
  a warning; live calls on that version are refused until a replacement is published.
- Template content changes after agents were created from it: existing agents are unaffected.

## Requirements *(mandatory)*

### Functional Requirements

**Agent type and lifecycle**

- **FR-001**: System MUST offer two agent types, single-prompt and flow, on a chooser that
  describes each and states the type cannot be changed after creation.
- **FR-002**: System MUST make the agent type immutable after creation and reject any change.
- **FR-003**: System MUST give each agent a unique ID that the operator can copy from the editor.
- **FR-004**: System MUST keep, per agent, a draft configuration (what the editor shows) and an
  optional published version (what live channels use).

**Configuration content**

- **FR-005**: The configuration MUST include: language; language model provider, model and
  temperature; system prompt; greeting; who speaks first (agent or caller); dynamic variables
  with optional defaults; speech recognition provider and model; voice provider, model, voice,
  speed, expressiveness and volume; noise cancellation (an option or off); call behaviour
  (end after silence, maximum duration, ring time, interruption sensitivity, responsiveness);
  webhook address and timeout; voicemail detection and action; keypad input; background audio;
  pronunciation dictionary; analysis model; and the references other features attach (tools,
  knowledge bases, flow, quality checks).
- **FR-006**: System MUST serve the selectable options from a platform catalog: languages;
  language models with their temperature rules; speech recognition providers and models per
  language; voice providers, models and voices; noise cancellation options; built-in background
  sounds; and the default for each choice. Adding a provider or model to the catalog MUST NOT
  require changes to the configuration format.
- **FR-007**: For each model the catalog MUST state the allowed temperature range, step and
  default, or a fixed value; System MUST lock the control for fixed-temperature models and clamp
  values into range when the model changes.
- **FR-008**: System MUST extract dynamic variable names from `{{name}}` placeholders in the
  prompt and greeting, allow adding names by hand, accept names that start with a letter or
  underscore and contain only letters, digits and underscores (max 64 characters, max 50
  variables), and reject reserved built-in names (`call_id`, `channel`, `direction`,
  `user_number`, `agent_number`, `timezone`, `current_time`, `current_date`, `current_datetime`).
- **FR-009**: System MUST let the operator browse voices of the selected provider with search and
  filters (gender, language where the provider supports them), see each voice's description, and
  play a preview sample before choosing wherever the provider supplies one.
- **FR-010**: When the voice provider changes, System MUST switch the voice model to that
  provider's default and clear a voice that does not belong to the new provider.
- **FR-011**: When a speech recognition provider offers exactly one model for the language,
  System MUST select it automatically; "Auto" MUST be offered where the platform picks the best
  model for the language.
- **FR-012**: System MUST let the operator upload their own background audio files (common audio
  formats, max 10 MB each) in addition to the built-in sounds, and list and delete their uploads.

**Validation and saving**

- **FR-013**: System MUST validate on save and report every failing field in one response with a
  message per field. Rules: name required (1 to 80 characters); model required and in the catalog;
  prompt required (max 50,000 characters); greeting max 1,000 characters; voice and voice model
  required; silence timeout 10 to 300 seconds; maximum duration 30 to 3,600 seconds; ring time 0
  to 30 seconds; interruption sensitivity and responsiveness 0 to 1; voice speed 0.5 to 2;
  expressiveness 0 to 2; volume 0 to 2; webhook address an absolute secure web address not
  pointing to a private or local network; webhook timeout 1 to 30 seconds; voicemail message
  1 to 500 characters when "leave a message" is chosen; keypad digit count 1 to 99, pause 1 to
  10 seconds, end key one of 0 to 9, `#`, `*` or none; background volume 0 to 3; at most 200
  pronunciation entries.
- **FR-014**: System MUST separate blocking errors (prevent save) from publish blockers (allow
  save, prevent publish), the latter including unpriced or withdrawn catalog components and
  missing tool or knowledge base references.
- **FR-015**: System MUST refuse a save when the draft changed since the editor loaded it, and
  tell the operator how to recover.
- **FR-016**: System MUST warn, without blocking, about: variables without defaults, defaults for
  unused variables, and an empty greeting when the agent speaks first.
- **FR-017**: System MUST guard against leaving the editor with unsaved changes.

**Agent list**

- **FR-018**: System MUST list agents newest-updated first with name, type, model, voice,
  language, published version number, created and updated dates, with pagination.
- **FR-019**: System MUST support search by partial name (case-insensitive) or exact agent ID,
  and filtering by type.
- **FR-020**: System MUST duplicate an agent into a new agent of the same type with the draft
  configuration, name "<name> (copy)", its own first version and no published version.
- **FR-021**: System MUST delete agents after confirmation, keeping their versions so past calls
  keep their configuration; deletion MUST be refused while a live channel uses the agent.

**Versioning**

- **FR-022**: Every save that changes the configuration MUST record an immutable version with a
  per-agent sequential number, timestamp, author, optional note (max 500 characters) and the way it
  was created (save, restore, template, duplicate, publish from a flow, test snapshot).
- **FR-023**: A save with no change MUST NOT create a version.
- **FR-024**: System MUST list versions newest first and show any single version in full.
- **FR-025**: System MUST compare any two versions, or a version and the current draft, as a list
  of changed fields with readable names, old and new values; list items such as variables and
  pronunciation entries MUST be matched by their key, not their position.
- **FR-026**: System MUST let the operator publish any version without publishing errors; only
  one version per agent is published at a time; new live calls use it within 10 seconds.
- **FR-027**: System MUST restore a version by copying its configuration into the draft and
  recording a new version that names the source, with an option to publish in the same step.
- **FR-028**: Versions MUST be self-contained: they capture the tool definitions attached at the
  time, so later edits to a tool do not change what an old version does.
- **FR-029**: Every call MUST reference the version it ran; test calls on an unsaved-to-version
  draft MUST get a version snapshot (reused if identical) without publishing it.

**Cost estimate**

- **FR-030**: The editor MUST show a per-minute cost estimate with a line per component (speech
  recognition, language model, voice, noise cancellation when on, platform fee) and the total,
  using the platform pricing catalog and rules from feature 001.
- **FR-031**: Model, voice model and speech recognition pickers MUST show each option's price per
  minute.
- **FR-032**: The estimate MUST mark unpriced components as "price unavailable" and show a
  surcharge-risk notice when the prompt size suggests typical calls will exceed the included
  language model input allowance.

**Templates**

- **FR-033**: System MUST offer platform-curated templates, each with name, industry category,
  description, icon, and partial configuration (at least prompt, greeting, language, who speaks
  first), filterable by category and searchable by name.
- **FR-034**: Using a template MUST create a single-prompt agent whose draft is the platform
  defaults overlaid with the template's values, named after the template, recorded as version 1
  with the template noted, and open it in the editor.

**AI prompt assistant**

- **FR-035**: System MUST provide a chat assistant that, given the conversation and the current
  prompt (if any), replies and optionally proposes a prompt, greeting and variable list.
- **FR-036**: Applying a proposal MUST only change the editor contents (undoable) and never save.
- **FR-037**: Each assistant request MUST be charged to the workspace as prompt generation usage
  and refused when the balance is at or below zero; requests MUST be limited to 20 per minute per
  workspace.

### Key Entities

- **Agent**: a named voice agent in a workspace; type (single-prompt or flow, fixed), language,
  draft configuration, the version the draft was last saved as, optional published version,
  created and updated times, deleted flag.
- **Agent Configuration**: plain data describing everything the runtime needs for one agent
  (see FR-005), with a format version so older versions remain readable.
- **Agent Version**: an immutable snapshot of a configuration with number, note, source, author,
  creation time, content fingerprint, and publish problems found at save time.
- **Template**: platform-curated starting configuration with industry category, description and
  icon.
- **Catalog**: platform-provided list of languages, models, voices, speech recognition and noise
  cancellation options with defaults and rules.
- **Background Audio Upload**: an audio file a workspace uploaded for use as ambience.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A first-time operator creates and saves a working agent from a template in under
  3 minutes.
- **SC-002**: The cost estimate reflects any change to a priced selection within 1 second.
- **SC-003**: For 100% of calls, the referenced version reproduces the exact configuration the
  call ran with, including after the agent or its tools are edited or deleted.
- **SC-004**: A failed save lists every rule violation present in the form at once in 100% of
  tested cases (no "fix one, discover the next").
- **SC-005**: With 1,000 agents in a workspace, list search returns results within 1 second.
- **SC-006**: After publishing a version, new live calls use it within 10 seconds; calls already
  in progress are unaffected.
- **SC-007**: 95% of assistant requests return within 30 seconds.
- **SC-008**: Restoring a previous version takes no more than 3 clicks from the editor.

## Assumptions

- Feature 001 provides accounts, workspaces, the pricing catalog and rules, the quote
  capability, and feature charging; this feature only reads prices.
- Flow agents (004) reuse this feature's agent record, configuration format, versions and list;
  the flow canvas, flow validation and flow publishing are out of scope here.
- Tools and knowledge bases (005) attach through references in the configuration; quality checks
  and analysis variables (007) likewise. This feature stores, versions and compares those
  references but does not edit their content.
- Test calls and the test panel (003) consume versions from this feature; the live call itself is
  out of scope.
- One user per workspace in v1, so there are no per-agent permissions; "author" is the user who
  saved.
- Defaults (Callwright choices): language English (US); greeting "Hi, thanks for calling. How can
  I help you today?"; agent speaks first; silence timeout 30 s; maximum duration 600 s; ring time
  5 s; interruption sensitivity 0.9; responsiveness 0.8; voice speed 1.0, expressiveness 0.9,
  volume 1.0; webhook timeout 3 s; voicemail detection off (action hang up); keypad input off
  (pause 2.5 s, end key `#`, 10 digits); background audio off (volume 0.8); analysis model empty
  meaning "same as the agent's model". Templates use the same defaults unless they set a value.
- Templates are authored by the platform team; workspaces cannot publish their own templates in v1.
- Voice cloning and custom voice uploads are out of scope.
- The assistant's chat history is kept only in the open editor session, not stored.
- Version history is kept for the life of the agent (no pruning in v1).
