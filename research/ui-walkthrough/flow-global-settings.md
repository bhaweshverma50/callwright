# Flow Global Settings (flow builder "Global Settings" modal)

Live walkthrough, 2026-10-16, agent `GkFGZHpQ0GXgXoix9VRKc`. Screens: `screens/gs-*`. Section texts captured earlier are in `research/live/gs-*.txt`.

## Shell

- Large modal titled "CONFIGURE · <section>", close button (aria-label "Close configure"). Escape closes it.
- Left nav groups: **CONVERSATION** (Model, Voice, Call Behavior, Functions, Advanced), **CONTEXT** (Knowledge Base), **EVALUATION** (Quality Checks).
- URL param `?configure=` = `model | voice | call-behavior | functions | advanced | knowledge-base | quality-checks`.
- There is no Save inside the modal for Model / Voice / Call Behavior / Advanced: those values go out with the header **Save** (PATCH update-agent + update-llm). Functions, analysis variables, KB attach and quality checks write immediately through their own endpoints.

## Model

Intro: "Sets the default model and provider for every Agent node in this flow. Individual nodes can override these values from the node panel on the canvas."

| Field | Control | Default | Options | Helper |
|---|---|---|---|---|
| Model | select | GPT-5.1 | GPT-5.1, GPT-5.2, GPT-5 Mini (no prices here) | |
| Provider | select | Azure OpenAI | Azure OpenAI, OpenAI | "Azure is the default; OpenAI is a fallback when the same model isn't deployed on Azure." |
| Who speaks first | select | Agent speaks first | Agent speaks first, User speaks first | |

No temperature control at flow level.

## Voice

Same component as the single-prompt Voice Settings tab (see `agent-single.md` 4.2) with two differences: Noise Cancellation shows the real value "Sanas Voice Isolation (Default)" with helper "Removes noise + background voices (best for noisy callers)", and the Voice Model select shows no prices. STT Provider, STT Model, Voice Provider, Voice Model, voice list (search for ElevenLabs, gender filter for Cartesia), Voice Temperature 0 to 2 step 0.1 (0.90), Voice Speed 0.5 to 2 step 0.1 (1.00x), Volume 0 to 2 step 0.05 (0.94).

## Call Behavior

| Field | Control | Default | Range | Helper |
|---|---|---|---|---|
| End Call on Silence | slider | 30s | 10s to 5m step 10s; marks 10s,1m..5m | "Automatically end the call after this duration of silence (10 seconds - 5 minutes)" |
| Maximum Call Duration (Optional) | number, minutes | empty (null) | | "Leave empty for no limit. Minimum: 0.5 minutes (30 seconds)" |
| Interruption Sensitivity | slider 0 to 1 step 0.05 | 0.95 | Low/Medium/High | as single form |
| Responsiveness | slider 0 to 1 step 0.05 | 0.79 | Slow/Medium/Fast | as single form |

No Ring Duration field at flow level (the single form has one).

## Functions

- Empty state: "Add Function" button, "No functions configured yet / Add functions to enable your agent to perform actions during calls". GETs `/tools/llm/{llm_id}` and `/tools/predefined/?limit=100&offset=0` (the predefined library IS fetched here; it returned `end_call` and `transfer_call` presets, saved in `data/tools-predefined.json`, but no UI to pick them was visible).
- "Add New Function" dialog. **Function Type \*** select with descriptions:
  - End Call: "End the conversation with an optional message"
  - Transfer Call: "Transfer call to another number or agent"
  - Press Digit: "Press DTMF digits during IVR navigation"
  - Custom API Call: "Make HTTP API request during the call"
- A read-only **Type** field shows the type id (`end_call`, `transfer_call`, `press_digit`). Required fields use native browser validation ("Please fill in this field.").

