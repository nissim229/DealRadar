import base64
import streamlit as st
import pandas as pd
import database as db
import agent_engine as engine
import car_engine
import email_utils
import plan_limits
import roles
import design_tokens
import topbar_logo
from icons import icon as svg_icon
from dashboard_grid import render_dashboard_grid
from nav import render_side_nav

# Uploaded logos are stored inline as base64 data URIs in app_settings
# (same generic key/value table as everything else here) rather than as
# files on disk - this app has no existing static-asset upload pipeline,
# and a data URI needs no separate serving route. Capped well under
# SQLite/Streamlit's practical limits for a single small logo image.
_MAX_LOGO_BYTES = 900_000


@st.dialog("Recent Signups")
def _show_signups_dialog():
    recent = db.get_recent_signups()
    if not recent:
        st.caption("No users yet.")
    else:
        st.dataframe(
            pd.DataFrame(
                [{"Name": name or "-", "Email": email, "Plan": plan, "Joined": (created_at or "")[:10]}
                 for email, name, plan, created_at in recent]
            ),
            use_container_width=True, hide_index=True, height=len(recent) * 35 + 38,
        )
    st.caption("Full list with credits, scans, and spend is in the Users tab.")


@st.dialog("Scan Activity")
def _show_scans_dialog(scan_breakdown):
    st.caption("A scan is 'live' when it pulled real RentCast listings; 'mock/preview' covers admin Test Scans, out-of-credit scans, and guest previews.")
    col1, col2 = st.columns(2)
    with col1:
        st.metric("This Month", f"{scan_breakdown['live_this_month']} live", f"{scan_breakdown['mock_this_month']} mock/preview")
    with col2:
        st.metric("All Time", f"{scan_breakdown['live_all_time']} live", f"{scan_breakdown['mock_all_time']} mock/preview")
    st.caption("Per-user RentCast call breakdown is in the API Usage tab.")


@st.dialog("Revenue")
def _show_revenue_dialog(revenue_stats):
    st.caption(f"{svg_icon('lightbulb', size=13, color='var(--radar-text-subtle)')} Simulated - no real payment processor is wired up yet.", unsafe_allow_html=True)
    col1, col2 = st.columns(2)
    with col1:
        st.metric("This Month", f"${revenue_stats['total_this_month']:,.0f}", f"{revenue_stats['count_this_month']} purchase(s)")
    with col2:
        st.metric("All Time", f"${revenue_stats['total_all_time']:,.0f}", f"{revenue_stats['count_all_time']} purchase(s)")
    recent_tx = db.get_recent_transactions(limit=8)
    if recent_tx:
        st.markdown("**Latest purchases**")
        st.dataframe(
            pd.DataFrame(
                [{"User": f"{name} ({email})" if name else email, "Package": pkg, "Amount": f"${amt:,.0f}", "Date": purchased_at}
                 for email, name, pkg, amt, credits, purchased_at in recent_tx]
            ),
            use_container_width=True, hide_index=True, height=len(recent_tx) * 35 + 38,
        )
    st.caption("Full transaction ledger and plan breakdown is in the Revenue tab.")


@st.dialog("Credits Outstanding")
def _show_credits_dialog():
    top_holders = db.get_top_credit_holders()
    if not top_holders:
        st.caption("No users yet.")
    else:
        st.markdown("**Highest balances**")
        st.dataframe(
            pd.DataFrame(
                [{"Name": name or "-", "Email": email, "Credits": credits, "Plan": plan}
                 for email, name, credits, plan in top_holders]
            ),
            use_container_width=True, hide_index=True, height=len(top_holders) * 35 + 38,
        )
    st.caption("Users at 0 credits (upsell targets) are listed below the stat cards on the main dashboard.")


def _clear_manage_user_target():
    st.session_state.admin_selected_user_id = None


@st.dialog("Manage User", width="large", on_dismiss=_clear_manage_user_target)
def _manage_user_dialog(selected_row, current_role):
    """The floating-dialog version of what used to be an always-inline
    panel below the table (see [[table_action_pattern]] for the app-wide
    standard this now matches). Kept as one dialog covering every action
    (profile, credits, suspend, password reset) rather than split into
    pencil/trash icons - a user row doesn't decompose into a simple edit/
    delete pair the way a saved search does (there's no "delete a user"
    action at all, deliberately - see the Table View memory's note that
    no delete_user function exists), so the single "Manage" entry point
    stays, just as a real overlay now instead of an inline block.

    on_dismiss=_clear_manage_user_target matters, not just the explicit
    Close button below: confirmed live that dismissing via the native X
    (or Esc/click-outside) left admin_selected_user_id set, so the very
    next unrelated interaction anywhere on the page (paging, changing
    rows-per-page) silently reopened this same dialog - on_dismiss is the
    one hook that fires for every dismissal path, not just a button
    inside the dialog's own body."""
    (u_id, u_email, u_name, u_role, u_plan, u_credits, u_suspended, u_created_at,
     u_scan_count, u_live_scan_count, u_rentcast_calls, u_total_spent,
     u_account_id, u_first_name, u_middle_name, u_last_name) = selected_row

    suspended_badge = " · :red[SUSPENDED]" if u_suspended else ""
    display_name = f"{u_name} · " if u_name else ""
    st.markdown(f"**{display_name}{u_email}** &nbsp;·&nbsp; {u_role.upper()} · {u_plan}{suspended_badge}")
    st.caption(f"Account ID: {u_account_id or '-'} · {u_scan_count} scan(s) run ({u_live_scan_count} live) · {u_rentcast_calls} RentCast call(s) · ${u_total_spent:,.0f} spent (demo) · joined {(u_created_at or '')[:10]}")

    # Full profile edit - covers the support-ticket case where a user
    # has a typo'd name/wrong email and can't fix it themselves. Not
    # shown to support - scoped to admin and above.
    if current_role != "support":
        # Legacy accounts (created before first/middle/last existed)
        # have empty structured-name columns even though their old
        # combined `name` is set - defaulting the fields to blank in
        # that case would silently blank the name on save (it gets
        # rebuilt from these three fields). Best-effort split the
        # legacy name into the fields instead, same convention as the
        # Google-signup name split, so what's shown matches what's
        # actually saved.
        if not (u_first_name or u_last_name) and u_name:
            _legacy_parts = u_name.strip().split(" ", 1)
            _default_first = _legacy_parts[0]
            _default_last = _legacy_parts[1] if len(_legacy_parts) > 1 else ""
        else:
            _default_first, _default_last = u_first_name or "", u_last_name or ""

        st.markdown("**Profile**")
        name_col1, name_col2, name_col3 = st.columns(3)
        with name_col1:
            new_first = st.text_input("First Name", value=_default_first, key=f"user_first_name_field_{u_id}")
        with name_col2:
            new_middle = st.text_input("Middle Name (optional)", value=u_middle_name or "", key=f"user_middle_name_field_{u_id}")
        with name_col3:
            new_last = st.text_input("Last Name", value=_default_last, key=f"user_last_name_field_{u_id}")
        prof_col1, prof_col2, prof_col3 = st.columns(3)
        with prof_col1:
            new_email = st.text_input("Email", value=u_email, key=f"user_email_field_{u_id}")
        with prof_col2:
            # Only a super_admin can change ANYONE's role, and never
            # their own (self-lockout / self-escalation risk) - see
            # roles.py. Everyone else just sees it as read-only text.
            can_edit_role = current_role == "super_admin" and u_id != st.session_state.user_id
            if can_edit_role:
                role_options = roles.ALL_ROLES
                new_role = st.selectbox("Role", role_options,
                                         index=role_options.index(u_role) if u_role in role_options else 0,
                                         key=f"user_role_field_{u_id}")
            else:
                new_role = u_role
                st.text_input("Role", value=u_role.upper(), disabled=True, key=f"user_role_field_ro_{u_id}",
                              help="Only a super_admin can change someone else's role.")
        with prof_col3:
            new_plan = st.selectbox("Plan", plan_limits.PLAN_ORDER, index=plan_limits.PLAN_ORDER.index(u_plan) if u_plan in plan_limits.PLAN_ORDER else 0, key=f"user_plan_field_{u_id}")

        # Disabled until a field actually differs from what's on file -
        # compared against the freshly-fetched DB values (u_*), not a
        # separately-tracked "original" snapshot, so the button greys
        # back out on its own right after a save (the next rerun's u_*
        # already reflects the just-saved values).
        profile_has_changes = (
            new_first.strip() != _default_first or new_middle.strip() != (u_middle_name or "") or
            new_last.strip() != _default_last or new_email.strip() != u_email or
            (can_edit_role and new_role != u_role) or new_plan != u_plan
        )
        if st.button(":material/save: Save Profile", key=f"user_profile_save_btn_{u_id}", use_container_width=True, disabled=not profile_has_changes):
            if not new_email.strip():
                st.error("Email can't be empty.")
            elif db.update_user_profile_admin(u_id, new_first.strip(), new_middle.strip(), new_last.strip(), new_email.strip()):
                if can_edit_role and new_role != u_role:
                    if not db.update_user_role_admin(u_id, new_role):
                        st.toast("Profile saved, but that role change was blocked - can't demote the last super_admin.", icon=":material/warning:")
                db.update_user_plan_admin(u_id, new_plan)
                # st.toast, not st.success - a success message here would
                # be wiped by the st.rerun() below before it's visible
                # (inline elements don't survive a rerun; toasts do).
                st.toast(f"Updated profile for {new_email}.", icon=":material/check_circle:")
                if u_id == st.session_state.user_id:
                    st.session_state.user_plan = new_plan
                st.rerun()
            else:
                st.error("That email is already in use by another account.")

    st.markdown("**Credits**")
    col_u2, col_u3, col_u4 = st.columns([1.3, 1, 1.6])
    with col_u2:
        # Key includes u_credits itself, not just u_id - confirmed live
        # that popping the plain-u_id key and calling st.rerun() (the
        # normal fix for this class of bug elsewhere in the app, e.g.
        # car_search.py's Make/Model reset) was NOT enough for a
        # number_input inside an open st.dialog specifically: both +5
        # Bonus clicks wrote to the DB correctly (confirmed by direct query
        # each time) but the dialog kept displaying the pre-click number
        # regardless. Baking the current value into the key sidesteps
        # whatever dialog/fragment-rerun quirk causes that - a changed
        # u_credits always means a genuinely new widget identity, so there
        # is no stale session_state for it to fall back to.
        new_cred = st.number_input("Credits", min_value=0, value=u_credits, key=f"user_cred_field_{u_id}_{u_credits}")
    with col_u3:
        st.markdown("<div style='margin-top:28px;'></div>", unsafe_allow_html=True)
        if st.button(":material/save: Save", key=f"user_save_btn_{u_id}", use_container_width=True, disabled=new_cred == u_credits):
            db.update_user_credits_admin(u_id, new_cred)
            st.toast(f"Updated credits for {u_email}.", icon=":material/check_circle:")
            if u_id == st.session_state.user_id:
                st.session_state.user_credits = new_cred
            st.rerun()
    with col_u4:
        st.markdown("<div style='margin-top:28px;'></div>", unsafe_allow_html=True)
        if st.button(":material/add_card: +5 Bonus", key=f"user_bonus_btn_{u_id}", use_container_width=True,
                     help="Grant 5 free credits (e.g. as a support goodwill gesture)"):
            db.add_purchased_credits(u_id, 5)
            st.toast(f"Added 5 bonus credits for {u_email}.")
            if u_id == st.session_state.user_id:
                st.session_state.user_credits += 5
            st.rerun()

    with st.popover(":material/more_horiz: More actions", key=f"user_more_popover_{u_id}"):
        if not roles.is_staff(u_role):
            suspend_label = ":material/lock_open: Reactivate Account" if u_suspended else ":material/block: Suspend Account"
            if st.button(suspend_label, key=f"user_suspend_btn_{u_id}", use_container_width=True):
                db.set_user_suspended(u_id, not u_suspended)
                st.toast(f"{'Reactivated' if u_suspended else 'Suspended'} {u_email}.")
                st.rerun()
        else:
            st.caption("Staff accounts can't be suspended.")

        st.markdown("---")
        st.caption("Reset this user's password")
        reset_pw = st.text_input("New password", type="password", key=f"user_reset_pw_{u_id}", label_visibility="collapsed", placeholder="New password (6+ characters)")
        if st.button(":material/key: Set New Password", key=f"user_reset_btn_{u_id}", use_container_width=True):
            if len(reset_pw) >= 6:
                db.admin_reset_password(u_id, reset_pw)
                if db.get_user_settings(u_id).get("notify_password_changed") and u_email:
                    email_utils.send_password_changed_email(u_email)
                st.toast(f"Password reset for {u_email}.")
            else:
                st.error("Password must be at least 6 characters.")

    st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)
    if st.button("Close", use_container_width=True, key=f"user_manage_close_btn_{u_id}"):
        st.session_state.admin_selected_user_id = None
        st.rerun()


