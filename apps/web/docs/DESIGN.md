# Callwright design system: signal chain

Callwright builds, runs and measures voice agents. Every call is a voice signal moving through a
chain: the caller speaks, speech to text hears it, the model decides, the voice answers, and the
caller hears it back. The interface makes that chain visible and translates money into the thing
operators actually buy, which is talk time.

This file is the source of truth for tokens and layout. Tokens live in `src/index.css`; motion
helpers in `src/components/motion.tsx`; the live gallery is `/dev/components`.

## 1. Principles

1. **Show the chain.** Wherever a call, a price or a latency appears, show which link of the chain
   it belongs to (caller, speech to text, model, voice, platform). The chain is the one recurring
   visual idea; it is never decoration.
2. **Money is talk time.** Balances, top-ups and trial credit are also stated as minutes of calls on
   the workspace's current stack. Dollars stay exact (three decimals for balances).
3. **One action colour.** Cobalt is the only colour that means "do this". Red is on-air (live,
   recording) only. Success, warning and danger are separate semantic colours.
4. **Spend boldness once per surface.** Each surface has one signature moment (section 6);
   everything around it stays quiet and aligned.
5. **Plain words.** Sentence case, active voice, user-side names. A button says what happens
   ("Add funds"), the toast confirms it with the same words ("Funds added"). Errors say what
   happened and how to fix it.

## 2. Colour

### Brand and data

| Token | Hex | Use |
|---|---|---|
| ink | `#171A3D` | Text in light theme; base of the dark theme |
| ink-deep | `#0E1030` | Dark theme page background, console surfaces in both themes |
| paper | `#F4F5FA` | Light theme page background |
| cobalt | `#3346E8` | The action colour: primary buttons, links, focus, selected state |
| violet | `#7A3CFF` | Only as the start of the heat ramp |
| on-air | `#F0412F` | Live and recording indicators only, never errors |
| heat ramp | `#7A3CFF` > `#E0457B` > `#FFB347` | Data visualisation and the cost chain only: waveforms, gauges, charts, latency bars, chain links |

### Semantic tokens

| Token | Light | Dark | Notes |
|---|---|---|---|
| `--bg` | `#F4F5FA` | `#0E1030` | Page |
| `--surface` | `#FFFFFF` | `#161A42` | Raised work surfaces |
| `--surface-2` | `#ECEEF6` | `#12153A` | Sidebar, recessed wells, table headers |
| `--surface-3` | `#E2E5F0` | `#20255A` | Hover fills, skeleton base |
| `--border` | `#DCDFEB` | `#262B5E` | Hairlines |
| `--border-strong` | `#C3C7DA` | `#3A4080` | Control borders |
| `--text` | `#171A3D` | `#EEF0FB` | 15:1 / 16:1 on page |
| `--text-2` | `#474B70` | `#B7BBDA` | Secondary text, 8:1 / 9:1 |
| `--text-3` | `#5E6287` | `#8F94BE` | Captions, 5.4:1 / 6.3:1 (AA for small text) |
| `--accent` | `#3346E8` | `#4B5CF0` | Fills; white text on it is 6.6:1 / 5.1:1 |
| `--accent-text` | `#2B3CD0` | `#A3ADFF` | Links and selected labels |
| `--accent-soft` | `#E6E9FD` | `#222A6E` | Selected backgrounds |
| `--success-text` / `--success-soft` | `#0F7A55` / `#DDF3EA` | `#5FD3A4` / `#123F3A` | Credits, done |
| `--warning-text` / `--warning-soft` | `#8F5200` / `#FFF1D6` | `#F5B94D` / `#3D3020` | Surcharges, low balance |
| `--danger-text` / `--danger-soft` | `#B42318` / `#FDE7E4` | `#FF8A7A` / `#4A1F2A` | Errors, destructive |
| `--on-air` | `#F0412F` | `#FF5A47` | Dot and ring only; the label beside it uses `--text` |

Rules:
- Text on any surface meets WCAG AA (4.5:1 small, 3:1 large). On-air red and the heat ramp never
  carry text.
- The dark theme is built from ink, not neutral black.

## 3. Colour on actions, and the one gradient

Primary actions are solid cobalt (`bg-accent`, `--accent-hover` on hover), with no glow, sheen or
coloured shadow. The same solid fill marks switches, the active step disc, avatars and selected
chips. No radial washes behind panels and no gradient text.

