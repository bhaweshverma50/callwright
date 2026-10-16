# DELTA resolution: specs 004, 005, 006

Resolution of the live UI walkthrough findings (`DELTA.md`, 2026-10-16) tagged [004], [005] and
[006], plus node-panel, settings and filter details taken from the evidence files
(`flow-builder.md`, `flow-global-settings.md`, `knowledge-base.md`, `calls.md`, `dashboard.md`,
`billing-shell.md`, `blocked-requests.json`, `data/tools-predefined.json`). Rows marked
"(evidence)" expand a DELTA bullet into the field-level detail it summarises.

Decisions: **ADOPT** = Callwright has this behaviour; **IMPROVE** = the reference has a gap or bug
and Callwright specifies the correct behaviour; **SKIP** = not copied.

## 004 flow agents

| Finding (short) | Spec | Decision | Where applied, or reason |
|---|---|---|---|
| Canvas toolbar has only Auto-layout and Fit to screen, icon-only, no tooltips | 004 | ADOPT | spec FR-040 (adds zoom in/out, tooltips, accessible names), FR-005; tasks T100, T101 |
| No minimap | 004 | SKIP | Fit to screen, zoom and auto-layout cover navigation at the 200-node limit; spec Assumptions |
| No right-click menus | 004 | SKIP | Every action is in the side panel, toolbar or keyboard; spec Assumptions |
| Backspace deletes, Delete key does not; Delete Node/Edge buttons act without confirm | 004 | IMPROVE | spec FR-041, US1 scenario 9, edge case (Backspace inside a field); tasks T100, T101 |
| Start node: who speaks first; static or model-written greeting; user-first optional greeting; canvas shows speaker | 004 | ADOPT | spec FR-019, FR-042; data-model 2.1 start row; contracts/flows.yaml StartConfig; task T107 |
| Model-written greeting relies on a note that the entry agent prompt must greet | 004 | IMPROVE | spec FR-042, US2 scenario 7; data-model code E_GREETING_SOURCE; tasks T109, T110 |
| Condition categories: chips, duplicates ignored, no format check ("Bad Cat!") | 004 | IMPROVE | spec FR-043; data-model 2.1 condition row, E_CATEGORY_NAME; contracts/flows.yaml category name pattern; tasks T105, T109 |
| Categories do not create one output handle each | 004 | IMPROVE | spec FR-043, US1 scenario 12, edge cases (rename, delete category); task T105 |
| Edges out of a classify node hide the condition and explain routing | 004 | ADOPT | spec FR-021, FR-043 (category picked from a list); data-model Edge.category; task T105 |
| Edge labels not sanitised ("Route To Billing!" previewed as `route_to_billing!`) | 004 | IMPROVE | spec FR-044, US1 scenario 8, edge case (no doubled prefix); research R7; data-model section 4 derivation and shared vectors; tasks T109, T110 |
| Start edge must have a label | 004 | IMPROVE | spec FR-044 (labels only on model-chosen connections); data-model Edge.label; contracts/flows.yaml Edge.label; task T109 |
| Agent node with empty instructions not flagged | 004 | IMPROVE | Kept as warning W_NO_INSTRUCTIONS when the persona prompt is also empty (FR-026); US2 scenario 8 |
| Invalid Task schema JSON and max rounds outside 1 to 20 do not block save | 004 | IMPROVE | spec FR-045, FR-055, US2 scenario 8 (drafts save, publish blocked); data-model E_INVALID_FIELD; tasks T104, T107, T109 |
| Non-E.164 transfer number ("12345") accepted | 004 | IMPROVE | spec FR-045, US1 scenario 10; data-model 2.1 transfer row; tasks T104, T109 |
| Save blocked by validation dialog when the graph has errors | 004 | IMPROVE | Drafts with errors save, publish is blocked (FR-006, FR-027, FR-045) |
| Save is three requests (agent PATCH and LLM PATCH in parallel, then flow PUT) and can half-save | 004 | IMPROVE | spec FR-046, US1 scenario 11, edge case (concurrent agent edit); data-model section 9; contracts/flows.yaml SaveFlowRequest.agent_settings, AgentSettingsChange, Flow.agent_draft_revision, 412 agent_draft_changed; plan key point 2; tasks T102, T103 |
| Flow save payload omits webhook timeout, pronunciation, analysis model and nulls max duration and ring (risk of dropped settings) | 004 | IMPROVE | spec FR-046 (only changed fields sent, untouched settings never reset); data-model section 9 deep merge; quickstart section 8 |
| Flow record has `is_active` | 004 | SKIP | Live traffic is decided by the published and pinned agent version (002); a second flag would duplicate state; spec Assumptions |
| New flow named "Untitled Flow" server side while the header shows the agent name; empty name shows no error | 004 | IMPROVE | spec FR-048, edge case (empty name); data-model flows.name; contracts/flows.yaml SaveFlowRequest.name; tasks T103, T108 |
| Assistant request sends node configs but no positions | 004 | IMPROVE | spec FR-049, US5 scenario 6; data-model section 7 placement rule; task T113 |
| `?configure=<tab>` deep-links Global Settings (7 sections) | 004 | ADOPT | spec FR-050, US4 scenario 6; plan key point 6; task T111 |
| Flow Call Behavior has no Ring Duration | 004 | IMPROVE | spec FR-052, US4 scenario 6; task T111 |
| Model tab helper: one provider default with another as fallback | 004 | SKIP | Vendor-specific copy; provider options come from the 002 catalog and provider fallback is a runtime concern (003) |
| Agent node shows no tools picker when the agent has no functions | 004 | IMPROVE | spec FR-053, US4 scenario 7; task T112 |
| Say "Allow Interruptions" defaults on | 004 | ADOPT | Already FR-014; data-model 2.1 say row (default true) |
| API Call "Speak during API call" toggle, default on, silent when off | 004 | ADOPT | Already FR-016; 005 HttpRequestSpec `speak_during_execution` default true |
| End node reason defaults `call_completed` | 004 | ADOPT | Already FR-018; data-model 2.1 end row |
| (evidence) Agent node: instructions, entry line, context strategy, model, voice and STT overrides with "use agent default" | 004 | ADOPT | Already FR-009, FR-010; FR-054; tasks T081, T112 |
| (evidence) Overrides: disabled temperature shows 0.70 while fixed at 1.0; provider switch; STT language | 004 | IMPROVE | spec FR-054 (fixed value shown, provider change clears voice and model, language drives STT model), US4 scenario 9; task T112 |
| (evidence) Task "Result Schema" is raw JSON text only | 004 | IMPROVE | spec FR-055 (field list or JSON Schema view, live errors with line); task T107 |
| (evidence) Simple Comparison: Equals, Contains, Regex, Exists; Value still shown for Exists | 004 | IMPROVE | Already FR-013 (adds not equals, greater, less, otherwise edge); FR-056 hides Value for exists; data-model condition row; task T107 |
| (evidence) Extract: "Customer Name" becomes `customer_name`; types; downstream placeholder list | 004 | ADOPT | spec FR-015, FR-056; data-model extract row; task T107 |
| (evidence) API Call node: URL unchecked, methods without DELETE, raw JSON headers and body | 004 | IMPROVE | spec FR-016, FR-045; 005 FR-046 shared request form (same methods as HTTP tools, masked secret headers); 005 task T096 |
| (evidence) API Call "Function Name" wraps the body as `{name, args}` | 004 | SKIP | The body template already expresses any wrapper; one less concept |
| (evidence) Transfer node: cold or warm, private or public handoff, static or generated briefing, hold message | 004 | ADOPT | Already FR-017 via 005 TransferSpec |
| (evidence) Transfer node label empty by default | 004 | IMPROVE | Node Types table default label "Transfer" (already) |
| (evidence) Node card subtitles; expand editor for multiline fields | 004 | ADOPT | spec FR-057; task T106 |
| (evidence) Header: name, copyable ID, version chip with history, settings, save; side panel AI and Test tabs swap with selection settings | 004 | ADOPT | spec FR-058; task T108 |
| (evidence) Test tab runs the saved server config, not the unsaved canvas | 004 | IMPROVE | spec FR-047, US1 scenario 13; task T108 |
| (evidence) Global Settings: some sections save with header Save, others immediately, with no indication | 004 | IMPROVE | spec FR-051; plan key point 6; task T111 |
| (evidence) "Who speaks first" exists in both the Model tab and the Start node | 004 | IMPROVE | spec FR-052, US4 scenario 8; data-model start row; contract AgentSettingsChange rejects start_speaker; task T111 |
| (evidence) Advanced section holds post-call analysis model and analysis variables | 004 | ADOPT | spec FR-050 (editor owned by 007); task T111 |

