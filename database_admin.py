"""
database_admin.py
Admin-side user management, split out of database.py (Section 5
monolith-split plan): user listing/usage dashboards (get_all_users_
for_admin[_table], set_user_suspended, get_usage_stats,
get_recent_signups, get_top_credit_holders, get_user_activity_summary,
get_signup_stats), admin profile/role/credit/password actions
(update_user_credits_admin, update_user_profile_admin,
update_user_plan_admin, update_user_role_admin, admin_reset_password),
and create_super_user_admin - moved here despite living under a stale
"GOOGLE SIGN-IN" comment header in the original file; it is actually
the Admin Controls "Add Admins" creation path, unrelated to Google
OAuth, misfiled there by physical proximity only.

Re-exported by database.py so every db.get_all_users_for_admin(...)
etc. call site keeps working unchanged.
"""
import sqlite3

import database


def get_all_users_for_admin():
    conn = sqlite3.connect(database.DB_NAME)
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
    conn = sqlite3.connect(database.DB_NAME)
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
    conn = sqlite3.connect(database.DB_NAME)
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
    conn = sqlite3.connect(database.DB_NAME)
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

def get_recent_signups(limit=15):
    """Newest accounts first, for the Total Users stat card's drill-down
    dialog on the admin dashboard."""
    conn = sqlite3.connect(database.DB_NAME)
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
    conn = sqlite3.connect(database.DB_NAME)
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
    conn = sqlite3.connect(database.DB_NAME)
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

def get_signup_stats(trend_days=30):
    """Total registered users, how many signed up in the last 7 days (a
    fixed metric, independent of the chart window), and a day-by-day count
    for the last `trend_days` days for the admin dashboard's growth trend
    chart - the window itself is admin-adjustable, not fixed to 30."""
    conn = sqlite3.connect(database.DB_NAME)
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


def update_user_credits_admin(user_id, absolute_credits):
    conn = sqlite3.connect(database.DB_NAME)
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
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET name=?, first_name=?, middle_name=?, last_name=?, email=? WHERE id=?",
            (database._combine_name(first_name, middle_name, last_name), first_name.strip(), middle_name.strip(), last_name.strip(),
             email, int(user_id))
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def update_user_plan_admin(user_id, plan):
    """Unconditional admin set of a user's plan tier - unlike
    update_user_plan() (upgrade-only, used by the real purchase flow so a
    smaller re-purchase can't accidentally downgrade someone), this can
    also downgrade, for correcting a wrong purchase or a support request."""
    conn = sqlite3.connect(database.DB_NAME)
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
    conn = sqlite3.connect(database.DB_NAME)
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


def admin_reset_password(user_id, new_password):
    """Admin-assisted password reset for a locked-out user - secure because
    it requires an authenticated admin to act, unlike a self-service reset
    without email verification, which would let anyone reset anyone else's
    password just by knowing their email (see the self-service email-based
    reset flow below, now that an email provider is configured)."""
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET password_hash=? WHERE id=?", (database.hash_password(new_password), int(user_id)))
        conn.commit()
    finally:
        conn.close()

def create_super_user_admin(email, password, role="admin"):
    """Used by Admin Controls > Add Admins - a separate creation path from
    register_user() (no free-scan-credit signup flow, no pre-seeded first
    search), so it needs its own account_id generation too rather than
    relying on register_user()'s. Without this, a freshly-added admin would
    show a blank Account ID until the next full init_db() backfill run.
    role defaults to "admin" (see roles.py) rather than "super_admin" -
    granting the top tier is a deliberate separate choice the caller (the
    Add Admins tab, itself super_admin-only) makes explicitly."""
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO users (email, password_hash, role, credits, account_id, created_at) VALUES (?, ?, ?, 99999, ?, CURRENT_TIMESTAMP)",
            (email, database.hash_password(password), role, database._generate_account_id(cursor))
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()
