import sqlite3
import hashlib
import hmac
import base64
import json
import os
import secrets
import bcrypt
from dotenv import load_dotenv
from datetime import datetime, timedelta
from plan_limits import PLAN_ORDER

# Anchor the database file AND the .env file to this script's own directory,
# not the terminal's current working directory. Using a bare relative
# filename for the DB meant launching the app from a slightly different
# folder (or a fresh terminal session) would silently create/read a
# DIFFERENT database file - looking like saved data (profiles, theme
# preference, credits) had been forgotten, when really it was just written
# to a different file each time. A bare load_dotenv() below the DB fix has
# the identical failure mode for .env: it resolves relative to the CALLER's
# working directory/call stack, not this file's location - confirmed live
# that it finds nothing at all when database.py is imported from an
# unrelated directory. That matters a lot more for PASSWORD_PEPPER
# specifically (see _load_or_create_password_pepper()) than it does for the
# other API keys .env holds: a silently-missing pepper doesn't just misuse a
# feature, it triggers self-provisioning a BRAND NEW one, permanently
# breaking every already-bcrypt-hashed password.
DB_NAME = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_config.db")
_ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(_ENV_PATH)

BCRYPT_COST = 12

# Password hashing/verification lives in database_crypto.py (Section 5
# monolith-split - see REVIEW_LOG.md). Re-exported here so every existing
# `import database as db; db.hash_password(...)` call site (and
# tests/test_auth.py's direct db._is_bcrypt_hash/_pre_hash_password/
# _bcrypt_cost_of calls) keeps working unchanged. DB_NAME/_ENV_PATH/
# BCRYPT_COST above and PASSWORD_PEPPER/_TIMING_DUMMY_HASH below
# deliberately stay in THIS file rather than moving to database_crypto.py -
# see that module's own docstring for why.
from database_crypto import (
    _check_for_duplicate_pepper_lines,
    _any_bcrypt_hash_exists,
    _load_or_create_password_pepper,
    _pre_hash_password,
    _pre_hash_password_unkeyed,
    hash_password,
    _hash_password_legacy,
    _is_bcrypt_hash,
    _bcrypt_cost_of,
    _burn_bcrypt_time,
    _check_password,
    verify_password,
)

PASSWORD_PEPPER = _load_or_create_password_pepper()

_TIMING_DUMMY_HASH = bcrypt.hashpw(b"dummy-timing-equalizer", bcrypt.gensalt(rounds=BCRYPT_COST))

# _generate_account_id/_combine_name live in database_shared.py - used
# across multiple domains (schema seed, register_user, admin profile edit,
# Google/staff creation), so they get a shared home instead of travelling
# with one domain module. Re-exported here for the same reason as above.
from database_shared import _generate_account_id, _combine_name


