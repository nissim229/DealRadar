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
