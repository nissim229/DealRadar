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
