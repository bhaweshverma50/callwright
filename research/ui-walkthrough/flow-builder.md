# Flow builder (`/agents/:id/flow`)

Live walkthrough on agent `GkFGZHpQ0GXgXoix9VRKc` ("Test Flow Agent", empty flow), 2026-10-16. Screens: `screens/flow-*`. All canvas edits were local; every write was blocked.

## 1. Routing around the builder

| URL | Result |
|---|---|
| `/agents/{id}` | redirects to `/agents/{id}/flow` (agent_type flow) |
| `/agents/{id}/edit` | "WRONG PAGE" guard: "This is a flow agent." / "The single-prompt editor doesn't apply here. Open the flow builder to edit nodes, voice, call behavior, and other settings for Test Flow Agent." Buttons "Open flow builder", "Back to agents". |
| `/agents/{id}/flow?configure=<tab>` | opens Global Settings on that tab (`model`, `voice`, `call-behavior`, `functions`, `advanced`, `knowledge-base`, `quality-checks`). The last tab used is remembered in the URL. |

GETs on load: `/agents/get-agent/{id}`, `/llms/get-llm/{llm_id}`, `/flows/by-agent/{id}`, `/flows/{flow_id}`, `/agents/{id}/versions/latest`, `/agents/{id}/versions?limit=50&offset=0`, `/tools/llm/{llm_id}`, `/knowledge-bases/agents/{id}`, `/evals/agents/{id}/config`, `/config/providers`, `/pricing/catalog`, voices.

## 2. Header bar

| Control | Type | Behaviour |
|---|---|---|
| "● FLOW" + flow name | inline text input, placeholder "Flow name…" | shows the agent name ("Test Flow Agent"); emptying it shows no error |
| ID chip | text + copy icon | copies the agent id |
| Version chip "v1 · 21m ago" (history icon) | button | opens a "Version history" panel: "1 version · newest first", row "v1 · current · 21m ago · 76f3823ccb… · agent created". With only the current version there are no Compare/Restore actions; close (X) button. |
| Global Settings (gear) | button | opens the settings modal (see `flow-global-settings.md`) |
| Save (disk icon) | primary button | validates the graph, then saves (see 7) |

## 3. Node palette ("NODES", left column)

9 HTML5-draggable cards (drag onto the canvas; click does nothing):

| Card title / subtitle | node_type | Default label on canvas | Canvas card subtitle |
|---|---|---|---|
| Start / Entry point | start | Start | "Agent speaks first" or "User speaks first" |
| Agent / AI agent with prompt | agent | New Agent | model id once overridden (e.g. "gpt-5.1"), else blank |
| Task / Collect structured data | task | Collect Data | "Data collection" |
| Condition / Branch based on intent | condition | Route | "Condition", then "LLM classify" |
| Say / Speak a message | say | Say | first words of the message |
| Extract / Extract data from call | extract_variable | Extract | "N fields" |
| API Call / Make an HTTP request | webhook | API Call | |
| Transfer / Transfer call to number | transfer | Transfer (label field is empty) | "Cold · No number", "Warm · 12345" |
| End / End conversation | end | End | |

Node ids are `node_<epoch ms>_<n>`. Every node has one target handle (left) and one source handle (right); End also renders both. A Condition node does not get one handle per category.

## 4. Canvas

- reactflow pane with dotted background. No minimap, no zoom +/- controls.
- Floating bottom toolbar with two icon buttons, aria-labels "Auto-layout" (magic wand) and "Fit to screen". No tooltips. Auto-layout arranges left to right.
- Right-click on node, edge or pane: no context menu. Double-click on the pane: nothing.
- Connect by dragging from a source handle to a target handle. Edge ids `edge_<epoch ms>`. Edges render as orthogonal (smoothstep) lines with a label pill showing the edge label.
- Delete: select a node and press Backspace (Delete key did not work in testing), or the "Delete Node" button in the panel. No confirm, deleting a node also removes its edges.
- Selecting a node or edge replaces the AI/Test tabs with a settings panel (back arrow + coloured dot + node label header). Clicking the empty pane returns to the AI/Test tabs.

## 5. Node settings panels (every field)

Common: **LABEL** text field at the top; **Delete Node** button (red outline) at the bottom. Multiline fields have an "Expand editor" icon that opens a modal editor titled with the field name and a "Done" button.

### Start
- Who speaks first? radio: **Agent speaks first** (default) / User speaks first.
- Agent first: "First message type" radio:
  - **Static message (no LLM)** (default) "Fast, deterministic. Spoken immediately via TTS." Reveals **Message \*** multiline, placeholder "Thank you for calling SecureShield Insurance. How can I help you today?", helper "Spoken immediately when the call starts. No LLM inference, fast and deterministic."
  - **LLM-generated from prompt** "Entry agent generates greeting from its instructions." Shows note "The entry agent will generate its greeting based on its own instructions. Make sure the entry agent's prompt includes greeting behavior."
- User first: replaces the above with **Optional greeting** multiline, helper "If set, this short message plays before waiting for the user. Leave empty for silence."

