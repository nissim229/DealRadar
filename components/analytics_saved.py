"""
components/analytics_saved.py
The Saved Properties tab, split out of components/analytics.py (Section 5
monolith-split plan): properties starred from any scan, shown in the same
2-column card grid the scan results use, each with its own saved-at
timestamp.
"""
import streamlit as st
import database as db
import roles
import agent_engine
import email_utils
from underwriting import compute_deal_metrics
from icons import icon as svg_icon
from components.property_card import render_property_card
from data_utils import relative_time

from components.analytics_atoms import _safe_hoa, _format_relative_time, render_empty_state


def _render_check_now(user_id, address, price, latitude, longitude, last_price_checked_at, is_admin, has_credits):
    """The manual price-drop 'Check Now' button for one saved property.
    Visible to every signed-in user regardless of plan (Saved Properties
    itself is already gated behind sign-in - see analytics_dashboard.py's
    is_guest branch - so there's no guest case to handle here); whether it
    actually WORKS depends on the same credits every plan already has
    (Free/Starter/Pro/Enterprise all include some), same cost as a live
    scan, or staff status - not a separate feature flag. Owner's own
    framing: this reuses the existing 'what goes to package' answer
    (credits) instead of inventing a new one."""
    can_check = is_admin or has_credits
    cols = st.columns([3, 2])
    with cols[0]:
        if last_price_checked_at:
            st.caption(f":material/history: Price checked {relative_time(last_price_checked_at)}")
        else:
            st.caption(":material/history: Price not manually checked yet")
    with cols[1]:
        clicked = st.button(
            "Check Now", key=f"check_now_{address}", use_container_width=True,
            disabled=not can_check,
            help=None if can_check else "Out of credits - buy more or upgrade your plan to check for price drops.",
        )
    if not clicked:
        return
    with st.spinner("Checking current price..."):
        fresh_price = agent_engine.check_saved_property_price(latitude, longitude, address, user_id=user_id)
    if not is_admin:
        db.deduct_credit(user_id)
        st.session_state.user_credits = max(0, st.session_state.user_credits - 1)
    if fresh_price is None:
        db.record_price_check_not_found(user_id, address)
        st.toast(f"{address}: not currently found among active listings - no fresh price data available.", icon=":material/info:")
        st.rerun()
    old_price = db.record_price_check(user_id, address, fresh_price)
    if old_price is not None and fresh_price < old_price:
        st.toast(f"Price dropped: {address} is now ${fresh_price:,.0f} (was ${old_price:,.0f}).", icon=":material/trending_down:")
        if st.session_state.user_settings.get("notify_price_drop"):
            email_utils.send_price_drop_email(st.session_state.user_email, address, old_price, fresh_price)
    else:
        st.toast(f"{address}: no price drop - still ${fresh_price:,.0f}.", icon=":material/check_circle:")
    st.rerun()


def _render_saved_properties_tab(view_mode, calc_rent, calc_vacancy_pct, calc_tax_rate, calc_ins_rate, calc_down_pct, calc_interest, calc_target_yield):
    st.markdown(f"""
        <div style='display:flex; align-items:center; gap:10px; margin-bottom:2px;'>
            {svg_icon("star-filled", size=20, color="var(--radar-warning)")}
            <span style='font-weight:700; font-size:var(--radar-text-xl); color:var(--radar-navy);'>Your Saved Properties</span>
        </div>
    """, unsafe_allow_html=True)
    st.caption("Properties you've starred from any scan, with your personal notes attached. Note: since DealRadar currently uses simulated listing data, there's no live 'still active' status to verify here - that would require a licensed MLS/IDX data feed.")

    saved_rows = db.get_saved_properties(st.session_state.user_id)
    is_admin = roles.is_admin_or_above(st.session_state.user_role)
    has_credits = st.session_state.user_credits > 0
    if saved_rows:
        # Same 2-column grid the main scan results use, instead of one
        # full-width card per row - the photo carousel is a fixed
        # height, so at full page width it read as a stretched-out
        # banner. This matches it back to the same proportions as
        # everywhere else in the app.
        for pair_start in range(0, len(saved_rows), 2):
            pair_rows = saved_rows[pair_start:pair_start + 2]
            grid_cols = st.columns(2)
            for slot, s_row in enumerate(pair_rows):
                s_idx = pair_start + slot
                address, title, price, beds, baths, latitude, longitude, notes, saved_at, last_price_checked_at = s_row
                row_item = {
                    "title": title, "address": address, "price": price,
                    "beds": beds, "baths": baths, "latitude": latitude, "longitude": longitude,
                }
                metrics = compute_deal_metrics(
                    float(price), calc_rent, calc_vacancy_pct, calc_tax_rate,
                    calc_ins_rate, calc_down_pct, calc_interest, calc_target_yield,
                    # Saved-property rows don't carry HOA yet - the
                    # saved_properties table predates this field and
                    # only stores address/title/price/beds/baths/lat/lon
                    # (see database.py's save_property). Safe no-op via
                    # _safe_hoa (returns 0, matching prior behavior)
                    # rather than a schema migration, which is a bigger
                    # change than this pass covers - see [[deferred-
                    # rentcast-raw-data-and-hoa]] for the follow-up.
                    hoa_monthly=_safe_hoa(row_item)
                )
                with grid_cols[slot]:
                    st.caption(_format_relative_time(saved_at))
                    render_property_card(s_idx, row_item, metrics, view_mode, "saved_card", False,
                                          st.session_state.user_id, st.session_state.get("distance_reference_point"),
                                          calc_target_yield,
                                          {"down_pct": calc_down_pct, "interest": calc_interest, "rent": calc_rent,
                                           "vacancy": calc_vacancy_pct, "tax_rate": calc_tax_rate, "ins_rate": calc_ins_rate})
                    _render_check_now(st.session_state.user_id, address, price, latitude, longitude,
                                       last_price_checked_at, is_admin, has_credits)
    else:
        render_empty_state(
            "star-outline", "No saved properties yet",
            "Star (☆) any property from a scan to keep track of it here, along with your own notes.",
            accent="var(--radar-warning)",
        )