The only gradient is the heat ramp (`grad-heat`, `#7A3CFF`, `#E0457B`, `#FFB347`), and only inside
data: waveforms, gauge arcs, charts, latency bars and the cost chain. Warnings use `heat-border`,
a solid warning hairline.

The logo (Handoff, `docs/brand/logo-options.html`) is a C cut at the waist with its lower half
stepped forward: the upper half in ink (paper on dark), the lower half in flat cobalt (`#6E7DFF` on
dark). Its colours are the `--logo-*` tokens in `src/index.css` (the violet and pink stops now carry
cobalt too); it sits bare on the sidebar and page, and on an ink tile only as the favicon and app
icons. Do not hand-edit `logo-data.generated.ts`.

White text on cobalt is at least 6.6:1.

## 4. Typography

| Role | Family | Settings |
|---|---|---|
| Display | Unbounded (variable) | Page titles 24px/400, section heads 20 to 32px/400, hero 44 to 64px/400, tracking -0.02 to -0.035em. A design element: wide, short lines, never more than 3 lines. |
| UI and body | Geist (variable) | 14px base in the app, 16px body on marketing pages, line height 1.5 to 1.7, 60 to 75 characters per line |
| Figures | Geist Mono (variable) | Only money, durations, latency, rates, counts in tables, ids. Tabular and slashed zero. |

Scale: 12, 13, 14, 16, 20, 24, 32, 44, 60.

Never: all-caps tracked eyebrows, middle-dot meta strings, arrow glyphs appended to button text,
one accent-coloured word inside a headline, monospace for ordinary labels.

## 5. Layout

### App shell

```
+------------+-----------------------------------------------------------+
| logo       | workspace name                 balance chip   user menu  |
|            +-----------------------------------------------------------+
| Build      | Title (Unbounded)                         [primary action]|
|  Agents    | One line saying what this page is for                     |
|  Knowledge +---------------------------------------+-------------------+
|  Channels  | main column                           | inspector pane    |
| Observe    |                                       | (sticky, 360px)   |
|  Dashboard |                                       |                   |
|  Calls     |                                       |                   |
| Quality    |                                       |                   |
| Feedback   |                                       |                   |
|  loop      |                                       |                   |
|------------|                                       |                   |
| Billing    |                                       |                   |
| Settings   |                                       |                   |
| collapse   |                                       |                   |
+------------+---------------------------------------+-------------------+
```

- Sidebar: 248px labelled and grouped (Build: Agents, Knowledge, Channels; Observe: Dashboard,
  Calls; Quality: Datasets, Simulations; Feedback loop: Review, Calibration, Issues), then Billing
  and Settings at the foot. Collapses to a 72px icon rail of centred 40x40 targets with label
  tooltips; the active item is a contained tinted square in the accent colour in both states. The
  choice is remembered per browser (`cw.rail.expanded`, default expanded). The `Main` navigation landmark holds the 11
  product areas; Settings sits in a separate `Workspace` landmark. Shortcut `[` toggles it.
- Below 1024px the sidebar becomes an off-canvas drawer opened from the top bar.
- Page header: title, one-line purpose, the page's primary action on the right. Left aligned.
- Work screens: main column plus a right inspector pane at 1280px and up. Below that the
  inspector content stacks under the main column, and record details open in a drawer.
- Content max width 1320px; gutters 16px on phones, 24px tablet, 40px desktop.

### Public pages

Left-aligned 12-column grid, max width 1200px. Hero: headline and copy on the left, the live call
console on the right. Sections are separated by space and hairlines, not by stacks of cards.

### Radius and elevation by hierarchy

| Level | Radius | Elevation | Examples |
|---|---|---|---|
| Inline | 4px | none | Badges, kbd, inline code |
| Control | 8px | none, 1px border | Buttons, inputs, selects, chips are pills |
| Work surface | 12px | 1px border, `--shadow-1` | Lists, forms, inspector |
| Feature | 20px | `--shadow-2` | Live call console, billing gauge, pricing chain, receipt |
| Floating | 12px | `--shadow-pop` | Menus, popovers, toasts, drawers |

Not every block is a card: page sections sit directly on the paper and use hairlines.

### Units and rows

