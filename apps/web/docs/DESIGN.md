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
| violet | `#7A3CFF` | Only as the far end of the cobalt gradient and the start of the heat ramp |
| on-air | `#F0412F` | Live and recording indicators only, never errors |
| heat ramp | `#7A3CFF` > `#E0457B` > `#FFB347` | Data visualisation only: waveforms, gauges, chain links, highlight borders |

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

## 3. Gradients

Allowed, from the palette only:

| Name | Value | Where |
|---|---|---|
| `--grad-action` | cobalt `#3346E8` to violet `#7A3CFF`, 120deg | Primary buttons, the logo tile, switches, the active step disc, a few hero headlines as gradient text |
| `--grad-heat` | `#7A3CFF`, `#E0457B`, `#FFB347` | Waveforms, gauge arcs, chain links, highlight borders (focused or active panels) |
| `--glow-hero` | radial cobalt and violet at 12 to 18 percent alpha | Behind the home hero, the pricing chain, the billing gauge and the auth visual |

Gradient text is limited to the home headline and the pricing headline. Body text, labels and
figures are always solid colour. White text on `--grad-action` is at least 6.6:1 at the cobalt end
and 5.4:1 at the violet end.

## 4. Typography

| Role | Family | Settings |
|---|---|---|
| Display | Unbounded (variable) | Page titles 24px/500, section heads 20 to 32px/500, hero 44 to 64px/600, tracking -0.02 to -0.035em. A design element: wide, short lines, never more than 3 lines. |
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
| Feature | 20px | `--shadow-2` plus glow | Live call console, billing gauge, pricing chain, receipt |
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
  icon and label in the accent colour; the active step is a gradient disc with a soft halo and a
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
| On-air pulse | Live indicators | 1.6s ring pulse |
| Logo mark | Logo tile bars | idle breathing bars on hover |
| Hover | Cards lift 2px with a cobalt glow; links get an animated underline; table rows highlight | 150 to 200ms |
| Sheen | One diagonal pass of a narrow (28 percent wide, 0.32 alpha) highlight across a primary button on hover or keyboard focus; never restarted mid-pass; never an idle loop except the single hero CTA (one pass every 7 s) | `--sheen-duration` 560ms, `--ease-out-soft` cubic-bezier(0.22, 1, 0.36, 1) |
| Press | Scale to `--press-scale` (0.975) for `--press-duration` (90ms) plus a ripple from the pointer on buttons and chips | 90ms, ripple 450ms |
| Focus | Animated heat-ramp border on focused feature panels; the 2px cobalt focus ring stays on every control | |
| Loading | Shimmer skeletons for every loading state; they unmount the moment content arrives | `--skeleton-duration` 1.3s, ease-in-out |

Motion tokens live on `:root` in `src/index.css`: `--ease-out-soft`, `--sheen-duration`,
`--sheen-idle-cycle`, `--press-duration`, `--press-scale`, `--skeleton-duration`.

Guardrails:
- Animate only `transform` and `opacity` (plus SVG `stroke-dashoffset`), no layout properties.
- `prefers-reduced-motion: reduce` turns off non-essential motion: `MotionConfig reducedMotion="user"`
  wraps the app, CSS animations are cut to 1ms, tickers jump to their value, the hero shows the
  finished call, the waveform is still. State changes stay instant and visible.
- No layout shift: tickers use tabular figures in fixed-width boxes; skeletons match content size.
- Keyboard focus is always visible: a 2px cobalt ring with 2px offset.

## 9. Components

`Button` (primary gradient with sheen and ripple, secondary, ghost, danger, link), `IconButton`,
`Field`, `Input`, `Textarea`, `Select`, `Slider`, `Switch`, `Tabs`, `Dialog`, `ConfirmDialog`,
`Drawer`, `Table`, `Pagination`, `Toast`, `EmptyState`, `Skeleton`, `Badge`, `Chip`, `Kbd`,
`MoneyText`, `Ticker`, `CostBreakdownCard` (receipt), `Panel`, `PageHeader`, `Inspector`,
`Waveform`, `FlowChain`, `Stepper`, `LatencyChip`, `PanelRows` (`FieldRow`, `InfoRow`), `SwitchControl`, `OnAir`, `Logo`, `LeaveGuard`, `ErrorSummaryDialog`.

## 10. Accessibility checklist

- AA contrast in both themes; colour is never the only signal (icons and words accompany tone).
- Skip link to main content; landmarks `Main` and `Workspace` navigation; one `h1` per page.
- Touch targets at least 40px on phones; navigation rows 36px desktop, 44px in the mobile drawer.
- Every icon-only control has an accessible name; tooltips are never the only place text lives.
- Live regions for balance changes, calculator totals and toasts.

## 11. Critique log

Recorded after each screenshot pass (section 12 of the brief: look, remove one accessory, re-shoot).
