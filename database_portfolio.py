"""
database_portfolio.py
Personal portfolio (owned properties, tenants, uploaded documents),
split out of database.py (Section 5 monolith-split plan). Re-exported
by database.py, including PORTFOLIO_FIELDS/RENTAL_STATUSES/
PORTFOLIO_UPLOADS_DIR - components/portfolio.py reads all three via
db.PORTFOLIO_FIELDS etc., so the facade re-export keeps that working
unchanged. PORTFOLIO_FIELDS's order is positionally load-bearing:
add_portfolio_property/update_portfolio_property build SQL values by
zipping this list against a fields dict, so do not reorder it.

PORTFOLIO_UPLOADS_DIR is computed from this file's own __file__, same
as database.py's DB_NAME/_ENV_PATH - safe here specifically because
this module is a flat sibling in the same directory as database.py,
not a package, so both resolve to the same actual path. database.py'
still runs os.makedirs(PORTFOLIO_UPLOADS_DIR, exist_ok=True) at its own
bottom (same relative position as before), just reading the re-
exported value.
"""
import sqlite3
import os

import database


PORTFOLIO_FIELDS = [
    "address", "property_type", "purchase_price", "purchase_date",
    "current_value_estimate", "mortgage_balance", "mortgage_rate",
    "monthly_mortgage_payment", "hoa_monthly", "insurance_annual",
    "property_tax_annual", "is_rented", "monthly_rent",
    "property_management_monthly", "other_expenses_monthly", "other_expenses_notes",
    "original_loan_amount", "mortgage_start_date", "loan_term_years", "use_mortgage_calculator",
    "rental_status", "num_occupants", "num_keys_given", "move_in_date", "parking_storage_info",
    "lender_name", "loan_officer_name", "lender_phone", "lender_email", "loan_account_number", "monthly_pmi",
    "notes",
]

RENTAL_STATUSES = ["Vacant", "Occupied", "Listed for Rent", "Under Repair", "For Sale"]

# Where uploaded lease/contract files are saved. Local disk, not the DB, since
# SQLite isn't a great fit for storing binary blobs of arbitrary size - this
# folder sits next to the DB file so it's anchored the same script-relative
# way (see database.py's DB_NAME comment) rather than relative to the terminal's
# working directory.
PORTFOLIO_UPLOADS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "portfolio_uploads")

def _sync_is_rented(fields):
    """is_rented (used throughout the existing cash-flow math) stays a plain
    derived flag: True only when rental_status is exactly 'Occupied' - the
    other statuses (Vacant, Listed for Rent, Under Repair, For Sale) don't
    represent live rental income, same as an unrented property today."""
    fields = dict(fields)
    fields["is_rented"] = 1 if fields.get("rental_status") == "Occupied" else 0
    return fields

def add_portfolio_property(user_id, **fields):
    """Adds an owned property to the user's personal portfolio. Only fields
    named in PORTFOLIO_FIELDS are accepted, in a fixed column order, so the
    caller can pass them as kwargs without worrying about SQL column order."""
    fields = _sync_is_rented(fields)
    values = [fields.get(f) for f in PORTFOLIO_FIELDS]
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute(f"""
            INSERT INTO portfolio_properties (user_id, {", ".join(PORTFOLIO_FIELDS)})
            VALUES (?, {", ".join(["?"] * len(PORTFOLIO_FIELDS))})
        """, (int(user_id), *values))
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()

def update_portfolio_property(property_id, user_id, **fields):
    """Updates an owned property, scoped to the owning user so one user can
    never edit another user's portfolio data."""
    fields = _sync_is_rented(fields)
    values = [fields.get(f) for f in PORTFOLIO_FIELDS]
    set_clause = ", ".join(f"{f}=?" for f in PORTFOLIO_FIELDS)
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"UPDATE portfolio_properties SET {set_clause} WHERE id=? AND user_id=?",
            (*values, int(property_id), int(user_id))
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()

