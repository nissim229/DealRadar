import sqlite3
import hashlib
import json
import os
import secrets
import bcrypt
from datetime import datetime, timedelta
from plan_limits import PLAN_ORDER

# Anchor the database file to this script's own directory, not the terminal's
# current working directory. Using a bare relative filename here meant that
# launching the app from a slightly different folder (or a fresh terminal
# session) would silently create/read a DIFFERENT database file - looking
# like saved data (profiles, theme preference, credits) had been forgotten,
# when really it was just written to a different file each time.
DB_NAME = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_config.db")

def hash_password(password):
    """Securely hashes a password using bcrypt. The password is pre-hashed
    with SHA-256 into a fixed 32-byte digest first, so bcrypt's own 72-byte
    input limit never silently truncates a long passphrase before it
    reaches the slow algorithm that actually needs the entropy."""
    pre_hashed = hashlib.sha256(password.encode()).digest()
    return bcrypt.hashpw(pre_hashed, bcrypt.gensalt()).decode()

def _hash_password_legacy(password):
    """The original unsalted SHA-256 hashing this app used before the
    bcrypt migration. Kept ONLY so verify_password() can still check a
    password against an account that hasn't logged in since the migration
    (its stored hash is still in this old format) - never used to create
    new hashes."""
    return hashlib.sha256(password.encode()).hexdigest()

def _is_bcrypt_hash(stored_hash):
    """bcrypt hashes always start with one of these version prefixes;
    a legacy SHA-256 hash is just a 64-char hex digest and never does."""
    return bool(stored_hash) and stored_hash.startswith(("$2a$", "$2b$", "$2y$"))

def verify_password(password, stored_hash):
    """Checks password against whichever hash format stored_hash is in -
    bcrypt for accounts already migrated, legacy SHA-256 otherwise. This
    dual-format check is what lets authenticate_user() migrate a legacy
    hash to bcrypt transparently on a successful login, instead of forcing
    every existing user through a password reset."""
    if not stored_hash:
        return False
    if _is_bcrypt_hash(stored_hash):
        pre_hashed = hashlib.sha256(password.encode()).digest()
        try:
            return bcrypt.checkpw(pre_hashed, stored_hash.encode())
        except ValueError:
            return False
    return _hash_password_legacy(password) == stored_hash


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
        if not row or not verify_password(password, row[7]):
            return None
        # A correct password against a still-legacy SHA-256 hash means this
        # account hasn't logged in since the bcrypt migration - upgrade its
        # stored hash right here, transparently, instead of requiring a
        # separate forced reset for every existing user. See hash_password()
        # and verify_password() for the full migration design.
        if not _is_bcrypt_hash(row[7]):
            cursor.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(password), int(row[0])))
            conn.commit()
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

def get_all_users_for_admin():
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, email, role, credits, name, is_suspended FROM users ORDER BY id")
        return cursor.fetchall()
    finally:
        conn.close()

def get_all_users_for_admin_table():
    """One row per user with everything the admin Users table needs to show
    at a glance - plan, credits, scan activity (total and live), real
    RentCast calls consumed, and total (simulated) dollars spent - computed
    with pre-aggregated subqueries and a single query rather than N+1 calls
    to get_user_activity_summary() per row, since this backs a table meant
    to show every user at once."""
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT u.id, u.email, u.name, u.role, COALESCE(u.plan, 'Free'), u.credits, u.is_suspended, u.created_at,
                   COALESCE(h.scan_count, 0), COALESCE(h.live_scan_count, 0),
                   COALESCE(r.rentcast_calls, 0), COALESCE(t.total_spent, 0),
                   u.account_id, COALESCE(u.first_name, ''), COALESCE(u.middle_name, ''), COALESCE(u.last_name, '')
            FROM users u
            LEFT JOIN (SELECT user_id, COUNT(*) as scan_count, SUM(was_live) as live_scan_count
                       FROM history_logs GROUP BY user_id) h ON u.id = h.user_id
            LEFT JOIN (SELECT user_id, COUNT(*) as rentcast_calls
                       FROM rentcast_usage_log WHERE user_id IS NOT NULL GROUP BY user_id) r ON u.id = r.user_id
            LEFT JOIN (SELECT user_id, SUM(dollar_amount) as total_spent
                       FROM credit_transactions GROUP BY user_id) t ON u.id = t.user_id
            ORDER BY u.id
        """)
        return cursor.fetchall()
    finally:
        conn.close()

def set_user_suspended(user_id, suspended):
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET is_suspended=? WHERE id=?", (1 if suspended else 0, int(user_id)))
        conn.commit()
    finally:
        conn.close()

def get_usage_stats():
    """Aggregate numbers for the admin usage dashboard: total users, total
    credits currently outstanding across all accounts, total scans ever run
    (history_logs row count), and the list of users sitting at 0 credits -
    the actual upsell target list once real packages/payments exist."""
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = cursor.fetchone()[0]

        cursor.execute("SELECT COALESCE(SUM(credits), 0) FROM users")
        total_credits = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM history_logs")
        total_scans = cursor.fetchone()[0]

        cursor.execute("SELECT email, name FROM users WHERE credits <= 0 AND role != 'admin'")
        zero_credit_users = cursor.fetchall()

        return {
            "total_users": total_users,
            "total_credits": total_credits,
            "total_scans": total_scans,
            "zero_credit_users": zero_credit_users,
        }
    finally:
        conn.close()

def get_dashboard_layout(user_id, dashboard_type):
    """Returns the saved grid layout {"grid_columns": N, "cards": [{"id","span"}, ...]}
    for this user's dashboard, or None if they've never customized it (the
    caller falls back to a built-in default layout in that case)."""
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT layout_json FROM dashboard_layouts WHERE user_id=? AND dashboard_type=?",
                        (int(user_id), dashboard_type))
        row = cursor.fetchone()
        return json.loads(row[0]) if row else None
    finally:
        conn.close()

def save_dashboard_layout(user_id, dashboard_type, layout):
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO dashboard_layouts (user_id, dashboard_type, layout_json, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id, dashboard_type) DO UPDATE SET layout_json=excluded.layout_json, updated_at=excluded.updated_at
        """, (int(user_id), dashboard_type, json.dumps(layout)))
        conn.commit()
    finally:
        conn.close()

