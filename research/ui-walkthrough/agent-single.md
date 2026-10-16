# Agents: list, type chooser, new flow, new single-prompt form

Live walkthrough, 2026-10-16. Screens in `screens/` (prefixes `agents-`, `single-`). Templates are in `templates.md`. Note: UI strings that contain long dashes are quoted here with a plain hyphen.

## 1. Agents list (`/agents`)

| Control | Type | Details |
|---|---|---|
| Header | text | eyebrow "AGENTS", title "Your voice agents.", subtitle "Build, configure, and manage the agents that answer your phones." |
| New agent | button | goes to `/agents/new` |
| Search agents by name or ID… | text input, client side | no request; counter changes to "0 OF 1 AGENT"; empty state "No agents match “zzz”" / "Try a different name or ID." |
| Count line | text | "1 AGENT · CLICK TO OPEN" |
| Agent card | card (click opens agent) | `#01`, name, type badge (FLOW / SINGLE), agent id, MODEL (`gpt-5.1`), VOICE (provider name, e.g. "Elevenlabs"), LANG (flag + `EN`), CREATED date |
| Duplicate agent | icon button with tooltip "Duplicate agent" | No confirm. Blocked: POST `/agents/duplicate-agent/{id}`, no body. Failure shows a "Network Error" snackbar. |
| Delete agent | icon button | Opens dialog "Delete agent" / "Are you sure you want to delete Test Flow Agent? This action cannot be undone." with Cancel / Delete (Delete was not confirmed in this walkthrough). |

## 2. Type chooser (`/agents/new`)

- "Back to agents" link. Eyebrow "NEW AGENT", title "How should this agent think?", copy "Pick how the agent decides what to say next. You can't change this later, so choose the one that fits your conversation shape."
- Two selectable cards (radio behaviour) and a Continue button (enabled immediately, Single-prompt is preselected):
  - **Single-prompt agent**: "One system prompt drives the whole conversation. Best for open-ended assistants where the LLM decides the path turn-by-turn." Bullets: Free-form prompt with dynamic variables; Tool-calling (functions, transfers, end-call); Knowledge-base attachments. Continue goes to `/agents/templates`.
  - **Flow agent**: "A visual graph of nodes (greet, ask, branch, transfer). Best for scripted journeys, qualification flows, and hand-offs you need to control step-by-step." Bullets: Drag-and-drop canvas with conditions and branches; Per-node prompts, tools, and variable extraction; Each node can use a different model. Continue goes to `/agents/new/flow`.

## 3. New flow agent (`/agents/new/flow`)

| Control | Type | Default | Notes |
|---|---|---|---|
| Back to type | link | | |
| AGENT NAME * | text, placeholder "e.g. Lead-qualification flow" | empty | "Create & open flow builder" stays disabled until non-empty |
| LANGUAGE | select | 🇺🇸 English (US) | helper "Voice and STT defaults are seeded for this language. You can refine them later." 47 options (list in 4.1) |
| Create & open flow builder | primary button | disabled | Blocked: POST `/llms/create-llm` `{llm_id, model, provider, model_temperature, general_prompt, start_speaker}`; on failure a "Network Error" snackbar, stays on page |

## 4. New single-prompt agent (`/agents/new/single`)

Header: "Back to agents", eyebrow "NEW AGENT", "Configure your new agent.", "Fine-tune every aspect of your voice agent - from prompt and voice to call behavior and webhooks." Buttons **Test agent** (on the unsaved form it only shows the snackbar "Test functionality coming soon!") and **Save agent**. Four tabs. A sticky **ESTIMATED COST** card sits on the right on every tab.

### 4.1 Tab "Basic Configuration"