| Type | Fields (placeholder / default) | Blocked request |
|---|---|---|
| End Call | Function Name \* ("e.g., end_call, hangup, finish_conversation"); Description \* ("What triggers this function to be called?"); Goodbye Message (Optional) ("e.g., Thank you for calling. Have a great day!") | POST `/tools/create` `{tool_id, llm_id, tool_config:{name, description, message, type}}` |
| Transfer Call | Function Name \* ("e.g., transfer_call, forward_to_agent, escalate"); Description \* ("When should this transfer happen?"); Routing Type \* select: Static (Fixed Number) "Always transfer to the same number" / Dynamic (AI Decides) "AI determines the number based on conversation"; Static: Transfer Phone Number \* ("+1234567890"); Dynamic: Routing Instructions \* ("For billing issues, transfer to +19995551111. For technical support, transfer to +19995552222.", helper "Provide instructions for when to transfer to which numbers"); Transfer Type \* select: Cold Transfer (Direct) "Directly transfer without introduction" / Warm Transfer (With Introduction) "Introduce the caller before transferring". Warm reveals "Warm Transfer Settings": Handoff Type \* (Private (Customer Doesn't Hear) "Brief the agent privately before connecting customer" / Public (Customer Hears)); Briefing Message Type \* (Static Message (Fixed Text) "Use the same message every time" / AI-Generated (Prompt-Based) "AI generates message based on prompt"); Briefing Message \* ("I have a customer who needs assistance with their account.", helper "This exact message will be used for every transfer") or Briefing Prompt \* (helper "AI will use this prompt to generate a contextual briefing") | POST `/tools/create` `{tool_id, llm_id, tool_config:{name, description, transfer_destination:{type, routing_type, routing_instructions, transfer_type, warm_transfer_config:{handoff_type, briefing_message_type, briefing_message}}, transfer_option:{type}, type}}` (both new and legacy keys are sent together) |
| Press Digit | Function Name \* ("e.g., press_digit, send_dtmf, navigate_ivr"); toggle "Enable Press Digit / Allow AI to press DTMF digits during IVR navigation" (default Disabled). Enabled reveals Description \* ("When should digits be pressed?"), Delay (ms) 1000, Cooldown (ms) 5000 | POST `/tools/create` `{tool_id, llm_id, tool_config:{name, description, enabled, delay_ms, cooldown_ms, type}}` |
| Custom API Call | Function Name \* ("e.g., check_availability"); Description \* ("What does this API call do?"); API URL \* ("https://api.example.com/endpoint", no URL format check: "notaurl" was sent); Method select POST (default), GET, PUT, DELETE; Timeout (ms) 120000; Parameters (JSON Schema) \* with "Use Template" button (helper "Define the parameters your API expects in JSON Schema format"; template = object with `appointment_available_ts` (string, required) and `doctor_name` (string, optional)); Simulation mock response ("Returned verbatim when this tool is called during a simulation. JSON or plain text. Leave empty to surface a pre-flight warning before sims run.") | POST `/tools/create` `{tool_id, llm_id, tool_config:{name, description, url, method, timeout_ms, parameters, type}}` (`mock_response` omitted when empty) |

- Only Custom API Call has a mock-response field; End Call, Transfer and Press Digit do not.
- No headers, auth or body-template fields on the Custom function (the flow API Call node has them).

## Advanced

Same sections as the single form Advanced tab (Webhook URL + timeout 3000 ms; Voicemail toggle and radio; Keypad Input toggle with Timeout, Termination Key, Digit Limit; Background Audio toggle with sound list, upload, volume; Pronunciation Dictionary rows), plus an analysis-variables editor that the create form lacks:

**POST-CALL ANALYSIS**: "Analysis Model (Optional)" select (None (use agent's main model), GPT-5.1, GPT-5.2, GPT-5 Mini); "Add Variable" button; empty state "No analysis variables defined yet / Add variables to extract structured data from call transcripts".

**Add Analysis Variable** dialog:

| Field | Control | Notes |
|---|---|---|
| Variable Name \* | text, placeholder "e.g., appointment_scheduled, customer_sentiment" | helper "Use snake_case naming convention". Not enforced: "Customer Mood" was accepted and sent. |
| Variable Type \* | select with descriptions | Boolean (Yes/No) "True or false values"; String (Text) "Free-form text" (default); Number "Numeric values" |
| Description | multiline, placeholder "What should this variable extract from the call?" | helper "Helps the AI understand what to extract" |
| Predefined Choices (Optional) | chip input "Add a choice and press Enter" + Add | helper "For categorical data, specify possible values (e.g., positive, neutral, negative)". Stays visible for Boolean and Number. |
| Cancel / Save Variable | buttons | Save disabled until a name is typed. Blocked: POST `/analysis/variables` `{variable_id, agent_id, name, type, description, choices[]}`. On failure the dialog stays open with a "Network Error" snackbar. |

## Knowledge Base

- Copy: "Documents attached here are searchable by every agent node during the call. Useful for FAQs, product specs, policies, and reference content." Empty state "No knowledge sources attached / Upload PDFs, Markdown files, or paste a URL to give this agent reference material to draw from during calls." Button "+ Attach source".
- "+ Attach source" opens **Select Knowledge Bases**: a search box ("Search...") and a list of existing KB documents ("No knowledge bases found" here), Cancel / Confirm. There is NO upload, Markdown or URL option in this dialog, despite the empty-state copy. Confirm is enabled even with nothing selected and sends POST `/knowledge-bases/agents/{agent_id}` `{kb_ids:[]}`.

## Quality Checks

12 built-in evaluators, alphabetical by display name. Each card: name, scope chip (per-call / per-turn), cost chip (Free / LLM judge), description, enable switch, and an expand chevron (aria-label "Configure", then "Hide settings") when it has settings. Editing a field shows **Discard** and **Save settings**. Toggling the switch saves immediately.

| Display name | name | Scope | Cost | Default on | Settings (default; range) |
|---|---|---|---|---|---|
| Anomaly detection | anomaly_detection | per-call | Free | off | Anomaly threshold (0 to 1) 0.7 "KNN mean cosine distance above which a call is flagged."; Reference window (days) 30 (1 to 365) "Compare against calls ending in the last N days."; Min neighbours before scoring 30 (5 to 500) "Below this, the detector returns insufficient_data instead of a number."; KNN k 10 (1 to 50) "Number of nearest neighbours to average."; Backfill per run 5 (0 to 20) "Embed this many un-embedded neighbour calls per run (0 = off)." |
| Factual consistency | factual_consistency | per-call | LLM judge | off | Judge model select: gpt-5-mini only, "Only model available for evaluator judges." |
| Flow completion | flow_completion | per-call | Free | ON | none (flow only) |
| Intent fulfillment | intent_fulfillment | per-call | LLM judge | off | Judge model gpt-5-mini ("Uses the OpenAI eval-judge model. Other tiers are not enabled for evaluators."); Sample rate (%) 100 (1 to 100) "100 = every call. Lower for cost control." (150 was accepted by the form) |
| KB retrieval relevance | kb_relevance | per-call | LLM judge | off | Judge model gpt-5-mini |
| Long silences | audio_silence | per-call | Free | ON | Max silence (ms) 3000 (500 to 60000) "Pass when no single silence exceeds this; default 5000ms (5s)." (helper contradicts the 3000 default); Silence threshold (dB below avg) -40 (-80 to -10) "How quiet a stretch must be to count as silent. -40 ≈ very quiet."; Min silence run (ms) 1000 (200 to 10000) "Ignore silences shorter than this. Keeps natural conversational pauses out." Reads the recording, not the transcript. |
| Per-node dead-ends | node_dead_end | per-call | Free | ON | none (flow only) |
| Per-turn progress | process_reward | per-turn | LLM judge | off | Judge model gpt-5-mini |
| Stuck loops | stuck_loop_detector | per-call | Free | ON | "Max visits per node before flagging as stuck" 3 (schema int 2 to 10, rendered as a plain text box) |
| Tool call correctness | tool_call_correctness | per-call | LLM judge | off | Judge model gpt-5-mini |
| Transition correctness | transition_correctness | per-call | LLM judge | off | "Judge LLM model" free-text field, value gpt-5-mini (schema type string). Description mentions map-reduce per-transition judging with shuffled alternatives. |
| Turn latency | latency_slo | per-turn | Free | ON | Threshold (ms) 3000 (100 to 30000) "Turns slower than this are flagged. Industry default: 3000ms." |

Blocked writes:
- Toggle or Save settings: PUT `/evals/agents/{agent_id}/config/{evaluator_name}` `{enabled, config:{judge_model, sample_rate_pct}}` (full config object each time).

**Add custom check** dialog: "Add a custom check / Pick a template, the system fills in the rest." Two template cards:
1. **Required / forbidden phrase**: "Pass when a phrase or regex appears (required) or is absent (forbidden)." Form "Configure custom check": Name, Description (optional), Phrase or pattern ("A substring or regex (see Regex toggle)."), Mode select required / forbidden ("Required = pass when present. Forbidden = pass when absent."), Look in select agent_text / user_text / both ("Whose turns to scan."), toggles "Treat as regex" and "Case sensitive". Buttons Back, Cancel, Create check (enabled once Name and pattern are filled). Blocked: POST `/evals/evaluators/custom` `{name, description:null, evaluator_type, config:{pattern, mode, target, regex, case_sensitive}}`.
2. **LLM judge, custom question** (chip "LLM judge"): "Plain-English yes/no criterion. gpt-5-mini scores each call." Fields: Name, Description (optional), Question for the judge ("Plain English. Example: 'Did the agent ask all three safety questions?'"), Judge model select (gpt-5-mini only). Blocked: POST `/evals/evaluators/custom` `{name, description, evaluator_type, config:{question, judge_model}}`.

Raw evaluator config response: `data/evals-config-flow-agent.json` (and `research/live/evaluator-catalog.json`).
