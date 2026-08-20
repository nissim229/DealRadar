"""data_utils.py
Small, shared helpers used across the app - kept dependency-free (no
Streamlit, no app modules) so anything can import them without risk of a
circular import.
"""

from datetime import datetime


def clean_value(val):
    """Normalizes a "missing" value to None, whether it arrives as a
    plain None or as a pandas/numpy float NaN - a DataFrame column with
    some listings missing a field upcasts the missing ones to NaN, not
    None, and NaN is truthy in Python so `if val:` doesn't catch it.
    Leaves every other value - including 0, "", real strings/numbers -
    untouched."""
    if val is None:
        return None
    try:
        if isinstance(val, float) and val != val:
            return None
    except TypeError:
        pass
    return val


def relative_time(timestamp_str):
    """Turns a SQLite CURRENT_TIMESTAMP string ('2026-08-16 07:31:28', UTC)
    into a relative label like '3 hours ago' - callers prepend their own
    prefix (e.g. "Saved "). Returns the input unchanged (or "") if it
    doesn't parse, so a caller can still show *something* rather than
    erroring on bad/missing data."""
    try:
        dt = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return timestamp_str or ""
    seconds = (datetime.utcnow() - dt).total_seconds()
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        m = int(seconds // 60)
        return f"{m} minute{'s' if m != 1 else ''} ago"
    if seconds < 86400:
        h = int(seconds // 3600)
        return f"{h} hour{'s' if h != 1 else ''} ago"
    days = int(seconds // 86400)
    if days < 30:
        return f"{days} day{'s' if days != 1 else ''} ago"
    if days < 365:
        months = days // 30
        return f"{months} month{'s' if months != 1 else ''} ago"
    years = days // 365
    return f"{years} year{'s' if years != 1 else ''} ago"
