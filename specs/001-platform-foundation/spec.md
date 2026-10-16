# Feature Specification: Platform Foundation

**Feature Branch**: `001-platform-foundation`
**Created**: 2026-10-16
**Status**: Draft
**Input**: User description: "Accounts and workspaces, sign-in, the app shell every other feature lives in, a prepaid credit balance with top-ups and an auditable transaction history, a versioned per-minute pricing catalog with bundle surcharges, a public pricing calculator, and per-feature usage reporting."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Sign up and land in a workspace (Priority: P1)

A new operator registers with email and password, verifies their email, and lands in their own
workspace with a starting credit balance, an empty dashboard and a navigation rail that reaches
every product area (Dashboard, Agents, Calls, Datasets, Simulations, Review, Calibration, Issues,
Channels, Knowledge, Billing).

**Why this priority**: Nothing else in the product is reachable without an account, a workspace
and the shell.

**Independent Test**: Register a fresh email, verify it, sign in, and confirm the workspace shows
its balance, the signed-in email and working navigation to every area.

**Acceptance Scenarios**:

1. **Given** an unregistered email, **When** the visitor registers and verifies, **Then** a
   workspace is created with the configured trial credit and the visitor lands on the dashboard.
2. **Given** a registered user, **When** they enter a wrong password 5 times within 15 minutes,
   **Then** further attempts are throttled and the message explains when they can retry.
3. **Given** a signed-in user, **When** they sign out, **Then** every open tab loses access and
   protected pages redirect to sign-in, returning to the original page after sign-in.
4. **Given** a user who forgot their password, **When** they request a reset, **Then** they get
   an email link that lets them set a new password once, within 1 hour.
5. **Given** a signed-in user, **When** they open the user menu, **Then** it shows their email,
   "Settings" and "Sign out"; Settings shows the workspace name (editable), the call recording
   default (on or off), the concurrent-call limit (read-only) and the account email, and a change
   is saved only after the user saves, with a confirmation.
6. **Given** any signed-in page, **When** the user opens an address that does not exist, **Then**
   a "page not found" view appears inside the shell with a link to the dashboard (no silent
   redirect).
7. **Given** an address or API request that names a record by a malformed or unknown ID, **When**
   it is opened, **Then** the API answers "not found" and the page says which kind of record was
   not found; no status code, transport error or internal error text is ever shown.
8. **Given** a fresh page load, **When** the user has not used an optional feature (voice
   copilot, analytics assistant, test call), **Then** no credential or session for that feature
   is requested.
9. **Given** a form with unsaved input (including a create form that has never been saved),
   **When** the user navigates away, reloads or closes the tab, **Then** they are asked to stay or
   leave without saving.
10. **Given** the navigation rail, **When** the app first opens, **Then** the rail is collapsed to
    icons with a label tooltip on each, the expanded rail groups Datasets and Simulations under
    "Quality" and Review, Calibration and Issues under "Feedback", and the user's expand or
    collapse choice is remembered on that browser.

---

### User Story 2 - Top up credit and see every transaction (Priority: P1)

An operator sees their balance in the header at all times, adds funds (preset $25/$100/$500/$1000
or a custom amount, minimum $5) through a hosted checkout, and sees the new balance and a
transaction row (date, type, amount, balance after, related call, description) as soon as the
payment succeeds.

**Why this priority**: Calls cannot run without credit; billing trust is core to adoption.

**Independent Test**: Complete a test-mode payment and confirm balance and history update without
a page reload; confirm a $4 custom amount is rejected.

**Acceptance Scenarios**:

1. **Given** a balance of $5.00, **When** a $25 top-up succeeds, **Then** the balance shows
   $30.00 and a `top_up` transaction with balance-after $30.00 appears.
2. **Given** a checkout the user abandons, **When** they return, **Then** no transaction is
   recorded and the balance is unchanged.
3. **Given** the payment provider notifies the same payment twice, **When** both notifications
   arrive, **Then** credit is added exactly once.
4. **Given** a completed call, **When** it is billed, **Then** a `call_charge` transaction linked
   to that call appears with its itemised cost.
5. **Given** a custom amount of $4, $0 or $10,001, or more than two decimals, **When** the
   operator tries to add funds, **Then** the field shows why (minimum $5, maximum $10,000, cents
   only), the add button explains it is disabled, and no checkout starts.
6. **Given** the preset amounts, **When** the operator clicks $100, **Then** the amount field
   shows $100.00 and checkout starts only when they press "Add funds" (one explicit action that
   names the amount).

