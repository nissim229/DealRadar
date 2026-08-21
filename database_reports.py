"""
database_reports.py
Saved-search reports (save/list/delete), split out of database.py
(Section 5 monolith-split plan). Re-exported by database.py so
db.save_report_config(...) etc. keep working unchanged. The 6
geocode-caching functions that used to sit physically between
save_report_config and get_all_reports/delete_report_config moved to
database_geocache.py instead - a genuinely different domain that was
just interleaved here by proximity, not by relation.
"""
import sqlite3

import database


def save_report_config(user_id, name, loc, price, beds, p_type, email, s_time,
                        state=None, cities_json=None, zip_code=None, category=None,
                        car_make=None, car_model=None, car_min_year=None, car_max_mileage=None, car_trim=None, car_max_year=None, car_fuel_type=None):
    """`state`/`cities_json`/`zip_code` are the new structured location
    picker's fields (see location_data.py); left as None for callers that
    still only have a free-text location string (e.g. the legacy path, or
    the quick "My First Search" seeded at registration), so those rows stay
    correctly detectable as "legacy" (NULL state) by the scan handler.

    `category` is None/"real_estate" for every search created before the
    cars category existed, or "cars" for one built from the car-criteria
    form - car_* fields are only ever set together with category="cars";
    property_type/min_beds stay whatever the caller passes (car searches
    pass p_type=None, beds=0) since they're meaningless for that category.

    price/car_max_mileage may be None - "Any price"/"Any mileage" picked on
    the car search form, a real, intentional "no cap" rather than a
    missing value. max_price has no NOT NULL constraint, so this persists
    as a real NULL, not a fake numeric sentinel."""
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO reports (user_id, profile_name, location, max_price, min_beds, property_type, recipient_email, schedule_time, state, cities_json, zip_code, category, car_make, car_model, car_min_year, car_max_mileage, car_trim, car_max_year, car_fuel_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (int(user_id), name, loc, int(price) if price is not None else None, int(beds), p_type, email, s_time,
              state, cities_json, zip_code, category, car_make, car_model, car_min_year, car_max_mileage, car_trim, car_max_year, car_fuel_type))
        conn.commit()
    finally:
        conn.close()

def get_all_reports(user_id, category=None):
    """category=None (the default) returns every saved search regardless of
    type - used by the duplicate-profile-name check on save, since the
    UNIQUE(user_id, profile_name) constraint applies across categories, not
    within one. Pass category="real_estate" or "cars" to scope the
    top-nav-driven dashboard/hunt-criteria pages to just that type - a
    legacy or real-estate row has category NULL, so "real_estate" matches
    both NULL and the literal string."""
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        if category is None:
            cursor.execute("SELECT profile_name FROM reports WHERE user_id=?", (int(user_id),))
        elif category == "real_estate":
            cursor.execute(
                "SELECT profile_name FROM reports WHERE user_id=? AND (category IS NULL OR category='real_estate')",
                (int(user_id),)
            )
        else:
            cursor.execute("SELECT profile_name FROM reports WHERE user_id=? AND category=?", (int(user_id), category))
        return [row[0] for row in cursor.fetchall()]
    finally:
        conn.close()

def delete_report_config(user_id, name):
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM reports WHERE user_id=? AND profile_name=?", (int(user_id), name))
        conn.commit()
    finally:
        conn.close()
