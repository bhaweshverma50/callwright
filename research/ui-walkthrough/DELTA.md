# DELTA: live UI walkthrough vs `calldash-functional-spec.md`

Findings from the 2026-10-16 live walkthrough that are NEW (not in the bundle-derived spec) or CONTRADICT it. Tags name the Callwright spec affected: 001 platform, 002 agent builder, 003 voice runtime, 004 flow agents, 005 tools/knowledge, 006 calls/analytics, 007 quality/evals, 008 testing/simulation, 009 issues, 010 channels. "C" = contradicts the spec, "N" = new detail.

## 001 platform

- C [001] `/settings` now renders "Not Found"; there is no settings page, no user menu and no Settings link. Logout is a bare icon button in the top bar (spec 0.1 / 10.6 describe a user menu with Settings and Logout and GET/PUT `/settings`).
- C [001] Sidebar has no "Voice · Hold space" button and no credit balance. The balance lives in the top bar (wallet chip, 3 decimals, not clickable) next to the email and an initial avatar. Bottom of the sidebar is only an initials badge.
- N [001] Sidebar has two section headers: **QUALITY** (Datasets, Simulations) and **FEEDBACK LOOP** (Review, Calibration, Issues). Sidebar is collapsed by default; collapsed icons show label tooltips.
- C [001] `/analytics-chat` redirects to `/dashboard`; unknown routes also redirect to `/dashboard`. `/experiments` redirects to `/simulations` (as in spec).
- N [001] GET `/auth/me` returns `max_concurrency` (1 on this account) plus `credits_balance`, `firebase_uid`, `workspace_name`, `is_admin`. Per-account concurrency cap is a first-class account field.
- N [001] GET `/billing/balance` returns `{user_id, balance}` (key `balance`).
- N [001] POST `/voice-commands/stream-token` fires on every full page load, whether or not the copilot is used (wasteful; mint lazily in Callwright).
- N [001] Unsaved-changes guard exists on the flow builder ("Unsaved changes / You have unsaved changes that will be lost. Leave without saving?" Stay on page / Leave anyway) but NOT on the single-prompt create form.
- N [001] API hygiene: GET `/simulator/experiments/<non-uuid>` returns HTTP 503 with a raw Postgres error string. Unknown dataset returns `{error, status_code:404}` and the UI prints "Request failed with status code 404".

## 002 agent builder

- N [002] Templates: exactly 7, all single-prompt, categories Automotive, Banking, E-Commerce, Healthcare, Telecom. Template `config` keys: `agent_name, model, model_temperature, language, start_speaker, begin_message, general_prompt, voice_provider, voice_model, stt_provider`. No `voice_id`, tools, variables, call behaviour or flow graph. All use `model:"gpt-5.1-chat"`, temperature 0.7, en-US, ElevenLabs flash v2.5, Deepgram. Full bodies saved in `templates/`.
- C [002] "Use template" create-llm payload omits `provider` (blank and flow creates include it). Clicking anywhere on a template card triggers creation immediately: no preview and no confirm.
- N [002] Type chooser preselects Single-prompt; Continue for single goes to the templates page, not straight to the form.
- N [002] Language list has 47 entries but two share the label "Spanish (Latin America)" (es-419 and es-LATAM); "Tamasheq" has no flag. Sorted by label with Multilingual first.
- C [002] All three LLMs (`gpt-5.1`, `gpt-5.2`, `gpt-5-mini`) have `fixed_temperature:true`, so the temperature slider is always disabled at 1.0. The flow-level Model tab has no temperature at all. The per-node override slider displays 0.70 while disabled with "Fixed at 1.0 for GPT-5 models" (inconsistent).
- N [002] Estimated cost card shows LLM $0.0000/min for GPT-5.1 and GPT-5.2 (no catalog price) and has no NC line; GPT-5 Mini shows "20k in tokens/min · 200 out tokens/min" $0.0015.
- C [002] Client validation is weaker than the spec lists: a webhook URL "notaurl", webhook timeout 50, max duration 0.2 or 61 minutes and ring -1 ms all pass client side (no inline errors, request sent). Only name, prompt and voice are enforced on create.
- N [002] Dynamic variables chip input accepts any text ("bad name!"); prompt `{{vars}}` are auto-added. Begin Message stays visible when Start Speaker = User.
- N [002] Display/value mismatches: Volume label 0.94 vs slider 0.95 (step 0.05); Responsiveness label 0.79 vs slider 0.8. Ring helper floors ("1500" shows "Ring for 1s") and prints negatives.
- N [002] Background audio volume (0 to 3) is displayed as a percentage of 3 (default 0.8 shows "27%").
- N [002] Noise Cancellation renders blank on the create form with helper "No noise cancellation applied" although the server default is `sanas_vi`; Global Settings shows "Sanas Voice Isolation (Default)". Possible create-form bug.
- N [002] The create form has no analysis-variables editor; it exists in flow Global Settings Advanced ("Add Variable").
- N [002] "Test agent" on the unsaved create form only shows "Test functionality coming soon!".
- N [002] "Duplicate agent" fires immediately with no confirm (POST `/agents/duplicate-agent/{id}`, empty body).
- N [002] Version record has more fields than the spec: `parent_version_id, archived_at, llm_model_id, voice_id, has_kb, node_count`, and the snapshot adds `type` and `analysis_variables[]`. With a single version the history panel shows no Compare/Restore.
- N [002] Flow save PATCH `/agents/update-agent/{id}` sends `max_call_duration_ms:null, ring_duration_ms:null` but no `webhook_timeout_ms`, `pronunciation_dictionary` or `post_call_analysis_model` (worth checking whether those flow-level edits persist at all).
- N [002] Voice picking on the create form is an inline list (not a modal). Switching provider clears the selected voice.