- The root font size is the browser default (16px); interface text is 14px on `body`. Fixed-size
  controls (switch, chain nodes, stepper discs) are sized in px so their geometry never depends
  on the root size.
- Cards share one anatomy: header with icon, title and one-line description; rows with 20px side
  padding, 16px vertical padding and hairlines between them; icon and label on the left, the value
  or control on the right (`FieldRow`, `InfoRow`). Long values truncate with a tooltip.
- Grids that collapse to one column use `grid-cols-[minmax(0,1fr)]` so content never forces a
  phone to scroll sideways.

### Flows and sequences

- Every horizontal flow (pricing chain, live call chain, build loop) is a `FlowChain`: equal grid
  columns, the circle centred in each, labels wrapping to two lines under it, connectors drawn as
  one layer from circle edge to circle edge with the same 8px gap, the same gradient and dash on
  every segment, flowing in sync. Below 34rem of container width (20rem for short chains) it turns
  vertical with equal rows. Extra controls (replay, reset) live in the panel header, never inline
  as a node. `tests/e2e/flow-geometry.spec.ts` checks every chain at 1440, 1024 and 390.
- Vertical sequences use `Stepper`: one centre axis, a continuous connector, numbered discs.

### Don't

- No side-stripe accents: no coloured left (or right) border, inset box-shadow bar or pseudo
  element bar to mark an active, selected or important item. Not on sidebar items, stepper rows,
  callouts, alerts, toasts, cards, table rows or tabs.
- Show state by other means per context: active navigation is a contained tinted square with the
  icon and label in the accent colour; the active step is a solid cobalt disc with a soft halo and a
  subtle full-row lift; selected rows get a full-row tint; callouts and alerts use an icon, a
  tinted background and, if needed, a full hairline border.
- No all-caps tracked eyebrows, middle-dot meta strings, arrow glyphs after button text, emojis,
  or one accent-coloured word in a headline.

## 6. Signature moments (one per surface)

1. **Home hero:** a live call plays out once in a dark console: caller and agent turns appear over
   an animated waveform, each agent turn carries a latency chip split by chain link, a running cost
   ticker counts up, and the chain strip lights the link that is working. Ends with a Replay button.
   Reduced motion shows the finished call.
2. **Pricing:** the calculator is a clickable chain Mic > Speech to text > Model > Voice > Speaker
   (noise cancellation is an optional link before speech to text). Clicking a node opens its vendor
   and model choices. Flowing particles carry the running per-minute subtotal along the links into
   a receipt. The worked example ($0.477, LLM billed at 1.13x) is a receipt with the surcharge line
   highlighted.
3. **Billing:** balance as a talk-time gauge: an arc that animates to the balance against the recent
   peak, "about N minutes of calls on your current stack" from the pricing quote for the default
   stack, and a projected run-out from the last 14 days of spend. Transactions are a day-grouped
   timeline; a call charge opens its breakdown in the inspector.
4. **Dashboard (empty):** a numbered three-step setup sequence (create an agent, make a test call,
   connect a number) with a progress bar. Numbered because it is a sequence.
5. **Sign-in and register:** split screen, form on one side and a quiet sample call on the other
   (slow waveform, three turns, latency chips, cost).

## 7. Icons

- `lucide-react` is the main set: navigation, buttons, stats, status, inputs. 1.75 stroke, 16px in
  controls, 18px in navigation, 20px in stats.
- `@phosphor-icons/react` duotone only where a richer glyph helps: empty states, feature tiles and
  setup steps (24 to 32px).
- One weight per context. Icons sit before labels; a button never ends in an arrow glyph.
- No sparkles for AI. Drafting and generating use a pen (`PenLine`), the assistant chat uses
  `MessageSquareText`, an agent is `Bot`.
- No emojis anywhere: interface, copy, toasts, docs.

## 8. Motion

Library: `motion` (`motion/react`). Helpers in `src/components/motion.tsx`.

