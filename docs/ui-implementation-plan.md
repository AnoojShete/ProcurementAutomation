# UI implementation plan: Ledger direction

Deliverable 4 of the UI redesign task (17 Oct 2026). It builds the design in
[design-direction.md](design-direction.md) and fixes the problems in
[ui-audit.md](ui-audit.md) (IDs in brackets). Status as of 17 Oct 2026 is
in the next section.

## Status (17 Oct 2026)

| # | State | Notes |
|---|---|---|
| 1 Tokens | Done | `styles/tokens.css`; `brand/surface/success/warning/danger/intel` and the raw `slate/rose/emerald/amber/blue` palettes re-pointed in `tailwind.config.js` |
| 2 Fonts | Done | `@fontsource` Plex Sans/Mono + Source Serif 4, latin + latin-ext, imported in `main.tsx`. Family names must stay quoted in the config ("Source Serif 4" ends in a number) |
| 3 Muted text | Done via tokens | axe: 0 axe violations of any WCAG 2 A/AA rule on 29 routes (was 107 contrast failures) |
| 4 Raw data | Mostly | lifecycle details formatted; SaaS labels; short refs with copy (`RefCopy`). Left: `builtin-ref-…` provider ref on the contract banner |
| 5 Stepper | Done | static current marker + "Waiting on …"; spinner only when `working`; one button per step |
| 6 Docket + strip | Done | `DocketHeader`, `LedgerStrip` on request, contract, vendor, document pages. Licence page not yet |
| 7 Chat trigger | Not moved (Anooj's) | `pb-24` gutter so the last row is never covered; it can still float over content mid-scroll |
| 8 Dashboards | Done | attention first ("Nothing needs you today" when empty), one strip, ruled lists |
| 9 Paper trail | Done on the request page | `Timeline` with `actor` and `stamp`; the stamp animates only for decisions < 2 min old |
| 10 Status | Done | `Badge`/`StatusDot` share one tone map, glyph, sentence case |
| 11 Tables | Done | 36 px rows, keyboard row links (Enter), Tabs on the approval inbox |
| 12 Type scale | Mostly | no text under 12 px; uppercase captions neutralised in CSS; decorative `→` removed |
| 13 Nav / document layout | Done | one active nav item; document page two columns, wrapping `dl` |
| 14 Wizard | Partly | button copy only ("Continue"); label/hint split not done |
| 15 Card diet | Partly | `Section` added and used for paper trails; most panels are still `Card` |
| 16 View Transitions | Not done | CSS hooks and `view-transition-name` on the docket title exist; rows don't pass `viewTransition` yet |
| 17 Login | Done | one sheet, wordmark, "Evaluation accounts" panel |
| 18–21 | Not done | sparklines, dark theme, axe in `showcase_screens.py` |

## Ground rules for every step

- **Keep behaviour:** routes, deep links (`?step=`, `?action=`), one home
  page per item, one action component per agent, and the `loading && !data`
  skeleton rule.
- **Keep the demo script working:** `tests/e2e/showcase_screens.py` waits
  on visible text (`Extracted Fields`, `Risk Signals`, `Sanctions
  Screening`, `Renewal Timeline`, `Kafka log`, `Failed events`, `Reorder
  Suggestions`, `Upload documents`, `Onboard vendor`, `Why was this
  flagged?`…). Keep those strings (sentence case is fine only if the selector
  is updated in the same change).
- **Chat button** (H6) belongs to Anooj. Agree on the placement with them
  before touching `AppShell`'s trigger; don't change `ChatDrawer`.
- **Verify each step:** `cd frontend && npm run build`; rebuild the gateway
  image and restart nginx; screenshot at 1440 px and 390 px; run axe (0
  contrast violations is the target); then `python
  tests/e2e/showcase_screens.py` before a demo.

---

## High impact (do first; together about 3–4 days)

| # | Change | Fixes | Files | Effort | Done when |
|---|---|---|---|---|---|
| 1 | **Tokens.** Add `styles/tokens.css` (CSS variables, reduced-motion block). Re-point existing Tailwind names (`brand`, `surface`, `success`, `warning`, `danger`, `intel`) to the variables. Add `ink`/`paper`/`sheet`/`rule`. | H1, H2 | `tailwind.config.js`, `styles/index.css`, new `styles/tokens.css` | 0.5 d | Every page renders in the Ledger palette with no page edits; typecheck passes |
| 2 | **Fonts.** `npm i @fontsource/ibm-plex-sans @fontsource/ibm-plex-mono @fontsource/source-serif-4`; import 400/500/600 for both `latin` and `latin-ext` (₹ is only in `latin-ext`). Set `font-sans`/`font-mono`/`font-doc`. | H2 | `main.tsx`, `tailwind.config.js` | 0.25 d | Network tab shows fonts served from `'self'` (CSP OK); `₹` renders in Plex |
| 3 | **Muted text sweep.** Replace text uses of `text-slate-400` (107) and `slate-500`-on-subtle with `text-ink-3`/`text-ink-2`; replace off-token `rose/emerald/amber/blue` text and fill (96) with role tokens. | H1, M3 | ~40 files, mechanical | 0.5 d | axe `color-contrast` = 0 on the 24 audited pages |
| 4 | **Raw data formatting.** Lifecycle `detail` via `formatDateTime` and a template-label map (`lib/lifecycle.ts:36`, `:93`); `SaaS` label map; short refs with copy button instead of full UUIDs; risk shown with its scale; "Today" for 0 days; zero values neutral. | H4, H5 | `lib/lifecycle.ts`, `lib/format.ts`, vendor/contract/licence pages, `LicenseIntelligenceCard` | 0.5 d | No ISO strings, snake_case, or bare UUIDs on the showcase screens |
| 5 | **Lifecycle stepper.** Static "current" marker plus "Waiting on: …"; spinner only for agent-processing states; equal structure for the last stage (label alignment); task-list layout on mobile. | H7 | `components/ui/LifecycleStepper.tsx`, `lib/lifecycle.ts` | 0.5 d | Signature step doesn't spin; all labels on one baseline |
| 6 | **Docket header + ledger strip.** Two shared components: `DocketHeader` (mono ref, serif title, status, primary action) and `LedgerStrip` (3–5 figures, double rule). Use them on request, contract, vendor, document, and licence home pages; remove the duplicated metric boxes. | H2, H3 | new `components/ui/DocketHeader.tsx`, `LedgerStrip.tsx`; 5 detail pages | 1 d | Each home page starts with the same docket; no figure shown twice |
| 7 | **Chat trigger placement** (with Anooj). Topbar icon button, or a reserved gutter. | H6 | `layouts/AppShell.tsx`, `Topbar.tsx` | 0.1 d | Nothing overlaps content at 1440 px or 390 px |

## Medium impact (about 3 days)

| # | Change | Fixes | Effort |
|---|---|---|---|
| 8 | **Dashboards re-ordered:** Needs attention first, one ledger strip, ruled sections instead of metric-box rows; zero states as single neutral sentences. | H3, H4 | 1 d |
| 9 | **Paper trail component** (signature feature): merge vendor timeline, approval chain, contract events, and notifications for the item into one ruled spine with *who/agent · what · when*; decision stamps with the 220 ms settle. | H2 | 1 d |
| 10 | **One `Status` component** with one tone map, sentence case, and a glyph; replace `StatusDot`/`Badge` variants and lowercase tags. | M3 | 0.5 d |
| 11 | **Tables:** whole-row links, numbers right-aligned, 36 px rows, remove empty Actions columns, `Tabs` instead of pill filters on the approval inbox. | M4, M5 | 0.5 d |
| 12 | **Typography pass:** 7-step scale; remove `text-[10px]`/`[11px]`, uppercase captions, and appended `→`; page titles at `title`, item titles at `doc-title`. | M6 | 0.5 d |
| 13 | **Fix nav double-active** (`end` on list items) and the **document detail layout** (`dl` gap, empty-preview state, two-column grid). | M1, M2 | 0.25 d |
| 14 | **Wizard form:** short labels + "Optional" marker + hint line; one input height token; "Continue" plus a separate "Skip this step". | M7 | 0.25 d |
| 15 | **Card diet:** `Card` kept for action panels and forms; other sections become ruled `Section`s (same props, so the swap is mechanical). | H3 | 0.5 d |

## Low impact (polish, about 1.5 days)

| # | Change | Fixes |
|---|---|---|
| 16 | List → detail **View Transition** (`viewTransition` on row links; `view-transition-name` on ref + title). Skipped automatically without browser support and under reduced motion. | — |
| 17 | Login as one sheet with a distinct "Evaluation accounts" panel; wordmark replaces "PI". | L7, H2 |
| 18 | Sparklines in the ledger strip where history exists (monthly spend, licence usage), drawn with the existing SVG approach; no chart library. | H3 |
| 19 | Focusable, labelled scroll regions; labels on the risk distribution bar; a better help popover; skeletons that match the real layout; no middle-dot meta strings. | L1–L3, L5, L6 |
| 20 | Optional dark theme via a second token block (values measured in design-direction.md); remove the unused `darkMode` config if not shipped. | M8 |
| 21 | Add an axe pass to `tests/e2e/showcase_screens.py`; add the guardrails in design-direction.md §11 to CLAUDE.md. | — |

## Suggested order for the demo deadline

If time is short, items **1 → 2 → 3 → 4 → 5 → 7** alone change the first
impression and fix every measurable failure (contrast, raw data, misleading
spinner, overlap) in about 2 days, with low risk because they're mostly
config, formatting, and one component. Add **6, 8, 9** next; they carry the
identity (docket, ledger strip, paper trail). Retake the showcase
screenshots after each group.