| Label | Control | Default | Options / range | Helper text |
|---|---|---|---|---|
| Agent Name * | text, placeholder "e.g., Customer Support Agent" | "" | | "A descriptive name to identify your agent" |
| Language * | select with flags | English (US) | 47 options, see below | "The primary language your agent will speak" |
| (section) LLM Configuration | | | | |
| AI Model * | select, each option shows $/min | GPT-5.1 ($0.0000/min) | GPT-5.1 ($0.0000/min), GPT-5.2 ($0.0000/min), GPT-5 Mini ($0.0015/min) | |
| Provider | select | Azure OpenAI | Azure OpenAI, OpenAI | "Which LLM provider to use for this agent" |
| Model Temperature | slider 0 to 2 step 0.1, marks Precise / Balanced / Creative, value label "1.00" | 1 | disabled for all 3 models | "Temperature is fixed at 1.0 for GPT-5 series models" |
| General Prompt (System Prompt) * | multiline, placeholder "You are a helpful customer support agent. Your role is to..." | "" | | "The main instructions that define your agent's behavior and personality. Type \n for newlines, \t for tabs." |
| Start Speaker | select | Assistant (AI speaks first) | Assistant (AI speaks first), User | "Who should speak first when the call connects". Choosing User does NOT hide Begin Message. |
| Begin Message | multiline, placeholder "Hello! Thanks for calling. How can I help you today?" | "Hello! How can I assist you today?" | | "The first message your agent will say when the call starts" |
| Dynamic Variables (Optional) | chip input, placeholder "Enter variable name and press Enter (e.g., customer_name, order_id)" | none | Enter adds a chip. Every `{{var}}` typed in the prompt is added automatically (deduplicated). No name validation: "bad name!" was accepted as a chip. | "Variables that can be dynamically set per call (e.g., customer_name, order_id)" |

Languages (47, in menu order): Multilingual, Arabic, Bengali, Chinese, Chinese (Simplified), Chinese (Traditional), Danish, Dutch, English, English (US), English (Australia), English (UK), English (New Zealand), English (India), French, French (Canada), German, Gujarati, Hebrew, Hindi, Hindi (Latin), Indonesian, Italian, Japanese, Kannada, Korean, Malayalam, Malay, Marathi, Norwegian, Odia, Punjabi, Polish, Portuguese, Portuguese (Brazil), Russian, Spanish, Spanish (Latin America) (appears twice: `es-419` and `es-LATAM` share the label), Swedish, Tamil, Tamasheq (no flag), Telugu, Thai, Turkish, Ukrainian, Urdu. Alphabetical by label except Multilingual first.

**Estimated cost card** (live, recalculates on every change):
- STT: "Deepgram" $0.0085/min
- LLM: "Azure OpenAI · gpt-5.1" $0.0000/min (gpt-5-mini shows "20k in tokens/min · 200 out tokens/min" and $0.0015/min; gpt-5.1/5.2 show $0 because the catalog has no price for them)
- TTS: "ElevenLabs · eleven_flash_v2_5", "750 chars/min", $0.0450/min
- PLATFORM: "CallDash fee" $0.0500/min
- "Total (base)" $0.1035/min (gpt-5.1) or $0.1050/min (gpt-5-mini); footer "Surcharge if usage exceeds bundle".
- There is no NC line in the card even though NC is a separate billing component.

### 4.2 Tab "Voice Settings"

Section "Speech-to-Text (STT)":

| Label | Control | Default | Options (label, description, price) | Helper |
|---|---|---|---|---|
| STT Provider | select | Deepgram | Deepgram, Sarvam AI, AssemblyAI | "The speech recognition service provider" |
| STT Model | select (renders blank when value is "" = Auto) | "" (Auto) | Deepgram: Auto (recommended) "nova-3 for English, nova-2 for others" $0.0085; Nova-3 "Best English accuracy" $0.0085; Nova-2 "Multilingual (36 languages)" $0.0058; Flux "Conversational, ultra-low latency, built-in turn detection" $0.0085. Sarvam AI: Saarika v2.5 "Transcribes in original language" $0.0060; Saaras v3 "Latest Sarvam STT model" $0.0060 (no Auto option, field still enabled and blank). AssemblyAI: Auto (recommended) "Streaming or multilingual based on language" $0.0030; Universal Streaming "English-focused" $0.0030; Universal Streaming Multilingual "Multilingual (es, fr, de, it, pt)" $0.0030 | "Leave as "Auto" to let the backend pick the best model based on language" |
| Noise Cancellation | select | renders blank; helper reads "No noise cancellation applied" | Sanas Voice Isolation (Default), Sanas Standard, AI Coustics, Off | helper text follows the option description |

Voice section:

