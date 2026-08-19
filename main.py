import streamlit as st
import database as db
import theme
import roles
from design_tokens import inject_design_tokens

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
from components.guest_landing import render_guest_landing
from components.portfolio import render_portfolio_page
from components.pricing import render_pricing_dialog
from components.settings import render_settings_page, maybe_autodetect_timezone

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
elif not st.session_state.authenticated:
    if st.session_state.show_login_form:
        if st.button("← Back to browsing"):
            st.session_state.show_login_form = False
            st.rerun()
        render_auth_portal()
    else:
        render_guest_landing()
else:
    # Inject the light/dark theme first, so topbar-specific overrides (injected
    # after) can win any CSS specificity ties and keep the navbar always dark
    # regardless of the page theme.
    if "theme_mode" not in st.session_state:
        st.session_state.theme_mode = "light"
    theme.inject_theme(st.session_state.theme_mode)
    maybe_autodetect_timezone()

    # Hide Streamlit's default chrome so our custom top bar sits flush at the top
    st.markdown("""
        <style>
            #MainMenu {visibility: hidden;}
            footer {visibility: hidden;}
            header[data-testid="stHeader"] {visibility: hidden; height: 0;}
            .block-container {padding-top: 0rem; max-width: 100%;}

            /* Style everything inside the top navbar container */
            div.st-key-scoutai_topbar {
                background-color: #0f172a !important;
                padding: 10px 28px;
                border-bottom: 1px solid #1e293b;
                margin-bottom: 20px;
            }
            div.st-key-scoutai_topbar div[data-testid="stHorizontalBlock"] {
                align-items: center;
            }

            /* Logo name + tagline - set via a real <style> rule, not an
            inline style="...!important" attribute, since Streamlit's HTML
            sanitizer silently strips !important out of inline style
            attributes (non-important inline properties like font-size
            survive fine) - this was making the "DealRadar" wordmark and
            tagline invisible against the dark navbar despite the color
            being "set" in the markdown source. */
            div.st-key-scoutai_topbar .dealradar-logo-name {
                color: white !important;
            }
            div.st-key-scoutai_topbar .dealradar-logo-tag {
                color: #94a3b8 !important;
            }

            /* Regular nav buttons */
            div.st-key-scoutai_topbar button {
                background-color: transparent !important;
                color: #cbd5e1 !important;
                border: none !important;
                font-weight: 500;
                padding: 8px 16px;
                border-radius: 6px;
            }
            div.st-key-scoutai_topbar button p,
            div.st-key-scoutai_topbar button span {
                color: #cbd5e1 !important;
            }
            div.st-key-scoutai_topbar button:hover {
                background-color: #1e293b !important;
                color: white !important;
            }
            div.st-key-scoutai_topbar button:hover p,
            div.st-key-scoutai_topbar button:hover span {
                color: white !important;
            }
            div.st-key-scoutai_topbar_active button {
                background-color: #2563eb !important;
                color: white !important;
                font-weight: 600;
            }
            div.st-key-scoutai_topbar_active button p,
            div.st-key-scoutai_topbar_active button span {
                color: white !important;
            }

            /* User popover trigger specifically - force every descendant
            transparent/light-gray, since its exact internal element structure
            isn't guaranteed and a narrower selector wasn't fully catching it.
            Scoped tightly to just this trigger (not the whole topbar) so it
            can't affect anything else, like the logo icon box. */
            div.st-key-scoutai_topbar [data-testid="stPopover"],
            div.st-key-scoutai_topbar [data-testid="stPopover"] * {
                background-color: transparent !important;
                color: #cbd5e1 !important;
                border-color: transparent !important;
            }
        </style>
    """, unsafe_allow_html=True)

    menu_options = ["Run Property Scans", "Manage Hunt Criteria", "My Portfolio"]

    with st.container(key="scoutai_topbar"):
        col_logo, col_nav, col_user = st.columns([1.4, 2.6, 1.6])

        with col_logo:
            st.markdown("""
                <div style='display: flex; align-items: center; gap: 10px;'>
                    <div style='background: linear-gradient(135deg, #2563eb, #1d4ed8); width: 34px; height: 34px; border-radius: 8px; display: flex; align-items: center; justify-content: center;'>
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                            <circle cx="12" cy="12" r="9" />
                            <circle cx="12" cy="12" r="5" />
                            <path d="M12 12 L18 6" />
                            <circle cx="17" cy="7" r="1.4" fill="white" stroke="none" />
                        </svg>
                    </div>
                    <div style='line-height: 1.1;'>
                        <span class='dealradar-logo-name' style='font-size: 16px; font-weight: 700;'>DealRadar</span>
                        <span class='dealradar-logo-tag' style='font-size: 10px; font-weight: 500; letter-spacing: 0.5px; display:block;'>PRECISION DEAL SCANNING</span>
                    </div>
                </div>
            """, unsafe_allow_html=True)

        with col_nav:
            nav_cols = st.columns(len(menu_options))
            for i, option in enumerate(menu_options):
                is_active = st.session_state.current_page == option
                with nav_cols[i]:
                    wrapper_key = "scoutai_topbar_active" if is_active else f"scoutai_topbar_inactive_{i}"
                    with st.container(key=wrapper_key):
                        if st.button(option, key=f"nav_btn_{option}", use_container_width=True):
                            st.session_state.current_page = option
                            st.rerun()

        with col_user:
            user_initial = st.session_state.user_email[0].upper() if st.session_state.user_email else "?"
            # Keyed on current_page so navigating away (e.g. clicking "Admin
            # Controls" inside this popover) gives it a fresh, closed
            # identity on the next page instead of staying open on top of
            # the new page - Streamlit popovers deliberately stay open
            # across a rerun triggered by a widget inside them (so filter
            # popovers elsewhere in the app can stay open while adjusting a
            # slider), which is right for in-place edits but wrong for a
            # full page-navigation click like this one.
            with st.popover(f":material/account_circle: {st.session_state.user_email}", use_container_width=True,
                             key=f"account_popover_{st.session_state.current_page}"):
                st.caption(f"Role: **{st.session_state.user_role.upper()}**")
                st.caption(f"Plan: **{st.session_state.user_plan}**")
                st.caption(f"Credits: **{st.session_state.user_credits}**")
                if st.button(":material/upgrade: Upgrade Plan", use_container_width=True, key="topbar_upgrade_btn"):
                    render_pricing_dialog()
                st.markdown("---")
                if st.button(":material/settings: Settings", use_container_width=True, key="topbar_settings_btn"):
                    st.session_state.current_page = "Settings"
                    st.rerun()
                st.markdown("---")

                if roles.is_staff(st.session_state.user_role):
                    if st.button(":material/shield_person: Admin Controls", use_container_width=True, key="topbar_admin_btn"):
                        st.session_state.current_page = "Admin Controls"
                        st.rerun()
                if st.button(":material/logout: Log Out", use_container_width=True, key="topbar_logout_btn"):
                    st.session_state.authenticated = False
                    st.session_state.user_id = None
                    st.session_state.user_role = "user"
                    st.session_state.user_email = None
                    st.session_state.user_name = ""
                    st.session_state.user_plan = "Free"
                    st.session_state.current_page = "Run Property Scans"
                    st.session_state.show_login_form = False
                    st.session_state.settings_show_change_password_form = False
                    st.session_state.user_settings = db.DEFAULT_USER_SETTINGS
                    st.rerun()

    broadcast_message = db.get_broadcast_message()
    if broadcast_message:
        st.info(broadcast_message, icon=":material/campaign:")

    # Route page fragments based on top nav selection
    if st.session_state.current_page == "Run Property Scans":
        render_analytics_dashboard()
    elif st.session_state.current_page == "Manage Hunt Criteria":
        render_strategy_configuration()
    elif st.session_state.current_page == "My Portfolio":
        render_portfolio_page()
    elif st.session_state.current_page == "Admin Controls":
        render_admin_control_panel()
    elif st.session_state.current_page == "Settings":
        render_settings_page()