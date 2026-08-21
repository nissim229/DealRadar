"""
database_auth.py
Core account lifecycle - register/authenticate, theme preference,
credit deduction/purchase, plan upgrades - split out of database.py
(Section 5 monolith-split plan). The single most security-critical
module in this split: authenticate_user() is every login this app
ever does. Calls database.hash_password()/database._check_password()/
database._burn_bcrypt_time()/database._generate_account_id()/
database._combine_name() (all re-exported into database.py from
earlier steps) rather than bare names, and imports PLAN_ORDER directly
from plan_limits (a static list, never monkeypatched in tests, unlike
DB_NAME/PASSWORD_PEPPER) rather than through the database module.

Re-exported by database.py so db.register_user(...)/
db.authenticate_user(...) etc. keep working unchanged - this is the
one module tests/test_auth.py exercises most directly.
"""
import sqlite3

import database
from plan_limits import PLAN_ORDER


def register_user(email, password, first_name="", middle_name="", last_name=""):
    """Creates a new account. Returns the new user's id on success, or None
    if the email is already taken (returning the id, not just True/False,
    lets the caller immediately pre-seed a first saved search for
    the new account without a second lookup). Generates a unique account_id
    and keeps the legacy `name` column in sync as the concatenation of the
    name parts - see the account_id/first_name migration note in init_db()."""
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        account_id = database._generate_account_id(cursor)
        cursor.execute(
            "INSERT INTO users (email, password_hash, role, credits, name, first_name, middle_name, last_name, account_id, created_at) "
            "VALUES (?, ?, 'user', 3, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
            (email, database.hash_password(password), database._combine_name(first_name, middle_name, last_name),
             first_name.strip(), middle_name.strip(), last_name.strip(), account_id)
        )
        conn.commit()
        return cursor.lastrowid
    except sqlite3.IntegrityError:
        return None
    finally:
        conn.close()

def authenticate_user(email, password):
    """Returns the user record dict on success, {"suspended": True} if the
    credentials are correct but the account has been suspended by an admin
    (so the login screen can show that specifically, instead of a generic
    "incorrect password" that would be actively misleading here), or None
    if the credentials themselves are wrong."""
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, role, credits, theme_preference, name, is_suspended, plan, password_hash FROM users WHERE email=?",
            (email,)
        )
        row = cursor.fetchone()
        if not row:
            # Burn the same CPU time a real check would, so a network
            # observer can't use response latency alone to learn that this
            # email doesn't have an account at all.
            database._burn_bcrypt_time()
            return None
        matched, needs_upgrade = database._check_password(password, row[7])
        if not matched:
            return None
        # A correct password against anything less than the current best
        # format (legacy SHA-256, the brief unkeyed-bcrypt transitional
        # scheme, or an outdated cost factor) means this account hasn't
        # logged in since that format was retired - upgrade its stored hash
        # right here, transparently, instead of a separate forced reset for
        # every existing user. See database.hash_password()/database._check_password() for
        # the full migration design. Never let a failed opportunistic
        # rewrite block an otherwise-successful login.
        if needs_upgrade:
            try:
                cursor.execute("UPDATE users SET password_hash=? WHERE id=?", (database.hash_password(password), int(row[0])))
                conn.commit()
            except sqlite3.Error:
                pass
        if row[5]:
            return {"suspended": True}
        return {
            "id": int(row[0]), "role": str(row[1]), "credits": int(row[2]),
            "theme_preference": str(row[3]) if row[3] else "light",
            "name": str(row[4]) if row[4] else "",
            "plan": str(row[6]) if row[6] else "Free",
        }
    finally:
        conn.close()

def update_user_theme_preference(user_id, mode):
    """Saves the user's chosen theme mode ('light', 'dark', or 'auto') so it
    persists across logins instead of resetting every session."""
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET theme_preference=? WHERE id=?", (mode, int(user_id)))
        conn.commit()
    finally:
        conn.close()

def deduct_credit(user_id):
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET credits = MAX(0, credits - 1) WHERE id=?", (int(user_id),))
        conn.commit()
    finally:
        conn.close()

def add_purchased_credits(user_id, amount):
    """Adds credits from a (currently simulated - no real payment processor
    is wired up yet) package purchase. Kept separate from
    update_user_credits_admin, which sets an absolute value for admin use -
    this always adds relative to whatever the user already has."""
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET credits = credits + ? WHERE id=?", (int(amount), int(user_id)))
        conn.commit()
    finally:
        conn.close()

def update_user_plan(user_id, new_plan):
    """Upgrades a user's plan tier - called alongside add_purchased_credits
    when a package purchase should also raise the matching plan's resource
    caps (see plan_limits.py). Upgrade-only and a no-op if the user is
    already on an equal-or-higher tier, so re-buying a lower package after
    already upgrading can't accidentally downgrade them."""
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT plan FROM users WHERE id=?", (int(user_id),))
        row = cursor.fetchone()
        current = row[0] if row and row[0] else "Free"
        if new_plan in PLAN_ORDER and PLAN_ORDER.index(new_plan) > PLAN_ORDER.index(current):
            cursor.execute("UPDATE users SET plan=? WHERE id=?", (new_plan, int(user_id)))
            conn.commit()
    finally:
        conn.close()
