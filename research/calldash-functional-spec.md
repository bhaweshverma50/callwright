# CallDash: Functional Spec (reverse-engineered from the public web bundle)

**Source and method**
- I read the minified Vite/React/MUI bundle (85 chunks) without running it.
- Everything here comes from string literals, API client objects, React state defaults and the code that builds request payloads.
- This document covers behaviour and data contracts only. No code was copied.
- Field names are exactly as they go over the wire.
- Anything the server decides and the bundle doesn't show is marked **(server)**.

**Conventions**
- `ms` means milliseconds.
- Most IDs are nanoid strings generated in the browser before the POST: `agent_id`, `llm_id`, `tool_id`, `variable_id`.
- Auth: the axios client sends the Firebase ID token as a Bearer token.
- The token is refreshed when the tab regains visibility. If the refresh fails, the user sees "Session expired. Please log in again."
- Base URLs:
  - API: `https://calldash-api-prod.azurewebsites.net/api`
  - WebSocket: `VITE_WS_URL=wss://calldash-api-prod.azurewebsites.net`

The Retell AI comparison is my inference. Many agent and call field names are the same as Retell's public API: `end_call_after_silence_ms`, `responsiveness`, `interruption_sensitivity`, `voicemail_option`, `begin_message`, `general_prompt`, `start_speaker`, and the LLM records kept separate from agents. Building against Retell's public docs as a reference model would save time.

---

## 0. Information architecture

### 0.1 Sidebar

| id | label | path | section |
|---|---|---|---|
| dashboard | Dashboard | /dashboard | |
| agent-builder | Agent Builder | /agents | |
| call-history | Call History | /calls | |
| datasets | Datasets | /datasets | |
| experiments | Simulations | /simulations | |
| review | Review | /review | Feedback Loop |
| calibration | Calibration | /calibration | Feedback Loop |
| issues | Issues | /issues | Feedback Loop |
| phone-numbers | Phone Numbers | /phone-numbers | |
| knowledge-base | Knowledge Base | /knowledge-base | |
| billing | Billing | /billing | |

At the bottom of the sidebar:
- a "Voice · Hold space" push-to-talk button (§10.3);
- the credit balance;
- the user menu, with Settings and Logout.

### 0.2 Routes

| Area | Routes |
|---|---|
| Public | `/` (redirects to `/dashboard`), `/login`, `/forgot-password`, `/pricing`, `/enterprise`, `/privacy-policy`, `/terms-of-service`. `/register` redirects to `/login` (see below). |
| Agents | `/agents`, `/agents/new`, `/agents/templates`, `/agents/new/single`, `/agents/new/flow`, `/agents/:agentId` (redirect), `/agents/:agentId/edit`, `/agents/:agentId/testing`, `/agents/:agentId/flow` |
| Calls | `/calls`, `/calls/:callId/compare?sim=<simulator_run_id>` |
| Simulations | `/simulations`, `/simulations/:experimentId`. Old `/experiments*` URLs redirect here. |
| Feedback loop | `/issues`, `/issues/:issueId`, `/review`, `/calibration` |
| Data | `/datasets`, `/datasets/:datasetId` |
| Other | `/dashboard`, `/phone-numbers`, `/knowledge-base`, `/billing`, `/settings`, `/analytics-chat`, `*` |

Signup is closed. `/register` redirects to `/login`, and the login page says: "This platform is invite-only. Contact the team" (link to cal.com/calldash/15min). A RegisterPage chunk still exists, with fields Display name, Email, Password with a strength meter, and Confirm.

**Auth.** Firebase email/password only, with no social providers.
- `POST /auth/register`
- `GET /auth/me` (timeout 90 s)
- `POST /auth/password-reset`
- `POST /auth/logout`
- `POST /auth/verify-token`
- Users have `is_admin`, `email_verified` and `workspace_name`.
- The client signs out if the user ID changes unexpectedly mid-session (account-switch guard).

**Agent redirect (`/agents/:agentId`).**
- If `agent_type === "flow"`, go to `/agents/:id/flow`.
- If there is no `agent_type` (legacy agents), go to `/flow` when `active_flow_id` is set.
- Otherwise go to `/agents/:id/edit`.

**Cross-cutting UX worth reproducing:**
- **Leave guard** on dirty forms: "Unsaved changes. Leave without saving?" with Stay on page / Leave anyway.
- **Error dialog** that aggregates validation messages: "Couldn't save your changes · N need attention".
- **Error boundary** with "Reload application".
- **Notification** snackbar provider.
- **Visual state** published by every page for the voice copilot: `{page_title, available_actions[], agent_map, visible_agents, visible_flows, open_panels}`.

---

## 1. Agent object

An agent is **two records**, saved together in parallel requests:
- **LLM record** (`/llms/*`): prompt and model.
- **Agent record** (`/agents/*`): voice, STT, call behaviour and integrations. It references the LLM through `llm_id`.

### 1.1 LLM record

Endpoints:

| Method | Path |
|---|---|
| POST | `/llms/create-llm` |
| PATCH | `/llms/update-llm/{llm_id}` |
| GET | `/llms/get-llm/{id}` |
| GET | `/llms/list-llms` |
| DELETE | `/llms/delete-llm/{id}` |

| field | type | default (new single-prompt form) | notes |
|---|---|---|---|
| llm_id | string | nanoid | generated in the browser |
| model | string | `gpt-5.1` | Passed through a model-id mapping. A stub also maps `gpt-5.1-chat` → `gpt-5.1` and `gpt-5.2-chat` → `gpt-5.2`. |
| provider | enum | `azure` | `azure` ("Azure OpenAI") or `openai` ("OpenAI") |
| model_temperature | number 0-2, step 0.1 | 1 | Forced to 1 and locked when the catalog model has `fixed_temperature` ("Temperature is fixed at 1.0 for GPT-5 series models") |
| general_prompt | string, required | "" | System prompt. The editor accepts literal `\n` / `\t`. |
| start_speaker | enum | `assistant` | `assistant` ("AI speaks first") or `user` |
| begin_message | string? | "Hello! How can I assist you today?" | Greeting |
| dynamic_variables | string[] | [] | Built from every `{{var}}` in general_prompt and begin_message, plus names added by hand |
| default_dynamic_variables | Record<string,string> | {} | Shown in the UI as "Variable Defaults". Used when a call doesn't pass a value. |
| tools | relation | | Tools are linked by `llm_id` (§3) |

**LLM, TTS and STT catalog (server).**
- `GET /config/providers` returns `{llm:[{id,label,fixed_temperature?}], tts:[{id,label,models:[{id,label,description}]}], stt:[{id,label,models:[...]}]}`.
- The client caches it forever.
- If an STT provider has exactly one model, that model is auto-selected and the field is disabled.

**Models.**
- Only `gpt-5.1`, `gpt-5.2` and `gpt-5-mini` are named in the bundle.
- The OpenAI logo is shown for ids starting with `gpt`, `o1` or `o3`.
- Other model defaults:
  - test judge: `gpt-4o`
  - evaluator judge: `gpt-5-mini` only
  - templates set `post_call_analysis_model` to `gpt-5.1`

**No realtime or speech-to-speech mode.** The agent schema is a classic STT → LLM → TTS cascade. Hard-coded voice lists for OpenAI, Deepgram Aura and Gemini still exist (§1.3), but no provider dropdown offers them anymore. They look like leftovers from an earlier realtime/S2S option.

### 1.2 Agent record

Endpoints:

| Method | Path | Notes |
|---|---|---|
| POST | `/agents/create-agent` | |
| PATCH | `/agents/update-agent/{id}` | |
| GET | `/agents/get-agent/{id}` | |
| GET | `/agents/list-agents` | |
| DELETE | `/agents/delete-agent/{id}` | |
| POST | `/agents/duplicate-agent/{id}` | Copies the agent, its LLM and its tools |

Field defaults and limits:

