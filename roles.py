"""
roles.py
Staff role hierarchy for DealRadar - who can do what inside Admin Controls.
No external dependencies (safe to import from anywhere, including
database.py and plan_limits.py, without circularity risk).

Three staff tiers, broadest to most restricted:
- super_admin: everything, including granting/changing anyone's role and
  the Pricing/Add Admins tabs - both real financial control and privilege-
  escalation surfaces, deliberately kept to the smallest possible set of
  people. Only a super_admin can ever change a role, and never their own
  (see admin_controls.py's Manage panel) - letting a lower tier touch
  roles at all would let it grant itself super_admin.
- admin: full day-to-day operations (Users, API Usage, Revenue, Broadcast)
  but can't edit pricing/cost config or create/promote other staff.
- support: narrowed to the Users tab only, and even there just the
  actions that actually help a customer (credits, suspend/reactivate,
  password reset) - not the Profile/Role/Plan edit fields.

Regular customers are role "user" and never see Admin Controls at all.
"""

STAFF_ROLES = ["support", "admin", "super_admin"]
ALL_ROLES = ["user"] + STAFF_ROLES


def is_staff(role):
    """Any staff tier - can open Admin Controls, use the free Test Scan
    button, and bypasses plan_limits caps (portfolio/saved-property/
    saved-search counts, which cost nothing real to exceed internally)."""
    return role in STAFF_ROLES


def is_admin_or_above(role):
    """Admin or super_admin - full Users-tab actions, sees Revenue, and
    gets unlimited real live scans regardless of credit balance. That last
    one has a real dollar cost (RentCast calls), so it's deliberately not
    extended to support - support doesn't need to run real property scans
    to do their job."""
    return role in ("admin", "super_admin")


def is_super_admin(role):
    return role == "super_admin"
