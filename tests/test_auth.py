"""Regression tests for database.py's password hashing and authentication.

Ground rules (see FIXLIST.md):
- Never touch the production agent_config.db - every test that needs a
  database gets its own fresh temp file via the temp_db fixture, built with
  init_db() rather than a copy of any real data.
- Never regenerate or overwrite PASSWORD_PEPPER in the real .env - tests
  that need a specific/different pepper monkeypatch database.PASSWORD_PEPPER
  directly instead of touching any file.
"""
import hashlib
import os
import subprocess
import sys
import sqlite3
import tempfile
import time

import bcrypt as bcrypt_lib
import pytest

import database as db

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def temp_db(monkeypatch, tmp_path):
    """tmp_path is pytest's own built-in fixture (a unique pathlib.Path per
    test, cleaned up per pytest's retention policy) - preferred over
    tempfile.mktemp(), which only reserves a filename without creating it
    and is documented as race-prone for exactly that reason."""
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr(db, "DB_NAME", db_path)
    db.init_db()
    yield db_path


def _insert_user(db_path, email, password_hash, role="user", credits=3, suspended=0):
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        account_id = db._generate_account_id(cur)
        cur.execute(
            "INSERT INTO users (email, password_hash, role, credits, account_id, is_suspended, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
            (email, password_hash, role, credits, account_id, suspended),
        )
        conn.commit()
    finally:
        conn.close()


def _get_hash(db_path, email):
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT password_hash FROM users WHERE email=?", (email,))
        row = cur.fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def test_wrong_password_rejected_on_bcrypt_account(temp_db):
    _insert_user(temp_db, "alice@example.com", db.hash_password("CorrectHorse1!"))
    assert db.authenticate_user("alice@example.com", "wrongpassword") is None


def test_correct_password_on_bcrypt_account_succeeds(temp_db):
    _insert_user(temp_db, "alice@example.com", db.hash_password("CorrectHorse1!"))
    result = db.authenticate_user("alice@example.com", "CorrectHorse1!")
    assert result is not None
    assert result["role"] == "user"


def test_legacy_sha256_hash_migrates_on_login(temp_db):
    legacy_hash = hashlib.sha256("OldPassw0rd!".encode()).hexdigest()
    _insert_user(temp_db, "legacy@example.com", legacy_hash)

    assert db.authenticate_user("legacy@example.com", "OldPassw0rd!") is not None

    upgraded_hash = _get_hash(temp_db, "legacy@example.com")
    assert db._is_bcrypt_hash(upgraded_hash)
    assert upgraded_hash != legacy_hash

    # Second login must not rewrite the hash again.
    assert db.authenticate_user("legacy@example.com", "OldPassw0rd!") is not None
    assert _get_hash(temp_db, "legacy@example.com") == upgraded_hash


def test_transitional_unkeyed_bcrypt_hash_recognized_and_upgraded(temp_db):
    """The brief bcrypt-over-bare-SHA256-digest scheme this app used before
    PASSWORD_PEPPER existed - must still verify and get upgraded, since a
    real account (testclient@dealradar.local) was actually migrated to
    exactly this format live before the pepper was introduced."""
    transitional_hash = bcrypt_lib.hashpw(
        hashlib.sha256("testpass123".encode()).digest(),
        bcrypt_lib.gensalt(rounds=12),
    ).decode()
    _insert_user(temp_db, "transitional@example.com", transitional_hash)

    assert db.authenticate_user("transitional@example.com", "testpass123") is not None

    upgraded_hash = _get_hash(temp_db, "transitional@example.com")
    assert upgraded_hash != transitional_hash
    assert db._is_bcrypt_hash(upgraded_hash)

    assert db.authenticate_user("transitional@example.com", "testpass123") is not None
    assert _get_hash(temp_db, "transitional@example.com") == upgraded_hash


def test_low_cost_bcrypt_hash_upgraded_to_target_cost(temp_db):
    low_cost_hash = bcrypt_lib.hashpw(db._pre_hash_password("LowCostPw1!"), bcrypt_lib.gensalt(rounds=4)).decode()
    _insert_user(temp_db, "lowcost@example.com", low_cost_hash)
    assert db._bcrypt_cost_of(low_cost_hash) == 4

    assert db.authenticate_user("lowcost@example.com", "LowCostPw1!") is not None

    upgraded_hash = _get_hash(temp_db, "lowcost@example.com")
    assert db._bcrypt_cost_of(upgraded_hash) == db.BCRYPT_COST


def test_long_passphrase_roundtrips(temp_db):
    long_pw = "x" * 200 + "!SpecialEnd"
    _insert_user(temp_db, "longpw@example.com", db.hash_password(long_pw))
    assert db.authenticate_user("longpw@example.com", long_pw) is not None
    assert db.authenticate_user("longpw@example.com", "wrong") is None


def test_nonexistent_email_returns_none(temp_db):
    assert db.authenticate_user("nobody@example.com", "whatever") is None


def test_empty_stored_hash_rejected():
    assert db.verify_password("anything", "") is False
    assert db.verify_password("anything", None) is False