def delete_portfolio_property(property_id, user_id):
    """Deletes an owned property, scoped to the owning user, along with its
    tenants and any uploaded documents (both the DB rows and the files on
    disk) - otherwise those would silently orphan."""
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT stored_filename FROM portfolio_documents WHERE property_id=? AND user_id=?", (int(property_id), int(user_id)))
        stored_filenames = [row[0] for row in cursor.fetchall()]
        cursor.execute("DELETE FROM portfolio_documents WHERE property_id=? AND user_id=?", (int(property_id), int(user_id)))
        cursor.execute("DELETE FROM portfolio_tenants WHERE property_id=? AND user_id=?", (int(property_id), int(user_id)))
        cursor.execute("DELETE FROM portfolio_properties WHERE id=? AND user_id=?", (int(property_id), int(user_id)))
        conn.commit()
        deleted = cursor.rowcount > 0
    finally:
        conn.close()
    for stored_filename in stored_filenames:
        try:
            os.remove(os.path.join(PORTFOLIO_UPLOADS_DIR, stored_filename))
        except OSError:
            pass
    return deleted

def get_portfolio_properties(user_id):
    """Fetches all owned properties for a user as dicts (this table has
    enough columns that positional tuple-unpacking elsewhere in this codebase
    would be error-prone), most recently added first."""
    conn = sqlite3.connect(database.DB_NAME)
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT id, {', '.join(PORTFOLIO_FIELDS)} FROM portfolio_properties WHERE user_id=? ORDER BY created_at DESC",
            (int(user_id),)
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()

# --- TENANTS (a property can have more than one, e.g. roommates) ---

def add_tenant(property_id, user_id, name, phone, email, lease_start, lease_end, notes=""):
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO portfolio_tenants (property_id, user_id, name, phone, email, lease_start, lease_end, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (int(property_id), int(user_id), name, phone, email, lease_start, lease_end, notes)
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()

def update_tenant(tenant_id, user_id, name, phone, email, lease_start, lease_end, notes=""):
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE portfolio_tenants SET name=?, phone=?, email=?, lease_start=?, lease_end=?, notes=? WHERE id=? AND user_id=?",
            (name, phone, email, lease_start, lease_end, notes, int(tenant_id), int(user_id))
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()

def delete_tenant(tenant_id, user_id):
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM portfolio_tenants WHERE id=? AND user_id=?", (int(tenant_id), int(user_id)))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()

def get_tenants(property_id, user_id):
    conn = sqlite3.connect(database.DB_NAME)
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, name, phone, email, lease_start, lease_end, notes FROM portfolio_tenants WHERE property_id=? AND user_id=? ORDER BY created_at",
            (int(property_id), int(user_id))
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()

# --- DOCUMENTS (uploaded lease/contract files, one property can have several) ---

def add_document(property_id, user_id, original_filename, stored_filename):
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO portfolio_documents (property_id, user_id, original_filename, stored_filename) VALUES (?, ?, ?, ?)",
            (int(property_id), int(user_id), original_filename, stored_filename)
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()

def get_documents(property_id, user_id):
    conn = sqlite3.connect(database.DB_NAME)
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, original_filename, stored_filename, uploaded_at FROM portfolio_documents WHERE property_id=? AND user_id=? ORDER BY uploaded_at DESC",
            (int(property_id), int(user_id))
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()

def delete_document(document_id, user_id):
    """Deletes a document's DB row and its file on disk, scoped to the
    owning user. Returns True only if a row was actually deleted."""
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT stored_filename FROM portfolio_documents WHERE id=? AND user_id=?", (int(document_id), int(user_id)))
        row = cursor.fetchone()
        if not row:
            return False
        cursor.execute("DELETE FROM portfolio_documents WHERE id=? AND user_id=?", (int(document_id), int(user_id)))
        conn.commit()
        deleted = cursor.rowcount > 0
    finally:
        conn.close()
    if deleted:
        try:
            os.remove(os.path.join(PORTFOLIO_UPLOADS_DIR, row[0]))
        except OSError:
            pass
    return deleted
