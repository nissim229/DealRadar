"""
database_shared.py
_generate_account_id and _combine_name, split out of database.py (Section 5
monolith-split plan). These two are used across multiple domains (schema
seeding, register_user, admin profile edit, self-service profile edit,
Google/staff creation) so they get a shared home rather than travelling
with any single domain module. Neither depends on DB_NAME/PASSWORD_PEPPER -
_generate_account_id takes an already-open cursor, _combine_name is pure -
so there's no circular-import concern here, unlike database_crypto.py.
"""
import secrets


def _generate_account_id(cursor):
    """Generates a short, unique, non-sequential public-facing account ID
    (e.g. "DR-8F3A9C2B") - see the users.account_id migration note in
    init_db() for why this isn't just the internal auto-increment id.
    Takes an existing cursor (used both from init_db()'s own connection
    during backfill, and from register_user()'s) so the uniqueness check
    happens inside the caller's own transaction. Retries on the
    astronomically unlikely event of a collision (8 hex chars = 4+ billion
    possibilities)."""
    while True:
        candidate = "DR-" + secrets.token_hex(4).upper()
        cursor.execute("SELECT 1 FROM users WHERE account_id=?", (candidate,))
        if not cursor.fetchone():
            return candidate


def _combine_name(first_name, middle_name, last_name):
    return " ".join(p.strip() for p in [first_name, middle_name, last_name] if p and p.strip())