def _render_users_tab_body(current_role):
    """Shared by the Users tab (admin/super_admin, inside the full
    dashboard+tabs layout) and the narrowed support view (its whole page,
    no other tabs) - one implementation instead of two drifting copies.
    Profile editing (name/email/plan) is hidden entirely for support - it's
    scoped to Credits and the suspend/password-reset actions, the ones that
    actually resolve a support ticket. The Role field within Profile is
    further restricted to super_admin only, and never for editing your own
    row - see roles.py and update_user_role_admin()'s docstring for why."""
    search_query = st.text_input(":material/search: Search users", placeholder="Search by email or name...", key="admin_user_search")
    user_rows = db.get_all_users_for_admin_table()
    if search_query:
        q = search_query.lower()
        user_rows = [u for u in user_rows if q in u[1].lower() or q in (u[2] or "").lower()]

    if not user_rows:
        st.caption("No users match your search.")
        return

    st.caption("Drag a column header to reorder it, click a header to sort, or use the toolbar above the table to search, hide columns, or export to CSV.")

    users_page_size = st.selectbox("Rows per page", [10, 25, 50, 100], index=1, key="admin_users_page_size")
    users_total_rows = len(user_rows)
    users_total_pages = max(1, (users_total_rows + users_page_size - 1) // users_page_size)
    users_current_page = min(st.session_state.get("admin_users_current_page", 1), users_total_pages)

    users_nav1, users_nav2, users_nav3 = st.columns([1, 2, 1])
    with users_nav1:
        if st.button(":material/chevron_left: Previous", disabled=users_current_page <= 1, use_container_width=True, key="admin_users_prev_page_btn"):
            st.session_state.admin_users_current_page = users_current_page - 1
            st.session_state.admin_selected_user_id = None
            st.rerun()
    with users_nav2:
        st.markdown(f"<div style='text-align:center; padding-top:8px; color:var(--radar-text-muted); font-size:13px;'>Page {users_current_page} of {users_total_pages} · {users_total_rows} total users</div>", unsafe_allow_html=True)
    with users_nav3:
        if st.button("Next :material/chevron_right:", disabled=users_current_page >= users_total_pages, use_container_width=True, key="admin_users_next_page_btn"):
            st.session_state.admin_users_current_page = users_current_page + 1
            st.session_state.admin_selected_user_id = None
            st.rerun()

    user_rows_page = user_rows[(users_current_page - 1) * users_page_size: users_current_page * users_page_size]

    users_table_df = pd.DataFrame([
        {
            "Name": u_name or "-", "Email": u_email, "Account ID": u_account_id or "-", "Role": u_role.upper(), "Plan": u_plan,
            "Credits": u_credits, "Scans": u_scan_count, "Live": u_live_scan_count,
            "RentCast Calls": u_rentcast_calls, "Spent ($)": u_total_spent,
            "Joined": (u_created_at or "")[:10], "Suspended": "Yes" if u_suspended else "No",
            "Manage": ":material/manage_accounts:",
        }
        for u_id, u_email, u_name, u_role, u_plan, u_credits, u_suspended, u_created_at,
            u_scan_count, u_live_scan_count, u_rentcast_calls, u_total_spent,
            u_account_id, u_first_name, u_middle_name, u_last_name in user_rows_page
    ])
    # No explicit height => Streamlit's fixed ~400px default with an inner
    # scrollbar, regardless of how many rows are on this page. Size it to
    # the actual row count instead (35px/row + ~38px header) so up to a
    # full page (max 100/page) is always visible without scrolling inside
    # the table itself - the Previous/Next buttons above are the only
    # scrolling the user should need.
    users_table_height = len(users_table_df) * 35 + 38
    st.dataframe(
        users_table_df, use_container_width=True, hide_index=True, key="admin_users_table",
        height=users_table_height,
        column_config={
            "Credits": st.column_config.NumberColumn(format="%d"),
            "Spent ($)": st.column_config.NumberColumn(format="$%.0f"),
            "Manage": st.column_config.ButtonColumn("Manage", width="small", type="tertiary", key="admin_users_manage_click"),
        },
    )

    manage_click = st.session_state.get("admin_users_manage_click")
    if manage_click and manage_click.get("row") is not None:
        st.session_state.admin_selected_user_id = user_rows_page[manage_click["row"]][0]

    selected_user_id = st.session_state.get("admin_selected_user_id")
    selected_row = next((u for u in user_rows_page if u[0] == selected_user_id), None)
    if selected_row:
        _manage_user_dialog(selected_row, current_role)


def _render_pricing_tab():
    st.markdown("### Credit Packages")
    st.caption("Prices, credits, and resource limits per plan tier - changes take effect immediately, no deploy needed.")
    packages = db.get_credit_packages()
    for tier_name, tier in packages.items():
        with st.container(key=f"admin_pkg_row_{tier_name}"):
            st.markdown(f"""<style>div.st-key-admin_pkg_row_{tier_name} {{ background: var(--radar-surface);
                border: 1px solid var(--radar-border); border-radius: var(--radar-radius-md);
                padding: var(--radar-space-3) var(--radar-space-4); margin-bottom: var(--radar-space-3); }}</style>""",
                        unsafe_allow_html=True)
            st.markdown(f"**{tier_name}**")
            pkg_col1, pkg_col2, pkg_col3, pkg_col4, pkg_col5, pkg_col6 = st.columns(6)
            with pkg_col1:
                new_price = st.number_input("Price ($)", min_value=0.0, value=float(tier["price"]), step=1.0, key=f"pkg_price_{tier_name}")
            with pkg_col2:
                new_credits = st.number_input("Credits", min_value=0, value=int(tier["credits"]), key=f"pkg_credits_{tier_name}")
            with pkg_col3:
                pf_unlimited = tier["portfolio_properties"] is None
                new_pf = None if st.checkbox("Unlim. portfolio", value=pf_unlimited, key=f"pkg_pf_unlim_{tier_name}") else \
                    st.number_input("Portfolio cap", min_value=0, value=int(tier["portfolio_properties"] or 0), key=f"pkg_pf_{tier_name}")
            with pkg_col4:
                sp_unlimited = tier["saved_properties"] is None
                new_sp = None if st.checkbox("Unlim. saved", value=sp_unlimited, key=f"pkg_sp_unlim_{tier_name}") else \
                    st.number_input("Saved cap", min_value=0, value=int(tier["saved_properties"] or 0), key=f"pkg_sp_{tier_name}")
            with pkg_col5:
                ss_unlimited = tier["saved_searches"] is None
                new_ss = None if st.checkbox("Unlim. searches", value=ss_unlimited, key=f"pkg_ss_unlim_{tier_name}") else \
                    st.number_input("Searches cap", min_value=0, value=int(tier["saved_searches"] or 0), key=f"pkg_ss_{tier_name}")
            with pkg_col6:
                st.markdown("<div style='margin-top:28px;'></div>", unsafe_allow_html=True)
                pkg_has_changes = (
                    new_price != float(tier["price"]) or new_credits != int(tier["credits"]) or
                    new_pf != tier["portfolio_properties"] or new_sp != tier["saved_properties"] or new_ss != tier["saved_searches"]
                )
                if st.button(":material/save: Save", key=f"pkg_save_{tier_name}", type="primary", use_container_width=True, disabled=not pkg_has_changes):
                    db.update_credit_package(tier_name, new_price, new_credits, new_pf, new_sp, new_ss)
                    st.toast(f"Updated {tier_name} package.")
                    st.rerun()

    st.markdown("<div style='height:16px;'></div>", unsafe_allow_html=True)
    st.markdown("### API Cost Guardrails")
    st.caption("These control what each scan actually costs you - the monthly call limit is what matters, not just what RentCast bills you for.")

    rc_conf = db.get_rentcast_config()
    with st.form("admin_rentcast_config_form"):
        st.markdown("**RentCast plan**")
        rc_name_input = st.text_input("Plan name", value=rc_conf["plan_name"])
        rc_cost_input = st.number_input("Monthly cost ($)", min_value=0.0, value=float(rc_conf["monthly_cost"]), step=1.0)
        rc_limit_input = st.number_input("Calls included per month", min_value=1, value=int(rc_conf["monthly_limit"]))
        rc_threshold_input = st.number_input(
            "Alert threshold (%)", min_value=1, max_value=100, value=int(rc_conf["alert_threshold_pct"]),
            help="Every admin/super_admin gets a one-time email + an in-app alert (bell icon) the moment usage this month first crosses this percentage of the limit above."
        )
        verified_note = f"Last verified {rc_conf['verified_at']}" if rc_conf["verified_at"] else "Never verified - RentCast has no price-change API, so re-check their pricing page periodically and re-save here."
        st.caption(verified_note)
        if st.form_submit_button(":material/save: Save RentCast Plan", type="primary", use_container_width=True):
            db.update_rentcast_config(rc_limit_input, rc_name_input, rc_cost_input, rc_threshold_input)
            st.toast("RentCast plan updated.")
            st.rerun()

    st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)
    places_conf = db.get_places_config()
    places_used = db.get_places_usage_this_month()
    with st.form("admin_places_config_form"):
        st.markdown("**Google Places (car dealer address lookups)**")
        st.caption(
            f"{places_used} / {places_conf['monthly_limit']} lookups used this month. Google Places bills "
            "per request on your own Google Cloud account - this app has no way to read your real budget/quota "
            "from Google's side, so this number is a self-declared cap you set from what you know in Cloud Console."
        )
        places_limit_input = st.number_input("Self-declared monthly budget (calls)", min_value=1, value=int(places_conf["monthly_limit"]))
        if st.form_submit_button(":material/save: Save Places Budget", type="primary", use_container_width=True):
            db.update_places_config(places_limit_input)
            st.toast("Places budget updated.")
            st.rerun()

    st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)
    ad_conf = db.get_autodev_config()
    ad_used_conf = db.get_autodev_usage_this_month()
    with st.form("admin_autodev_config_form"):
        st.markdown("**Auto.dev (car listings)**")
        st.caption(f"{ad_used_conf} / {ad_conf['monthly_limit']} calls used this month - once this cap is hit, Cars searches fall back to simulated listing data instead of calling Auto.dev.")
        ad_limit_input = st.number_input("Monthly call limit", min_value=1, value=int(ad_conf["monthly_limit"]))
        if st.form_submit_button(":material/save: Save Auto.dev Limit", type="primary", use_container_width=True):
            db.update_autodev_config(ad_limit_input)
            st.toast("Auto.dev monthly limit updated.")
            st.rerun()

    st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)
    oa_conf = db.get_openai_config()
    oa_used = db.get_openai_usage_this_month()
    with st.form("admin_openai_config_form"):
        st.markdown("**OpenAI report generation**")
        st.caption(f"{oa_used} / {oa_conf['monthly_limit']} calls used this month - once this cap is hit, scans fall back to the free local report generator instead of calling OpenAI.")
        oa_limit_input = st.number_input("Monthly call limit", min_value=1, value=int(oa_conf["monthly_limit"]))
        if st.form_submit_button(":material/save: Save OpenAI Limit", type="primary", use_container_width=True):
            db.update_openai_config(oa_limit_input)
            st.toast("OpenAI monthly limit updated.")
            st.rerun()

    st.markdown("<div style='height:16px;'></div>", unsafe_allow_html=True)
    st.markdown("### Promo Codes")
    with st.expander(":material/add: Create a new code"):
        # This checkbox lives outside the form deliberately: form
        # widgets don't trigger a rerun on change (only the submit
        # button does), so a checkbox INSIDE the form couldn't reveal
        # the conditional date_input below until the form was already
        # submitted - by then it's too late for the user to fill it in.
        promo_has_expiry = st.checkbox("Set an expiry date", key="admin_new_promo_has_expiry")
        with st.form("admin_new_promo_form"):
            promo_code_input = st.text_input("Code", placeholder="e.g. LAUNCH20").upper()
            promo_type_input = st.radio("Discount type", ["percent", "flat"], horizontal=True,
                                         format_func=lambda x: "% off" if x == "percent" else "$ off")
            promo_value_input = st.number_input("Discount value", min_value=0.0, step=1.0)
            promo_max_uses_input = st.number_input("Max uses (0 = unlimited)", min_value=0, value=0)
            promo_expiry_input = st.date_input("Expires on") if promo_has_expiry else None
            if st.form_submit_button(":material/add: Create Code", type="primary", use_container_width=True):
                if not promo_code_input:
                    st.error("Enter a code.")
                else:
                    expires_str = f"{promo_expiry_input} 23:59:59" if promo_expiry_input else None
                    max_uses = promo_max_uses_input if promo_max_uses_input > 0 else None
                    if db.create_promo_code(promo_code_input, promo_type_input, promo_value_input, max_uses, expires_str):
                        st.toast(f"Created code {promo_code_input}.", icon=":material/check_circle:")
                        st.rerun()
                    else:
                        st.error("A code with that name already exists.")

    promo_codes = db.get_promo_codes()
    if not promo_codes:
        st.caption("No promo codes yet.")
    else:
        for p_id, p_code, p_type, p_value, p_max, p_used, p_expires, p_active in promo_codes:
            with st.container(key=f"admin_promo_row_{p_id}"):
                st.markdown(f"""<style>div.st-key-admin_promo_row_{p_id} {{ background: var(--radar-surface);
                    border: 1px solid var(--radar-border); border-radius: var(--radar-radius-md);
                    padding: var(--radar-space-3) var(--radar-space-4); margin-bottom: var(--radar-space-3); }}</style>""",
                            unsafe_allow_html=True)
                discount_label = f"{p_value:.0f}% off" if p_type == "percent" else f"${p_value:.0f} off"
                usage_label = f"{p_used}/{p_max} used" if p_max else f"{p_used} used (unlimited)"
                expiry_label = f" · expires {p_expires[:10]}" if p_expires else ""
                status_label = " · :red[inactive]" if not p_active else ""
                promo_row1, promo_row2 = st.columns([4, 1])
                with promo_row1:
                    st.markdown(f"**{p_code}** &nbsp;·&nbsp; {discount_label} &nbsp;·&nbsp; {usage_label}{expiry_label}{status_label}")
                with promo_row2:
                    toggle_label = ":material/lock_open: Reactivate" if not p_active else ":material/block: Deactivate"
                    if st.button(toggle_label, key=f"promo_toggle_{p_id}", use_container_width=True):
                        db.set_promo_code_active(p_id, not p_active)
                        st.rerun()