| Label | Control | Default | Options | Helper |
|---|---|---|---|---|
| Voice Provider * | select | ElevenLabs | ElevenLabs, Cartesia, Fish Audio | "The text-to-speech service provider" |
| Voice Model * | select with $/min | Flash v2.5 ($0.0450/min) | ElevenLabs: Turbo v2.5 (Fastest) $0.045, Turbo v2 $0.045, Flash v2.5 $0.045, Flash v2 $0.045, Multilingual v2 (Best Quality) $0.09. Cartesia: Sonic 2 (Default), Sonic 2 (Speed/Emotion), Sonic 3 (Latest), Sonic Turbo (Fastest), all $0.0275. Fish Audio: S2.1 Pro (Latest), S2 Pro (Multi-Speaker), S1 (Standard), all $0.015. Switching provider applies that provider's default model. | "The specific model version for voice synthesis" |
| Voice * | inline scrollable list (not a modal on this page) | Jessica - Playful, Bright, Warm (ElevenLabs) | see below. Switching provider clears the selection (switching back to ElevenLabs does not reselect Jessica). | "The specific voice your agent will use" |
| Voice Temperature | slider 0 to 2, step 0.1, marks 0/1/2, value label "0.90" | 0.9 | | "Controls voice expressiveness. Higher values = more variation (0-2)" |
| Voice Speed | slider 0.5 to 2, step 0.1, marks 0.5x/1x/2x, label "1.00x" | 1.0 | | "Speaking rate of the voice. 1.0 is normal speed (0.5-2x)" |
| Volume | slider 0 to 2, step 0.05, marks 0/1/2, label "0.94" | 0.94 (thumb snaps to 0.95) | | "Audio output volume. 1.0 is default volume (0-2)" |

Voice browser per provider:
- **ElevenLabs**: "Search voices..." box, server side (GET `/voices/elevenlabs?page_size=100&search=sar&fetch_all=true`). 29 voices, each with name, description and a ▶ preview button. First 15: Dr. Jason, Arabella, Saavi - Natural Hindi Customer Care Agent, David Ashby, Anika - Hindi Customer Care Agent, Alok K - Customer Care, Liz- Customer Service Assistant, Henna, Bella - Professional, Bright, Warm, Roger - Laid-Back, Casual, Resonant, Sarah - Mature, Reassuring, Confident, Laura - Enthusiast, Quirky Attitude, Charlie - Deep, Confident, Energetic, George - Warm, Captivating Storyteller, Callum - Husky Trickster. Full list in `data/voices-elevenlabs.json` (workspace plus premade voices; each has `category`, e.g. `professional`).
- **Cartesia**: no search box; a "Gender Filter" select (All, Masculine, Feminine, Gender Neutral) that refetches (`gender=feminine` returned 542). 1043 voices with name, description, gender and language tags, no preview button. First 15: Skylar - Friendly Guide, Daniel - Modern Assistant, Gemma - Decisive Agent, Parker - Supportive Pal, Archie - Approachable Mate, Jacqueline - Reassuring Agent, Clive - Measured Expert, Ella - Caring Scout, Arlo - Service Specialist, Corey - Supportive Buddy, Lauren - Lively Narrator, Fabio - Logistics Expert, Supannee - Support Concierge, Cora - Service Specialist, Zander - Composed Advisor. Data: `data/voices-cartesia.json`.
- **Fish Audio**: no search, no filter, no paging, no preview. Shows the top 50 public voices by score (`total` = 1000) with a language tag and "N uses". The list is community voices such as "Super Smash Bros. 4/Ultimate Announcer", "Спокойный женский голос", "Valentino Narración Biblica Fer", "Farid Dieck", "Меллстрой", "ALEX_CHIKNA", "Mortal Kombat", Arabic voices, "ELITE", "voz de locutor k", "Energetic Male", "Sarah", "Smash Bros". Not curated for business use. Data: `data/voices-fishaudio.json`.

### 4.3 Tab "Call Behavior"

| Label | Control | Default | Range | Helper / live text |
|---|---|---|---|---|
| End Call on Silence | slider, value label "30s" | 30000 ms | 10000 to 300000, step 10000; marks 10s, 1m, 2m, 3m, 4m, 5m | "Automatically end the call after this duration of silence (10 seconds - 5 minutes)" |
| Maximum Call Duration (Optional) | number with "minutes" adornment, placeholder "e.g., 10 (10 minutes)" | 10 | decimals allowed | live helper "Max duration: 10m" (0.2 shows "12s", 2.5 shows "2m 30s", 61 shows "61m"); empty shows "Leave empty for no limit. Minimum: 0.5 minutes (30 seconds)". No inline error for 0.2 or 61. |
| Ring Duration (Optional) | number with "ms" adornment, placeholder "e.g., 5000 (5 seconds)" | 5000 | | live helper "Ring for 5s before connecting" (floors: 1500 shows "1s"; 60000 shows "1m"; -1 shows "Ring for -1s"); 0 or empty shows "How long the phone should ring before the agent answers" |
| Interruption Sensitivity | slider 0 to 1 step 0.05, marks Low / Medium / High | 0.95 | | "How easily the agent can be interrupted. Higher = more interruptible (0-1)" |
| Responsiveness | slider 0 to 1 step 0.05, marks Slow / Medium / Fast | label 0.79 (thumb at 0.8) | | "How quickly the agent responds to user input. Higher = faster responses (0-1)" |

