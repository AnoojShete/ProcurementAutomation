# Prompt: implement the Fractal roadmap

Paste everything below the line into Claude Code, opened in
`ProcurementAutomation/`. To work on a subset, change the scope line, for
example "Scope: FR-01 to FR-03 only".

---

Implement the **"Fractal roadmap — Oct 15, 2026"** section of `TODO.md`
(items FR-01 to FR-28) in this repo. Scope: R0, then R1. Do R2 only if I
say so. R3 runs in November.

**Before starting**
1. Read `CLAUDE.md`, the roadmap section of `TODO.md`, and the git log
   entries since Oct 15. Run `git status` and `git log` and list anything
   that changed since the roadmap was written. Don't overwrite other
   people's uncommitted or recent work. If something already covers an
   item, re-verify it rather than rebuilding it.
2. Show me a checklist of the R0 items: dependencies, and whether
   each is blocked. An item is blocked if it needs a decision from me
   (anything that says "ask before"), real credentials, or Anooj's area
   (email automation, the chatbot), which we don't build.
3. Start with the highest unblocked R0 item. FR-01, FR-02 and FR-04 come
   first because they are Team A's own action items.

**For each item, one at a time**
1. Before editing, tell me in a few lines: the problem as it is in the
   code now (with file:line), the change, the files and services
   touched, and the tests that will prove it.
2. Implement it the way the repo does things: migrations in the owning
   service, new topics in `kafka-topics.yaml`, `acls.conf` and
   `events.md`, publish through the outbox, identity from the JWT, rules
   in the rules engine, one action component per agent in the frontend.
3. Verify it:
   - Run the service's suite (`./scripts/test-service.sh <svc>`), the
     root tests, and `npm run typecheck` if the frontend changed.
   - Run the relevant e2e script against the running stack.
   - Revert the fix once and show that the new test fails without it.
4. Check `git diff` for unrelated changes and remove them.
5. Check the item's "Done when" line point by point. If a point isn't
   met, the item isn't done.
6. Update `TODO.md`: tick the box only when every "Done when" point is
   met, and add one line of evidence (test names and pass counts, or the
   file in `docs/results/`). Update `docs/project-flow.html` (status
   colours), `README.md` (public overview) and `readmeforme.md` (technical
   reference) when the item changes what they say. There is no
   CHANGELOG — `git log` and the TODO evidence lines are the history.
7. Report: what changed, what you ran and the actual output (passed and
   failed), and what's left open. Then go on to the next item.

**Rules**
- Never say a test passed unless you ran it, and quote failures as they
  are. Never weaken a check to make it pass, and never tick a box for
  partial work. Write "partial" and say what's missing.
- Stop and ask on architecture choices (FR-13 Legal-BERT vs fixing the
  docs, FR-15 the PySpark service, FR-16 Helm, FR-24 MCP), destructive
  migrations, new external services or credentials. Don't deploy
  anywhere and don't rotate keys.
- For Anooj's areas, stop at publishing the event or writing the spec,
  and list what he needs to do.
- Don't start R1 while an unblocked R0 item is still open, or R2 while
  an unblocked R1 item is.

**At the end**
Audit the whole thing again, end to end, against the roadmap, the 29 Aug
mentor feedback (the 11 overall items plus Team A's four), and the
26 Sep minutes. For each one, say done, partial (what's missing) or not
started, with evidence. Then list honestly what's still open and who
owns it.
