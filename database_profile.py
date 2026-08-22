"""
database_profile.py
Self-service account identity: own-profile view/edit, change-own-
password, and email-verified password reset tokens - split out of
database.py (Section 5 monolith-split plan). Re-exported by
database.py so every db.get_own_profile(...)/db.get_user_by_email(...)
etc. call site keeps working unchanged.

Note: update_user_plan_admin/update_user_role_admin/admin_reset_password
sit physically between these functions in the original file but are
admin-side actions, not self-service ones - they move to
database_admin.py in a later step, not here.
"""
import sqlite3
import secrets
from datetime import datetime, timedelta, timezone

import database


def get_own_profile(user_id):
    """First/middle/last name, email/phone/address, and the read-only
    account_id for the Settings page's Account section - deliberately
    nothing payment-related here (see update_own_profile). Legacy accounts
    (created before first/middle/last existed) have empty structured-name
    columns even though their old combined `name` is set - best-effort
    split that legacy name into first/last here rather than returning
    blanks, since update_own_profile rebuilds `name` from these three
    fields and would otherwise silently blank a real name on save."""
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT first_name, middle_name, last_name, email, phone, address, account_id, name FROM users WHERE id=?", (int(user_id),))
        row = cursor.fetchone()
        if not row:
            return None
        first_name, middle_name, last_name, legacy_name = row[0] or "", row[1] or "", row[2] or "", row[7] or ""
        if not (first_name or last_name) and legacy_name:
            legacy_parts = legacy_name.strip().split(" ", 1)
            first_name = legacy_parts[0]
            last_name = legacy_parts[1] if len(legacy_parts) > 1 else ""
        return {
            "first_name": first_name, "middle_name": middle_name, "last_name": last_name,
            "email": row[3] or "", "phone": row[4] or "", "address": row[5] or "", "account_id": row[6] or "",
        }
    finally:
        conn.close()

def update_own_profile(user_id, first_name, middle_name, last_name, email, phone, address, current_password=None):
    """Self-service profile edit for a logged-in user. Email doubles as the
    login credential, so changing it specifically requires re-entering and
    verifying the current password (name fields/phone/address alone don't -
    that would be needless friction for fixing a typo). Also keeps the
    legacy single `name` column in sync as the concatenation of the parts,
    same as register_user(). Returns {"success": bool, "error": str|None}.

    Deliberately no card/payment fields on this table or in this function -
    storing raw card data yourself is a real PCI-DSS liability, not just an
    unbuilt feature. When billing is added, only a processor-issued token/
    customer id belongs here, never a card number - see the Settings
    Account section's billing note."""
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT email, password_hash FROM users WHERE id=?", (int(user_id),))
        row = cursor.fetchone()
        if not row:
            return {"success": False, "error": "Account not found."}
        current_email, password_hash = row
        if email != current_email:
            if not current_password or not database.verify_password(current_password, password_hash):
                return {"success": False, "error": "Enter your current password to change your email."}
        cursor.execute(
            "UPDATE users SET name=?, first_name=?, middle_name=?, last_name=?, email=?, phone=?, address=? WHERE id=?",
            (database._combine_name(first_name, middle_name, last_name), first_name.strip(), middle_name.strip(), last_name.strip(),
             email, phone, address, int(user_id))
        )
        conn.commit()
        return {"success": True, "error": None}
    except sqlite3.IntegrityError:
        return {"success": False, "error": "That email is already in use by another account."}
    finally:
        conn.close()

def change_own_password(user_id, current_password, new_password):
    """Self-service password change for a logged-in user - verifies their
    current password first (that's the identity check here, since they're
    already authenticated but this is still a sensitive action), then
    updates it. Returns True on success, False if current_password didn't
    match."""
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT password_hash FROM users WHERE id=?", (int(user_id),))
        row = cursor.fetchone()
        if not row or not database.verify_password(current_password, row[0]):
            return False
        cursor.execute("UPDATE users SET password_hash=? WHERE id=?", (database.hash_password(new_password), int(user_id)))
        conn.commit()
        return True
    finally:
        conn.close()

# --- SELF-SERVICE PASSWORD RESET (email-verified, no login required) ---

def get_user_by_email(email):
    """Returns (id, is_suspended) for an account with this email, or None.
    Used by the forgot-password flow - deliberately returns nothing more
    than what's needed to decide whether to issue a reset token."""
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, is_suspended FROM users WHERE email=?", (email,))
        row = cursor.fetchone()
        return (int(row[0]), bool(row[1])) if row else None
    finally:
        conn.close()

def create_password_reset_token(user_id, valid_minutes=60):
    """Issues a fresh single-use reset token for a user, expiring in
    valid_minutes. Doesn't invalidate older unused tokens for the same user -
    validate_reset_token below only cares whether the specific token
    presented is itself valid and unused, so an old emailed link simply
    stops mattering once its own expiry passes."""
    token = secrets.token_urlsafe(32)
    # .replace(tzinfo=None) keeps this the same naive-UTC value utcnow()
    # used to produce (datetime.utcnow() is deprecated in 3.12+) - expires_at
    # is stored as a plain string and compared against strptime()'s own
    # naive result in validate_reset_token below, so switching to an aware
    # datetime here without stripping tzinfo would raise a naive/aware
    # comparison TypeError there instead of just fixing a warning.
    expires_at = (datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=valid_minutes)).strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO password_reset_tokens (user_id, token, expires_at) VALUES (?, ?, ?)",
            (int(user_id), token, expires_at)
        )
        conn.commit()
        return token
    finally:
        conn.close()

def validate_reset_token(token):
    """Returns the user_id for a token that exists, hasn't been used, and
    hasn't expired - or None otherwise. Doesn't distinguish *why* a token is
    invalid (expired vs. used vs. never existed) in its return value, since
    the caller should show the same generic "this link is no longer valid"
    message regardless - narrower error messages here would just help someone
    probe which tokens exist."""
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT user_id, expires_at, used FROM password_reset_tokens WHERE token=?",
            (token,)
        )
        row = cursor.fetchone()
        if not row:
            return None
        user_id, expires_at, used = row
        if used:
            return None
        if datetime.now(timezone.utc).replace(tzinfo=None) > datetime.strptime(expires_at, "%Y-%m-%d %H:%M:%S"):
            return None
        return int(user_id)
    finally:
        conn.close()

def reset_password_with_token(token, new_password):
    """Validates the token, updates the password, and marks the token used -
    all in one call so there's no window where a token is confirmed valid
    but not yet consumed. Returns True on success."""
    user_id = validate_reset_token(token)
    if user_id is None:
        return False
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET password_hash=? WHERE id=?", (database.hash_password(new_password), user_id))
        cursor.execute("UPDATE password_reset_tokens SET used=1 WHERE token=?", (token,))
        conn.commit()
        return True
    finally:
        conn.close()