### 4.4 Tab "Advanced" ("Advanced Settings")

**Webhook Configuration**
- Webhook URL (Optional): text, placeholder "https://your-api.com/webhook", helper "Receive real-time call events and updates via webhook".
- Webhook Timeout: number, "ms" adornment, default 3000, helper "Maximum time to wait for webhook response (milliseconds)".
- Observed: "notaurl" and a timeout of 50 were NOT rejected client side on create; the request went out (and was blocked).

**Voicemail Configuration**: custom toggle "Enable Voicemail Detection" / "Detect when a call goes to voicemail", state text Disabled/Enabled. When enabled it reveals a radio pair:
- "End call when voicemail is detected" / "The call will automatically end if voicemail is detected" (default)
- "Leave a message on voicemail" / "The AI will leave a pre-recorded message". Selecting it reveals "Message to leave" (multiline, placeholder "Hi, this is [Company]. Please call us back at...", counter "0/500 characters").

**User Keypad Input Detection**: "Enable the AI to listen for keypad input during a call" / "The AI will respond when any of the following conditions are met"; toggle. When enabled:
- Timeout: slider 1000 to 10000 ms, step 500, default 2.5 s, marks 1s, 2.5s, 5s, 7.5s, 10s. Helper "The AI will respond if no keypad input is detected within the set time".
- Termination Key: select, default `#`; options `#`, `*`, `0` to `9`. Helper "The AI will respond when the user presses the configured termination key (0-9, #, *)".
- Digit Limit: stepper (minus / plus), default 10, clamps at 1 and 99. Helper "The AI will respond immediately after the caller enters the configured number of digits".

**Background Audio**: toggle "Enable Background Audio" / "Play ambient sounds during calls". When enabled:
- Ambient Sound: select, helper "Continuous background sound that plays throughout the call", default Office Ambience. Options under the group header "Built-in Sounds": Office Ambience, City Ambience, Forest Ambience, Crowded Room, Hold Music, Keyboard Typing, Keyboard Typing 2 (a "Your Uploads" group appears when files exist; GET `/assets/audio-files` returned []).
- "Upload Custom Audio" button opens a file chooser, accept `.mp3,.wav,.ogg,.flac,.aac,.opus`, single file.
- Volume: slider 0 to 3 step 0.05, default 0.8, displayed as a percentage of 3 ("27%"), marks 0%, 50%, 100%. So 100% means a gain of 3.0.

**Post-Call Analysis**: "Analysis Model (Optional)" select, blank by default; options "None (use agent's main model)", GPT-5.1, GPT-5.2, GPT-5 Mini. Helper "AI model to use for analyzing call transcripts and extracting variables". The create form has no analysis-variables editor.

**Pronunciation Dictionary**: "Define how specific words should be pronounced. Words are replaced before TTS." "Add Entry" adds a row: Word (text), Say as (text), delete (trash icon).

### 4.5 Save, validation, blocked payloads

- Save agent with an empty form: error dialog "Couldn't create agent" / "2 ISSUES NEED ATTENTION" / 1. "Agent name is required" 2. "General prompt is required" / OK. After OK the form stays on the current tab.
- Name filled, no prompt, Cartesia with no voice: "General prompt is required", "Please select a voice".
- Valid form: blocked POST `/llms/create-llm` `{llm_id, model, provider, model_temperature, general_prompt, start_speaker, begin_message, dynamic_variables:[string]}`. Because the first write is blocked, the dialog shows "Couldn't create agent / 1 ISSUE NEED ATTENTION / Network Error". The follow-up `create-agent` call is never reached (its shape stays as documented in the functional spec).
- No unsaved-changes guard on the create form: "Back to agents" leaves immediately.

## 5. Account facts seen in GET responses

- GET `/auth/me` keys: `user_id, email, workspace_name, email_verified, credits_balance, max_concurrency, firebase_uid, is_admin`. `max_concurrency` is 1 on this account (a per-account concurrent call cap).
- GET `/assets/audio-files` returns `[]`.
