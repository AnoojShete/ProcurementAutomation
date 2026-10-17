# UI research: references and what to take from them

Phase 1–2 of the UI redesign task (17 Oct 2026). Companion files:
[ui-audit.md](ui-audit.md) (current problems, ranked) and
[design-direction.md](design-direction.md) (three concepts, the chosen one,
tokens, and the implementation plan).

**How this was gathered.** Each source below was opened during the research
(web fetch of the original page, or the original repository). Under each
source, **Observed** is what the source itself says or shows, and **For us**
is my recommendation. Where I couldn't see a product's UI (e.g. it's behind a
login), I say so rather than describe screens I haven't seen.

---

## 0. The product, before choosing any look

Taken from the code and the running stack (`localhost:8080`, all services
healthy), not from the docs alone.

| Question | Answer |
|---|---|
| What it does | Runs an IT purchase from request to signed contract: document intake (OCR + classification), vendor onboarding and risk, approval routing with SLAs, contract generation and e-signature, licence-usage anomalies, inventory reorder, notifications. Five agents talk over Kafka. |
| Who uses it | Four roles with different navigation (`frontend/src/lib/roleNav.ts`): **requester** (6 nav items), **approver** (7), **finance** (10), **admin** (16). |
| Most important objects | Request, document, vendor, contract, licence. Each has **one home page** (CLAUDE.md convention), and lists and dashboards link to it. |
| Locale | India: ₹ with lakh grouping (`₹3,32,223`), GSTIN, IFSC, sanctions lists. |
| Stack | React 18, React Router 6.30 (data router: `createBrowserRouter`), Tailwind 3.4, lucide-react icons, no component library, two hand-built SVG charts. No animation library. |
| Hard constraints | Gateway CSP is `font-src 'self' data:` and `script-src 'self'`, so **Google Fonts and CDN scripts are blocked**; fonts must be bundled (e.g. `@fontsource`). The chat drawer and its floating button belong to Anooj (team boundary in CLAUDE.md). Deep links (`?step=`, `?action=`) and `tests/e2e/showcase_screens.py` selectors (`text=Extracted Fields`, `text=Risk Signals`, …) must keep working. |
| Demo-critical screens | From `docs/showcase.html` and `tests/e2e/showcase_screens.py`: login → role dashboards → document upload and detail (extracted fields) → vendor detail (risk, sanctions) → approval queue → request detail (lifecycle stepper) → contract detail (risk, signing) → licences → business rules → control panel (Kafka log, failed events). |
| What already works | One-home-per-item navigation, ⌘K palette, a single back arrow, honest explanatory copy ("missing ones are left out, not guessed"), tabular figures, a consistent 6 px radius, no horizontal scroll at 390 px (measured). |

So the identity has to come from **procurement itself**: paper trails,
ledgers, documents, signatures, audit. It should not come from "AI".

---

## 1. Production interfaces in this domain

