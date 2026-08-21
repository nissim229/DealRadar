# DealRadar — Pending Fixes & Improvements

> Prepared by the reviewing assistant (ox-alpha) after a full codebase review.
> Work already completed and independently verified — do NOT redo:
>
> - Password hashing: unsalted SHA-256 → HMAC-peppered bcrypt with transparent
>   migration, timing equalization, cost-factor self-upgrade (commits ade4ee4,
>   82828c2, 5aa927f — all verified with a 15-case functional suite plus the
>   CWD regression test; pepper loading confirmed CWD-safe).
> - Dependency pinning: requirements.txt fully pinned, tzdata added,
>   openai bumped to 3.3.1, requirements-lock.txt added, .python-version added.
>
---

## 1. Quick wins (do these first, one commit)

- [x] **Delete dead database files** in project root:
      `app_data.db`, `dealradar.db`, `scoutai.db` — all 0 bytes, leftovers from
      renames. Only `agent_config.db` is real (see `DB_NAME` in database.py).

- [x] **Fix bare `except:` clauses** in `agent_engine.py` lines 357 and 362.
      They wrap `int()` conversions (max_price / min_beds) and currently swallow
      everything including KeyboardInterrupt. Change to:
      `except (TypeError, ValueError):`

- [x] **Rewrite SETUP.md** — it is stale:
      - Title still says "ScoutAI Enterprise"; app is now DealRadar.
      - Folder structure section doesn't match reality (components/ has grown,
        there are now many more root modules).
      - Documents `admin@scoutai.com` / `admin123`. The owner is deliberately
        keeping this password until launch (project not live yet) — replace the
        credential mention with a prominent "BEFORE GOING LIVE: rotate the
        seeded admin password (admin123 is public in git history)" warning
        instead of deleting the info silently.

## 2. Real test suite (pytest) — protects everything that comes after

- [x] Create `requirements-dev.txt` with `pytest` (keep it out of the runtime
      requirements.txt / lock file).
- [x] Create `tests/test_auth.py` porting the ad-hoc verification suite:
      - wrong password rejected on a bcrypt account
      - legacy SHA-256 hash: login succeeds AND stored hash upgrades to
        `$2b$12$...`; second login succeeds with NO further rewrite
      - transitional unkeyed-bcrypt hash (bcrypt over bare sha256 digest):
        recognized, login succeeds, upgraded to peppered scheme
      - low-cost bcrypt hash (e.g. rounds=4): login succeeds, cost raised to 12
      - 200+ character passphrase round-trips (pre-hash path)
      - nonexistent email returns None; empty stored hash rejected
      - pepper is load-bearing: a hash created under pepper A fails
        verification under pepper B
      - suspended account still returns `{"suspended": True}`
      - rough timing parity between missing-account and wrong-password paths
- [x] **Hard rule: tests must never touch the production `agent_config.db`.**
      Copy it to a temp file and monkeypatch `database.DB_NAME` for every test
      (fixture-scoped).
- [x] Add the pepper regression test: import `database` with CWD set to an
      unrelated directory, assert `.env` is byte-for-byte unchanged afterwards
      and `PASSWORD_PEPPER` resolves to the value already in `.env`.
- [x] Run `pytest` before every commit from here on.

## 3. Silent exception audit (17 broad handlers) [x]

Done in commit `9d493b9` - see REVIEW_LOG.md Entry 3. Actual current count
was 24 sites across 6 files (this list was approximate/stale, as noted
below); audited the full current set, not just what's listed here.

These swallow errors invisibly. For each one, make a deliberate choice:
log it (`logging` module or `st.error` where user-facing), re-raise, or add a
comment explicitly justifying the silence. Approximate locations:

- `components/analytics.py`: lines 391, 726, 837, 863, 898, 1094, 1151, 1250,
  1403, 1563, 1824, 1920
- `agent_engine.py`: lines 73, 667
- `components/settings.py`: line 62

(Line numbers approximate — locate by surrounding code, they predate recent
commits.)

## 4. sqlite connection hygiene [x - no code change needed]

Checked in the round covered by commit `9d493b9`/REVIEW_LOG.md Entry 3 -
verified all 109/109 `sqlite3.connect()` sites in `database.py` already
have a matching `try:`/`finally: conn.close()` pair. The leak risk this
item describes doesn't currently exist; a `closing()` refactor would be
purely cosmetic. Deliberately not done - see Entry 3's own reasoning.

`database.py` opens `sqlite3.connect(...)` ~108 times with manual
`conn.close()`. Any exception path without try/finally leaks the connection.
Wrap call sites in a helper, e.g.:

```python
from contextlib import closing
with closing(sqlite3.connect(DB_NAME)) as conn:
    ...  # closing() guarantees close; use conn.commit() as today
```

Note: `with sqlite3.connect(...)` alone only manages transactions, NOT closing
— don't confuse the two. This is mechanical but wide; consider doing it in
2–3 focused commits rather than one giant diff.

## 5. Later / cosmetic (fine to defer)

- [ ] Split monoliths: `components/analytics.py` (~2,000 lines),
      `database.py` (~2,750 lines), `topbar.py` (~48 KB).
- [ ] Generalize the hardcoded mock-city directory in `agent_engine.py`
      (currently Denver/Boulder only) used by the offline fallback generator.
- [ ] Make Auto.dev monthly limit admin-editable, mirroring
      `db.get_rentcast_config()` (a code comment in car_engine.py already
      flags this as intended follow-up).
- [ ] Decide fate of untracked files: `.agents/`, `.claude/settings.local.json`,
      `.claude/skills/` — commit intentionally or add to .gitignore.

---

## Pre-launch checklist (NOT now — owner's explicit decision)

- [ ] Rotate the seeded admin password away from `admin123` BEFORE the app or
      repo goes public. It is permanently in git history.

## Ground rules

1. Never write to the production `agent_config.db` from tests or scripts.
2. Never regenerate or overwrite `PASSWORD_PEPPER` in `.env`.
3. Keep commits focused: one logical change per commit.
4. After each change: `python -m py_compile` on touched files, then full
   `pytest` once the suite exists.
