import streamlit as st
import pandas as pd
import database as db
import agent_engine as engine
import email_utils
import plan_limits
import roles
from icons import icon as svg_icon
from dashboard_grid import render_dashboard_grid


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
            use_container_width=True, hide_index=True,
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
            use_container_width=True, hide_index=True,
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
            use_container_width=True, hide_index=True,
        )
    st.caption("Users at 0 credits (upsell targets) are listed below the stat cards on the main dashboard.")


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
    if not selected_row:
        return

    (u_id, u_email, u_name, u_role, u_plan, u_credits, u_suspended, u_created_at,
     u_scan_count, u_live_scan_count, u_rentcast_calls, u_total_spent,
     u_account_id, u_first_name, u_middle_name, u_last_name) = selected_row

    st.markdown("---")
    with st.container(key=f"admin_user_manage_panel_{u_id}"):
        st.markdown(f"""<style>div.st-key-admin_user_manage_panel_{u_id} {{ background: var(--radar-surface);
            border: 1px solid var(--radar-border); border-radius: var(--radar-radius-md);
            padding: var(--radar-space-4); }}</style>""",
                    unsafe_allow_html=True)

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
            if st.button(":material/save: Save Profile", key=f"user_profile_save_btn_{u_id}", use_container_width=True):
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
            new_cred = st.number_input("Credits", min_value=0, value=u_credits, key=f"user_cred_field_{u_id}")
        with col_u3:
            st.markdown("<div style='margin-top:28px;'></div>", unsafe_allow_html=True)
            if st.button(":material/save: Save", key=f"user_save_btn_{u_id}", use_container_width=True):
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
                if st.button(":material/save: Save", key=f"pkg_save_{tier_name}", use_container_width=True):
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
        verified_note = f"Last verified {rc_conf['verified_at']}" if rc_conf["verified_at"] else "Never verified - RentCast has no price-change API, so re-check their pricing page periodically and re-save here."
        st.caption(verified_note)
        if st.form_submit_button(":material/save: Save RentCast Plan", use_container_width=True):
            db.update_rentcast_config(rc_limit_input, rc_name_input, rc_cost_input)
            st.toast("RentCast plan updated.")
            st.rerun()

    st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)
    oa_conf = db.get_openai_config()
    oa_used = db.get_openai_usage_this_month()
    with st.form("admin_openai_config_form"):
        st.markdown("**OpenAI report generation**")
        st.caption(f"{oa_used} / {oa_conf['monthly_limit']} calls used this month - once this cap is hit, scans fall back to the free local report generator instead of calling OpenAI.")
        oa_limit_input = st.number_input("Monthly call limit", min_value=1, value=int(oa_conf["monthly_limit"]))
        if st.form_submit_button(":material/save: Save OpenAI Limit", use_container_width=True):
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
        st.session_state.current_page = "Run Property Scans"
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
                    <div style='font-size:32px; font-weight:800; color:white; line-height:1.2;'>Admin Controls</div>
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
            elif rc_fraction >= 0.8:
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
    tab_labels = [":material/dashboard: Dashboard", ":material/group: Users", ":material/api: API Usage", ":material/payments: Revenue"]
    if roles.is_super_admin(current_role):
        tab_labels.append(":material/sell: Pricing")
    tab_labels.append(":material/campaign: Broadcast")
    if roles.is_super_admin(current_role):
        tab_labels.append(":material/admin_panel_settings: Add Admins")
    tab_map = dict(zip(tab_labels, st.tabs(tab_labels)))

    with tab_map[":material/dashboard: Dashboard"]:
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

        render_dashboard_grid("admin", dashboard_cards, default_grid_columns=4)

    with tab_map[":material/group: Users"]:
        _render_users_tab_body(current_role)

    with tab_map[":material/api: API Usage"]:
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
            st.dataframe(usage_df, use_container_width=True, hide_index=True)

    with tab_map[":material/payments: Revenue"]:
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
            st.dataframe(tx_df, use_container_width=True, hide_index=True)

    if roles.is_super_admin(current_role):
        with tab_map[":material/sell: Pricing"]:
            _render_pricing_tab()

    if roles.is_super_admin(current_role):
        with tab_map[":material/admin_panel_settings: Add Admins"]:
            st.markdown("### Grant Staff Access")
            st.caption("Only a super_admin can grant or change roles - see the role descriptions below.")
            with st.expander(":material/info: What each role can do"):
                st.caption("**Support** - the Users tab only, and just enough to help a customer: credits, suspend/reactivate, password reset. No pricing, revenue, or profile-editing access.")
                st.caption("**Admin** - full day-to-day operations: Users (full), API Usage, Revenue, Broadcast. Can't edit pricing/cost config or grant roles to anyone.")
                st.caption("**Super Admin** - everything, including this tab and Pricing. Keep this to the smallest number of people who genuinely need it.")

            grant_mode = st.radio("How", ["Promote an existing user", "Create a new account"], horizontal=True, key="admin_grant_mode")

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

    with tab_map[":material/campaign: Broadcast"]:
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