def _render_dashboard_tab(stats, signup_stats, scan_breakdown, revenue_stats, _render_signup_trend_card, _render_zero_credit_card, _render_rentcast_card, _render_autodev_card):
    # Each card is a real (CSS-restyled) button, not decorative HTML -
    # click opens a floating st.dialog with drill-down detail.
    # Streamlit's st.tabs can't be jumped to programmatically, so a
    # dialog (with its own native close button) is the actual
    # mechanism for "click a card, see more" here, not a same-page tab
    # switch.
    stat_cols = st.columns(4)
    stat_defs = [
        (":material/group:", "Total Users", stats["total_users"], f"+{signup_stats['new_this_week']} this week", _show_signups_dialog, ()),
        (":material/show_chart:", "Live Scans (This Month)", scan_breakdown["live_this_month"],
         f"{scan_breakdown['mock_this_month']} mock/preview", _show_scans_dialog, (scan_breakdown,)),
        (":material/payments:", "Revenue (This Month)", f"${revenue_stats['total_this_month']:,.0f}",
         f"${revenue_stats['total_all_time']:,.0f} all-time · demo", _show_revenue_dialog, (revenue_stats,)),
        (":material/toll:", "Credits Outstanding", f"{stats['total_credits']:,}", "across all accounts", _show_credits_dialog, ()),
    ]
    for i, (icon_shortcode, label, value, sub, dialog_fn, dialog_args) in enumerate(stat_defs):
        with stat_cols[i]:
            with st.container(key=f"admin_stat_card_{i}"):
                if st.button(f"{icon_shortcode} **{value}**\n{label}", key=f"admin_stat_card_btn_{i}",
                             use_container_width=True, help=sub):
                    dialog_fn(*dialog_args)

    st.markdown("<div style='height:12px;'></div>", unsafe_allow_html=True)

    # ---- DASHBOARD GRID - signup trend, zero-credit list, and
    # RentCast usage are real always-visible cards (not hidden behind
    # a dropdown), laid out in a persisted, admin-resizable grid (see
    # dashboard_grid.py) instead of a fixed one-per-row stack. ----
    dashboard_cards = [
        {"id": "signup_trend", "title": "Signup Trend", "render": _render_signup_trend_card,
         "default_row": 1, "default_col": 1, "default_span": 2},
    ]
    if stats["zero_credit_users"]:
        dashboard_cards.append({"id": "zero_credit", "title": "0-Credit Users", "render": _render_zero_credit_card,
                                 "default_row": 1, "default_col": 3, "default_span": 1})
    dashboard_cards.append({"id": "rentcast_usage", "title": "RentCast Usage", "render": _render_rentcast_card,
                             "default_row": 1, "default_col": 4, "default_span": 1})
    dashboard_cards.append({"id": "autodev_usage", "title": "Auto.dev Usage", "render": _render_autodev_card,
                             "default_row": 2, "default_col": 1, "default_span": 1})

    # A fixed card_height (not just the same span-derived width every
    # card already got) is what actually makes all 1x1 cards land at the
    # same size regardless of content - the zero-credit card's list is
    # variable-length (0 to N users), which was the actual case that
    # broke the row's rhythm; overflow-y:auto lets a long list scroll
    # inside its own card instead of growing it. 300px comfortably fits
    # the tallest card (signup_trend's header + 180px chart + padding)
    # with a little room to spare.
    render_dashboard_grid("admin", dashboard_cards, default_grid_columns=4, card_height=300)