DEFAULT_USER_SETTINGS = {
    "timezone": None,  # None = not yet detected/set - display code falls back to UTC
    "default_down_pct": 25,
    "default_interest_rate": 6.5,
    "default_vacancy_pct": 5,
    "default_tax_rate": 1.2,
    "default_insurance_rate": 0.4,
    "default_target_yield": 8.0,
    "default_results_view": "Properties + Map",
    "default_underwriter_mode": "Simple",
    "default_reference_address": "",
    # Security/status notifications default on (a user generally wants to
    # know their credits ran out or their password changed); the deal-found
    # alert defaults off since it's closer to an opt-in feature notification
    # than an account-status one - matches how most apps treat "alerts about
    # things I might like" vs. "alerts about my account."
    "notify_deal_found": False,
    "notify_low_credits": True,
    "notify_password_changed": True,
}


def get_user_settings(user_id):
    """Returns this user's Settings-page preferences, with any keys missing
    from an older saved blob (or a user who's never saved one at all)
    backfilled from DEFAULT_USER_SETTINGS - same missing-key-tolerance
    reasoning as dashboard_grid.py's layout backfill, so adding a new
    setting later never breaks an existing saved row."""
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT settings_json FROM user_settings WHERE user_id=?", (int(user_id),))
        row = cursor.fetchone()
        saved = json.loads(row[0]) if row and row[0] else {}
        return {**DEFAULT_USER_SETTINGS, **saved}
    finally:
        conn.close()


def save_user_settings(user_id, settings):
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO user_settings (user_id, settings_json, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET settings_json=excluded.settings_json, updated_at=excluded.updated_at
        """, (int(user_id), json.dumps(settings)))
        conn.commit()
    finally:
        conn.close()


def get_recent_signups(limit=15):
    """Newest accounts first, for the Total Users stat card's drill-down
    dialog on the admin dashboard."""
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT email, name, COALESCE(plan, 'Free'), created_at FROM users
            ORDER BY created_at DESC LIMIT ?
        """, (limit,))
        return cursor.fetchall()
    finally:
        conn.close()