## 003 voice runtime

- N [003] Per-minute prices shown in pickers: STT Deepgram Auto/Nova-3/Flux $0.0085, Nova-2 $0.0058, Sarvam $0.0060, AssemblyAI $0.0030. TTS ElevenLabs $0.045 (Multilingual v2 $0.09), Cartesia $0.0275, Fish Audio $0.015. Platform fee $0.05.
- C [003] Sarvam STT offers no "Auto" model (field enabled and blank by default). Sarvam TTS (bulbul) is not offered in any voice-provider dropdown (only ElevenLabs, Cartesia, Fish Audio).
- N [003] Voice catalogs: ElevenLabs 29 voices (workspace + premade, server search, preview); Cartesia 1043 voices, gender filter only, no search, no preview; Fish Audio top 50 of 1000 community voices by score, no search/filter/preview (list dominated by meme and non-English voices).
- C [003] Per-node voice overrides use different ranges than the agent: Speed 0.5 to 2 step 0.05 (agent step 0.1) and "Stability" 0 to 1 step 0.05 mapped to voice_temperature (agent range 0 to 2).
- N [003] Per-node STT override includes a Language select ("Affects STT model selection") and STT model list starting with "Auto-select based on language".
- N [003] NC option descriptions: Voice Isolation "Removes noise + background voices (best for noisy callers)", Standard "Removes noise, preserves all voices", AI Coustics "Lightweight noise cancellation", Off.
- C [003] Voice copilot: holding Space with the mic denied shows a toast "Microphone access is blocked. Check your browser permissions."; there is no visible copilot button anywhere.

## 004 flow agents

- N [004] Canvas has no minimap and no zoom buttons; only "Auto-layout" and "Fit to screen" (aria-labels, no tooltips). No right-click menus. Backspace deletes the selected node; "Delete Node"/"Delete Edge" buttons delete without confirm.
- N [004] Start node UI: "Who speaks first?" radios; agent-first has "First message type" Static (default, Message required) or LLM-generated; user-first shows "Optional greeting". Start label on canvas shows "Agent speaks first".
- N [004] Condition categories are chips (dedup, no format check) and do NOT create one handle per category; edges out of a classifier node hide Handoff Condition and show a "ROUTING HANDLED BY THE CLASSIFICATION NODE" explanation.
- C [004] Edge labels are not sanitised: "Route To Billing!" is accepted and previewed as `route_to_billing!` (invalid Python/tool name). Validation requires a label on the Start edge too.
- C [004] Fewer save-blocking errors than the spec implies: an Agent node with empty instructions, invalid Task schema JSON, Task max rounds outside 1 to 20 and a non-E.164 transfer number ("12345") do not block save.
- N [004] Save order: PATCH update-agent and PATCH update-llm in parallel first; `PUT /flows/{id}` only after both succeed.
- N [004] Flow record has `is_active` (spec only knew activate/deactivate endpoints). New flows are named "Untitled Flow" server side while the header shows the agent name.
- N [004] `/flows/generate` request sends node `config` but no positions; `/agents/:id/flow?configure=<tab>` deep-links Global Settings (`model, voice, call-behavior, functions, advanced, knowledge-base, quality-checks`).
- N [004] Flow Global Settings Call Behavior has no Ring Duration; Model tab helper "Azure is the default; OpenAI is a fallback when the same model isn't deployed on Azure."
- N [004] Agent node showed no tools picker when the agent has no functions.
- N [004] Say node "Allow Interruptions" defaults ON; API Call "Speak during API call" is a toggle (default ON) whose OFF text is "API call executes silently, then continues to next node"; End node Reason defaults `call_completed`.

## 005 tools / knowledge