### Ramp Procurement (help-centre documentation)
- https://support.ramp.com/get-started-with-procurement
- https://support.ramp.com/agentic-intake-programs
- **Observed (from Ramp's docs, not the UI, which is behind a login):**
  intake forms always start with two fixed questions, then conditional ones.
  Intake answers drive routing ("IT and security route in automatically when
  sensitive data is involved; FP&A pulled in when the amount clears
  $10,000"). Each approval step gets a generated summary with a
  recommendation and per-check findings, but the person approves or rejects.
  Approvers can approve, reject, or *request changes*. A PO is created
  automatically once a request is fully approved.
- **For us:** the closest competitor to our flow, and it validates our
  model: agents gather the evidence, a person decides. The approval screen
  should open with the checks (risk, budget, duplicate, policy route) as a
  short verdict list above the request details. Right now
  `ProcurementAssessment` sits in a side column on the request page.

### Zip (intake-to-procure)
- https://ziphq.com/products/intake-to-procure
- **Observed (marketing copy only; no UI walkthrough found):** intake forms
  "adapt questions and selections based on how requesters answer". Requests
  route to "queues and user hierarchies". The pitch stresses giving
  employees "complete visibility into request progress".
- **For us:** "visibility into request progress" is the requester's main
  need. Our `LifecycleStepper` already provides it. It deserves to be the
  signature element of the request page (see design-direction.md), not one
  boxed card among many.

### Linear: "How we redesigned the Linear UI"
- https://linear.app/now/how-we-redesigned-the-linear-ui
- **Observed:** themes cut from 98 variables to **3 inputs** (base, accent,
  contrast), generated in **LCH** "because it is perceptually uniform". A
  contrast variable gives high-contrast themes for accessibility. Blue was
  deliberately limited "to make the look more neutral and timeless".
  Sidebar, tabs, and headers were adjusted to "reduce visual noise, maintain
  visual alignment, and increase the hierarchy and density of navigation
  elements". Inter Display was used for headings only. They deliberately
  *deferred* navigation changes because those change user behaviour.
- **For us:** (a) a small set of semantic tokens instead of raw palette
  classes (we have 96 off-token `rose/emerald/amber/blue` uses); (b) fix the
  visual layer first and leave navigation alone, which is exactly right for a
  97 %-done project; (c) a heading face distinct from the UI face.

### Stripe: "Designing accessible color systems"
- https://stripe.com/blog/accessible-color-systems
- **Observed:** colours were built in CIELAB so every hue follows the **same
  lightness curve**. As a result, "any two colors at least five levels apart"
  pass 4.5:1 for small text, and four levels apart pass for icons and large
  text. Badges that were hard to distinguish were fixed by moving both
  background and text up one level, not by hand-tuning pairs.
- **For us:** our status colours (success/warning/danger/brand) are tuned
  pair by pair. A level rule ("tag text = level 11, tag fill = level 2") makes
  every status tag pass by construction. I checked every pair proposed in
  design-direction.md against WCAG 2 (ratios listed there).

---

## 2. Distinctive but usable layouts and identities

### GOV.UK Design System: task list
- https://design-system.service.gov.uk/components/task-list
- https://designnotes.blog.gov.uk/2023/12/15/working-as-a-community-to-iterate-the-task-list-pattern/
- https://designnotes.blog.gov.uk/2017/04/04/weve-published-the-task-list-pattern
- **Observed:** a multi-step application is shown as a list of tasks, each
  with a **text** status. The 2023 iteration **removed uppercase from status
  tags**, made the **whole row clickable**, and added hint text. In 2017,
  research found users read black status text as "a problem", so "Completed"
  became blue.
- **For us:** our 8-step lifecycle is exactly a task list, and our approvers
  and requesters aren't procurement experts. Three borrowings: whole-row
  click targets (risk table's three-line "View details →" link,
  [audit](ui-audit.md#m5)); sentence-case status labels (we have 12
  `uppercase tracking-wide` labels); test what a status colour *means* to
  users, not only whether it passes contrast.

### Edward Tufte: sparklines
- https://www.edwardtufte.com/notebook/sparkline-theory-and-practice-edward-tufte/
- **Observed:** "a small intense, simple, word-sized graphic with typographic
  resolution". "Avoid all data frames". "max[data], min[design]".
- **For us:** our dashboards show bare numbers in boxes ("Monthly Spend
  ₹3,32,223", "Active Contracts 98") with no sense of trend. The data exists
  (licence usage history, monthly spend). A word-sized line next to the
  number, with no frame, adds meaning without another card. This is a real
  data feature, not decoration.

### OpenAI: "Designing delightful frontends with GPT-5.4"
- https://developers.openai.com/blog/designing-delightful-frontends-with-gpt-5-4
- **Observed:** "Cards are allowed only when they are the container for a
  user interaction." A "brand first" test: if the first viewport "could
  belong to another brand" once the nav is removed, branding is too weak.
  Avoid "fixed or floating UI that overlaps key content". Verify with
  Playwright across viewports.
- **For us:** every one of these is a live issue. 89 `<Card>` and 30
  `<MetricCard>` uses wrap nearly all content in identical boxes. Strip the
  sidebar and our dashboard could be any GitHub-styled admin. The floating
  chat button overlaps content on 9 of the 13 signed-in screens I
  inspected (whatever sits in the bottom-right corner).

---

## 3. Typography, spacing, hierarchy, colour

### IBM Plex
- https://github.com/IBM/plex
- **Observed:** Sans, Serif, Mono, and Sans Condensed, all with true
  italics. Designed "to work well in user interface (UI) environments". OFL
  1.1.
- **Verified for this project** (font files downloaded from the
  `@fontsource` packages and inspected with fontTools): Plex Sans and Plex
  Mono have **tabular digits by default** (all ten digits the same width), so
  amounts align without `tabular-nums`. The **₹ glyph (U+20B9) is only in the
  `latin-ext` subset**, so both `latin` and `latin-ext` must be loaded or
  every amount falls back to another font mid-number.
- **For us:** a UI face built by an enterprise, with an industrial,
  slightly mechanical character that suits ledgers and documents. It avoids
  the "Inter everywhere" default, and its Mono sibling suits reference
  numbers (PR-5c4d789f, GSTIN, IFSC, SHA-256 seals) that we already show in
  `font-mono`.

### Source Serif 4
- https://fontsource.org/fonts/source-serif-4 (Adobe, OFL; packages
  `@fontsource/source-serif-4` 5.3.x checked on npm)
- **Verified:** ₹ in `latin-ext`, has `tnum` and `pnum` features.
- **For us:** a serif for **page titles of documents and contracts only**,
  so that contracts and invoices read like documents and the operational UI
  reads like a tool. Used only for titles, so performance cost is limited to
  one or two weights.

### Primer (GitHub): colour usage
- https://primer.style/product/getting-started/foundations/color-usage
- **Observed:** base tokens "should never be used directly in code";
  functional tokens (`fg`, `bg`, `border`, each `muted` / `emphasis`) carry
  meaning. "Emphasis background colors … are always combined with
  `fgColor-onEmphasis`".
- **For us:** our current palette is literally Primer's (`brand-500` =
  `#0969da`, `surface-border` = `#d1d9e0`), which is why the app reads as a
  GitHub clone. Keep Primer's *structure* (functional tokens), drop its
  *values*.

### Radix Colors: the 12-step scale
- https://www.radix-ui.com/colors/docs/palette-composition/understanding-the-scale
- **Observed:** steps 1–2 for backgrounds, 3–5 for component fill
  (normal/hover/pressed), 6–8 for borders (8 for focus rings), 9–10 for solid
  fills, 11–12 for text. "Steps 11 and 12 are guaranteed to Lc 60 and Lc 90
  APCA" on step 2.
- **For us:** a ready-made vocabulary for naming our tokens so students can
  explain *why* each colour is where it is.

### Tailwind v3: colours as CSS variables
- https://v3.tailwindcss.com/docs/customizing-colors#using-css-variables
- **Observed:** store bare channels (`--color-primary: 255 115 179;`) and
  map them in the config as `rgb(var(--color-primary))`, or opacity
  modifiers break.
- **For us:** this is how we change the look **without touching 50 page
  files**. Keep the existing class names (`brand-*`, `surface-*`,
  `success-*`…) but point them at CSS variables. Dark mode then becomes a
  second `:root` block.

---

## 4. Micro-interactions, transitions, loading, feedback

### Vercel: Web Interface Guidelines
- https://github.com/vercel-labs/web-interface-guidelines
- **Observed (quoted rules):** "Show a loading indicator & keep the original
  label." Add a show-delay and minimum visible time so spinners don't
  flicker. "Update the UI immediately when success is likely." "Never
  `transition: all`." "Honor `prefers-reduced-motion`." "Skeletons mirror
  final content exactly." "Don't rely on color alone; include text labels."
  Use tabular numbers for comparisons. Use 0 *or* 2 decimal places for
  currency per context, never both. Separate numbers and units with a
  non-breaking space. Use at least two shadow layers. Child radius ≤ parent
  radius.
- **For us:** the most directly usable checklist. Several items are already
  done (tabular figures, focus-visible ring). Several are open: reduced
  motion (0 uses in `src/`), the `Button` loading state replaces the icon
  but not the label (good), and skeletons that don't match their content
  (`SkeletonCard` has `shadow-card` and padding that the real
  `MetricCard` doesn't).

### MDN: View Transition API; React Router `viewTransition`
- https://developer.mozilla.org/en-US/docs/Web/API/View_Transition_API
- https://reactrouter.com/v6/components/link
- **Observed:** `document.startViewTransition()` animates between DOM
  states, and `view-transition-name` pairs elements across states. React
  Router v6 exposes it as the `viewTransition` prop on `Link`/`NavLink`,
  which "only works when using a data router" (we are on one).
- **For us:** one motion moment with a purpose: the row you click in a list
  (request ID + title) carries over into the detail page header, so the user
  sees *where they went*. Zero dependencies, and browsers without support
  simply navigate instantly.

### web.dev: `prefers-reduced-motion`
- https://web.dev/articles/prefers-reduced-motion
- **Observed:** treat animation as opt-in under `no-preference`. For some
  users "reducing animations is a medical necessity". Blunt `animation: none`
  can break code that waits for `animationend`, so shorten durations instead.
- **For us:** implement as a global near-zero duration rule, not `none`.

---

## 5. Libraries, techniques, tools

| Tool | Status here | Recommendation |
|---|---|---|
| `@fontsource/ibm-plex-sans`, `-mono`, `@fontsource/source-serif-4` (5.3.x on npm) | Not installed | **Use.** Bundled by Vite, so it satisfies `font-src 'self'`. Import only 400/500/600 and the `latin` + `latin-ext` subsets. |
| View Transitions via React Router `viewTransition` | Available (RR 6.30.6, data router) | **Use** for list → detail only. |
| Motion (motion.dev) / Framer Motion | Not installed | **Don't add.** CSS transitions and View Transitions cover what's needed. A new dependency isn't justified for a 97 %-done app. |
| shadcn/ui, Radix Primitives | Not installed | **Don't adopt wholesale.** We have working hand-built components and a CLAUDE.md rule of one action component per agent. Borrow Radix's colour-scale *naming* only. |
| axe-core 4.10.2 | Used for this audit (in a Playwright context with CSP bypass; app unchanged) | Add an axe pass to `tests/e2e/showcase_screens.py` later (low priority). |

---

## 6. Prompts, skills, and workflows for coding agents

### Anthropic `frontend-design` skill
- https://raw.githubusercontent.com/anthropics/skills/main/skills/frontend-design/SKILL.md
- **Observed:** "The subject's industry, subject matter, materials, and
  vernacular are where distinctive visual choices come from." Work in two
  passes: draft a compact token system, then review it against the brief and
  revise generic parts **before** coding. "Visual structure is information."
  Use numbered markers only for real sequences. Its avoid-list includes
  "Using all caps for labels", "a '→' appended to link and button text",
  "fade-and-slide-up entrances on each section", "Templated SaaS card
  grids", "meta strings joined with middle dots", and the second-order
  defaults "cream backgrounds with terracotta accents" and "near-black with
  one bright accent".
- **For us:** the "materials and vernacular" rule produced the recommended
  direction (ledger paper, ink, the paper trail). The avoid-list maps onto
  concrete current issues: 12 uppercase labels, 27 `→`/`ArrowRight` uses,
  "Finance view · Saturday…" middle-dot meta strings.

### OpenKBS: frontend design guide
- https://openkbs.com/docs/frontend-design/
- **Observed:** "Pick an extreme and commit." Avoid Arial/Inter/Roboto **and
  system fonts**. "Justify every gradient stop or skip the gradient." Don't
  put both a border and a drop shadow on the same card. "Never use emoji as
  UI controls."
- **For us:** this conflicts with the current deliberate choice of the
  system font (`tailwind.config.js`: "reads as native"). I side with
  changing it, for identity: the system font is the main reason screenshots
  are indistinguishable from GitHub. "Pick an extreme" is tempered by the
  audience (approvers, finance), so the extreme we commit to is
  *documentary precision*, not visual spectacle.

### Claude Help Center: CLAUDE.md and better prompts
- https://support.claude.com/en/articles/14553240-give-claude-context-claude-md-and-better-prompts
- **Observed:** keep CLAUDE.md under ~200 lines, include "conventions and
  hard constraints", leave out "aspirational rules the team does not
  actually follow", and define "done" with acceptance criteria. The page
  does **not** cover UI work or screenshots specifically.
- **For us:** once the design spec is built, add 5–8 lines to CLAUDE.md's
  *Frontend conventions*: use tokens, not palette classes; no uppercase
  labels; no `→` in button text; serif only for document titles. Rules
  like these stop future agent edits from drifting back.

### Local skills available in this environment
`frontend-design`, `avoid-ai-design` (has a zero-dependency scanner,
`scripts/detect.mjs`), `impeccable` (critique/polish/audit modes), and
`webapp-testing` (Playwright). **Recommended workflow per screen:**
screenshot (Playwright) → change tokens/components → re-screenshot at
1440 px and 390 px → run axe → run `avoid-ai-design` in detection mode →
retake `tests/e2e/showcase_screens.py`.

---

## 7. Accessibility, responsiveness, performance

### WCAG 2.2 SC 2.5.8 Target Size (Minimum)
- https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html
- **Observed:** pointer targets of at least **24 × 24 CSS px**, or spaced so
  24 px circles don't overlap. Links inside sentences are exempt.
- **For us:** `Button size="sm"` is 28 px tall (passes). The topbar icon
  buttons are about 30 px (pass). Inline table action links like "Document /
  Request / Contract" in the control panel rely on the spacing exception.
  Keep at least 8 px gaps there.

### WCAG 2 contrast (and APCA)
- Vercel's guidelines prefer APCA, and Radix publishes APCA guarantees. WCAG
  2.x AA (4.5:1 text, 3:1 UI boundaries) is still the testable standard, so
  every pair in design-direction.md is checked against WCAG 2.
- **Measured on our app:** 107 failing elements on 23 of 24 pages, mostly
  `text-slate-400` on white (**2.56:1**) and `text-slate-500` on
  `surface-subtle` (**4.47:1**). Details in [ui-audit.md](ui-audit.md#h1).

---

## Summary: what to carry into the design

1. **Identity comes from the domain:** the paper trail, ledger rules,
   reference numbers, signatures, and stamps. Not from gradients, glass, or
   "AI" colour.
2. **Fewer boxes:** cards only where they contain an interaction (OpenAI);
   ruled sections and hairlines elsewhere (ledger vernacular).
3. **Semantic tokens via CSS variables**, keeping the existing Tailwind class
   names, so the restyle is mostly config, not 50 page edits (Tailwind,
   Primer, Linear).
4. **Contrast by construction** (Stripe, Radix), measured, not assumed.
5. **One motion moment with a purpose** (View Transitions on list → detail),
   with everything else instant, and reduced motion honoured.
6. **Bundled fonts** because of our CSP, with the `latin-ext` subset because
   of ₹.