def get_top_credit_holders(limit=10):
    """Highest credit balances first, for the Credits Outstanding stat
    card's drill-down dialog - the zero-credit list nearby already covers
    the opposite (upsell) end."""
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT email, name, credits, COALESCE(plan, 'Free') FROM users
            WHERE role != 'admin' ORDER BY credits DESC LIMIT ?
        """, (limit,))
        return cursor.fetchall()
    finally:
        conn.close()

def get_user_activity_summary(user_id):
    """Cross-user support view for admins: how many hunt-criteria profiles,
    past scans (broken into live vs mock), real RentCast calls consumed, and
    dollars spent (from the simulated transaction ledger) a given user has -
    without needing to ask them directly."""
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM reports WHERE user_id=?", (int(user_id),))
        profile_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*), COALESCE(SUM(was_live), 0) FROM history_logs WHERE user_id=?", (int(user_id),))
        scan_count, live_scan_count = cursor.fetchone()
        cursor.execute("SELECT COUNT(*) FROM saved_properties WHERE user_id=?", (int(user_id),))
        saved_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM rentcast_usage_log WHERE user_id=?", (int(user_id),))
        rentcast_call_count = cursor.fetchone()[0]
        cursor.execute("SELECT COALESCE(SUM(dollar_amount), 0) FROM credit_transactions WHERE user_id=?", (int(user_id),))
        total_spent = cursor.fetchone()[0]
        return {
            "profile_count": profile_count, "scan_count": scan_count, "saved_count": saved_count,
            "live_scan_count": live_scan_count, "rentcast_call_count": rentcast_call_count, "total_spent": total_spent,
        }
    finally:
        conn.close()

def get_broadcast_message():
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM app_settings WHERE key='broadcast_message'")
        row = cursor.fetchone()
        return row[0] if row and row[0] else ""
    finally:
        conn.close()

def set_broadcast_message(message):
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO app_settings (key, value) VALUES ('broadcast_message', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (message,)
        )
        # Own timestamp, not reused from anywhere else, so the notification
        # bell can tell whether THIS broadcast is new since the user last
        # opened it - a plain key/value pair fits app_settings' existing
        # shape rather than needing a dedicated table for one extra field.
        cursor.execute(
            "INSERT INTO app_settings (key, value) VALUES ('broadcast_message_set_at', CURRENT_TIMESTAMP) "
            "ON CONFLICT(key) DO UPDATE SET value=CURRENT_TIMESTAMP"
        )
        conn.commit()
    finally:
        conn.close()

def get_broadcast_message_set_at():
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM app_settings WHERE key='broadcast_message_set_at'")
        row = cursor.fetchone()
        return row[0] if row and row[0] else None
    finally:
        conn.close()

def get_design_standards():
    """Returns the current DESIGN_STANDARDS.md content - an admin-saved
    override from app_settings if one exists (Admin Controls > Design
    Standards lets a super_admin edit this live, in-app), otherwise the
    file checked into the repo, read fresh each call so a code-level edit
    (e.g. Claude updating the file directly) shows up immediately without
    needing a matching DB write. The file stays the source of truth for
    what ships; the DB override is for a quick in-app wording tweak that
    doesn't need a code change."""
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM app_settings WHERE key='design_standards_override'")
        row = cursor.fetchone()
        if row and row[0]:
            return row[0]
    finally:
        conn.close()

    try:
        standards_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "DESIGN_STANDARDS.md")
        with open(standards_path, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""

def set_design_standards_override(content):
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO app_settings (key, value) VALUES ('design_standards_override', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (content,)
        )
        conn.commit()
    finally:
        conn.close()

def clear_design_standards_override():
    """Reverts to the repo file (DESIGN_STANDARDS.md) as the source of
    truth again, discarding any in-app edit."""
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM app_settings WHERE key='design_standards_override'")
        conn.commit()
    finally:
        conn.close()

def has_design_standards_override():
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM app_settings WHERE key='design_standards_override'")
        return cursor.fetchone() is not None
    finally:
        conn.close()

# Sitewide brand controls (Admin Controls > Brand & Design, super_admin-
# only) - accent color, the 3 typeface roles, and an optional custom
# logo, all read by design_tokens.py's inject_design_tokens() so a save
# here actually re-skins the live app (CSS custom properties + the
# Google Fonts import), not just a settings record nobody reads. One
# JSON blob under app_settings, same missing-key-tolerant backfill
# pattern as DEFAULT_USER_SETTINGS, since this is sitewide (not
# per-user) state - a dedicated table would be one row forever.
DEFAULT_BRAND_SETTINGS = {
    "accent_color": "#22d3ee",
    "font_display": "Sora",
    "font_body": "Work Sans",
    "font_mono": "JetBrains Mono",
    "logo_data_uri": "",  # empty = use the built-in radar SVG mark
    # Per-category raw HTML override for the topbar logo lockup - empty
    # means "use the built-in coded house/car badge" (see main.py's
    # col_logo block). Separate from logo_data_uri above: that one swaps
    # just the icon image inside the built-in badge, these replace the
    # *entire* lockup (icon + wordmark + caption) with whatever HTML the
    # admin pastes, one per deal category.
    "logo_html_real_estate": "",
    "logo_html_cars": "",
    "logo_html_guest": "",
    # Saved logo presets per slot - a library of {"name", "html"} dicts an
    # admin can build up over time and re-apply later without retyping,
    # separate from logo_html_* above (which is only ever the single
    # currently-ACTIVE override). Applying a preset copies its html into
    # the matching logo_html_* field; presets themselves are never
    # rendered directly.
    "logo_presets_real_estate": [],
    "logo_presets_cars": [],
    "logo_presets_guest": [],
}

def get_brand_settings():
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM app_settings WHERE key='brand_settings_json'")
        row = cursor.fetchone()
        saved = json.loads(row[0]) if row and row[0] else {}
        return {**DEFAULT_BRAND_SETTINGS, **saved}
    finally:
        conn.close()

def save_brand_settings(settings):
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO app_settings (key, value) VALUES ('brand_settings_json', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (json.dumps(settings),)
        )
        conn.commit()
    finally:
        conn.close()

def clear_brand_settings():
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM app_settings WHERE key='brand_settings_json'")
        conn.commit()
    finally:
        conn.close()

def log_rentcast_call(success, user_id=None):
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO rentcast_usage_log (success, user_id) VALUES (?, ?)",
                        (1 if success else 0, int(user_id) if user_id is not None else None))
        conn.commit()
    finally:
        conn.close()

def log_autodev_call(success, user_id=None):
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO autodev_usage_log (success, user_id) VALUES (?, ?)",
                        (1 if success else 0, int(user_id) if user_id is not None else None))
        conn.commit()
    finally:
        conn.close()

def get_autodev_usage_this_month():
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM autodev_usage_log WHERE strftime('%Y-%m', called_at) = strftime('%Y-%m', 'now')"
        )
        return cursor.fetchone()[0]
    finally:
        conn.close()

def log_places_call(success, user_id=None):
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO places_usage_log (success, user_id) VALUES (?, ?)",
                        (1 if success else 0, int(user_id) if user_id is not None else None))
        conn.commit()
    finally:
        conn.close()

def get_places_usage_this_month():
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM places_usage_log WHERE strftime('%Y-%m', called_at) = strftime('%Y-%m', 'now')"
        )
        return cursor.fetchone()[0]
    finally:
        conn.close()

def get_places_config():
    """Google Places has no app-readable plan/quota the way RentCast does -
    it's pay-per-request billing on the admin's own Google Cloud account.
    monthly_limit here is a self-declared budget (the admin's own number,
    from their Cloud Console), tracked against places_usage_log the same
    way RentCast's real plan limit is - just without any claim that this
    app actually knows Google's side of it."""
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM app_settings WHERE key='places_monthly_limit'")
        row = cursor.fetchone()
        return {"monthly_limit": int(row[0]) if row else 1000}
    finally:
        conn.close()

def update_places_config(monthly_limit):
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO app_settings (key, value) VALUES ('places_monthly_limit', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(int(monthly_limit)),)
        )
        conn.commit()
    finally:
        conn.close()

