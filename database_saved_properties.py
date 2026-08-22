"""
database_saved_properties.py
Saved/favorited properties (with personal notes), split out of
database.py (Section 5 monolith-split plan). Re-exported by
database.py so db.save_property(...) etc. keep working unchanged.
"""
import sqlite3

import database


def save_property(user_id, address, title, price, beds, baths, latitude, longitude):
    """Adds a property to the user's saved/favorites list. Safe to call again
    on an already-saved property - it just updates the cached details."""
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO saved_properties (user_id, address, title, price, beds, baths, latitude, longitude)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, address) DO UPDATE SET
                title=excluded.title, price=excluded.price, beds=excluded.beds,
                baths=excluded.baths, latitude=excluded.latitude, longitude=excluded.longitude
        """, (int(user_id), address, title, int(price), int(beds), float(baths), float(latitude), float(longitude)))
        conn.commit()
    finally:
        conn.close()

def unsave_property(user_id, address):
    """Removes a property from the saved/favorites list."""
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM saved_properties WHERE user_id=? AND address=?", (int(user_id), address))
        conn.commit()
    finally:
        conn.close()

def is_property_saved(user_id, address):
    """Returns True if this address is currently saved for this user."""
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM saved_properties WHERE user_id=? AND address=?", (int(user_id), address))
        return cursor.fetchone() is not None
    finally:
        conn.close()

def update_property_notes(user_id, address, notes):
    """Updates the personal notes text for a saved property."""
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE saved_properties SET notes=? WHERE user_id=? AND address=?", (notes, int(user_id), address))
        conn.commit()
    finally:
        conn.close()

def get_property_notes(user_id, address):
    """Returns the saved notes text for a property, or empty string if none."""
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT notes FROM saved_properties WHERE user_id=? AND address=?", (int(user_id), address))
        row = cursor.fetchone()
        return row[0] if row and row[0] else ""
    finally:
        conn.close()

def get_saved_properties(user_id):
    """Fetches all saved/favorited properties for a user, most recently saved first."""
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT address, title, price, beds, baths, latitude, longitude, notes, saved_at, last_price_checked_at
            FROM saved_properties WHERE user_id=? ORDER BY saved_at DESC
        """, (int(user_id),))
        return cursor.fetchall()
    finally:
        conn.close()

def get_saved_property_check_info(user_id, address):
    """Returns (price, last_price_checked_at) for one saved property, or
    None if this address isn't currently saved by this user - used by the
    property detail dialog's Price Check tab (added when Check Now moved
    there from its old inline spot on the Saved Properties grid) to show
    freshness without needing the caller to already have the full saved
    list in hand."""
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT price, last_price_checked_at FROM saved_properties WHERE user_id=? AND address=?", (int(user_id), address))
        return cursor.fetchone()
    finally:
        conn.close()

def record_price_check(user_id, address, new_price):
    """Records the result of a manual 'Check Now' price check: always
    overwrites `price` with the fresh read (see the last_price_checked_at
    migration's comment in database_schema.py for why there's no separate
    'last known price' column) and stamps last_price_checked_at. Returns
    the PRIOR price so the caller can tell whether this was actually a
    drop worth alerting on, without a second round-trip."""
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT price FROM saved_properties WHERE user_id=? AND address=?", (int(user_id), address))
        row = cursor.fetchone()
        if not row:
            return None
        old_price = row[0]
        cursor.execute(
            "UPDATE saved_properties SET price=?, last_price_checked_at=CURRENT_TIMESTAMP WHERE user_id=? AND address=?",
            (int(new_price), int(user_id), address)
        )
        conn.commit()
        return old_price
    finally:
        conn.close()

def record_price_check_not_found(user_id, address):
    """Stamps last_price_checked_at (only) when a 'Check Now' click spent a
    real API call but the address wasn't found among current listings -
    reviewer-flagged UX asymmetry (Entry 14/Round 5): without this, a
    'not found' result left last_price_checked_at NULL forever even though
    a real check WAS performed, so the UI kept saying 'Price not manually
    checked yet' as if nothing had happened. price is deliberately left
    untouched - there's no fresh number to record."""
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE saved_properties SET last_price_checked_at=CURRENT_TIMESTAMP WHERE user_id=? AND address=?",
            (int(user_id), address)
        )
        conn.commit()
    finally:
        conn.close()

def count_saved_properties(user_id):
    """Used by the saved-properties plan-limit gate - cheaper than fetching
    every saved property just to call len() on it."""
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM saved_properties WHERE user_id=?", (int(user_id),))
        return cursor.fetchone()[0]
    finally:
        conn.close()
