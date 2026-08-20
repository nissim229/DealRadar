"""data_utils.py
Small, shared helpers for cleaning values pulled from listing data - which
shows up throughout this app both as plain dicts (straight from a scan)
and as pandas Series/DataFrame rows (the grid/table/map views), each with
different "missing value" behavior.
"""


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