def get_autodev_usage_by_user(limit=10):
    """Same idea as get_rentcast_usage_by_user, for Cars' Auto.dev calls -
    no legacy-NULL-user_id bucket needed here since autodev_usage_log had
    a user_id column from the start (unlike rentcast_usage_log, which
    predates its own user_id migration)."""
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT u.email, u.name, COUNT(*) as call_count
            FROM autodev_usage_log a
            JOIN users u ON a.user_id = u.id
            WHERE strftime('%Y-%m', a.called_at) = strftime('%Y-%m', 'now')
            GROUP BY a.user_id
            ORDER BY call_count DESC
            LIMIT ?
        """, (limit,))
        return [{"email": email, "name": name, "call_count": count} for email, name, count in cursor.fetchall()]
    finally:
        conn.close()

def get_rentcast_usage_this_month():
    """Counts real RentCast API calls made so far in the current calendar
    month (both successes and failures - a failed request still counts
    against the plan's quota, since RentCast bills per request sent, not
    per useful result returned)."""
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM rentcast_usage_log WHERE strftime('%Y-%m', called_at) = strftime('%Y-%m', 'now')"
        )
        return cursor.fetchone()[0]
    finally:
        conn.close()

def get_rentcast_usage_by_user(limit=10):
    """Per-user breakdown of real RentCast calls made this calendar month,
    highest first - answers "who's actually spending the API quota", which
    the plain monthly total can't. Rows logged before the user_id column
    existed (see the rentcast_usage_log migration) group under a synthetic
    "Unknown (legacy)" bucket rather than being silently dropped or
    misattributed to whichever user happens to have a matching id."""
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT u.email, u.name, COUNT(*) as call_count
            FROM rentcast_usage_log r
            JOIN users u ON r.user_id = u.id
            WHERE strftime('%Y-%m', r.called_at) = strftime('%Y-%m', 'now')
            GROUP BY r.user_id
            ORDER BY call_count DESC
            LIMIT ?
        """, (limit,))
        rows = [{"email": email, "name": name, "call_count": count} for email, name, count in cursor.fetchall()]

        cursor.execute("""
            SELECT COUNT(*) FROM rentcast_usage_log
            WHERE user_id IS NULL AND strftime('%Y-%m', called_at) = strftime('%Y-%m', 'now')
        """)
        legacy_count = cursor.fetchone()[0]
        if legacy_count:
            rows.append({"email": None, "name": "Unknown (legacy, before per-user tracking)", "call_count": legacy_count})
        return rows
    finally:
        conn.close()

def get_scan_live_mock_breakdown():
    """All-time and this-month counts of live (real RentCast data) vs mock
    (preview/sample) scans, from history_logs.was_live. Existing rows from
    before that column existed default to 0 (mock) - see its migration."""
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COALESCE(SUM(was_live), 0), COUNT(*) FROM history_logs")
        live_all, total_all = cursor.fetchone()
        cursor.execute("""
            SELECT COALESCE(SUM(was_live), 0), COUNT(*) FROM history_logs
            WHERE strftime('%Y-%m', generated_at) = strftime('%Y-%m', 'now')
        """)
        live_month, total_month = cursor.fetchone()
        return {
            "live_all_time": live_all, "mock_all_time": total_all - live_all,
            "live_this_month": live_month, "mock_this_month": total_month - live_month,
        }
    finally:
        conn.close()

def get_signup_stats(trend_days=30):
    """Total registered users, how many signed up in the last 7 days (a
    fixed metric, independent of the chart window), and a day-by-day count
    for the last `trend_days` days for the admin dashboard's growth trend
    chart - the window itself is admin-adjustable, not fixed to 30."""
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users")
        total = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM users WHERE created_at >= datetime('now', '-7 days')")
        new_this_week = cursor.fetchone()[0]
        cursor.execute("""
            SELECT date(created_at) as d, COUNT(*) FROM users
            WHERE created_at >= datetime('now', ?)
            GROUP BY d ORDER BY d
        """, (f"-{int(trend_days)} days",))
        daily = cursor.fetchall()
        return {"total": total, "new_this_week": new_this_week, "daily": daily}
    finally:
        conn.close()

def get_plan_distribution():
    """How many users sit on each plan tier (Free/Starter/Pro/Enterprise) -
    stored on every user already via users.plan, just never surfaced."""
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COALESCE(plan, 'Free'), COUNT(*) FROM users GROUP BY COALESCE(plan, 'Free')")
        return dict(cursor.fetchall())
    finally:
        conn.close()

def log_credit_transaction(user_id, package_name, dollar_amount, credits_granted, promo_code=None):
    """Records a (simulated) package purchase - see components/pricing.py's
    demo checkout. dollar_amount is the FINAL (post-promo-discount) price
    actually charged, not the sticker price - revenue stats stay accurate
    even when discounts were applied. Not called for admin-granted bonus
    credits, so revenue totals only ever reflect actual (simulated)
    purchases."""
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO credit_transactions (user_id, package_name, dollar_amount, credits_granted, promo_code) VALUES (?, ?, ?, ?, ?)",
            (int(user_id), package_name, float(dollar_amount), int(credits_granted), promo_code)
        )
        conn.commit()
    finally:
        conn.close()

def get_revenue_stats():
    """All-time and this-month totals from the (simulated) transaction
    ledger, for the admin Revenue tab."""
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COALESCE(SUM(dollar_amount), 0), COUNT(*) FROM credit_transactions")
        total_all, count_all = cursor.fetchone()
        cursor.execute("""
            SELECT COALESCE(SUM(dollar_amount), 0), COUNT(*) FROM credit_transactions
            WHERE strftime('%Y-%m', purchased_at) = strftime('%Y-%m', 'now')
        """)
        total_month, count_month = cursor.fetchone()
        return {
            "total_all_time": total_all, "count_all_time": count_all,
            "total_this_month": total_month, "count_this_month": count_month,
        }
    finally:
        conn.close()

