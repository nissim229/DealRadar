"""
database_geocache.py
Geocode caching (cities, car dealers, RentCast area listings), split
out of database.py (Section 5 monolith-split plan). Was previously
physically sandwiched between save_report_config and get_all_reports/
delete_report_config (a genuinely different domain, un-interleaved by
this same split - see database_reports.py). Re-exported by database.py
so db.get_cached_city_coords(...) etc. keep working unchanged.
"""
import sqlite3
import json

import database


def get_cached_city_coords(city, state):
    """Returns (lat, lon) for a previously-geocoded city/state pair, or
    None if it hasn't been resolved yet - callers geocode and store via
    cache_city_coords() on a miss, so a given city is only ever geocoded
    once across the whole app's lifetime."""
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT lat, lon FROM city_coords_cache WHERE city=? AND state=?", (city, state))
        row = cursor.fetchone()
        return (row[0], row[1]) if row else None
    finally:
        conn.close()

def get_cached_dealer_coords(dealer_name, city, state):
    """Returns (lat, lon) for a previously-geocoded dealer, or None on a
    miss - same idea as get_cached_city_coords, keyed on the (dealer_name,
    city, state) triple since a dealer name alone isn't unique (many
    "CarMax" locations) but the combination is what Google Places was
    actually asked to resolve."""
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT lat, lon FROM dealer_coords_cache WHERE dealer_name=? AND city=? AND state=?",
            (dealer_name, city, state)
        )
        row = cursor.fetchone()
        return (row[0], row[1]) if row else None
    finally:
        conn.close()

def cache_dealer_coords(dealer_name, city, state, lat, lon):
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO dealer_coords_cache (dealer_name, city, state, lat, lon) VALUES (?, ?, ?, ?, ?)",
            (dealer_name, city, state, float(lat), float(lon))
        )
        conn.commit()
    finally:
        conn.close()

def get_cached_rentcast_area(cache_key, max_age_hours=24):
    """Returns the cached raw (unfiltered) RentCast listings for this area
    key if they were fetched within max_age_hours, else None on a cache
    miss or a stale entry - the caller falls back to a real API call either
    way, exactly like get_cached_city_coords above."""
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT listings_json FROM rentcast_area_cache WHERE cache_key=? "
            "AND fetched_at > datetime('now', ?)",
            (cache_key, f"-{int(max_age_hours)} hours")
        )
        row = cursor.fetchone()
        return json.loads(row[0]) if row else None
    finally:
        conn.close()

def save_rentcast_area_cache(cache_key, listings):
    """Upserts this area's raw listings + a fresh fetched_at timestamp -
    the next same-area request within the TTL reads this instead of
    spending another real RentCast call."""
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO rentcast_area_cache (cache_key, listings_json, fetched_at) VALUES (?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(cache_key) DO UPDATE SET listings_json=excluded.listings_json, fetched_at=excluded.fetched_at",
            (cache_key, json.dumps(listings))
        )
        conn.commit()
    finally:
        conn.close()

def cache_city_coords(city, state, lat, lon):
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO city_coords_cache (city, state, lat, lon) VALUES (?, ?, ?, ?)",
            (city, state, float(lat), float(lon))
        )
        conn.commit()
    finally:
        conn.close()