def _render_api_usage_tab(scan_breakdown):
    st.markdown("### Live vs. Mock/Preview Scans")
    st.caption("A scan is 'live' when it pulled real RentCast listings; 'mock/preview' covers admin Test Scans, out-of-credit scans, and guest previews.")
    api_col1, api_col2 = st.columns(2)
    with api_col1:
        st.markdown(f"""
            <div style='background:var(--radar-surface); border:1px solid var(--radar-border); border-radius:var(--radar-radius-md); padding:var(--radar-space-4);'>
                <div style='font-size:12px; font-weight:700; color:var(--radar-text-muted); margin-bottom:6px;'>ALL TIME</div>
                <div style='font-size:22px; font-weight:800; color:var(--radar-navy);'>{scan_breakdown['live_all_time']} live</div>
                <div style='font-size:13px; color:var(--radar-text-muted);'>{scan_breakdown['mock_all_time']} mock/preview</div>
            </div>
        """, unsafe_allow_html=True)
    with api_col2:
        st.markdown(f"""
            <div style='background:var(--radar-surface); border:1px solid var(--radar-border); border-radius:var(--radar-radius-md); padding:var(--radar-space-4);'>
                <div style='font-size:12px; font-weight:700; color:var(--radar-text-muted); margin-bottom:6px;'>THIS MONTH</div>
                <div style='font-size:22px; font-weight:800; color:var(--radar-navy);'>{scan_breakdown['live_this_month']} live</div>
                <div style='font-size:13px; color:var(--radar-text-muted);'>{scan_breakdown['mock_this_month']} mock/preview</div>
            </div>
        """, unsafe_allow_html=True)

    st.markdown("<div style='height:16px;'></div>", unsafe_allow_html=True)
    st.markdown("### RentCast Calls by User (This Month)")
    usage_by_user = db.get_rentcast_usage_by_user()
    if not usage_by_user:
        st.caption("No real RentCast calls made yet this month.")
    else:
        usage_df = pd.DataFrame([
            {"User": f"{row['name']} ({row['email']})" if row["name"] and row["email"] else row["name"] or row["email"],
             "RentCast Calls": row["call_count"]}
            for row in usage_by_user
        ])
        st.dataframe(usage_df, use_container_width=True, hide_index=True, height=len(usage_df) * 35 + 38)

    st.markdown("<div style='height:16px;'></div>", unsafe_allow_html=True)
    st.markdown("### Auto.dev Calls by User (This Month)")
    st.caption("Cars category searches, plus the live make/model dropdown lookups behind them.")
    autodev_usage_by_user = db.get_autodev_usage_by_user()
    if not autodev_usage_by_user:
        st.caption("No real Auto.dev calls made yet this month.")
    else:
        autodev_usage_df = pd.DataFrame([
            {"User": f"{row['name']} ({row['email']})" if row["name"] and row["email"] else row["name"] or row["email"],
             "Auto.dev Calls": row["call_count"]}
            for row in autodev_usage_by_user
        ])
        st.dataframe(autodev_usage_df, use_container_width=True, hide_index=True, height=len(autodev_usage_df) * 35 + 38)


