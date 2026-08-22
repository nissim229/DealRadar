"""
database_dashboard.py
Per-user dashboard grid layout + Settings-page preferences, split out of
database.py (Section 5 monolith-split plan). Re-exported by database.py
so `db.get_dashboard_layout(...)`, `db.get_user_settings(...)`, and
`db.DEFAULT_USER_SETTINGS` (used directly by main.py and topbar.py to
reset a logged-out session's settings) keep working unchanged.
"""
import sqlite3
import json

import database


def get_dashboard_layout(user_id, dashboard_type):
    """Returns the saved grid layout {"grid_columns": N, "cards": [{"id","span"}, ...]}
    for this user's dashboard, or None if they've never customized it (the
    caller falls back to a built-in default layout in that case)."""
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT layout_json FROM dashboard_layouts WHERE user_id=? AND dashboard_type=?",
                        (int(user_id), dashboard_type))
        row = cursor.fetchone()
        return json.loads(row[0]) if row else None
    finally:
        conn.close()

def save_dashboard_layout(user_id, dashboard_type, layout):
    conn = sqlite3.connect(database.DB_NAME)
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
    "default_cards_per_row": 3,
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
    # Same "opt-in feature notification" bucket as notify_deal_found above -
    # a price drop on a saved property is closer to a nice-to-have alert
    # than an account-status one.
    "notify_price_drop": False,
}


def get_user_settings(user_id):
    """Returns this user's Settings-page preferences, with any keys missing
    from an older saved blob (or a user who's never saved one at all)
    backfilled from DEFAULT_USER_SETTINGS - same missing-key-tolerance
    reasoning as dashboard_grid.py's layout backfill, so adding a new
    setting later never breaks an existing saved row."""
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT settings_json FROM user_settings WHERE user_id=?", (int(user_id),))
        row = cursor.fetchone()
        saved = json.loads(row[0]) if row and row[0] else {}
        return {**DEFAULT_USER_SETTINGS, **saved}
    finally:
        conn.close()


def save_user_settings(user_id, settings):
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO user_settings (user_id, settings_json, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET settings_json=excluded.settings_json, updated_at=excluded.updated_at
        """, (int(user_id), json.dumps(settings)))
        conn.commit()
    finally:
        conn.close()

