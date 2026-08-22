# Claude → Hugging Face handoff (current round only)

Same structure/purpose as `CLAUDE_HANDOFF_TO_CODEX.md`: a current-scope
summary so HG can review without re-reading all of `REVIEW_LOG.md`. Refreshed
after each Claude implementation round - not a replacement for the permanent
log (`REVIEW_LOG.md`) or the backlog (`FIXLIST.md`).

**HEAD**: `5d97ca9` (REVIEW_LOG Entry 20) plus the coordination-file reorg
this handoff itself is part of (not yet committed as of this writing - see
below).

## Summary

Two things happened since HG's last recorded context (Round 9,
`REVIEWER_FEEDBACK.md`, HEAD `80e3124`):

1. **Item 4 of the design-review plan** (the last item, closing that plan
   out): renamed "Run Property Scans" → "Find Properties" and added an icon
   to every top-nav item across both Property and Cars categories. Caught
   and fixed a real overflow regression before calling it done (see below).
2. **Coordination-file reorg** (this round, per Codex's proposal that HG
   independently reviewed and the owner asked Claude to execute): moved the
   four process/handoff docs into `docs/project/`, added this file, and
   updated `CLAUDE_DESIGN_HANDOFF.md`'s own protocol sections to reference
   the new paths.

## Every file changed

**Item 4** (commit `b075913`): `topbar.py`, `topbar_styles.py`, `main.py`,
`components/admin_controls.py`, `components/analytics.py`,
`components/analytics_dashboard.py`, `components/analytics_saved.py`,
`components/auth_portal.py`, `components/settings.py`.

**Codex's FIXLIST.md Section 9 addition** (commit `8945834`): `FIXLIST.md`
only - 3 UX findings logged as backlog (map scroll-capture, card focus-target
sizing, mini-results chip redesign), not yet implemented.

**REVIEW_LOG Entry 20** (commit `5d97ca9`): `REVIEW_LOG.md` (pre-move path).

**This reorg** (not yet committed): `docs/project/REVIEW_LOG.md` (moved from
root), `docs/project/CLAUDE_HANDOFF_TO_CODEX.md` (moved from root),
`docs/project/CLAUDE_DESIGN_HANDOFF.md` (moved from root, untracked, protocol
sections updated), `docs/project/REVIEWER_FEEDBACK.md` (moved from root,
untracked), `docs/project/CLAUDE_HANDOFF_TO_HUGGING_FACE.md` (this file,
new). `FIXLIST.md`/`DESIGN_STANDARDS.md` stay at repo root (dev-facing).

## Design decisions / tradeoffs

- **Item 4**: audited every button label in the app via script before
  assuming a "long story buttons" problem existed anywhere beyond the nav -
  found the app already follows icon+1-2-words nearly everywhere. The nav
  links (plain text, no icons) were the one real exception. Icons were
  reused from existing precedent where one existed (star = saved, matching
  Saved Properties' own hero icon; directions_car matches the category
  switcher's own Cars icon) rather than invented ad hoc.
- **Item 4 regression, caught before considering it done**: adding icons to
  all 4 real-estate nav items widened the row past the nav column's old
  365px min-width floor (sized for 3 plain-text items). Confirmed via
  `getBoundingClientRect` at 1169px width that "My Portfolio" was genuinely
  clipped, not just visually tight - a screenshot glance at 1440px alone
  would have missed this, since it only broke at the narrower width. Fixed
  by tightening nav button padding and bumping the floor to 580px (measured
  real content need, not guessed), then reverified at both widths via live
  DOM measurement.
- **On button color** (owner asked, not part of the original design-review
  plan): recommended against adding new button colors. The existing
  primary/secondary signal (blue = main action, neutral = everything else)
  already does real work; more colors risk diluting that and cluttering the
  restrained visual language both Codex's review and DESIGN_STANDARDS.md
  call out as worth preserving. Icons (already the established
  differentiator) carry the "recognize function at a glance" job instead.
- **Reorg**: `REVIEWER_FEEDBACK.md`/`CLAUDE_DESIGN_HANDOFF.md` were moved on
  the filesystem (not `git mv`, since they were never git-tracked - they're
  HG's/Codex's own living scratch files, fully overwritten each round, not a
  permanent record); `REVIEW_LOG.md`/`CLAUDE_HANDOFF_TO_CODEX.md` were
  proper `git mv` renames since those are Claude's own tracked output.
  **Action needed on your end**: write your next round's findings to
  `docs/project/REVIEWER_FEEDBACK.md`, not the old root-level path - the
  root-level file no longer exists after this commit lands.

## Testing performed

- Item 4: `py_compile` clean, full `pytest` suite (59 tests) green, live
  verification at both 1169px and 1440px viewport widths (not just one),
  confirmed via `getBoundingClientRect` measurements rather than screenshot
  impressions alone. Cars' own nav (Find a Car/Saved Searches, also newly
  iconed) checked and unaffected.
- Codex's FIXLIST.md findings: spot-verified `scrollZoom:True`'s presence at
  the 3 named call sites, and confirmed the 4th file
  (`location_picker.py`) has no `config=` at all - meaning it's correctly in
  scope for achieving consistent behavior even without an existing `True` to
  flip. Not implemented, so no functional testing needed yet.
- Reorg: docs-only, no Python touched, no test suite impact expected -
  `pytest` re-run after the move regardless, still 59 passed.

## Remaining concerns / questions

1. Item 4's icon choices (`search` for Find Properties, `account_balance`
   for My Portfolio) are a judgment call, not pulled from existing
   precedent the way `star`/`directions_car` were - worth a second opinion.
2. The 580px nav-column min-width floor is calibrated for real-estate's
   specific 4-item set. If a nav label or icon set changes again, this needs
   re-measuring, not just eyeballing.
3. Codex's 3 FIXLIST.md UX findings (scroll-capture, card focus targets,
   mini-results chips) are logged but not implemented - not yet requested by
   the owner, flagging so HG's own review doesn't assume they're done.
4. This is the first round using the new coordination-file layout - if
   anything about the new paths trips up your own tooling/workflow, say so
   now so it can be adjusted before it becomes a recurring friction point.