---

### User Story 3 - Know the price of a call before and after it happens (Priority: P2)

Pricing is per minute across five components: speech-to-text, LLM, text-to-speech, optional
noise cancellation, and a flat platform fee. Each provider/model has a catalog rate. LLM and TTS
rates include a usage bundle per minute (LLM input 20,000 tokens, LLM output 200 tokens, TTS 750
characters). Duration is rounded up to the whole second. For a surchargeable component the billed
minutes are `max(duration_minutes, usage / bundle_per_minute)` across its usage meters, and cost
is `rate × billed_minutes`. Operators can see the estimate while configuring an agent, on a public
calculator, and the exact breakdown (with surcharge amount and bundle multiplier) on every call.

**Why this priority**: Every agent, call and usage view depends on one shared pricing rule.

**Independent Test**: Price the reference call (271 s; 102,348 input tokens; 745 output tokens;
2,555 TTS characters; STT $0.0085, LLM $0.0015, TTS $0.0450, platform $0.0500 per minute) and
get LLM billed minutes 5.1174, TTS 4.5167, total $0.477.

**Acceptance Scenarios**:

1. **Given** the reference call above, **When** it is priced, **Then** the LLM line shows a
   surcharge of ≈ $0.0009 and a bundle multiplier of 1.13×, and TTS shows no surcharge.
2. **Given** a 4.2-second call, **When** it is priced, **Then** it is billed as 5 seconds.
3. **Given** a catalog rate change, **When** older calls are viewed, **Then** they keep the rate
   that was in effect when they ran.
4. **Given** a visitor on the public calculator, **When** they pick STT, model, voice and monthly
   minutes, **Then** cost per minute and the monthly estimate update immediately.

---

### User Story 4 - See where the money went (Priority: P3)

An operator opens usage for a date range (default the last 30 days) and sees raw and billable
cost per feature (calls, evaluations, simulations, analytics questions, prompt generation),
with totals.

**Why this priority**: Useful once the account has real traffic; not needed for first value.

**Independent Test**: Seed one call and one evaluation in range and one outside; confirm only the
in-range rows and correct totals appear.

**Acceptance Scenarios**:

1. **Given** no usage in the window, **When** the page loads, **Then** it says "No usage charges
   yet in this window" with the window dates.
2. **Given** the usage panel, **When** the operator picks a different start and end date (up to
   366 days), **Then** rows and totals refresh for that window; an end before the start is refused
   inline.

---

### Edge Cases

- Balance reaches zero during a live call: the call is allowed to finish up to a configured
  grace amount; new calls are refused with an "add funds" message.
- Concurrent calls exceed the workspace limit: the extra call is refused with a clear reason.
- A catalog row is missing for a selected provider/model: the estimate shows the component as
  "price unavailable" and the agent cannot be saved for live traffic until it is priced.
- A refund or dispute from the payment provider: recorded as a negative `adjustment`, never by
  editing the original row.
- Session token expires mid-session: refreshed silently; if refresh fails, user is sent to
  sign-in and returned afterwards.
- A settings save with an empty or over-long workspace name: the field shows the error and
  nothing is saved.
- A server fault while loading a record: the page shows a generic "something went wrong" message
  with a reference the user can quote to support; database or stack details never reach the
  browser.
- The balance chip is clicked: it opens Billing (it is a link, not decoration).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST let a visitor register with email + password and require email
  verification before any call can be placed.
- **FR-002**: System MUST create one workspace per new account, with the registering user as
  owner, a trial credit (default $5.00) and a max-concurrency limit (default 5 calls).
- **FR-003**: System MUST support sign-in, sign-out, password reset and login throttling.
- **FR-004**: System MUST expose the current user, workspace name, email-verified flag, credit
  balance, concurrency limit and admin flag to the app.
- **FR-005**: System MUST show a persistent shell: collapsible icon navigation to all product
  areas (collapsed by default, label tooltips while collapsed, section headers "Quality" for
  Datasets and Simulations and "Feedback" for Review, Calibration and Issues, expand state
  remembered per browser), a live balance chip in the top bar that links to Billing and shows the
  balance to three decimals (charges move in $0.001 steps), the signed-in email, an initials
  avatar, and a user menu with Settings and Sign out.
- **FR-006**: System MUST record every credit movement as an immutable transaction of type
  `top_up`, `call_charge`, `feature_charge`, `trial_grant`, `refund` or `adjustment`, storing
  amount, balance after, optional call reference and description.
