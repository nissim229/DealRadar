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
                background-color: var(--radar-navy) !important;
                padding: 10px 28px;
                border-bottom: 1px solid #1e293b;
                margin-bottom: 20px;
            }
            div.st-key-scoutai_topbar div[data-testid="stHorizontalBlock"] {
                align-items: center;
            }

            /* Below ~1300px (e.g. a laptop-width window with the Pro
            sidebar open) the topbar's full content genuinely doesn't fit
            on one row. Hiding the caption line is a real, if partial,
            reclaim - Streamlit's st.columns() gives each column a fixed
            percentage share regardless of content, so it doesn't
            single-handedly prevent every possible wrap at extreme
            widths, but it's a safe, honest trim (nothing functional
            depends on the caption) that helps and can't make anything
            worse, unlike forcing column widths directly (tried and
            reverted - it started clipping the "DEAL RADAR" wordmark
            itself instead of just removing dead space). */
            @media (max-width: 1300px) {
                div.st-key-scoutai_topbar .dealradar-logo-caption {
                    display: none !important;
                }
            }

            /* Premium logo lockup, round 2 - user supplied a reference
            screenshot of a circular-ring icon badge + "DEAL"/"RADAR"
            wordmark + a small descriptive caption line, replacing round
            1's rounded-square icon with a dashed spin animation + ping
            dot + mono tag pill (that spec was followed exactly too, but
            got superseded by this screenshot - "this is how the logo
            should look"). Each category gets its own color, not a shared
            one: real estate uses --radar-primary (blue, NOT admin-
            controlled), cars uses --radar-accent (cyan, admin-controlled
            via Brand & Design) - set once per render as the --logo-color
            custom property on the wrapping group so every child rule
            below can just reference var(--logo-color) instead of
            duplicating a whole rule set per category. */
            div.st-key-scoutai_topbar .dealradar-logo-group {
                display: flex; align-items: center; gap: 12px; cursor: pointer;
            }
            div.st-key-scoutai_topbar .dealradar-logo-scope {
                position: relative; width: 38px; height: 38px; flex: none;
                display: flex; align-items: center; justify-content: center;
                border-radius: 50%;
                border: 1.5px solid var(--logo-color);
                transition: box-shadow 0.3s ease;
            }
            div.st-key-scoutai_topbar .dealradar-logo-group:hover .dealradar-logo-scope {
                box-shadow: 0 0 14px rgba(var(--radar-accent-rgb), 0.25);
            }
            div.st-key-scoutai_topbar .dealradar-logo-icon {
                width: 16px; height: 16px; color: var(--logo-color) !important;
            }
            div.st-key-scoutai_topbar .dealradar-logo-text {
                display: flex; flex-direction: column; line-height: 1.2;
            }
            div.st-key-scoutai_topbar .dealradar-logo-word-row {
                display: flex; align-items: center; gap: 6px;
            }
            /* !important on every color below - Streamlit's base theme
            sets [data-testid="stAppViewContainer"] span/p/... to the
            light-theme slate text color with !important, which otherwise
            silently wins over these (non-important) rules and makes the
            wordmark/caption invisible against the dark navbar - same
            root cause round 1's own comment already warned about. */
            div.st-key-scoutai_topbar .dealradar-logo-word-deal {
                font-family: var(--radar-font-display) !important;
                font-size: 15px; font-weight: 800; color: var(--radar-text-on-dark) !important;
                text-transform: uppercase; letter-spacing: normal;
            }
            div.st-key-scoutai_topbar .dealradar-logo-word-radar {
                font-family: var(--radar-font-display) !important;
                font-size: 15px; font-weight: 800; color: var(--logo-color) !important;
                text-transform: uppercase; letter-spacing: 0.01em;
            }
            div.st-key-scoutai_topbar .dealradar-logo-caption {
                font-family: var(--radar-font-mono) !important;
                font-size: 8px; font-weight: 600; letter-spacing: 0.1em;
                color: #64748b !important; text-transform: uppercase;
                margin-top: 1px;
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
            /* Nav row labels only (not the category pill, help/alerts/
            avatar circles, or account popover - those keep their own
            fonts) - matches the monospace/uppercase/tracked caption
            style from the "Secure Sector" button test the user approved
            separately, applied here per their explicit follow-up ask. */
            div.st-key-scoutai_nav_row button p {
                font-family: 'JetBrains Mono', ui-monospace, monospace !important;
                text-transform: uppercase !important;
                letter-spacing: 0.08em !important;
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
            /* Nav labels specifically: no filled pill for the active
            item anymore - color/weight alone carry the distinction now
            (muted gray at rest, bold cyan when active), matching the
            reference caption's "plain text / bold cyan emphasis"
            contrast instead of a highlight box. Overrides the broader
            topbar button rules above for just the nav row. */
            div.st-key-scoutai_nav_row button,
            div.st-key-scoutai_nav_row button:hover {
                background-color: transparent !important;
            }
            div.st-key-scoutai_nav_row button p,
            div.st-key-scoutai_nav_row button span {
                color: #64748b !important;
                font-weight: 500 !important;
            }
            div.st-key-scoutai_nav_row button:hover p,
            div.st-key-scoutai_nav_row button:hover span {
                color: #94a3b8 !important;
            }
            div.st-key-scoutai_topbar_active button {
                background-color: transparent !important;
                color: var(--radar-accent) !important;
                font-weight: 700;
            }
            div.st-key-scoutai_topbar_active button p,
            div.st-key-scoutai_topbar_active button span {
                color: var(--radar-accent) !important;
                font-weight: 700 !important;
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

            /* Nav's own column and the icon cluster's column each get a
            hard pixel floor, not just a fractional share. Three different
            approaches to sharing one flex row between them (justify-
            content:space-between, flex:1 growth) were tried and rejected -
            Streamlit's own containers are wrapped in several layers of
            nested flex divs with inconsistent default flex-grow/basis
            behavior between layers, and forcing growth at one layer kept
            silently not propagating to the one that actually determines
            rendered width (confirmed via direct inline-style experiments
            in the live DOM, not just guessing). Two independent
            st.columns with a min-width floor is far more predictable:
            :has() lets the floor target the actual stColumn box (the
            thing that needs to not shrink) using the same key classes
            already applied to their contents - nav's floor covers the
            longest real category's button set (real-estate's 3), icons'
            floor covers the fixed 3-circle cluster (34*3 + 10*2 gaps). */
            div[data-testid="stColumn"]:has(div.st-key-scoutai_nav_row) {
                min-width: 365px !important;
            }
            div[data-testid="stColumn"]:has(div.st-key-topbar_icons_row) {
                min-width: 126px !important;
            }

            /* Help/alerts/avatar as one tight cluster, Control-M-style
            (reference image: uniform circles, small gap, hugging the right
            edge) instead of three independently-positioned columns with
            Streamlit's own inter-column gutter between them. display:flex/
            flex-direction:row overrides Streamlit's default column-
            direction stVerticalBlock. */
            div.st-key-topbar_icons_row {
                display: flex !important; flex-direction: row !important;
                align-items: center !important; justify-content: flex-end !important;
                gap: 10px !important;
                /* topbar_icons_row itself still stretches to fill
                col_icons's full column width by Streamlit's own default
                (same flex:1 1 0% pattern as everywhere else in this
                file) - width:fit-content stops it from having any
                surplus space in the first place, which is what its
                children were expanding to fill despite their own
                flex:none (confirmed live: each circle's wrapper measured
                65px, not 34px, even with grow=0 set - the surplus was
                coming from one level up, not from the children resisting
                the override). margin-left:auto keeps it flush at the
                column's right edge once it's no longer forced to stretch. */
                width: fit-content !important; flex: none !important; margin-left: auto !important;
            }
            /* The 3 popover wraps are GRANDCHILDREN of topbar_icons_row
            (an intermediate Streamlit wrapper div sits between), and each
            wrap's own stVerticalBlock div carries Streamlit's default
            flex:1 1 0% - confirmed live by walking the full parent chain,
            since an earlier `> div` (direct-child) rule was silently
            hitting the intermediate wrapper instead (already flex:0 0
            auto by default, so that rule was a no-op) while the real
            offender one level deeper kept growing each circle's own box
            to ~216px and spacing them across the whole row instead of
            clustering tight at the end. Targeting the wraps' own key
            classes directly, regardless of nesting depth, is what
            actually reaches the element that needs fixing. */
            div.st-key-topbar_icons_row .st-key-topbar_help_popover_wrap,
            div.st-key-topbar_icons_row .st-key-topbar_alerts_popover_wrap,
            div.st-key-topbar_icons_row .st-key-topbar_account_popover_wrap {
                flex: none !important; width: fit-content !important;
            }

            /* All three circles share one size/centering fix. Streamlit
            puts a -5px right margin on a popover trigger's label wrapper
            (reserved space for its own chevron, which we hide) - with the
            chevron gone that negative margin was still being counted by
            the button's flex centering, visibly skewing the glyph ~2.5px
            off-center. Zeroing every descendant div's margin removes it. */
            div.st-key-topbar_icons_row [data-testid="stPopoverButton"] div {
                margin: 0 !important;
            }

            /* Compact avatar trigger - just the user's initial in a
            circular badge, replacing the old icon+full-email button so
            the topbar reclaims width (same problem class the category
            pill dropdown solved). Hover reveals role/email via
            st.popover's native help= tooltip; click still opens the full
            menu unchanged below. */
            div.st-key-topbar_account_popover_wrap [data-testid="stPopoverButton"] {
                background: linear-gradient(135deg, #2563eb, #1d4ed8) !important;
                color: white !important;
                width: 34px !important; height: 34px !important; min-height: 0 !important;
                border-radius: 50% !important; padding: 0 !important; flex: none !important;
                display: flex !important; align-items: center !important; justify-content: center !important;
                font-weight: 700 !important; font-size: 31px !important;
            }
            div.st-key-topbar_account_popover_wrap [data-testid="stPopoverButton"] p {
                color: white !important; margin: 0 !important; font-size: 31px !important; line-height: 1 !important;
            }
            /* Streamlit auto-appends a decorative chevron (aria-hidden) as a
            descendant of the label inside every popover trigger button -
            fine for the category dropdown (it reads as a real dropdown)
            but wrong here, where the whole button IS the icon/initial. */
            div.st-key-topbar_account_popover_wrap [data-testid="stPopoverButton"] div[aria-hidden="true"] {
                display: none !important;
            }

            /* Help icon and alerts bell - same-size filled circle as the
            avatar (not a ghost/outline style anymore), each its own solid
            color so the three read as distinct actions at a glance:
            avatar blue (identity), help green (informational/safe), bell
            red (attention/alerts) - matching the user's own mockup. */
            div.st-key-topbar_help_popover_wrap [data-testid="stPopoverButton"],
            div.st-key-topbar_alerts_popover_wrap [data-testid="stPopoverButton"] {
                color: white !important;
                width: 34px !important; height: 34px !important; min-height: 0 !important;
                border: none !important;
                border-radius: 50% !important; padding: 0 !important; flex: none !important;
                display: flex !important; align-items: center !important; justify-content: center !important;
            }
            div.st-key-topbar_help_popover_wrap [data-testid="stPopoverButton"] {
                background: linear-gradient(135deg, #22c55e, #16a34a) !important;
            }
            div.st-key-topbar_alerts_popover_wrap [data-testid="stPopoverButton"] {
                background: linear-gradient(135deg, #ef4444, #dc2626) !important;
            }
            div.st-key-topbar_help_popover_wrap [data-testid="stPopoverButton"] div[aria-hidden="true"],
            div.st-key-topbar_alerts_popover_wrap [data-testid="stPopoverButton"] div[aria-hidden="true"] {
                display: none !important;
            }
            /* The visible glyph for an inline :material/x: shortcode in a
            popover's label renders as <span role="img">, NOT
            [data-testid="stIconMaterial"] (that testid only exists on
            the hidden decorative chevron, coincidentally sharing the
            "material icon" naming) - confirmed by dumping the button's
            real outerHTML, since this silently meant font-size here was
            never touching the icon anyone actually sees, stuck at
            Streamlit's own small default (~12.5px in a 34px circle,
            nowhere near the requested 90%+ fill) despite the circle
            itself rendering at the right size and color. */
            div.st-key-topbar_help_popover_wrap [data-testid="stPopoverButton"] span[role="img"],
            div.st-key-topbar_alerts_popover_wrap [data-testid="stPopoverButton"] span[role="img"] {
                font-size: 31px !important; color: white !important;
            }
            div.st-key-topbar_help_popover_wrap [data-testid="stPopoverButton"]:hover {
                background: linear-gradient(135deg, #16a34a, #15803d) !important;
            }
            div.st-key-topbar_alerts_popover_wrap [data-testid="stPopoverButton"]:hover {
                background: linear-gradient(135deg, #dc2626, #b91c1c) !important;
            }
            /* position:relative on the alerts wrapper is what lets the
            unread-count badge below overlay the button's corner instead
            of pushing layout around: the badge is a sibling markdown
            block, but position:absolute takes it out of flow and anchors
            it to this div regardless of source order. */
            div.st-key-topbar_alerts_popover_wrap { position: relative; }
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
            /* Amber, not red - the bell itself is solid red now, so a red
            badge on top of it would disappear. */
            .dealradar-alert-badge {
                position: absolute; top: -4px; right: -4px;
                background: #f59e0b; color: #451a03; font-size: 10px; font-weight: 700;
                min-width: 15px; height: 15px; border-radius: 999px;
                display: flex; align-items: center; justify-content: center;
                padding: 0 3px; line-height: 1; pointer-events: none;
                border: 1.5px solid var(--radar-navy);
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
        col_logo, col_category, col_nav, col_icons = st.columns([0.9, 1.0, 3.3, 0.9])

        with col_logo:
            # Two category-specific icons (house for real estate, car for
            # cars) inside the same "premium logo" lockup - round 2, built
            # from the user's reference screenshot (circular ring badge +
            # "DEAL"/"RADAR" wordmark + a descriptive caption line),
            # replacing round 1's rounded-square/dashed-ring/mono-tag
            # version once the user showed how it should actually look.
            # Real estate's ring/icon/RADAR-text all use --radar-primary
            # (blue, not admin-controlled); cars uses --radar-accent
            # (cyan, admin-controlled via Brand & Design) - a customer
            # browsing Cars shouldn't see a house mark or the real-estate
            # color, same reasoning as the scan-loading radar's icon swap
            # (see scan_loading.py). A custom logo uploaded via Admin
            # Controls > Brand & Design still overrides the icon entirely
            # (dropping the ring, which is chrome for *our* icon, not
            # something that should overlay someone else's uploaded
            # artwork) - the wordmark/caption stay either way.
            if st.session_state.active_category == "cars":
                icon_path_html = (
                    '<path d="M15.75 6H8.25L6.155 9.143a.75.75 0 00-.096.36V15c0 .414.336.75.75.75h1.5a.75.75 0 00.75-.75v-.75h10.5v.75a.75.75 0 00.75.75h1.5a.75.75 0 00.75-.75V9.502a.75.75 0 00-.096-.36L15.75 6zm-7.875 5.25a.75.75 0 110-1.5.75.75 0 010 1.5zm8.25 0a.75.75 0 110-1.5.75.75 0 010 1.5zM4.5 16.5h15M6 16.5v1.5a.75.75 0 01-.75.75H4.5A.75.75 0 013.75 18v-1.5M20.25 16.5V18a.75.75 0 01-.75.75h-.75a.75.75 0 01-.75-.75v-1.5" />'
                )
                caption = "PREMIUM AUTOMOTIVE TRACKER"
                logo_color_var = "var(--radar-accent)"
            else:
                icon_path_html = (
                    '<path d="M2.25 12l8.954-8.955c.44-.439 1.152-.439 1.591 0L21.75 12M4.5 9.75v10.125c0 .621.504 1.125 1.125 1.125H9.75v-4.875c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125V21h4.125c.621 0 1.125-.504 1.125-1.125V9.75M8.25 21h8.25" />'
                )
                caption = "PREMIUM REAL ESTATE LOCATOR"
                logo_color_var = "var(--radar-primary)"

            custom_logo = db.get_brand_settings()["logo_data_uri"]
            if custom_logo:
                scope_content = f"<img src='{custom_logo}' style='width: 100%; height: 100%; object-fit: cover; border-radius: 50%;' />"
            else:
                scope_content = (
                    '<svg class="dealradar-logo-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" '
                    'stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">'
                    f"{icon_path_html}</svg>"
                )

            st.markdown(
                f"<div class='dealradar-logo-group' style='--logo-color: {logo_color_var};'>"
                f"<div class='dealradar-logo-scope'>{scope_content}</div>"
                "<div class='dealradar-logo-text'>"
                "<div class='dealradar-logo-word-row'>"
                "<span class='dealradar-logo-word-deal'>DEAL</span>"
                "<span class='dealradar-logo-word-radar'>RADAR</span>"
                "</div>"
                f"<span class='dealradar-logo-caption'>{caption}</span>"
                "</div>"
                "</div>",
                unsafe_allow_html=True,
            )

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

        with col_icons:
            with st.container(key="topbar_icons_row"):
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