"""
topbar.py
The top navigation bar shared by every authenticated AND guest page - logo,
category switcher, section nav, help/alerts, and the account popover. Lives
alongside topbar_logo.py (which factors out just the logo lockup) rather
than in nav.py, which is scoped to left-side section navs, a different UI
concern (see nav.py's own docstring).

Extracted verbatim out of main.py's old inline router block so the same
navbar can render for both a real session and a guest one - is_guest=True
swaps the account popover's contents (sign-in prompt instead of email/role/
plan/credits/Settings/Admin/Logout) but leaves the logo/category/nav row
identical, which is exactly the "almost identical to the real page" parity
the guest-browsing feature is built around.
"""

import streamlit as st
import database as db
import roles
import car_engine
from data_utils import relative_time
from topbar_logo import render_topbar_logo_html
from components.pricing import render_pricing_dialog


def _usage_badge(used, limit, threshold_pct=85):
    """Shared green/amber/red bucketing for the admin-only API-usage
    badges below - same logic RentCast's badge originated, now used for
    Auto.dev and Places too. Returns (text, color), or (None, None) when
    there's nothing sensible to show (a zero/negative limit)."""
    if limit <= 0:
        return None, None
    pct = (used / limit) * 100
    if used >= limit:
        color = "red"
    elif pct >= threshold_pct:
        color = "amber"
    else:
        color = "green"
    return f"{used}/{limit}", color

CATEGORIES = [
    {"value": "real_estate", "label": "Property", "icon": ":material/home:"},
    {"value": "cars", "label": "Cars", "icon": ":material/directions_car:"},
]
CATEGORY_MENUS = {
    "real_estate": ["Run Property Scans", "History", "My Portfolio"],
    "cars": ["Find a Car", "Saved Searches"],
}