- **FR-007**: System MUST compute the balance only from transactions.
- **FR-008**: System MUST let users top up via hosted checkout with presets and a custom amount
  (minimum $5, maximum $10,000 per top-up, whole cents), crediting only after confirmed payment,
  idempotently. Invalid amounts MUST be explained inline, never ignored silently; presets fill the
  amount and checkout starts only from the explicit "Add funds" action.
- **FR-009**: System MUST list transactions newest first with pagination (default 20 per page).
- **FR-010**: System MUST maintain a versioned pricing catalog of per-minute rates keyed by
  component (stt, llm, tts, nc, platform), provider and optional model, with effective dates and
  bundle sizes for surchargeable components.
- **FR-011**: System MUST price calls with whole-second round-up and the bundle rule in
  User Story 3, storing per component: rate, billed minutes, cost, surcharge amount, bundle
  multiplier, and catalog version.
- **FR-012**: System MUST provide a cost estimate for any agent configuration (per-minute total
  and per-component lines).
- **FR-013**: System MUST provide a public pricing page with an interactive calculator.
- **FR-014**: System MUST report usage per feature for a date range with raw and billable cost;
  the user chooses the range (default the last 30 days, at most 366 days).
- **FR-015**: System MUST refuse new calls when the balance is at or below zero or the
  workspace is at its concurrency limit, with the reason shown to the caller of the API.
- **FR-016**: System MUST provide public marketing pages (home, pricing, enterprise contact,
  privacy policy, terms of service).
- **FR-017**: System MUST provide a Settings page, reached from the user menu, where the owner
  edits the workspace name and the workspace call recording default, and sees the concurrent-call
  limit and account email; changes apply only on save and are confirmed.
- **FR-018**: System MUST show a "page not found" view inside the shell for any unknown signed-in
  address, with a link to the dashboard, instead of redirecting silently.
- **FR-019**: System MUST answer requests that name a record by a malformed or unknown ID with a
  "not found" problem (never a server error), MUST never include database, stack or vendor error
  text in any response, and MUST give every server-error response a reference ID that support can
  trace; the app MUST turn problems into plain messages and never display raw status codes or
  transport errors.
- **FR-020**: System MUST NOT mint credentials, tokens or sessions for optional features on page
  load; each is requested only when the user first uses that feature.
- **FR-021**: System MUST protect every form with unsaved input, including never-saved create
  forms, against in-app navigation, reload and tab close with a stay-or-leave prompt.
- **FR-022**: The launch pricing catalog MUST hold a rate for every speech recognition, language
  model, voice and noise cancellation option the agent builder offers (002), plus the platform
  fee; a missing rate MUST fail the release check and MUST never be shown or charged as $0.
- **FR-023**: System MUST record every feature charge in usage reporting, including zero-amount
  charges (for example internal embeddings for anomaly detection); a zero-amount charge MUST
  create a usage row and MUST NOT create a credit transaction; only amounts above zero move
  credit.

### Key Entities

- **User**: a person who signs in; email, verification state, admin flag.
- **Workspace**: the tenant boundary; name, owner, concurrency limit, call recording default;
  owns every other record.
- **Credit Transaction**: one immutable movement of credit; type, amount, balance after,
  optional call or feature reference, description, timestamp.
- **Pricing Catalog Entry**: component, provider, optional model, per-minute rate, bundle sizes,
  effective from/to.
- **Cost Breakdown**: per-call record of each component's rate, billed minutes, cost, surcharge
  and multiplier, plus catalog version.
- **Usage Row**: feature, period, raw cost, billable cost.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A new user goes from landing page to signed-in dashboard in under 2 minutes
  (excluding email delivery time).
- **SC-002**: A successful top-up shows in the balance within 10 seconds of payment confirmation.
- **SC-003**: The sum of transactions equals the displayed balance for 100% of workspaces in a
  nightly reconciliation.
- **SC-004**: The reference call prices to $0.477 (±$0.001) and the reference surcharge to
  ≈ $0.0009 in automated tests.
- **SC-005**: Zero duplicate credits across replayed payment notifications in tests.

## Assumptions

- Email + password is the only sign-in method in v1; SSO/OAuth is a later enterprise feature.
- One user per workspace in v1; team invitations and roles are out of scope.
- Prices are in USD only; taxes and invoices are handled by the payment provider.
- The trial credit amount and concurrency default are configurable per environment.
- Marketing pages are static content and need no CMS.
- Launch per-minute rates match the reference market rates captured on 2026-10-16 (data-model.md,
  pricing seed); product can change them later by publishing a new catalog version.