def _render_revenue_tab(revenue_stats):
    st.markdown("### Revenue (Simulated)")
    st.caption(f"{svg_icon('lightbulb', size=13, color='var(--radar-text-subtle)')} No real payment processor is wired up yet - these numbers reflect the demo checkout in Buy Credits, not real charges.", unsafe_allow_html=True)

    rev_col1, rev_col2 = st.columns(2)
    with rev_col1:
        st.markdown(f"""
            <div style='background:var(--radar-surface); border:1px solid var(--radar-border); border-radius:var(--radar-radius-md); padding:var(--radar-space-4);'>
                <div style='font-size:12px; font-weight:700; color:var(--radar-text-muted); margin-bottom:6px;'>THIS MONTH</div>
                <div style='font-size:22px; font-weight:800; color:var(--radar-navy);'>${revenue_stats['total_this_month']:,.0f}</div>
                <div style='font-size:13px; color:var(--radar-text-muted);'>{revenue_stats['count_this_month']} purchase(s)</div>
            </div>
        """, unsafe_allow_html=True)
    with rev_col2:
        st.markdown(f"""
            <div style='background:var(--radar-surface); border:1px solid var(--radar-border); border-radius:var(--radar-radius-md); padding:var(--radar-space-4);'>
                <div style='font-size:12px; font-weight:700; color:var(--radar-text-muted); margin-bottom:6px;'>ALL TIME</div>
                <div style='font-size:22px; font-weight:800; color:var(--radar-navy);'>${revenue_stats['total_all_time']:,.0f}</div>
                <div style='font-size:13px; color:var(--radar-text-muted);'>{revenue_stats['count_all_time']} purchase(s)</div>
            </div>
        """, unsafe_allow_html=True)

    st.markdown("<div style='height:16px;'></div>", unsafe_allow_html=True)
    st.markdown("### Plan Tier Distribution")
    plan_dist = db.get_plan_distribution()
    plan_cols = st.columns(len(plan_dist) or 1)
    for (plan_name, count), col in zip(plan_dist.items(), plan_cols):
        with col:
            st.markdown(f"""
                <div style='background:var(--radar-surface); border:1px solid var(--radar-border); border-radius:var(--radar-radius-md); padding:10px 14px; text-align:center;'>
                    <div style='font-size:18px; font-weight:800; color:var(--radar-navy);'>{count}</div>
                    <div style='font-size:11px; color:var(--radar-text-muted); font-weight:600;'>{plan_name}</div>
                </div>
            """, unsafe_allow_html=True)

    st.markdown("<div style='height:16px;'></div>", unsafe_allow_html=True)
    st.markdown("### Recent Transactions")
    recent_tx = db.get_recent_transactions()
    if not recent_tx:
        st.caption("No purchases yet.")
    else:
        tx_df = pd.DataFrame([
            {"User": f"{name} ({email})" if name else email, "Package": pkg,
             "Amount": f"${amt:,.0f}", "Credits": credits, "Date": purchased_at}
            for email, name, pkg, amt, credits, purchased_at in recent_tx
        ])
        st.dataframe(tx_df, use_container_width=True, hide_index=True, height=len(tx_df) * 35 + 38)


def _render_add_admins_tab(current_role):
    st.markdown("### Grant Staff Access")
    st.caption("Only a super_admin can grant or change roles - see the role descriptions below.")
    with st.expander(":material/info: What each role can do"):
        st.caption("**Support** - the Users tab only, and just enough to help a customer: credits, suspend/reactivate, password reset. No pricing, revenue, or profile-editing access.")
        st.caption("**Admin** - full day-to-day operations: Users (full), API Usage, Revenue, Broadcast. Can't edit pricing/cost config or grant roles to anyone.")
        st.caption("**Super Admin** - everything, including this tab and Pricing. Keep this to the smallest number of people who genuinely need it.")

    nav_col, content_col = st.columns([1, 3])
    with nav_col:
        grant_mode = render_side_nav(
            [
                {"label": "Promote an existing user", "icon": ":material/person_add:"},
                {"label": "Create a new account", "icon": ":material/add_circle:"},
            ],
            key_prefix="admin_grant_mode_nav",
        )

    with content_col:
        if grant_mode == "Promote an existing user":
            candidates = [(u[0], u[1], u[2], u[3]) for u in db.get_all_users_for_admin_table() if u[3] != "super_admin"]
            if not candidates:
                st.caption("No eligible users - everyone is already a super_admin.")
            else:
                labels = [f"{name or email} ({email}) - currently {role.upper()}" for _, email, name, role in candidates]
                picked_idx = st.selectbox("User", range(len(candidates)), format_func=lambda i: labels[i], key="admin_promote_user_select")
                picked_id, picked_email, picked_name, picked_current_role = candidates[picked_idx]
                new_staff_role = st.selectbox("Grant role", roles.STAFF_ROLES,
                                               index=roles.STAFF_ROLES.index(picked_current_role) if picked_current_role in roles.STAFF_ROLES else 0,
                                               key="admin_promote_role_select")
                if st.button(":material/verified_user: Grant Access", type="primary", use_container_width=True, key="admin_promote_btn"):
                    if db.update_user_role_admin(picked_id, new_staff_role):
                        st.toast(f"{picked_email} is now {new_staff_role.upper()}.", icon=":material/check_circle:")
                        st.rerun()
                    else:
                        st.error("Couldn't demote the last super_admin - promote someone else first.")
        else:
            new_admin_email = st.text_input("Email")
            new_admin_pass = st.text_input("Password", type="password")
            new_admin_role = st.selectbox("Role", roles.STAFF_ROLES, index=roles.STAFF_ROLES.index("admin"), key="admin_new_account_role")

            if st.button(":material/verified_user: Create Account", type="primary", use_container_width=True, key="admin_create_account_btn"):
                if new_admin_email and len(new_admin_pass) >= 6:
                    if db.create_super_user_admin(new_admin_email, new_admin_pass, new_admin_role):
                        st.success(f"{new_admin_role.upper()} account created for {new_admin_email}.")
                    else:
                        st.error("An account with this email already exists.")
                else:
                    st.error("Enter an email and a password of at least 6 characters.")


def _render_broadcast_tab():
    st.markdown("### Site-Wide Announcement")
    st.caption("Shown as a banner to every logged-in user until you clear it - useful for maintenance notices or new feature announcements.")
    current_message = db.get_broadcast_message()
    new_message = st.text_area("Message", value=current_message, placeholder="e.g., Scheduled maintenance tonight 10-11pm ET.")
    bc_col1, bc_col2 = st.columns([1, 1])
    with bc_col1:
        if st.button(":material/campaign: Publish", type="primary", use_container_width=True):
            db.set_broadcast_message(new_message)
            st.toast("Broadcast message published.")
            st.rerun()
    with bc_col2:
        if st.button(":material/close: Clear", use_container_width=True, disabled=not current_message):
            db.set_broadcast_message("")
            st.toast("Broadcast message cleared.")
            st.rerun()


def _render_design_standards_tab():
    st.markdown("### Design Standards")
    st.caption(
        "The UI conventions every new page or feature gets checked against - navigation, tables, "
        "badges, icons, and so on. Edit here for a quick wording tweak, or ask Claude to update it "
        "alongside a real code change so the doc and the code move together."
    )

    has_override = db.has_design_standards_override()
    if has_override:
        st.info(":material/edit: Showing your saved edit, not the version checked into the repo.", icon=":material/edit:")

    current_content = db.get_design_standards()
    edited_content = st.text_area(
        "Content (Markdown)", value=current_content, height=420,
        label_visibility="collapsed", key="design_standards_editor",
    )

    ds_col1, ds_col2 = st.columns([1, 1])
    with ds_col1:
        if st.button(":material/save: Save", type="primary", use_container_width=True,
                     disabled=(edited_content == current_content)):
            db.set_design_standards_override(edited_content)
            st.toast("Design standards updated.")
            st.rerun()
    with ds_col2:
        if st.button(":material/restart_alt: Revert to repo file", use_container_width=True, disabled=not has_override):
            db.clear_design_standards_override()
            st.toast("Reverted to DESIGN_STANDARDS.md.")
            st.rerun()

    st.markdown("---")
    st.markdown("##### Preview")
    with st.container(border=True):
        st.markdown(current_content)


