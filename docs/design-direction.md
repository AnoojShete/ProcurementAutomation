# Design direction: three concepts, one choice, and the spec

Phases 4–5 of the UI redesign task (17 Oct 2026). Inputs:
[ui-research.md](ui-research.md) (sources) and [ui-audit.md](ui-audit.md)
(problems H1–H7, M1–M8, L1–L7). The build order is in
[ui-implementation-plan.md](ui-implementation-plan.md).

Every colour pair quoted below was measured with the WCAG 2 contrast formula.
Ratios are against the named background. Every font named was checked for
the ₹ glyph (U+20B9) and for tabular figures in the actual `@fontsource`
files.

---

## Concept A: Ledger ("the paper trail")

**Philosophy.** Every purchase leaves a paper trail: request, quote, approval,
contract, signature, invoice. The interface looks like a well-kept ledger and
case file: ruled, precise, quiet, and auditable. The intended impression for
an evaluator or an approver is *"I can trust what this says, and I can see
who did what."*

**Typography.**
- **Source Serif 4** (600) for *item titles only*: a contract, document,
  request, or vendor name at the top of its home page. It's the one place
  the UI says "this is a document".
- **IBM Plex Sans** (400/500/600) for all UI text. Its digits are tabular by
  default (verified), so amounts align in columns.
- **IBM Plex Mono** (400/500) for references: `PR-5c4d789f`, GSTIN, IFSC,
  SHA-256 seals, invoice numbers.

**Palette (light).** Ledger paper green-grey with ink, drawn from columnar
accounting pads. This is deliberately not cream-and-terracotta.

| Token | Hex | Contrast | Use |
|---|---|---|---|
| `paper` | `#F4F6F2` | n/a | App background |
| `sheet` | `#FFFFFF` | n/a | Sections, tables, forms |
| `sheet-sunk` | `#EEF2EC` | n/a | Table header, code/contract text, hover |
| `rule` | `#CED8CF` | n/a (decorative) | Hairlines between rows and sections |
| `rule-strong` | `#7F8D83` | 3.48 on sheet, 3.20 on paper | Input and checkbox borders (meets 3 : 1) |
| `ink` | `#18211C` | 16.49 / 15.17 | Primary text |
| `ink-2` | `#46524A` | 8.18 / 7.53 | Secondary text, labels |
| `ink-3` | `#5C6860` | 5.83 / 5.36 | Captions, timestamps (replaces `slate-400`) |
| `accent` (ink blue) | `#1F4B8F` | 8.53 / 7.85; white on it 8.53 | Primary actions, links, current step, focus ring |
| `accent-hover` | `#173A70` | 11.20 | Hover/pressed |
| `accent-tint` | `#E8EEF7` | accent on it 7.31 | Selected row, info notes |
| `done` / `done-tint` | `#1E6B3A` / `#E6F2EA` | 5.67 on tint | Completed, approved, signed |
| `attention` / `attention-tint` | `#7A4E00` / `#FFF3D1` | 6.51 on tint | Waiting, due soon, needs review |
| `danger` / `danger-tint` | `#B42318` / `#FDECEA` | 5.75 on tint; white on it 6.57 | Rejected, failed, high risk, overdue |

**Surfaces.** Flat. No drop shadows on page content. Sections are white
sheets on paper, separated by space and a hairline, not a box per item.
Totals get the accountant's **double rule** (two 1 px lines, 2 px apart).

**Layout.** Max content width 1200 px. Every item page has the same
skeleton: a **docket header** (mono reference, serif title, status, and a
ledger strip of 3–5 key figures), then a main column (8/12) and the **paper
trail** rail (4/12) at ≥ 1280 px. Dashboards open with "Needs attention",
then one ledger strip, then ruled sections.

