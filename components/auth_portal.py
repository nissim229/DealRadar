import streamlit as st
import database as db
import agent_engine as engine
import email_utils
import google_oauth
from icons import icon as svg_icon
from topbar_logo import render_guest_logo_html

# Local dev only - if this app is ever deployed to a real domain, the reset
# link needs to point there instead of localhost.
APP_BASE_URL = "http://localhost:8501"


def _render_auth_topbar():
    """The dark navbar this page never had - it used to be just a bare
    "Back to browsing" button floating above a plain, off-standard
    icon+wordmark header (see the removed _render_auth_header). Now
    carries the same guest logo lockup used on the landing page
    (topbar_logo.render_guest_logo_html - "DEAL RADAR GUEST", admin-
    overridable from Brand & Design), so a visitor sees one consistent
    brand mark across guest landing -> sign in/register -> the app
    itself, instead of a different logo treatment per page."""
    st.markdown("""
        <style>
        div.st-key-auth_topbar {
            background-color: var(--radar-navy);
            padding: 14px 28px;
            margin-bottom: 32px;
        }
        div.st-key-auth_topbar button {
            background-color: transparent !important;
            color: #cbd5e1 !important;
            border: 1px solid var(--radar-navy-light) !important;
            font-weight: 500 !important;
            white-space: nowrap !important;
        }
        div.st-key-auth_topbar button p {
            white-space: nowrap !important;
        }
        div.st-key-auth_topbar button:hover {
            border-color: rgba(var(--radar-accent-rgb), 0.4) !important;
            color: white !important;
        }
        </style>
    """, unsafe_allow_html=True)
    with st.container(key="auth_topbar"):
        col_logo, col_spacer, col_back = st.columns([2, 2.5, 1.5])
        with col_logo:
            render_guest_logo_html()
        with col_back:
            if st.button("← Back to browsing", key="auth_back_to_browsing_btn", use_container_width=True):
                st.session_state.show_login_form = False
                st.rerun()


def _inject_card_styles():
    st.markdown("""
        <style>
        div.st-key-auth_card {
            background: var(--radar-surface);
            border: 1px solid var(--radar-border);
            border-radius: var(--radar-radius-xl);
            box-shadow: var(--radar-shadow-lg);
            padding: var(--radar-space-7) var(--radar-space-6);
        }
        /* Sign In / Register segmented pill control */
        div.st-key-auth_mode_toggle div[role="radiogroup"] {
            background: var(--radar-surface-alt);
            border-radius: var(--radar-radius-pill);
            padding: 4px;
            gap: 0 !important;
        }
        div.st-key-auth_mode_toggle label {
            border-radius: var(--radar-radius-pill) !important;
            padding: 8px 0 !important;
            flex: 1;
            justify-content: center;
            transition: background 0.15s ease;
        }
        div.st-key-auth_mode_toggle label:has(input:checked) {
            background: var(--radar-surface) !important;
            box-shadow: var(--radar-shadow-sm);
        }
        div.st-key-auth_mode_toggle label[data-selected="true"] > div > div:first-child > div:first-child {
            background-color: var(--radar-primary) !important;
        }
        div.st-key-auth_card button[data-testid="stBaseButton-primary"] {
            background-color: var(--radar-primary) !important;
            border-color: var(--radar-primary) !important;
        }
        div.st-key-auth_card button[data-testid="stBaseButton-primary"]:hover {
            background-color: var(--radar-primary-dark) !important;
            border-color: var(--radar-primary-dark) !important;
        }
        div.st-key-auth_card button[data-testid="stBaseButton-tertiary"] {
            color: var(--radar-text-muted) !important;
            font-size: var(--radar-text-sm) !important;
        }
        div.st-key-auth_card button[data-testid="stBaseButton-tertiary"]:hover {
            color: var(--radar-primary) !important;
        }
        .auth-google-btn:hover {
            background: var(--radar-surface-alt) !important;
        }
        </style>
    """, unsafe_allow_html=True)