## 005 tools and knowledge

| Finding (short) | Spec | Decision | Where applied, or reason |
|---|---|---|---|
| Predefined tool library fetched by the Functions tab but no picker shown | 005 | ADOPT | spec FR-043, US1 scenario 8; data-model "Tool presets"; contracts/tools.yaml `GET /tools/presets`, ToolPreset; tasks T093, T094, T095 |
| Predefined transfer preset uses a legacy shape | 005 | IMPROVE | spec FR-043 (presets stored in the current shape), FR-045 |
| Only Custom API Call has a simulation mock field | 005 | ADOPT | spec FR-044, FR-001, FR-041, FR-042 adjusted, US5 scenario 4; data-model mock_response CHECK and fixed simulated outcomes; contracts/tools.yaml mock_response notes, mock-coverage description; task T100 |
| Transfer create sends new and legacy shapes in one payload | 005 | IMPROVE | spec FR-045, US1 scenario 9; data-model `extra = "forbid"`; contracts/tools.yaml ToolCreate and ToolUpdate `additionalProperties: false`; tasks T093, T094; quickstart section 7 |
| Custom API methods POST, GET, PUT, DELETE while the flow node has PATCH but no DELETE | 005 | IMPROVE | Already FR-014 (all five); FR-046 same methods and options for tools and webhook nodes; HttpRequestSpec description; task T096 |
| Custom API timeout default 120000 ms | 005 | IMPROVE | Kept FR-014 range 1 to 30 s (default 8 s): a two-minute wait would stall a live call |
| Custom API URL not validated ("notaurl" sent) | 005 | IMPROVE | spec FR-046, US2 scenario 8 (plus FR-021 https and address guard); task T096 |
| Custom API has no headers or auth fields | 005 | IMPROVE | Already FR-014 headers and FR-024 encrypted, masked secret headers |
| Press Digit description, delay and cooldown appear only after an "Enable" switch | 005 | SKIP | Attaching or detaching the tool decides availability; a disabled-but-attached tool confuses; spec Assumptions |
| (evidence) Function type dialog with four types, descriptions and a read-only type id | 005 | ADOPT | Already FR-001, FR-003 (type immutable); task T032 |
| (evidence) Required fields rely on the browser's generic "Please fill in this field." | 005 | IMPROVE | spec FR-046 (inline messages naming the field, Save disabled while invalid); task T095 |
| KB "+ Attach source" is only a picker of existing documents; no upload | 005 | IMPROVE | spec FR-047, US4 scenario 8; task T099 |
| Attach empty state promises Markdown files and URLs that do not exist | 005 | IMPROVE | spec FR-047 (copy names only PDF and DOCX); Markdown and URL stay later additions (Assumptions) |
| Attach Confirm enabled with nothing selected, sends `{kb_ids: []}` | 005 | IMPROVE | spec FR-047, US4 scenario 9; contracts/knowledge.yaml setAgentKnowledgeBases description; task T099 |
| KB upload dialog: name, drop zone with types and 20 MB, Upload disabled until a file is chosen, two entry buttons | 005 | ADOPT | spec FR-048, US3 scenario 8; data-model `display_name`; contracts/knowledge.yaml upload `display_name`, Document.display_name; tasks T097, T098 |
| (evidence) No chunking, embedding model, top-k or re-index controls | 005 | ADOPT | Already Assumptions (search configuration fixed in v1) |
| Analysis variable dialog: snake_case advised but not enforced; choices shown for Boolean and Number | 005 | IMPROVE | Not applied here: analysis variables are owned by 007-quality-evals (`analysis_vars`). Forward to 007: convert names to snake_case on entry and hide choices for Boolean. 005 Assumptions note the ownership |

