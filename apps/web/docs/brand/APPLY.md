# Applying the chosen logo

The four concepts live in `public/brand/concepts/<key>/` and are reviewed in
`docs/brand/logo-options.html` (screenshot: `logo-options.png`). Keys: `handoff`, `dovetail`,
`thread`, `two-voices`. Nothing in the app uses them until one is applied.

## One command

From the repo root, with `apps/web` dependencies installed:

```
uv run --with fonttools --with brotli python apps/web/scripts/brand/apply_concept.py <key>
```

Add `--out /some/dir` to write the same tree elsewhere for review first. Set `CW_FONTS` (the
`@fontsource-variable` folder) and `CW_PLAYWRIGHT` (a `@playwright/test` path) when running from a
checkout without `node_modules`.

## What it changes

| Path | Change |
|---|---|
| `public/favicon.svg` | Replaced: the concept's app icon (replaces the old teal bars) |
| `public/favicon.ico` | New: 16, 32 and 48 px PNGs in one icon |
| `public/apple-touch-icon.png` | New: 180 px, full bleed, no transparency |
| `public/icon-192.png`, `icon-512.png` | New: PWA icons |
| `public/icon-maskable-512.png` | New: mark inside the 80 percent safe circle |
| `public/og-image.png` | New: 1200 x 630, dark lockup and tagline |
| `public/site.webmanifest` | New |
| `public/brand/*.svg` | New: symbol, symbol-dark, lockup-light, lockup-dark, mono |
| `src/components/logo-data.generated.ts` | New: symbol and lockup art; colours are `--logo-*` tokens, ids are made unique per instance with `useId` |
| `src/components/Logo.tsx` | Replaced from `scripts/brand/templates/Logo.tsx` |
| `src/index.css` | Appends (or replaces) the `brand:logo` block from `scripts/brand/templates/logo.css`: `--logo-*` tokens for light, dark and `.logo-on-dark`, and the hover animation |
| `index.html` | Favicon, apple-touch-icon, manifest, theme-color and Open Graph tags |

## Logo component

Same props as today, so `Sidebar`, `PublicLayout` (header and footer), `AuthLayout` and the
component gallery need no edits:

- `compact`: symbol only (collapsed rail). Otherwise the lockup.
- `onConsole`: forces the dark palette on always-dark surfaces.
- New, optional: `mono` (one colour, `currentColor`), `height` (default 32), `animated` (default on).

It renders one inline SVG, so the wordmark needs no web font and sits on the same optical centre as
the symbol at any height. Theme comes from CSS variables, not props, so it flips with
`data-theme` without a re-render.

Animation (hover on the logo or its link, never idle, off under reduced motion; replaces the
breathing bars):

- Handoff: the two halves slide level and step apart again.
- Dovetail: the lower block drops out of the joint and locks back in.
- Thread: the stroke draws itself in, end to end.
- Two voices: the overlap fades and lights again.

## Follow-ups after applying

1. `docs/DESIGN.md`: in section 3 change "the logo tile" to the new mark; in section 8 replace the
   "Logo mark: logo tile bars, idle breathing bars on hover" row with the concept's motion.
2. Remove the `.breathe` rules from `src/index.css` (only the old Logo used them; the
   `bar-breathe` keyframes stay, the waveform and button spinner use them).
3. Rename the gallery demo "Logo mark (hover)" if the motion changed meaning.
4. Re-shoot `docs/screens` (`pnpm screens`) and run `pnpm lint`, `pnpm typecheck`, `pnpm test`.