def _render_logo_slot(slot_key, slot_title, help_text, default_html_fn, preview_wrap_fn, inject_css_fn, brand, nonce):
    """One category's logo editor: textarea + explicit preview button +
    live preview + a saved-presets library (save/apply/delete). Shared by
    all 3 slots (real_estate/cars/guest) in _render_brand_design_tab so
    the CRUD logic exists once, not three near-identical copies. Returns
    the textarea's current value so the caller can include it when the
    main "Save brand settings" button is clicked.

    Preset Apply/Delete act immediately (their own save + rerun) rather
    than waiting for the main Save button - "select from the saved logo"
    should just work, not require a second click on an unrelated button.
    The explicit preview button is redundant with the textarea's own
    on-blur rerun (Streamlit already reruns - and re-syncs the textarea's
    latest value - on any button click, including this one), but the user
    asked for something visible to click before trusting what they typed,
    so it's here even though the preview below is already always current
    as of the last rerun."""
    st.markdown(f"##### {slot_title}")
    st.caption(help_text)

    text_col, btn_col = st.columns([5, 1])
    with text_col:
        current_html = st.text_area(
            f"{slot_title} HTML", value=brand.get(f"logo_html_{slot_key}", ""),
            height=140, key=f"brand_logo_html_{slot_key}_{nonce}",
            placeholder="Leave blank for the built-in default...", label_visibility="collapsed",
        )
    with btn_col:
        st.button(":material/visibility: Preview", key=f"brand_logo_preview_btn_{slot_key}", use_container_width=True)

    st.caption("Preview")
    # flatten_html collapses the admin's pasted (naturally multi-line,
    # indented) HTML onto one line before it hits st.markdown - without
    # it, Streamlit's markdown parser treats indented lines as a code
    # block and shows them as literal text instead of rendering them,
    # exactly what happens on the real topbar too if the raw override
    # were rendered unflattened. See flatten_html's docstring.
    preview_html = topbar_logo.flatten_html(current_html.strip()) if current_html.strip() else default_html_fn()
    if inject_css_fn:
        inject_css_fn()
    st.markdown(preview_wrap_fn(preview_html), unsafe_allow_html=True)

    st.markdown("###### Saved presets")
    presets = brand.get(f"logo_presets_{slot_key}", [])
    if presets:
        for i, preset in enumerate(presets):
            p_name_col, p_preview_col, p_apply_col, p_delete_col = st.columns([2, 3, 1, 1])
            with p_name_col:
                st.markdown(f"<div style='padding-top: 8px;'>{preset['name']}</div>", unsafe_allow_html=True)
            with p_preview_col:
                if inject_css_fn:
                    inject_css_fn()
                st.markdown(
                    f"<div style='transform: scale(0.7); transform-origin: left center;'>"
                    f"{preview_wrap_fn(topbar_logo.flatten_html(preset['html']))}</div>",
                    unsafe_allow_html=True,
                )
            with p_apply_col:
                if st.button(":material/check: Apply", key=f"brand_logo_preset_apply_{slot_key}_{i}", use_container_width=True):
                    new_settings = dict(db.get_brand_settings())
                    new_settings[f"logo_html_{slot_key}"] = preset["html"]
                    db.save_brand_settings(new_settings)
                    st.session_state.brand_logo_html_nonce = st.session_state.get("brand_logo_html_nonce", 0) + 1
                    st.toast(f"Applied '{preset['name']}'.")
                    st.rerun()
            with p_delete_col:
                if st.button(":material/delete:", key=f"brand_logo_preset_delete_{slot_key}_{i}", use_container_width=True):
                    new_settings = dict(db.get_brand_settings())
                    new_settings[f"logo_presets_{slot_key}"] = [p for j, p in enumerate(presets) if j != i]
                    db.save_brand_settings(new_settings)
                    st.toast(f"Deleted '{preset['name']}'.")
                    st.rerun()
    else:
        st.caption("No saved presets yet - save the box above to build a library you can switch between later.")

    # A separate nonce from the HTML textarea's - saving a preset should
    # only clear the name box, not also wipe out whatever draft HTML the
    # admin still has in the big textarea above (which isn't necessarily
    # active yet and shouldn't disappear just because they saved a copy
    # of it as a preset).
    preset_name_nonce = st.session_state.setdefault(f"brand_logo_preset_name_nonce_{slot_key}", 0)
    name_col, save_col = st.columns([3, 1])
    with name_col:
        preset_name = st.text_input(
            "Preset name", key=f"brand_logo_preset_name_{slot_key}_{preset_name_nonce}", placeholder="e.g., Holiday logo",
            label_visibility="collapsed",
        )
    with save_col:
        if st.button(":material/save: Save as preset", key=f"brand_logo_preset_save_{slot_key}", use_container_width=True):
            if not preset_name.strip():
                st.error("Give this preset a name first.")
            elif not current_html.strip():
                st.error("Nothing to save - the box above is empty (that's just the built-in default).")
            else:
                new_settings = dict(db.get_brand_settings())
                new_presets = list(new_settings.get(f"logo_presets_{slot_key}", []))
                new_presets.append({"name": preset_name.strip(), "html": current_html.strip()})
                new_settings[f"logo_presets_{slot_key}"] = new_presets
                db.save_brand_settings(new_settings)
                st.session_state[f"brand_logo_preset_name_nonce_{slot_key}"] = preset_name_nonce + 1
                st.toast(f"Saved preset '{preset_name.strip()}'.")
                st.rerun()

    return current_html