**Navigation and components.** Keep the sidebar and its routes; Linear
deferred navigation changes for the same reason. Restyle it: paper
background, active item = ink text + a 2 px accent rule, no filled box.
Buttons are rectangular (4 px radius), never pills. Status tags are sentence
case with a 2 px radius, tint fill, and tone text. Tables have 36 px ruled
rows and right-aligned numbers, and whole rows are links.

**Motion.** Two moments, both tied to real events:
1. **List → detail**: the clicked row's reference and title carry into the
   docket header (View Transitions via React Router's `viewTransition`).
2. **Decision stamp**: when an approval or signature completes, an
   "Approved" or "Signed" stamp mark settles into the paper trail (scale
   0.96 → 1, opacity 0 → 1, 220 ms).

Everything else is instant or a 100 ms colour change.

**Signature feature: the paper trail.** A ruled vertical spine on every item
page listing each event with *who* (person or agent), *what*, and *when*,
ending in a stamp for decisions. It's built from data we already have
(vendor timeline, approval chain, contract events, notifications). It
explains the multi-agent system without any "AI" styling: *"Contract & Risk
agent · generated contract from template Hardware Purchase · 17 Oct, 01:18"*.

**Trade-offs.**
- *Accessibility:* strongest of the three. Every text pair is ≥ 5.0 : 1.
- *Complexity:* low to medium. Mostly tokens and about 6 shared components;
  the paper trail is one new component.
- *Performance:* 3 families × 2–3 weights × 2 subsets ≈ 10–14 woff2 files,
  of which only the weights used are fetched.
- *Risk:* serif overuse would look like a blog, so it's restricted to item
  titles.

```
┌ paper ─────────────────────────────────────────────────────────────────┐
│ PR-5c4d789f · Hardware request          (mono, ink-3)                  │
│ Hardware Procurement — IT               (Source Serif 26/600)          │
│ ● Waiting on signer                                    [Sign now]      │
│ ─────────────────────────────────────────────────────────────────────  │
│ Amount        Vendor risk     Approval        Contract                 │
│ ₹3,000        Medium · 46     1 of 1 done     Sent 17 Oct              │
│ ═════════════════════════════════════════════════════════════════════  │
│ Lifecycle (task list, whole rows clickable)  │ Paper trail             │
│ ✓ Request created          16 Oct, 19:48     │ │ 16 Oct 19:48 requester│
│ ✓ Vendor validated         Vendor matched    │ │ 17 Oct 01:18 Approved ▣│
│ ● Signature                Waiting on signer │ │ 17 Oct 01:18 Contract │
│ ○ Fulfilment                                 │ │   agent: generated    │
└──────────────────────────────────────────────┴─────────────────────────┘
```

---

## Concept B: Control Room

**Philosophy.** Five agents are machinery, and this is the operator's
console. The impression is *live, technical, and powerful*: you watch events
move through Kafka.

**Typography.** **Archivo** variable (width axis; semi-condensed for labels
and table headers, normal for body; ₹ in `latin-ext`) + **IBM Plex Mono**
for every figure and ID.

**Palette (dark-first).**

| Token | Hex | Contrast on `bg` |
|---|---|---|
| `bg` | `#101315` | n/a |
| `surface` / `raised` | `#171B1E` / `#1F2428` | n/a |
| `line` | `#2E363B` | n/a |
| `text` / `text-2` / `text-3` | `#E7EAEC` / `#A7B0B6` / `#8A949B` | 15.43 / 8.46 / 6.03 |
| `signal` (sodium amber, actions) | `#F2A93B` | 9.34 (dark text on it 9.34) |
| `ok` / `fault` / `info` | `#43B98F` / `#F2707A` / `#76AFFF` | 7.62 / 6.55 / 8.30 |

**Surfaces.** Stacked dark planes, 1 px lines, no shadows; "LED" status dots.

**Layout.** Three panes: a 56 px icon rail, the work area with 32 px dense
rows, and a right **event rail** streaming the Kafka log.

**Navigation and components.** Icon rail with tooltips; segmented controls;
square buttons; monospace tables.

**Motion.** Events slide into the rail (transform only); LEDs pulse while an
agent is processing.

**Signature feature: the agent rail.** A strip under the topbar with five
lanes, one per agent, ticking as events arrive (from the existing control
panel data).

**Trade-offs.**
- *Accessibility:* contrast is fine. Constant motion is a problem for
  vestibular users and attention, and dark-first is hard to read on a
  classroom projector.
- *Fit:* flatters the admin, but requesters and approvers don't care about
  Kafka. It's the "near-black with one bright accent" look the Anthropic
  skill names as a second-order AI default.
- *Complexity:* high (layout change on every page, live streaming UI).
- *Performance:* continuous polling plus animation.

---

## Concept C: Five Desks

**Philosophy.** Every step is handled by a named agent "desk", and colour
tells you which desk owns what. The impression is *organised and
explainable*: the multi-agent architecture is visible to an evaluator in
one glance.

**Typography.** **Public Sans** only (₹ and `tnum` verified), using size
and weight for hierarchy: large 34–48 px display numerals for key figures,
and a strict Swiss scale.

**Palette.**

| Token | Hex | Contrast (white / canvas) |
|---|---|---|
| `white` / `canvas` | `#FFFFFF` / `#F3F3F0` | n/a |
| `ink` / `ink-2` | `#1B1B1A` / `#55554F` | 17.24 / 7.50 |
| Documents & Vendors (teal) | `#0E6E66` | 6.10 / 5.49 |
| Approval & Inventory (blue) | `#2E4FB8` | 7.18 / 6.45 |
| Contract & Risk (brick) | `#A2461B` | 6.13 / 5.51 |
| Notifications (olive) | `#5E6B12` | 5.85 / 5.26 |
| `line` | `#DADAD3` | n/a |

**Surfaces.** White, with full-bleed coloured bands; no cards.

**Layout.** A 12-column grid, master–detail lists, and oversized numerals.

**Navigation and components.** Sidebar grouped by desk, each group marked
with its colour; tags carry a desk colour bar.

**Motion.** Band segments fill when a stage changes hands.

**Signature feature: the hand-off band.** A full-width segmented band on
each request; each segment is coloured by the agent that owns that step.

**Trade-offs.**
- *Accessibility:* 4 identity hues plus 3 status hues makes 7. Brick
  collides with danger red and olive with success green. Colour carries
  meaning, so every use needs a text label.
- *Complexity:* medium.
- *Fit:* strongest for telling the architecture story, weakest for everyday
  users, who care about *their* request, not which service handled it.

---

## Decision: Concept A, Ledger

| Criterion | A Ledger | B Control Room | C Five Desks |
|---|---|---|---|
| Product identity (procurement, audit) | **Strong**: built from the domain's own materials | Strong for ops and infra; weak for procurement | Strong for architecture |
| Task efficiency for all 4 roles | **High**: attention first, row links, task-list lifecycle | Admin only | Medium: colour legend to learn |
| Distinctiveness | **High**: serif docket, double rules, paper trail, stamps | Medium: a known dark-console genre | High |
| Professional credibility | **Highest**: reads like finance software | Medium | Medium–high |
| Accessibility | **All text ≥ 5.0 : 1**, little motion | Motion and dark-first issues | 7-hue collisions |
| Responsiveness | Two columns stack naturally | Three panes don't fit at 390 px | Bands work |
| Implementation risk | **Low–medium**: tokens keep class names | High | Medium |
| Fit with existing code | **Highest**: same structure, CLAUDE.md conventions intact | Rewrites the shell | Rewrites nav |

**Why A.** It fixes the two biggest audit problems, anonymity (H2) and
same-box monotony (H3), from the product's own vernacular rather than from
a trend. It delivers H1 (contrast) by construction. Most of it lands through
token changes that keep existing Tailwind class names working, which suits a
97 %-complete codebase and a student team that must explain every choice.

**Borrowed from C:** agent attribution, as *words* in the paper trail
("Contract & Risk agent · …"), not as colour. Evaluators still see the
multi-agent design without a 7-hue palette.

---

## Design specification (Ledger)

### 1. Tokens

Implemented as CSS variables holding bare RGB channels (Tailwind v3 pattern,
so `/50` opacity modifiers keep working). The **existing class names are
re-pointed**, so `bg-brand-500`, `border-surface-border`, and so on change
colour everywhere without editing page files.

```css
/* frontend/src/styles/tokens.css */
:root {
  /* surfaces */
  --paper: 244 246 242;        /* #F4F6F2 */
  --sheet: 255 255 255;        /* #FFFFFF */
  --sheet-sunk: 238 242 236;   /* #EEF2EC */
  --rule: 206 216 207;         /* #CED8CF */
  --rule-strong: 127 141 131;  /* #7F8D83 */
  /* text */
  --ink: 24 33 28;             /* #18211C */
  --ink-2: 70 82 74;           /* #46524A */
  --ink-3: 92 104 96;          /* #5C6860 */
  /* roles */
  --accent: 31 75 143;         /* #1F4B8F */
  --accent-hover: 23 58 112;   /* #173A70 */
  --accent-tint: 232 238 247;  /* #E8EEF7 */
  --done: 30 107 58;           /* #1E6B3A */
  --done-tint: 230 242 234;    /* #E6F2EA */
  --attention: 122 78 0;       /* #7A4E00 */
  --attention-tint: 255 243 209; /* #FFF3D1 */
  --danger: 180 35 24;         /* #B42318 */
  --danger-tint: 253 236 234;  /* #FDECEA */
  /* type */
  --font-ui: "IBM Plex Sans", system-ui, sans-serif;
  --font-doc: "Source Serif 4", Georgia, serif;
  --font-ref: "IBM Plex Mono", ui-monospace, monospace;
  /* motion */
  --dur-1: 100ms; --dur-2: 160ms; --dur-3: 220ms;
  --ease-out: cubic-bezier(0.2, 0, 0, 1);
  --ease-in: cubic-bezier(0.4, 0, 1, 1);
}
@media (prefers-reduced-motion: reduce) {
  :root { --dur-1: 0.01ms; --dur-2: 0.01ms; --dur-3: 0.01ms; }
}
```

Mapping in `tailwind.config.js` (the shape, not the full file):

```js
const c = (v) => `rgb(var(--${v}) / <alpha-value>)`;
colors: {
  paper: c("paper"), sheet: c("sheet"), rule: c("rule"),
  ink: { DEFAULT: c("ink"), 2: c("ink-2"), 3: c("ink-3") },
  surface: { DEFAULT: c("sheet"), subtle: c("paper"), muted: c("sheet-sunk"), border: c("rule") },
  brand: { 50: c("accent-tint"), 500: c("accent"), 600: c("accent-hover"), 700: c("accent-hover") /* … */ },
  success: { 50: c("done-tint"), 500: c("done"), 600: c("done"), 700: c("done") },
  warning: { 50: c("attention-tint"), 500: c("attention"), 600: c("attention"), 700: c("attention") },
  danger:  { 50: c("danger-tint"), 500: c("danger"), 600: c("danger"), 700: c("danger") },
}
```

**Optional dark theme** (measured; deliver later via a second `:root` block
if wanted): paper `#121614`, sheet `#181D1A`, ink `#E6EBE7` (14.15 on
sheet), ink-2 `#B3BDB6` (8.84), ink-3 `#929D96` (6.09), accent `#8DB0EC`
(7.77; dark text on it 8.30), danger `#F08A80` (7.04), attention `#E2B457`
(8.87), done `#6CC08C` (7.77), rule `#2C3430`, rule-strong `#5E6A63` (3.02
on sheet; inputs sit on sheet only).

### 2. Typography scale

| Step | Size / line height | Family, weight | Use |
|---|---|---|---|
| `caption` | 12 / 16 | Plex Sans 400, `ink-3` | Timestamps, hints. **Minimum size**: no 10/11 px. |
| `meta` | 13 / 20 | Plex Sans 400 | Table cells, metadata |
| `body` | 14 / 22 | Plex Sans 400 | Default text |
| `label` | 14 / 20 | Plex Sans 500 | Field labels, nav, section titles |
| `heading` | 16 / 24 | Plex Sans 600 | Section headings. Also inputs on mobile (prevents iOS zoom). |
| `title` | 20 / 28 | Plex Sans 600 | List and dashboard page titles |
| `doc-title` | 26 / 32 | Source Serif 4 600 | Item titles on home pages only |
| `figure` | 28 / 32 | Plex Sans 500 | Ledger-strip figures (tabular by default) |
| `ref` | 12–13 | Plex Mono 400 | IDs, GSTIN, hashes |

Rules: sentence case everywhere, including captions (no `uppercase
tracking-wide`). Line length ≤ 75 characters for prose (contract text,
explanations). No `→` appended to button or link text; arrows only where
direction *is* the meaning (pipeline chips).

### 3. Spacing

4 px base. Steps: 4, 8, 12, 16, 24, 32, 48 (Tailwind `1 2 3 4 6 8 12`).
- Inside a row or control: 8–12.
- Section padding: 16 (mobile), 24 (≥ md).
- Between sections: 32. Between page header and content: 24.
- Table rows: 36 px (Carbon "small–medium"). Dense admin logs: 32 px.

### 4. Layout rules

- Content max width 1200 px, left-aligned in the main area (not centred
  in a 1320 px frame).
- **Item home pages:** docket header → ledger strip → `grid-cols-12`: main
  `col-span-8`, paper trail `col-span-4` at ≥ 1280 px, stacked below (trail
  after main).
- **Dashboards:** 1. Needs attention (always first; when empty, one line:
  "Nothing needs you today"). 2. Ledger strip (3–5 figures, ordered by
  actionability). 3. Ruled sections.
- **Lists:** filters bar above the table; whole row is the link; empty
  "Actions" columns removed.
- **Cards** only for things you act on: forms, the action panel (approve,
  sign, verify), modals. Everything else is a ruled section.
- **Floating elements** never cover content (H6).

### 5. Component states

| Component | Rest | Hover | Active / selected | Focus | Disabled | Loading |
|---|---|---|---|---|---|---|
| Button, primary | `accent` fill, white text | `accent-hover` | `accent-hover` + inset 1 px | 2 px `accent` ring, 2 px offset | 40 % opacity, no hover | Spinner replaces icon; label stays; disabled after 150 ms (no flicker) |
| Button, secondary | `sheet`, 1 px `rule-strong`, `ink` text | `sheet-sunk` | `rule` fill | same ring | `ink-3` text | same |
| Button, danger | `sheet`, `danger` text and border | `danger` fill, white | n/a | same ring | n/a | same |
| Input | `sheet`, 1 px `rule-strong`, 36 px (40 px mobile) | border `ink-3` | n/a | 2 px `accent` ring | `sheet-sunk` fill | n/a |
| Input, error | 1 px `danger` + message below in `danger` 12 px | | | | | |
| Table row | `sheet`, hairline `rule` | `sheet-sunk` | `accent-tint` + 2 px left `accent` rule | ring inset | n/a | skeleton rows of real height |
| Status tag | tint fill + tone text, 2 px radius, 20 px tall, sentence case, leading glyph (✓ ● ○ ✕) | n/a | n/a | n/a | n/a | n/a |
| Lifecycle step | done ✓ `done` · current ● `accent` + "Waiting on: X" · working: spinner (only while an agent runs) · pending ○ `ink-3` · blocked ⊘ · failed ✕ `danger` | row `sheet-sunk` | `accent-tint` | ring | n/a | n/a |
| Nav item | `ink-2` text | `ink`, `sheet-sunk` | `ink` 500 + 2 px `accent` rule left | ring | n/a | n/a |

**Feedback and empty states.** Success: an inline confirmation in the panel
where the action happened (it already stays mounted thanks to the
`loading && !data` rule), plus a stamp in the paper trail for decisions.
Error: the `{error: {code, message}}` message next to the control, never
only a toast. Empty: one sentence saying why it's empty, plus the next
action ("No contracts yet. They're generated when a request is approved.").
Zero values in neutral colour (H4).

### 6. Borders, shadows, radius, surfaces

- **Radius:** 2 px tags; 4 px buttons, inputs, sections; 8 px modals and
  popovers only. Children never exceed their parent's radius. No pills
  except avatar circles and status dots.
- **Borders:** 1 px `rule` between rows and around sections; `rule-strong`
  for interactive boundaries; double rule (`border-b-[3px] border-double`)
  under totals and the docket header.
- **Shadows:** none on page content. Floating layers (popover, menu, modal,
  palette) only: `0 1px 2px rgb(24 33 28 / .08), 0 8px 24px rgb(24 33 28 /
  .12)`. A section never has both a border and a shadow.
- **Background:** flat `paper`. No gradients, no grain, no glass.

### 7. Iconography

lucide-react (already installed), 1.75 stroke, 16 px in UI and 14 px in
tables, `ink-2` (never `slate-400`). Icons accompany labels; they never
carry state alone. No emoji. The "PI" square is replaced by a simple
wordmark: "Procurement" in Plex Sans 600 with a 2 px double rule under it.

### 8. Motion

| Token | Duration | Easing | Used for |
|---|---|---|---|
| `--dur-1` | 100 ms | `--ease-out` | Colour and background on hover/press |
| `--dur-2` | 160 ms | `--ease-out` in, `--ease-in` out | Popover, menu, palette, drawer |
| `--dur-3` | 220 ms | `--ease-out` | List → detail view transition; decision stamp |

Only `transform`, `opacity`, and colours; never `transition: all`. Reduced
motion sets durations to 0.01 ms (not `none`, so `animationend` handlers
still fire). Spinners appear only after 150 ms and stay at least 300 ms.
Nothing animates on polling refreshes.

### 9. Breakpoints

Tailwind defaults, used as follows:

| Width | Behaviour |
|---|---|
| < 640 | Single column; ledger strip 2-up with wrapping labels; tables become stacked rows (label: value) for item lists; inputs 16 px text |
| ≥ 640 `sm` | Ledger strip 3-up; tables stay tables with horizontal scroll *inside* the section |
| ≥ 1024 `lg` | Sidebar visible (as now) |
| ≥ 1280 `xl` | Paper trail rail beside the main column |

### 10. Accessibility requirements (acceptance criteria)

1. axe-core: **0 `color-contrast` violations** on the 24 audited pages
   (currently 107).
2. All text ≥ 4.5 : 1; input/checkbox borders and focus rings ≥ 3 : 1
   (token values above meet these).
3. Pointer targets ≥ 24 × 24 px (WCAG 2.2 2.5.8); 44 px for primary mobile
   actions.
4. Status always has text (and a glyph); colour is never the only signal.
5. Scrollable regions focusable and labelled (L1).
6. `prefers-reduced-motion` honoured globally.
7. A "Skip to content" link; one `h1` per page (the docket or page title).
8. Keyboard: every row link and lifecycle step reachable and operable;
   focus returns to the trigger when a modal closes.

### 11. Guardrails (add to CLAUDE.md once built)

- Use tokens (`ink`, `ink-2`, `ink-3`, `paper`, `sheet`, role colours), not
  raw `slate/rose/emerald/amber/blue` classes.
- Serif only for item titles. No uppercase captions. No `→` in button text.
- Cards only around things you act on.
- Status via the shared `Status` component only.
