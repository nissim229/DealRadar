"""
tests/test_security_paths.py
Regression tests for security-critical self-service account paths -
reviewer-flagged as the next tier of coverage after the pure functions:
password change/reset, the Google OAuth CSRF state token, and credit
deduction. Uses the shared temp_db fixture from conftest.py - never
touches the production agent_config.db.
"""
import sqlite3
import time

import pytest

import database as db
import google_oauth
from conftest import _insert_user


def _get_credits(db_path, user_id):
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT credits FROM users WHERE id=?", (user_id,))
        return cur.fetchone()[0]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# database_profile.py: change_own_password
# ---------------------------------------------------------------------------

def test_change_own_password_succeeds_with_correct_current_password(temp_db):
    user_id = _insert_user(temp_db, "alice@example.com", db.hash_password("OldPass1!"))
    assert db.change_own_password(user_id, "OldPass1!", "NewPass2!") is True
    assert db.authenticate_user("alice@example.com", "NewPass2!") is not None
    assert db.authenticate_user("alice@example.com", "OldPass1!") is None


def test_change_own_password_rejects_wrong_current_password(temp_db):
    """The current-password check is the identity check here (the user is
    already authenticated, but changing a password is still sensitive) -
    a wrong current password must refuse the change AND leave the old
    password fully working, not partially update anything."""
    user_id = _insert_user(temp_db, "bob@example.com", db.hash_password("OldPass1!"))
    assert db.change_own_password(user_id, "WrongPassword!", "NewPass2!") is False
    assert db.authenticate_user("bob@example.com", "OldPass1!") is not None
    assert db.authenticate_user("bob@example.com", "NewPass2!") is None


# ---------------------------------------------------------------------------
# database_profile.py: password-reset token lifecycle
# ---------------------------------------------------------------------------

def test_reset_token_full_lifecycle(temp_db):
    """The complete happy path: a fresh token validates to the right user,
    resetting the password with it succeeds and actually changes the
    password, and - critically - the same token cannot be used a second
    time (single-use enforcement, checked all in one flow so a bug that
    only breaks the *second* use in sequence would fail this test)."""
    user_id = _insert_user(temp_db, "carol@example.com", db.hash_password("OldPass1!"))
    token = db.create_password_reset_token(user_id)

    assert db.validate_reset_token(token) == user_id
    assert db.reset_password_with_token(token, "BrandNewPass3!") is True
    assert db.authenticate_user("carol@example.com", "BrandNewPass3!") is not None
    assert db.authenticate_user("carol@example.com", "OldPass1!") is None

    # Same token again - must now be rejected as already-used.
    assert db.validate_reset_token(token) is None
    assert db.reset_password_with_token(token, "SomeOtherPass4!") is False
    # Password must still be the one set by the first (successful) reset.
    assert db.authenticate_user("carol@example.com", "BrandNewPass3!") is not None


def test_expired_reset_token_is_rejected(temp_db):
    user_id = _insert_user(temp_db, "dave@example.com", db.hash_password("OldPass1!"))
    token = db.create_password_reset_token(user_id, valid_minutes=-1)  # already expired
    assert db.validate_reset_token(token) is None
    assert db.reset_password_with_token(token, "NewPass2!") is False
    assert db.authenticate_user("dave@example.com", "OldPass1!") is not None


def test_nonexistent_reset_token_is_rejected(temp_db):
    assert db.validate_reset_token("this-token-was-never-issued") is None
    assert db.reset_password_with_token("this-token-was-never-issued", "NewPass2!") is False


# ---------------------------------------------------------------------------
# google_oauth.py: generate_state / verify_state (CSRF token round trip)
# ---------------------------------------------------------------------------

def test_state_round_trips_for_both_modes():
    """No server-side state to lose (see generate_state's own docstring on
    why - Streamlit resets session_state across the OAuth redirect round
    trip), so the mode must survive purely inside the signed token."""
    assert google_oauth.verify_state(google_oauth.generate_state("signin")) == "signin"
    assert google_oauth.verify_state(google_oauth.generate_state("register")) == "register"


def test_state_defaults_to_signin_for_invalid_mode():
    state = google_oauth.generate_state("not-a-real-mode")
    assert google_oauth.verify_state(state) == "signin"


def test_tampered_state_is_rejected():
    """Flipping a single character in the signed payload must invalidate
    the signature - this is the actual CSRF protection, so a tamper that
    slips through would be a real forgery vector, not just a cosmetic
    bug."""
    state = google_oauth.generate_state("signin")
    tampered = state[:-1] + ("0" if state[-1] != "0" else "1")
    assert google_oauth.verify_state(tampered) is None


def test_expired_state_is_rejected(monkeypatch):
    """Forces the age check itself (rather than sleeping in real time) by
    shrinking the max-age window to something already in the past by the
    time verify_state runs."""
    state = google_oauth.generate_state("signin")
    monkeypatch.setattr(google_oauth, "STATE_MAX_AGE_SECONDS", -1)
    assert google_oauth.verify_state(state) is None


def test_malformed_state_is_rejected():
    assert google_oauth.verify_state(None) is None
    assert google_oauth.verify_state("") is None
    assert google_oauth.verify_state("not.enough.dots.here") is None
    assert google_oauth.verify_state("nodotsatall") is None


# ---------------------------------------------------------------------------
# database_auth.py: deduct_credit
# ---------------------------------------------------------------------------

def test_deduct_credit_decrements_by_one(temp_db):
    user_id = _insert_user(temp_db, "erin@example.com", db.hash_password("Pass1!"), credits=3)
    db.deduct_credit(user_id)
    assert _get_credits(temp_db, user_id) == 2


def test_deduct_credit_floors_at_zero(temp_db):
    """MAX(0, credits - 1) in the SQL itself - deducting from a
    zero-credit account must never go negative, since a negative credit
    balance would be a real accounting bug elsewhere (e.g. plan-limit
    checks that assume credits >= 0)."""
    user_id = _insert_user(temp_db, "frank@example.com", db.hash_password("Pass1!"), credits=0)
    db.deduct_credit(user_id)
    assert _get_credits(temp_db, user_id) == 0