def init_db():
    """Initializes a relational multi-tenant SaaS schema with historical logging."""
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        
        # 1. Users Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE,
                password_hash TEXT,
                role TEXT DEFAULT 'user',
                credits INTEGER DEFAULT 3
            )
        """)

        # Migration: add theme_preference column for existing databases created
        # before this feature existed. SQLite has no "ADD COLUMN IF NOT EXISTS",
        # so this is wrapped to safely no-op if the column already exists.
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN theme_preference TEXT DEFAULT 'light'")
        except sqlite3.OperationalError:
            pass

        # Migration: add name column for existing databases created before
        # registration collected it. Same no-op-if-exists pattern as above.
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN name TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass

        # Migration: add is_suspended column for the admin suspend/reactivate
        # feature. Same no-op-if-exists pattern as above.
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN is_suspended INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass

        # Migration: add plan column (Free/Starter/Pro/Enterprise - see
        # plan_limits.py) gating portfolio properties, saved properties, and
        # saved searches. SQLite backfills existing rows with the column
        # default on ADD COLUMN, so every pre-existing user lands on Free.
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN plan TEXT DEFAULT 'Free'")
        except sqlite3.OperationalError:
            pass

        # Migration: signup timestamp, for the admin dashboard's registered-
        # user growth trend. SQLite refuses a non-constant DEFAULT (like
        # CURRENT_TIMESTAMP) in ADD COLUMN once a table already has rows -
        # add it plain, then backfill. Every pre-existing user's created_at
        # lands on "whenever this migration ran" rather than their real
        # signup date - a known, acceptable imprecision for historical rows,
        # since there was never a signup timestamp to recover in the first
        # place. New rows get their real signup time via register_user().
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN created_at TIMESTAMP")
        except sqlite3.OperationalError:
            pass
        cursor.execute("UPDATE users SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL")

        # Migration: phone and mailing address, for the Settings page's
        # Account section - plain contact info, not tied to any billing
        # integration (deliberately not storing anything payment-related;
        # see update_own_profile's docstring for why).
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN phone TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN address TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass

        # Migration: structured name parts (first/middle/last - middle
        # optional) plus a short, non-sequential public-facing account ID
        # (e.g. "DR-8F3A9C2B"). Deliberately separate from the existing
        # auto-increment `id` column - showing that directly to users would
        # leak total signup count (anyone could compare two account numbers
        # and estimate how many customers exist). No DB-level UNIQUE
        # constraint on account_id (SQLite's ADD COLUMN doesn't reliably
        # support adding one on an existing table across versions, matching
        # this file's existing convention of not retrofitting UNIQUE via
        # ALTER) - uniqueness is enforced in _generate_account_id() instead,
        # which checks for a collision before returning. The old single
        # `name` column stays as-is and is kept auto-in-sync as the
        # concatenation of the parts below, since most of the app (topbar,
        # admin table, dashboard greeting) displays that one field and
        # didn't need a full refactor to structured parts.
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN first_name TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN middle_name TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN last_name TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN account_id TEXT")
        except sqlite3.OperationalError:
            pass

        # Migration: last time this user opened the topbar notification
        # bell, for a real unread count instead of just a "something's
        # here" dot. Deliberately left NULL with no default (not backfilled
        # to CURRENT_TIMESTAMP like created_at above) - NULL correctly
        # means "never opened it", so every existing activity item counts
        # as unread the first time, which is the honest answer.
        try:
            cursor.execute("ALTER TABLE users ADD COLUMN last_notifications_read_at TIMESTAMP")
        except sqlite3.OperationalError:
            pass

        # Backfill: every pre-existing account (created before this feature
        # existed) needs an account_id too, not just new signups.
        cursor.execute("SELECT id FROM users WHERE account_id IS NULL OR account_id=''")
        for (existing_uid,) in cursor.fetchall():
            cursor.execute("UPDATE users SET account_id=? WHERE id=?", (_generate_account_id(cursor), existing_uid))

        # App-wide key/value settings (currently just the admin broadcast
        # banner message) - a single small table rather than one column per
        # setting, so adding future settings doesn't need another migration.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)

        # One row per real RentCast API call attempted (success or failure -
        # RentCast bills per request either way), so usage against the free
        # 50/month tier can be tracked and capped. A log table rather than a
        # single counter, since counting rows in the current calendar month
        # handles the monthly reset automatically with no separate "reset
        # this counter" job to remember to run.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS rentcast_usage_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                called_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                success INTEGER
            )
        """)

        # Migration: which user triggered each real RentCast call - the
        # original table only tracked the global monthly count against the
        # 50/month cap, with no way to see who's actually spending it.
        # NULL on rows logged before this migration (unavoidable - that
        # context was never captured) shows up as "legacy" in the admin
        # per-user breakdown rather than being attributed to the wrong user.
        try:
            cursor.execute("ALTER TABLE rentcast_usage_log ADD COLUMN user_id INTEGER")
        except sqlite3.OperationalError:
            pass

        # Same shape/purpose as rentcast_usage_log above, for the Cars
        # category's real Auto.dev listings API - a separate table (not a
        # shared one with a "provider" column) so each vendor's monthly-cap
        # math stays a simple row count with no filtering to get wrong.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS autodev_usage_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                called_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                success INTEGER,
                user_id INTEGER
            )
        """)

        # Same shape again, for Google Places "Find Place From Text" calls -
        # used to geocode a car dealer's real address by name (see
        # agent_engine.geocode_dealer). Google Places is pay-per-request
        # billing on the user's own Google Cloud account, not a fixed plan
        # like RentCast/Auto.dev - this app has no way to read the real
        # budget/quota from Google's side, so places_config below is a
        # self-declared number the admin sets, tracked against this log the
        # same way. Existing Street View/Nearby-Places calls elsewhere in
        # this app are NOT logged here yet - only the new dealer-geocode
        # call site was in scope when this was added.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS places_usage_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                called_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                success INTEGER,
                user_id INTEGER
            )
        """)

        # Simulated purchase ledger - "Buy Credits" has no real payment
        # processor wired up yet (see components/pricing.py), so this is the
        # paper trail for admin revenue visibility until one exists: every
        # demo "Buy Now" click logs the package, its listed price, and the
        # credits granted. Deliberately NOT written by the admin's own "+5
        # Bonus" goodwill-credit button, so revenue figures only ever
        # reflect (simulated) purchases, not free grants.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS credit_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                package_name TEXT,
                dollar_amount REAL,
                credits_granted INTEGER,
                purchased_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)

        # Migration: which promo code (if any) was applied to a purchase -
        # NULL for every purchase made before promo codes existed, or any
        # full-price purchase after.
        try:
            cursor.execute("ALTER TABLE credit_transactions ADD COLUMN promo_code TEXT")
        except sqlite3.OperationalError:
            pass

        # Admin-editable credit packages - previously hardcoded in
        # plan_limits.py (price/credits/resource caps baked into the code,
        # needing a full deploy to change a single number). Seeded from
        # plan_limits.DEFAULT_PLAN_LIMITS the first time this table is empty
        # (see _seed_credit_packages_if_empty below) so behavior is
        # unchanged until an admin actually edits something. NULL on a
        # resource-cap column means "unlimited" (same convention as
        # plan_limits.py always used).
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS credit_packages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tier_name TEXT UNIQUE,
                price REAL,
                credits INTEGER,
                portfolio_properties INTEGER,
                saved_properties INTEGER,
                saved_searches INTEGER,
                highlight INTEGER DEFAULT 0,
                display_order INTEGER
            )
        """)

        # Admin-created discount codes for the Buy Credits checkout -
        # percent or flat dollar off, optionally capped at N total
        # redemptions and/or an expiry date. max_uses/expires_at NULL means
        # unlimited/no expiry.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS promo_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE,
                discount_type TEXT,
                discount_value REAL,
                max_uses INTEGER,
                times_used INTEGER DEFAULT 0,
                expires_at TIMESTAMP,
                active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # One row per OpenAI report-generation call, mirroring
        # rentcast_usage_log's shape/purpose - unlike RentCast, this had NO
        # cap at all before this table existed (every scan, including
        # anonymous guest previews, called OpenAI unconditionally). The
        # admin-editable monthly limit lives in app_settings
        # ('openai_monthly_limit'); once hit, scans fall back to the
        # existing local mock report generator instead of calling OpenAI.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS openai_usage_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                called_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                user_id INTEGER
            )
        """)

        # Per-user, per-dashboard saved grid layout (grid width + each
        # card's column span) - lets a user resize/arrange their own
        # dashboard cards from the GUI instead of the layout being fixed in
        # code. One JSON blob per (user, dashboard) rather than a row per
        # card: this is small, purely-presentational config, not queryable
        # data, so the flexibility of "whatever shape the layout needs"
        # outweighs normalizing it - same reasoning already used for
        # cities_json/coordinates_json elsewhere in this schema.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS dashboard_layouts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                dashboard_type TEXT,
                layout_json TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, dashboard_type)
            )
        """)

        # Per-user Settings page preferences (timezone, default underwriting
        # assumptions, default scan view/mode, default distance reference
        # point, notification toggles) - one JSON blob per user rather than
        # ~13 individual columns, same reasoning and shape as
        # dashboard_layouts above: this is always read/written as one cohesive
        # object from the Settings page, never filtered/queried piecemeal by
        # SQL elsewhere, so a blob avoids a long run of near-identical
        # ALTER TABLE migrations for very little benefit.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id INTEGER PRIMARY KEY,
                settings_json TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 2. Multi-Tenant Reports (Saved Searches) Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                profile_name TEXT,
                location TEXT,
                max_price INTEGER,
                min_beds INTEGER,
                property_type TEXT,
                recipient_email TEXT,
                schedule_time TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id),
                UNIQUE(user_id, profile_name)
            )
        """)

        # Migration: structured location fields for the state/city hunt-
        # criteria picker, alongside the original free-text `location`
        # column (kept for backward-compat display in report titles/PDF
        # headers/emails). NULL on these three is exactly how a legacy
        # search (saved before this feature) is told apart from a new one.
        for column, col_type in [
            ("state", "TEXT"),
            ("cities_json", "TEXT"),
            ("zip_code", "TEXT"),
        ]:
            try:
                cursor.execute(f"ALTER TABLE reports ADD COLUMN {column} {col_type}")
            except sqlite3.OperationalError:
                pass

        # Migration: category support (real_estate / cars) so DealRadar can
        # scan for deals beyond property listings. NULL/"real_estate" on
        # existing rows is exactly how a pre-category search is told apart
        # from a new one - see roles.py-style NULL-means-legacy pattern used
        # for state/cities_json/zip_code above. The car_* columns are unused
        # (NULL) for real_estate searches and vice versa for property_type/
        # min_beds - one table, category-scoped columns, rather than two
        # separate tables, since every other part of this feature (saved-
        # search limits, the Modify/Decommission grids, scheduling) is
        # already built around "one row per saved search" regardless of type.
        for column, col_type in [
            ("category", "TEXT"),
            ("car_make", "TEXT"),
            ("car_model", "TEXT"),
            ("car_min_year", "INTEGER"),
            ("car_max_mileage", "INTEGER"),
            ("car_trim", "TEXT"),
            ("car_max_year", "INTEGER"),
            ("car_fuel_type", "TEXT"),
        ]:
            try:
                cursor.execute(f"ALTER TABLE reports ADD COLUMN {column} {col_type}")
            except sqlite3.OperationalError:
                pass

        # Caches city/state -> lat/lon lookups from the geocoder so the
        # location picker's map and repeated scans of the same saved search
        # don't re-hit Nominatim every time.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS city_coords_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                city TEXT,
                state TEXT,
                lat REAL,
                lon REAL,
                UNIQUE(city, state)
            )
        """)

        # Same idea as city_coords_cache, for a specific car dealer's
        # geocoded address (dealer_name + city/state - Auto.dev's listings
        # response has no dealer street address of its own, only city/
        # state/zip, but a dealer name + city is enough for Google Places to
        # find the real business - see agent_engine.geocode_dealer). The
        # same dealer shows up across many different searches, so caching
        # here is what keeps repeat lookups free instead of spending the
        # Places budget on the same dealer over and over.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS dealer_coords_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dealer_name TEXT,
                city TEXT,
                state TEXT,
                lat REAL,
                lon REAL,
                UNIQUE(dealer_name, city, state)
            )
        """)

        # Cache-aside store for real RentCast listings, keyed by AREA (rounded
        # lat/lon + property_type + radius), not by any one user's exact
        # price/beds filter - so two different users searching the same city
        # share one RentCast call instead of each spending their own. See
        # [[deferred_rentcast_caching_plan]] for why a 24h TTL loses nothing
        # (RentCast itself only refreshes listings at least once/day).
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS rentcast_area_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cache_key TEXT UNIQUE NOT NULL,
                listings_json TEXT NOT NULL,
                fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 3. UPDATED: Historical Output Log Table with map tracking structures
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS history_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                profile_name TEXT,
                location TEXT,
                generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                report_content TEXT,
                coordinates_json TEXT,  -- Field to store live lat/long strings safely
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)

        # Migration: whether this specific scan pulled real RentCast listings
        # (1) or fell back to mock/preview data (0) - out of credits, no
        # RentCast key configured, an admin Test Scan, etc. Existing rows
        # predating this migration default to 0 (counted as mock) since
        # there's no way to recover which they actually were.
        try:
            cursor.execute("ALTER TABLE history_logs ADD COLUMN was_live INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass

        # Migration: which deal category this scan belongs to, so the
        # real-estate History Log page and the topbar notification feed
        # (which is category-aware, matching the help popover) don't mix
        # property scans and car scans together. 'real_estate' default
        # (a constant, unlike created_at's CURRENT_TIMESTAMP above - safe
        # for ADD COLUMN) correctly reclassifies every pre-Cars-era row.
        try:
            cursor.execute("ALTER TABLE history_logs ADD COLUMN category TEXT DEFAULT 'real_estate'")
        except sqlite3.OperationalError:
            pass

        # 5. Personal Portfolio Table - properties a user actually owns (rentals
        # and/or their own home), entered manually since this is the user's own
        # real financial data, not something to pull from an external API.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS portfolio_properties (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                address TEXT,
                property_type TEXT DEFAULT 'Primary Residence',
                purchase_price REAL DEFAULT 0,
                purchase_date TEXT DEFAULT '',
                current_value_estimate REAL DEFAULT 0,
                mortgage_balance REAL DEFAULT 0,
                mortgage_rate REAL DEFAULT 0,
                monthly_mortgage_payment REAL DEFAULT 0,
                hoa_monthly REAL DEFAULT 0,
                insurance_annual REAL DEFAULT 0,
                property_tax_annual REAL DEFAULT 0,
                is_rented INTEGER DEFAULT 0,
                monthly_rent REAL DEFAULT 0,
                property_management_monthly REAL DEFAULT 0,
                other_expenses_monthly REAL DEFAULT 0,
                other_expenses_notes TEXT DEFAULT '',
                original_loan_amount REAL DEFAULT 0,
                mortgage_start_date TEXT DEFAULT '',
                loan_term_years INTEGER DEFAULT 30,
                use_mortgage_calculator INTEGER DEFAULT 0,
                rental_status TEXT DEFAULT 'Vacant',
                num_occupants INTEGER DEFAULT 0,
                num_keys_given INTEGER DEFAULT 0,
                move_in_date TEXT DEFAULT '',
                parking_storage_info TEXT DEFAULT '',
                lender_name TEXT DEFAULT '',
                loan_officer_name TEXT DEFAULT '',
                lender_phone TEXT DEFAULT '',
                lender_email TEXT DEFAULT '',
                loan_account_number TEXT DEFAULT '',
                monthly_pmi REAL DEFAULT 0,
                notes TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)

        # Migration: add property-management, catch-all "other expenses",
        # mortgage-amortization-calculator, status/occupancy, and lender
        # contact / PMI columns for portfolio_properties tables created
        # before these fields existed. Same no-op-if-exists pattern as the
        # users-table migrations.
        for column, col_type in [
            ("property_management_monthly", "REAL DEFAULT 0"),
            ("other_expenses_monthly", "REAL DEFAULT 0"),
            ("other_expenses_notes", "TEXT DEFAULT ''"),
            ("original_loan_amount", "REAL DEFAULT 0"),
            ("mortgage_start_date", "TEXT DEFAULT ''"),
            ("loan_term_years", "INTEGER DEFAULT 30"),
            ("use_mortgage_calculator", "INTEGER DEFAULT 0"),
            ("rental_status", "TEXT DEFAULT 'Vacant'"),
            ("num_occupants", "INTEGER DEFAULT 0"),
            ("num_keys_given", "INTEGER DEFAULT 0"),
            ("move_in_date", "TEXT DEFAULT ''"),
            ("parking_storage_info", "TEXT DEFAULT ''"),
            ("lender_name", "TEXT DEFAULT ''"),
            ("loan_officer_name", "TEXT DEFAULT ''"),
            ("lender_phone", "TEXT DEFAULT ''"),
            ("lender_email", "TEXT DEFAULT ''"),
            ("loan_account_number", "TEXT DEFAULT ''"),
            ("monthly_pmi", "REAL DEFAULT 0"),
        ]:
            try:
                cursor.execute(f"ALTER TABLE portfolio_properties ADD COLUMN {column} {col_type}")
            except sqlite3.OperationalError:
                pass

        # Existing rows predate rental_status - backfill from the old
        # is_rented boolean so properties already marked rented don't
        # silently revert to the new column's 'Vacant' default.
        cursor.execute("UPDATE portfolio_properties SET rental_status='Occupied' WHERE is_rented=1 AND (rental_status IS NULL OR rental_status='Vacant')")

        # Tenants - a property can have more than one (roommates), each with
        # their own contact info and lease dates.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS portfolio_tenants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                property_id INTEGER,
                user_id INTEGER,
                name TEXT DEFAULT '',
                phone TEXT DEFAULT '',
                email TEXT DEFAULT '',
                lease_start TEXT DEFAULT '',
                lease_end TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(property_id) REFERENCES portfolio_properties(id),
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)

        # Documents - lease/contract files attached to a property. Stored on
        # local disk (see PORTFOLIO_UPLOADS_DIR in database.py); this table
        # just tracks the metadata pointing at each saved file.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS portfolio_documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                property_id INTEGER,
                user_id INTEGER,
                original_filename TEXT DEFAULT '',
                stored_filename TEXT DEFAULT '',
                uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(property_id) REFERENCES portfolio_properties(id),
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)

        # Self-service "forgot password" tokens - a row per requested reset,
        # single-use and time-limited. Not reused across requests so an old
        # emailed link can't be replayed after a newer one was issued.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS password_reset_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                token TEXT UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP,
                used INTEGER DEFAULT 0,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)

        # 4. Saved/Favorited Properties Table (with optional personal notes)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS saved_properties (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                address TEXT,
                title TEXT,
                price INTEGER,
                beds INTEGER,
                baths REAL,
                latitude REAL,
                longitude REAL,
                notes TEXT DEFAULT '',
                saved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id),
                UNIQUE(user_id, address)
            )
        """)

        # One-time migration: the old two-tier role model (user/admin) is
        # becoming three staff tiers (support/admin/super_admin - see
        # roles.py). Every account that was 'admin' under the old model had
        # full unrestricted access, which is what 'super_admin' means now -
        # so they're upgraded to preserve their existing access exactly,
        # not silently narrowed to the new (weaker) 'admin' tier. Guarded by
        # an app_settings marker so this runs exactly once ever: without
        # the guard, it would re-fire on every init_db() call (every script
        # rerun) and force every 'admin' back to 'super_admin' each time,
        # making it impossible for a super_admin to ever demote someone to
        # the new narrower 'admin' tier - the demotion would just get
        # silently undone on the next page load.
        cursor.execute("SELECT value FROM app_settings WHERE key='role_migration_v1_done'")
        if not cursor.fetchone():
            cursor.execute("UPDATE users SET role='super_admin' WHERE role='admin'")
            cursor.execute("INSERT INTO app_settings (key, value) VALUES ('role_migration_v1_done', '1')")

        # Auto-Provision the Master Admin account - only on a genuinely
        # fresh install (no staff-role user at all). Deliberately checks
        # role, not this specific seed email: checking "does a user with
        # email=admin@scoutai.com exist" would re-fire and spawn a
        # duplicate 99999-credit admin account every time init_db() runs
        # (i.e. on every script rerun) once the real admin renames their
        # own email away from the seed value - which the self-service
        # profile editor (Settings > Account) now lets them do. Confirmed
        # live: renaming the seed admin's email and then reloading the app
        # silently recreated a second admin@scoutai.com account until this
        # was changed to an existence-of-any-staff check instead.
        cursor.execute("SELECT id FROM users WHERE role IN ('admin', 'super_admin') LIMIT 1")
        if not cursor.fetchone():
            cursor.execute(
                "INSERT INTO users (email, password_hash, role, credits, account_id, created_at) VALUES (?, ?, 'super_admin', 99999, ?, CURRENT_TIMESTAMP)",
                ("admin@scoutai.com", hash_password("admin123"), _generate_account_id(cursor))
            )

        # First-run seed: copy plan_limits.DEFAULT_PLAN_LIMITS into the new
        # admin-editable credit_packages table, so nothing changes for
        # existing installs until an admin actually edits a price.
        cursor.execute("SELECT COUNT(*) FROM credit_packages")
        if cursor.fetchone()[0] == 0:
            from plan_limits import DEFAULT_PLAN_LIMITS, PLAN_ORDER
            for order, tier_name in enumerate(PLAN_ORDER):
                tier = DEFAULT_PLAN_LIMITS[tier_name]
                cursor.execute("""
                    INSERT INTO credit_packages (tier_name, price, credits, portfolio_properties, saved_properties, saved_searches, highlight, display_order)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (tier_name, tier["price"], tier["credits"], tier["portfolio_properties"],
                      tier["saved_properties"], tier["saved_searches"], 1 if tier["highlight"] else 0, order))

        conn.commit()
    finally:
        conn.close()

