"""
plan_limits.py
Source of truth for what each subscription tier's NAME and rank order is
(Free < Starter < Pro < Enterprise) - tier names/ordering stay code-defined
since they're structural, not something an admin needs to change day-to-day.

The actual numbers (price, credits, resource caps) used to live here as a
hardcoded dict, but are now admin-editable and stored in the database's
credit_packages table (see database.py) - DEFAULT_PLAN_LIMITS below is only
the one-time seed data for that table on a fresh install, plus a defensive
fallback if a DB read ever comes back empty.

get_limit()/is_within_limit() lazily import database.py (inside the
function body, not at module level) specifically to avoid a circular
import: database.py imports PLAN_ORDER from this file at module load time,
so this file importing database.py at module level back would deadlock.
A function-local import is safe because by the time either function
actually runs, both modules have already finished loading.
"""

DEFAULT_PLAN_LIMITS = {
    "Free":       {"price": 0,   "credits": 3,   "portfolio_properties": 1,    "saved_properties": 5,   "saved_searches": 1,  "highlight": False},
    "Starter":    {"price": 9,   "credits": 10,  "portfolio_properties": 5,    "saved_properties": 25,  "saved_searches": 3,  "highlight": False},
    "Pro":        {"price": 35,  "credits": 50,  "portfolio_properties": 20,   "saved_properties": 100, "saved_searches": 10, "highlight": True},
    "Enterprise": {"price": 120, "credits": 200, "portfolio_properties": None, "saved_properties": None, "saved_searches": None, "highlight": False},
}

PLAN_ORDER = ["Free", "Starter", "Pro", "Enterprise"]

RESOURCE_LABELS = {
    "portfolio_properties": "portfolio properties",
    "saved_properties": "saved properties",
    "saved_searches": "saved searches",
}


def plan_rank(plan):
    return PLAN_ORDER.index(plan) if plan in PLAN_ORDER else 0


def get_limit(plan, resource):
    """Returns the numeric cap for `resource` on `plan`, or None for
    unlimited. Unknown plan names fall back to Free's limits."""
    import database as db
    packages = db.get_credit_packages()
    tier = packages.get(plan, packages.get("Free", DEFAULT_PLAN_LIMITS["Free"]))
    return tier.get(resource)


def is_within_limit(role, plan, resource, current_count):
    """True if adding one more `resource` is allowed. Any staff role always
    passes, regardless of their plan column - these are internal record
    caps (max saved properties, etc.), not real external cost, so there's
    no reason to restrict this to admin-and-above the way the real-dollar
    RentCast-call bypass in analytics.py is (see roles.is_admin_or_above)."""
    from roles import is_staff
    if is_staff(role):
        return True
    limit = get_limit(plan, resource)
    return limit is None or current_count < limit
