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
from topbar_styles import TOPBAR_CSS


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
    "real_estate": ["Find Properties", "Saved Properties", "History", "My Portfolio"],
    "cars": ["Find a Car", "Saved Searches"],
}
# Icon per nav item, keyed by the exact page-name strings above - kept as a
# separate lookup rather than turning CATEGORY_MENUS into (icon, label)
# tuples, since those strings are also used as routing keys (compared
# directly against st.session_state.current_page throughout main.py and
# elsewhere) - this way nothing about routing changes, only what's
# rendered. Reuses icons already established elsewhere in the app for the
# same concept (star = saved, matching the Saved Properties page's own
# hero icon; directions_car matches the category switcher's own Cars
# icon) rather than picking new ones ad hoc.
NAV_ICONS = {
    "Find Properties": ":material/search:",
    "Saved Properties": ":material/star:",
    "History": ":material/history:",
    "My Portfolio": ":material/account_balance:",
    "Find a Car": ":material/directions_car:",
    "Saved Searches": ":material/star:",
}


def render_main_topbar(is_guest=False):
    """Renders the navbar and the sitewide broadcast banner beneath it.
    Returns nothing - navigation/category selection is read back from
    st.session_state.current_page / active_category by main.py's router,
    same as before this was extracted into its own function."""
    # Hide Streamlit's default chrome so our custom top bar sits flush at the top
    st.markdown(TOPBAR_CSS, unsafe_allow_html=True)

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
                with st.popover(trigger_label, width="stretch",
                                 key=f"topbar_category_popover_trigger_{st.session_state.active_category}"):
                    for cat in CATEGORIES:
                        is_active = cat["value"] == st.session_state.active_category
                        if st.button(f"{cat['icon']} {cat['label']}", key=f"topbar_category_opt_{cat['value']}",
                                     width="stretch", type="primary" if is_active else "secondary"):
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
                            if st.button(f"{NAV_ICONS.get(option, '')} {option}", key=f"nav_btn_{option}", width="stretch"):
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

                    autodev_conf = db.get_autodev_config()
                    ad_text, ad_color = _usage_badge(db.get_autodev_usage_this_month(), autodev_conf["monthly_limit"])
                    if ad_text:
                        usage_badges.append({
                            "source": "autodev", "text": ad_text, "color": ad_color,
                            "help": "Auto.dev usage this month · powers Cars listings",
                            "line1": f"**{ad_text}** Auto.dev calls used this month.",
                            "line2": f"{autodev_conf['monthly_limit']:,}/month plan - powers real car listings. Adjust in Admin Controls > Pricing.",
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
                            st.caption("1. **Find Properties** - set your criteria and scan for deals, no setup needed.")
                            st.caption("2. **Saved Properties** - properties you've starred, in one place.")
                            st.caption("3. **History** - every past scan, free to revisit anytime.")
                            st.caption("4. **My Portfolio** - track properties you already own.")
                        else:
                            st.caption("1. **Find a Car** - set your criteria and scan live listings.")
                            st.caption("2. **Saved Searches** - save criteria to re-run or edit later.")
                        st.markdown("---")
                        st.caption("A **deal grade** compares a listing to real market comps - "
                                    "if there isn't enough comparable data, we say so rather than guess.")

                # Design-review pass (Codex handoff + independent review):
                # this row was crowded with a separate always-visible pill
                # per API source (RentCast/Auto.dev/Places) on top of the
                # category picker, 4 nav links, Help, Alerts, and the
                # account avatar - all admin-only info, competing with
                # nav links every other user actually needs. Collapsed to
                # ONE compact icon that opens all 3 lines in a single
                # popover instead of 3 separate always-visible widgets -
                # same one-click-away detail, a third of the row space.
                # Colored by the single worst status among the 3 sources
                # (red > amber > green) so an at-risk source still catches
                # the eye without needing 3 pills to do it.
                if usage_badges:
                    worst_color = "red" if any(b["color"] == "red" for b in usage_badges) else (
                        "amber" if any(b["color"] == "amber" for b in usage_badges) else "green"
                    )
                    with st.container(key=f"topbar_usage_summary_{worst_color}"):
                        with st.popover(":material/monitoring:", help="API usage this month",
                                         key=f"topbar_usage_summary_popover_{st.session_state.current_page}"):
                            st.caption("**API usage this month**")
                            for badge in usage_badges:
                                st.caption(f"{badge['line1']} {badge['line2']}")

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
                        with st.popover(":material/person:", width="content",
                                         help="Browsing as Guest - sample data only",
                                         key=f"account_popover_guest_{st.session_state.current_page}"):
                            st.caption("Browsing as **Guest**")
                            st.caption("Sample data only - nothing here is saved.")
                            if st.button(":material/login: Sign In / Register", width="stretch",
                                         type="primary", key="topbar_guest_signin_btn"):
                                st.session_state.show_login_form = True
                                st.rerun()
                            st.markdown("---")
                            if st.button(":material/settings: Settings", width="stretch", key="topbar_guest_settings_btn"):
                                st.session_state.current_page = "Settings"
                                st.rerun()
                    else:
                        user_initial = st.session_state.user_email[0].upper() if st.session_state.user_email else "?"
                        with st.popover(user_initial, width="content",
                                         help=f"{st.session_state.user_email}  ·  {st.session_state.user_role.upper()}",
                                         key=f"account_popover_{st.session_state.current_page}"):
                            st.caption(st.session_state.user_email)
                            st.caption(f"Role: **{st.session_state.user_role.upper()}**")
                            st.caption(f"Plan: **{st.session_state.user_plan}**")
                            st.caption(f"Credits: **{st.session_state.user_credits}**")
                            if st.button(":material/upgrade: Upgrade Plan", width="stretch", key="topbar_upgrade_btn"):
                                render_pricing_dialog()
                            st.markdown("---")
                            if st.button(":material/settings: Settings", width="stretch", key="topbar_settings_btn"):
                                st.session_state.current_page = "Settings"
                                st.rerun()
                            st.markdown("---")

                            if roles.is_staff(st.session_state.user_role):
                                if st.button(":material/shield_person: Admin Controls", width="stretch", key="topbar_admin_btn"):
                                    st.session_state.current_page = "Admin Controls"
                                    st.rerun()
                            if st.button(":material/logout: Log Out", width="stretch", key="topbar_logout_btn"):
                                st.session_state.authenticated = False
                                st.session_state.user_id = None
                                st.session_state.user_role = "user"
                                st.session_state.user_email = None
                                st.session_state.user_name = ""
                                st.session_state.user_plan = "Free"
                                st.session_state.current_page = "Find Properties"
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