def register_user(email, password, first_name="", middle_name="", last_name=""):
    """Creates a new account. Returns the new user's id on success, or None
    if the email is already taken (returning the id, not just True/False,
    lets the caller immediately pre-seed a first saved search for
    the new account without a second lookup). Generates a unique account_id
    and keeps the legacy `name` column in sync as the concatenation of the
    name parts - see the account_id/first_name migration note in init_db()."""
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        account_id = _generate_account_id(cursor)
        cursor.execute(
            "INSERT INTO users (email, password_hash, role, credits, name, first_name, middle_name, last_name, account_id, created_at) "
            "VALUES (?, ?, 'user', 3, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
            (email, hash_password(password), _combine_name(first_name, middle_name, last_name),
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
    conn = sqlite3.connect(DB_NAME)
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
            _burn_bcrypt_time()
            return None
        matched, needs_upgrade = _check_password(password, row[7])
        if not matched:
            return None
        # A correct password against anything less than the current best
        # format (legacy SHA-256, the brief unkeyed-bcrypt transitional
        # scheme, or an outdated cost factor) means this account hasn't
        # logged in since that format was retired - upgrade its stored hash
        # right here, transparently, instead of a separate forced reset for
        # every existing user. See hash_password()/_check_password() for
        # the full migration design. Never let a failed opportunistic
        # rewrite block an otherwise-successful login.
        if needs_upgrade:
            try:
                cursor.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(password), int(row[0])))
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
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET theme_preference=? WHERE id=?", (mode, int(user_id)))
        conn.commit()
    finally:
        conn.close()

