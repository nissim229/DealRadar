"""
database_billing.py
Provider usage/config (RentCast, Auto.dev, Places, OpenAI) plus credit
packages, revenue stats, and promo codes - split out of database.py
(Section 5 monolith-split plan). These were physically interleaved
line-by-line in the original file, not contiguous per provider;
merged into one module here deliberately, since they're conceptually
one "money and API-cost tracking" domain, not because un-interleaving
them was hard. get_signup_stats (users-table growth, an admin-
dashboard stat) sat physically in the middle of this range but is NOT
part of this domain - stays in database.py for now, moves to
database_admin.py in a later step.

Re-exported by database.py so every db.get_rentcast_config(...) etc.
call site keeps working unchanged - notably plan_limits.py's
function-local `import database as db` lazy-import contract depends on
db.get_credit_packages() still resolving through the facade.
"""
import sqlite3
from datetime import datetime

import database


def log_rentcast_call(success, user_id=None):
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO rentcast_usage_log (success, user_id) VALUES (?, ?)",
                        (1 if success else 0, int(user_id) if user_id is not None else None))
        conn.commit()
    finally:
        conn.close()

def log_autodev_call(success, user_id=None):
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO autodev_usage_log (success, user_id) VALUES (?, ?)",
                        (1 if success else 0, int(user_id) if user_id is not None else None))
        conn.commit()
    finally:
        conn.close()

def get_autodev_usage_this_month():
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM autodev_usage_log WHERE strftime('%Y-%m', called_at) = strftime('%Y-%m', 'now')"
        )
        return cursor.fetchone()[0]
    finally:
        conn.close()

def log_places_call(success, user_id=None):
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO places_usage_log (success, user_id) VALUES (?, ?)",
                        (1 if success else 0, int(user_id) if user_id is not None else None))
        conn.commit()
    finally:
        conn.close()

def get_places_usage_this_month():
    conn = sqlite3.connect(database.DB_NAME)
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
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM app_settings WHERE key='places_monthly_limit'")
        row = cursor.fetchone()
        return {"monthly_limit": int(row[0]) if row else 1000}
    finally:
        conn.close()

def update_places_config(monthly_limit):
    conn = sqlite3.connect(database.DB_NAME)
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
    conn = sqlite3.connect(database.DB_NAME)
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
    conn = sqlite3.connect(database.DB_NAME)
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
    conn = sqlite3.connect(database.DB_NAME)
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


def get_plan_distribution():
    """How many users sit on each plan tier (Free/Starter/Pro/Enterprise) -
    stored on every user already via users.plan, just never surfaced."""
    conn = sqlite3.connect(database.DB_NAME)
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
    conn = sqlite3.connect(database.DB_NAME)
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
    conn = sqlite3.connect(database.DB_NAME)
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
    conn = sqlite3.connect(database.DB_NAME)
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
    conn = sqlite3.connect(database.DB_NAME)
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
    conn = sqlite3.connect(database.DB_NAME)
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
    conn = sqlite3.connect(database.DB_NAME)
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
    conn = sqlite3.connect(database.DB_NAME)
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
    conn = sqlite3.connect(database.DB_NAME)
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
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM app_settings WHERE key='rentcast_alert_sent_month'")
        row = cursor.fetchone()
        return bool(row) and row[0] == datetime.now().strftime("%Y-%m")
    finally:
        conn.close()

def mark_rentcast_alert_sent():
    conn = sqlite3.connect(database.DB_NAME)
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
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM app_settings WHERE key='openai_monthly_limit'")
        row = cursor.fetchone()
        return {"monthly_limit": int(row[0]) if row else 500}
    finally:
        conn.close()

def update_openai_config(monthly_limit):
    conn = sqlite3.connect(database.DB_NAME)
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

def get_autodev_config():
    """Admin-editable monthly cap on Auto.dev calls - previously a flat
    AUTODEV_MONTHLY_LIMIT=1000 constant in car_engine.py (that module's own
    comment already flagged promoting it to admin-editable, mirroring
    get_rentcast_config(), as intended follow-up work). Default of 1000
    matches Auto.dev's free-tier limit, the old hardcoded value."""
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM app_settings WHERE key='autodev_monthly_limit'")
        row = cursor.fetchone()
        return {"monthly_limit": int(row[0]) if row else 1000}
    finally:
        conn.close()

def update_autodev_config(monthly_limit):
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO app_settings (key, value) VALUES ('autodev_monthly_limit', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(int(monthly_limit)),)
        )
        conn.commit()
    finally:
        conn.close()

def log_openai_call(user_id=None):
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO openai_usage_log (user_id) VALUES (?)",
                        (int(user_id) if user_id is not None else None,))
        conn.commit()
    finally:
        conn.close()

def get_openai_usage_this_month():
    conn = sqlite3.connect(database.DB_NAME)
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
    conn = sqlite3.connect(database.DB_NAME)
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
    conn = sqlite3.connect(database.DB_NAME)
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
    conn = sqlite3.connect(database.DB_NAME)
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
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE promo_codes SET times_used = times_used + 1 WHERE code=?", (code,))
        conn.commit()
    finally:
        conn.close()

def set_promo_code_active(promo_id, active):
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE promo_codes SET active=? WHERE id=?", (1 if active else 0, int(promo_id)))
        conn.commit()
    finally:
        conn.close()
