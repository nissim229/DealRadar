"""
tests/conftest.py
Shared pytest fixtures/helpers for every test file under tests/ - pulled
out of test_auth.py (which had the only copy) so new test files don't
duplicate the same temp-DB setup. See test_auth.py's own docstring for
the ground rules this fixture exists to enforce (never touch the
production agent_config.db, never regenerate PASSWORD_PEPPER).
"""
import sqlite3

import pytest

import database as db


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
        return cur.lastrowid
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
