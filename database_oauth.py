"""
database_oauth.py
Google Sign-In user lookup/creation, split out of database.py (Section 5
monolith-split plan). Calls back into database.get_user_by_email() and
database.register_user() rather than local names, since those functions
do not live here (get_user_by_email is in database_profile.py,
register_user is in database_auth.py, both re-exported through the
database.py facade either way) - going through the shared `database`
module keeps this working regardless of extraction order.
"""
import sqlite3
import secrets

import database


def _user_record_by_id(user_id):
    """Shared by get_or_create_google_user and get_google_login_only - both
    need the same authenticate_user()-shaped dict once they've resolved a
    user_id, differing only in whether they're allowed to create one."""
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, role, credits, theme_preference, name, plan FROM users WHERE id=?",
            (user_id,)
        )
        row = cursor.fetchone()
        return {
            "id": int(row[0]), "role": str(row[1]), "credits": int(row[2]),
            "theme_preference": str(row[3]) if row[3] else "light",
            "name": str(row[4]) if row[4] else "",
            "plan": str(row[5]) if row[5] else "Free",
        }
    finally:
        conn.close()

def get_or_create_google_user(email, name=""):
    """Looks up a user by email; if none exists yet, creates one with a
    random unusable password (they'll always authenticate via Google, so
    the local password_hash column is never actually checked for this
    account - it just satisfies the NOT NULL/UNIQUE-adjacent expectations
    the rest of the schema has for every row) and the same 3 free credits
    any new signup gets. Returns the same shape authenticate_user() does on
    success, or {"suspended": True} if an existing account was suspended."""
    existing = database.get_user_by_email(email)
    if existing is None:
        # Google only gives one combined display name, not separate parts -
        # best-effort split on the first space (first word = first name,
        # rest = last name); the user can fix this precisely later via
        # Settings > Account if the split guessed wrong (e.g. multi-word
        # first/last names, suffixes).
        name_parts = name.strip().split(" ", 1)
        first = name_parts[0] if name_parts else ""
        last = name_parts[1] if len(name_parts) > 1 else ""
        user_id = database.register_user(email, secrets.token_urlsafe(32), first, "", last)
    else:
        user_id, is_suspended = existing
        if is_suspended:
            return {"suspended": True}
    return _user_record_by_id(user_id)

def get_google_login_only(email):
    """Like get_or_create_google_user, but never creates an account - used
    when the user picked the Sign In tab, where silently registering them
    would be surprising. Returns the user_record dict for an existing
    active account, {"suspended": True} if suspended, or None if no
    account exists for this email at all (caller shows a "no account
    found, want to register?" recovery view instead of erroring)."""
    existing = database.get_user_by_email(email)
    if existing is None:
        return None
    user_id, is_suspended = existing
    if is_suspended:
        return {"suspended": True}
    return _user_record_by_id(user_id)