def get_recent_transactions(limit=15):
    """Most recent (simulated) purchases, newest first, for the admin
    Revenue tab's transaction ledger."""
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT u.email, u.name, t.package_name, t.dollar_amount, t.credits_granted, t.purchased_at
            FROM credit_transactions t
            JOIN users u ON t.user_id = u.id
            ORDER BY t.purchased_at DESC
            LIMIT ?
        """, (limit,))
        return cursor.fetchall()
    finally:
        conn.close()

def get_credit_packages():
    """All credit packages (Free + purchasable tiers), keyed by tier_name,
    in the same shape plan_limits.py's old hardcoded PLAN_LIMITS dict used -
    so every existing caller of plan_limits.get_limit()/is_within_limit()
    keeps working unchanged. Source of truth for pricing/resource caps now
    lives here instead of in code, editable via the admin Pricing tab."""
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT tier_name, price, credits, portfolio_properties, saved_properties, saved_searches, highlight
            FROM credit_packages ORDER BY display_order
        """)
        return {
            row[0]: {
                "price": row[1], "credits": row[2], "portfolio_properties": row[3],
                "saved_properties": row[4], "saved_searches": row[5], "highlight": bool(row[6]),
            }
            for row in cursor.fetchall()
        }
    finally:
        conn.close()

def update_credit_package(tier_name, price, credits, portfolio_properties, saved_properties, saved_searches):
    """Admin edit of one package's price/credits/resource caps. None on a
    resource-cap field means unlimited - same convention as before."""
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE credit_packages SET price=?, credits=?, portfolio_properties=?, saved_properties=?, saved_searches=?
            WHERE tier_name=?
        """, (float(price), int(credits), portfolio_properties, saved_properties, saved_searches, tier_name))
        conn.commit()
    finally:
        conn.close()

def get_rentcast_config():
    """Admin-editable RentCast plan info - previously a hardcoded constant
    (RENTCAST_MONTHLY_LIMIT=50 in agent_engine.py) that never matched
    reality if the account's real RentCast plan changed. Defaults match the
    old hardcoded value/free-tier assumption when nothing's been set yet."""
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT key, value FROM app_settings WHERE key IN "
                        "('rentcast_monthly_limit', 'rentcast_plan_name', 'rentcast_monthly_cost', "
                        "'rentcast_verified_at', 'rentcast_alert_threshold_pct')")
        settings = dict(cursor.fetchall())
        return {
            "monthly_limit": int(settings.get("rentcast_monthly_limit", 50)),
            "plan_name": settings.get("rentcast_plan_name", "Developer (Free)"),
            "monthly_cost": float(settings.get("rentcast_monthly_cost", 0)),
            "verified_at": settings.get("rentcast_verified_at"),
            "alert_threshold_pct": int(settings.get("rentcast_alert_threshold_pct", 85)),
        }
    finally:
        conn.close()

def update_rentcast_config(monthly_limit, plan_name, monthly_cost, alert_threshold_pct=85):
    """Saves the admin's real RentCast plan details and stamps 'verified_at'
    to now - the honest substitute for an automated price-change alert
    (RentCast has no webhook/API for its own pricing changes), so the admin
    panel can show "verified N days ago, please re-check" instead of
    silently trusting a number that might be stale.

    alert_threshold_pct drives a *different* alert - see
    maybe_send_rentcast_quota_alert() - that emails staff once usage this
    calendar month reaches this percentage of monthly_limit."""
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        for key, value in [
            ("rentcast_monthly_limit", str(int(monthly_limit))),
            ("rentcast_plan_name", plan_name),
            ("rentcast_monthly_cost", str(float(monthly_cost))),
            ("rentcast_verified_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            ("rentcast_alert_threshold_pct", str(int(alert_threshold_pct))),
        ]:
            cursor.execute(
                "INSERT INTO app_settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value)
            )
        conn.commit()
    finally:
        conn.close()

def get_admin_staff_emails():
    """Every admin/super_admin's email - the recipient list for the RentCast
    quota-threshold alert (an operational/billing concern, not something a
    'support'-tier staff account needs to act on)."""
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT email FROM users WHERE role IN ('admin', 'super_admin')")
        return [row[0] for row in cursor.fetchall()]
    finally:
        conn.close()

def was_rentcast_alert_sent_this_month():
    """True once maybe_send_rentcast_quota_alert() has already fired this
    calendar month - a plain 'YYYY-MM' string comparison naturally resets
    itself every month with no cleanup job needed."""
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM app_settings WHERE key='rentcast_alert_sent_month'")
        row = cursor.fetchone()
        return bool(row) and row[0] == datetime.now().strftime("%Y-%m")
    finally:
        conn.close()

def mark_rentcast_alert_sent():
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO app_settings (key, value) VALUES ('rentcast_alert_sent_month', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (datetime.now().strftime("%Y-%m"),)
        )
        conn.commit()
    finally:
        conn.close()

def get_openai_config():
    """Admin-editable monthly cap on OpenAI report-generation calls -
    previously uncapped entirely (every scan, including anonymous guest
    previews, called OpenAI with no limit). Default of 500/month is a
    starting point, editable in the admin Pricing tab."""
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM app_settings WHERE key='openai_monthly_limit'")
        row = cursor.fetchone()
        return {"monthly_limit": int(row[0]) if row else 500}
    finally:
        conn.close()

def update_openai_config(monthly_limit):
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO app_settings (key, value) VALUES ('openai_monthly_limit', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(int(monthly_limit)),)
        )
        conn.commit()
    finally:
        conn.close()