def render_main_topbar(is_guest=False):
    """Renders the navbar and the sitewide broadcast banner beneath it.
    Returns nothing - navigation/category selection is read back from
    st.session_state.current_page / active_category by main.py's router,
    same as before this was extracted into its own function."""
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

            /* Below ~900px, hiding the caption alone (above) isn't enough -
            the logo/category/nav/icon columns' own min-width floors
            (365px + 126px, see further down) no longer all fit on one row,
            and since Streamlit's own default columns don't shrink content
            to fit, they were overlapping each other instead of wrapping -
            confirmed live at 650-900px widths (the logo wordmark visibly
            overlapped the category pill). Streamlit already has a clean
            stacked layout for this - it's what naturally happens below its
            own ~640px column-stacking breakpoint (each column's min-width
            becomes 100%) - so rather than inventing a separate narrow
            treatment, this just pulls that same stacking rule earlier,
            before the overlap zone is ever reached, instead of after it.
            Confirmed at 375px the natural stacked result already reads
            fine without further adjustment. */
            @media (max-width: 900px) {
                div.st-key-scoutai_topbar > div > div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] {
                    min-width: 100% !important;
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
            div.st-key-topbar_icons_row .st-key-topbar_account_popover_wrap,
            div.st-key-topbar_icons_row [class*="st-key-topbar_usage_badge_"] {
                flex: none !important; width: fit-content !important;
            }
            /* The wraps above are GRANDchildren of topbar_icons_row - the
            REAL direct children are Streamlit's own intermediate wrapper
            divs, and THEIR flex-basis is what actually reserves each
            item's horizontal slot in the row. For three same-width 34px
            circles the fit-content rule above was enough (each wrapper's
            real content still shrank close enough to 34px that a few
            stray px of overflow just disappeared into the row's own
            10px gap) - but the RentCast badge's wider "29/50" pill (65px)
            overflowed its own ~26px-wide direct-child slot by far more
            than the gap could absorb, visibly overlapping Help next to
            it (confirmed live via getBoundingClientRect - badge left
            edge sat 28px inside Help's right edge). Sizing the true
            direct children fixes every item's slot at once, badge
            included, instead of patching the badge alone. */
            div.st-key-topbar_icons_row > div {
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

            /* Admin-only API-usage pills - rounded rectangles (hold text
            like "29/50", so a same-size circle wouldn't fit) rather than
            more identical nav icons. One shared rule set covers all three
            sources (RentCast/Auto.dev/Places, see _usage_badge below) -
            each container's key encodes BOTH which source it is and its
            live-computed color (e.g. "topbar_usage_badge_rentcast_green"),
            matched here with two class-substring selectors (source-
            agnostic shape/sizing, then a color-only selector for the
            background) instead of one rule per source. Colors are baked
            into the key as static classes, never injected via a fresh
            <style> tag on every render - that was tried first and broke
            alignment: the injected tag became an extra sibling inside the
            wrap's own default column layout, pushing the button down and
            sideways out of the row. */
            div[class*="st-key-topbar_usage_badge_"] [data-testid="stPopoverButton"] {
                color: white !important; border: none !important;
                height: 34px !important; min-height: 0 !important; width: auto !important;
                border-radius: 17px !important; padding: 0 14px !important; flex: none !important;
                display: flex !important; align-items: center !important; justify-content: center !important;
                font-weight: 700 !important;
            }
            div[class*="st-key-topbar_usage_badge_"] [data-testid="stPopoverButton"] p {
                color: white !important; margin: 0 !important; font-size: 13px !important;
                font-variant-numeric: tabular-nums !important;
            }
            div[class*="st-key-topbar_usage_badge_"] [data-testid="stPopoverButton"] div[aria-hidden="true"] {
                display: none !important;
            }
            div[class*="st-key-topbar_usage_badge_"][class*="_green"] [data-testid="stPopoverButton"] {
                background: linear-gradient(135deg, #22c55e, #16a34a) !important;
            }
            div[class*="st-key-topbar_usage_badge_"][class*="_amber"] [data-testid="stPopoverButton"] {
                background: linear-gradient(135deg, #f59e0b, #d97706) !important;
            }
            div[class*="st-key-topbar_usage_badge_"][class*="_red"] [data-testid="stPopoverButton"] {
                background: linear-gradient(135deg, #ef4444, #dc2626) !important;
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
            # This is now the DEFAULT for each category, overridable per
            # category via Admin Controls > Brand & Design's raw-HTML
            # logo editor (render_topbar_logo_html below) - an empty
            # override falls through to this coded version.
            render_topbar_logo_html(st.session_state.active_category)

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
                # Admin-only API-usage badges (RentCast/Auto.dev/Places) -
                # computed before Help renders so they land right next to
                # it in visual order ("keep track of it" without opening
                # the alerts bell or Admin Controls). Same shared-quota
                # framing as the bell's own threshold warnings below, just
                # always-visible instead of alert-only, so usage is read
                # once here and reused for both instead of querying twice.
                # Shown regardless of the active category (Property/Cars)
                # since an admin checking one category may still want a
                # glance at the other's API cost.
                usage_badges = []
                if not is_guest and roles.is_admin_or_above(st.session_state.user_role):
                    rc_conf = db.get_rentcast_config()
                    rc_text, rc_color = _usage_badge(db.get_rentcast_usage_this_month(), rc_conf["monthly_limit"], rc_conf["alert_threshold_pct"])
                    if rc_text:
                        usage_badges.append({
                            "source": "rentcast", "text": rc_text, "color": rc_color,
                            "help": f"RentCast usage this month · {rc_conf['plan_name']} plan",
                            "line1": f"**{rc_text}** RentCast calls used this month.",
                            "line2": f"Alerts fire at {rc_conf['alert_threshold_pct']}% - adjust in Admin Controls > Pricing.",
                        })

                    ad_text, ad_color = _usage_badge(db.get_autodev_usage_this_month(), car_engine.AUTODEV_MONTHLY_LIMIT)
                    if ad_text:
                        usage_badges.append({
                            "source": "autodev", "text": ad_text, "color": ad_color,
                            "help": "Auto.dev usage this month · powers Cars listings",
                            "line1": f"**{ad_text}** Auto.dev calls used this month.",
                            "line2": f"Fixed {car_engine.AUTODEV_MONTHLY_LIMIT:,}/month plan - powers real car listings.",
                        })

                    places_conf = db.get_places_config()
                    pl_text, pl_color = _usage_badge(db.get_places_usage_this_month(), places_conf["monthly_limit"])
                    if pl_text:
                        usage_badges.append({
                            "source": "places", "text": pl_text, "color": pl_color,
                            "help": "Google Places usage this month · dealer address lookups",
                            "line1": f"**{pl_text}** Places lookups used this month.",
                            "line2": "Self-declared budget (not a real Google-enforced cap) - adjust in Admin Controls > Pricing.",
                        })

                with st.container(key="topbar_help_popover_wrap"):
                    with st.popover(":material/help:", help="Help",
                                     key=f"topbar_help_popover_{st.session_state.active_category}"):
                        st.markdown(f"**How {active_category['label']} scanning works**")
                        if st.session_state.active_category == "real_estate":
                            st.caption("1. **Run Property Scans** - set your criteria and scan for deals, no setup needed.")
                            st.caption("2. **History** - every past scan, free to revisit anytime.")
                            st.caption("3. **My Portfolio** - track properties you already own.")
                        else:
                            st.caption("1. **Find a Car** - set your criteria and scan live listings.")
                            st.caption("2. **Saved Searches** - save criteria to re-run or edit later.")
                        st.markdown("---")
                        st.caption("A **deal grade** compares a listing to real market comps - "
                                    "if there isn't enough comparable data, we say so rather than guess.")

                for badge in usage_badges:
                    with st.container(key=f"topbar_usage_badge_{badge['source']}_{badge['color']}"):
                        with st.popover(badge["text"], help=badge["help"],
                                         key=f"topbar_usage_badge_popover_{badge['source']}_{st.session_state.current_page}"):
                            st.caption(badge["line1"])
                            st.caption(badge["line2"])

                if is_guest:
                    recent_activity = []
                    unread_count = 0
                else:
                    recent_activity = db.get_recent_activity(st.session_state.user_id, st.session_state.active_category, limit=5)
                    alerts_broadcast = db.get_broadcast_message()
                    alerts_broadcast_at = db.get_broadcast_message_set_at() if alerts_broadcast else None
                    last_read = db.get_last_notifications_read_at(st.session_state.user_id)
                    low_credits = st.session_state.user_credits <= 3

                    # Same badges computed above - only the framing differs
                    # (a one-time-feeling alert inside the bell vs. an
                    # always-visible number). Every source at amber/red
                    # gets its own warning line, not just RentCast.
                    usage_warnings = [
                        f"{badge['source'].capitalize()} usage at {badge['text']} this month."
                        for badge in usage_badges if badge["color"] in ("amber", "red")
                    ]

                    unread_count = sum(
                        1 for _, _, generated_at in recent_activity
                        if last_read is None or (generated_at and generated_at > last_read)
                    )
                    if alerts_broadcast and (last_read is None or (alerts_broadcast_at and alerts_broadcast_at > last_read)):
                        unread_count += 1
                    unread_count += len(usage_warnings)

                with st.container(key="topbar_alerts_popover_wrap"):
                    with st.popover(":material/notifications:", help="Alerts",
                                     key=f"topbar_alerts_popover_{st.session_state.current_page}"):
                        if is_guest:
                            st.caption("Sign in to see your activity and alerts here.")
                        else:
                            if low_credits:
                                st.warning(f"Running low on credits ({st.session_state.user_credits} left).", icon=":material/bolt:")
                            for warning_line in usage_warnings:
                                st.warning(warning_line, icon=":material/data_usage:")
                            if alerts_broadcast:
                                st.info(alerts_broadcast, icon=":material/campaign:")
                            if recent_activity:
                                st.caption(f"Recent {active_category['label']} activity")
                                for profile_name, location, generated_at in recent_activity:
                                    label = f"**{profile_name}**" + (f" — {location}" if location else "")
                                    st.caption(f"{label}  ·  {relative_time(generated_at)}")
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

                # Keyed on current_page so navigating away (e.g. clicking "Admin
                # Controls" inside this popover) gives it a fresh, closed
                # identity on the next page instead of staying open on top of
                # the new page - Streamlit popovers deliberately stay open
                # across a rerun triggered by a widget inside them (so filter
                # popovers elsewhere in the app can stay open while adjusting a
                # slider), which is right for in-place edits but wrong for a
                # full page-navigation click like this one.
                with st.container(key="topbar_account_popover_wrap"):
                    if is_guest:
                        with st.popover(":material/person:", use_container_width=False,
                                         help="Browsing as Guest - sample data only",
                                         key=f"account_popover_guest_{st.session_state.current_page}"):
                            st.caption("Browsing as **Guest**")
                            st.caption("Sample data only - nothing here is saved.")
                            if st.button(":material/login: Sign In / Register", use_container_width=True,
                                         type="primary", key="topbar_guest_signin_btn"):
                                st.session_state.show_login_form = True
                                st.rerun()
                            st.markdown("---")
                            if st.button(":material/settings: Settings", use_container_width=True, key="topbar_guest_settings_btn"):
                                st.session_state.current_page = "Settings"
                                st.rerun()
                    else:
                        user_initial = st.session_state.user_email[0].upper() if st.session_state.user_email else "?"
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
                                # Otherwise the guest view landed on right
                                # after would show this account's last real
                                # scan instead of a fresh sample one - these
                                # session keys aren't scoped to a user_id.
                                st.session_state.pop("active_scanned_report", None)
                                st.session_state.pop("active_scanned_coords", None)
                                st.session_state.pop("active_scanned_profile", None)
                                st.rerun()

    broadcast_message = db.get_broadcast_message()
    if broadcast_message:
        st.info(broadcast_message, icon=":material/campaign:")