def _render_google_button(mode):
    auth_url = google_oauth.build_auth_url(mode)
    st.markdown(f"""
        <a href="{auth_url}" class="auth-google-btn" style='display:flex; align-items:center; justify-content:center;
            gap:10px; width:100%; box-sizing:border-box; padding:10px 0; margin-bottom: var(--radar-space-4);
            border:1px solid var(--radar-border); border-radius: var(--radar-radius-sm); background: var(--radar-surface);
            color: var(--radar-text); font-weight: var(--radar-weight-semibold); font-size: var(--radar-text-base);
            text-decoration:none;'>
            <svg width="18" height="18" viewBox="0 0 48 48">
                <path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3c-1.6 4.7-6.1 8-11.3 8-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.9 1.2 8 3.1l5.7-5.7C34.6 6.1 29.6 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.7-.4-3.5z"/>
                <path fill="#FF3D00" d="m6.3 14.7 6.6 4.8C14.6 15.1 18.9 12 24 12c3.1 0 5.9 1.2 8 3.1l5.7-5.7C34.6 6.1 29.6 4 24 4 16.3 4 9.7 8.3 6.3 14.7z"/>
                <path fill="#4CAF50" d="M24 44c5.5 0 10.4-2.1 14.1-5.6l-6.5-5.5c-2 1.4-4.6 2.3-7.6 2.3-5.2 0-9.6-3.3-11.3-7.9l-6.6 5.1C9.5 39.6 16.2 44 24 44z"/>
                <path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.3-2.2 4.2-4.1 5.6l6.5 5.5C41.6 35.6 44 30.1 44 24c0-1.3-.1-2.7-.4-3.5z"/>
            </svg>
            Continue with Google
        </a>
    """, unsafe_allow_html=True)


def _apply_login_session(user_record, email):
    st.session_state.authenticated = True
    st.session_state.user_id = user_record["id"]
    st.session_state.user_role = user_record["role"]
    st.session_state.user_credits = user_record["credits"]
    st.session_state.user_email = email
    st.session_state.user_name = user_record.get("name", "")
    st.session_state.theme_mode = user_record.get("theme_preference", "light")
    st.session_state.user_plan = user_record.get("plan", "Free")
    st.session_state.user_settings = db.get_user_settings(user_record["id"])
    # These session keys aren't scoped to a user_id - without clearing
    # them, a guest's sample scan (or another account's, on a shared
    # machine) would still be showing on Run Property Scans/History right
    # after this login, as if it were this account's own real data. Mirrors
    # the same clear on logout in topbar.py.
    st.session_state.pop("active_scanned_report", None)
    st.session_state.pop("active_scanned_coords", None)
    st.session_state.pop("active_scanned_profile", None)


def _render_no_account_found():
    pending = st.session_state.google_pending_signup
    email, name = pending["email"], pending.get("name", "")
    st.markdown(f"""
        <div style='text-align:center; margin-bottom: var(--radar-space-4);'>
            {svg_icon("alert", size=32, color="var(--radar-warning)")}
            <div style='font-size: var(--radar-text-xl); font-weight: var(--radar-weight-bold); color: var(--radar-navy); margin-top: var(--radar-space-2);'>No account found for {email}</div>
            <div style='color: var(--radar-text-muted); font-size: var(--radar-text-base); margin-top: 4px;'>Want to create one using this Google account?</div>
        </div>
    """, unsafe_allow_html=True)
    if st.button("Create my account", type="primary", use_container_width=True, key="google_create_account_btn"):
        user_record = db.get_or_create_google_user(email, name)
        st.session_state.google_pending_signup = None
        if user_record.get("suspended"):
            st.error("This account has been suspended. Contact support for help.")
        else:
            _apply_login_session(user_record, email)
            st.rerun()
    if st.button("Register manually instead", use_container_width=True, key="google_manual_register_btn"):
        st.session_state.google_pending_signup = None
        st.session_state.show_login_form = True
        st.session_state.prefill_register_email = email
        st.session_state.auth_portal_mode_selector_final = "Register New Account"
        st.rerun()
    if st.button("Back to Sign In", use_container_width=True, key="google_back_to_signin_btn"):
        st.session_state.google_pending_signup = None
        st.session_state.show_login_form = True
        st.rerun()


def handle_google_oauth_callback(code):
    """Called from main.py's router when Google redirects back with
    ?code=...&state=.... Verifies the state token was signed by us and
    hasn't expired (CSRF protection - see google_oauth.verify_state for why
    this can't just be a value stashed in st.session_state), exchanges the
    code for the user's email/name, and either signs them in or - if they
    were on the Sign In tab and no account exists - offers to create one
    instead of silently registering them behind their back."""
    _inject_card_styles()

    col1, col2, col3 = st.columns([1, 1.5, 1])
    with col2:
        _render_auth_topbar()
        with st.container(key="auth_card"):
            if st.session_state.get("google_pending_signup"):
                # The OAuth `code` is single-use and already spent by the
                # time this renders (we only get here via a rerun after the
                # first exchange found no account) - don't try it again.
                _render_no_account_found()
                return

            received_state = st.query_params.get("state")
            st.query_params.clear()
            mode = google_oauth.verify_state(received_state)

            if mode is None:
                st.error("Your Google sign-in link expired. Please try again.")
            else:
                info = google_oauth.fetch_user_info(code)
                if info is None:
                    st.error("Couldn't complete Google sign-in. Please try again or use your email and password.")
                elif mode == "register":
                    # Register-mode is forgiving: if this Google account
                    # already has a DealRadar account, just sign them in
                    # rather than dead-ending on an "already exists" error.
                    user_record = db.get_or_create_google_user(info["email"], info.get("name", ""))
                    if user_record.get("suspended"):
                        st.error("This account has been suspended. Contact support for help.")
                    else:
                        _apply_login_session(user_record, info["email"])
                        st.rerun()
                else:  # mode == "signin"
                    user_record = db.get_google_login_only(info["email"])
                    if user_record is None:
                        st.session_state.google_pending_signup = {"email": info["email"], "name": info.get("name", "")}
                        st.rerun()
                    elif user_record.get("suspended"):
                        st.error("This account has been suspended. Contact support for help.")
                    else:
                        _apply_login_session(user_record, info["email"])
                        st.rerun()

            if st.button("Back to Sign In", type="primary", use_container_width=True):
                st.session_state.show_login_form = True
                st.rerun()


