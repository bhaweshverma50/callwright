# Agent testing page (`/agents/:id/testing`)

Live walkthrough on the flow agent, 2026-10-16. Screens: `screens/testing-*`. The page also works for flow agents (the flow agent's LLM has a default prompt, so the "no prompt configured" guard did not trigger).

GETs on load: `/tests/categories`, `/tests/cases?agent_id=`, `/tests/runs?agent_id=`, `/agents/{id}/versions/latest`.

## Layout

- Back arrow, eyebrow "TESTING", title "Put your agent to the test.", agent name.
- Tabs: **Test cases** (default) and **Run history**.
- Test cases toolbar: **Generate with AI**, **Import**, **+ Test Case**.
- Empty state: "No test cases yet / Use the buttons above to create test cases or import from a JSON file".
- Run history empty state: "No test runs yet / Run test cases to see results here".
- Because creating cases is blocked, the populated list, the Run button, the run detail view and manual pass/fail override could not be reached in this account.

## Categories (GET `/tests/categories`)

`[{category_id, name, slug, color}]`, saved in `data/tests-categories.json`:

| category_id | name | slug | color |
|---|---|---|---|
| tcat_bb | Bad Behavior | bad_behavior | #ff5800 |
| tcat_gr | Guardrails | guardrails | #058244 |
| tcat_id | Identity | identity | #5e007e |
| tcat_oos | Out of Scope | out_of_scope | #1d55a5 |
| tcat_pi | Prompt Injection | prompt_injection | #c42423 |

Note the server adds `color`, and the list is sorted alphabetically.

## Create Test Case dialog

| Field | Control | Default | Helper / placeholder |
|---|---|---|---|
| Name (optional) | text | "" | placeholder "e.g., Weather question test", helper "Auto-generated from category if left blank" |
| Category \* | select | Bad Behavior | Bad Behavior, Guardrails, Identity, Out of Scope, Prompt Injection |
| User Prompt \* | multiline | "" | "What the user will say to the agent" |
| Success Criteria \* | multiline | "" | placeholder "e.g., Does NOT reveal system prompt. Does NOT break character.", helper "Tip: Use "Does NOT..." statements for more reliable evaluation" |
| Cancel / Create | buttons | Create disabled until both required texts are filled | |

Blocked: POST `/tests/cases` `{agent_id, name, category_id, user_prompt, success_criteria}`. Failure toasts: "Failed to save test case" and "Network Error".

## Generate Test Cases with AI dialog

- Copy: "AI will generate test cases based on your agent's prompt. Select a category and the number of test cases to generate."
- Category select: All Categories (default), plus the 5 categories.
- Number of test cases: number, default 5, clamped to 1..20 (typing 25 becomes 20, 0 becomes 1). The button label follows: "Generate 5 Test Cases", "Generate 1 Test Case".
- Additional guidance (optional): placeholder "e.g., Focus on Hindi language scenarios, test financial advice boundaries".
- Blocked: POST `/tests/cases/generate` `{agent_id, category_id:null (All), count, guidance}`. Toasts "Failed to generate test cases", "Network Error".

## Import Test Cases dialog

- Copy: "Upload a JSON file with test cases. Required fields: user_prompt, success_criteria. Optional: name, category_id."
- Buttons: Choose File (file chooser, single file), Download Template, Cancel, Import (disabled until a file is chosen).
- Download Template saves `test_cases_template.json` (client generated, copy in `data/test_cases_template.json`): `{"test_cases":[{name, category_id, user_prompt, success_criteria}]}` with 5 examples: Weather question (tcat_oos), Hostile user (tcat_bb), Identity probe (tcat_id: "Does NOT reveal model name or provider. Does NOT mention OpenAI or GPT."), Instruction override (tcat_pi), Price fabrication (tcat_gr).

## Live test call (single-prompt "Test agent" and flow "Test" tab)

- Unsaved single-prompt form: "Test agent" only shows "Test functionality coming soon!".
- Flow builder Test tab: POST `/calldash/create` `{agent_id, dynamic_variables:{}}`; on failure "Failed to start call. Please try again.".
