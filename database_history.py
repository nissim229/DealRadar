"""
database_history.py
Scan history logs, split out of database.py (Section 5 monolith-split
plan): save/list/delete + notification-read tracking + the live-vs-
mock scan breakdown stat. get_scan_live_mock_breakdown was previously
physically grouped near RentCast usage stats by proximity only - it
actually queries history_logs.was_live, so it belongs here. Re-
exported by database.py so db.save_history_log(...) etc. keep working
unchanged.
"""
import sqlite3
from datetime import datetime, timedelta

import database


def get_scan_live_mock_breakdown():
    """All-time and this-month counts of live (real RentCast data) vs mock
    (preview/sample) scans, from history_logs.was_live. Existing rows from
    before that column existed default to 0 (mock) - see its migration."""
    conn = sqlite3.connect(database.DB_NAME)
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

def save_history_log(user_id, profile_name, location, content, coordinates_json="", was_live=False, category="real_estate"):
    """Saves a compiled AI report output and its map coordinates to the
    history archive. was_live records whether this scan pulled real
    RentCast listings vs mock/preview data, for the admin usage dashboard.
    category distinguishes property scans from Cars scans (see
    [[cars_category_feature]]) - Cars searches log a lightweight row here
    too (empty content, no map coordinates), purely so the notification
    bell has real recent-activity data for that category, not just
    real estate."""
    conn = sqlite3.connect(database.DB_NAME)
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
    conn = sqlite3.connect(database.DB_NAME)
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
    conn = sqlite3.connect(database.DB_NAME)
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
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT last_notifications_read_at FROM users WHERE id=?", (int(user_id),))
        row = cursor.fetchone()
        return row[0] if row else None
    finally:
        conn.close()

def mark_notifications_read(user_id):
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET last_notifications_read_at=CURRENT_TIMESTAMP WHERE id=?", (int(user_id),))
        conn.commit()
    finally:
        conn.close()

def delete_history_log(user_id, log_id):
    """Deletes a single history log entry, scoped to the owning user so one
    user can never delete another user's scan history."""
    conn = sqlite3.connect(database.DB_NAME)
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
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM history_logs WHERE user_id=? AND generated_at < ?", (int(user_id), cutoff))
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()
