# UI audit: the current interface, ranked by impact

Phase 3 of the UI redesign task (17 Oct 2026). Research is in
[ui-research.md](ui-research.md); the proposed fixes are in
[design-direction.md](design-direction.md).

## How this was inspected

- **Live app**, not only code: the running compose stack at
  `localhost:8080`, signed in as each demo role (requester, approver,
  finance, admin). A read-only Playwright script (logins and page visits
  only, no data changed) captured 24 desktop pages at 1440 × 900, 3 mobile
  pages at 390 × 844, and one with the OS set to dark mode.
- **Accessibility**: axe-core 4.10.2 (WCAG 2 A/AA rules) on all 24 desktop
  pages. The gateway's CSP blocks injected scripts, as it should, so axe ran
  in a test-only browser context with CSP bypass. The app was not changed.
- **Code**: counts below are from `grep` over `frontend/src`.
- **Not inspected**: keyboard-only walkthroughs of every flow, screen-reader
  output, real-device Safari, and interactive states (open modals, the
  signing flow, upload in progress). These need a manual pass.

Screenshots referenced below are in `docs/assets/ui-audit/`.

## Verdict

The UI is **clean, consistent, and functional**. It isn't broken, and much
of it is thoughtful. Its problem is that it is **anonymous**: the palette is
GitHub Primer's exact values (`#0969da`, `#d1d9e0`, `#f6f8fa`), the font is
the OS default, and nearly every piece of content sits in the same bordered
white box. Remove the sidebar and the screenshots could be any admin panel.
On top of that sit a measurable contrast problem, some leaking raw data, and
a few layout bugs that an evaluator will notice during a demo.

### What already works (keep it)

| Strength | Where |
|---|---|
| One home page per item; lists link to it | All detail pages |
| Honest, explanatory copy ("missing ones are left out, not guessed"; "Checked 20 minutes ago by the order monitor · runs hourly") | Vendor risk, order status |
| Explanations next to scores (contributing factors with weights) | `vendor-detail.png` |
| Tabular figures for money; lakh grouping (`₹3,32,223`) | Everywhere |
| ⌘K palette, one back arrow, breadcrumb title | Topbar |
| No horizontal scroll at 390 px (measured `scrollWidth = 390` on 3 pages) | `mobile-dashboard.png` |
| Consistent 6 px radius, focus-visible ring, `Button` keeps its label while loading | `components/ui` |
| The control panel's pipeline chips (Drop folder → Kafka → … → E-signature) | Control Panel |

---

## High impact

### H1. Text contrast fails on 23 of 24 pages {#h1}
**Evidence (axe):** 107 failing elements on 23/24 pages. The main
offenders:

| Classes | Colours | Ratio | Count |
|---|---|---|---|
| `text-slate-400` on white (captions, hints, timestamps, field labels) | `#94a3b8` / `#ffffff` | **2.56 : 1** | 59 |
| `text-slate-500` on `surface-subtle` (topbar "Search", table headers) | `#64748b` / `#f6f8fa` | **4.47 : 1** | 32 |
| `text-emerald-600` on `bg-emerald-50` (licence "Normal" tags) | `#059669` / `#ecfdf5` | **3.57 : 1** | 5 |
| `text-rose-600` on `#fff8f9` (savings panel) | | 4.48 : 1 | 2 |

`text-slate-400` appears 107 times in `src/`. It's the default "quiet"
colour, so the problem recurs every time someone writes a caption.
**Fix:** a `fg-muted` token at ≥ 4.5 : 1 on every surface, and stop using
raw `slate-400` for text (allowed only for disabled states and decorative
icons). Proposed values in design-direction.md all measure ≥ 5.0 : 1.

### H2. The product has no visual identity {#h2}
**Evidence:** `tailwind.config.js` colours are Primer's values one for one,
and the font is `-apple-system, BlinkMacSystemFont, Segoe UI…`. The logo is
a black square reading "PI". `login.png` is a centred form with three
stacked boxes. Nothing on any screen says *procurement*, *India*, or
*paper trail*.
**Fix:** the "Ledger" direction: ledger-ruled surfaces, ink colours, IBM
Plex, a serif for document titles, a docket-style header. Most of it is
delivered through tokens, not page rewrites.