def _render_brand_design_tab():
    st.markdown("### Brand & Design")
    st.caption(
        "Live controls for the app's accent color, typefaces, and logo - saved here, they drive "
        "the design tokens every page's CSS already reads from (design_tokens.py), so a change "
        "shows up across the whole app on the next rerun, no code edit needed."
    )

    brand = db.get_brand_settings()
    # st.text_area (unlike color_picker/selectbox) ignores a changed
    # `value=` on rerun once the user has typed in it - the frontend
    # treats its own edited content as authoritative and never re-syncs
    # from the server, even after the underlying session_state key is
    # popped. Confirmed live: after Reset to defaults, the DB and the
    # preview below both correctly showed the built-in default, but the
    # textarea itself kept showing the just-cleared custom HTML - a real,
    # if purely cosmetic, bug. The fix that actually forces a re-render is
    # changing the widget's *key* (a nonce bumped on reset), not clearing
    # session_state - a new key is a new frontend component with no local
    # edit state to preserve.
    logo_html_nonce = st.session_state.setdefault("brand_logo_html_nonce", 0)

    st.markdown("##### Accent color")
    st.caption("Drives the cyan cyberpunk accents (nav highlight, Run Live Scan button, scan-loading radar).")
    accent_color = st.color_picker("Accent color", value=brand["accent_color"], key="brand_accent_picker",
                                    label_visibility="collapsed")

    st.markdown("##### Typefaces")
    font_col1, font_col2, font_col3 = st.columns(3)
    with font_col1:
        font_display = st.selectbox("Display (headings)", options=list(design_tokens.DISPLAY_FONT_OPTIONS.keys()),
                                     index=list(design_tokens.DISPLAY_FONT_OPTIONS.keys()).index(brand["font_display"])
                                     if brand["font_display"] in design_tokens.DISPLAY_FONT_OPTIONS else 0,
                                     key="brand_font_display")
    with font_col2:
        font_body = st.selectbox("Body (default text)", options=list(design_tokens.BODY_FONT_OPTIONS.keys()),
                                  index=list(design_tokens.BODY_FONT_OPTIONS.keys()).index(brand["font_body"])
                                  if brand["font_body"] in design_tokens.BODY_FONT_OPTIONS else 0,
                                  key="brand_font_body")
    with font_col3:
        font_mono = st.selectbox("Mono (data, code)", options=list(design_tokens.MONO_FONT_OPTIONS.keys()),
                                  index=list(design_tokens.MONO_FONT_OPTIONS.keys()).index(brand["font_mono"])
                                  if brand["font_mono"] in design_tokens.MONO_FONT_OPTIONS else 0,
                                  key="brand_font_mono")

    st.markdown("##### Logo")
    if brand["logo_data_uri"]:
        st.markdown(
            f"<img src='{brand['logo_data_uri']}' style='width: 48px; height: 48px; border-radius: 8px; "
            f"object-fit: contain; border: 1px solid var(--radar-border);' />",
            unsafe_allow_html=True,
        )
        st.caption("Current custom logo (replaces the built-in radar mark in the topbar).")
    else:
        st.caption("No custom logo set - the built-in radar mark is shown.")

    uploaded_logo = st.file_uploader("Upload a new logo (PNG, JPG, or SVG - square works best)",
                                      type=["png", "jpg", "jpeg", "svg"], key="brand_logo_uploader")
    remove_logo = False
    if brand["logo_data_uri"]:
        remove_logo = st.checkbox("Remove custom logo on save (revert to the built-in mark)", key="brand_logo_remove")

    st.markdown("##### Logo overrides")
    st.caption(
        "Each of the app's 3 logo slots (Real Estate and Cars in the main topbar, Guest for the anonymous "
        "landing page AND the Sign In/Register page, which share one logo) defaults to a coded badge - paste "
        "raw HTML below to replace one entirely, or build a library of saved presets to switch between over "
        "time. Leave the box blank to keep the built-in default. Inline styles and this app's CSS variables "
        "(e.g. `var(--radar-accent)`, `var(--radar-navy)`) work; Tailwind utility classes don't, since this "
        "app doesn't load Tailwind - translate any Tailwind class to inline CSS first."
    )

    def _scoutai_wrap(html):
        # Reusing the real topbar's own class (not a fresh
        # st.container(key=...), which would collide with the actual
        # topbar's key) is what makes this an accurate, not approximate,
        # preview - main.py's <style> block (already injected earlier in
        # this same page render) targets `div.st-key-scoutai_topbar` by
        # class, and CSS doesn't care whether that class came from
        # Streamlit's own container machinery or a plain div in raw markdown.
        return f"<div class='st-key-scoutai_topbar' style='border-radius: 8px;'>{html}</div>"

    def _guest_wrap(html):
        return f"<div style='background: var(--radar-navy); padding: 14px 20px; border-radius: 8px;'>{html}</div>"

    real_estate_html = _render_logo_slot(
        "real_estate", "Real Estate logo",
        "Shown in the main topbar's Property view.",
        lambda: topbar_logo.build_default_logo_html("real_estate"), _scoutai_wrap, None,
        brand, logo_html_nonce,
    )
    st.markdown("---")
    cars_html = _render_logo_slot(
        "cars", "Cars logo",
        "Shown in the main topbar's Cars view.",
        lambda: topbar_logo.build_default_logo_html("cars"), _scoutai_wrap, None,
        brand, logo_html_nonce,
    )
    st.markdown("---")
    guest_html = _render_logo_slot(
        "guest", "Guest logo",
        "Shown on the anonymous landing page and the Sign In/Register page (they share this one logo).",
        topbar_logo.build_default_guest_logo_html, _guest_wrap, topbar_logo.inject_guest_logo_css,
        brand, logo_html_nonce,
    )

    st.markdown("---")
    save_col, reset_col = st.columns([1, 1])
    with save_col:
        if st.button(":material/save: Save brand settings", type="primary", use_container_width=True):
            new_settings = dict(brand)
            new_settings["accent_color"] = accent_color
            new_settings["font_display"] = font_display
            new_settings["font_body"] = font_body
            new_settings["font_mono"] = font_mono
            new_settings["logo_html_real_estate"] = real_estate_html.strip()
            new_settings["logo_html_cars"] = cars_html.strip()
            new_settings["logo_html_guest"] = guest_html.strip()
            if remove_logo:
                new_settings["logo_data_uri"] = ""
            elif uploaded_logo is not None:
                if uploaded_logo.size > _MAX_LOGO_BYTES:
                    st.error(f"Logo file is too large ({uploaded_logo.size // 1024} KB) - keep it under "
                              f"{_MAX_LOGO_BYTES // 1024} KB.")
                    st.stop()
                mime = uploaded_logo.type or "image/png"
                encoded = base64.b64encode(uploaded_logo.getvalue()).decode("ascii")
                new_settings["logo_data_uri"] = f"data:{mime};base64,{encoded}"
            db.save_brand_settings(new_settings)
            st.toast("Brand settings updated.")
            st.rerun()
    with reset_col:
        if st.button(":material/restart_alt: Reset to defaults", use_container_width=True):
            # Presets are a saved library the admin builds up over time,
            # separate from what's currently ACTIVE - clear_brand_settings
            # would delete the whole settings row (presets included), so
            # reset everything else but carry the presets forward instead
            # of wiping out a library just because the admin wanted the
            # active color/fonts/logos back to default.
            preserved_presets = {k: v for k, v in brand.items() if k.startswith("logo_presets_")}
            db.save_brand_settings({**db.DEFAULT_BRAND_SETTINGS, **preserved_presets})
            # Widgets keep their session_state value across reruns once
            # touched, ignoring a changed `value=`/`index=` default - so
            # without this, the picker/dropdowns would keep showing the
            # just-cleared color/fonts even though the DB (and every other
            # page's CSS) already reverted.
            for widget_key in ("brand_accent_picker", "brand_font_display", "brand_font_body", "brand_font_mono"):
                st.session_state.pop(widget_key, None)
            # text_area needs a new key entirely, not just a cleared
            # session_state entry - see the comment above logo_html_nonce.
            st.session_state.brand_logo_html_nonce = logo_html_nonce + 1
            st.toast("Brand settings reset to defaults.")
            st.rerun()


