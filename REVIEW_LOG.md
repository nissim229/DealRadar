# DealRadar — Review Log

Running log of completed work, for the external reviewing assistant to
check against the actual repo (github.com/nissim229/DealRadar) and the
local working tree.

**Convention**: each round of fixes gets appended below as a new numbered
entry (newest at the bottom). Nothing gets edited or removed once an entry
is written — if a reviewed item needs a follow-up fix, that follow-up gets
its own new entry, same as the bcrypt migration's three rounds in this
project's git history. Always ask the reviewer to check this same file;
tell it which entry (or "the latest entry") is ready.

Each entry lists what changed, the commit hash(es) it can check the real
diff against, how it was verified before being marked done, and a "What to
check" list of specific questions for the reviewer.

**Reviewer's feedback goes in its own file, `REVIEWER_FEEDBACK.md`** (same
project root), not directly into this one. The reviewer has write access
scoped to this project folder, so it can create/overwrite that file itself
each round rather than the owner having to paste its response into chat -
but this file (`REVIEW_LOG.md`) is only ever written by the assistant
doing the fixes, so its own history can't be altered by anything else that
touches this folder. `REVIEWER_FEEDBACK.md` gets fully overwritten each
round (always "latest feedback", no need to hunt through old ones); once
its claims are independently checked, anything that holds up gets folded
into the matching entry here as a "Reviewer Feedback" subsection.

---

## Entry 1 — FIXLIST.md Sections 1–2 (2026-08-21)

**Status**: Pending review

Commits (both pushed to `master`):
- `125bb74679440864b4fcdaefe1c1ca38758ea580` — Section 1 (quick wins)
- `fc9a2f62c7d16a00384f10cf1dabca1061d78d95` — Section 2 (pytest suite)

### Section 1: Quick wins (commit `125bb74`)

1. **Deleted dead database files**: `app_data.db`, `dealradar.db`,
   `scoutai.db` (all confirmed 0 bytes before deletion). These were already
   gitignored (`*.db` in `.gitignore`), so this is a local-disk cleanup only
   — the commit itself doesn't show a tracked deletion for these files, only
   the other changes below. Only `agent_config.db` (`database.py`'s
   `DB_NAME`) is real.

2. **Fixed bare `except:` clauses** in `agent_engine.py` (originally lines
   357 and 362, wrapping `int()` conversions for `max_price`/`min_beds`).
   Changed to `except (TypeError, ValueError):`. Verified after the change
   that non-numeric input (`'not-a-number'`, `'also-not-a-number'`) still
   falls back to the defaults (750000 / 3) without crashing, via a direct
   call to `fetch_live_listings(..., allow_live=False)`.

3. **Rewrote `SETUP.md`**:
   - Title changed from "ScoutAI Enterprise" to "DealRadar".
   - Folder structure section updated to reflect the actual current file
     tree (was still showing the old 5-file skeleton).
   - Added a note about `requirements-lock.txt` (full pinned freeze) as an
     alternative install path to `requirements.txt`.
   - Added a note that `PASSWORD_PEPPER` self-provisions into `.env`
     automatically on first run and should be backed up once real
     passwords exist.
   - Replaced the bare `admin@scoutai.com` / `admin123` credential mention
     with a "⚠️ BEFORE GOING LIVE: rotate the seeded admin password" warning.
     **This was confirmed with the project owner directly before writing**
     — they confirmed keeping `admin123` during development (pre-launch) is
     intentional, so the fix documents the risk rather than forcing a
     rotation now.

### Section 2: Real pytest suite (commit `fc9a2f6`)

New files:
- `requirements-dev.txt` — `pytest==9.1.1` only, kept separate from the
  runtime `requirements.txt` / `requirements-lock.txt`.
- `pytest.ini` — `pythonpath = .` (so `tests/` can `import database`
  without installing the project as a package), `testpaths = tests`.
