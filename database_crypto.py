"""
database_crypto.py
Password hashing/verification, split out of database.py (Section 5 of
FIXLIST.md/REVIEW_LOG.md - the monolith-split plan). Re-exported by
database.py so `import database as db; db.hash_password(...)` etc. keep
working unchanged, and so tests/test_auth.py's direct calls to the
underscore-prefixed names here (`db._generate_account_id` lives in
database_shared.py instead, but `db._is_bcrypt_hash`, `db._pre_hash_password`,
`db._bcrypt_cost_of` are all defined here) keep resolving.

Deliberately does NOT own DB_NAME, _ENV_PATH, PASSWORD_PEPPER, BCRYPT_COST,
or _TIMING_DUMMY_HASH - those stay in database.py itself (see that file's
own comments) for two reasons: (1) DB_NAME/_ENV_PATH are computed from
this module's own __file__, so they'd resolve to the wrong directory if
this ever became a package; (2) tests/test_auth.py does
`monkeypatch.setattr(db, "PASSWORD_PEPPER", ...)` / `monkeypatch.setattr(db,
"DB_NAME", ...)` directly on the `database` module object - every function
here reads those back via `import database; database.XXX` at CALL time
(never a bare name, never `from database import XXX`) so the monkeypatch
keeps reaching them. This does create a real circular import (database.py
imports from here, this file imports database.py back) - safe specifically
because `import database` below only binds the module name eagerly; the
actual attribute reads happen lazily inside function bodies, by which point
database.py has already finished defining DB_NAME/_ENV_PATH/PASSWORD_PEPPER/
BCRYPT_COST/_TIMING_DUMMY_HASH (see database.py's import ordering).
"""
import hashlib
import hmac
import base64
import os
import secrets
import sqlite3
import bcrypt

import database


def _check_for_duplicate_pepper_lines():
    """python-dotenv resolves a duplicate key within one file by silently
    taking the last occurrence - if .env ever ends up with two
    PASSWORD_PEPPER= lines (e.g. from the exact re-provisioning bug this
    anchoring fix closes), a future load could silently pick the WRONG one
    relative to whichever pepper actual stored hashes were created with.
    Refuses to start rather than guess."""
    if not os.path.exists(database._ENV_PATH):
        return
    with open(database._ENV_PATH, "r", encoding="utf-8") as f:
        count = sum(1 for line in f if line.strip().startswith("PASSWORD_PEPPER="))
    if count > 1:
        raise RuntimeError(
            f"Found {count} PASSWORD_PEPPER= lines in .env - refusing to start. "
            "python-dotenv would silently use only the last one, which may not "
            "be the pepper existing bcrypt password hashes were created with. "
            "Manually remove all but the correct line, then restart."
        )

def _any_bcrypt_hash_exists():
    """True if the users table already has at least one bcrypt hash. Used
    as a safety interlock: if PASSWORD_PEPPER is missing but bcrypt hashes
    already exist, minting a fresh pepper would silently make every one of
    those hashes unverifiable forever. Returns False (nothing to protect
    yet) if the database or table doesn't exist - a genuinely fresh
    install, not a lost pepper."""
    if not os.path.exists(database.DB_NAME):
        return False
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='users'")
        if cursor.fetchone()[0] == 0:
            return False
        cursor.execute("SELECT COUNT(*) FROM users WHERE password_hash LIKE '$2%'")
        return cursor.fetchone()[0] > 0
    except sqlite3.Error:
        return False
    finally:
        conn.close()

def _load_or_create_password_pepper():
    """The HMAC key used to pre-hash passwords before bcrypt (see
    _pre_hash_password()). Keeping it in .env, separate from the database,
    means a leaked DB dump alone can't be replayed into valid bcrypt inputs
    for a dictionary/rainbow-table attack - the "shucking" risk of an
    unkeyed pre-hash, where a cracked legacy SHA-256 digest is itself
    everything needed to authenticate against the new scheme. Self-
    provisions on first run, the same way init_db() seeds a first admin
    account - but unlike that seed, losing this value after real passwords
    have been hashed with it would lock every user out, so (a) it's loaded
    from the anchored _ENV_PATH explicitly rather than ambient os.getenv()
    (see the module-level load_dotenv() note above), (b) it refuses to
    silently mint a replacement if bcrypt hashes already exist without one,
    and (c) once generated, it's written to .env immediately and never
    silently regenerated again."""
    _check_for_duplicate_pepper_lines()
    pepper = os.getenv("PASSWORD_PEPPER")
    if pepper:
        return pepper.encode()
    if _any_bcrypt_hash_exists():
        raise RuntimeError(
            "PASSWORD_PEPPER is missing from .env, but the database already "
            "contains bcrypt-hashed passwords. Generating a new pepper now "
            "would make every one of those hashes permanently unverifiable - "
            "refusing to start. Restore the correct PASSWORD_PEPPER line in "
            ".env instead (check backups / other machines), then restart."
        )
    pepper = secrets.token_hex(32)
    with open(database._ENV_PATH, "a", encoding="utf-8") as f:
        f.write(f"\nPASSWORD_PEPPER={pepper}\n")
    os.environ["PASSWORD_PEPPER"] = pepper
    print("[Security] Generated a new PASSWORD_PEPPER and saved it to .env - "
          "back this file up; losing this value invalidates every stored password hash.")
    return pepper.encode()

