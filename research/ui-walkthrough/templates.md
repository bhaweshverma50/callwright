# Agent templates (`/agents/templates`)

Captured live on 2026-10-16. Raw bodies: `templates/_list.json` (GET `/templates`), `templates/_categories.json` (GET `/templates/categories`) and one file per template (`templates/<slug>.json`). The app never calls GET `/templates/{id}`: the list response already carries the full `config`, and "Use template" builds the create payload from it.

## Page UI

| Control | Type | Details |
|---|---|---|
| Back arrow | icon button | goes back to `/agents/new` |
| "BLANK / Start from scratch" card | card | "Create a blank agent and configure everything yourself"; opens `/agents/new/single` |
| Search templates… | text input | Server side: each change sends GET `/templates?search=<q>`. Matches name/description ("loan" returned only Collection Voice Bot, so description text is not fully searched, or matching is name-weighted). Empty result: "No templates found". |
| Category chips | single-select chips | `All`, `Automotive`, `Banking`, `E-Commerce`, `Healthcare`, `Telecom` (from GET `/templates/categories`, "All" prepended). Each click sends GET `/templates?category=<name>`. |
| Template card | card | category eyebrow (upper case), name, description, "Use template". Clicking anywhere on the card is the same as "Use template". |
| Use template | button | Immediately creates the agent (no preview, no confirm). Blocked request: POST `/llms/create-llm` with `{llm_id, model, model_temperature, general_prompt, start_speaker, begin_message}` (note: no `provider` key, unlike the flow and blank create). On failure a "Network Error" snackbar shows and the page stays put. |

Counts per category: Automotive 1, Banking 2, E-Commerce 1, Healthcare 2, Telecom 1, All 7.

## Template object

`{template_id, name, description, category, icon, color, config, sort_order, created_at}`

`config` keys (all 7 identical): `agent_name, model, model_temperature, language, start_speaker, begin_message, general_prompt, voice_provider, voice_model, stt_provider`. There is no `voice_id`, no tools, no variables, no KB, no call-behaviour block and no flow graph in any template. All templates are single-prompt.

Shared values across all 7: `model: "gpt-5.1-chat"` (the client maps this to `gpt-5.1`), `model_temperature: 0.7`, `language: en-US`, `start_speaker: assistant`, `voice_provider: elevenlabs`, `voice_model: eleven_flash_v2_5`, `stt_provider: deepgram`. None of the prompts use `{{variables}}`.

## The 7 templates

| sort | template_id | Name | Category | Icon / colour | Begin message | Prompt (chars) |
|---|---|---|---|---|---|---|
| 1 | tmpl_collection | Collection Voice Bot | Banking | AccountBalance / #c42423 | "Good morning, am I speaking with the account holder?" | 2016 |
| 2 | tmpl_telesales | Telesales Assistant | Banking | TrendingUp / #058244 | "Good morning, am I speaking with the account holder?" | 2215 |
| 3 | tmpl_telecom | Telecom Sales Agent | Telecom | PhoneInTalk / #1d55a5 | "Good morning, am I speaking with the account holder? This is Vista Telecom calling." | 1472 |
| 4 | tmpl_ecommerce | E-Commerce Sales Agent | E-Commerce | ShoppingCart / #ff5800 | "Good morning, am I speaking with the account holder? This is Vista Cart calling." | 1609 |
| 5 | tmpl_healthcare | Healthcare Triage & Booking | Healthcare | LocalHospital / #5e007e | "Welcome to Vista Healthcare. I am Vista AI. May I have your name, and how can I assist you today?" | 1673 |
| 6 | tmpl_auto_assist | Auto Assist & EV Support | Automotive | DirectionsCar / #058244 | "Welcome to Vista Auto Assist. Before we proceed, are you currently in a safe location?" | 1764 |
| 7 | tmpl_healthcare_checkin | Healthcare Check-in (agent_name "Healthcare Check-in Agent") | Healthcare | MedicalServices / #5e007e | "Hello, this is Vista Healthcare. I am calling to help you prepare for your upcoming appointment. May I confirm I am speaking with the right person?" | 976 |

### Prompt structure per template

- **Collection Voice Bot** (Vista First Bank, outbound collections for Consumer Durable / Two Wheeler / Cross-Sell loans): Role & Objective; Call Opening; Scenario 1 (third party answers); Scenario 2 (right party contact); Asking for Payment with 3 priorities (online on-call via payment link/UPI/bank site, branch visit, field-executive pick-up); rebuttals when the customer refuses (bounce charges, penal charges, credit impact, NOC delay), capture a Promise to Pay date; Call Closing.
- **Telesales Assistant** (Vista Financial Services, pre-approved personal loan): Phase 1 Opening & Rapport; Phase 2 Product Pitching (amount, tenure, rate, EMI, bundled life/health insurance, fees, complimentary benefits, foreclosure); Phase 3 Customer Verification (identity, salaried vs business details, 2 references, last 4 of PAN and account); Phase 4 Declarations & Closing (health declaration, exclusions, 90-day waiting period, final consent, ask for 5-star rating).
- **Telecom Sales Agent** (Vista Telecom, prepaid to postpaid / 5G family upgrade, outbound): Role & Objective; Phase 1 Opening & Rapport; Phase 2 Product Pitching; Phase 3 Customer Verification; Phase 4 Closing.
- **E-Commerce Sales Agent** (Vista Cart, shopping credit line + Premium Membership, BNPL, app onboarding): same 4-phase skeleton as Telecom.
- **Healthcare Triage & Booking** (Vista Healthcare, inbound): Phase 1 Opening & Intent Capture; Phase 2 Patient Triage (symptom assessment, emergency check); Phase 3 Appointment Booking & Verification (department recommendation, pharmacy integration mentioned); Phase 4 Closing.
- **Auto Assist & EV Support** (Vista Auto Assist, inbound distress): Phase 1 Opening & Safety Check; Phase 2 Issue Assessment & Triage; Phase 3 Location & Vehicle Verification; Phase 4 Resolution & Closing (technician dispatch).
- **Healthcare Check-in** (Vista Healthcare, outbound pre-visit): free-form "Your tasks" numbered list (identity, insurance, medical history, appointment details, pre-visit instructions, FAQs) plus "Guidelines" bullets (warm tone, repeat when confused, emergencies to emergency services, confirm before ending).

## Implications for Callwright

- Templates are pure prompt + voice presets. A richer template (tools, variables, call behaviour, flow graph) would already beat CallDash here.
- The `gpt-5.1-chat` id in data, mapped client side, shows template data and the model catalog drifted; keep template model ids validated against the live catalog server side.