- `tests/test_auth.py` — 12 tests, all currently passing:
  1. `test_wrong_password_rejected_on_bcrypt_account`
  2. `test_correct_password_on_bcrypt_account_succeeds`
  3. `test_legacy_sha256_hash_migrates_on_login` (also checks a second
     login does NOT rewrite the hash again)
  4. `test_transitional_unkeyed_bcrypt_hash_recognized_and_upgraded` — the
     brief bcrypt-over-bare-SHA256 scheme this app used before
     `PASSWORD_PEPPER` existed; this is the exact format a real account
     (`testclient@dealradar.local`) was migrated to live earlier this
     session, before the pepper was introduced
  5. `test_low_cost_bcrypt_hash_upgraded_to_target_cost` (rounds=4 → 12)
  6. `test_long_passphrase_roundtrips` (200+ char password)
  7. `test_nonexistent_email_returns_none`
  8. `test_empty_stored_hash_rejected`
  9. `test_pepper_is_load_bearing` — a hash made under pepper A must fail
     verification under pepper B
  10. `test_suspended_account_still_returns_suspended_marker`
  11. `test_timing_rough_parity_missing_account_vs_wrong_password`
  12. `test_pepper_regression_cwd_independent` — imports `database.py` in a
      **real subprocess**, CWD set to an unrelated temp directory, with
      `PASSWORD_PEPPER` explicitly stripped from the inherited environment
      (so env-var inheritance can't mask a regression). Confirms the
      resolved pepper's SHA-256 fingerprint matches the real `.env` value,
      and that `.env` is byte-for-byte unchanged afterward.

Hard rules followed (per FIXLIST.md's own ground rules):
- No test ever opens the real `agent_config.db` — every DB-touching test
  gets a fresh temp file via a fixture (`init_db()` on a monkeypatched
  `database.DB_NAME`).
- No test regenerates or overwrites the real `PASSWORD_PEPPER` — the
  pepper-isolation test (`test_pepper_is_load_bearing`) monkeypatches
  `database.PASSWORD_PEPPER` in memory only, never touches `.env`.

**Self-check performed before trusting the suite**: temporarily deleted the
transitional-scheme fallback branch from `database._check_password()`,
reran the suite — `test_transitional_unkeyed_bcrypt_hash_recognized_and_upgraded`
failed exactly as expected, the other 11 stayed green — then restored the
real code and reran, confirming all 12 pass again (`git diff database.py`
showed zero diff afterward, confirming a clean restore).

### What to check (Entry 1)

- Does the bare-`except:` fix in `agent_engine.py` look correct and
  complete (right exception types, no other bare excepts nearby that
  should've been caught in the same pass)?
- Is the `SETUP.md` rewrite accurate against the actual current repo
  structure?
- Is 12 tests reasonable coverage for `authenticate_user()`/
  `verify_password()`/`_check_password()`, or is something load-bearing
  still untested?
- Does the CWD regression test's subprocess-based approach actually prove
  what it claims, or is there a gap (e.g. environment variables other than
  `PASSWORD_PEPPER` that could leak through and mask a regression)?
- Anything in the "already completed" scope that looks incomplete or
  wrong when checked against the real files at those two commit hashes?

### Reviewer Feedback (Entry 1)

**Verdict: approved**, all 5 "what to check" items confirmed, with 3 new
findings. Every claim below was independently re-verified against the real
repo before being recorded here (grep for bare `except:`, the stale
`strategy_config.py` references, `except Exception:` line numbers,
`FIXLIST.md` checkbox counts, `git status`/`git diff` state, and a
`pytest` rerun) — nothing here is taken on the reviewer's word alone.

- Bare-except fix: confirmed, zero bare `except:` remain repo-wide.
- SETUP.md: confirmed accurate, **except** one stale leftover - its "Bugs
  fixed in this version" section still cites `strategy_config.py`, which
  no longer exists as source (only an orphaned `.pyc` remains in
  `components/__pycache__/`). `main.py`'s router comment (line 46) also
  still references it.
- 12-test coverage: confirmed as a sound core. Named gaps, none blocking:
  `change_own_password()`/`update_own_profile()`'s current-password checks,
  the password-reset flows, `register_user()` end-to-end, and - flagged as
  highest-value - **the opportunistic-hash-upgrade write-failure path**
  (the `except sqlite3.Error: pass` in `authenticate_user()` from commit
  82828c2) has zero test coverage despite being load-bearing: a regression
  there could silently lock out valid logins.
- CWD regression test: confirmed sound, no material gap. Noted it assumes
  an already-initialized project (real `.env` present) - would fail loudly
  on a pristine from-scratch clone rather than pass vacuously, which is
  the correct failure mode, just worth knowing for a future CI setup.
- Completeness: confirmed. Working tree, checkbox counts, and the
  database.py clean-restore claim all check out exactly as stated.

**New issues found** (not yet acted on - candidates for a follow-up entry):
1. Stale `strategy_config.py` references (SETUP.md + main.py comment) and
   an orphaned `.pyc` to delete.
2. Missing test for the failed-upgrade-write resilience path (suggested
   approach: monkeypatch the cursor/connection to raise `sqlite3.Error`
   during the UPDATE, assert `authenticate_user()` still returns the user
   dict).
3. Minor/cosmetic: `tests/test_auth.py`'s `temp_db` fixture uses the
   deprecated, race-prone `tempfile.mktemp()`; pytest's built-in
   `tmp_path` fixture does the same job idiomatically.

---

## Entry 2 — Follow-up on Entry 1's 3 new findings (2026-08-21)

**Status**: Pending review

Commit: `7ded9c7` (pushed to `master`).

Addresses all 3 items from Entry 1's "New issues found":

1. **Stale `strategy_config.py` references fixed.** `main.py`'s
   `active_category` comment and `SETUP.md`'s "Bugs fixed" section both
   described a module that no longer exists as source (real-estate search
   is ad-hoc now, mirroring cars - see `components/analytics.py`).
   Updated both; `SETUP.md`'s entry is historical so it was annotated
   rather than deleted. Also deleted the orphaned
   `components/__pycache__/strategy_config.cpython-313.pyc`.
   (Note: several *other* files - `components/car_search.py`,
   `components/pricing.py`, `components/analytics.py`,
   `DESIGN_STANDARDS.md`, `location_data.py` - also reference
   `strategy_config.py` in docstrings/comments, mostly as "same pattern
   as X" comparisons. These were out of the scope the reviewer actually
   flagged - only `SETUP.md` and `main.py`'s comment were named - so left
   untouched here rather than expanding scope unprompted.)

2. **Added `test_login_succeeds_even_if_hash_upgrade_write_fails`** to
   `tests/test_auth.py`, covering the previously-untested load-bearing
   path: `authenticate_user()`'s opportunistic hash-upgrade write is
   wrapped in `try/except sqlite3.Error` so a failed write can never turn
   a correct login into a failure (commit 82828c2). Since
   `sqlite3.Cursor`/`Connection` are immutable C types that block
   `monkeypatch.setattr()` on their methods directly, the failure is
   forced via a thin proxy wrapping `sqlite3.connect()` that intercepts
   only the one `UPDATE users SET password_hash` statement. **Sanity-
   checked**: temporarily removed the `try/except`, confirmed this exact
   new test fails (the simulated `OperationalError` propagates uncaught),
   then restored and confirmed all 13 tests pass (`git diff` on
   `database.py` empty afterward).

3. **Swapped `tempfile.mktemp()` for pytest's `tmp_path` fixture** in the
   `temp_db` fixture - same behavior, no longer using a documented-
   deprecated, race-prone API.

Full suite: **13 passed** (was 12; +1 from item 2 above).

### What to check (Entry 2)

- Are the `SETUP.md`/`main.py` reference fixes accurate against the
  current codebase?
- Is the proxy-based approach for forcing the sqlite3 write failure sound,
  or is there a cleaner/more standard way to do this in pytest that was
  missed?
- Was leaving the other `strategy_config.py` references (outside what was
  explicitly flagged) alone the right call, or should those be swept up
  too in a future entry?

---

## Entry 3 — strategy_config sweep, FIXLIST Sections 3–4, register_user test (2026-08-21)

**Status**: Pending review

Commits (all pushed to `master`):
- `ed015be` — full 8-site strategy_config.py comment sweep
- `9d493b9` — Section 3 (silent exception audit)
- `6d72d14` — register_user() end-to-end test

### strategy_config.py sweep (commit `ed015be`)

Used `REVIEWER_FEEDBACK.md`'s complete 8-site inventory
(`location_data.py:4`, `location_picker.py:5`, `analytics.py:1448`,
`car_search.py:6`, `car_search.py:787`, `pricing.py:5`,
`DESIGN_STANDARDS.md:73`, `DESIGN_STANDARDS.md:143`). 7 fixed (repointed at
the real current file/pattern, verified each new reference via grep - e.g.
`pricing.py`'s "used from three places" list was checked against actual
current importers, not just had the dead name swapped out); 1
(`location_picker.py:5`) needed no change, already correctly described the
module as removed.

### Section 3: silent exception audit (commit `9d493b9`)

FIXLIST.md named ~15 approximate sites (title claimed 17) across 3 files
and said its line numbers predate recent commits. A full repo-wide grep
found the real current total: **24** `except Exception:` sites across 6
files - including 4 in `agent_engine.py` beyond the 2 named, and
`google_oauth.py`/`email_utils.py`/`car_engine.py` not mentioned at all.
Audited the complete current set, not just the stale named subset.

17 of 24 were already fine on inspection (already print a diagnostic or
have deliberate error-type-branching logic) - left untouched. Fixed the 7
genuinely silent ones: 5 in `analytics.py` got a `print(f"[Analytics] ...: {e}")`
diagnostic (mini results strip parse, live-scan execution failure,
split-view map, results header count, best-deal computation, quick-filter
toolbar, properties-only grid, map-only view, table view, history-row
summary, hero stat cards - one print per distinct failure site, named
individually); 1 in `agent_engine.py` (Street View metadata check) got a
log; 2 (`agent_engine.py`'s geodesic distance calc, `settings.py`'s
timezone fallback) got comment-only justification instead of logging,
since both are high-frequency/expected-fallback paths where a print would
be noise, not signal. All prints follow the codebase's existing
`print(f"[Tag] message")` convention rather than introducing the stdlib
`logging` module fresh.

### Section 4: sqlite connection hygiene — **no code change made**

Verified precisely before acting: **all 109 of 109** `sqlite3.connect()`
call sites in `database.py` already have a matching `try:`/`finally:
conn.close()` pair (checked programmatically, not just a count match -
confirmed the `finally:` actually appears within each function, not
coincidentally elsewhere in the file). This means the specific risk
FIXLIST describes - a connection leaking because an exception path skips
the close - **does not currently exist anywhere in this codebase**;
`finally:` already guarantees the close exactly as `contextlib.closing()`
would. A 109-site mechanical refactor to `closing()` would be purely
cosmetic with zero reliability benefit, and touching that many call sites
for no functional gain carries real risk of introducing an actual mistake
in the process - so it was deliberately not done. Flagging this explicitly
rather than silently skipping the section.

### Extra: register_user() end-to-end test (commit `6d72d14`)

Requested alongside Sections 3-4. Every prior auth test called
`hash_password()` directly; this one goes through the real account-
creation entry point, confirming it produces a bcrypt hash, the account
can log in, wrong password is rejected, and a duplicate email returns
`None` (not a crash). **Sanity-checked**: temporarily made
`register_user()` call `_hash_password_legacy()` instead, confirmed this
exact test fails, restored, confirmed all 14 tests pass (`git diff` on
`database.py` empty afterward).

Full suite: **14 passed** (was 13; +1 from the register_user test).

### What to check (Entry 3)

- Are the 7 strategy_config.py reference fixes accurate against the
  current codebase (correct new file/function pointed at in each case)?
- Is the 24-site (vs. FIXLIST's named ~15) exception audit scope
  appropriate, or should the 17 already-compliant sites have gotten a
  second look too?
- Are the print-vs-comment-only judgment calls reasonable, especially the
  2 comment-only ones (geodesic distance, timezone fallback) - any of
  these actually warrant logging after all?
- **Most important**: is the Section 4 "no code change - already safe"
  conclusion correct? Please independently verify the 109/109 try/finally
  claim rather than taking it at face value, since this is the one item
  in this entry where doing nothing was the deliberate choice.
- Is the register_user() test's coverage sufficient, or is there a gap in
  how it exercises the real entry point?

### Reviewer Feedback (Entry 3)

**Verdict: approved**, all 5 items confirmed. Every claim independently
re-verified before recording here (handler counts by file, remaining
strategy_config references, register_user's IntegrityError path, a full
pytest rerun) - all held up exactly as stated.

- strategy_config sweep: confirmed, zero remaining source references
  outside the one intentionally-left site.
- 24-site audit scope: confirmed correct via the reviewer's own
  independent recount (exact per-file breakdown matched).
- Print-vs-comment judgment calls: confirmed reasonable, no site flagged
  for re-litigation.
- **Section 4: confirmed via independent AST analysis** (not just string/
  count matching) - parsed `database.py` directly, confirmed all 109
  `sqlite3.connect()` sites are direct assignments each paired with a
  `try:/finally:` that closes that exact variable, zero exceptions. The
  "no code change needed" conclusion holds.
- register_user test: confirmed sufficient for its stated scope.

**Two optional hardening notes, both taken** (commit `ff13d2e`):
1. **`conn.row_factory` micro-caveat** (informational, not a defect): 3
   functions (`get_portfolio_properties`, `get_tenants`, `get_documents`)
   placed that one assignment between `connect()` and `try:` - couldn't
   practically fail today, but a future edit inserting something fallible
   there would escape the `finally`. Moved inside `try:` in all three;
   smoke-tested against a temp DB afterward (no exceptions, correct
   empty-list results).
2. **register_user test additions**: now also asserts the legacy `name`
   column stays correctly in sync via `_combine_name()` (no stray double
   space with an empty middle name) and that every new signup seeds
   exactly 3 free credits.

Full suite after both: **14 passed** (test count unchanged - these were
additional assertions in the existing test, not new tests).

---

## Entry 4 — FIXLIST.md Section 5, pre-split cleanup (2026-08-21)

**Status**: Reviewer feedback folded in below - approved.

Commits:
- `6ca678d` - resolve the untracked `.agents/`/`.claude/skills/`/
  `.claude/settings.local.json` decision
- `272205d` - widen mock street-name variety to every city
- `8031062` - make Auto.dev's monthly limit admin-editable

### `6ca678d`: untracked-file decision

`.agents/` and `.claude/skills/` turned out to be real Windows symlinks
into `venv/site-packages/streamlit/...` (confirmed via `Get-Item` before
acting) - committing a symlink on Windows is fragile and goes dangling on
a fresh clone, so both got added to `.gitignore` instead of tracked.
`.claude/settings.local.json` is a real file (just the `Bash(git push:*)`
permission rule, no secrets) - committed normally.

### `272205d`: mock street-name generalization

`agent_engine.py`'s mock-data generator had per-city hardcoded street
lists for exactly the 4 cities in `GUEST_QUICK_SEARCH_CITIES` (Denver,
Austin, Miami, Boulder - the guest first-scan fast path), falling back to
a generic 5-name list everywhere else. Merged into one 24-name
`MOCK_STREET_NAMES` pool assigned unconditionally before the city-match
branch, so no code path can still reach the old generic list. Deliberately
did **not** touch the 4-city coordinate cache itself (removing it would
put a live Nominatim geocoding call on an anonymous visitor's very first
scan) - scope was "generalize the variety, keep the reliability
optimization."

### `8031062`: Auto.dev admin-editable limit

Auto.dev's monthly call cap was a flat `1000` constant in `car_engine.py`,
inconsistent with RentCast/Places/OpenAI's already-admin-editable configs.
Added `get_autodev_config()`/`update_autodev_config()` to `database.py`
(same `app_settings`-backed upsert-and-finally shape as the other three
setters, default `1000` matching the old constant), updated both gate
sites in `car_engine.py` to read the config at call time, and wired the
value into `topbar.py`'s usage badge/tooltip and `admin_controls.py`'s
usage card + a new Pricing tab config form. Verified live: set the limit
to 1500 in Admin Controls, confirmed the topbar badge and gate both
picked it up without a restart, reset to 1000.

### Reviewer Feedback (Entry 4)

**Verdict: approved**, all three commits confirmed. Spot-verified two of
the reviewer's central claims myself before folding this in (per this
log's practice of not trusting external-reviewer claims blindly): the
`.gitignore` really does list `.agents/` and `.claude/skills/` and
`git check-ignore` confirms both paths resolve as ignored; and
`GUEST_QUICK_SEARCH_CITIES` (now living in
`components/analytics_scan_form.py` after Entry 5's split) is still
exactly Denver/Austin/Miami/Boulder, matching the reviewer's cross-check.

- `6ca678d`: confirmed correct - symlink claim verified on disk, permission
  file confirmed secret-free.
- `272205d`: confirmed, and the reviewer noted the scope judgment (widen
  variety, keep the coordinate-cache optimization) was better than
  FIXLIST's literal wording.
- `8031062`: confirmed complete and pattern-consistent with the other
  three provider configs across all four touched files; no DB-layer
  validation on the new setter was flagged as consistent with the
  existing three setters, not a gap.
- Two informational-only observations, neither requiring action:
  `MOCK_STREET_NAMES` is rebuilt per call (negligible cost, pure style);
  the live threshold-toggle verification can't be re-run from the diff
  alone but the end state (default resolves to 1000) is consistent.
- Also reviewed in passing: `cdb5e39` (Entry 3 bookkeeping) and `ff13d2e`
  (Entry 3's two optional hardening notes) - both confirmed as intended.

### What to check (Entry 5, since this entry is already closed out)

Nothing further here - see Entry 5 below for the follow-on monolith-split
work this entry's own "Remaining Section 5 work" note flagged.

---

## Entry 5 — FIXLIST.md Section 5, monolith split (2026-08-21)

**Status**: Reviewer feedback folded in below - approved.

The three files FIXLIST.md Section 5 flagged as "fine to defer, cosmetic"
- `topbar.py` (785 lines), `database.py` (2780 lines, 127 functions), and
`components/analytics.py` (2194 lines, 29 functions) - all split into a
thin **facade** (the original file, kept at its exact path so every
existing `import database as db`/`from components.analytics import
X`/`from topbar import render_main_topbar` call site needed zero changes)
plus flat sibling modules holding the real code. 28 commits, one per
extraction step, each independently verified (`py_compile`, the full
`pytest` suite, a functional/import check, and - for every step - a live
browser check of the specific feature just moved) before being committed.
Full commit range: `38c560f`..`b201b4c`.

### `topbar.py` (785 -> 306 lines)

- `38c560f` - the ~481-line static `TOPBAR_CSS` block extracted verbatim
  into `topbar_styles.py`; `topbar.py` imports the constant and calls
  `st.markdown()` at the exact same call site relative to `main.py`'s
  theme-injection calls (CSS-specificity ordering untouched). Deliberately
  **not** further decomposed - `render_main_topbar`'s dynamic popover
  `key=` f-strings (built from live `session_state` so popovers auto-close
  on navigation) and its 7 paired `st.rerun()` calls are fragile-but-
  load-bearing patterns not worth the risk for a readability-only gain.

### `database.py` (2780 -> 223 lines), 13 domain modules + schema split

Sequenced lowest-risk-first: `database_crypto.py` + `database_shared.py`
first (the only group `tests/test_auth.py` exercises directly - validates
the whole facade pattern before anything else depends on it), then
`database_settings.py` -> `database_dashboard.py` -> `database_oauth.py`
-> `database_profile.py` -> `database_reports.py` + `database_geocache.py`
-> `database_history.py` -> `database_saved_properties.py` ->
`database_portfolio.py` -> `database_billing.py` -> `database_admin.py` ->
`database_auth.py`, finally `database_schema.py` (`init_db()` decomposed
into 22 ordered helper functions, done last once every domain boundary was
settled).

Two load-bearing constraints verified before starting, both held for
every step:
- **Flat siblings, never a package** - `DB_NAME`/`_ENV_PATH`/
  `PORTFOLIO_UPLOADS_DIR` are all `__file__`-relative; a `database/`
  package would resolve these one directory too deep.
- **Cross-module calls go through `database.func()`**, never a bare name
  or a direct import of the concrete module - new sibling modules do
  `import database` and read `database.DB_NAME`/`database.hash_password()`
  etc. at call time, preserving `tests/test_auth.py`'s
  `monkeypatch.setattr(db, "DB_NAME", ...)` pattern and working regardless
  of extraction order (verified directly: `database_oauth.py` calls
  `database.get_user_by_email()` before that function had even been
  extracted yet, and it still resolved correctly).

Highest-risk single step, `4071301` (`init_db()` -> `database_schema.py`):
verified with a dedicated diff script confirming **0 mismatches across
387 statement lines** between the original function body and the 22 new
helpers, plus an idempotency check (`init_db()` called twice against a
temp DB, no duplicate master-admin or credit packages) and a fresh-install
smoke test (21 tables + `sqlite_sequence` created correctly). `6089faa`
(`database_billing.py`) specifically re-verified `plan_limits.py`'s
pre-existing lazy `import database as db` circular-import workaround
still resolves `get_credit_packages()`/`update_credit_package()` correctly
through the facade.

### `components/analytics.py` (2194 -> 16 lines), 9 sibling modules

`11cc6dd` atoms -> `7f0ad5b` dialogs -> `e37d1e0` map -> `603c567` scan
form -> `9633e03` scan engine, then the plan's explicitly-flagged riskiest
unit in the whole scope - `_render_scan_results` (588 lines, zero test
coverage) - split as its own multi-step sequence: `ab7fb19` extracted the
quick-filter toolbar first as pure extract-method (verified and committed
alone before touching any view branch, per the plan's own instruction),
then each of the 4 view-mode branches one at a time (`1e8aac1` Properties
Only, `26ddea1` Properties + Map, `c6d876a` Map Only, `527910a` Table
View - the last of which carries `st.session_state.property_dialog_ctx`,
a real producer/consumer contract with `components/property_card.py`,
verified to keep its exact key name). `03576c3` then relocated the whole
toolbar+4-views+orchestrator group into `components/analytics_results.py`
in one file move. `0dadfc8` history -> `7edeeed` saved properties ->
`b201b4c` the top-level `render_analytics_dashboard` orchestrator (widest
fan-in of the whole split) into `components/analytics_dashboard.py`,
leaving `components/analytics.py` as a 16-line pure facade re-exporting
exactly the 5 names other files still import directly (`main.py`'s
`render_analytics_dashboard`/`render_history_page`,
`components/portfolio.py`'s `render_empty_state`/`render_stat_card`,
`components/car_search.py`'s `build_clustered_map_data`).

### Verification applied to every one of the 28 steps

`py_compile` on every touched file, the full `pytest` suite (all 14 tests
in `tests/test_auth.py` stayed green after every single step, not just
`database.py`'s own steps), `git diff --stat` confirming only the intended
file(s) changed, and a live browser check scoped to whatever moved that
step (a specific view mode, the History archived-scan viewer, the Saved
Properties card grid, etc.) - logged in each commit message. The final
step additionally re-ran a fuller smoke check across the whole app (guest
dashboard auto-scan, sign-in as a real test account, sign-in as
super-admin - Pro underwriter console, all 3 usage badges, Admin Controls
dashboard - and My Portfolio) since it was the widest-reaching change in
the whole plan.

### What to check

- Spot-check a handful of the 28 commits' diffs directly - are these pure
  moves (facade re-export + sibling file), or did any step's line-count
  change hide an actual logic edit?
- `database_schema.py`: is the 387-line diff-verification script's
  approach (excluding the dispatcher wholesale by slicing at
  `def init_db():` rather than filtering by string content) actually sound,
  or could it have a blind spot the same way the first version's `"try:"`
  string-filter did?
- Cross-module reference pattern: spot-check a few of the `database.func()`
  / `analytics_atoms.func()` calls in the new sibling files - correct
  target module in every case, no accidental bare-name reference that
  would only work by import-order luck?
- `_render_scan_results`'s 4-branch split: does `property_dialog_ctx`
  really carry an unchanged key/shape into `components/property_card.py`
  across all 4 view-mode functions, or did the explicit-parameter
  refactor subtly change what's in the dict for any one of them?
- Is the final `components/analytics.py` facade's 5-name re-export list
  actually complete - any other file in the repo importing a 6th name
  from `components.analytics` that got missed?

### Reviewer Feedback (Entry 5)

**Verdict: approved**, with one pre-existing bug surfaced (unrelated to
the split, not a regression). Every check was redone independently with
different methods than this log's own verification (AST parsing across
all 61 project `.py` files, live DB builds from git snapshots, byte-level
compares), rather than trusting the logged claims. Confirmed the one
concrete bug claim myself before recording it here (git blame on
`components/property_card.py:486`) rather than folding it in blindly.

- **Commit range**: exactly 28 commits, matching this entry's list
  one-for-one in sequence. `HEAD` = `9b9f845`, tree clean, synced with
  origin/master.
- **Facade completeness - exhaustive, not spot-checked**: every `db.X`/
  `database.X` reference, every `from database import ...`/`from
  components.analytics import ...`/`from topbar import ...`, and every
  direct sibling-module import across all 61 `.py` files resolves in its
  target namespace - zero unresolved references. Independently confirmed
  the analytics facade's 5-name re-export list is complete (answers this
  entry's last "what to check" item).
- **Pure-move confirmation**, sampled deep on `e838e61` (crypto+shared),
  `6089faa` (billing), and `b201b4c` (orchestrator): every removed
  monolith line reappears in its sibling module identically after
  normalizing whitespace and the `db.`->`database.` prefix rewrite - zero
  residual logic deltas. `38c560f`'s CSS block compared byte-for-byte
  against the pre-split inline literal: 28,668 of 28,672 characters
  identical, the sole difference one whitespace-only line.
- **`init_db()` decomposition, verified empirically rather than by
  auditing this log's own diff script**: built fresh DBs from both the
  pre-split monolith and the new `database_schema.py` path (checked out
  in an isolated sandbox) and diffed them directly - 22 tables, all
  column/index/trigger definitions, all 4 seed rows, and the seeded
  master-admin row identical; double-init produced no duplicate seeds.
  Answers this entry's diff-script-soundness question: moot, since the
  outcome was verified independently of the script's method.
- **`property_dialog_ctx` contract - fully preserved**: all 4 producers
  survive (the `_mini`-suffix producer had moved to
  `components/analytics_scan_form.py:241`, not lost - initially looked
  like 3). Every producer's key set matches the pre-split snapshot
  exactly, both `key_prefix` suffixes preserved verbatim, and the
  consumer in `components/property_card.py` reads the same 10 keys before
  and after.
- **Cross-module reference pattern**: confirmed via the same AST sweep -
  no bare-name call survives that depends on import-order luck. Full
  `pytest` rerun: 14 passed.
- **Sandbox discipline**: all verification ran in isolated temp dirs with
  temp `DB_NAME`s and a sandbox pepper; the project `.env` was checked
  afterward - exactly one `PASSWORD_PEPPER` line, unmodified, and
  production `agent_config.db` untouched.

**One finding, added to `FIXLIST.md`**: `components/property_card.py:486`
calls `_property_detail_dialog()`, which is defined nowhere in the repo -
the correct name is `render_property_detail_dialog()` (defined line 279,
correctly called at line 425, the table view's "eye" icon path). This is
the OTHER "View Full Details" path - the button on a property card in the
grid views (Properties Only / Properties + Map / Map Only). Clicking it
sets `property_dialog_ctx` then raises `NameError` on the very next line.
Confirmed via `git blame`: present since the initial commit (`82d0192`,
2026-08-17), untouched by every commit since including this entire
monolith split - not a regression, does not block this approval.

---

## Entry 6 — FIXLIST.md Section 6, property_card.py NameError fix (2026-08-21)

**Status**: Reviewer feedback folded in below - approved.

Commits:
- `fffee08` - the fix itself
- `dba4d17` - marks the FIXLIST.md Section 6 checkbox done

### The bug

`components/property_card.py:486` called `_property_detail_dialog()`,
which is defined nowhere in the repo - the real function is
`render_property_detail_dialog()` (defined line 279, correctly called
elsewhere at line 425 - the table view's "eye" icon path). This is the
*other* "View Full Details" path: the button on a property card in the
grid views (Properties Only / Properties + Map / Map Only). Clicking it
set `property_dialog_ctx` then raised `NameError` on the very next line.
Surfaced by the external reviewer during Entry 5's review (folded in
there), confirmed via `git blame` before fixing: present since the
initial commit (`82d0192`, 2026-08-17), untouched by every commit since -
not caused by the monolith split.

### The fix (`fffee08`)

One-line change: `_property_detail_dialog()` -> `render_property_detail_dialog()`
at line 486. Nothing else touched.

### Verification

`py_compile` clean, all 14 tests in `tests/test_auth.py` pass. Live
browser check: ran a scan, opened the dialog from a card's "View Full
Details" button in both Properties Only and Properties + Map view -
correct property data, grade, and underwriting breakdown render in the
modal, dialog closes cleanly. (The first attempt at this live check
misleadingly appeared to still fail - traced to a stale Python module
cache in the long-running dev server process, which had been started
before `components/analytics_results.py` existed; restarting the server
process cleanly resolved it and confirmed the fix works. Not a defect in
the fix itself.)

### What to check

- Is the one-line diff actually correct and complete - does line 486 now
  call the real function, and does nothing else in the file still
  reference the non-existent name?
- Does `FIXLIST.md` Section 6 accurately describe the bug and its fix?

### Reviewer Feedback (Entry 6)

**Verdict: approved.** Independently re-verified before folding in: the
`fffee08` diff really is the exact one-liner (`1 insertion(+), 1
deletion(-)`, nothing else touched); the live file confirms line 486 now
calls the real function and both call sites (425 and 486) resolve to the
same `render_property_detail_dialog` defined at line 279; `FIXLIST.md`
Section 6 exists with an accurate description and its checkbox marked;
full suite rerun independently: 14 passed.

The reviewer's one procedural note - that this entry didn't exist yet
when they checked - is what prompted writing it; no other gaps found.

---

## Entry 7 — FIXLIST.md Section 7, two more NameErrors from the same missed-rename (2026-08-21)

**Status**: Reviewer feedback folded in below - approved.

Commit: `bcb54eb`.

### The bugs

Found by the reviewer's own proactive follow-up sweep after Entry 6 - an
AST-based undefined-name scan across every project `.py` file (the same
bug class as Section 6's `_property_detail_dialog`), not something this
log flagged first. Commit `d41643c` (2026-08-19, "Give the login/register
page a real navbar...") renamed `_render_auth_header()` to
`_render_auth_topbar()` and updated only one of its three call sites
(line 236, inside `render_auth_portal()`). Two more remained on the old
name:

1. `components/auth_portal.py:190` - inside `handle_google_oauth_callback()`
   (fires on every Google OAuth sign-in callback).
2. `components/auth_portal.py:364` - inside `render_reset_password_view(token)`
   (fires the moment anyone opens a password-reset email link).

Verified before fixing: `git show d41643c -- components/auth_portal.py`
confirms the rename happened at the function definition and at line 236
only; `git blame` on lines 190/364 shows `82d0192` (initial commit)
because those specific lines' *content* was never touched by `d41643c` -
only the function they call was renamed out from under them, which is
exactly why `git blame` alone doesn't surface this bug class and a static
undefined-name sweep is needed instead.

### The fix (`bcb54eb`)

Two-line change: both `_render_auth_header()` calls -> `_render_auth_topbar()`.
Line 17's docstring mention of `_render_auth_header` ("see the removed
`_render_auth_header`") is deliberately left as historical text, not a bug.

### Verification

`py_compile` clean, all 14 tests in `tests/test_auth.py` pass. Live
browser check via direct query-string navigation - neither path needs a
real OAuth/email round-trip since the crash was on each function's very
first line, before any external call: `?reset_token=<fake>` now renders
the dark navbar and a graceful "This Link Has Expired" message;
`?code=<fake>` now renders the same navbar and a graceful "Your Google
sign-in link expired" message. (Hit the same stale-dev-server-module-
cache false-negative as Entry 6's first attempt - a clean server restart
resolved it before either check was trusted.)

Also ticked FIXLIST.md Section 5's four checkboxes in the same pass
(monolith split, mock-city generalization, Auto.dev limit, untracked-file
decision) - all genuinely completed per Entries 4-5, just left unticked.

### What to check

- Does the two-line diff correctly resolve both call sites, and does
  anything else in the repo still reference the removed
  `_render_auth_header` name outside the intentional docstring mention?
- Is there a fourth call site anywhere this sweep might have missed?

### Reviewer Feedback (Entry 7)

**Verdict: approved.** Independently re-verified before folding in: the
`.env` gitignore claim (`git check-ignore -v .env` confirms it's ignored)
and that `GMAIL_APP_PASSWORD` in `.env` does contain an email-address-
shaped value rather than an app password - this is an owner-side config
gap flagged for the owner directly, not something for me to change.
No new feedback file was required for this fold-in; recorded directly
from the reviewer's sweep content already on file.

---

## Entry 8 — FIXLIST.md Section 8, deal-math audit (2026-08-21)

**Status**: Reviewer feedback folded in below - approved. Follow-up MAO
polish item (commit `85baa3e`) also done.

Commits: `cbcbc07` (Bug 1), `089b498` (Gaps 2-3).

### The audit (reviewer-initiated, not requested by this log)

The reviewer independently recomputed every metric `compute_deal_metrics`
produces by hand against a worked $400k/$3,500-rent example, spot-checked
`monthly_payment_factor` against a hand computation at 6.5%/30yr,
verified the MAO closed-form is algebraically exact (the price where CoC
hits target) and that HOA propagates correctly through both cash flow and
MAO, checked zero-down/zero-rate guard rails, and separately verified the
car-grading engine (median-based comps, mileage-adjustment direction,
no-comp honesty) - all confirmed correct as-is. One real bug and one
consistency gap surfaced.

### Bug 1: NOI floor hides real losses on all-cash deals

`underwriting.py:41` (`max(0.0, ...)`) and the matching `Math.max(0, ...)`
in `whatif_calculator.py`'s JS clamped NOI at zero. With no debt service
(all-cash or near free-and-clear), cashflow = NOI directly, so a
genuinely money-losing property (the reviewer's cited case: -$2,600/yr
true cash flow) reported $0 cashflow and graded "average" instead of
"critical" - the one badge that exists specifically to warn these buyers
off. A mortgaged loser was never affected (debt service alone pushes
cashflow negative regardless), which is why this went unnoticed.

Fix (`cbcbc07`): NOI stays unclamped everywhere it feeds cashflow/CoC/
grade in both the Python and JS implementations; only the *displayed*
cap-rate value is floored at 0% (`max(0.0, noi)` applied just at that one
read site) to avoid a confusing negative percentage.

### Gaps 2-3: card verdict vs What-If verdict could disagree

The What-If sandbox modeled property management %, maintenance reserve %
(its own default: 5%), and closing costs (added to the CoC denominator);
the shared `compute_deal_metrics()` used by every card/summary surface
modeled none of them. Consequence: the identical listing could grade
"excellent" on its card and drop to "average" inside What-If for the same
inputs - both implementations were internally correct, just different
models.

**Owner decision** (asked directly, since this changes every existing
grade in the app, not just a bug fix): fold all 3 lines into
`compute_deal_metrics()` using What-If's own defaults (mgmt 0%,
maintenance 5%, closing $0) rather than the smaller options (maintenance
only, or leave the two models different and just document it). Chosen
specifically so grades stop disagreeing app-wide, accepting that some
currently-"excellent" cards will grade lower once the real 5% maintenance
reserve applies everywhere, not just in the sandbox.

Fix (`089b498`): `compute_deal_metrics()` gains `calc_mgmt_pct=0.0`,
`calc_maint_pct=5.0`, `calc_closing_costs=0.0` - defaults exactly matching
What-If's own sliders, so none of the 18 existing call sites across the
app needed to change. Management fee and maintenance reserve compute the
same way What-If already does (% of effective gross rent); closing costs
join the down payment in the CoC denominator. The MAO closed-form was
re-derived by hand to absorb all three (mgmt/maintenance/HOA move to the
numerator as fixed income reductions; closing costs move to the numerator
scaled by the target yield) - mirroring, not reinventing,
`whatif_calculator.py`'s own suggested-max-offer algebra. Also updated
`property_card.py`'s "Why This Grade" breakdown table to show the new
management/maintenance/closing-cost lines (only when non-zero, same
pattern as the existing HOA row) - otherwise the table's own numbers
would stop adding up once a nonzero default reserve was silently
subtracted.

### Verification

Constructed an identical-input test comparing `compute_deal_metrics()`
against a line-by-line Python port of the JS formula: noi/cap_rate/
cashflow/coc/mao all matched to `0.0000000000` (floating-point exact) -
confirms the two surfaces are now the same formula, not two independent
ones that happen to agree. A constructed all-cash-loss case now correctly
returns negative NOI/cashflow and grades "critical" (previously "average"
at $0/$0). Live browser check: a property's "Why This Grade" tab and
"What-If Calculator" tab show identical NOI ($32,209) and matching CoC
(13.4%/13.43%) for the same listing - previously these could diverge.
Reran the pre-existing $400k/$3,500-rent worked example and a profitable
all-cash case: both unchanged (mgmt defaults to 0%, so only maintenance's
5% default shifts any existing number, matching What-If's own default
exactly - no silent behavior change beyond what was decided). All 14
tests in `tests/test_auth.py` pass throughout.

### What to check

- Does the MAO re-derivation actually match `whatif_calculator.py`'s own
  algebra in every term, or did the hand-derivation diverge somewhere the
  bit-for-bit test case didn't happen to exercise?
- Are there other display surfaces (PDF export, dashboard stat cards,
  portfolio) that read `metrics["noi"]`/`metrics["cap_rate"]` and might
  now show a value inconsistent with a table that wasn't updated to
  surface the new mgmt/maintenance/closing-cost lines the way
  `property_card.py`'s breakdown table was? (Checked before writing this
  entry: `pdf_export.py` and the dashboard sidebar preview only show
  final aggregate numbers - NOI/cap rate/cash flow/CoC/MAO - with no
  itemized expense list to sum against, so they can't go visibly
  inconsistent the way an itemized table could. `property_card.py`'s
  table was the only itemized breakdown in the app, and it's the one
  already fixed. Reviewer: please double-check this conclusion rather
  than take it at face value.)
- Is defaulting `calc_maint_pct` to 5.0 (a real, non-zero behavior change
  applied to every existing caller with no code change) the right call,
  or should it have required each caller to opt in explicitly instead?

### Reviewer Feedback (Entry 8)

**Verdict: approved**, all three open questions closed definitively.
Independently reran the reviewer's core claim myself before folding it
in - a 3,000-case randomized differential test (Python `compute_deal_
metrics()` vs. a line-by-line port of the JS), not just the single
hand-picked case from the original fix: 0 grade mismatches, worst
relative deviation ~1e-10 (same order as the reviewer's own ~1e-12 -
different random seeds/ranges naturally land at slightly different but
equally-negligible float noise). Also independently confirmed the
"not achievable" edge case is real (not a hypothetical): Python's MAO
formula had no `numerator<=0` guard at all before this round, while
`whatif_calculator.py`'s JS already had one.

- **Q1 (MAO term-by-term match)**: confirmed via two independent
  methods - symbolic term comparison (including the non-obvious detail
  that both models compute management fee AND maintenance as % of
  *effective gross* income, post-vacancy, not gross rent, so the two
  can't diverge on vacancy changes either) and the randomized
  differential test. Two non-algebra differences remain and are
  documented, not bugs: fixed 30y loan term outside the What-If sandbox
  (pre-existing), and the MAO-not-achievable case (now fixed below).
- **Q2 (other display surfaces)**: confirmed safe via a repo-wide grep
  for every itemized metric key - `property_card.py`'s breakdown table
  was the only consumer needing the update it already got;
  `pdf_export.py` only shows aggregates, nothing to go inconsistent.
- **Q3 (calc_maint_pct=5.0 default)**: confirmed correct given the
  owner's explicit decision to have grades stop disagreeing app-wide -
  an opt-in-per-caller design would have preserved exactly the
  divergence the owner chose to eliminate. Portfolio math (a separate
  domain, operates on stored actuals) is unaffected.

**Follow-up fix from this round** (commit `85baa3e`): the MAO-not-
achievable case now returns `mao=None`/`mao_delta=None` instead of a
negative dollar figure, matching `whatif_calculator.py`'s own
`denom>0 && numerator>0` guard exactly (previously Python's denom<=0
fallback was `price`, a Python-only inconsistency with the JS, which
always showed "Not achievable" for both denom<=0 and numerator<=0).
Both consumers (`pdf_export.py`, the Table View's MAO column) updated
to handle `None`/`NaN` without crashing or showing a misleading number.

Also reconfirmed as part of this fold-in: the "no REVIEW_LOG entry for
`cbcbc07`" note in the reviewer's earlier pass was stale by the time it
was read - this same Entry 8 already covered `cbcbc07` (see its opening
line), committed in `ff92f06` before that note was written. No action
needed beyond noting the timing.

---

## Entry 9 — tests/test_underwriting.py, locking in the Section 8 deal-math (2026-08-22)

**Status**: Reviewer feedback folded in below - approved.

Commit: `ba409be`.

### What was added

15 new tests (14 -> 29 total in `tests/`), covering everything FIXLIST
Section 8 changed, so none of it can silently regress:

- **Golden-value worked example** - the exact $400k/$3,500-rent/5% vac/
  1.2% tax/0.4% ins/25% down/6.5%/8% target case the reviewer hand-
  computed in the original audit, asserted across all 13 metrics, plus a
  from-scratch amortization-formula cross-check on debt service
  independent of `monthly_payment_factor` itself (guards against a
  regression that breaks both the app's formula and a golden-value test
  identically).
- **Regression**: an all-cash loser returns negative NOI/cashflow and
  grades "critical" (the exact Bug 1 case), plus a separate test that
  cap-rate display still floors at 0% even though NOI stays a true
  negative underneath it.
- **MAO None guard**, both halves: numerator non-positive and denom
  non-positive, matching the exact condition added in the MAO polish
  (commit `85baa3e`).
- **HOA/management%/maintenance%/closing-costs** each shift cashflow and
  MAO by an independently hand-derived exact amount - closing costs
  specifically asserted to leave cashflow **unchanged** (a one-time cost,
  not an ongoing expense), a real nuance the original task wording
  glossed over but the actual formula requires.
- **Car engine**: `_grade_tier`'s exact 12%/0% boundaries, `_median`
  (odd/even length), `_drop_price_outliers` (drops sub-half-group-median
  prices, leaves groups under 3 untouched), and the mileage-adjustment
  sign via `_grade_real_listings`.

### Verification

Every golden value was independently hand-derived before being locked in
(not copied from the function's own output). Sanity-checked the two
highest-value tests by deliberately reintroducing the original bugs:
reverting the NOI-clamp fix correctly failed exactly the 2 tests guarding
it; reverting the MAO-not-achievable guard correctly failed exactly the 2
tests guarding it - both reverted afterward, `git diff` confirmed clean.
Full suite: 29 passed.

### What to check

- Is the closing-costs-leaves-cashflow-unchanged assertion actually
  correct, or does it misread the formula the same way the original task
  wording did?
- Do the golden values in the worked-example test actually match what the
  reviewer independently hand-computed in the original audit, or only
  what the code currently outputs?

### Reviewer Feedback (Entry 9)

**Verdict: approved.** Confirmed the closing-costs deviation is correct,
not a misreading: closing costs are one-time transaction costs, not
recurring expenses, so asserting unchanged cashflow is the right
behavior - the original task wording's "closing costs shift cashflow"
phrasing was the misreading, not the test. Suite confirmed 29 green, CI
confirmed green on the real GitHub Actions run for this commit.

---

## Entry 10 — GitHub Actions CI (2026-08-22)

**Status**: Reviewer feedback folded in below - approved.

Commit: `27f7a5e`.

### What was added

`.github/workflows/ci.yml`, triggering on `push` and `pull_request`:
checks out the repo, sets up Python 3.13 (matching `.python-version`),
installs `requirements.txt` + `requirements-dev.txt`, compile-checks
every tracked `.py` file (`python -m compileall -q .`), then runs the
full `pytest` suite. No written spec first - standard boilerplate, not a
design decision.

### Verification

Before trusting it, verified in a genuinely clean environment, not just
locally: cloned the repo into an isolated temp directory (no `.env`, no
`agent_config.db` - the real production DB, gitignored, was never
touched), built a fresh venv from `requirements.txt`, and confirmed both
`compileall` and the full suite pass - including that
`database.py`'s `PASSWORD_PEPPER` self-provisioning correctly creates a
fresh `.env` on first run rather than crashing. Then confirmed the real
GitHub Actions run itself (not just the local simulation): polled
`api.github.com/repos/nissim229/DealRadar/actions/runs` until the run
tied to `27f7a5e` completed - **status: completed, conclusion: success**,
all 9 steps green.

### Reviewer Feedback (Entry 10)

**Verdict: approved.** Independently re-verified before folding in: the
workflow file's steps and versions read back correctly (Python 3.13
matching local dev exactly, `compileall` stronger than a per-file
`py_compile` sweep), `requirements-dev.txt` confirmed tracked and pinned,
and the same live run (`.../actions/runs/32543338369`) independently
re-checked as **Success**, all steps green.

One informational-only note (no action required): the run logs a
warning that `actions/checkout@v4`/`actions/setup-python@v5` are running
on a Node.js version GitHub is deprecating for actions - harmless today,
just something to bump when GitHub starts enforcing it.

Also noted: the reviewer's priority list flagged item 4 ("owner sets a
real Gmail app password so password-reset emails actually send") as the
next remaining item - this was independently resolved in this same
session (the owner generated a real 16-character Google App Password
and it was live-tested via a real SMTP login, confirmed successful)
before this entry was written, so item 4 is already closed too. Only
the deliberately-deferred pre-launch admin password rotation remains
open.

---

## Entry 11 — My Portfolio gated behind sign-in for guests (2026-08-22)

**Status**: Reviewer feedback folded in below - approved.

Commit: `9835459`.

### The fix

My Portfolio previously showed guests 2 fake sample properties (a
"guest preview," consistent with the rest of the app's read-only demo
mode at the time). Real feedback: a portfolio is something a customer
builds, not something a guest should preview any version of - it should
gate like History does instead. `render_portfolio_page(is_guest=True)`
now renders the guest banner + an empty-state sign-in gate and returns
immediately, before fetching or rendering any property data - identical
shape to `render_history_page`'s own guest gate
(`analytics_history.py:245-247`).

Removed the guest-mode plumbing this made dead: `_guest_demo_portfolio()`
(the fake-property generator), the `is_guest` guard clauses in
`_save_property_fields`/`_render_tenants_subtab`/
`_render_documents_subtab` (unreachable now), and the `is_guest`
conditionals in the Add-a-Property tab (guests never reach it either).
`guest_action_button`'s call site in the delete-property flow was left
alone - a generic, still-functional helper for real users, not orphaned
code.

### Verification

Live-checked: guest My Portfolio shows only the sign-in gate (no stat
cards, no tabs, no sample data); signing in as the real test account
(`testclient@dealradar.local`) shows the real (empty) portfolio, the Add
a Property form renders correctly (the plan-limit check, now un-gated
from `is_guest`, still passes cleanly for a real user), and the Summary
tab's own empty state is unaffected. All 29 tests pass.

### Reviewer Feedback (Entry 11)

**Verdict: approved.** Independently re-verified before folding in: a
repo-wide grep confirms zero remaining references to
`_guest_demo_portfolio` anywhere (the only other similarly-named hit,
`_run_guest_demo_scan`, is the unrelated property-scan demo feature, not
missed cleanup); `main.py:112` still calls
`render_portfolio_page(is_guest=is_guest)` with the same signature, so
no caller needed updating. Confirmed the removed guest guards
(save-property toast, tenants/documents captions, add-property toast,
the `not is_guest and ...` plan-limit exemption) all sat strictly
downstream of the new early return, making their removal safe rather
than a behavior change for real users. Full suite: 29 passed.

---

## Entry 12 — Reviewer scan: dead code cleanup, deployment blocker, test coverage (2026-08-22)

**Status**: Reviewer feedback folded in below - approved. Follow-up
`datetime.utcnow()` fix (commit `1c5056c`) also done.

Commits: `9f6fff1` (dead code), `c6b681d` (deployment blocker),
`543b7ed` (test coverage).

### Dead code cleanup (`9f6fff1`)

Reviewer-flagged, left over from the monolith split: `database.py`
(now a facade) still imported 8 names it never used itself (`sqlite3`,
`hashlib`, `hmac`, `base64`, `json`, `secrets`, `datetime`/`timedelta`,
`plan_limits.PLAN_ORDER` - each now owned by a sibling module), and
re-exported 2 private helpers (`_user_record_by_id`,
`_sync_is_rented`) that are only ever called inside the sibling module
that defines them, never as `db._name(...)` from anywhere else.
Verified each claim by grep (zero real usages beyond the import line
itself; zero repo-wide `db.X`/`database.X` reliance on the two
re-exports) before removing anything.

### Deployment blocker: hardcoded base URL (`c6b681d`)

Reviewer-flagged: `google_oauth.py:27`'s `REDIRECT_URI` was hardcoded to
`http://localhost:8501` with no way to change it - would break Google
sign-in on any real deployment, since Google rejects any redirect-URI
mismatch against what's configured on the OAuth client. Found the
identical hardcoded value in `components/auth_portal.py`'s
`APP_BASE_URL` (password-reset email links) while fixing this - both
needed the same fix, not just the one flagged. Both now read
`os.getenv("APP_BASE_URL", "http://localhost:8501")` - same env var,
same default, so local dev is completely unaffected until it's
actually set. Added to `.env.example` with a note that the Google
Cloud OAuth client's Authorized redirect URI must be updated to match
whenever this changes.

### Test coverage: pure helpers + security-critical paths (`543b7ed`)

Reviewer-flagged coverage gap, the biggest item in this round: 28 new
tests (29 -> 57 total). `tests/conftest.py` extracts the `temp_db`
fixture (and `_insert_user`/`_get_hash`) out of `test_auth.py`, which
had the only copy, so new test files don't duplicate the setup;
`test_auth.py` refactored to import from it, unchanged behavior.
`tests/test_pure_helpers.py` (11 tests, no DB): `agent_engine.py`'s
`build_zillow_search_url`/`build_redfin_search_url`/
`calculate_distance_miles`, and `google_oauth.py`'s/`email_utils.py`'s
`is_google_oauth_configured`/`is_email_configured`.
`tests/test_security_paths.py` (12 tests, uses `temp_db`):
`change_own_password`, the full password-reset-token lifecycle in one
flow (issue -> validate -> reset -> re-validate confirms single-use
enforcement), `generate_state`/`verify_state` (round-trip, tamper
rejection, expiry via monkeypatching the max-age constant rather than
sleeping), and `deduct_credit` (normal decrement + zero-floor guard).
`tests/test_underwriting.py` gained 5 tests for `car_engine.py`'s
`classify_fuel_type` (including the exact mislabeled-hybrid case its
own docstring exists to fix) and `compute_car_deal_metrics`.

### Verification

Every one of the 13 functions named in the reviewer's list was checked
to actually exist with the claimed signature before a test was written
against it. Sanity-checked the highest-value new test by deliberately
breaking single-use token enforcement in `reset_password_with_token`
(commented out the `used=1` update) - exactly the one test guarding
that property failed, the other 11 in the same file still passed;
reverted, confirmed clean. Live-checked the deployment-blocker fix:
the password-reset-link flow (`?reset_token=` query param) renders
identically with no `.env` override, same as before the change. Full
suite: 57 passed, both locally and on the real GitHub Actions run for
`543b7ed` (confirmed via the GitHub API, not just assumed from a local
pass).

### What to check

- Are there other places in the codebase with the same hardcoded-
  localhost pattern that neither the reviewer's scan nor this fix
  caught? (Checked before writing this entry: a repo-wide grep for
  `localhost:8501` now finds only the two intentional
  `os.getenv("APP_BASE_URL", "http://localhost:8501")` default
  expressions themselves - nothing else hardcoded. Reviewer: please
  double-check this rather than take it at face value.)
- Do the new security-path tests actually exercise the real code paths
  a browser-driven flow would hit, or do any of them call the
  underlying `database_profile.py`/`google_oauth.py` functions in a way
  that skips something a real request would go through?

### Reviewer Feedback (Entry 12)

**Verdict: approved**, all three commits verified clean against the
real diffs (dead-code removal, both `APP_BASE_URL` sites, the full test
suite). Confirmed HEAD/branch/tree state matched, 57/57 passed.

**Security-path coverage question, answered with call-site citations**:
the reviewer traced each test back to its real production call site -
`components/settings.py:291` (`change_own_password`),
`components/auth_portal.py:350/385/417` (the reset-token lifecycle, in
the same order the tests exercise it), and
`components/analytics_scan_engine.py:217` (`deduct_credit`) - all
independently confirmed correct by re-reading those exact lines. One
citation needed a correction: `generate_state` is not called directly
from `auth_portal.py:188` as stated - it's called from inside
`google_oauth.build_auth_url()` (line 91), which `auth_portal.py:114`
calls. The tests still validate the real production code path (`build_
auth_url` is the only caller of `generate_state` anywhere in the repo),
just one level removed from where the citation placed it - not a defect
in the tests themselves, a citation-accuracy correction only.

**New finding, fixed in this round** (commit `1c5056c`):
`database_profile.py:126,159` used `datetime.utcnow()`, deprecated
since Python 3.12 and surfaced as 6 warnings by the new test suite.
Not a naive find-replace - swapping in `datetime.now(datetime.UTC)`
would produce an *aware* datetime, but `expires_at` is stored as a
plain string and re-parsed via `datetime.strptime()` (always naive) -
comparing an aware "now" against that naive value would raise
`TypeError`. Fixed with `datetime.now(timezone.utc).replace(tzinfo=None)`,
which reproduces `utcnow()`'s exact old naive-UTC value instead.
Verified: full suite reruns clean under `-W error::DeprecationWarning`
(promotes any remaining deprecation warning to a hard failure) -
57 passed, confirming the warning is actually gone; a direct functional
check against a temp DB confirmed a valid token still validates and an
already-expired one is still correctly rejected, so the fix didn't
silently change the real expiry comparison logic. CI green on the real
GitHub Actions run for `1c5056c`.

## Entry 13 — Focused security pass + rehab costs in the deal formula (2026-08-22)

**Status**: Both done, verified locally + live in browser. Not yet
reviewed by HG.

Commits: `03d9640` (security pass), `3cd870f` (rehab costs).

### Security pass (`03d9640`)

Owner asked what else the app could use; scoped this to 3 concrete,
checkable categories matched to recently-changed code rather than an
unbounded audit: IDOR, SQL injection, XSS.

- **XSS**: `components/property_card.py` and
  `components/analytics_results.py` both build a PDF-export `<a
  download="...">` attribute via an f-string inside
  `unsafe_allow_html=True`, interpolating a user-controlled title/
  profile name with no escaping - a `"` in that string breaks out of
  the attribute. Fixed with `html.escape(..., quote=True)` on the
  filename in both files. Distinguished from a non-issue considered
  and rejected: Brand & Design's logo-preset name is admin-only and
  that panel already grants admins raw-HTML injection by design, so
  it's not a real trust-boundary crossing.
- **IDOR (defense-in-depth, not a live exploit)**: `add_tenant` and
  `add_document` in `database_portfolio.py` inserted rows scoped to a
  `property_id` without first checking that property actually belongs
  to `user_id` - every sibling function in the same file (get/update/
  delete for tenants, documents, properties) already does this check;
  these two inserts were the only exception. Traced the actual call
  path before fixing: not reachable through today's UI, since
  Streamlit's `session_state` isn't client-manipulable the way a REST
  API's parameters would be. Fixed anyway as correct hygiene matching
  every other function in the file, not because of a live exploit.
- **SQL injection**: reviewed, found no new issues - the file already
  parameterizes every query.

Verified: `py_compile` clean on both edited files; full suite (57
tests) still green (no test exercised these code paths, so nothing
was expected to change); live-checked both PDF exports (property card
and scan results) still download correctly with the escaped filename
rendering as plain text, not breaking the attribute.

### Rehab costs in the deal formula (`3cd870f`)

The reviewer's original deal-math audit (Entry 8) flagged rehab budget
as a real-world cost line missing from BOTH `compute_deal_metrics()`
and the What-If sandbox - the one gap left after mgmt/maintenance/
closing were fixed. Added `calc_rehab_cost` to `compute_deal_metrics()`
in `underwriting.py`, treated identically to `calc_closing_costs` in
every formula (one-time cash that never touches NOI/cashflow, only
shifts `total_cash_needed`/CoC denominator and MAO's numerator scaled
by `target_yield`) - same derivation, not a new one. Added the
matching input to `whatif_calculator.py`'s JS sandbox (3rd field in
the "At Purchase" row, using the pre-existing but previously-unused
`wi-field-grid-3` CSS class) and a conditional "🛠️ Rehab budget" row
to `property_card.py`'s "Why This Grade" breakdown, generalizing the
CoC help text to list whichever upfront-cost lines are actually
present.

Verified independently via a standalone script before touching any
UI: cashflow unchanged, `total_cash_needed` shifts by exactly the
rehab delta, MAO shifts by exactly `target_yield * rehab / denom` to
the penny. Confirmed live in the browser: typing $25,000 into Rehab
Budget on a real scanned property left Monthly Cash Flow at $1,246
unchanged, moved Cash Needed from $73,788 to exactly $98,788, dropped
CoC ROI 20.26% -> 15.14%, and dropped Suggested Max Offer $392,577 ->
$371,046 - all matching the formula. Added 2 new tests
(`test_rehab_cost_leaves_cashflow_unchanged_but_shifts_coc_and_mao`,
`test_closing_costs_and_rehab_cost_combine_additively_in_mao`). Full
suite: 59 passed (57 prior + 2 new).

Confirmed, before writing this entry: no current call site of
`compute_deal_metrics()` passes `calc_rehab_cost` (or, checked at the
same time, `calc_closing_costs`) as a nonzero value - both are opt-in
parameters with display code ready on the card, but neither has a
dedicated per-property input outside the What-If sandbox yet. The new
rehab breakdown row is therefore currently unreachable in production,
same as the pre-existing closing-costs row - a consistent, pre-
existing pattern, not a new gap.

### What to check

- The IDOR fix's ownership-check queries (`SELECT 1 FROM
  portfolio_properties WHERE id=? AND user_id=?`) - do they match the
  exact pattern every other scoped function in `database_portfolio.py`
  uses, or did this introduce any subtle difference?
- The rehab-cost MAO/CoC algebra - independently re-derive it against
  `underwriting.py`'s own docstring rather than trusting the "matches
  closing costs" claim at face value.
- Whether `calc_rehab_cost`/`calc_closing_costs` being unreachable from
  any current UI call site (noted above) is worth its own FIXLIST item
  - a future "add rehab/closing-cost inputs to the property card
    itself" task - or whether that's out of scope until a real user
  need shows up.

### Reviewer Feedback (Entry 13)

**Verdict: approved**, no new issues. `REVIEWER_FEEDBACK.md` was
properly overwritten this round (a single clean write, not prepended
to prior rounds - the convention holding this time). Independently
re-checked the specific claims below before folding them in rather
than taking them at face value:

- **XSS fix**: confirmed `html.escape(f"...", quote=True)` at
  `property_card.py:288` and `analytics_results.py:706`, both with
  `import html` present, both files' filename f-strings now escaped
  before landing in `download="..."`.
- **IDOR line citations**: `update_portfolio_property:84`,
  `delete_portfolio_property:103`, `get_tenants:184`,
  `update_tenant:160`, `delete_tenant:172`, `get_documents:217`,
  `delete_document:234` - all confirmed to be the ownership-scoped SQL
  WHERE clauses inside the functions defined a few lines above each
  (def lines 74/92/155/168/178/211/224 respectively). Citations
  accurate this round.
- **Python <-> JS formula parity**: confirmed
  `(target_yield * (calc_closing_costs + calc_rehab_cost))` at
  `underwriting.py:124` matches `(targetFrac * (closing + rehab))` at
  `whatif_calculator.py:386` exactly - same treatment, same terms.

Nothing to correct this round - reviewer's citations and algebra both
held up under direct verification.

## Entry 14 — Manual price-drop "Check Now" on saved properties (2026-08-22)

**Status**: Done, verified live as 3 distinct accounts. Not yet
reviewed by HG.

Commit: `d7c1caa`.

Closes the standout item from HG's own "what to add next" list
(price-drop alerts) - the one HG suggestion that survived independent
verification as a real, unimplemented gap (2 of HG's other 7
suggestions turned out to already exist in the app - see Entry 12's
discussion). Owner's explicit framing before implementation: leave
real payment processing for later, but this + a security pass were
worth doing now.

### Why manual, not automatic

Investigated whether this could be a background job (checks fire
without anyone opening the app) before writing any code. Found: this
app has **no background scheduler at all** - every existing alert
(RentCast quota, low credits, deal-found) fires synchronously, inline,
only when a user is actively running a scan. Building real background
alerting would mean adding infrastructure outside the Streamlit app
itself (e.g. a Windows Task Scheduler job), which the owner did not
ask for. Combined with a second real constraint the owner raised
directly - RentCast has a tight monthly cap on real estate, Auto.dev
(cars) has much more headroom - any automatic per-property recheck
loop risks silently burning through a scarce, real-dollar-cost
resource. Presented 3 options (check-on-visit, piggyback on the
existing area cache, real scheduled job); owner asked for a
recommendation while explicitly flagging the quota concern, which
shaped the final design below.

### What got built

- `check_saved_property_price()` (`agent_engine.py`): re-runs a real
  RentCast search centered on the saved property's OWN lat/lon and
  looks for an exact address match. Initially assumed this could ride
  the existing area-cache for free (see Entry 12/13's caching
  discussion); checked the actual cache-key composition before
  promising that and found it doesn't hold - the cache key includes
  the ORIGINAL scan's search-center coordinates and specific property
  type, which essentially never matches a saved property's own
  coordinates + "any type." Corrected course before writing the UI:
  this is honestly a real API call in the common case, so gating it
  behind a real cost (1 credit, same as a live scan) is not just
  cautious, it's accurate.
- Gating deliberately reuses the plan/credit system that already
  exists instead of inventing a new per-tier quota: `is_admin_or_above`
  bypasses entirely (mirrors the exact same bypass real live scans
  already get), any signed-in user with `credits > 0` can click it,
  disabled+tooltipped otherwise. This directly answers the owner's own
  question ("what goes to package or not") - nothing new needs
  deciding; a plan's existing credit allotment already controls whether
  its users can afford to use this.
- `price` is always overwritten with the fresh read (it was already
  mutable via `save_property`'s own `ON CONFLICT DO UPDATE`, never an
  immutable snapshot); the alert (toast + opt-in email via new
  `notify_price_drop` Settings toggle, defaulting off like
  `notify_deal_found`) fires only when the fresh read is lower than
  what was on file.
- New nullable `last_price_checked_at` column on `saved_properties`
  (standard try/except-OperationalError migration, same pattern as
  every other additive column in `database_schema.py`).

### Verified

Live in the browser as 3 distinct accounts on a restarted server
(the schema migration only runs at `database.py`'s import time, so a
server that was already running before this change needed a real
restart - confirmed via a stale-column symptom: the button silently
never rendered until the restart, traced to that root cause rather
than assumed):
- **super_admin** (`admin@scoutai.com`): button always enabled,
  bypasses credits. Full click -> spinner -> real RentCast lookup ->
  toast flow confirmed end to end. The saved property checked
  (mock/simulated data, like most of this dev DB) correctly came back
  "not currently found among active listings" - an honest no-data
  result, not a bug, since there's no real listing behind a simulated
  address to match against.
- **0-credit test user** (temporary test account, saved property
  added and removed for this test only): button correctly renders
  disabled with the exact tooltip "Out of credits - buy more or
  upgrade your plan to check for price drops."
- Confirmed via direct DB query which real plan-tier accounts exist
  and which credit levels they're at, rather than assuming.

`py_compile` clean on all 7 touched files; full suite 59 passed
(unchanged - no test exercises this new UI path yet, matching how
`add_tenant`/`add_document`'s IDOR fix in Entry 13 also had no direct
test coverage).

### What to check

- Is `check_saved_property_price`'s address-matching (`listing["address"]
  == address`, an exact string match against RentCast's own
  `formattedAddress`) too brittle - could a real listing's address
  format drift slightly from what was saved and cause a false "not
  found" even when the property IS still listed?
- Whether spending 1 credit on a check that comes back "not found" (as
  opposed to "found, no drop") is the right call, or whether a
  no-data result should be free since nothing conclusive was learned.
- The claim that RentCast's cache-key composition (rounded lat/lon +
  property_type + radius) makes free cache-hit reuse rare for this
  specific use case - reviewer's own read of `_fetch_rentcast_listings`
  welcome, since this is the assumption the whole "gate behind 1
  credit" design rests on.

### Reviewer Feedback (Entry 14)

**Verdict: all 3 checks confirmed accurate** on independent
verification - admin-bypass pattern match (`analytics_scan_engine.py`
215-217 vs `analytics_saved.py` 31,48-49), the shared `formattedAddress`
field on both sides of the address comparison (`agent_engine.py:262`),
and the "not found" early-return-before-`record_price_check` asymmetry
(confirmed at the exact lines cited). `REVIEWER_FEEDBACK.md` again
properly overwritten (single "Round 5" write). Reviewer additionally
flagged a real multi-unit/condo edge case for address-as-identifier
(pre-existing, baked into the `UNIQUE(user_id, address)` constraint,
not new) and suggested fixing the asymmetry via option (a): stamp
`last_price_checked_at` even on "not found," since a real check WAS
performed.

**Implemented option (a)** (commit `3024eda`) - and while wiring in the
second call to `db.record_price_check(...)`'s sibling function,
**found a real bug neither the reviewer's read nor my own original
live testing had caught**: `record_price_check()` itself (added in
`d7c1caa`) was never re-exported from `database.py`'s facade, so
`db.record_price_check(...)` would raise `AttributeError` the moment
ANY check actually found a real price - the "not found" branch was the
ONLY one that had ever been exercised, in review or in testing,
because every saved property tested against was mock-sourced and
therefore always "not found" against real RentCast data. Confirmed via
`hasattr(db, "record_price_check")` before assuming, added the missing
re-export, then re-verified live end to end on a freshly restarted
server: "Check Now" now correctly flips the caption from "Price not
manually checked yet" to "Price checked just now," confirmed directly
against the DB. Full suite: 59 passed.

## Entry 15 — Saved Properties promoted to its own top-nav tab (2026-08-22)

**Status**: Done, verified live. Not yet reviewed by HG.

Commit: `bdf0e4a`.

Owner's complaint: Saved Properties rendered inline at the bottom of
Run Property Scans, below the search form, hero stat cards, results
grid, and map - too long a scroll to reach after running a scan.
History got this exact complaint earlier in the project and was
promoted to its own navbar item; Saved Properties was left behind in
the old layout at the time this app's nav was simplified.

Added `render_saved_properties_page()` to `components/analytics_saved.py`,
copying `render_history_page()`'s shape exactly: its own hero banner,
the identical guest-gate copy that used to live inline in
`analytics_dashboard.py`, and - since there's no interactive Pro
sidebar up here to source `calc_*` from - the user's saved default
assumptions instead of live slider values. Same tradeoff History
already made and shipped with; nothing new invented.

Wired in via the same plumbing every other nav item already uses:
`CATEGORY_MENUS` in `topbar.py` (plus the Help popover's numbered
list), `main.py`'s page router, `components/analytics.py`'s facade
re-export. Removed the dead inline block and 3 now-unused imports
(`render_guest_banner`, `render_empty_state`,
`_render_saved_properties_tab`) from `analytics_dashboard.py`.

### Verified

Live in the browser on a freshly restarted server: Saved Properties
now shows as its own topbar tab between Run Property Scans and
History; guest view renders the same gate copy as before, now with a
proper page hero; signed in as admin, saved properties + the Check Now
button (Entry 14) render correctly with zero scrolling required; Run
Property Scans itself now ends right after the map/export button, with
no Saved Properties section left at the bottom. `py_compile` clean on
all 5 touched files. Full suite: 59 passed, no regressions. No server
errors in the logs.

### What to check

- Whether the 4-tab navbar (`Run Property Scans`, `Saved Properties`,
  `History`, `My Portfolio`) still fits comfortably at narrower
  viewport widths - `nav_cols = st.columns(len(menu_options))` sizes
  itself to whatever's in `CATEGORY_MENUS`, so it's mechanically
  correct, but a 4th tab makes each one narrower than 3 did.
- Tab placement: Saved Properties was put 2nd (right after Run
  Property Scans, before History/My Portfolio) as the closest fit to
  the natural workflow (scan -> save -> come back later) - worth a
  second opinion on whether that ordering is actually right.

## Entry 16 — View modes + sort for Saved Properties; Check Now moved into the dialog (2026-08-22)

**Status**: Done, verified live. Not yet reviewed by HG.

Commit: `f4b69d3`.

Owner's ask: bring "all the view and sort options" to Saved
Properties, which had only a fixed 2-column card grid - no filters, no
map, no table, no way to reorder a growing saved list.

### View modes + quick filters

Reused the exact same toolbar and 4 view-mode functions scan results
and History already share (`_render_quick_filter_toolbar`,
`_render_properties_only_view`, `_render_properties_and_map_view`,
`_render_map_only_view`, `_render_table_view` -
`components/analytics_results.py`) rather than reimplementing them.
Those functions all take a JSON string (not a Python list), so
`_render_saved_properties_tab` now builds each row as a dict (metrics
precomputed once per row), sorts the list, then `json.dumps()`s it
before handing off - zero changes needed to the shared functions
themselves, so scan results/History are untouched.

### Sort (new - didn't exist for properties before)

Ported from car search's own "Sort by" popover - the only place a sort
control existed in this app before (scan results itself never had
one). "Best Deal First" sorts directly by cash-on-cash return;
properties always get a real grade from `compute_deal_metrics`, so
(unlike cars) there's no "too few comps to grade" case to carve out.
Also added Price (low/high) and Newest/Oldest Saved.

### Check Now relocated into the property detail dialog

The shared view-mode functions have no extension point for per-card
extra content, so Entry 14's "Check Now" button (previously inline
under every card in the old custom grid) moved into
`render_property_detail_dialog` as a new "Price Check" tab -
`_render_property_detail_tabs` only adds it when
`db.is_property_saved(user_id, address)` is true, so it never appears
on a plain scan result. Net improvement, not just a workaround: Price
Check is now reachable from every view mode (Properties Only/+Map/Map
Only/Table View), not just the one grid layout it used to be pinned
to. Added `get_saved_property_check_info()` to
`database_saved_properties.py` (+ facade re-export in `database.py`)
so the dialog can look up one property's check-freshness without the
full saved list already in hand.

**Known trade-off, not a regression**: the old per-card "Saved 3 days
ago" caption is gone - the shared view functions have no slot for it.
Partly recovered via the new Newest/Oldest Saved sort options instead
of a permanently-visible per-card timestamp.

### Verified

Live on a freshly restarted server, signed in as admin: sort control
renders and correctly reorders (confirmed in Table View - Excellent/
highest-CoC rows first, then Average, then Critical last); Properties
+ Map, Map Only, and Table View all render real saved-property data
correctly; opened the Price Check tab via "View Full Details" and
clicked Check Now - confirmed end-to-end against the DB
(`last_price_checked_at` correctly stamped). `py_compile` clean on all
4 touched files. Full suite: 59 passed, no regressions. No server
errors in the logs.

### What to check

- Whether losing the per-card "Saved X ago" caption is an acceptable
  trade for the new sort options, or worth a follow-up to recover it
  some other way.
- Whether Check Now living only in the dialog (not also inline on the
  card) hurts discoverability compared to Entry 14's original always-
  visible placement - the dialog does require one more click
  ("View Full Details") to reach it now.
- The precomputed `_coc`/`_saved_at` extra keys added to each row dict
  before JSON-encoding - confirmed they don't leak into Table View's
  visible columns (it builds its own named-column dict, not a raw
  dump of the DataFrame), but worth a second look given they ride
  along through `_render_properties_only_view`/`_render_properties_
  and_map_view` too.
