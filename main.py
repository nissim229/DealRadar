import streamlit as st
import database as db
import theme
from design_tokens import inject_design_tokens
from topbar import render_main_topbar

# 1. Global Page and Theme Layout Settings
st.set_page_config(page_title="DealRadar", layout="wide")

# Sitewide design tokens (color/spacing/radius/shadow/type vocabulary for the
# custom HTML blocks throughout this app) - injected before the router split
# so guest/auth pages get them too, not just the authenticated app.
inject_design_tokens()

# 2. Modular Component Imports from the new Components Folder
from components.auth_portal import render_auth_portal, render_reset_password_view, handle_google_oauth_callback
from components.analytics import render_analytics_dashboard
from components.strategy_config import render_strategy_configuration
from components.admin_controls import render_admin_control_panel
from components.portfolio import render_portfolio_page
from components.settings import render_settings_page, maybe_autodetect_timezone
from components.car_search import render_car_search_page, render_saved_car_searches_page

# Initialize User Account Session Memory Slots
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "user_id" not in st.session_state:
    st.session_state.user_id = None
if "user_email" not in st.session_state:
    st.session_state.user_email = None
if "user_name" not in st.session_state:
    st.session_state.user_name = ""
if "user_role" not in st.session_state:
    st.session_state.user_role = "user"
if "user_credits" not in st.session_state:
    st.session_state.user_credits = 0
if "user_plan" not in st.session_state:
    st.session_state.user_plan = "Free"
if "user_settings" not in st.session_state:
    st.session_state.user_settings = db.DEFAULT_USER_SETTINGS
if "current_page" not in st.session_state:
    st.session_state.current_page = "Run Property Scans"
if "active_category" not in st.session_state:
    # "real_estate" or "cars" - the single source of truth for which deal
    # type the app is currently scanning for, driving both the top nav's
    # own menu items (see CATEGORY_MENUS below) and every category-aware
    # page (analytics.py's dashboard, strategy_config.py's hunt criteria).
    st.session_state.active_category = "real_estate"
if "show_login_form" not in st.session_state:
    st.session_state.show_login_form = False

# --- MASTER UI ROUTER ENGINE ---
reset_token = st.query_params.get("reset_token")
oauth_code = st.query_params.get("code")
if reset_token:
    # Someone arrived via an emailed reset link - route here regardless of
    # show_login_form/authenticated state, since they won't necessarily have
    # clicked "Sign In" first.
    render_reset_password_view(reset_token)
elif (oauth_code or st.session_state.get("google_pending_signup")) and not st.session_state.authenticated:
    # Google redirected back here after the user approved sign-in. The
    # google_pending_signup branch keeps routing here on reruns after the
    # "no account found" view appears, once the one-time ?code= is gone
    # from the URL but we're still mid-flow.
    handle_google_oauth_callback(oauth_code)
elif not st.session_state.authenticated and st.session_state.show_login_form:
    # render_auth_portal() now renders its own dark navbar (logo +
    # "Back to browsing") - see components/auth_portal.py's
    # _render_auth_topbar - matching the standard navbar every other
    # page has instead of a bare, unstyled button.
    render_auth_portal()
else:
    # Both a real session and an anonymous one land here now - a first-
    # time visitor sees the exact same navbar/page set a logged-in user
    # does (not a separate marketing splash), just with is_guest=True
    # swapping the account popover for a sign-in prompt and each page's
    # data for a clearly-labeled sample, rather than a stripped-down
    # parallel UI. See [[guest_browsing_read_only_mode]].
    is_guest = not st.session_state.authenticated
    st.session_state.is_guest = is_guest
    # Inject the light/dark theme first, so topbar-specific overrides (injected
    # after) can win any CSS specificity ties and keep the navbar always dark
    # regardless of the page theme.
    if "theme_mode" not in st.session_state:
        st.session_state.theme_mode = "light"
    theme.inject_theme(st.session_state.theme_mode)
    if not is_guest:
        maybe_autodetect_timezone()

    render_main_topbar(is_guest)

    # Route page fragments based on top nav selection. Cars gets its own
    # dedicated one-page flow (components/car_search.py) rather than
    # sharing real estate's Run Scans/Manage Criteria pair - see
    # [[cars-category-feature]] for why (search runs immediately, no
    # saved-profile step first).
    # Admin Controls is never offered to a guest (the guest account popover
    # has no Admin entry, so this only guards a stale/manually-set
    # current_page) - fall back to the default page rather than let a
    # guest session reach staff-only content.
    if is_guest and st.session_state.current_page == "Admin Controls":
        st.session_state.current_page = "Run Property Scans"

    if st.session_state.current_page == "Run Property Scans":
        render_analytics_dashboard(is_guest=is_guest)
    elif st.session_state.current_page == "Manage Searches":
        render_strategy_configuration(is_guest=is_guest)
    elif st.session_state.current_page == "Find a Car":
        render_car_search_page(is_guest=is_guest)
    elif st.session_state.current_page == "Saved Searches":
        render_saved_car_searches_page(is_guest=is_guest)
    elif st.session_state.current_page == "My Portfolio":
        render_portfolio_page(is_guest=is_guest)
    elif st.session_state.current_page == "Admin Controls":
        render_admin_control_panel()
    elif st.session_state.current_page == "Settings":
        render_settings_page(is_guest=is_guest)