def log_openai_call(user_id=None):
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO openai_usage_log (user_id) VALUES (?)",
                        (int(user_id) if user_id is not None else None,))
        conn.commit()
    finally:
        conn.close()

def get_openai_usage_this_month():
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM openai_usage_log WHERE strftime('%Y-%m', called_at) = strftime('%Y-%m', 'now')"
        )
        return cursor.fetchone()[0]
    finally:
        conn.close()

def create_promo_code(code, discount_type, discount_value, max_uses=None, expires_at=None):
    """discount_type is 'percent' or 'flat'. Returns False if the code
    already exists (codes are unique, case as typed)."""
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO promo_codes (code, discount_type, discount_value, max_uses, expires_at) VALUES (?, ?, ?, ?, ?)",
            (code, discount_type, float(discount_value), max_uses, expires_at)
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def get_promo_codes():
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, code, discount_type, discount_value, max_uses, times_used, expires_at, active
            FROM promo_codes ORDER BY created_at DESC
        """)
        return cursor.fetchall()
    finally:
        conn.close()

def validate_promo_code(code):
    """Returns (row, None) if the code can be used right now, or (None,
    reason) explaining why not - checked at both display time (in the Buy
    Credits dialog) and again at purchase time, since a code could expire
    or hit its cap between the two."""
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, code, discount_type, discount_value, max_uses, times_used, expires_at, active
            FROM promo_codes WHERE code=?
        """, (code,))
        row = cursor.fetchone()
        if not row:
            return None, "That code doesn't exist."
        _id, _code, discount_type, discount_value, max_uses, times_used, expires_at, active = row
        if not active:
            return None, "That code has been deactivated."
        if expires_at and datetime.now() > datetime.strptime(expires_at, "%Y-%m-%d %H:%M:%S"):
            return None, "That code has expired."
        if max_uses is not None and times_used >= max_uses:
            return None, "That code has reached its usage limit."
        return {"id": _id, "code": _code, "discount_type": discount_type, "discount_value": discount_value}, None
    finally:
        conn.close()

def redeem_promo_code(code):
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE promo_codes SET times_used = times_used + 1 WHERE code=?", (code,))
        conn.commit()
    finally:
        conn.close()

def set_promo_code_active(promo_id, active):
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE promo_codes SET active=? WHERE id=?", (1 if active else 0, int(promo_id)))
        conn.commit()
    finally:
        conn.close()

def update_user_credits_admin(user_id, absolute_credits):
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET credits=? WHERE id=?", (int(absolute_credits), int(user_id)))
        conn.commit()
    finally:
        conn.close()

def update_user_profile_admin(user_id, first_name, middle_name, last_name, email):
    """Admin edit of a user's own name/email - for support tickets where the
    user can't fix a typo or update their email themselves. Keeps the
    legacy `name` column in sync as the concatenation, same as
    update_own_profile(). Returns False if the new email is already taken
    by a different account, True on success."""
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET name=?, first_name=?, middle_name=?, last_name=?, email=? WHERE id=?",
            (_combine_name(first_name, middle_name, last_name), first_name.strip(), middle_name.strip(), last_name.strip(),
             email, int(user_id))
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def get_own_profile(user_id):
    """First/middle/last name, email/phone/address, and the read-only
    account_id for the Settings page's Account section - deliberately
    nothing payment-related here (see update_own_profile). Legacy accounts
    (created before first/middle/last existed) have empty structured-name
    columns even though their old combined `name` is set - best-effort
    split that legacy name into first/last here rather than returning
    blanks, since update_own_profile rebuilds `name` from these three
    fields and would otherwise silently blank a real name on save."""
    conn = sqlite3.connect(DB_NAME)
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
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT email, password_hash FROM users WHERE id=?", (int(user_id),))
        row = cursor.fetchone()
        if not row:
            return {"success": False, "error": "Account not found."}
        current_email, password_hash = row
        if email != current_email:
            if not current_password or not verify_password(current_password, password_hash):
                return {"success": False, "error": "Enter your current password to change your email."}
        cursor.execute(
            "UPDATE users SET name=?, first_name=?, middle_name=?, last_name=?, email=?, phone=?, address=? WHERE id=?",
            (_combine_name(first_name, middle_name, last_name), first_name.strip(), middle_name.strip(), last_name.strip(),
             email, phone, address, int(user_id))
        )
        conn.commit()
        return {"success": True, "error": None}
    except sqlite3.IntegrityError:
        return {"success": False, "error": "That email is already in use by another account."}
    finally:
        conn.close()

def update_user_plan_admin(user_id, plan):
    """Unconditional admin set of a user's plan tier - unlike
    update_user_plan() (upgrade-only, used by the real purchase flow so a
    smaller re-purchase can't accidentally downgrade someone), this can
    also downgrade, for correcting a wrong purchase or a support request."""
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET plan=? WHERE id=?", (plan, int(user_id)))
        conn.commit()
    finally:
        conn.close()

