import os
import bcrypt
from dotenv import load_dotenv

# Anchor the database file AND the .env file to this script's own directory,
# not the terminal's current working directory. Using a bare relative
# filename for the DB meant launching the app from a slightly different
# folder (or a fresh terminal session) would silently create/read a
# DIFFERENT database file - looking like saved data (profiles, theme
# preference, credits) had been forgotten, when really it was just written
# to a different file each time. A bare load_dotenv() below the DB fix has
# the identical failure mode for .env: it resolves relative to the CALLER's
# working directory/call stack, not this file's location - confirmed live
# that it finds nothing at all when database.py is imported from an
# unrelated directory. That matters a lot more for PASSWORD_PEPPER
# specifically (see _load_or_create_password_pepper()) than it does for the
# other API keys .env holds: a silently-missing pepper doesn't just misuse a
# feature, it triggers self-provisioning a BRAND NEW one, permanently
# breaking every already-bcrypt-hashed password.
DB_NAME = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_config.db")
_ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(_ENV_PATH)

BCRYPT_COST = 12

# Password hashing/verification lives in database_crypto.py (Section 5
# monolith-split - see REVIEW_LOG.md). Re-exported here so every existing
# `import database as db; db.hash_password(...)` call site (and
# tests/test_auth.py's direct db._is_bcrypt_hash/_pre_hash_password/
# _bcrypt_cost_of calls) keeps working unchanged. DB_NAME/_ENV_PATH/
# BCRYPT_COST above and PASSWORD_PEPPER/_TIMING_DUMMY_HASH below
# deliberately stay in THIS file rather than moving to database_crypto.py -
# see that module's own docstring for why.
from database_crypto import (
    _check_for_duplicate_pepper_lines,
    _any_bcrypt_hash_exists,
    _load_or_create_password_pepper,
    _pre_hash_password,
    _pre_hash_password_unkeyed,
    hash_password,
    _hash_password_legacy,
    _is_bcrypt_hash,
    _bcrypt_cost_of,
    _burn_bcrypt_time,
    _check_password,
    verify_password,
)

PASSWORD_PEPPER = _load_or_create_password_pepper()

_TIMING_DUMMY_HASH = bcrypt.hashpw(b"dummy-timing-equalizer", bcrypt.gensalt(rounds=BCRYPT_COST))

# _generate_account_id/_combine_name live in database_shared.py - used
# across multiple domains (schema seed, register_user, admin profile edit,
# Google/staff creation), so they get a shared home instead of travelling
# with one domain module. Re-exported here for the same reason as above.
from database_shared import _generate_account_id, _combine_name


from database_schema import init_db

from database_auth import (
    register_user,
    authenticate_user,
    update_user_theme_preference,
    deduct_credit,
    add_purchased_credits,
    update_user_plan,
)

from database_admin import (
    get_all_users_for_admin,
    get_all_users_for_admin_table,
    set_user_suspended,
    get_usage_stats,
    get_recent_signups,
    get_top_credit_holders,
    get_user_activity_summary,
    get_signup_stats,
    update_user_credits_admin,
    update_user_profile_admin,
    update_user_plan_admin,
    update_user_role_admin,
    admin_reset_password,
    create_super_user_admin,
)

from database_dashboard import (
    get_dashboard_layout,
    save_dashboard_layout,
    DEFAULT_USER_SETTINGS,
    get_user_settings,
    save_user_settings,
)
from database_settings import (
    get_broadcast_message,
    set_broadcast_message,
    get_broadcast_message_set_at,
    get_design_standards,
    set_design_standards_override,
    clear_design_standards_override,
    has_design_standards_override,
    DEFAULT_BRAND_SETTINGS,
    get_brand_settings,
    save_brand_settings,
    clear_brand_settings,
)

from database_billing import (
    log_rentcast_call,
    log_autodev_call,
    get_autodev_usage_this_month,
    log_places_call,
    get_places_usage_this_month,
    get_places_config,
    update_places_config,
    get_autodev_usage_by_user,
    get_rentcast_usage_this_month,
    get_rentcast_usage_by_user,
    get_plan_distribution,
    log_credit_transaction,
    get_revenue_stats,
    get_recent_transactions,
    get_credit_packages,
    update_credit_package,
    get_rentcast_config,
    update_rentcast_config,
    get_admin_staff_emails,
    was_rentcast_alert_sent_this_month,
    mark_rentcast_alert_sent,
    get_openai_config,
    update_openai_config,
    get_autodev_config,
    update_autodev_config,
    log_openai_call,
    get_openai_usage_this_month,
    create_promo_code,
    get_promo_codes,
    validate_promo_code,
    redeem_promo_code,
    set_promo_code_active,
)
from database_profile import (
    get_own_profile,
    update_own_profile,
    change_own_password,
    get_user_by_email,
    create_password_reset_token,
    validate_reset_token,
    reset_password_with_token,
)







# --- GOOGLE SIGN-IN (Google is the sole authenticator - no local password) ---
from database_oauth import get_or_create_google_user, get_google_login_only

from database_reports import save_report_config, get_all_reports, delete_report_config
from database_geocache import (
    get_cached_city_coords,
    get_cached_dealer_coords,
    cache_dealer_coords,
    get_cached_rentcast_area,
    save_rentcast_area_cache,
    cache_city_coords,
)

from database_history import (
    save_history_log,
    get_history_logs,
    get_recent_activity,
    get_last_notifications_read_at,
    mark_notifications_read,
    delete_history_log,
    delete_history_logs_older_than,
    get_scan_live_mock_breakdown,
)


# --- SAVED / FAVORITED PROPERTIES (with optional personal notes) ---
from database_saved_properties import (
    save_property,
    unsave_property,
    is_property_saved,
    update_property_notes,
    get_property_notes,
    get_saved_properties,
    count_saved_properties,
    record_price_check,
    record_price_check_not_found,
    get_saved_property_check_info,
)


# --- PERSONAL PORTFOLIO (properties the user actually owns) ---
from database_portfolio import (
    PORTFOLIO_FIELDS,
    RENTAL_STATUSES,
    PORTFOLIO_UPLOADS_DIR,
    add_portfolio_property,
    update_portfolio_property,
    delete_portfolio_property,
    get_portfolio_properties,
    add_tenant,
    update_tenant,
    delete_tenant,
    get_tenants,
    add_document,
    get_documents,
    delete_document,
)

os.makedirs(PORTFOLIO_UPLOADS_DIR, exist_ok=True)
init_db()