### H3. Everything is the same box {#h3}
**Evidence:** 89 `<Card>` + 30 `<MetricCard>` uses. On
`finance-dashboard.png` the page is: 5 metric boxes, a box, a box with 4
sub-boxes and 6 bordered rows, then another box. All have the same weight,
so nothing tells the eye where to start. On `vendor-detail.png` four metric
boxes repeat numbers that the risk panel directly below shows again (score
0.66 appears twice).
**Fix:** cards only where the user acts (forms, action panels). Elsewhere,
use ruled sections: a heading, a hairline, and content on the page surface.
Replace metric-box rows with one **ledger strip**, a single ruled row of
figures with labels, optionally a sparkline. Put "Needs attention" first on
every dashboard; it's the only section that tells the user what to do.

### H4. Zero values and alarm colours that contradict each other {#h4}
**Evidence:** `admin-overview.png`: "POTENTIAL ANNUAL SAVINGS **₹0**,
identified across 0 severely underutilised SaaS licenses" in a pink
`rose` alarm panel, directly under "0 Anomalous · 5 Normal".
`finance-dashboard.png`: "Pending Financial Approval **0**" is the first
and largest figure. Licence list: "Last User Login **0 days ago**" with an
amber clock icon, on every row.
**Fix:** a zero state is good news, so render it neutral and short ("No
reclaimable seats this week"). Never use danger colour for a zero. Write
"Today" instead of "0 days ago". Order dashboard figures by what needs action.

### H5. Raw data leaks into the UI during the demo {#h5}
**Evidence:**
- Request lifecycle shows `2026-10-16T19:48:20.936475Z` under "Request
  Created" and `hardware_purchase` under "Contract" (`request-detail.png`).
  Source: `frontend/src/lib/lifecycle.ts:36` and `:93` pass raw fields as
  `detail`.
- Vendor page shows the full UUID under the name (`vendor-detail.png`).
  Contract page shows the UUID and `builtin-ref-c1dd9930c72da147`.
- Approval inbox type column: "Saas" (CSS `capitalize` on `saas`).
- Risk score shown as a bare `0.66` with no scale ("of 1"? percentile?).
**Fix:** format at the source (`formatDateTime`, a template-label map, a
`SaaS` label map). Show short refs (`VEN-937efc2f`) with copy-on-click for
the full ID. Show risk as "66 / 100", or keep the decimal but add the scale
on first use.

### H6. The floating chat button covers content {#h6}
**Evidence:** the fixed 56 px button at bottom-right overlaps content on 9
of the 13 signed-in screens inspected: the "Contract" link in the control
panel table, the "View details" link on the risk table, the "Financial
stability" input on the vendor page, and the "Backordered" figure on mobile.
**Fix:** move the entry point into the topbar as an icon button next to
Help, or reserve a right-hand gutter. **Owner: Anooj (chatbot)**, so agree
on this with them first. Only the trigger's placement changes, not the
drawer.

### H7. The lifecycle stepper misreports "waiting" as "working" {#h7}
**Evidence:** on `request-detail.png` the current step (Signature) shows a
**spinning** loader, but the request is waiting for a person to sign.
Spinners mean "the system is busy". The last stage's label ("Fulfillment")
sits ~20 px higher than the others because only non-last stages render the
connector element that pushes labels down
(`components/ui/LifecycleStepper.tsx`, `!isLast &&` block).
**Fix:** static "current" marker (filled ring) and a "Waiting on: signer"
line; a spinner only while an agent is actually processing. Give every stage
the same structure (an invisible connector on the last one).

---

## Medium impact

### M1. Two navigation items active at once
Requester sidebar highlights both **My Requests** and **New Request** on
`/app/requests/new` (`new-request.png`): the `/app/requests` item isn't
`end`. Fix: `end: true` on list items that have child routes in nav.

### M2. Document detail layout bugs
`document-detail.png`: (a) "Received" and "Uploaded by
requester@demo…" run together as "ReceivedUploaded by" because the `dl` row
has no gap and the value wraps; (b) the preview area is an empty grey box
for this PDF; (c) "Extracted Fields" is a fixed-width column that leaves the
right third of the page empty.
Fix: `gap-4` + right-aligned wrapping values; a real empty preview state
(file icon, name, "Open PDF"); a 2-column grid (preview | fields) that uses
the full width.

### M3. Five different ways to show a status
`StatusDot` (dot + text), `Badge` (bordered tag), lowercase tags (`active`,
`signed`, `review`), uppercase captions, and off-token colours (31 `rose`,
29 `emerald`, 18 `amber`, 12 `blue` uses). The same "approved/OK" state is
green dot, green tag, or emerald pill, depending on the page.
Fix: one `Status` component, one tone map, sentence case, tokens only.

### M4. Pill tabs on the approval inbox
`approval-inbox.png`: tier filters are `rounded-full` pills, unlike the
`Tabs` component used elsewhere (51 `rounded-full` uses overall, mostly
legitimate dots). The approver's main screen is one table row and 80 % empty
space.
Fix: use `Tabs`; give the approver page the request summary and checks for
the selected row (master–detail), so the approver can decide without a page
change.

### M5. Row actions that wrap and duplicate the row link {#m5}
`risk.png`: "View details →" wraps onto three lines in an 80 px column,
making each row 80 px tall. Licences table has an empty "Actions" column.
Fix: make the whole row the link (GOV.UK task-list pattern) and drop the
column.

### M6. Typography has no scale
Sizes in use: `text-xs` (262), `text-sm` (204), `text-13` (49),
`text-[11px]` (21), `text-[10px]` (4), `lg`/`xl`/`2xl`/`3xl`. That's 10
sizes, 25 of them arbitrary pixel values. Twelve `uppercase tracking-wide`
captions. 27 `→`/`ArrowRight` decorations in link and button text. Page
titles are the same 14 px semibold as panel titles, so pages have no top.
Fix: a 7-step scale (design-direction.md), sentence-case captions, and arrows
only where the arrow *is* the meaning (pipeline chips).

### M7. Wizard form labels carry help text
`new-request.png`: "Estimated Amount in INR (Optional — auto-filled from
document)" and "Department (Optional — defaults to General if skipped)"
wrap to two lines. "Continue (or Skip)" is ambiguous. The wizard's inputs
are 40 px tall, while `.field` elsewhere is 32 px.
Fix: short label + "Optional" marker + hint line below; one input height
token; "Continue" as the button and "Skip this step" as a secondary link.