def render_auth_portal():
    _render_auth_topbar()
    _inject_card_styles()
    if "prefill_register_email" in st.session_state:
        st.session_state.auth_email_input = st.session_state.pop("prefill_register_email")

    col1, col2, col3 = st.columns([1, 1.5, 1])
    with col2:
        with st.container(key="auth_card"):
            if st.session_state.get("show_forgot_password_form"):
                _render_forgot_password_form()
                return

            with st.container(key="auth_mode_toggle"):
                mode = st.radio("Account access", ["Sign In", "Register New Account"], horizontal=True,
                                 key="auth_portal_mode_selector_final", label_visibility="collapsed")
            st.markdown("<div style='height: var(--radar-space-5);'></div>", unsafe_allow_html=True)

            if google_oauth.is_google_oauth_configured():
                _render_google_button("signin" if mode == "Sign In" else "register")
                st.markdown("""
                    <div style='display:flex; align-items:center; gap: var(--radar-space-3); margin-bottom: var(--radar-space-4);
                                color: var(--radar-text-subtle); font-size: var(--radar-text-sm);'>
                        <div style='flex:1; height:1px; background: var(--radar-border);'></div>or<div style='flex:1; height:1px; background: var(--radar-border);'></div>
                    </div>
                """, unsafe_allow_html=True)

            email = st.text_input("Email", placeholder="investor@firm.com", key="auth_email_input")
            password = st.text_input("Password", type="password", placeholder="********")

            if mode == "Sign In":
                _, link_col = st.columns([2, 1])
                with link_col:
                    st.markdown("<div style='text-align:right; margin-top:-8px;'>", unsafe_allow_html=True)
                    if st.button("Forgot password?", key="forgot_pw_link", use_container_width=False, type="tertiary"):
                        st.session_state.show_forgot_password_form = True
                        st.rerun()
                    st.markdown("</div>", unsafe_allow_html=True)

                if st.button("Sign In", type="primary", use_container_width=True):
                    user_record = db.authenticate_user(email, password)
                    if user_record and user_record.get("suspended"):
                        st.error("This account has been suspended. Contact support for help.")
                    elif user_record:
                        _apply_login_session(user_record, email)
                        st.success("Signed in!")
                        st.rerun()
                    else:
                        st.error("Incorrect email or password.")
            else:
                name_col1, name_col2, name_col3 = st.columns(3)
                with name_col1:
                    first_name = st.text_input("First Name", placeholder="Jane")
                with name_col2:
                    middle_name = st.text_input("Middle Name (optional)", placeholder="")
                with name_col3:
                    last_name = st.text_input("Last Name", placeholder="Investor")

                st.markdown("<div style='margin-top:6px;'></div>", unsafe_allow_html=True)
                st.caption("Tell us what you're looking for and we'll set up your first search automatically - you can always add more or change it later.")
                intent_col1, intent_col2 = st.columns(2)
                with intent_col1:
                    target_city = st.text_input("Target City (optional)", placeholder="e.g., Denver, Colorado")
                with intent_col2:
                    target_type = st.selectbox("Property Type", ["Single Family Home", "Condo", "Multi-Family", "Townhouse"])

                st.caption("New accounts start with 3 free scan credits.")
                if st.button("Create Account", type="primary", use_container_width=True):
                    if not email or len(password) < 6:
                        st.error("Password must be at least 6 characters.")
                    elif not first_name.strip() or not last_name.strip():
                        st.error("Please enter your first and last name.")
                    else:
                        new_user_id = db.register_user(email, password, first_name.strip(), middle_name.strip(), last_name.strip())
                        if new_user_id:
                            if target_city.strip():
                                with st.spinner("Setting up your first search..."):
                                    geo_result = engine.validate_and_geocode_location(target_city.strip())
                                if geo_result:
                                    db.save_report_config(
                                        new_user_id, "My First Search", geo_result["display_name"],
                                        750000, 3, target_type, email, "08:00",
                                    )
                            st.success("Account created! Switch to Sign In to log in.")
                        else:
                            st.error("An account with this email already exists.")


