import streamlit as st
import database as db
import theme
import roles
from datetime import datetime
from design_tokens import inject_design_tokens


def _relative_time(timestamp_str):
    """'2026-08-19 07:31:28' (a SQLite CURRENT_TIMESTAMP string, UTC) ->
    '3 hours ago', for the alerts bell's activity feed. Deliberately a
    separate, prefix-less copy of analytics.py's _format_relative_time
    (which always prepends "Saved ") rather than importing that private
    helper across modules for a different label shape."""
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
    d = int(seconds // 86400)
    return f"{d} day{'s' if d != 1 else ''} ago"

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
                font-family: var(--radar-font-display) !important;
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
                padding: 8px 9px;
                border-radius: 6px;
                white-space: nowrap;
            }
            div.st-key-scoutai_topbar button p {
                font-size: 12.5px !important;
                white-space: nowrap;
            }
            /* Nav button row - each button sized to fit its own text
            (shrink-to-fit) rather than forced into an equal 1/3 share of
            col_nav's width, which was clipping "Manage Searches" at
            three items sharing a narrower column now that the category
            switcher takes space beside it. */
            div.st-key-scoutai_nav_row div[data-testid="stHorizontalBlock"] {
                flex-wrap: nowrap !important;
                width: auto !important;
                justify-content: flex-start !important;
                gap: 4px;
            }
            div.st-key-scoutai_nav_row div[data-testid="stColumn"] {
                width: auto !important;
                flex: 0 0 auto !important;
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
            Scoped to its own wrapper key (not the whole topbar, and not the
            category dropdown below, which needs the opposite - a solid white
            trigger) so it can't leak onto anything else. */
            div.st-key-topbar_account_popover_wrap [data-testid="stPopover"],
            div.st-key-topbar_account_popover_wrap [data-testid="stPopover"] * {
                background-color: transparent !important;
                color: #cbd5e1 !important;
                border-color: transparent !important;
            }
            /* Compact avatar trigger - just the user's initial in a circular
            badge, replacing the old icon+full-email button so the topbar
            reclaims width (same problem class the category pill dropdown
            solved). Hover reveals role/email via st.popover's native help=
            tooltip; click still opens the full menu unchanged below. These
            selectors carry equal-or-higher specificity than the generic
            transparent rule above and are declared after it, so they win
            the cascade instead of being flattened back to transparent. */
            /* Streamlit's stVerticalBlock wrapper is flex-direction:column,
            so justify-content controls the VERTICAL axis here and
            align-items controls the horizontal one - align-items is what
            actually pushes content to the wrap's right edge. (Confirmed
            live: with justify-content:flex-end the button was sitting
            ~150px left of the true edge, unaffected, since that property
            was only ever governing an axis with nothing to push against.) */
            div.st-key-topbar_account_popover_wrap { display: flex !important; align-items: flex-end !important; }
            div.st-key-topbar_account_popover_wrap [data-testid="stPopoverButton"] {
                background: linear-gradient(135deg, #2563eb, #1d4ed8) !important;
                color: white !important;
                width: 34px !important; height: 34px !important; min-height: 0 !important;
                border-radius: 50% !important; padding: 0 !important; flex: none !important;
                display: flex !important; align-items: center !important; justify-content: center !important;
                font-weight: 700 !important; font-size: 30px !important;
            }
            div.st-key-topbar_account_popover_wrap [data-testid="stPopoverButton"] p {
                color: white !important; margin: 0 !important; font-size: 30px !important; line-height: 1 !important;
            }
            /* Streamlit auto-appends a decorative chevron (aria-hidden) as a
            sibling of the label inside every popover trigger button - fine
            for the category dropdown (it reads as a real dropdown) but
            wrong here, where the whole button IS the icon/initial. */
            div.st-key-topbar_account_popover_wrap [data-testid="stPopoverButton"] div[aria-hidden="true"] {
                display: none !important;
            }

            /* Help icon trigger - small ghost circle matching the navbar's
            muted text color, consistent with the account avatar's circular
            shape but visually secondary (outline, not filled) since it's a
            reference action, not identity/navigation. */
            div.st-key-topbar_help_popover_wrap { display: flex !important; align-items: center !important; }
            div.st-key-topbar_help_popover_wrap [data-testid="stPopoverButton"] {
                background: transparent !important;
                border: 1px solid rgba(148, 163, 184, 0.35) !important;
                color: #cbd5e1 !important;
                width: 30px !important; height: 30px !important; min-height: 0 !important;
                border-radius: 50% !important; padding: 0 !important; flex: none !important;
                display: flex !important; align-items: center !important; justify-content: center !important;
            }
            div.st-key-topbar_help_popover_wrap [data-testid="stPopoverButton"] div[aria-hidden="true"] {
                display: none !important;
            }
            div.st-key-topbar_help_popover_wrap [data-testid="stPopoverButton"] [data-testid="stIconMaterial"] {
                font-size: 27px !important;
            }
            div.st-key-topbar_help_popover_wrap [data-testid="stPopoverButton"]:hover {
                background: rgba(148, 163, 184, 0.15) !important;
                color: white !important;
            }

            /* Alerts bell - same ghost-circle shape as the help icon.
            position:relative on the wrapper is what lets the unread-count
            badge below overlay the button's corner instead of pushing
            layout around: the badge is a sibling markdown block, but
            position:absolute takes it out of flow and anchors it to this
            div regardless of source order. */
            div.st-key-topbar_alerts_popover_wrap { position: relative; display: flex !important; align-items: center !important; }
            div.st-key-topbar_alerts_popover_wrap [data-testid="stPopoverButton"] {
                background: transparent !important;
                border: 1px solid rgba(148, 163, 184, 0.35) !important;
                color: #cbd5e1 !important;
                width: 30px !important; height: 30px !important; min-height: 0 !important;
                border-radius: 50% !important; padding: 0 !important; flex: none !important;
                display: flex !important; align-items: center !important; justify-content: center !important;
            }
            div.st-key-topbar_alerts_popover_wrap [data-testid="stPopoverButton"] div[aria-hidden="true"] {
                display: none !important;
            }
            div.st-key-topbar_alerts_popover_wrap [data-testid="stPopoverButton"] [data-testid="stIconMaterial"] {
                font-size: 27px !important;
            }
            div.st-key-topbar_alerts_popover_wrap [data-testid="stPopoverButton"]:hover {
                background: rgba(148, 163, 184, 0.15) !important;
                color: white !important;
            }
            /* Streamlit gives every element's own wrapper div (stElement
            Container) position:relative by default - that's a closer
            positioned ancestor than our wrap div above, so the badge's
            position:absolute was anchoring to its own snug wrapper
            (pushing it below the button in normal flow) instead of
            escaping to the wrap's corner. Resetting it to static here
            lets absolute positioning skip past it to the wrap. */
            div.st-key-topbar_alerts_popover_wrap div[data-testid="stElementContainer"] {
                position: static !important;
            }
            .dealradar-alert-badge {
                position: absolute; top: -4px; right: calc(50% - 19px);
                background: #ef4444; color: white; font-size: 10px; font-weight: 700;
                min-width: 15px; height: 15px; border-radius: 999px;
                display: flex; align-items: center; justify-content: center;
                padding: 0 3px; line-height: 1; pointer-events: none;
                border: 1.5px solid #0f172a;
            }

            /* Category dropdown - deliberately NOT styled like the nav
            buttons beside it (transparent/pill-on-hover). This picks which
            deal type the app is scanning for, which in turn decides what
            the nav buttons even are (see CATEGORY_MENUS) - so visually it
            needs to read as "governs the row next to it", not as a peer
            destination inside that row. A solid white pill trigger (the
            same white-pill language used for a selected state everywhere
            else in the app) that opens a menu, so it still reads clearly
            on the dark navbar and scales past two categories without
            needing more navbar width per category. */
            div.st-key-topbar_category_popover [data-testid="stPopoverButton"] {
                background: white !important; color: var(--radar-navy) !important;
                border: none !important; border-radius: 999px !important;
                font-weight: 600 !important; font-size: 12.5px !important;
                padding: 6px 14px !important; min-height: 0 !important; box-shadow: none !important;
                white-space: nowrap;
            }
            div.st-key-topbar_category_popover [data-testid="stPopoverButton"] p,
            div.st-key-topbar_category_popover [data-testid="stPopoverButton"] span {
                color: var(--radar-navy) !important;
            }
            /* Menu items inside the open dropdown - reuse the nav row's own
            active/hover language (blue = active, dark-hover = affordance)
            rather than inventing a third visual style for "selected". */
            /* Streamlit renders an open popover's body in a portal appended
            outside div.st-key-topbar_category_popover entirely (confirmed
            by inspecting the live DOM - the option buttons' ancestor chain
            never includes that key class), so scoping off the popover
            container doesn't reach them. Each option button carries its
            own per-category key class instead
            (st-key-topbar_category_opt_<value>, from the st.button key= in
            main.py) - matching on that substring reaches every option
            regardless of portal placement, and automatically covers any
            category added to CATEGORIES later without a new CSS rule. */
            div[class*="st-key-topbar_category_opt_"] button[kind="secondary"] {
                background: transparent !important; color: var(--radar-text) !important;
                border-radius: var(--radar-radius-sm) !important; justify-content: flex-start !important;
            }
            div[class*="st-key-topbar_category_opt_"] button[kind="secondary"]:hover {
                background: var(--radar-surface-alt) !important;
            }
            div[class*="st-key-topbar_category_opt_"] button[kind="primary"] {
                background: rgba(37,99,235,0.08) !important; color: var(--radar-primary) !important;
                border-radius: var(--radar-radius-sm) !important; justify-content: flex-start !important;
                font-weight: 700 !important;
            }
        </style>
    """, unsafe_allow_html=True)

    # Ordered list, not just CATEGORY_MENUS' keys, so a category's display
    # label/icon and its menu-item set can evolve independently and a new
    # category only needs one entry added here to show up in the dropdown.
    CATEGORIES = [
        {"value": "real_estate", "label": "Property", "icon": ":material/home:"},
        {"value": "cars", "label": "Cars", "icon": ":material/directions_car:"},
    ]
    CATEGORY_MENUS = {
        "real_estate": ["Run Property Scans", "Manage Searches", "My Portfolio"],
        "cars": ["Find a Car", "Saved Searches"],
    }
    active_category = next(c for c in CATEGORIES if c["value"] == st.session_state.active_category)
    menu_options = CATEGORY_MENUS[st.session_state.active_category]

    with st.container(key="scoutai_topbar"):
        col_logo, col_category, col_nav, col_help, col_alerts, col_user = st.columns([1.35, 0.85, 2.6, 0.35, 0.35, 0.9])

        with col_logo:
            st.markdown("""
                <div style='display: flex; align-items: center; gap: 10px; width: 100%;'>
                    <div style='background: linear-gradient(135deg, #2563eb, #1d4ed8); width: 34px; height: 34px; border-radius: 8px; display: flex; align-items: center; justify-content: center; flex: none;'>
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                            <circle cx="12" cy="12" r="9" />
                            <circle cx="12" cy="12" r="5" />
                            <path d="M12 12 L18 6" />
                            <circle cx="17" cy="7" r="1.4" fill="white" stroke="none" />
                        </svg>
                    </div>
                    <div style='line-height: 1.1; flex: none;'>
                        <span class='dealradar-logo-name' style='font-size: 16px; font-weight: 700;'>DealRadar</span>
                        <span class='dealradar-logo-tag' style='font-size: 10px; font-weight: 500; letter-spacing: 0.5px; display:block;'>PRECISION DEAL SCANNING</span>
                    </div>
                    <div style='flex: 1;'></div>
                    <div style='width: 1px; height: 28px; background: rgba(148, 163, 184, 0.35); flex: none;'></div>
                </div>
            """, unsafe_allow_html=True)

        with col_category:
            with st.container(key="topbar_category_popover"):
                trigger_label = f"{active_category['icon']} {active_category['label']}"
                # Keyed on active_category, not left implicit, so picking a
                # new category gives the popover a fresh closed identity on
                # the next rerun instead of staying open over the page it
                # just switched to - st.popover deliberately stays open
                # across a rerun triggered by a widget inside it (see
                # [[feedback-popover-navigation]]), which is right for the
                # account popover's in-place actions but wrong here, where
                # every option click is a navigation.
                with st.popover(trigger_label, use_container_width=True,
                                 key=f"topbar_category_popover_trigger_{st.session_state.active_category}"):
                    for cat in CATEGORIES:
                        is_active = cat["value"] == st.session_state.active_category
                        if st.button(f"{cat['icon']} {cat['label']}", key=f"topbar_category_opt_{cat['value']}",
                                     use_container_width=True, type="primary" if is_active else "secondary"):
                            st.session_state.active_category = cat["value"]
                            if st.session_state.current_page not in CATEGORY_MENUS[cat["value"]]:
                                st.session_state.current_page = CATEGORY_MENUS[cat["value"]][0]
                            st.rerun()

        with col_nav:
            with st.container(key="scoutai_nav_row"):
                nav_cols = st.columns(len(menu_options))
                for i, option in enumerate(menu_options):
                    is_active = st.session_state.current_page == option
                    with nav_cols[i]:
                        wrapper_key = "scoutai_topbar_active" if is_active else f"scoutai_topbar_inactive_{i}"
                        with st.container(key=wrapper_key):
                            if st.button(option, key=f"nav_btn_{option}", use_container_width=True):
                                st.session_state.current_page = option
                                st.rerun()

        with col_help:
            with st.container(key="topbar_help_popover_wrap"):
                with st.popover(":material/help:", help="Help",
                                 key=f"topbar_help_popover_{st.session_state.active_category}"):
                    st.markdown(f"**How {active_category['label']} scanning works**")
                    if st.session_state.active_category == "real_estate":
                        st.caption("1. **Run Property Scans** - set your criteria and scan for deals.")
                        st.caption("2. **Manage Searches** - save criteria to re-run or edit later.")
                        st.caption("3. **My Portfolio** - track properties you already own.")
                    else:
                        st.caption("1. **Find a Car** - set your criteria and scan live listings.")
                        st.caption("2. **Saved Searches** - save criteria to re-run or edit later.")
                    st.markdown("---")
                    st.caption("A **deal grade** compares a listing to real market comps - "
                                "if there isn't enough comparable data, we say so rather than guess.")

        with col_alerts:
            recent_activity = db.get_recent_activity(st.session_state.user_id, st.session_state.active_category, limit=5)
            alerts_broadcast = db.get_broadcast_message()
            alerts_broadcast_at = db.get_broadcast_message_set_at() if alerts_broadcast else None
            last_read = db.get_last_notifications_read_at(st.session_state.user_id)
            low_credits = st.session_state.user_credits <= 3

            unread_count = sum(
                1 for _, _, generated_at in recent_activity
                if last_read is None or (generated_at and generated_at > last_read)
            )
            if alerts_broadcast and (last_read is None or (alerts_broadcast_at and alerts_broadcast_at > last_read)):
                unread_count += 1

            with st.container(key="topbar_alerts_popover_wrap"):
                with st.popover(":material/notifications:", help="Alerts",
                                 key=f"topbar_alerts_popover_{st.session_state.current_page}"):
                    if low_credits:
                        st.warning(f"Running low on credits ({st.session_state.user_credits} left).", icon=":material/bolt:")
                    if alerts_broadcast:
                        st.info(alerts_broadcast, icon=":material/campaign:")
                    if recent_activity:
                        st.caption(f"Recent {active_category['label']} activity")
                        for profile_name, location, generated_at in recent_activity:
                            label = f"**{profile_name}**" + (f" — {location}" if location else "")
                            st.caption(f"{label}  ·  {_relative_time(generated_at)}")
                    elif not low_credits and not alerts_broadcast:
                        st.caption("Nothing yet - run a scan to see activity here.")
                    # Marking read happens on every render of an *open*
                    # popover (this code only executes while it's open - see
                    # [[feedback_popover_navigation]]'s confirmed open/closed
                    # rendering model) - idempotent, and clears the badge
                    # starting the next rerun rather than the one that just
                    # displayed it, matching normal bell-icon UX.
                    db.mark_notifications_read(st.session_state.user_id)
                if unread_count > 0:
                    st.markdown(f"<div class='dealradar-alert-badge'>{unread_count if unread_count <= 9 else '9+'}</div>", unsafe_allow_html=True)

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
            with st.container(key="topbar_account_popover_wrap"):
                with st.popover(user_initial, use_container_width=False,
                                 help=f"{st.session_state.user_email}  ·  {st.session_state.user_role.upper()}",
                                 key=f"account_popover_{st.session_state.current_page}"):
                    st.caption(st.session_state.user_email)
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
                        st.session_state.active_category = "real_estate"
                        st.session_state.show_login_form = False
                        st.session_state.settings_show_change_password_form = False
                        st.session_state.user_settings = db.DEFAULT_USER_SETTINGS
                        st.rerun()

    broadcast_message = db.get_broadcast_message()
    if broadcast_message:
        st.info(broadcast_message, icon=":material/campaign:")

    # Route page fragments based on top nav selection. Cars gets its own
    # dedicated one-page flow (components/car_search.py) rather than
    # sharing real estate's Run Scans/Manage Criteria pair - see
    # [[cars-category-feature]] for why (search runs immediately, no
    # saved-profile step first).
    if st.session_state.current_page == "Run Property Scans":
        render_analytics_dashboard()
    elif st.session_state.current_page == "Manage Searches":
        render_strategy_configuration()
    elif st.session_state.current_page == "Find a Car":
        render_car_search_page()
    elif st.session_state.current_page == "Saved Searches":
        render_saved_car_searches_page()
    elif st.session_state.current_page == "My Portfolio":
        render_portfolio_page()
    elif st.session_state.current_page == "Admin Controls":
        render_admin_control_panel()
    elif st.session_state.current_page == "Settings":
        render_settings_page()