### M8. No reduced-motion handling, no dark theme
`prefers-reduced-motion` appears 0 times. Spinners and `animate-pulse` run
regardless. `darkMode: "class"` is configured, but there are 0 `dark:`
classes; `dark_pref_home.png` renders light (acceptable, but then remove the
dead config, or deliver dark via tokens).

---

## Low impact

| # | Issue | Evidence | Fix |
|---|---|---|---|
| L1 | Scrollable regions not keyboard-focusable | axe `scrollable-region-focusable` on contract text, licence detail, audit (3 pages) | `tabIndex={0}` + `role="region"` + label |
| L2 | Risk distribution bar has no labels or legend | `risk.png` | Inline labels "Medium 76 · High 3" under the segments |
| L3 | Help popover offers only "Back to dashboard" | Topbar | Link to the demo guide / role-specific tips |
| L4 | Metric labels truncate on mobile ("Pending Financial…") | `mobile-dashboard.png` | Ledger strip wraps labels to 2 lines |
| L5 | Skeletons don't match their content | `SkeletonCard` has a shadow and padding that `MetricCard` lacks | Skeletons generated from the real layout |
| L6 | Middle-dot meta strings ("Finance view · Saturday, October 17, 2026") | Dashboards | Plain sentence or two separate elements |
| L7 | Login is three stacked boxes with demo-account buttons styled like inputs | `login.png` | One sheet; demo accounts as a distinct, labelled evaluation panel |

---

## Responsive and performance notes

- **Responsive:** sidebar collapses into a drawer below `lg`, tables don't
  force horizontal page scroll, and metric boxes go 2-up at 390 px. Good
  base. The weak points are truncation (L4) and the floating button (H6).
- **Performance:** no web fonts (adding them is a new cost, so subset and
  limit weights); no animation library; two hand-built SVG charts. Pages
  poll (`usePolling`), so avoid animating values on every poll.
