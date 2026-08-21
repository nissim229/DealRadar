"""
components/settings.py
The Settings page - appearance, timezone, default underwriting assumptions,
default scan view/mode, a default distance reference point, notification
preferences (with real email delivery via email_utils.py), and account
security (Change Password, moved here from the topbar account popover).

All of it (except Appearance, which keeps its own existing column - see
database.py's theme_preference) lives in one JSON blob per user
(database.py's user_settings table / get_user_settings / save_user_settings)
rather than one column each, matching the reasoning already used for
dashboard_layouts.

Laid out as a left-nav + single-section content pane (same pattern as
components/portfolio.py's property picker) rather than one long stacked
page - only the selected section renders, so there's nothing to scroll
through to reach a setting several sections down.
"""
import streamlit as st
import streamlit.components.v1 as components
from datetime import datetime
from zoneinfo import ZoneInfo, available_timezones
import database as db
import theme
import email_utils
from nav import render_top_style_subnav
from icons import icon as svg_icon
from guest_mode import guest_action_button, render_guest_banner

RESULTS_VIEW_OPTIONS = ["Properties Only", "Properties + Map", "Map Only", "Table View"]
UNDERWRITER_MODE_OPTIONS = ["Simple", "Pro"]

SETTINGS_SECTIONS = [
    ("Appearance", ":material/palette:"),
    ("Timezone", ":material/schedule:"),
    ("Default Underwriting Assumptions", ":material/calculate:"),
    ("Default Scan View & Mode", ":material/tune:"),
    ("Default Distance Reference Point", ":material/pin_drop:"),
    ("Notifications", ":material/notifications:"),
    ("Account", ":material/person:"),
]