def render_admin_control_panel():
    st.markdown("""
        <style>
        div.st-key-admin_hero {
            background: var(--radar-gradient-hero);
            padding: var(--radar-space-6) var(--radar-space-7);
            margin-bottom: var(--radar-space-5);
            border-radius: 0 0 var(--radar-radius-xl) var(--radar-radius-xl);
        }
        div[class*="st-key-admin_stat_card_"] button {
            background: var(--radar-surface) !important;
            border: 1px solid var(--radar-border) !important;
            border-left: 3px solid var(--radar-primary) !important;
            border-radius: var(--radar-radius-md) !important;
            padding: 10px 14px !important;
            text-align: left !important;
            width: 100% !important;
            height: auto !important;
            white-space: pre-line !important;
        }
        div[class*="st-key-admin_stat_card_"] button:hover {
            border-color: var(--radar-primary) !important;
            box-shadow: var(--radar-shadow-sm);
        }
        div[class*="st-key-admin_stat_card_"] button p {
            text-align: left !important;
        }
        </style>
    """, unsafe_allow_html=True)

    if st.button("← Back to Dashboard", key="admin_back_to_dashboard_btn"):
        st.session_state.current_page = "Find a Car" if st.session_state.get("active_category") == "cars" else "Run Property Scans"
        st.rerun()

    current_role = st.session_state.user_role
    if not roles.is_staff(current_role):
        # Defense in depth - the topbar only shows the "Admin Controls"
        # button to staff, but this page shouldn't trust that alone.
        st.error("You don't have access to this page.")
        return

    if current_role == "support":
        # Deliberately no hero dashboard, stat cards, or business-metric
        # tabs (Revenue, API Usage, Pricing, Add Admins) for support - just
        # straight to the one tab that actually helps a customer. See
        # _render_users_tab_body's docstring for what's further narrowed
        # within it.
        st.markdown(f"""
            <div style='display:flex; align-items:center; gap:10px; margin-bottom:var(--radar-space-4);'>
                {svg_icon("shield-check", size=20, color="var(--radar-primary)")}
                <span style='font-weight:700; font-size:var(--radar-text-xl); color:var(--radar-navy);'>Support Console</span>
            </div>
        """, unsafe_allow_html=True)
        _render_users_tab_body(current_role)
        return

    with st.container(key="admin_hero"):
        st.markdown(f"""
            <div style='text-align:center; max-width:760px; margin:0 auto;'>
                <div style='display:flex; align-items:center; justify-content:center; gap:14px; margin-bottom:10px;'>
                    <div style='background: var(--radar-gradient-brand); width: 48px; height: 48px;
                                border-radius: var(--radar-radius-md); display:flex; align-items:center; justify-content:center; flex-shrink:0;'>
                        {svg_icon("shield-check", size=24, color="white")}
                    </div>
                    <div style='font-family:var(--radar-font-display); font-size:32px; font-weight:800; color:white; line-height:1.2;'>Admin Controls</div>
                </div>
                <div style='font-size:16px; color:var(--radar-text-on-dark-muted);'>Manage users, credits, and admin access</div>
            </div>
        """, unsafe_allow_html=True)

    # ---- USAGE DASHBOARD ----
    stats = db.get_usage_stats()
    signup_stats = db.get_signup_stats()
    scan_breakdown = db.get_scan_live_mock_breakdown()
    revenue_stats = db.get_revenue_stats()

    # Card-rendering functions are defined here (before the tabs exist) but
    # not called until inside the Dashboard tab below - keeps the data
    # fetches (stats/signup_stats/scan_breakdown/revenue_stats) in one place
    # up top, since API Usage and Revenue tabs also read scan_breakdown/
    # revenue_stats directly.
    def _render_signup_trend_card():
        with st.container(key="admin_signup_trend_card"):
            st.markdown("""<style>div.st-key-admin_signup_trend_card { background: var(--radar-surface);
                border: 1px solid var(--radar-border); border-radius: var(--radar-radius-md);
                padding: var(--radar-space-4); margin-bottom: var(--radar-space-4); }</style>""",
                        unsafe_allow_html=True)
            trend_head_col1, trend_head_col2 = st.columns([2, 1])
            with trend_head_col1:
                st.markdown(f"""
                    <div style='display:flex; align-items:center; gap:8px; padding-top:6px;'>
                        {svg_icon("chart", size=16, color="var(--radar-primary)")}
                        <span style='font-weight:700; color:var(--radar-navy); font-size:14px;'>Signup Trend</span>
                    </div>
                """, unsafe_allow_html=True)
            with trend_head_col2:
                trend_days = st.selectbox("Window", [7, 14, 30, 60, 90, 180, 365], index=2,
                                           key="admin_signup_trend_days", label_visibility="collapsed",
                                           format_func=lambda d: f"Last {d} days")
            trend_stats = db.get_signup_stats(trend_days=trend_days)
            if trend_stats["daily"]:
                trend_df = pd.DataFrame(trend_stats["daily"], columns=["Date", "New Signups"]).set_index("Date")
                st.line_chart(trend_df, height=180)
            else:
                st.caption(f"No signups in the last {trend_days} days.")

    def _render_zero_credit_card():
        with st.container(key="admin_zero_credit_card"):
            st.markdown("""<style>div.st-key-admin_zero_credit_card { background: var(--radar-surface);
                border: 1px solid var(--radar-border); border-radius: var(--radar-radius-md);
                padding: var(--radar-space-4); margin-bottom: var(--radar-space-4); }</style>""",
                        unsafe_allow_html=True)
            st.markdown(f"""
                <div style='display:flex; align-items:center; gap:8px; margin-bottom:2px;'>
                    {svg_icon("chart", size=16, color="var(--radar-warning)")}
                    <span style='font-weight:700; color:var(--radar-navy); font-size:14px;'>{len(stats['zero_credit_users'])} User(s) at 0 Credits</span>
                </div>
            """, unsafe_allow_html=True)
            st.caption("They've used up their free scans and haven't purchased more - good candidates for a win-back offer or a bonus-credit nudge (see the Users tab).")
            for zc_email, zc_name in stats["zero_credit_users"]:
                st.caption(f"• {zc_name or zc_email} ({zc_email})" if zc_name else f"• {zc_email}")

    def _render_rentcast_card():
        rentcast_config = db.get_rentcast_config()
        if engine.is_rentcast_configured():
            rc_used = db.get_rentcast_usage_this_month()
            rc_limit = rentcast_config["monthly_limit"]
            rc_fraction = min(rc_used / rc_limit, 1.0) if rc_limit else 0
            if rc_used >= rc_limit:
                rc_color, rc_status = "var(--radar-danger)", "Limit reached - scans are using simulated data until next month"
            elif rc_fraction * 100 >= rentcast_config["alert_threshold_pct"]:
                rc_color, rc_status = "var(--radar-warning)", "Getting close to the monthly limit"
            else:
                rc_color, rc_status = "var(--radar-success)", "Within budget"

            with st.container(key="admin_rentcast_usage"):
                st.markdown(f"""<style>div.st-key-admin_rentcast_usage {{ background: var(--radar-surface);
                    border: 1px solid var(--radar-border); border-radius: var(--radar-radius-md);
                    padding: var(--radar-space-4); margin-bottom: var(--radar-space-4); }}</style>""",
                            unsafe_allow_html=True)
                st.markdown(f"""
                    <div style='display:flex; align-items:center; justify-content:space-between; margin-bottom:6px;'>
                        <div style='display:flex; align-items:center; gap:8px;'>
                            {svg_icon("chart", size=16, color=rc_color)}
                            <span style='font-weight:700; color:var(--radar-navy); font-size:14px;'>RentCast API Usage This Month</span>
                        </div>
                        <span style='font-weight:700; color:{rc_color}; font-size:14px;'>{rc_used} / {rc_limit}</span>
                    </div>
                """, unsafe_allow_html=True)
                st.progress(rc_fraction)
                st.caption(f"{rc_status} · Plan on file: {rentcast_config['plan_name']} (${rentcast_config['monthly_cost']:,.0f}/mo) - edit in the Pricing tab")
        else:
            st.info("RentCast isn't configured yet - scans are using simulated listing data. Add RENTCAST_API_KEY to .env to switch on real listings.", icon=":material/info:")

    def _render_autodev_card():
        # Cars' equivalent of the RentCast card above - now admin-editable
        # via db.get_autodev_config(), the same app_settings-backed pattern
        # as get_rentcast_config()/get_places_config()/get_openai_config().
        if car_engine.is_autodev_configured():
            ad_used = db.get_autodev_usage_this_month()
            ad_limit = db.get_autodev_config()["monthly_limit"]
            ad_fraction = min(ad_used / ad_limit, 1.0) if ad_limit else 0
            if ad_used >= ad_limit:
                ad_color, ad_status = "var(--radar-danger)", "Limit reached - car searches are using simulated data until next month"
            elif ad_fraction >= 0.8:
                ad_color, ad_status = "var(--radar-warning)", "Getting close to the monthly limit"
            else:
                ad_color, ad_status = "var(--radar-success)", "Within budget"

            with st.container(key="admin_autodev_usage"):
                st.markdown(f"""<style>div.st-key-admin_autodev_usage {{ background: var(--radar-surface);
                    border: 1px solid var(--radar-border); border-radius: var(--radar-radius-md);
                    padding: var(--radar-space-4); margin-bottom: var(--radar-space-4); }}</style>""",
                            unsafe_allow_html=True)
                st.markdown(f"""
                    <div style='display:flex; align-items:center; justify-content:space-between; margin-bottom:6px;'>
                        <div style='display:flex; align-items:center; gap:8px;'>
                            {svg_icon("chart", size=16, color=ad_color)}
                            <span style='font-weight:700; color:var(--radar-navy); font-size:14px;'>Auto.dev API Usage This Month</span>
                        </div>
                        <span style='font-weight:700; color:{ad_color}; font-size:14px;'>{ad_used} / {ad_limit}</span>
                    </div>
                """, unsafe_allow_html=True)
                st.progress(ad_fraction)
                st.caption(f"{ad_status} · {ad_limit:,} calls/mo plan - powers Cars category search - edit in the Pricing tab")
        else:
            st.info("Auto.dev isn't configured yet - Cars searches are using simulated listing data. Add AUTODEV_API_KEY to .env to switch on real listings.", icon=":material/info:")

    # Pricing and Add Admins are super_admin-exclusive - real financial
    # control and the privilege-escalation surface respectively (see
    # roles.py) - so they're left out of the tab bar entirely for 'admin',
    # not just hidden-but-present. Built from a label list + dict lookup
    # (rather than fixed positional unpacking like `t1, t2 = st.tabs(...)`)
    # specifically because the tab COUNT itself varies by role. Dashboard
    # is first and always present (both admin and super_admin reach this
    # code path - support gets its own separate narrowed view above and
    # never sees this tab bar at all) - placing the tab bar directly under
    # the hero, with the stat-card overview as its own tab instead of
    # always-visible content, means reaching Users/API Usage/etc. no longer
    # requires scrolling past the whole dashboard first.
    nav_items = [
        {"label": "Dashboard", "icon": ":material/dashboard:"},
        {"label": "Users", "icon": ":material/group:"},
        {"label": "API Usage", "icon": ":material/api:"},
        {"label": "Revenue", "icon": ":material/payments:"},
    ]
    if roles.is_super_admin(current_role):
        nav_items.append({"label": "Pricing", "icon": ":material/sell:"})
    nav_items.append({"label": "Broadcast", "icon": ":material/campaign:"})
    if roles.is_super_admin(current_role):
        nav_items.append({"label": "Add Admins", "icon": ":material/admin_panel_settings:"})
        nav_items.append({"label": "Design Standards", "icon": ":material/design_services:"})
        nav_items.append({"label": "Brand & Design", "icon": ":material/palette:"})

    nav_col, content_col = st.columns([1, 4])
    with nav_col:
        active_section = render_side_nav(nav_items, key_prefix="admin_nav")

    with content_col:
        if active_section == "Dashboard":
            _render_dashboard_tab(stats, signup_stats, scan_breakdown, revenue_stats,
                                   _render_signup_trend_card, _render_zero_credit_card, _render_rentcast_card, _render_autodev_card)
        elif active_section == "Users":
            _render_users_tab_body(current_role)
        elif active_section == "API Usage":
            _render_api_usage_tab(scan_breakdown)
        elif active_section == "Revenue":
            _render_revenue_tab(revenue_stats)
        elif active_section == "Pricing" and roles.is_super_admin(current_role):
            _render_pricing_tab()
        elif active_section == "Broadcast":
            _render_broadcast_tab()
        elif active_section == "Add Admins" and roles.is_super_admin(current_role):
            _render_add_admins_tab(current_role)
        elif active_section == "Design Standards" and roles.is_super_admin(current_role):
            _render_design_standards_tab()
        elif active_section == "Brand & Design" and roles.is_super_admin(current_role):
            _render_brand_design_tab()