- C [005] The predefined-tool library IS fetched by the Functions tab (`GET /tools/predefined/?limit=100&offset=0`, returns `end_call` and a legacy warm `transfer_call` preset), though no picker is shown.
- C [005] Only Custom API Call has a "Simulation mock response" field; End Call, Transfer Call and Press Digit dialogs have none (spec: every type).
- N [005] Transfer tool create sends both the new and the legacy shape in one payload: `transfer_destination:{type, routing_type, routing_instructions, transfer_type, warm_transfer_config}` plus `transfer_option:{type}`.
- N [005] Custom API: methods POST, GET, PUT, DELETE (no PATCH, while the flow API node has PATCH but no DELETE); timeout 120000; URL not validated; no headers/auth fields. Press Digit: Description, Delay 1000 and Cooldown 5000 appear only after "Enable Press Digit" is switched on.
- C [005] KB "+ Attach source" dialog is only a picker of existing documents (search + checklist). No upload, Markdown or URL option exists despite the empty-state copy. Confirm with nothing selected sends `{kb_ids:[]}`.
- N [005] KB upload dialog: Document Name + drop zone "PDF, DOCX - max 20 MB", Upload disabled until a file is chosen; two entry buttons (header and empty state).
- N [005] Analysis variable dialog: snake_case is advised but not enforced ("Customer Mood" sent as is); Predefined Choices stay available for Boolean and Number types.

## 006 calls / analytics

- N [006] Call list page sizes 10, 20, 50, 100; sort options map to `start_timestamp`/`duration` × `desc`/`asc`. No column-visibility control, no export.
- C [006] "Your label" filter offers "Any" too, is sent as `annotation_label`, is counted in the Filters badge but gets no chip. From/To number values are sent unencoded (`from_number=+1555`, the `+` becomes a space server side). Dates are sent as UTC ISO of local midnight.
- C [006] Dashboard period presets do not fetch until "Apply filters"; Refresh refetches only `/dashboard/stats`. Stats response nests KPIs under `overview` and adds `avg_cost`; quality response adds `prior_window`.
- C [006] The standalone analytics chat page is gone; only the floating panel remains (expandable, "New chat"). Error copy "Something went wrong. Please try again."
- N [006] Billing: preset chips ($25, $100, $500, $1000) start checkout in one click (no confirm); custom amount has no maximum and accepts decimals; below $5 the Add click silently does nothing. Feature usage window is a fixed last-30-days label. `/usage/me` returns `total_raw_cost_usd` and `total_billable_cost_usd` (raw vs marked-up cost). Transactions page sizes 10/20/50, no filters.

## 007 quality / evals

- C [007] The built-in set is 12 evaluators and differs from the spec list: anomaly_detection, factual_consistency, flow_completion, intent_fulfillment, kb_relevance, **audio_silence** ("Long silences", reads the recording), node_dead_end, process_reward, stuck_loop_detector, tool_call_correctness, transition_correctness, **latency_slo** ("Turn latency"). Evaluator types: `anomaly`, `class`, `audio_quality`, `process_reward`.
- N [007] Enabled by default on a new flow agent: Flow completion, Long silences, Per-node dead-ends, Stuck loops, Turn latency (all free). All LLM-judge checks and Anomaly detection start off.
- N [007] Settings quirks: Long silences default max 3000 ms while its helper says "default 5000ms"; Intent fulfillment Sample rate accepts 150 (schema max 100); Stuck loops (int 2 to 10) renders as a plain text box; Transition correctness judge model is a free-text field.
- N [007] Toggle and Save settings both PUT the full `{enabled, config}`; editing shows Discard / Save settings per card.
- N [007] Custom check flow is two-step (template cards, then form with Back). Phrase check sends `description:null` when empty. Create enables once Name and pattern/question are filled.
- N [007] Calibration `min_sample_for_signal` = 5.

## 008 testing / simulation

- N [008] `/tests/categories` returns a `color` per category and is sorted by name; the create dialog defaults to Bad Behavior.
- N [008] Generate dialog clamps count to 1..20, button label pluralises ("Generate 1 Test Case"), "All Categories" sends `category_id:null`, guidance placeholder "e.g., Focus on Hindi language scenarios, test financial advice boundaries".
- N [008] Testing page works for flow agents too.
- N [008] Simulations page agent filter is client side; there is no button to start a simulation from this page. GETs use `limit=50`.
- C [008] New dataset dialog has no agent field (API supports `agent_id`); empty Name shows "Name required". Dataset items GET uses `limit=500`.

## 009 issues

- C [009] Window and Source filters do not refetch the list; only Agent and Status do. Source only changes the Detect button to "Detect (incl. sims)" and the `include_simulations` flag (spec: Source controls both list and detect).
- N [009] Detect is disabled until an agent is chosen. Status options are lower-case raw values (all, open, validating, validated, applied, dismissed).

## 010 channels

- N [010] Page eyebrow is "CHANNELS" while the sidebar says "Phone Numbers". Origination URI is a single fixed `sip:1bf5vp09rrg.sip.livekit.cloud` with copy button.
- N [010] Import validation copy: "Phone number must be in E.164 format (e.g., +14155551234)" and "Enter hostname or IP address only (e.g., termination.example.com or 192.168.1.1), not a full SIP URI". Empty submit shows nothing. Payload includes client-supplied `user_id`.
- N [010] WhatsApp dialog: placeholders, Cloud API Version default "23.0", shared webhook `https://calldash-api-prod.azurewebsites.net/api/whatsapp/webhook`, Meta docs icon link; Phone Number ID is not validated as numeric; failure copy "Failed to create WhatsApp channel. Please try again."