| Effect | Where | Timing |
|---|---|---|
| Route transition | Shell outlet and public outlet: fade plus 6px rise | 220ms, ease out |
| Staggered reveal | First load of a page's top-level blocks | 40ms stagger, 260ms each |
| Panel and drawer | Inspector content swap, drawers, dialogs, menus | 200ms spring, opacity plus transform |
| List enter and exit | Timeline rows, toasts, setup steps | 180ms, layout animation on reorder |
| Number tickers | Balance, talk time, cost tickers, calculator totals | spring to the new value, about 600ms |
| Waveform | Hero console, auth panel, gauge, 404 flatline | SVG bars scaled with transforms |
| Chain flow | Pricing links, hero chain | dash offset and particles along SVG paths |
| Gauge arc | Billing | path length from 0 to value, 900ms |
| On-air pulse | Live indicators | 1.6s pulse (`halo-pulse`): grows out of the dot from 0.85 of its size and invisible, never pops in |
| Active node and step | FlowChain node, Stepper disc | The cobalt fill and the halo scale in from 0.85 and fade in together over `--state-duration` (360ms, `--ease-out-soft`), and leave the same way. The halo is a steady soft ring plus a pulse (`--halo-pulse-duration` 1.8s) that grows out of the disc's own edge. Reduced motion: the steady ring only |
| Tooltips | Every tooltip and info tip | Opens after 300ms; adjacent tips open at once within 400ms (Provider skip delay); fades in while settling 3px toward its trigger (160ms), fades out in 90ms. Keyboard focus opens it, a click does not |
| Logo mark | The two halves of the Handoff C, on hover or focus of the logo or its link | One pass: the halves slide apart and step back together, 720ms, `--ease-out-soft`; never idle; none under reduced motion |
| Hover | Card borders darken (nothing moves or glows); primary buttons step to `--accent-hover`; links get an animated underline; table rows highlight | 150 to 200ms |
| Press | Scale to `--press-scale` (0.975) for `--press-duration` (90ms) plus a ripple from the pointer on buttons and chips | 90ms, ripple 450ms |
| Focus | A cobalt hairline on focused feature panels; the 2px cobalt focus ring stays on every control | |
| Loading | Shimmer skeletons for content-shaped loading; they unmount the moment content arrives | `--skeleton-duration` 1.3s, ease-in-out |
| Loading mark | `LogoLoader` for app boot, the session check (`FullPageLoader`) and route loading (`PanelLoader`): the two halves of the C swing half a turn out and back, the leader alternating, locking into the mark at each end, with soft comets and a glow at each lock. Fades in after 140ms so fast loads never flash it. Frames in `docs/screens/loader/` | 2.4s seamless loop; reduced motion: the still mark breathing in opacity |

Motion tokens live on `:root` in `src/index.css`: `--ease-out-soft`, `--press-duration`, `--press-scale`, `--skeleton-duration`, `--state-duration`,
`--halo-pulse-duration` (colours `--halo`, `--halo-soft`). `EASE_OUT_SOFT` and `STATE_DURATION` in
`motion.tsx` mirror them for motion components.

Guardrails:
- Animate only `transform` and `opacity` (plus SVG `stroke-dashoffset`), no layout properties.
- `prefers-reduced-motion: reduce` turns off non-essential motion: `MotionConfig reducedMotion="user"`
  wraps the app, CSS animations are cut to 1ms, tickers jump to their value, the hero shows the
  finished call, the waveform is still. State changes stay instant and visible.
- No layout shift: tickers use tabular figures in fixed-width boxes; skeletons match content size.
- Keyboard focus is always visible: a 2px cobalt ring with 2px offset.

## 9. Components

`Button` (solid cobalt primary with press and ripple, secondary, ghost, danger, link), `IconButton`,
`Field`, `Input`, `Textarea`, `Select`, `Slider`, `Switch`, `Tabs`, `Dialog`, `ConfirmDialog`,
`Drawer`, `Table`, `Pagination`, `Toast`, `EmptyState`, `Skeleton`, `Badge`, `Chip`, `Kbd`,
`MoneyText`, `Ticker`, `CostBreakdownCard` (receipt), `Panel`, `PageHeader`, `Inspector`,
`Waveform`, `FlowChain`, `Stepper`, `LatencyChip`, `PanelRows` (`FieldRow`, `InfoRow`), `SwitchControl`, `OnAir`, `Logo`, `LeaveGuard`, `ErrorSummaryDialog`,
`Tooltip`, `TruncatedText`, `InfoTip`, `CopyButton`, `LogoLoader` (`FullPageLoader`, `PanelLoader`),
`Segmented`, `ChoiceGroup`.

