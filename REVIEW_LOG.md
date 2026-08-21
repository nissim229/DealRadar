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
