# Accessibility audit of the agent editor (T085)

Date: 2026-11-03. Scope: `apps/web/src/routes/agents/` (editor tabs Basics, Voice, Behaviour,
Tools, Knowledge, Quality, Advanced; the save bar; Write with AI; the voice picker; tool attach and
tool editor dialogs; quality variable and custom check dialogs; the error summary; version history,
compare and restore; the testing page with browser call, test cases, generate and import) and the
shared primitives they are built on.

## Method

- Real Chrome through Playwright against the mock API (`vite --mode mock`), desktop 1440 px light,
  dark, and 390 px.
- axe-core 4.12 injected into the page (not a project dependency), tags WCAG 2.0 to 2.2 A and AA plus
  best practice, run on every editor tab, on every dialog and drawer while open, and on the testing
  page.
- Keyboard walks: Tab through each tab and each dialog, recording the focused element, its name and
  whether a focus indicator is drawn; Escape in each dialog with a check of where focus lands.
- Heading outline and live regions listed per view.

## Found and fixed

| # | Problem | Fix |
|---|---|---|
| 1 | Slider thumbs (temperature, speed, expressiveness, volume, silence timeout, interruption sensitivity, responsiveness, background volume) had no accessible name: a `<label for>` cannot name the Radix thumb span (axe `aria-input-field-name`). | `FieldRow` gives its label an id and shares it through context; `Slider` uses it as `aria-labelledby` when its `id` is the row's `htmlFor`. |
| 2 | Each settings row's one-line help ("Lower is more predictable...") was not tied to its control. | The same context gives `Slider`, `SwitchControl`, `Select`, `Input` and `Textarea` the row description in `aria-describedby`, ahead of their own error text. |
| 3 | Dialogs and drawers opened from state (every one in the editor) dropped focus on the page body when closed: Radix returns focus only to its own trigger. | `useDialogFocus` (Dialog and Drawer) remembers the opener and returns to it, or to the menu trigger when a menu item opened the dialog, unless the closing action moved focus on purpose (error summary jumps). |
| 4 | Dialogs opened with focus on the header close button, whose tooltip then took the first Escape. | Initial focus goes to the first control in the body, then the footer, then the panel; a control with `autoFocus` keeps it. Write with AI focuses its message box. |
| 5 | Pending buttons were `disabled`, so pressing Save or Test agent from the keyboard dropped focus on the body. | A pending button is `aria-disabled` and ignores clicks but keeps focus; the editor no longer disables the button whose action is running. When Save leaves the bar after saving, focus moves to the "All changes saved" status. |
| 6 | Tab panels are a tab stop (Radix) but showed no focus indicator. | `TabPanel` has the shared focus ring. |
| 7 | Voice picker: each radio contained the preview button (axe `nested-interactive`); arrow keys moved focus without selecting. | The preview button sits beside the radio; arrows select and focus (radio group pattern), Home and End jump to the ends. |
| 8 | Custom check templates: a `button` with role `listitem` (axe `aria-allowed-role`). | Each item is a `listitem` holding the button; the template body describes the button. |
| 9 | Version compare: the "unchanged lines" fold button was a direct child of `role=table`. | It sits in a row and cell. |
| 10 | Browser call header: the cost info tip was a direct child of a `dl` group (axe `definition-list`). | It moved inside the `dd`. |
| 11 | Test run panel: the Export button lost its name below 640 px (label `hidden`). | The label is `sr-only` on narrow screens. |
| 12 | The sidebar logo row and the assistant dock sat outside landmarks (axe `region`). | Desktop sidebar is an `aside`; the dock is a labelled `region`. |

Tests: `src/components/a11y.test.tsx` (row naming and descriptions, dialog focus in and out
including the menu case, pending buttons), `routes/agents/editor/VoicePickerDialog.test.tsx`,
`routes/agents/versions/DiffView.test.tsx`, and `tests/e2e/agents-a11y.spec.ts` (sliders named in
the page, History returns focus, keyboard save keeps focus).

## Checked and already fine

- Every control is reachable by Tab in reading order; no keyboard traps; dialogs trap focus.
- Icon-only buttons all have names (`IconButton` requires `label`); switches and selects named.
- Headings: one `h1` per page, `h2` per panel, `h3` inside (quality checks, empty states).
- Live regions: the save status, the cost per minute, validation errors (`role=alert`), toasts, the
  assistant conversation, the tool test run output.
- Drag: the only drag (moving the assistant dock) also moves with the arrow keys; analysis
  variables reorder with Move up and Move down buttons.
- Version history, compare menu, restore and publish dialogs, tool dialogs, quality dialogs,
  generate and import dialogs: axe clean after the fixes (desktop, light). The editor tabs are axe
  clean in light and dark and at 390 px apart from the exempt item below.

## Not changed

- The Precise, Balanced and Creative marks under a fixed temperature fall below 4.5:1 (axe
  `color-contrast`). They belong to a disabled control, which WCAG 1.4.3 exempts, and are
  `aria-hidden`; the reason is spoken through the note under the slider.
- When focus sits on a control with a tooltip, the first Escape closes the tooltip and the second
  closes the dialog. This is Radix's layered dismissal and what WCAG 1.4.13 asks for.
- A screen reader pass with VoiceOver or NVDA was not run; the audit relies on the accessibility
  tree, names and descriptions checked in Chrome and in the unit tests.