Choices:
- `Segmented` is for two to four short, exclusive options (who speaks first, a type filter, call
  recording). The selected segment is a raised pill that slides between options.
- `ChoiceGroup` is for options that need a description or a price (agent type, speech recognition
  model, noise cancellation). Selection is a tinted surface, an accent outline all round and a check
  disc; unselected cards darken their border on hover. Both are radio groups: one tab stop, arrow keys move.
- `Slider` takes `marks` (Low, Medium, High) aligned with the thumb centre; the value itself sits in
  a fixed-width mono pill above the track, formatted from the catalog control range so the label is
  always the stored value (1,500 ms reads "1.5 s", gain 1.0 reads "100%").
- `Chip mono={false}` for word filters (industries); mono stays for amounts.
- `FlowChain stack="always"` keeps a chain vertical with a value on each row (the agent cost chain).
- `toast({ action })` adds one follow-up ("Open the copy").

Tooltips and truncation:
- Every icon-only button names its action in a tooltip (`IconButton` does it for you).
- Text that can outgrow its space is a `TruncatedText`: one line, an ellipsis, and the full text in
  a tooltip only while it is cut. Inside a link or button pass `focusable={false}`.
- `InfoTip` explains a term or a figure (how talk time is computed, what a bundle surcharge is).
  The tip adds detail; anything the reader must know stays visible next to it. `InfoRow` and
  `FieldRow` take a `hint` for this.

## 10. Accessibility checklist

- AA contrast in both themes; colour is never the only signal (icons and words accompany tone).
- Skip link to main content; landmarks `Main` and `Workspace` navigation; one `h1` per page.
- Touch targets at least 40px on phones; navigation rows 36px desktop, 44px in the mobile drawer.
- Every icon-only control has an accessible name, which its tooltip repeats; tooltips are never the
  only place required text lives.
- Live regions for balance changes, calculator totals and toasts.

## 11. Critique log

Recorded after each screenshot pass: look, remove one accessory, re-shoot.

1. First pass (1440 light and dark): the sign-in panel carried a waveform card and a chain strip;
   the chain strip was the accessory removed, so the sample call is the one visual. Phones scrolled
   sideways on home and pricing (single-column grids sized to content); fixed with
   `grid-cols-[minmax(0,1fr)]`. Chain links took the SVG default width and overflowed the console.
2. Receipts in the 360px inspector wrapped component names; they now drop the rate column and
   model names below container widths (container queries).
3. User review: the switch thumb overflowed (root font size 14px made rem utilities 87.5 percent
   while px sizes were not; root restored to 16px, switch fixed in px); settings cards did not
   share an anatomy (now `PanelRows`); the collapsed rail was cramped and clipped (Tooltip's Slot
   dropped NavLink's class function; rebuilt with centred 40x40 targets).
4. User review: side-stripe accents removed everywhere (sidebar, rows, toasts, stepper); every
   flow redrawn with one `FlowChain` so connectors are equal; the button sheen became one short
   eased pass on hover; the dashboard sequence became a real stepper.
5. At 1024 the pricing chain had no room for subtotals between nodes; with `FlowChain` they sit
   centred on equal connectors, and the chain turns vertical on narrow containers.
6. Agent builder (spec 002): the editor is one signature moment, the agent's own signal chain in the
   inspector with a rate per link and a total that ticks; the link whose selection changed lights up
   for two seconds. Removed during review: a type badge duplicated by the section title, a second
   "Pronunciation" label inside the Pronunciation card, check marks after the type chooser bullets
   and the stretched-link overlay on agent cards (it hid tooltips on cut-off values). Fixed: gradient
   strokes on horizontal SVG paths need `gradientUnits="userSpaceOnUse"`, icon prefixes in inputs
   need 36px of padding, and choice-card prices move under the description on small cards so titles
   do not wrap against them.
7. ui-unslop pass (polish): one solid cobalt action colour replaced the cobalt to violet gradient,
   the sheen, the coloured shadows and the radial washes; cards stop lifting and glowing on hover;
   the logo went flat cobalt; display headings dropped to weight 400; the heat ramp left the tour
   ring, the live calls stripe and the warning borders and stays only in data and the cost chain;
   half-pixel text sizes rounded up (12.5 to 13, 13.5 to 14); tracked uppercase labels became
   sentence case; sparkles became a pen, a chat bubble or a bot by meaning.