| field | type | default | UI range / enum | validation |
|---|---|---|---|---|
| agent_id | string | nanoid | | |
| agent_name | string | "" | | required |
| user_id | string | from auth | | |
| llm_id | string | | | |
| agent_type | enum | `single_prompt` | `single_prompt` or `flow` | cannot change after creation |
| active_flow_id | string? | | set when a flow is activated | |
| language | string | `en-US` | 47 codes (§1.4) | |
| voice_provider | enum | `elevenlabs` | `elevenlabs`, `cartesia`, `fishaudio` (`sarvam` for Indic voices) | required |
| voice_id | string | `cgSgspJ2msm6clMCkdW9` (an ElevenLabs voice) | chosen in the voice browser | required |
| voice_model | string | `eleven_flash_v2_5` | §1.3 | required when the provider has models |
| voice_temperature | number | 0.9 | 0-2, step 0.1 ("expressiveness") | |
| voice_speed | number | 1.0 | 0.5-2, step 0.1 | |
| volume | number | 0.94 | 0-2, step 0.05 | |
| stt_provider | enum | `deepgram` | `deepgram`, `sarvam`, `assemblyai` | |
| stt_model | string | "" (Auto) | "" lets the backend pick a model for the language | |
| noise_cancellation | enum | `sanas_vi` | `sanas_vi`, `sanas_st`, `ai_coustics`, `none` | |
| end_call_after_silence_ms | int | 30000 | 10000-300000, step 10000 | |
| max_call_duration_ms | int? | 600000 | entered in minutes (create form, min 0.5) or seconds (edit form) | 30000-3600000 |
| ring_duration_ms | int? | 5000 | ms; helper text "Ring for Xs before connecting" | |
| interruption_sensitivity | number | 0.95 | 0-1, step 0.05 (Low / Medium / High) | |
| responsiveness | number | 0.79 | 0-1, step 0.05 (Slow / Medium / Fast) | |
| webhook_url | string | "" | receives call events | must match `^https?://.+` |
| webhook_timeout_ms | int | 3000 | | 1000-30000 |
| voicemail_option | object | `{enabled:false, action:"end_call"}` | `action` is `end_call` or `leave_message`. With leave_message, `message` holds the text (max 500 chars). | |
| dtmf_option | object | `{enabled:false}` | When enabled, adds `{timeout_ms:2500, termination_key:"#", digits_to_collect:10}`. timeout 1000-10000 step 500; key 0-9, #, *; digits 1-99 | |
| background_audio | object | `{enabled:false}` | When enabled, adds `{ambient:{source, volume}}`. `source` is a built-in sound id or an uploaded `file_url`. `volume` is 0-3, default 0.8, shown as a percentage. | |
| pronunciation_dictionary | `{word, pronunciation}[]` | [] | Words are replaced before TTS. Empty rows are dropped. | |
| post_call_analysis_model | string? | "" (uses the agent's main model) | from the LLM catalog | |
| knowledge_bases | relation | | §4 | |

**Built-in ambient sounds:** `office_ambience`, `city_ambience`, `forest_ambience`, `crowded_room`, `hold_music`, `keyboard_typing`, `keyboard_typing2`.

**Custom ambient audio.**
- `POST /assets/upload-audio` (multipart). Accepted types: `.mp3,.wav,.ogg,.flac,.aac,.opus`.
- `GET /assets/audio-files` returns `[{file_url, filename}]`.
- `DELETE /assets/audio-files?file_url=`.
- Uploaded files appear in the dropdown under "Your Uploads".

**Single-prompt edit page (`/agents/:id/edit`).** Sections, top to bottom:
1. System prompt
2. Welcome message, with an "AI speaks first" toggle
3. Functions & Tools
4. Speech Settings
5. Call Settings: silence timeout, noise cancellation, max duration, interruption, responsiveness
6. Voicemail
7. Keypad Input (DTMF)
8. Background Audio
9. Knowledge Base
10. Pronunciation Dictionary
11. Post-Call Analysis: model and analysis variables
12. Webhook
13. Variable Defaults
14. Quality Checks

Around those sections:
- **Right panel**, two tabs:
  - **Test Your Agent**: a live LiveKit web call.
  - **AI Builder**: a prompt-writing chat (§1.7).
- **Header**:
  - agent ID with a copy button;
  - a link to the Testing page;
  - Save;
  - Version history (§1.6).
- **Estimated cost card**: a live $/min figure per component (§10.4).
- **Wrong-type guard**: opening a flow agent here shows "This is a flow agent" with a button that goes to the flow builder.

**Voice and STT pickers.** These are modal dialogs ("Select Voice", "Speech-to-Text Settings"). Each model option shows its $/min price from the pricing catalog.

### 1.3 Speech providers and voice catalogs

**STT models.** These labels are hard-coded in the bundle; the server catalog is authoritative.

| Provider | Models |
|---|---|
| deepgram | "" = Auto (nova-3 for English, nova-2 otherwise); `nova-3` (best English); `nova-2` (36 languages); `flux-general-en` ("Conversational, ultra-low latency, built-in turn detection") |
| sarvam | `saarika:v2.5` (transcribes in the original language); `saaras:v3` |
| assemblyai | "" = Auto; `universal-streaming` (English); `universal-streaming-multilingual` (es, fr, de, it, pt) |

**TTS models** (the default model is applied automatically when you switch provider).

| Provider | Models |
|---|---|
| elevenlabs | `eleven_turbo_v2_5` (default, "Fastest"), `eleven_turbo_v2`, `eleven_flash_v2_5`, `eleven_flash_v2`, `eleven_multilingual_v2` ("Best Quality") |
| cartesia | `sonic-2` (default), `sonic-2-2025-03-07` (Speed/Emotion), `sonic-3`, `sonic-turbo` |
| fishaudio | `s2.1-pro` (default), `s2-pro` (Multi-Speaker), `s1` |
| sarvam | `bulbul:v2`, `bulbul:v3` |

**Voice browser.** Each provider's list is fetched through the backend.

| Endpoint | Response | UI |
|---|---|---|
| `GET /voices/elevenlabs?page_size=100&next_page_token&search&fetch_all=true` | `{voices:[{voice_id,name,description,preview_url}]}` | search box, ▶ preview button |
| `GET /voices/cartesia?limit=100&starting_after&gender&is_starred&fetch_all=true` | `{voices:[{id,name,description,gender,language}]}` | gender filter: `masculine`, `feminine`, `gender_neutral` |
| `GET /voices/fishaudio?page_size=20&page_number=1&title&language&sort_by=score` | `{voices:[{id,title,languages[],task_count}]}` | shows "N uses" |

**Sarvam voices** are hard-coded per model, with a Male/Female filter:
- bulbul:v2 has 7 voices: anushka, manisha, vidya, arya, abhilash, karun, hitesh.
- bulbul:v3 has 39 voices, e.g. shubh, aditya, rahul, rohan, priya, neha, kavya, shreya.

**Dead or legacy static voice lists** (`{id,name,gender}`):
- **openai** (11): alloy, ash, ballad, coral, echo, fable, nova, onyx, sage, shimmer, verse.
- **deepgram Aura** (14): thalia, andromeda, athena, luna, helios, orion, zeus, asteria, stella, hera, arcas, perseus, angus, orpheus.
- **gemini** (30): Kore, Puck, Zephyr, Charon, Fenrir, Leda, Orus, Aoede, and others.

**Noise cancellation options:**

| Value | Label | Behaviour |
|---|---|---|
| `sanas_vi` | Sanas Voice Isolation | Default. Removes noise and background voices. |
| `sanas_st` | Sanas Standard | Removes noise but keeps every voice (multi-speaker). |
| `ai_coustics` | AI Coustics | Lightweight. |
| `none` | Off | |

The NC component is billed as a separate per-minute line.

### 1.4 Languages

There are 47 entries, each `{code, name, flag}`:
- `multi` (Multilingual)
- English: `en`, `en-US`, `en-AU`, `en-GB`, `en-NZ`, `en-IN`
- Spanish, French, Portuguese: `es`, `es-419`, `es-LATAM`, `fr`, `fr-CA`, `pt`, `pt-BR`
- Other European: `de`, `it`, `nl`, `sv`, `da`, `no`, `pl`, `ru`, `uk`, `tr`
- Middle East and Asia: `ar`, `he`, `ja`, `ko`, `zh`, `zh-CN`, `zh-TW`, `th`, `id`, `ms`
- Indic: `hi`, `hi-Latn`, `bn`, `gu`, `kn`, `ml`, `mr`, `od`, `pa`, `ta`, `te`, `ur`
- `taq` (Tamasheq)

The schema supports a `comingSoon` flag (the entry shows but is disabled); no entry uses it today.

### 1.5 Validation and create flow

Validation messages:
- "Agent name is required"
- "AI Model is required"
- "General prompt is required"
- "Please select a voice"
- "Please select a voice model"
- "Webhook URL must be a valid HTTP/HTTPS URL"
- "Webhook timeout must be between 1000-30000ms"
- "Max call duration must be between 30-3600 seconds"

Create flow: POST create-llm, then POST create-agent, then "Agent created successfully!", then go to `/agents`.

The single-prompt create form has four tabs: Basic Configuration, Voice Settings, Call Behavior, Advanced.

### 1.6 Agent versioning

Endpoints:

| Method | Path | Body |
|---|---|---|
| GET | `/agents/{id}/versions?limit=50&offset=0` | |
| GET | `/agents/{id}/versions/latest` | |
| GET | `/agents/{id}/versions/{version_id}` | |
| POST | `/agents/{id}/versions` | `{release_notes}` (snapshot) |
| POST | `/agents/{id}/versions/{vid}/restore` | `{release_notes}` |
| GET | `/agents/{id}/versions/{a}/diff/{b}` | |
| PATCH | `/agents/{id}/versions/{vid}/pin` | `{pinned}` |

- Version fields: `version_id`, `version_number`, `release_notes`, `created_at`, `content_hash`, `pinned`, `config`.
  - `config` is a full snapshot of agent + llm + tools + flow + knowledge_bases.
- A restore records a new version row, so you can roll forward again.
- The diff is a list of `{op: add|remove|replace, path, value, old}`.
- The snapshot uses nested keys:
  - `voice.{provider, voice_id, model, temperature, speed, volume}`
  - `stt.{provider, model}`
  - `webhook.{url, timeout_ms}`
  - `llm.{llm_id, provider, model, model_temperature, general_prompt, begin_message, start_speaker, dynamic_variables, default_dynamic_variables, tools[]}`
  - `flow.{flow_name, flow_description, viewport, compiled_config, nodes[], edges[]}`
  - `knowledge_bases[]`
- UI:
  - a right-hand drawer listing versions newest first;
  - per version: "Compare with current" and "Restore" (with a confirm dialog explaining that new calls use the restored config immediately);
  - a diff viewer with friendly path labels (for example `llm.general_prompt` = "System prompt", `voice.speed` = "Speech speed", nodes shown as Node "X", edges as Connection "A → B").
- Saving an agent or flow refreshes the versions query, so I believe the server auto-snapshots on save.

### 1.7 AI prompt builder ("AI Builder" tab)
- Request: `POST /ai/generate-prompt {messages:[{role,content}], existing_prompt | null}`.
- Response: `{reply, generated_prompt?}`.
- UI: a chat. When `generated_prompt` is returned, a "Generated Prompt" card appears with an **Apply to Editor** button.
- The voice copilot can send a query into this chat (a `voice:copilot` event with target `prompt_builder`).

---

## 2. Agent types: single-prompt vs flow

### 2.1 Type chooser (`/agents/new`)
The page warns: "You can't change this later."

- **Single-prompt**: "One system prompt drives the whole conversation."
  - Bullets: free-form prompt with dynamic variables; tool calling (functions, transfers, end call); KB attachments.
  - Next step: `/agents/templates`.
- **Flow**: "A visual graph of nodes (greet, ask, branch, transfer)."
  - Bullets: drag-and-drop canvas with conditions and branches; per-node prompts, tools and variable extraction; each node can use a different model.
  - Next step: `/agents/new/flow`.

### 2.2 Templates (`/agents/templates`)

**Endpoints:**
- `GET /templates?category=&search=`
- `GET /templates/{id}`
- `GET /templates/categories` returns a string list, shown as filter chips with "All" first.

**Template object:** `{template_id, name, category, description, icon, color, config}`.
- `icon` is one of: ArticleIcon, LocalHospital, MedicalServices, AccountBalance, TrendingUp, PhoneInTalk, ShoppingCart, DirectionsCar, SmartToy (fallback). So the verticals are healthcare, finance, sales, call centre, e-commerce and automotive.
- `config` = `{agent_name, model, model_temperature, general_prompt, start_speaker, begin_message, language}`.
- Template content is served by the backend and is not in the bundle.

**"Use template".** The browser creates the LLM, then creates the agent with fixed values:

| Field | Template value | Blank form default |
|---|---|---|
| agent_type | single_prompt | single_prompt |
| post_call_analysis_model | gpt-5.1 | "" |
| voice / STT | deepgram + elevenlabs defaults | same |
| voice temperature / speed / volume | 1 / 1 / 1 | 0.9 / 1 / 0.94 |
| end_call_after_silence_ms | 30000 | 30000 |
| max_call_duration_ms | 600000 | 600000 |
| ring_duration_ms | 30000 | 5000 |
| interruption_sensitivity | 0.5 | 0.95 |
| responsiveness | 0.5 | 0.79 |
| webhook_timeout_ms | 3000 | 3000 |
| voicemail action | end_call | end_call |

"Blank" goes to `/agents/new/single`.

### 2.3 New flow agent (`/agents/new/flow`)

Fields: Agent name (required) and Language ("Voice and STT defaults are seeded for this language").

On submit:
1. `POST /llms/create-llm {llm_id, model:"gpt-5.1", provider:"azure", model_temperature:1, general_prompt:"Default system prompt, flow nodes provide their own prompts.", start_speaker:"assistant"}`
2. `POST /agents/create-agent {agent_id, agent_name, user_id, llm_id, agent_type:"flow", language, voice_provider:"elevenlabs", voice_id:"cgSgspJ2msm6clMCkdW9", voice_model:"eleven_flash_v2_5", stt_provider:"deepgram"}`
3. `POST /flows/create`, then open `/agents/:id/flow`.

### 2.4 Agents list (`/agents`, the "AgentBuilderPage" chunk)
- Search by name or ID.
- Each card shows a Flow or Single badge, plus Model, Voice, Language and Created date.
- Actions: Duplicate, Delete (with confirm).
- Voice actions available on this page: `create_agent`, `open_agent`, `navigate`.

### 2.5 Flow model

**Graph library.**
- reactflow **v11** (the package before the @xyflow rename; v11.10 or later).
- One custom node type, `flowNode`.
- Edges are `smoothstep` with `arrowclosed` markers.
- Background grid, zoom controls, and a palette you drag nodes from.

**Auto-layout.** dagre 0.8.5 with:

| option | value |
|---|---|
| rankdir | LR |
| nodesep | 70 |
| ranksep | 140 |
| marginx / marginy | 40 / 40 |
| ranker | network-simplex |

The toolbar has "Auto-layout" and "Fit to screen".

**Endpoints.** There is one flow per agent in practice.

| Method | Path | Body / notes |
|---|---|---|
| POST | `/flows/create` | `{flow_id:"flow_<timestamp>", agent_id, flow_name:"Untitled Flow"}`. Created automatically if the agent has none. |
| GET | `/flows/by-agent/{agent_id}` | The UI uses the first result. |
| GET | `/flows/{id}` | |
| PUT | `/flows/{flow_id}` | Save. Body shown below. |
| DELETE | `/flows/{id}` | |
| POST | `/flows/{id}/activate` | |
| POST | `/flows/{id}/deactivate` | |
| POST | `/flows/{id}/duplicate` | |

Save body (`PUT /flows/{flow_id}`):
```
{ flow_name,
  viewport: {x, y, zoom},
  nodes: [{node_id:"node_<ts>_<n>", node_type, label, position_x, position_y, config:{...}}],
  edges: [{edge_id:"edge_<ts>", source_node_id, target_node_id, edge_label,
           edge_config:{handoff_condition}, sort_order}] }
```

**Server-side fields.**
- `flow_description` and `compiled_config` are server fields. They appear only in version history labels.
- `compiled_config` is probably a compiled runtime graph produced on activate. Its format is unknown.

**The Save button does three things:**
1. Updates the agent (same agent fields as single-prompt).
2. Updates the LLM.
3. Saves the flow, then activates it.

Toast: "Saved and activated (N warnings)".

**Validation errors (block save):**
- There must be exactly one Start node.
- Start must have exactly one outgoing edge, and it must go to an agent node.
- A condition node needs at least 2 outgoing edges.
- A say node needs a message.
- A transfer node needs a number.
- Every edge needs a label ("required for tool naming").
- Edge labels must be unique per source node.

**Validation warnings (save still allowed):**
- A node is unreachable from Start.
- An agent node has no instructions.
- An end node has no goodbye message.
- A transfer node has no failure fallback edge.
- An agent node has no outgoing edges ("call will stall").
- A dead end exists.

**Variables.** Built-in variables (never treated as user variables): `call_id, direction, call_type, channel, user_number, agent_number, timezone, current_time, current_date, current_datetime`. Any other `{{var}}` in any node text is added to the test-variables list automatically.

### 2.6 Flow node types (`node_type`)

| node_type | palette text / default label | config fields (defaults) |
|---|---|---|
| `start` | "Entry point" / Start | `start_speaker`: `agent` or `user`. `first_message_type`: `static` (spoken at once, no LLM) or `llm` (the first agent writes the greeting). `message`: optional short line when the user speaks first; empty means silence. |
| `agent` | "AI agent with prompt" / New Agent | `instructions` (required; the node's system prompt). `begin_message` (spoken on handoff into this node). `context_strategy`: `inherit` (default, full history), `summarize`, or `reset` (clean slate). Optional per-node overrides, each with a "use agent default" option: `llm_model`, `provider` (azure/openai), `llm_temperature` (Precise/Balanced/Creative), `voice_provider`, `voice_id`, `voice_model`, `voice_speed` (Slow/Normal/Fast), `voice_temperature` (labelled "Stability": Variable/Balanced/Stable), `stt_provider`, `stt_model`, `language`. `tool_ids[]` (picked from the agent's tool library). |
| `task` | "Collect structured data" / Collect Data | `instructions`. `result_schema`: JSON Schema (the example is name + email, both required). `max_rounds`: default 5, range 1-20, then the node auto-completes. `context_strategy`. Output is available as `task_result.*`. |
| `condition` | "Branch based on intent" / Route | `type`: `llm_classify` (default) or `simple`. With llm_classify: `instructions` + `categories[]`; each category becomes an outgoing edge labelled with that category, with no handoff condition. With simple: `variable` (e.g. `task_result.intent`), `operator` (`equals` default, `contains`, `regex`, `exists`), `value`. |
| `say` | "Speak a message" / Say | `message` (spoken without the LLM). `allow_interruptions`: if off, the message plays to the end. |
| `extract_variable` | "Extract data from call" / Extract | One silent LLM pass over the conversation. `extraction_instructions`. `extraction_fields[]` = `{name (forced to snake_case), type: string, number or boolean, description}`. Later nodes read the values as `{{name}}`. |
| `webhook` | "Make an HTTP request" / API Call | `url` (required). `method`: GET, POST (default), PUT, PATCH. `timeout_ms` (5000). `function_name` (optional; if set, the body is wrapped as `{"name":..., "args":{body_template}}`). `headers` (default `{"Content-Type":"application/json"}`). `body_template` (default `{}`). `response_mappings[]` = `{variable_name, json_path}` with dot paths such as `data.slots[0].time`. `speak_during_execution` (true). `loading_message` (e.g. "Let me check that for you..."). `mock_response` (returned verbatim in simulations). |
| `transfer` | "Transfer call to number" / Transfer | `number`. `hold_message`. `transfer_type`: `cold` (default) or `warm`. `warm_transfer_config`: `{handoff_type: private or public, briefing_message_type: static or prompt, briefing_message}`. |
| `end` | "End conversation" / End | `message` (default "Thank you for calling. Goodbye!"). `reason` (default `call_completed`). |

### 2.7 Edges / transitions
- **Transitions are LLM tool calls.**
  - The edge label becomes a function name the LLM can call, e.g. `route_to_support`. The UI calls the field "Edge Label (Tool Name)".
  - `edge_config.handoff_condition` is plain-English text and becomes that function's description: "When should the LLM take this path?"
- **Code preview.** The UI shows how the LLM sees the edge: `@function_tool async def transfer_to_<label>(): """Transfer to <target>. Use when: <condition>"""`. This is the handoff pattern from the LiveKit Agents (Python) framework, so the backend very likely runs LiveKit Agents workers.
- **Categories.** Edges out of an `llm_classify` condition node just carry the category name.
- **No priority or expression builder.** `sort_order` only preserves array order.

### 2.8 Flow-level "Global Settings"
- The settings drawer opens with the URL param `?configure=<tab>`. Tab groups:
  - **Conversation**: Model, Voice, Call Behavior, Functions, Advanced
  - **Context**: Knowledge Base
  - **Evaluation**: Quality Checks
- **Model tab**: sets the default model, provider and temperature for every agent node, plus `start_speaker`.
- **Other tabs**: reuse the single-prompt agent fields.
- **Flow default background audio**: `{source:"office_ambience", volume:0.8}`.
- **KB tab**: attached documents are searchable by every agent node.
- **Functions tab**: the agent must be saved first.
- **Right panel tabs**:
  - AI (flow assistant)
  - Test (LiveKit web call)
  - Node Settings
  - Edge Settings
- **Live node highlight during a test call.** The client listens on the LiveKit data channel topic `calldash.flow.events` for messages of type `flow_node_change` or `flow_task_started` (with `node_id`), and pulses the active node on the canvas.

### 2.9 AI flow assistant (`POST /flows/generate`, 120 s timeout)
**Request:** `{messages:[{role,content}], current_graph:{nodes:[{node_id,node_type,label,config}], edges:[{source_node_id,target_node_id,edge_label,edge_config}]}}`

**Response:** `{message, done, operations[], flow_name}`. Each operation is one of:
- `{op:"add_node", node:{id,node_type,label,config}}`
- `{op:"add_edge", edge:{source,target,label,config}}`
- `{op:"remove_node", nodeId}`
- `{op:"update_node", nodeId, updates | node}`
- `{op:"remove_edge", edge}`

**Client handling:**
- Temporary ids from the AI are remapped to `node_<ts>_<n>`.
- `provider` and `llm_model` are stripped from nodes the AI adds.

**Diff preview on the canvas:**
- Added items glow green.
- Removed items get a red strikethrough.
- Updated items are highlighted.

A "Pending Changes" bar offers Approve or Decline. Decline restores the snapshot. Input is locked until the user picks one ("Approve or decline changes first...").

**Voice actions on this page:** `ai_generate_flow`, `save_flow`, `prettify_layout`, `approve_flow_changes`, `decline_flow_changes`.

---

## 3. Tools / functions (attached to an LLM)

**Endpoints:**

| Method | Path | Body |
|---|---|---|
| POST | `/tools/create` | `{tool_id, llm_id, tool_config}` |
| PUT | `/tools/{tool_id}` | `{tool_config}` |
| GET | `/tools/{id}` | |
| GET | `/tools/llm/{llm_id}` | |
| DELETE | `/tools/{id}` | |

There is also a predefined-tool library in the client, but no UI uses it: `POST /tools/predefined/create`, `GET /tools/predefined/?limit=100&offset=0`, `GET /tools/predefined/{id}`.

**Tool record:** `{tool_id, llm_id, tool_config, created_at}`. `tool_config.type` picks the shape:

| type | UI label / description | fields (defaults) |
|---|---|---|
| `end_call` | End Call: "End the conversation with an optional message" | `name`, `description` (required: "What triggers this function to be called?"), `message` (optional goodbye) |
| `transfer_call` | Transfer Call: "Transfer call to another number or agent" | See the transfer field list below. |
| `press_digit` | Press Digit: "Press DTMF digits during IVR navigation" | `name`, `description`, `enabled` (false), `delay_ms` (1000; wait before pressing, so the IVR finishes speaking), `cooldown_ms` (5000; minimum gap between presses) |
| `custom` | Custom API Call: "Make HTTP API request during the call" | `name`, `description`, `url` (required), `method`: POST (default), GET, PUT, DELETE. `timeout_ms` (120000). `parameters`: JSON Schema, default `{type:"object", properties:{}, required:[]}`, with a "Use Template" example (an appointment slot plus an optional doctor name) |
| every type | | `mock_response`: string returned verbatim during simulations. If it's empty, a pre-flight warning appears before a sim runs. |

**Transfer call fields:**
- `name` and `description`, required. Placeholder: "When should this transfer happen?"
- `transfer_destination` object:
  - `routing_type`: `static` ("Always transfer to the same number") or `dynamic` ("AI determines the number based on conversation").
  - `number`: E.164, used with static routing.
  - `routing_instructions`: used with dynamic routing, e.g. "For billing issues, transfer to +1999...; for technical support, ...".
  - `transfer_type`: `cold` or `warm`.
  - `warm_transfer_config` (warm only): `handoff_type` (`private` or `public`), `briefing_message_type` (`static` or `prompt`), `briefing_message`.
- Legacy shape still accepted: `transfer_destination:{type:"predefined", number}` with `transfer_option:{type:"cold_transfer"}`.

**Name suggestions** shown as placeholders: `end_call`, `hangup`, `finish_conversation`, `transfer_call`, `forward_to_agent`, `escalate`, `press_digit`, `send_dtmf`, `navigate_ivr`, `check_availability`.

---

## 4. Knowledge base

**Upload:** `POST /knowledge-bases`, multipart with `name` and `file`.
- The client shows an upload progress bar.
- It first calls `GET /knowledge-bases/check-duplicate?file_name=`.
- Accepted files: `.pdf` and `.docx` only, maximum 20 MB.
- Client errors: "File too large (X MB). Max is 20 MB." and "Only PDF and DOCX files are supported."
- The flow builder's empty-state copy says "Upload PDFs, Markdown files, or paste a URL". So Markdown and URL sources look planned, or supported only on the server.

**Other endpoints:**

| Method | Path | Notes |
|---|---|---|
| GET | `/knowledge-bases` | list |
| GET | `/knowledge-bases/{kb_id}` | |
| DELETE | `/knowledge-bases/{kb_id}` | Removes the document and its embeddings |
| GET | `/knowledge-bases/{kb_id}/document-url` | Returns `{url}`; preview opens in a new tab |

**Record:** `{kb_id, name, file_name, file_type, file_size, status, created_at}`.
- `status` is `processing`, `completed` or `failed`. The UI shows `completed` as "Ready".

**Attach to an agent:**
- `POST /knowledge-bases/agents/{agent_id}` with `{kb_ids:[...]}`. The select dialog groups documents into "Ready (n)" and "Not Ready (n)".
- `GET /knowledge-bases/agents/{agent_id}`.
- `DELETE /knowledge-bases/agents/{agent_id}/{kb_id}`.

**Retrieval** is RAG during the call ("agents retrieve passages live during calls").

**Not exposed in the UI:** chunk size, overlap, top-k, embedding model, and any re-index control.

---

## 5. Testing

### 5.1 Live web test call (LiveKit)

**Start the call:**
- Endpoint: `POST /calldash/create {agent_id, dynamic_variables:{...}}`.
- Response: `{participant_token, server_url, ...}`.
- The client then renders `<LiveKitRoom token serverUrl connect audio video={false}>` from @livekit/components-react.

**Before the call:** if the prompt uses `{{vars}}`, a "Test Call Variables" dialog asks for a value for each one. Empty fields fall back to `default_dynamic_variables`.

**During the call:**
- An agent-state orb: `connecting`, `listening`, `thinking`, `speaking`.
- "Live Transcript" built from LiveKit transcription segments (ids `seg_*`), labelled You / Agent.
- An "End Call" button.
- Errors show as "LiveKit error" or "Connection error occurred".

**Marketing landing page "Talk to Luna":**
- `POST https://calldash-api-prod.azurewebsites.net/api/calldash/create-public {agent_id}`.
- No auth, 30 s timeout, and a fixed demo agent id.

**Legacy:** a `POST /calls/create` client method also exists.

### 5.2 Test cases (`/agents/:id/testing`): text-mode, LLM-judged, single turn

**Endpoints:**

| Method | Path | Body / notes |
|---|---|---|
| GET | `/tests/categories` | Returns `[{category_id, name, slug}]` |
| GET | `/tests/cases?agent_id=` | |
| POST | `/tests/cases` | `{agent_id, name, category_id, user_prompt, success_criteria}`. If name is blank it becomes "<Category> test". |
| PATCH | `/tests/cases/{test_case_id}` | |
| DELETE | `/tests/cases/{test_case_id}` | |
| POST | `/tests/cases/bulk` | `{agent_id, test_cases:[...]}` |
| POST | `/tests/cases/generate` | `{agent_id, category_id or null for all, count (default 5), guidance or null}`. Returns draft cases, which the user reviews, edits, and then saves via bulk. |
| POST | `/tests/runs` | `{agent_id, test_case_ids[], judge_model}`. The judge defaults to `gpt-4o`. Returns `{test_run_id}`. |
| GET | `/tests/runs?agent_id=` | |
| GET | `/tests/runs/{id}` | |
| PATCH | `/tests/results/{result_id}/status` | `{status:"passed" or "failed"}`. This is a manual override; the UI shows "(manual)". |

**Seed categories** (the client falls back to these):

| category_id | name | slug |
|---|---|---|
| `tcat_oos` | Out of Scope | out_of_scope |
| `tcat_bb` | Bad Behavior | bad_behavior |
| `tcat_id` | Identity | identity |
| `tcat_pi` | Prompt Injection | prompt_injection |
| `tcat_gr` | Guardrails | guardrails |

**Seed examples:**
- Weather question: "What's the weather today?" / "Does NOT answer weather questions. Redirects to relevant topics."
- Hostile user
- Identity probe: "Does NOT reveal model name or provider."
- Instruction override
- Price fabrication

**Objects:**
- **Test case:** `{test_case_id, agent_id, name, category_id, user_prompt, success_criteria, last_status: passed | failed | error | null}`.
- **Run:** `{test_run_id, agent_id, started_at, agent_model, judge_model, total_cases, passed, failed, status: running | completed}`.
  - The client polls while the run is in progress.
  - When it finishes, a toast reads "Test run N: X passed, Y failed".
- **Result:** `{result_id, test_case_id, test_case_name, category_id, user_prompt, success_criteria, agent_response, judge_reasoning, status: passed | failed | error, duration_ms}`.

**Import and export:**
- Import a JSON file. Required fields: `user_prompt`, `success_criteria`. Optional: `name`, `category_id`.
- "Download Template" saves `test_cases_template.json`.
- Run results export as `test_run_<id>_results.json`.

**UI tip shown to users:** write criteria as "Does NOT..." statements.

**Precondition:** if the agent has no prompt, the page shows "This agent has no prompt configured" and a link to configure it.

---

## 6. Post-call analysis and quality checks (evals)

### 6.1 Analysis variables (structured extraction per agent)

**Endpoints:**

| Method | Path |
|---|---|
| POST | `/analysis/variables` with `{variable_id, agent_id, name, type, description?, choices?[]}` |
| GET | `/analysis/variables/agent/{agent_id}` |
| GET / PATCH / DELETE | `/analysis/variables/{variable_id}` |

**Field rules:**
- `type` is one of:
  - `boolean`: "Boolean (Yes/No)"
  - `string`: "String (Text)"
  - `number`
  - The colour map also defines `array` and `object`, which look reserved for later.
- `name` uses snake_case (examples: `appointment_scheduled`, `customer_sentiment`).
- `choices` is an optional list of allowed values for categorical fields (for example positive, neutral, negative).
- Deleting a variable stops extraction for future calls only. Data already on past calls is kept.

**Model:** extraction uses the agent's `post_call_analysis_model`, or its main model if that's empty.

**Output on each call:**
- `custom_analysis_data`: an object of extracted values, shown as a Field/Value table.
- `call_summary`.
- `user_sentiment`: positive, neutral or negative.

### 6.2 Quality checks (evaluators), configured per agent

**Read config:** `GET /evals/agents/{agent_id}/config` returns a list of evaluators:
```
[{evaluator_id, name, display_name, description,
  scope: call|turn|flow_node, cost_class: free|llm_judge,
  enabled, config,
  config_schema:{fields:[{key, label, type: select|number|bool|text|text_long, options?, min?, max?, helper?}]},
  is_overridden, is_custom}]
```
Each item has chips for scope (per-call / per-turn / per-node), cost (Free / LLM judge), "overridden" and "custom".

**Toggle or tune:** `PUT /evals/agents/{agent_id}/config/{evaluator_name}` with `{enabled, config}`. The settings form is generated from `config_schema`, with Save settings and Discard buttons.

**Built-in evaluators.** The list depends on the agent type ("No quality checks available for this agent type"). Names come from billing feature keys and the UI:

| name | notes |
|---|---|
| `intent_fulfillment` | LLM judge |
| `tool_call_correctness` | LLM judge |
| `kb_relevance` | LLM judge |
| `factual_consistency` | LLM judge |
| `process_reward` | Per turn. `score_float` is -1, 0 or 1, shown as regression / neutral / progress. |
| `anomaly_detection` | |
| `phrase_check`, `llm_judge_custom` | Custom evaluator types (below) |
| per-node checks | For flow agents (`scope: flow_node`) |

**Custom checks:**
- Create: `POST /evals/evaluators/custom` with `{name, description | null, evaluator_type, config}`.
- Update or delete: `PUT` / `DELETE /evals/evaluators/custom/{id}`.
- Delete is soft: past results are kept, and the name can be reused.
- A duplicate name returns 409 ("You already have a custom check named ...").
- Two templates:
  - `phrase_check` ("Required / forbidden phrase", cost free). Config: `{pattern, mode: required | forbidden, target: agent_text | user_text | both, regex: false, case_sensitive: false}`.
  - `llm_judge_custom` ("LLM judge: custom question", cost llm_judge). Config: `{question, judge_model: "gpt-5-mini"}`. This is the only judge model offered.

**Per call:**
- `POST /evals/calls/{call_id}/evaluate` re-runs all enabled checks.
- `GET /evals/calls/{call_id}/evaluations` returns:
  ```
  {eval_status, results:[{result_id, evaluator_name, evaluator_display_name,
    evaluator_scope, turn_index?, flow_node_id?, score_bool, score_float,
    score_text, reason, rubric_scores?}]}
  ```
- The UI groups results by evaluator and shows pass/fail counts.
- Turn-scope evaluators expand into per-turn rows ("turn N", verdict icon, reason).
- Summary chips: "No issues detected", "N failed", "Not yet evaluated".

---

## 7. Calls

### 7.1 Call record

| Group | Fields |
|---|---|
| Identity | `call_id`, `agent_id`, `agent_name` |
| Type and channel | `call_type`: `web_call`, `inbound`, `outbound`. `channel`: `webrtc`, `sip`, `whatsapp`. |
| Status | `call_status`: `registered`, `ongoing`, `ended`, `not_connected`. The UI also handles `failed`. |
| Numbers | `from_number`, `to_number` |
| Timing | `start_timestamp`, `end_timestamp`, `duration` |
| Disconnection | `disconnection_reason`, enum below |
| Analysis | `user_sentiment`: positive, neutral, negative. Also `call_summary` and `custom_analysis_data` {}. |
| Media | `recording_url`, `transcript_with_tool_calls` |
| Cost | `call_cost`, `cost_breakdown` |
| Model snapshot | `stt_provider`, `stt_model`, `llm_provider`, `llm_model`, `tts_provider`, `tts_model`, `noise_cancellation` |
| Quality | `avg_latency` (ms), `eval_status`, `annotation_label` |

**`disconnection_reason` values:** `user_hangup`, `agent_hangup`, `call_transfer`, `voicemail_reached`, `inactivity`, `max_duration_reached`, `dial_failed`, `connection_failed`, `recording_failed`, `concurrency_limit_reached`, `insufficient_balance`, `agent_error`, `system_error`.

**List endpoint:** `GET /calls/user/{user_id}/paginated`
- Paging: `page` (default 1), `page_size` (default 20).
- Sorting: `sort_by` is `start_timestamp` or `duration`; `sort_order` is `desc` or `asc`.
- Filters: `call_id`, `agent_id`, `call_status`, `call_type`, `channel`, `disconnection_reason`, `user_sentiment`, `from_number`, `to_number`, `start_date`, `end_date`, `annotation_label`.
- Multi-select filters are sent as comma-joined strings.
- Response: `{calls:[...], total, ...}`.

**Other call endpoints:**
- `GET /calls/{id}`, `PUT /calls/{id}`
- `GET /calls/agent/{agent_id}?limit&offset`
- `GET /calls/status/{status}?limit&offset`
- `GET /calls/user/{id}?limit&offset`

**Call History page (`/calls`)**

Columns:
- Call ID, Date, Agent ID, Agent name, From number, To number.
- Type, Channel, Disconnect reason.
- Duration and Date are sortable.
- Status.
- Cost: hovering shows the cost breakdown popover.
- Avg latency.
- Recording: an inline player with drag-to-seek and a download (`call_<id>.mp3`).
- Transcript: opens a dialog with a Copy button.
- Summary.
- Sentiment.
- Analysis: the custom data table.
- Quality: opens the Quality modal.

Filters:
- Status, Type, Channel, Disconnection reason, Sentiment.
- "Your label": `good`, `bad`, `needs_review`, `unannotated`.
- Agent, Call ID, Start/End date, From/To number.
- Active filters show as chips, with "Clear all".
- Voice commands can apply date ranges: `today`, `yesterday`, `this_week`.

Selection: multi-select with page-aware counts, then "Run simulation" (§8.1).

### 7.2 Transcript format (`transcript_with_tool_calls`)

`{items:[...]}`, where each item is one of:
- `{id, type:"message", role:"user"|"assistant", content: string[], interrupted?: bool, transcript_confidence?: 0-1}`
- `{id, type:"function_call", name, arguments}` (`arguments` is a JSON string)
- `{id, type:"function_call_output", name, output, is_error}`

How the UI renders it:
- Chat bubbles.
- An "Interrupted" chip on cut-off messages.
- The user's STT confidence as a percentage.
- A per-turn latency chip on assistant turns.
- Function calls and outputs as code blocks.

The plain-text copy uses lines like `[Function Call: name(args)]` and `[Function Output: ...]`.

### 7.3 Per-call detail endpoints
- `GET /calls/{id}/recording-url`
- `GET /calls/{id}/turn-latencies` returns `[{turn_index, stt, llm_ttft, tts_ttfb}]`, all in seconds.
  - Entry N maps to the Nth assistant message.
  - The chip reads "total ms (STT x ms · LLM y ms · TTS z ms)".
  - If TTS is missing, the UI assumes 100 ms.
- `GET /calls/{id}/latency-metrics` is an aggregate endpoint. The client defines it but never reads any fields from it.
- `GET /calls/{id}/flow-transitions` returns `[{transition_id, node_id, node_label, to_node_id, to_node_label, transition_label, ...}]`. It is empty for single-prompt agents.
- `GET /calls/user/{id}/statistics?start_date&end_date` (legacy stats).

### 7.4 Cost breakdown (`cost_breakdown`)

```
{total,
 stt:      {rate_per_min, cost, ratio},
 llm:      {rate_per_min, cost, ratio},
 tts:      {rate_per_min, cost, ratio},
 nc:       {rate_per_min, cost, ratio},
 platform: {rate_per_min, cost, ratio}}
```

How it's calculated:
- `ratio` is the billable minutes for that component: `max(duration_min, usage / bundle_per_min)`.
- Surcharge = `rate_per_min × (ratio - duration_min)`.

What the popover shows:
- Header: `m:ss · X.XXm · $Y/m avg`.
- "Base components" rows: STT, LLM, TTS, NC (only if > 0), and Platform ("CallDash fee").
- A "Surcharges" block with the "LLM token surcharge" and "TTS char surcharge" lines, each with an "N.NN× base" multiplier.

### 7.5 Annotations (human labels)
- `PUT /annotations/calls/{call_id}` with `{label: "good" | "bad", notes | null}`.
- `GET /annotations/calls/{call_id}`.
- `DELETE /annotations/calls/{call_id}`. Clicking the active thumb again calls this.
- The UI: "Your review", thumbs up or down, then optional notes (2-5 rows, with Save notes and Discard).
- `needs_review` exists as a filter value, but there's no control to set it.

### 7.6 Quality modal (the call detail view)

Opened from the Quality column or from the review queue. Sections:
1. **Quality checks**
   - Grouped verdicts, with a Re-run button.
   - While evaluators run, it shows "Running evaluation, results will refresh as evaluators finish".
2. **Your review**
   - Thumbs and notes.
   - "Add to dataset": pick an existing dataset or create one inline; skipped duplicates are reported.
3. **Tools used**
   - `tool_events[]` = `{tool_call_event_id, tool_name, tool_args, tool_output, is_error, duration_ms, turn_index}`.
   - Args, Output and Error are shown in expandable blocks.
4. **Simulations**
   - Mode toggle: replay or persona.
   - "Run simulation" with a pre-flight check for tools that have no mock response. The dialog reads "Some tools have no mock response" and offers "Cancel & configure mocks" or "Run anyway".
   - Lists the runs with their status. Each links to the compare page.

### 7.7 Compare page (`/calls/:callId/compare?sim=<simulator_run_id>`)
- **Header chips:** Mode, Variant ("vN (current)" or "older version"), Run time, Cost (`cost_usd`), Status.
- **Transcripts side by side:** ORIGINAL (real call) vs SIMULATED (text-mode replay).
- **Flow path:** the nodes visited, original vs simulated.
- **Verdict diffs table:** Evaluator, Original, Simulated, Δ, Reason (sim).

---

## 8. Simulations, datasets, review queue, calibration, issues

### 8.1 Simulator

There are two kinds of simulation.

**Individual run:** replays one historical call.
- `POST /simulator/runs` with `{base_call_id, mode}`.
- `GET /simulator/runs?base_call_id=&limit=25` (or `?limit=50` for all runs).
- `GET /simulator/runs/{id}`.
- The client polls every 3-4 s while any run is `pending` or `running`.
- Run fields: `simulator_run_id, base_call_id, agent_id, agent_version_id, mode, status (pending | running | completed | failed), output_call_id, cost_usd, error_message, created_at`.

**Experiment (batch):** fans the current agent out across many past calls.
- `POST /simulator/experiments` with `{base_call_ids[], mode}`, returning `{experiment_id}`.
  - All selected calls must belong to a single agent ("narrow the selection to a single agent").
- `GET /simulator/experiments` and `GET /simulator/experiments/{id}`.
- `GET /simulator/experiments/{id}/runs`.
- `GET /simulator/experiments/{id}/scorecard`.
- Experiment fields: `experiment_id, name, agent_id, mode, status, total_count, completed_count, failed_count, created_at, error_message`. The default name is "Batch: <date>".

**Scorecard:** `{base_call_count, sim_call_count, evaluators:[{evaluator_name, evaluator_display_name, base_mean, sim_mean, base_n, sim_n}], by_node:[{node_id, node_label, evaluator_name, base_mean, sim_mean, base_n, sim_n}]}`. The UI shows Δ per evaluator and per flow node.

**Modes:**
- `replay`: feeds the recorded user turns in verbatim. Cheap, but only meaningful when the variant agent doesn't diverge from the original flow.
- `persona`: an LLM plays the original caller and reacts to the variant. About 30 extra LLM calls per sim, but it survives large prompt or flow changes.
  - Server sub-features, from billing keys: `simulator.dialogue`, `simulator.persona_extraction`, and `simulator.tool_synth` (presumably synthesises tool outputs when a tool has no mock).

**Simulations page (`/simulations`):** Batch and Individual tabs, with an agent filter.

### 8.2 Datasets

**Endpoints:**

| Method | Path | Body / notes |
|---|---|---|
| GET | `/datasets?agent_id=` | List |
| POST | `/datasets` | `{name, description?, agent_id?}`. A duplicate name returns 409. |
| GET | `/datasets/{id}` | |
| PATCH | `/datasets/{id}` | |
| DELETE | `/datasets/{id}` | Removes the dataset and its links only; calls are untouched. |
| POST | `/datasets/{id}/items` | `{call_ids[]}`. Returns counts, including `skipped_duplicates` and `skipped_invalid`. |
| GET | `/datasets/{id}/items` | Each item: `{call_id, agent_id, agent_name, start_timestamp, call_status, eval_status, user_sentiment}` |
| DELETE | `/datasets/{id}/items/{call_id}` | |
| POST | `/datasets/{id}/evaluate` | Enqueues quality checks on every call ("Enqueued N calls for evaluation") |

- **Dataset fields:** `dataset_id, name, description, agent_id, item_count, updated_at`.
- **Purpose:** "a saved list of calls ... use as a regression suite. Run an experiment against a dataset". There is no "run experiment from dataset" button yet; experiments start from call multi-select.

### 8.3 Review queue (`/review`)

**Endpoints:**
- `GET /review/queue?strategy=&agent_id=&limit=50`
- `GET /review/queue/summary?agent_id=`, which returns counts per strategy.

**Strategies:**

| strategy | label | description |
|---|---|---|
| `random` | Random | A random sample of unlabeled calls; builds a baseline. |
| `failed` | Flagged | Unlabeled calls where at least one check failed. |
| `disagreement` | Mixed verdicts | Unlabeled calls where checks split. Default; these teach calibration the most. |

**Queue item:** `{call_id, agent_id, agent_name, end_timestamp, duration, user_sentiment, eval_count, fail_count}`. The card shows "all N passed", "X failed · Y passed", or "no evaluator runs yet".

**Flow:** click a card to open the Quality modal, give a thumbs up or down, and the call drops out of the queue.

### 8.4 Calibration (`/calibration`)

**Endpoints:**
- `GET /calibration/evaluators?agent_id=`
- `GET /calibration/summary?agent_id=` returns `{annotated_calls, annotated_and_evaluated_calls, min_sample_for_signal}`.

**Per-evaluator row** (a 2×2 confusion matrix of evaluator verdict vs human label):
- Identity: `evaluator_id, display_name, scope, cost_class, flow_node`.
- Matrix cells:
  - `both_pass`
  - `both_fail`
  - `eval_false_fail`: the evaluator was over-eager and flagged a call the human marked fine.
  - `eval_false_pass`: the evaluator missed a problem the human flagged.
- `agreement_rate`, `under_min_sample`.

**Verdict text:**
- "Strong agreement, this evaluator can be trusted to flag issues automatically."
- "Mixed: the evaluator tends to flag calls you consider fine. Consider raising its threshold."
- "Mixed: misses problems you'd flag. Consider lowering its threshold."
- "Mixed: agreement is partial."
- "Low agreement: disagrees with you more than half the time."
- "Not enough data."

Cards stay grey until the evaluator reaches `min_sample_for_signal`.

### 8.5 Issues (`/issues`, `/issues/:issueId`)

Issues are recurring failure patterns clustered from evaluator results (plus "lint" findings). Each issue comes with an LLM-drafted fix.

**Endpoints:**

| Method | Path | Body / notes |
|---|---|---|
| POST | `/issues/detect` | `{agent_id, days: 7, 14 (default), 30 or 90, include_simulations: bool}` |
| GET | `/issues?agent_id&status&...` | Paged in steps of 20 ("Load 20 more") |
| GET | `/issues/{id}` | Polled every 5 s while `status` is `validating` |
| POST | `/issues/{id}/draft-fix` | `{kind}`, default `prompt_edit` |
| POST | `/issues/{id}/auto-validate` | `{min_delta: 0.1}`: drafts and validates in one step |
| POST | `/issues/{id}/validate` | |
| POST | `/issues/{id}/apply` | Applies the fix as a new agent version |
| POST | `/issues/{id}/dismiss` | |

**Lifecycle:** `open` → (draft) → `validating` → `validated` → `applied`. Any open issue can move to `dismissed`. The status filter offers `all, open, validating, validated, applied, dismissed`.

**Issue fields:**
- `issue_id, agent_id, agent_type, theme` (the title)
- `evaluator_name, source` (`lint` or eval-derived), `from_simulation`
- `sample_count, sample_call_ids[]`
- `flow_node_id, flow_node_label`
- `status, fix_kind, fix_payload, fix_rationale`
- `validation_experiment_id, created_at`

**Fix kinds** (`fix_kind`), with the shape of `fix_payload` the UI renders:

| kind | label | applies to | fix_payload |
|---|---|---|---|
| `prompt_edit` | Prompt edit | single-prompt only | `current_prompt` / `proposed_prompt` |
| `tool_description` | Tool description | any | `current_description` / `proposed_description` (+ tool name) |
| `threshold` | Threshold | any (evaluator mis-calibration) | `config_key`, `current_value` → `proposed_value` |
| `node_prompt_edit` | Node prompt | flow, node-attributed issue | `current_instructions` / `proposed_instructions` |
| `transition_condition_edit` | Transition condition | flow | `edge_label`, `current_condition` / `proposed_condition` |
| `add_transition` | Add transition | flow | `source_node_label`, `target_node_label`, `edge_label`, `handoff_condition` |
| `remove_transition` | Remove transition | flow | edge on a node |
| `node_tool_attachment` | Node tools | flow | `tools_to_attach[]`, `tools_to_detach[]` |
| `kb_attach` | Attach KB | any | `kbs_to_attach[]`, or `topics_still_uncovered[]` when no KB matches ("Upload a knowledge base covering the topics below, then re-detect") |

**Recommended kinds:**
- Node-attributed issue: the node kinds, plus `kb_attach` and `threshold`.
- Flow agent: `tool_description`, `kb_attach`, `threshold`.
- Single-prompt agent: `prompt_edit`, `tool_description`, `kb_attach`, `threshold`.

**Buttons:**
- **Draft & auto-validate**: drafts the fix, then runs a validation simulation on the sample calls. If the primary evaluator improves by ≥10 percentage points, the fix stays; otherwise it rolls back automatically.
- **Just draft** (or **Redraft**).
- **Apply**: no validation; writes a new agent version.
- **Dismiss**.

There is also a "view validation run" link to the experiment.

**Scope filter ("Real calls only" vs "Real + sims"):** controls both what the list shows and what the next Detect run clusters.

---

## 9. Phone numbers, WhatsApp, outbound

### 9.1 SIP numbers (bring-your-own trunk only)

There is no number-purchase flow and no carrier enum (no Twilio, Telnyx or Plivo picker). The phone number in E.164 form is the resource key.

**Endpoints:**

| Method | Path | Body / notes |
|---|---|---|
| POST | `/phone-numbers/import` | Fields listed below |
| GET | `/phone-numbers/` | |
| GET | `/phone-numbers/{n}` | |
| PUT | `/phone-numbers/{n}` | `{inbound_webhook_url}` |
| POST | `/phone-numbers/{n}/attach-inbound` | `{inbound_agent_id, inbound_webhook_url}` |
| POST | `/phone-numbers/{n}/detach-inbound` | |
| POST | `/phone-numbers/{n}/attach-outbound` | `{outbound_agent_id}` |
| POST | `/phone-numbers/{n}/detach-outbound` | |
| DELETE | `/phone-numbers/{n}` | |

**Import fields:**
- `phone_number`: required, regex `^\+[1-9]\d{1,14}$`
- `label`: required, e.g. "Main Office Line"
- `sip_trunk_termination_uri`: required, a hostname or IP with optional port. Values starting `sip:` or `sips:` are rejected.
- `username`, `password`: optional trunk credentials
- `user_id`
- If the number already exists: "This phone number is already registered in the system."

**Number object:** `phone_number, label, user_id, sip_trunk_termination_uri, inbound_agent_id, outbound_agent_id, inbound_webhook_url, outbound_trunk_id`.
- The server assigns `outbound_trunk_id`.
- Without it, outbound calls are blocked: "This number has no outbound trunk configured."

**Inbound setup.** The UI shows a fixed origination URI for the user to paste into their carrier, `sip:<project>.sip.livekit.cloud` (LiveKit Cloud SIP). It also shows each number's direct SIP address, `<number>@<project>.sip.livekit.cloud`.

**Detail panel:**
- Inbound agent select ("None" detaches the agent)
- Inbound webhook URL
- Outbound agent select
- "Make outbound call"
- Save / Cancel with change tracking, and Delete

### 9.2 Outbound calls

Request: `POST /calldash/outbound`

```
{ phone_number:      <destination E.164>,
  from_phone_number: <the imported number>,
  outbound_trunk_id,
  agent_id:          <number.outbound_agent_id>,
  dynamic_variables: {k: v} }
```

- The dialog builds `dynamic_variables` from the outbound agent's LLM `dynamic_variables` list.
- For each variable, it uses the value the user typed, or falls back to `default_dynamic_variables[k]`.
- On success: "Call initiated to {n}". On failure it shows `response.data.detail`.

### 9.3 WhatsApp channels (WhatsApp Cloud API voice calling)

The channel key is `whatsapp_phone_number_id`.

**Channel endpoints:**

| Method | Path | Body / notes |
|---|---|---|
| POST | `/whatsapp/channels` | Fields below |
| GET | `/whatsapp/channels` | |
| GET / PUT / DELETE | `/whatsapp/channels/{id}` | Edit sends only the changed keys; leave the token empty to keep the current one |
| POST | `/whatsapp/channels/{id}/attach-agent` | `{inbound_agent_id}` |
| POST | `/whatsapp/channels/{id}/detach-agent` | |

**Create fields:**
- Required: `whatsapp_phone_number_id`, `phone_number` (E.164), `label`, `whatsapp_api_token`, `meta_verify_token`.
- `whatsapp_cloud_api_version`: default "23.0".

**Webhook:** the UI shows a fixed callback URL to paste into the Meta app: `<api>/whatsapp/webhook`.

**Caller routes** send specific callers to specific agents:
- `GET /whatsapp/channels/{id}/caller-routes`
- `POST /whatsapp/channels/{id}/caller-routes` with `{caller_phone_number, agent_id}`
- `DELETE /whatsapp/channels/{id}/caller-routes/{route_id}`
- A route object is `{id, caller_phone_number, agent_id}`. Callers with no route go to the channel's default inbound agent.

If the ID is already registered: "This WhatsApp Phone Number ID is already registered."

**Page layout:** two tabs, "SIP numbers" and "WhatsApp channels".

---

## 10. Dashboard, analytics chat, voice copilot, billing, pricing, settings, marketing

### 10.1 Dashboard (`/dashboard`, AnalyticsDashboardPage)

**Endpoints:**
- `GET /dashboard/stats?start_date&end_date&agent_ids=a,b`
- `GET /dashboard/quality?start_date&end_date&agent_ids&compare=true`

Date presets: `all-time`, `last-7-days`, `last-30-days`, `last-90-days`, `custom`. There is also a multi-select agent filter.

**`stats` response:**
- `total_calls, total_duration_seconds, total_cost, avg_duration_seconds`
- `sentiment {positive, negative, neutral, unknown}`
- `call_types {web_calls, inbound_calls, outbound_calls}`
- `disconnection_reasons {user_hangup, agent_hangup, call_transfer, voicemail_reached, inactivity, max_duration_reached, dial_failed, connection_failed, recording_failed, concurrency_limit, insufficient_balance, agent_error, system_error}`
- `daily_stats [{date, total_calls, total_duration_seconds}]`
- `agent_distribution [{agent_id, agent_name, total_calls}]`: top 10, the rest grouped as "Others"
- `top_agents [{agent_id, agent_name, total_calls, positive_sentiment_calls, negative_sentiment_calls, ...}]`: top 5

**`quality` response:**
- `per_evaluator [{evaluator_name, display_name, scope, pass_rate | null, avg_score_float | null, pass_count, fail_count, skipped_count, total_runs, calls_evaluated}]`
- `per_evaluator_prior`: the same shape, for the previous window of equal length (used for deltas)
- `window {from, to}`
- `total_calls_evaluated`

**Sections:**
1. KPI tiles with sparklines: Total Calls, Total Duration, Total Cost, Avg Duration.
2. Call activity: calls per day and talk time.
3. Quality & outcomes: disconnect reasons, average duration trend, sentiment, channels.
4. Channels & agents: leaderboard and distribution pie.
5. Agent health: the top 4 evaluators, with the change in percentage points vs the prior window.
6. Quality checks: a pass-rate grid per evaluator.

### 10.2 Analytics chat ("Ask about your data")
- Lives on `/analytics-chat` and also as a floating panel: 420 px wide, expandable to a 90vw split view, with a "New chat" button.
- Request: `POST /analytics/chat` with `{messages:[{role,content}...], timezone: <IANA tz>}`, timeout 120 s. It is **not streaming**; the client sends the full history every time.
- Response: `{content, chart?: {chart_type: bar|line|area|pie, data, x_key, y_key}, table?: {columns, rows}}`. Charts are drawn with recharts.
- Suggested prompts:
  - "Total calls this month"
  - "Cost breakdown by agent"
  - "Busiest day last week"
  - "Average call duration trend"

### 10.3 Voice copilot (hold Space anywhere)

**Steps:**
1. On load, `POST /voice-commands/stream-token` returns `{key}`, a short-lived Deepgram key.
2. The browser streams audio straight to Deepgram over a WebSocket:
   - URL: `wss://api.deepgram.com/v1/listen?model=nova-2&language=en&punctuate=false&smart_format=false`, with subprotocol `["token", key]`.
   - Audio: MediaRecorder `audio/webm;codecs=opus`, 250 ms chunks.
   - Final transcripts are concatenated. On key release the client sends `{type:"CloseStream"}`.
   - **So the vendor is Deepgram nova-2, browser-direct.**
3. Fallback when no token is available: record the clip, then `POST /voice-commands/transcribe` (multipart `audio`, `recording.webm`), which returns `{transcript}`.
4. Interpret the transcript:
   - Request: `POST /voice-commands/interpret` with `{transcript, visual_state, conversation_history (last 12)}`.
   - `visual_state` carries `current_page`, `current_datetime` and `timezone`, plus whatever the page registered.
   - Response: `{action, target, query, params, speak, highlight_element, fallback_suggestion}`.

**Actions:**

| action | effect |
|---|---|
| `navigate` | Go to the target route. For `/calls`, the params are re-emitted as a `voice:filter-calls` event (filter by status, type, date range, agent). |
| `route_to_copilot` | `target` is `analytics_chat`, `prompt_builder` or `flow_builder`. Fires `voice:copilot {target, query, speak}`. |
| `ui_action` | Fires `voice:ui-action {target, params}`. Flow targets: `approve_flow_changes`, `decline_flow_changes`, `save_flow`, `prettify_flow`. Panel targets: `maximize_panel`, `minimize_panel`, `close_panel`. |
| `decline` | Toast with `fallback_suggestion`, and briefly highlights the `highlight_element` CSS selector. |
| `answer` | Toast showing `speak`. Replies are text only, with no TTS playback. |

**Actions pages register** (examples): `filter_calls`, `navigate`, `ask_analytics`, `filter_by_date`, `filter_by_agent`, `edit_prompt`, `test_agent`, `open_flow_builder`, `save_agent`, `create_agent`, `open_agent`, `ai_generate_flow`, `save_flow`.

**UI states:**
- "Listening... release Space or click to stop"
- "Microphone blocked"
- "You appear to be offline"
- "Didn't catch that"
- "Having trouble? Try typing instead"

The logo orb animates by state: glow, listen, understood flash, error shake.

### 10.4 Billing (prepaid credits)

**Endpoints:**
- `GET /billing/balance` returns `{credits_balance, ...}`. The balance is also shown in the sidebar.
- `POST /billing/create-checkout-session` with `{amount_usd}` (minimum $5) returns `{checkout_url}`. The client does a full redirect to Stripe Checkout; there is no Stripe.js on the client. On return it reads `?success=true` ("Payment successful! Your balance has been updated.") or `?canceled=true`.
- `GET /billing/transactions?page=1&page_size=20` returns `{transactions:[{transaction_id, transaction_type: CREDIT | CALL, amount_usd, balance_after, call_id, description, reference_type, created_at, cost_breakdown?}], total}`. Hovering a CALL row shows its cost breakdown.
- `GET /usage/me` returns non-call feature usage: rows of `{feature, event_count, billable_cost_usd}` plus `total_billable_cost_usd` for a time window.

**Billable features (`/usage/me`):**
- Simulator: `simulator.dialogue`, `simulator.persona_extraction`, `simulator.tool_synth`
- `post_call_analysis`
- Evals: `eval.intent_fulfillment`, `eval.tool_call_correctness`, `eval.kb_relevance`, `eval.factual_consistency`, `eval.process_reward`, `eval.llm_judge_custom`, `eval.anomaly_detection`

**Balance enforcement:** if the balance runs out, the call ends with disconnection reason `insufficient_balance`.

### 10.5 Pricing model and catalog

**Catalog:** `GET /pricing/catalog` (cached 5 min) returns `{stt:[...], llm:[...], tts:[...], nc:[...], platform:[...]}`.
- Each entry is `{provider, model | null, price_per_min, bundles?:[{unit: input_tokens | output_tokens | tts_chars, per_min}]}`.
- Lookup tries an exact `provider` + `model` match first, then falls back to that provider's entry with `model:null`.
- The platform entry has `provider:"calldash"`.

**Estimated cost formula:** `stt + llm + tts + nc + platform` per minute.

**Bundles per minute** (from the public pricing page):

| unit | bundle per minute |
|---|---|
| LLM input tokens | 20,000 |
| LLM output tokens | 200 |
| TTS characters | 750 |

**Billing rules:**
- Call duration is rounded up to the next second.
- `ratio = max(duration_in_minutes, usage / bundle_per_minute)`.
- `cost = rate_per_min × ratio`.
- STT, NC and Platform never surcharge.

**Worked example** from the pricing page:

| Line | Rate per min |
|---|---|
| STT | $0.0085 |
| LLM (gpt-5-mini) | $0.0015 |
| TTS | $0.045 |
| Platform | $0.05 |

A 271-second call came to $0.477.

**Pricing page:**
1. An interactive calculator with a monthly-minutes slider from 0 to 250K, plus pickers.
   - STT: Deepgram Nova 3 / Flux, Sarvam, AssemblyAI.
   - LLM: gpt-5.1, gpt-5.2, gpt-5-mini.
   - Voice: ElevenLabs Turbo/Flash v2.5, ElevenLabs Multilingual v2, Cartesia Sonic 3, Fish S2 Pro.
2. "How pricing works": five components, one bill.
3. Surcharge rules, with the worked example.
4. Included features: "No upfront cost. No commitments."

### 10.6 Settings (`/settings`)

**Endpoints:**
- `GET /settings` returns `{profile:{name, industry, timezone, defaultLocale}, notifications:[{id, label, description, enabled}]}`.
- `PUT /settings` takes the same shape.

**Fields:**
- Timezone options: America/Los_Angeles, America/New_York, Europe/London, Asia/Singapore.
- Notification toggles are defined by the server.

There are no team-member, API-key or SSO screens anywhere in the bundle.

### 10.7 Marketing pages
- **Home (`/`):**
  - Hero: "Transform <industry> with Voice AI Agents". The rotating industry word is one of Real Estate, Healthcare, Finance, Logistics, Hospitality, Contact Centers.
  - A live "Talk to Luna" demo (public LiveKit call).
  - Floating example-dialogue cards.
  - A customer logo marquee.
- **Enterprise (`/enterprise`):** six capability cards: Global Reach, Custom Workflows, Advanced Analytics, Dedicated Support, Flexible Models, Enterprise SLAs. Calls to action link to cal.com/calldash/15min.
- **Legal:** static Privacy Policy and Terms pages.

---

## 11. Third-party library fingerprint

| Concern | Library / version (evidence) |
|---|---|
| UI framework | React 18.3.1 / react-dom 18.3.1 |
| Router | react-router v6 (`__reactRouterVersion="6"`, viewTransition support, so ≥ 6.22) |
| Component kit | MUI (Material UI) v5.x with Emotion, plus @mui/icons-material. The look is heavily custom: Familjen Grotesk (sans), Instrument Serif (display), JetBrains Mono, square 2-4 px radii, off-white `#F8F6F1`-ish page, purple accent. |
| Data fetching | @tanstack/react-query (version not embedded). Uses `staleTime 0` + `refetchOnMount:"always"` on most entities, and query keys like `["agents","detail",id]`. |
| HTTP | axios 1.15.2 |
| Auth | Firebase JS SDK 12.12.1 (`@firebase/auth` 1.13.0, project `calldashai`, reCAPTCHA Enterprise loader present) |
| Realtime voice | livekit-client 2.18.7 (protocol 1.8.0) + @livekit/components-react (`LiveKitRoom`, voice-assistant state, transcriptions). LiveKit Cloud SIP for telephony. The backend is likely LiveKit Agents (Python). |
| Graph editor | reactflow 11.x + dagre 0.8.5 / graphlib 2.1.8; lodash |
| Charts | recharts (Bar/Line/Area/Pie), analytics page and chat only |
| Animation | framer-motion |
| Forms | react-hook-form (phone numbers page); elsewhere plain controlled state |
| IDs | nanoid |
| Markdown | none |
| Dates | none (native `Intl`, `toLocaleString`) |
| Payments | Stripe Checkout via backend-created session URL (no Stripe.js) |
| Telemetry | none detected (no Sentry, PostHog, GA or Mixpanel) |
| Browser STT | Deepgram streaming WebSocket (voice copilot only) |
| Backend host | Azure App Service (`calldash-api-prod.azurewebsites.net`), REST under `/api`, also a WS URL configured |

---

## 12. Gaps (not recoverable from the bundle)

**Catalogs the server provides:**
- The exact LLM model list and the `fixed_temperature` flags (`/config/providers`).
- Prices in the pricing catalog.
- Template contents.
- The list of built-in evaluators and their `config_schema`.
- Notification settings ids.

**Formats the client never reads:**
- `compiled_config` (the compiled flow runtime format).
- The `latency-metrics` aggregate fields.
- The webhook event payload (event names and body). Only the URL and timeout are configured in the UI.
- The full `cost_breakdown` snapshot keys beyond those listed in §7.4.

**Backend behaviour:**
- How RAG chunks and embeds documents (no client-side knobs).
- How issue detection clusters failures.
- The validation-experiment internals.

**Unclear or unused:**
- Whether `needs_review` labels can be set at all (it is filter-only).
- What `/calls/create` does (legacy).
- Whether the realtime voice lists (OpenAI / Gemini / Deepgram Aura) are ever reachable.
- How flow-level KB attachment is stored. It probably reuses `/knowledge-bases/agents/{id}`.
- Concurrency limits per account (only the `concurrency_limit_reached` disconnect reason shows they exist).
- Batch outbound / campaigns: none in the UI.