def format_local_datetime(utc_str, tz_name=None, fmt="%b %d, %Y %I:%M %p"):
    """Converts a naive UTC timestamp string (as stored by SQLite's
    CURRENT_TIMESTAMP, e.g. history_logs.generated_at) into the user's local
    time. Explicitly labels the result "UTC" when falling back (no tz set,
    or an invalid/removed IANA name) - the ambiguity of an unlabeled server
    timestamp reading like "7:26 AM" when it's actually "10 minutes ago" in
    the user's own timezone is the exact bug this whole feature fixes, so
    the fallback case must never look like a real local time."""
    if not utc_str:
        return ""
    try:
        naive = datetime.strptime(utc_str.split(".")[0], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return utc_str
    aware_utc = naive.replace(tzinfo=ZoneInfo("UTC"))
    if tz_name:
        try:
            return aware_utc.astimezone(ZoneInfo(tz_name)).strftime(fmt)
        except Exception:
            # Deliberately silent: an invalid/removed IANA tz_name is
            # exactly the documented fallback case above - falls through
            # to the explicit "UTC"-labeled return below rather than
            # crashing the page over a stale saved timezone preference.
            pass
    return aware_utc.strftime(fmt) + " UTC"


def maybe_autodetect_timezone():
    """Runs once per user - until a timezone is saved, injects a tiny JS
    snippet that reads the browser's IANA timezone name and round-trips it
    back to Python via a URL query param + one page reload, since Streamlit
    has no native way to read browser-local info. Guarded on
    user_settings["timezone"] already being set, so this costs at most one
    extra reload ever per user, not on every page load - and a user can
    still override the detected zone from the Settings page afterward."""
    if st.session_state.user_settings.get("timezone"):
        return

    detected_tz = st.query_params.get("tz")
    if detected_tz:
        st.session_state.user_settings["timezone"] = detected_tz
        db.save_user_settings(st.session_state.user_id, st.session_state.user_settings)
        del st.query_params["tz"]
        return

    components.html("""
        <script>
        try {
            const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
            const url = new URL(window.parent.location.href);
            if (url.searchParams.get('tz') !== tz) {
                url.searchParams.set('tz', tz);
                window.parent.location.href = url.toString();
            }
        } catch (e) {}
        </script>
    """, height=0)


def _save(settings):
    st.session_state.user_settings = settings
    if st.session_state.get("is_guest"):
        # Keeps the change visible for the rest of this demo session
        # (settings widgets read back from st.session_state.user_settings),
        # just never persisted - matches every other guest write action.
        st.toast("Preview only - sign in to keep this setting.", icon=":material/lock:")
        return
    db.save_user_settings(st.session_state.user_id, settings)


def _on_theme_change(mode):
    if st.session_state.get("is_guest"):
        st.toast("Preview only - sign in to keep this setting.", icon=":material/lock:")
        return
    db.update_user_theme_preference(st.session_state.user_id, mode)


def _render_appearance(settings):
    st.markdown("##### Appearance")
    theme.theme_toggle_control(key="settings_theme_toggle", on_change=_on_theme_change)


def _render_timezone(settings):
    st.markdown("##### Timezone")
    st.caption("Used to show scan times (like your History log) in your own local time instead of the server's.")
    tz_list = sorted(available_timezones())
    current_tz = settings.get("timezone") or "UTC"
    tz_index = tz_list.index(current_tz) if current_tz in tz_list else tz_list.index("UTC")
    new_tz = st.selectbox("Timezone", tz_list, index=tz_index, key="settings_timezone_select")
    if new_tz != settings.get("timezone"):
        settings["timezone"] = new_tz
        _save(settings)
        st.toast("Timezone updated.")
    if not st.session_state.user_settings.get("timezone") or st.session_state.user_settings.get("timezone") == "UTC":
        st.caption(":material/info: Auto-detected from your browser on your next page load if not set above.")


def _render_underwriting(settings):
    st.markdown("##### Default Underwriting Assumptions")
    st.caption("Used as the starting point for every scan's financing calculator - Pro mode still lets you adjust per scan, and Simple mode uses these directly.")
    col1, col2 = st.columns(2)
    with col1:
        new_down = st.slider("Down Payment (%)", min_value=0, max_value=100, value=int(settings["default_down_pct"]), key="settings_down_pct")
        new_interest = st.number_input("Mortgage Interest Rate (%)", min_value=0.0, value=float(settings["default_interest_rate"]), step=0.25, key="settings_interest_rate")
        new_vacancy = st.slider("Vacancy Allowance (%)", min_value=0, max_value=20, value=int(settings["default_vacancy_pct"]), key="settings_vacancy_pct")
    with col2:
        new_tax = st.number_input("Annual Property Tax Rate (%)", min_value=0.0, max_value=5.0, value=float(settings["default_tax_rate"]), step=0.1, key="settings_tax_rate")
        new_ins = st.number_input("Annual Hazard Insurance Rate (%)", min_value=0.0, max_value=5.0, value=float(settings["default_insurance_rate"]), step=0.05, key="settings_ins_rate")
        new_target = st.slider("Desired Cash-on-Cash Return (%)", min_value=1.0, max_value=20.0, value=float(settings["default_target_yield"]), step=0.5, key="settings_target_yield")
    new_vals = {
        "default_down_pct": new_down, "default_interest_rate": new_interest, "default_vacancy_pct": new_vacancy,
        "default_tax_rate": new_tax, "default_insurance_rate": new_ins, "default_target_yield": new_target,
    }
    if any(settings[k] != v for k, v in new_vals.items()):
        settings.update(new_vals)
        _save(settings)
        st.toast("Default underwriting assumptions updated.")


def _render_view_mode(settings):
    st.markdown("##### Default Scan View & Mode")
    col1, col2 = st.columns(2)
    with col1:
        new_view = st.selectbox("Default results view", RESULTS_VIEW_OPTIONS,
                                 index=RESULTS_VIEW_OPTIONS.index(settings["default_results_view"]), key="settings_default_view")
    with col2:
        new_mode = st.selectbox("Default sidebar mode", UNDERWRITER_MODE_OPTIONS,
                                 index=UNDERWRITER_MODE_OPTIONS.index(settings["default_underwriter_mode"]), key="settings_default_mode")
    if new_view != settings["default_results_view"] or new_mode != settings["default_underwriter_mode"]:
        settings["default_results_view"] = new_view
        settings["default_underwriter_mode"] = new_mode
        _save(settings)
        st.toast("Default view/mode updated.")


def _render_reference_point(settings):
    st.markdown("##### Default Distance Reference Point")
    st.caption("Auto-fills the 'measure distance from' field on every scan's results (e.g. your workplace or downtown) - still editable per scan.")
    new_ref = st.text_input("Default reference address", value=settings["default_reference_address"],
                             placeholder="e.g., 1600 Pennsylvania Ave, Washington DC", key="settings_default_reference")
    if new_ref != settings["default_reference_address"]:
        settings["default_reference_address"] = new_ref
        _save(settings)
        st.toast("Default reference address updated.")


def _render_notifications(settings):
    st.markdown("##### Notifications")
    if not email_utils.is_email_configured():
        st.warning("Email isn't configured on this server yet, so notifications below won't actually send until it is - your preferences will still be saved.", icon=":material/warning:")
    new_deal = st.checkbox("Email me when a live scan finds an outstanding deal", value=settings["notify_deal_found"], key="settings_notify_deal")
    new_credits = st.checkbox("Email me when my credits run out", value=settings["notify_low_credits"], key="settings_notify_credits")
    new_pw = st.checkbox("Email me when my password changes", value=settings["notify_password_changed"], key="settings_notify_pw")
    if new_deal != settings["notify_deal_found"] or new_credits != settings["notify_low_credits"] or new_pw != settings["notify_password_changed"]:
        settings["notify_deal_found"] = new_deal
        settings["notify_low_credits"] = new_credits
        settings["notify_password_changed"] = new_pw
        _save(settings)
        st.toast("Notification preferences updated.")

    st.markdown("---")
    if guest_action_button(":material/mail: Send test email", "send a test email", key="settings_send_test_email",
                            disabled=not email_utils.is_email_configured()):
        if email_utils.send_test_email(st.session_state.user_email):
            st.success(f"Test email sent to {st.session_state.user_email} - check your inbox.")
        else:
            st.error("Couldn't send the test email. Email may not be configured correctly on this server.")


def _render_account(settings):
    st.markdown("##### Account")

    if st.session_state.get("is_guest"):
        render_guest_banner("there's no real account to show")
        st.caption("Sign in to manage your profile, password, and billing.")
        return

    profile = db.get_own_profile(st.session_state.user_id)
    if profile is None:
        st.error("Couldn't load your account profile. Please try again or contact support.")
        return
    st.caption(f"Account ID: **{profile['account_id']}** - reference this if you ever contact support.")

    st.markdown("**Profile**")
    name_col1, name_col2, name_col3 = st.columns(3)
    with name_col1:
        new_first = st.text_input("First Name", value=profile["first_name"], key="settings_profile_first_name")
    with name_col2:
        new_middle = st.text_input("Middle Name (optional)", value=profile["middle_name"], key="settings_profile_middle_name")
    with name_col3:
        new_last = st.text_input("Last Name", value=profile["last_name"], key="settings_profile_last_name")
    new_email = st.text_input("Email", value=profile["email"], key="settings_profile_email")
    new_phone = st.text_input("Phone", value=profile["phone"], placeholder="e.g., (555) 123-4567", key="settings_profile_phone")
    new_address = st.text_area("Mailing address", value=profile["address"],
                                placeholder="Street, City, State, ZIP - useful if you relocate", key="settings_profile_address")

    email_changing = new_email != profile["email"]
    profile_pw = None
    if email_changing:
        st.caption(":material/lock: Changing your email requires your current password, since it's also your sign-in username.")
        profile_pw = st.text_input("Current password", type="password", key="settings_profile_pw")

    profile_has_changes = (
        new_first != profile["first_name"] or new_middle != profile["middle_name"] or new_last != profile["last_name"] or
        new_email != profile["email"] or new_phone != profile["phone"] or new_address != profile["address"]
    )
    if st.button(":material/save: Save Profile", key="settings_save_profile_btn", type="primary", disabled=not profile_has_changes):
        if not new_first.strip() or not new_last.strip():
            st.error("First and last name can't be empty.")
        else:
            result = db.update_own_profile(st.session_state.user_id, new_first, new_middle, new_last, new_email, new_phone, new_address, profile_pw)
            if result["success"]:
                st.session_state.user_name = " ".join(p.strip() for p in [new_first, new_middle, new_last] if p and p.strip())
                st.session_state.user_email = new_email
                # st.toast, not st.success - a success message here would be
                # wiped by the st.rerun() below before it's visible (inline
                # elements don't survive a rerun; toasts do).
                st.toast("Profile updated!", icon=":material/check_circle:")
                st.rerun()
            else:
                st.error(result["error"])

    st.markdown("---")
    st.markdown("**Billing**")
    st.caption(
        "No payment method on file - billing isn't set up yet. When it is, your card details will be "
        "collected and stored directly by a licensed payment processor (e.g. Stripe), never by DealRadar "
        "itself - that's a real security/compliance requirement (PCI-DSS), not just a design choice."
    )

    st.markdown("---")
    st.markdown("**Password**")
    if st.session_state.get("settings_show_change_password_form"):
        current_pw = st.text_input("Current password", type="password", key="settings_cpw_current")
        new_pw_val = st.text_input("New password", type="password", key="settings_cpw_new")
        confirm_pw = st.text_input("Confirm new password", type="password", key="settings_cpw_confirm")
        col1, col2 = st.columns(2)
        with col1:
            # No "before" value to diff against for password fields (never
            # pre-filled, for security) - disabled until there's actually
            # something to submit instead.
            if st.button(":material/key: Update Password", use_container_width=True, key="settings_cpw_submit_btn",
                          type="primary", disabled=not (new_pw_val and confirm_pw)):
                if len(new_pw_val) < 6:
                    st.error("New password must be at least 6 characters.")
                elif new_pw_val != confirm_pw:
                    st.error("New passwords don't match.")
                elif db.change_own_password(st.session_state.user_id, current_pw, new_pw_val):
                    if st.session_state.user_settings.get("notify_password_changed"):
                        email_utils.send_password_changed_email(st.session_state.user_email)
                    st.success("Password updated!")
                    st.session_state.settings_show_change_password_form = False
                else:
                    st.error("Current password is incorrect.")
        with col2:
            if st.button("Cancel", use_container_width=True, key="settings_cpw_cancel_btn"):
                st.session_state.settings_show_change_password_form = False
                st.rerun()
    else:
        if st.button(":material/key: Change Password", key="settings_change_pw_btn"):
            st.session_state.settings_show_change_password_form = True
            st.rerun()


_SECTION_RENDERERS = {
    "Appearance": _render_appearance,
    "Timezone": _render_timezone,
    "Default Underwriting Assumptions": _render_underwriting,
    "Default Scan View & Mode": _render_view_mode,
    "Default Distance Reference Point": _render_reference_point,
    "Notifications": _render_notifications,
    "Account": _render_account,
}


def render_settings_page(is_guest=False):
    settings = dict(st.session_state.user_settings)

    st.markdown("""
        <style>
        div.st-key-settings_hero {
            background: var(--radar-gradient-hero);
            padding: var(--radar-space-6) var(--radar-space-7);
            margin-bottom: var(--radar-space-5);
            border-radius: 0 0 var(--radar-radius-xl) var(--radar-radius-xl);
        }
        div.st-key-settings_content {
            background: var(--radar-surface); border: 1px solid var(--radar-border);
            border-radius: var(--radar-radius-lg); padding: var(--radar-space-5);
        }
        </style>
    """, unsafe_allow_html=True)

    if st.button("← Back to Dashboard", key="settings_back_btn"):
        st.session_state.current_page = "Find a Car" if st.session_state.get("active_category") == "cars" else "Run Property Scans"
        st.rerun()

    with st.container(key="settings_hero"):
        st.markdown(f"""
            <div style='text-align:center; max-width:760px; margin:0 auto;'>
                <div style='display:flex; align-items:center; justify-content:center; gap:14px; margin-bottom:10px;'>
                    <div style='background: var(--radar-gradient-brand); width: 48px; height: 48px;
                                border-radius: var(--radar-radius-md); display:flex; align-items:center; justify-content:center; flex-shrink:0;'>
                        {svg_icon("settings", size=24, color="white")}
                    </div>
                    <div style='font-family:var(--radar-font-display); font-size:32px; font-weight:800; color:white; line-height:1.2;'>Settings</div>
                </div>
                <div style='font-size:16px; color:var(--radar-text-on-dark-muted);'>Your defaults, notifications, and account preferences</div>
            </div>
        """, unsafe_allow_html=True)

    active_section = render_top_style_subnav(
        [{"label": name, "icon": icon} for name, icon in SETTINGS_SECTIONS],
        key_prefix="settings_nav",
    )
    with st.container(key="settings_content"):
        _SECTION_RENDERERS[active_section](settings)