def _pre_hash_password(password):
    """HMAC-SHA256 keyed with PASSWORD_PEPPER, then base64-encoded - the
    same bcrypt_sha256 pattern passlib uses. This keeps the result under
    bcrypt's 72-byte input limit regardless of the original password's
    length, and - because it's keyed with a secret that lives only in
    .env, never in the database - a leaked DB dump alone can't be used to
    derive valid bcrypt inputs, unlike an unkeyed SHA-256 pre-hash."""
    digest = hmac.new(database.PASSWORD_PEPPER, password.encode(), hashlib.sha256).digest()
    return base64.b64encode(digest)

def _pre_hash_password_unkeyed(password):
    """The transitional pre-hash this app briefly used with bcrypt before
    PASSWORD_PEPPER was introduced (a bare SHA-256 digest, no pepper).
    Kept only so _check_password() can recognize and upgrade any account
    migrated during that window - never used to create new hashes."""
    return hashlib.sha256(password.encode()).digest()

def hash_password(password):
    """Securely hashes a password: HMAC-SHA256 pre-hash (see
    _pre_hash_password) then bcrypt at BCRYPT_COST. Always produces the
    current best format - existing weaker-format hashes are upgraded
    lazily on login, see authenticate_user()."""
    return bcrypt.hashpw(_pre_hash_password(password), bcrypt.gensalt(rounds=database.BCRYPT_COST)).decode()

def _hash_password_legacy(password):
    """The original unsalted, unpeppered SHA-256 hashing this app used
    before any bcrypt migration. Kept ONLY so _check_password() can still
    verify an account that hasn't logged in since - never used to create
    new hashes."""
    return hashlib.sha256(password.encode()).hexdigest()

def _is_bcrypt_hash(stored_hash):
    """bcrypt hashes always start with one of these version prefixes;
    a legacy SHA-256 hash is just a 64-char hex digest and never does."""
    return bool(stored_hash) and stored_hash.startswith(("$2a$", "$2b$", "$2y$"))

def _bcrypt_cost_of(stored_hash):
    """Extracts the cost factor bcrypt encoded into stored_hash (the
    "$2b$12$..." field), so authenticate_user() can opportunistically
    rehash an old, lower-cost hash up to BCRYPT_COST as that target rises
    over time, without a separate mass-migration each time it does."""
    try:
        return int(stored_hash.split("$")[2])
    except (IndexError, ValueError, AttributeError):
        return None

def _burn_bcrypt_time():
    """Runs one throwaway bcrypt check at the real cost factor, purely so
    the legacy-hash and no-such-account paths in _check_password() take
    roughly as long as a real bcrypt verification - otherwise a network
    observer could use response latency alone to learn that a given email
    doesn't exist, or that a given account hasn't been migrated to bcrypt
    yet, without any database access."""
    bcrypt.checkpw(b"x", database._TIMING_DUMMY_HASH)

def _check_password(password, stored_hash):
    """Returns (matched, needs_upgrade). needs_upgrade is True when the
    password matched but stored_hash isn't in the current best format:
    the original unsalted SHA-256 scheme, the brief transitional
    bcrypt-over-unkeyed-SHA-256 scheme, or a bcrypt hash whose cost factor
    is below BCRYPT_COST. authenticate_user() uses this to decide whether
    to opportunistically rewrite the stored hash on a successful login."""
    if not stored_hash:
        _burn_bcrypt_time()
        return False, False
    if _is_bcrypt_hash(stored_hash):
        try:
            if bcrypt.checkpw(_pre_hash_password(password), stored_hash.encode()):
                return True, (_bcrypt_cost_of(stored_hash) or 0) < database.BCRYPT_COST
            if bcrypt.checkpw(_pre_hash_password_unkeyed(password), stored_hash.encode()):
                return True, True
            return False, False
        except ValueError:
            return False, False
    _burn_bcrypt_time()
    matched = hmac.compare_digest(_hash_password_legacy(password), stored_hash)
    return matched, matched

def verify_password(password, stored_hash):
    """Simple matched/not-matched check against whichever hash format
    stored_hash is in - for callers that don't need the upgrade-on-login
    bookkeeping (see _check_password(), used by authenticate_user())."""
    matched, _ = _check_password(password, stored_hash)
    return matched