def update_user_role_admin(user_id, role):
    """Sets a user's role (see roles.py for the four tiers). This is the one
    genuinely dangerous admin action - it's how someone gets (or loses)
    access to Admin Controls at all, including the ability to grant roles
    to others - so unlike the other admin setters here, it enforces a real
    invariant at this layer rather than trusting the caller: refuses to
    demote the LAST super_admin away from that role, which would lock
    everyone out of ever granting staff access again (nobody left who's
    allowed to). The UI layer (admin_controls.py) additionally restricts
    who can even see this control (super_admin only) and never lets anyone
    change their own role, but that's a UI convenience, not the safety net
    - this check is. Returns True on success, False if this specific
    demotion was refused."""
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT role FROM users WHERE id=?", (int(user_id),))
        row = cursor.fetchone()
        current_role = row[0] if row else None
        if current_role == "super_admin" and role != "super_admin":
            cursor.execute("SELECT COUNT(*) FROM users WHERE role='super_admin'")
            if cursor.fetchone()[0] <= 1:
                return False
        cursor.execute("UPDATE users SET role=? WHERE id=?", (role, int(user_id)))
        conn.commit()
        return True
    finally:
        conn.close()

def change_own_password(user_id, current_password, new_password):
    """Self-service password change for a logged-in user - verifies their
    current password first (that's the identity check here, since they're
    already authenticated but this is still a sensitive action), then
    updates it. Returns True on success, False if current_password didn't
    match."""
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT password_hash FROM users WHERE id=?", (int(user_id),))
        row = cursor.fetchone()
        if not row or not verify_password(current_password, row[0]):
            return False
        cursor.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(new_password), int(user_id)))
        conn.commit()
        return True
    finally:
        conn.close()

def admin_reset_password(user_id, new_password):
    """Admin-assisted password reset for a locked-out user - secure because
    it requires an authenticated admin to act, unlike a self-service reset
    without email verification, which would let anyone reset anyone else's
    password just by knowing their email (see the self-service email-based
    reset flow below, now that an email provider is configured)."""
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(new_password), int(user_id)))
        conn.commit()
    finally:
        conn.close()

# --- SELF-SERVICE PASSWORD RESET (email-verified, no login required) ---

def get_user_by_email(email):
    """Returns (id, is_suspended) for an account with this email, or None.
    Used by the forgot-password flow - deliberately returns nothing more
    than what's needed to decide whether to issue a reset token."""
    conn = sqlite3.connect(DB_NAME)
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
    expires_at = (datetime.utcnow() + timedelta(minutes=valid_minutes)).strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(DB_NAME)
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
    conn = sqlite3.connect(DB_NAME)
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
        if datetime.utcnow() > datetime.strptime(expires_at, "%Y-%m-%d %H:%M:%S"):
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
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(new_password), user_id))
        cursor.execute("UPDATE password_reset_tokens SET used=1 WHERE token=?", (token,))
        conn.commit()
        return True
    finally:
        conn.close()

# --- GOOGLE SIGN-IN (Google is the sole authenticator - no local password) ---

def _user_record_by_id(user_id):
    """Shared by get_or_create_google_user and get_google_login_only - both
    need the same authenticate_user()-shaped dict once they've resolved a
    user_id, differing only in whether they're allowed to create one."""
    conn = sqlite3.connect(DB_NAME)
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
    existing = get_user_by_email(email)
    if existing is None:
        # Google only gives one combined display name, not separate parts -
        # best-effort split on the first space (first word = first name,
        # rest = last name); the user can fix this precisely later via
        # Settings > Account if the split guessed wrong (e.g. multi-word
        # first/last names, suffixes).
        name_parts = name.strip().split(" ", 1)
        first = name_parts[0] if name_parts else ""
        last = name_parts[1] if len(name_parts) > 1 else ""
        user_id = register_user(email, secrets.token_urlsafe(32), first, "", last)
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
    existing = get_user_by_email(email)
    if existing is None:
        return None
    user_id, is_suspended = existing
    if is_suspended:
        return {"suspended": True}
    return _user_record_by_id(user_id)

def create_super_user_admin(email, password, role="admin"):
    """Used by Admin Controls > Add Admins - a separate creation path from
    register_user() (no free-scan-credit signup flow, no pre-seeded first
    search), so it needs its own account_id generation too rather than
    relying on register_user()'s. Without this, a freshly-added admin would
    show a blank Account ID until the next full init_db() backfill run.
    role defaults to "admin" (see roles.py) rather than "super_admin" -
    granting the top tier is a deliberate separate choice the caller (the
    Add Admins tab, itself super_admin-only) makes explicitly."""
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO users (email, password_hash, role, credits, account_id, created_at) VALUES (?, ?, ?, 99999, ?, CURRENT_TIMESTAMP)",
            (email, hash_password(password), role, _generate_account_id(cursor))
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

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
    conn = sqlite3.connect(DB_NAME)
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

def get_cached_city_coords(city, state):
    """Returns (lat, lon) for a previously-geocoded city/state pair, or
    None if it hasn't been resolved yet - callers geocode and store via
    cache_city_coords() on a miss, so a given city is only ever geocoded
    once across the whole app's lifetime."""
    conn = sqlite3.connect(DB_NAME)
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
    conn = sqlite3.connect(DB_NAME)
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
    conn = sqlite3.connect(DB_NAME)
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
    conn = sqlite3.connect(DB_NAME)
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
    conn = sqlite3.connect(DB_NAME)
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
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO city_coords_cache (city, state, lat, lon) VALUES (?, ?, ?, ?)",
            (city, state, float(lat), float(lon))
        )
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
    conn = sqlite3.connect(DB_NAME)
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
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM reports WHERE user_id=? AND profile_name=?", (int(user_id), name))
        conn.commit()
    finally:
        conn.close()

# --- HISTORY LOG QUERIES (UPDATED FOR DYNAMIC COORDINATES) ---