def _render_forgot_password_form():
    st.markdown(f"""
        <div style='text-align:center; margin-bottom: var(--radar-space-4);'>
            {svg_icon("key", size=32, color="var(--radar-primary)")}
            <div style='font-size: var(--radar-text-xl); font-weight: var(--radar-weight-bold); color: var(--radar-navy); margin-top: var(--radar-space-2);'>Reset Your Password</div>
            <div style='color: var(--radar-text-muted); font-size: var(--radar-text-base); margin-top: 4px;'>Enter your email and we'll send you a link to set a new password.</div>
        </div>
    """, unsafe_allow_html=True)

    email = st.text_input("Email", placeholder="investor@firm.com", key="forgot_pw_email")

    if st.button("Send Reset Link", type="primary", use_container_width=True):
        if not email:
            st.error("Enter your email address.")
        elif not email_utils.is_email_configured():
            st.error("Password reset emails aren't set up yet. Contact an admin for help resetting your password.")
        else:
            user = db.get_user_by_email(email)
            # Same message whether or not the email exists / is suspended -
            # confirming which emails are or aren't registered to an
            # anonymous requester is an account-enumeration risk.
            if user and not user[1]:
                user_id, _ = user
                token = db.create_password_reset_token(user_id)
                reset_link = f"{APP_BASE_URL}/?reset_token={token}"
                email_utils.send_password_reset_email(email, reset_link)
            st.success("If that email is registered, a reset link is on its way. Check your inbox (and spam folder).")

    if st.button("← Back to Sign In", use_container_width=True):
        st.session_state.show_forgot_password_form = False
        st.rerun()


def render_reset_password_view(token):
    """Shown when the app is loaded with a ?reset_token=... query param -
    i.e. someone clicked the link from a password reset email. Reachable
    whether or not they've clicked 'Sign In' first, since an emailed link
    is the entry point here, not the normal login flow."""
    _inject_card_styles()
    col1, col2, col3 = st.columns([1, 1.5, 1])
    with col2:
        _render_auth_topbar()
        with st.container(key="auth_card"):
            if st.session_state.get("password_reset_done"):
                st.markdown(f"""
                    <div style='text-align:center; margin-bottom: var(--radar-space-4);'>
                        {svg_icon("shield-check", size=32, color="var(--radar-success)")}
                        <div style='font-size: var(--radar-text-xl); font-weight: var(--radar-weight-bold); color: var(--radar-navy); margin-top: var(--radar-space-2);'>Password Updated</div>
                        <div style='color: var(--radar-text-muted); font-size: var(--radar-text-base); margin-top: 4px;'>You can now sign in with your new password.</div>
                    </div>
                """, unsafe_allow_html=True)
                if st.button("Continue to Sign In", type="primary", use_container_width=True):
                    st.query_params.clear()
                    st.session_state.password_reset_done = False
                    st.session_state.show_login_form = True
                    st.rerun()
                return

            user_id = db.validate_reset_token(token)
            if user_id is None:
                st.markdown(f"""
                    <div style='text-align:center; margin-bottom: var(--radar-space-4);'>
                        {svg_icon("alert", size=32, color="var(--radar-danger)")}
                        <div style='font-size: var(--radar-text-xl); font-weight: var(--radar-weight-bold); color: var(--radar-navy); margin-top: var(--radar-space-2);'>This Link Has Expired</div>
                        <div style='color: var(--radar-text-muted); font-size: var(--radar-text-base); margin-top: 4px;'>Reset links are only valid for 1 hour and can only be used once. Request a new one below.</div>
                    </div>
                """, unsafe_allow_html=True)
                if st.button("Request a New Link", type="primary", use_container_width=True):
                    st.query_params.clear()
                    st.session_state.show_login_form = True
                    st.session_state.show_forgot_password_form = True
                    st.rerun()
                return

            st.markdown(f"""
                <div style='text-align:center; margin-bottom: var(--radar-space-4);'>
                    {svg_icon("shield-check", size=32, color="var(--radar-success)")}
                    <div style='font-size: var(--radar-text-xl); font-weight: var(--radar-weight-bold); color: var(--radar-navy); margin-top: var(--radar-space-2);'>Set a New Password</div>
                </div>
            """, unsafe_allow_html=True)

            new_password = st.text_input("New Password", type="password", placeholder="At least 6 characters", key="reset_new_pw")
            confirm_password = st.text_input("Confirm New Password", type="password", key="reset_confirm_pw")

            if st.button("Reset Password", type="primary", use_container_width=True):
                if len(new_password) < 6:
                    st.error("Password must be at least 6 characters.")
                elif new_password != confirm_password:
                    st.error("Passwords don't match.")
                else:
                    db.reset_password_with_token(token, new_password)
                    st.session_state.password_reset_done = True
                    st.rerun()
