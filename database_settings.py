"""
database_settings.py
Sitewide app_settings-backed config, split out of database.py (Section 5
monolith-split plan): broadcast banner message, DESIGN_STANDARDS.md
override, and brand/theming settings. Re-exported by database.py so
`db.get_broadcast_message()` etc. keep working unchanged. Reads
database.DB_NAME at call time (not a copied value) so it stays correct
if that constant is ever monkeypatched, matching every other sibling
module in this split.
"""
import sqlite3
import os
import json

import database


def get_broadcast_message():
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM app_settings WHERE key='broadcast_message'")
        row = cursor.fetchone()
        return row[0] if row and row[0] else ""
    finally:
        conn.close()

def set_broadcast_message(message):
    conn = sqlite3.connect(database.DB_NAME)
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
    conn = sqlite3.connect(database.DB_NAME)
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
    conn = sqlite3.connect(database.DB_NAME)
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
    conn = sqlite3.connect(database.DB_NAME)
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
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM app_settings WHERE key='design_standards_override'")
        conn.commit()
    finally:
        conn.close()

def has_design_standards_override():
    conn = sqlite3.connect(database.DB_NAME)
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
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM app_settings WHERE key='brand_settings_json'")
        row = cursor.fetchone()
        saved = json.loads(row[0]) if row and row[0] else {}
        return {**DEFAULT_BRAND_SETTINGS, **saved}
    finally:
        conn.close()

def save_brand_settings(settings):
    conn = sqlite3.connect(database.DB_NAME)
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
    conn = sqlite3.connect(database.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM app_settings WHERE key='brand_settings_json'")
        conn.commit()
    finally:
        conn.close()