def test_pepper_is_load_bearing(monkeypatch):
    """A hash created under one pepper must NOT verify under a different
    one - otherwise the pepper isn't actually providing any protection."""
    monkeypatch.setattr(db, "PASSWORD_PEPPER", b"pepper-A")
    hash_under_a = db.hash_password("SamePassword1!")

    monkeypatch.setattr(db, "PASSWORD_PEPPER", b"pepper-B")
    assert db.verify_password("SamePassword1!", hash_under_a) is False

    monkeypatch.setattr(db, "PASSWORD_PEPPER", b"pepper-A")
    assert db.verify_password("SamePassword1!", hash_under_a) is True


def test_suspended_account_still_returns_suspended_marker(temp_db):
    _insert_user(temp_db, "suspended@example.com", db.hash_password("Passw0rd1!"), suspended=1)
    assert db.authenticate_user("suspended@example.com", "Passw0rd1!") == {"suspended": True}


def test_timing_rough_parity_missing_account_vs_wrong_password(temp_db):
    """Not a precise constant-time guarantee - just checks the dummy-bcrypt
    timing equalizer keeps a missing-account lookup and a wrong-password
    check within roughly the same order of magnitude, so a network
    observer can't trivially distinguish the two from latency alone."""
    _insert_user(temp_db, "real@example.com", db.hash_password("RealPassword1!"))

    t0 = time.time()
    db.authenticate_user("doesnotexist@example.com", "whatever")
    t_missing = time.time() - t0

    t0 = time.time()
    db.authenticate_user("real@example.com", "wrongpassword")
    t_wrong = time.time() - t0

    assert t_missing > 0.02
    assert t_wrong > 0.02
    ratio = max(t_missing, t_wrong) / max(min(t_missing, t_wrong), 0.001)
    assert ratio < 10


def test_pepper_regression_cwd_independent():
    """Import database.py from a completely different working directory,
    in a fresh subprocess (Python caches modules, so a second in-process
    import wouldn't re-run the module-level loading code) with
    PASSWORD_PEPPER stripped from the inherited environment (otherwise the
    child would see it via inheritance regardless of whether the CWD-based
    file lookup actually works, masking a regression). Confirms the
    resolved pepper still matches what's really in .env, and that .env
    itself is byte-for-byte unchanged - the exact bug fixed in 5aa927f."""
    env_path = os.path.join(PROJECT_ROOT, ".env")
    with open(env_path, "r", encoding="utf-8") as f:
        before = f.read()

    expected_fingerprint = hashlib.sha256(db.PASSWORD_PEPPER).hexdigest()[:16]

    elsewhere = tempfile.mkdtemp()
    script = (
        "import sys, hashlib\n"
        "sys.path.insert(0, r'%s')\n"
        "import database as db\n"
        "print(hashlib.sha256(db.PASSWORD_PEPPER).hexdigest()[:16])\n"
    ) % PROJECT_ROOT

    clean_env = {k: v for k, v in os.environ.items() if k != "PASSWORD_PEPPER"}
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=elsewhere,
        capture_output=True,
        text=True,
        timeout=30,
        env=clean_env,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == expected_fingerprint, (
        "PASSWORD_PEPPER resolved to a DIFFERENT value when database.py was "
        "imported from an unrelated working directory - the CWD-independent "
        "pepper loading fix has regressed."
    )

    with open(env_path, "r", encoding="utf-8") as f:
        after = f.read()
    assert before == after, ".env was modified merely by importing database.py from another CWD"


def test_login_succeeds_even_if_hash_upgrade_write_fails(temp_db, monkeypatch):
    """The opportunistic hash-upgrade write in authenticate_user() (commit
    82828c2) is wrapped in try/except sqlite3.Error specifically so a
    failed write can never turn an otherwise-correct login into a failure.
    Forces that one UPDATE to raise and confirms the login still succeeds
    - and that the failure was real (the hash stays un-upgraded), not just
    an inert patch that never got exercised.

    sqlite3.Cursor/Connection are immutable C types (can't monkeypatch
    their methods directly), so this wraps sqlite3.connect() itself with
    thin proxy objects that intercept only the one UPDATE statement and
    forward everything else untouched."""
    legacy_hash = hashlib.sha256("UpgradeMeSoon1!".encode()).hexdigest()
    _insert_user(temp_db, "upgrade-fail@example.com", legacy_hash)

    real_connect = sqlite3.connect

    class _FlakyCursor:
        def __init__(self, real_cursor):
            self._real = real_cursor

        def execute(self, sql, params=()):
            if isinstance(sql, str) and sql.strip().startswith("UPDATE users SET password_hash"):
                raise sqlite3.OperationalError("simulated failure for this test")
            return self._real.execute(sql, params)

        def __getattr__(self, name):
            return getattr(self._real, name)

    class _FlakyConnection:
        def __init__(self, real_conn):
            self._real = real_conn

        def cursor(self):
            return _FlakyCursor(self._real.cursor())

        def __getattr__(self, name):
            return getattr(self._real, name)

    def flaky_connect(*args, **kwargs):
        return _FlakyConnection(real_connect(*args, **kwargs))

    with monkeypatch.context() as m:
        m.setattr(sqlite3, "connect", flaky_connect)
        result = db.authenticate_user("upgrade-fail@example.com", "UpgradeMeSoon1!")

    assert result is not None

    assert _get_hash(temp_db, "upgrade-fail@example.com") == legacy_hash, (
        "hash was upgraded despite the UPDATE being forced to fail - the "
        "patch didn't actually exercise the failure path this test targets"
    )