def save_history_log(user_id, profile_name, location, content, coordinates_json="", was_live=False, category="real_estate"):
    """Saves a compiled AI report output and its map coordinates to the
    history archive. was_live records whether this scan pulled real
    RentCast listings vs mock/preview data, for the admin usage dashboard.
    category distinguishes property scans from Cars scans (see
    [[cars_category_feature]]) - Cars searches log a lightweight row here
    too (empty content, no map coordinates), purely so the notification
    bell has real recent-activity data for that category, not just
    real estate."""
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO history_logs (user_id, profile_name, location, report_content, coordinates_json, was_live, category) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (int(user_id), profile_name, location, content, coordinates_json, 1 if was_live else 0, category)
        )
        conn.commit()
    finally:
        conn.close()

def get_history_logs(user_id, category="real_estate"):
    """Fetches full past log metadata fields including map coordinates,
    scoped to one category - the real-estate History Log page only ever
    wants its own scans, not Cars' lightweight activity rows."""
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, profile_name, location, generated_at, report_content, coordinates_json FROM history_logs WHERE user_id=? AND category=? ORDER BY generated_at DESC",
            (int(user_id), category)
        )
        return cursor.fetchall()
    finally:
        conn.close()

def get_recent_activity(user_id, category, limit=5):
    """Most recent scans for one user+category, for the topbar
    notification feed - same underlying data as get_history_logs, just
    without the heavy report_content column and with a row cap."""
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT profile_name, location, generated_at FROM history_logs WHERE user_id=? AND category=? ORDER BY generated_at DESC LIMIT ?",
            (int(user_id), category, limit)
        )
        return cursor.fetchall()
    finally:
        conn.close()

def get_last_notifications_read_at(user_id):
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT last_notifications_read_at FROM users WHERE id=?", (int(user_id),))
        row = cursor.fetchone()
        return row[0] if row else None
    finally:
        conn.close()

def mark_notifications_read(user_id):
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET last_notifications_read_at=CURRENT_TIMESTAMP WHERE id=?", (int(user_id),))
        conn.commit()
    finally:
        conn.close()

def delete_history_log(user_id, log_id):
    """Deletes a single history log entry, scoped to the owning user so one
    user can never delete another user's scan history."""
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM history_logs WHERE id=? AND user_id=?", (int(log_id), int(user_id)))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()

def delete_history_logs_older_than(user_id, days):
    """Bulk-deletes every history log entry older than `days` days ago,
    scoped to the owning user. Returns the number of rows deleted, so the
    caller can confirm exactly what happened rather than a generic
    success message."""
    cutoff = (datetime.utcnow() - timedelta(days=int(days))).strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM history_logs WHERE user_id=? AND generated_at < ?", (int(user_id), cutoff))
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()

# --- SAVED / FAVORITED PROPERTIES (with optional personal notes) ---
# A property is uniquely identified per-user by its address, since the mock
# listing generator doesn't have stable IDs across scans.

def save_property(user_id, address, title, price, beds, baths, latitude, longitude):
    """Adds a property to the user's saved/favorites list. Safe to call again
    on an already-saved property - it just updates the cached details."""
    conn = sqlite3.connect(DB_NAME)
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
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM saved_properties WHERE user_id=? AND address=?", (int(user_id), address))
        conn.commit()
    finally:
        conn.close()

def is_property_saved(user_id, address):
    """Returns True if this address is currently saved for this user."""
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM saved_properties WHERE user_id=? AND address=?", (int(user_id), address))
        return cursor.fetchone() is not None
    finally:
        conn.close()

def update_property_notes(user_id, address, notes):
    """Updates the personal notes text for a saved property."""
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE saved_properties SET notes=? WHERE user_id=? AND address=?", (notes, int(user_id), address))
        conn.commit()
    finally:
        conn.close()

def get_property_notes(user_id, address):
    """Returns the saved notes text for a property, or empty string if none."""
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT notes FROM saved_properties WHERE user_id=? AND address=?", (int(user_id), address))
        row = cursor.fetchone()
        return row[0] if row and row[0] else ""
    finally:
        conn.close()

def get_saved_properties(user_id):
    """Fetches all saved/favorited properties for a user, most recently saved first."""
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT address, title, price, beds, baths, latitude, longitude, notes, saved_at
            FROM saved_properties WHERE user_id=? ORDER BY saved_at DESC
        """, (int(user_id),))
        return cursor.fetchall()
    finally:
        conn.close()

def count_saved_properties(user_id):
    """Used by the saved-properties plan-limit gate - cheaper than fetching
    every saved property just to call len() on it."""
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM saved_properties WHERE user_id=?", (int(user_id),))
        return cursor.fetchone()[0]
    finally:
        conn.close()

# --- PERSONAL PORTFOLIO (properties the user actually owns) ---

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
# way (see the DB_NAME comment above) rather than relative to the terminal's
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
    conn = sqlite3.connect(DB_NAME)
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
    conn = sqlite3.connect(DB_NAME)
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
    conn = sqlite3.connect(DB_NAME)
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
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    try:
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
    conn = sqlite3.connect(DB_NAME)
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
    conn = sqlite3.connect(DB_NAME)
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
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM portfolio_tenants WHERE id=? AND user_id=?", (int(tenant_id), int(user_id)))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()

def get_tenants(property_id, user_id):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    try:
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
    conn = sqlite3.connect(DB_NAME)
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
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    try:
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
    conn = sqlite3.connect(DB_NAME)
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

os.makedirs(PORTFOLIO_UPLOADS_DIR, exist_ok=True)
init_db()