## 006 calls and analytics

| Finding (short) | Spec | Decision | Where applied, or reason |
|---|---|---|---|
| Call list page sizes 10, 20, 50, 100 | 006 | ADOPT | spec FR-001 adjusted, US1 scenario 8; contracts/calls.yaml page_size description; task T092 |
| Sort by start time or duration, each ascending or descending | 006 | ADOPT | Already FR-003 (plus cost and average latency) |
| (evidence) Every filter change refetches immediately in Call History | 006 | ADOPT | Already FR-005 and task T017 (URL-synced filters) |
| No column-visibility control | 006 | IMPROVE | spec FR-034, US1 scenario 12; task T092 |
| No export | 006 | IMPROVE | spec FR-035, US1 scenario 13; contracts/calls.yaml `GET /calls/export`; data-model CallListQuery; tasks T090, T091 |
| "Your label" filter offers "Any" | 006 | ADOPT | spec FR-036 ("Any" means not applied) |
| "Your label" is counted in the badge but gets no chip | 006 | IMPROVE | spec FR-036, US1 scenario 9; task T092 |
| "Needs review" label value in the filter | 006 | SKIP | Label values are owned by 007 (good, bad); the filter follows 007's values; spec Assumptions |
| (evidence) Separate Type (web, inbound, outbound) and Channel (WebRTC, SIP, WhatsApp) filters | 006 | SKIP | Callwright's channel value already encodes direction and transport; spec Assumptions |
| From/To number values sent unencoded (`+` arrives as a space) | 006 | IMPROVE | spec FR-037, US1 scenario 10; contracts/calls.yaml FromNumber, ToNumber; data-model CallListQuery and digit expression indexes; tasks T088, T089, T092 |
| Dates sent as UTC instants of local midnight | 006 | IMPROVE | spec FR-038, US1 scenario 11; contracts/calls.yaml start_date, end_date, tz; data-model CallListQuery; tasks T088, T089 |
| Dashboard period presets do not fetch until "Apply filters" | 006 | IMPROVE | spec FR-039, US3 scenario 7; task T093 |
| Dashboard Refresh refetches only the stats request | 006 | IMPROVE | spec FR-039, US3 scenario 8; task T093 |
| (evidence) Active filter chip row with removable range and "Clear all" | 006 | ADOPT | spec FR-040, US3 scenario 7; task T093 |
| (evidence) Dashboard default period is All time | 006 | SKIP | Keep last 30 days (FR-017): faster first load and a more useful first view |
| Stats nest KPIs under `overview` and add average cost | 006 | ADOPT | Already FR-018; contracts/dashboard.yaml `kpis` with `cost_per_call_usd` |
| Quality response adds `prior_window` | 006 | ADOPT | Already FR-020; contracts/dashboard.yaml DashboardQuality.prior_window |
| Standalone analytics chat page removed; floating panel with expand, "New chat" and suggested questions | 006 | ADOPT | Already US5, FR-023, task T070; spec Assumptions (no separate page) |
| Assistant error copy is generic ("Something went wrong") | 006 | IMPROVE | spec FR-041, US5 scenario 6; task T094 (402, 429, 503, declined) |
| Billing: preset chips start checkout in one click, custom amount has no maximum, a below-minimum Add does nothing silently, transactions have no filters | 006 | IMPROVE | Not applied here: billing UI and API are owned by 001-platform-foundation. Forward to 001: confirm before checkout, a maximum amount, an inline minimum message, transaction type and date filters |
| Billing: fixed last-30-days usage window; usage returns raw and billable totals | 006 | ADOPT | Not applied here: usage reporting is owned by 001 (`usage.yaml`). Forward to 001: keep raw versus billable totals; offer a selectable window |

## Totals

| Spec | ADOPT | IMPROVE | SKIP | Rows |
|---|---|---|---|---|
| 004 | 13 | 24 | 5 | 42 |
| 005 | 5 | 11 | 1 | 17 |
| 006 | 9 | 9 | 3 | 21 |
| All | 27 | 44 | 9 | 80 |

Items not applied in 004 to 006 folders (owners must pick them up): analysis-variable dialog
(007), billing page and usage window (001). No architecture change is required: the atomic flow
save uses the existing 002 `agents.service.update_draft` call inside 004's transaction, the same
cross-module service pattern already used by 004 creation and by 005 attachments.