def deduct_credit(user_id):
    conn = sqlite3.connect(DB_NAME)
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
    conn = sqlite3.connect(DB_NAME)
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
    conn = sqlite3.connect(DB_NAME)
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

from database_admin import (
    get_all_users_for_admin,
    get_all_users_for_admin_table,
    set_user_suspended,
    get_usage_stats,
    get_recent_signups,
    get_top_credit_holders,
    get_user_activity_summary,
    get_signup_stats,
    update_user_credits_admin,
    update_user_profile_admin,
    update_user_plan_admin,
    update_user_role_admin,
    admin_reset_password,
    create_super_user_admin,
)

from database_dashboard import (
    get_dashboard_layout,
    save_dashboard_layout,
    DEFAULT_USER_SETTINGS,
    get_user_settings,
    save_user_settings,
)
from database_settings import (
    get_broadcast_message,
    set_broadcast_message,
    get_broadcast_message_set_at,
    get_design_standards,
    set_design_standards_override,
    clear_design_standards_override,
    has_design_standards_override,
    DEFAULT_BRAND_SETTINGS,
    get_brand_settings,
    save_brand_settings,
    clear_brand_settings,
)

from database_billing import (
    log_rentcast_call,
    log_autodev_call,
    get_autodev_usage_this_month,
    log_places_call,
    get_places_usage_this_month,
    get_places_config,
    update_places_config,
    get_autodev_usage_by_user,
    get_rentcast_usage_this_month,
    get_rentcast_usage_by_user,
    get_plan_distribution,
    log_credit_transaction,
    get_revenue_stats,
    get_recent_transactions,
    get_credit_packages,
    update_credit_package,
    get_rentcast_config,
    update_rentcast_config,
    get_admin_staff_emails,
    was_rentcast_alert_sent_this_month,
    mark_rentcast_alert_sent,
    get_openai_config,
    update_openai_config,
    get_autodev_config,
    update_autodev_config,
    log_openai_call,
    get_openai_usage_this_month,
    create_promo_code,
    get_promo_codes,
    validate_promo_code,
    redeem_promo_code,
    set_promo_code_active,
)
from database_profile import (
    get_own_profile,
    update_own_profile,
    change_own_password,
    get_user_by_email,
    create_password_reset_token,
    validate_reset_token,
    reset_password_with_token,
)