### Agent
- **Instructions \*** multiline, placeholder "You are a customer support specialist...", helper "System prompt for this agent node".
- **Begin Message** multiline, placeholder "Hi, I'm transferring you to our support team...", helper "Spoken when transferring to this agent".
- **Context Strategy** select: Inherit (full history) (default), Summarize (compressed), Reset (clean slate). Helper "How conversation history is passed when entering this agent".
- **LLM** group: Model select: Use agent default (default), GPT-5.1, GPT-5.2, GPT-5 Mini. Choosing a model reveals Provider select (Use agent default, Azure OpenAI, OpenAI) and a Temperature slider 0 to 2 step 0.05 (marks Precise / Balanced / Creative), shown at "0.70" but disabled with "Fixed at 1.0 for GPT-5 models".
- **VOICE** group: Provider select: Use agent default, ElevenLabs, Cartesia, Fish Audio. Choosing one reveals: Voice select ("Select a voice" + the provider's voices, 29 for ElevenLabs), Voice Model select ("Use provider default" + models), Speed slider 0.5 to 2 step 0.05 (Slow / Normal / Fast, default 1.00), Stability slider 0 to 1 step 0.05 (Variable / Balanced / Stable, default 0.90; this is `voice_temperature`).
- **SPEECH-TO-TEXT** group: Provider select: Use agent default, Deepgram, Sarvam AI, AssemblyAI. Choosing one reveals Model select ("Auto-select based on language" + that provider's models, e.g. Auto (recommended), Nova-3, Nova-2, Flux), helper "Leave empty for automatic selection", and **Language** select ("Use agent default" + 47 languages), helper "Affects STT model selection".
- No tools picker was shown (the agent has no functions; the node tool list probably appears only when the tool library is non-empty).

### Task (Collect Data)
- **Instructions \*** placeholder "Collect the user's full name and email address...", helper "Instructions for what data to collect".
- **Result Schema (JSON)** multiline, placeholder shows `{"type":"object","properties":{"name":{"type":"string"},"email":{"type":"string"}},"required":["name","email"]}`, helper "JSON Schema defining the data fields to collect". Live validation: "Invalid JSON".
- **Max Rounds** number, default 5, `min=1 max=20` (0 and 25 are accepted without a message), helper "Max conversation rounds before auto-completing".
- **Context Strategy** select (same 3 options).

### Condition (Route)
- **Condition Type** select: LLM Classification (default), Simple Comparison.
- LLM Classification: **Classification Instructions** (placeholder "Classify the user's intent based on conversation...", helper "How the LLM should classify the conversation into the categories below"); **Categories** chip input, placeholder "Add category...", Enter or + adds, duplicates ignored, no format check ("Bad Cat!" accepted). Helper "Each category becomes a separate output edge from this node".
- Simple Comparison: **Variable** (placeholder "e.g. task_result.intent"), **Operator** select: Equals (default), Contains, Regex, Exists; **Value** (placeholder "Expected value"). Value stays visible with Exists.

### Say
- **Message \*** placeholder "Hello! Please hold while I transfer you...", helper "Spoken without LLM inference, fast and deterministic".
- **Allow Interruptions** toggle, default ON, helper "If disabled, the message plays fully before continuing".

### Extract
- Intro: "Extracts data from conversation history silently, no user interaction. Runs a single LLM call to parse what was already said. Use {{variable_name}} in downstream node prompts."
- **Extraction Instructions** (optional) placeholder "Extract the user's name and what they're looking for from the conversation so far.", helper "Optional context for the LLM about what to look for".
- **Variables to Extract**: name input (placeholder "Variable name (e.g. customer_name)") + add button. A typed "Customer Name" becomes `{{customer_name}}`. Each row: type select String (text) / Number / Boolean (yes/no), description (placeholder "What this variable represents..."), delete. Footer "USE IN DOWNSTREAM NODES: {{customer_name}} (string)".

### API Call
- **URL \*** placeholder "https://api.example.com/endpoint" (no format check).
- **Method** select GET, POST (default), PUT, PATCH.
- **Timeout (ms)** default 5000.
- **Function Name** placeholder "e.g. check_availability", helper "Optional: if set, body is wrapped as {name, args}. Leave empty for raw body."
- **Headers (JSON)** placeholder `{"Content-Type": "application/json"}`; **Body Template (JSON)** placeholder `{}`. Both show "Invalid JSON".
- **Extract Variables from Response**: "Map JSON response fields to flow variables. Use dot notation for nested paths (e.g. data.slots[0].time)." "Add mapping" adds a row: variable_name, data.field.path, delete.
- **Speak during API call** toggle (default ON) with multiline (placeholder "Let me check that for you...", helper "Spoken while the API call is in progress"). OFF shows "API call executes silently, then continues to next node".
- **Simulation mock response** multiline, placeholder `{"slots": ["10am", "2pm"]} OR "Booking Success"`, helper "Returned verbatim when this API call fires during a simulation. JSON or plain text. Leave empty to surface a pre-flight warning before sims run."

### Transfer
- **Destination Number** placeholder "+1234567890" (no E.164 check; "12345" accepted and shown on the card).
- **Hold Message** placeholder "Please hold while I transfer your call.", helper "Spoken before the transfer begins".
- **Transfer Type** segmented buttons: Cold Transfer (default, "Transfers immediately, caller hears ringing") / Warm Transfer ("Calls supervisor first, briefs them, then connects").
- Warm reveals **Handoff Type** segmented Private (default, "Briefing happens in a private room, customer only hears hold") / Public ("Customer hears the briefing to supervisor"), and **Briefing Message** segmented Static Message (default; multiline placeholder "I have a customer who needs assistance with their account.", helper "This exact message will be spoken to the supervisor") / AI Generated (placeholder "Provide a concise summary of the customer's issue and what has been discussed...", helper "AI will generate a briefing from conversation history using this prompt").

### End
- **Goodbye Message** prefilled "Thank you for calling. Goodbye!", helper "Message spoken before ending the call".
- **Reason** text prefilled `call_completed`.

## 6. Edge settings panel

Header "Source → Target". Fields:
- **Edge Label (Tool Name)** placeholder "e.g. route_to_support", helper "Becomes the function tool name the LLM can call". Free text, no sanitising: "Route To Billing!" was accepted and rendered in the preview as `route_to_billing!`.
- **Handoff Condition** multiline, placeholder "When should the LLM take this path? e.g. 'When the user mentions billing, invoices, or payment issues'", helper "This text becomes the tool's description. The LLM reads it to decide when to call this handoff."
- **HOW THE LLM SEES THIS** live code preview: `@function_tool async def <label or transfer_to_...>(): """<condition or 'Transfer to next agent'>"""`.
- Edges leaving a Condition node hide Handoff Condition and show "ROUTING HANDLED BY THE CLASSIFICATION NODE: This path is chosen by the Route node's categories, so there's no handoff condition to set here. The edge label above is just the category name for this branch, you don't need to enter the routing rule twice."
- **Delete Edge** button.

## 7. Save and validation

Validation dialog "Couldn't save flow / N ISSUES NEED ATTENTION / OK". Messages observed:
- `"Route" needs at least 2 outgoing connections`
- `"Say" has no message text`
- `Edge from "Start" to "New Agent" has no label (required for tool naming)` (the Start edge also needs a label)
- `Edge from "Route" to "Say" has no label (required for tool naming)`

Not flagged as errors: an Agent node with empty instructions, a Task node with invalid JSON schema text, Transfer number "12345", unconnected Task/Extract nodes (warnings could not be observed because the save never succeeded).

Valid graph: Save fires two parallel blocked requests, then stops with "Couldn't save flow / Network Error":
- PATCH `/agents/update-agent/{id}`: `{agent_name, language, voice_id, voice_provider, voice_model, voice_temperature, voice_speed, volume, stt_provider, stt_model, noise_cancellation, end_call_after_silence_ms, max_call_duration_ms:null, ring_duration_ms:null, interruption_sensitivity, responsiveness, webhook_url, voicemail_option:{enabled, action}, dtmf_option:{enabled, timeout_ms, termination_key, digits_to_collect}, background_audio:{enabled}}`. Note: no `webhook_timeout_ms`, `pronunciation_dictionary` or `post_call_analysis_model` in this payload.
- PATCH `/llms/update-llm/{llm_id}`: `{model, provider, model_temperature, general_prompt, start_speaker}`.
- The `PUT /flows/{flow_id}` and `/activate` calls are never reached when these fail.

## 8. Right panel tabs (nothing selected)

**AI** tab: "AI Flow Assistant / Describe the flow you want to create or modify. For example: "Create a customer support agent that handles billing and tech issues"". Textarea placeholder "Describe the flow you want...", send button (disabled when empty). After sending, the message bubble shows, error "Network Error", and a "Clear chat" link. Blocked: POST `/flows/generate` with `{messages:[{role, content}], current_graph:{nodes:[{node_id, node_type, label, config:{first_message_type, start_speaker, context_strategy, llm_model, voice_provider, stt_provider, max_rounds, result_schema, type, operator, categories[], extraction_fields:[{name, type, description}], transfer_type, number, warm_transfer_config:{handoff_type, briefing_message_type, briefing_message}}}], edges:[{source_node_id, target_node_id, edge_label, edge_config:{handoff_condition}}]}}`. Positions are not sent.

**Test** tab: big mic button, "Test your agent / Click the microphone to start a test call". Click sends POST `/calldash/create` `{agent_id, dynamic_variables:{}}` (blocked) and shows "Failed to start call. Please try again." in red. No pre-call variables dialog appeared because the flow has no `{{vars}}`. The test uses the saved server config, not the unsaved canvas.

## 9. Records seen (GET)

- Flow: `{flow_id:"flow_<ms>", user_id, agent_id, flow_name:"Untitled Flow", flow_description, is_active:false, viewport:null, nodes:[], edges:[], created_at, updated_at}`. Note `is_active` (activation state) on the flow record.
- Agent (flow type) and version records saved in `data/agent-record-flow.json` and `data/agent-version-record.json`. Version rows carry `parent_version_id, archived_at, pinned, llm_model_id, voice_id, has_kb, node_count, content_hash, config` and the config adds `type` and `analysis_variables[]`.