# --- GOOGLE SIGN-IN (Google is the sole authenticator - no local password) ---
from database_oauth import _user_record_by_id, get_or_create_google_user, get_google_login_only

from database_reports import save_report_config, get_all_reports, delete_report_config
from database_geocache import (
    get_cached_city_coords,
    get_cached_dealer_coords,
    cache_dealer_coords,
    get_cached_rentcast_area,
    save_rentcast_area_cache,
    cache_city_coords,
)

from database_history import (
    save_history_log,
    get_history_logs,
    get_recent_activity,
    get_last_notifications_read_at,
    mark_notifications_read,
    delete_history_log,
    delete_history_logs_older_than,
    get_scan_live_mock_breakdown,
)


# --- SAVED / FAVORITED PROPERTIES (with optional personal notes) ---
from database_saved_properties import (
    save_property,
    unsave_property,
    is_property_saved,
    update_property_notes,
    get_property_notes,
    get_saved_properties,
    count_saved_properties,
)


# --- PERSONAL PORTFOLIO (properties the user actually owns) ---
from database_portfolio import (
    PORTFOLIO_FIELDS,
    RENTAL_STATUSES,
    PORTFOLIO_UPLOADS_DIR,
    _sync_is_rented,
    add_portfolio_property,
    update_portfolio_property,
    delete_portfolio_property,
    get_portfolio_properties,
    add_tenant,
    update_tenant,
    delete_tenant,
    get_tenants,
    add_document,
    get_documents,
    delete_document,
)

os.makedirs(PORTFOLIO_UPLOADS_DIR, exist_ok=True)
init_db()