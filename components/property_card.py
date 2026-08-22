"""
property_card.py
The property card component - photo, badge, price, and the tabbed detail
expander (Why This Grade / What-If Calculator / Photos / Notes & Neighborhood).
"""

import html
import streamlit as st
import streamlit.components.v1 as components
import database as db
import agent_engine as engine
import pandas as pd
import plan_limits
import roles
import email_utils
from underwriting import GRADE_STYLES, render_deal_badge
from pdf_export import generate_single_property_pdf_link
from whatif_calculator import render_whatif_calculator_html
from photo_carousel import render_photo_carousel_html
from components import pricing
from icons import icon as svg_icon
from data_utils import clean_value, relative_time
from guest_mode import guest_action_button


def render_grade_explanation(metrics, calc_target_yield):
    """Renders a beginner-friendly breakdown of why a property got its grade,
    as a clean table with each term defined, instead of a dense paragraph."""
    grade = metrics["grade"]
    margin = metrics["coc"] - calc_target_yield

    st.markdown(f"**{GRADE_STYLES[grade]['simple_verdict']}**")
    st.markdown("---")

    rows = [
        ("💵 Rental income after vacancy", f"${metrics['eff_gross_income']:,.0f}/yr", "Rent you'd actually collect, assuming it sits empty sometimes"),
        ("🏛️ Taxes + insurance", f"${metrics['annual_taxes'] + metrics['annual_insurance']:,.0f}/yr", "Ongoing ownership costs, before the mortgage"),
    ]
    # Only shown when there actually is one - most single-family listings
    # have none, and a $0 row for every property would just be noise.
    # When it's non-zero, it's a real cost this grade already accounts
    # for (see underwriting.py's compute_deal_metrics), not an omission.
    if metrics.get("annual_hoa"):
        rows.append(("🏘️ HOA fees", f"${metrics['annual_hoa']:,.0f}/yr", f"${metrics['monthly_hoa']:,.0f}/mo homeowners association dues"))
    # Same "only shown when non-zero" pattern as HOA above - management
    # defaults to $0 (no assumption made unless a caller opts in), but
    # maintenance defaults to a real 5%-of-rent reserve (matching the
    # What-If sandbox's own default), so this row now appears on every
    # card by default - previously this cost was silently baked into NOI
    # with no line explaining it, which made this table's own numbers
    # not add up (rent minus taxes/insurance no longer equals NOI once
    # this exists) if left unlabeled.
    if metrics.get("annual_mgmt_fee"):
        rows.append(("🧰 Property management", f"${metrics['annual_mgmt_fee']:,.0f}/yr", "Fee for a property manager, as a % of rent collected"))
    if metrics.get("annual_maintenance"):
        rows.append(("🔧 Maintenance reserve", f"${metrics['annual_maintenance']:,.0f}/yr", "Ongoing repairs/upkeep, set aside as a % of rent"))
    rows += [
        ("📊 Net Operating Income (NOI)", f"${metrics['noi']:,.0f}/yr", "Income minus taxes/insurance/HOA/management/maintenance - your profit before the mortgage"),
        ("🏦 Mortgage payment", f"${metrics['a_debt']:,.0f}/yr", "What you pay the bank each year on the loan"),
        ("💰 Cash flow", f"${metrics['cashflow']:,.0f}/yr", "NOI minus mortgage payment - what's left in your pocket"),
    ]
    if metrics.get("closing_costs"):
        rows.append(("🧾 Closing costs", f"${metrics['closing_costs']:,.0f}", "One-time cost at purchase, added to your total cash needed"))
    if metrics.get("rehab_cost"):
        rows.append(("🛠️ Rehab budget", f"${metrics['rehab_cost']:,.0f}", "One-time renovation cost before move-in, added to your total cash needed"))
    # Help text names exactly the cash-needed components actually present
    # for this property, rather than a fixed phrase that would silently
    # go stale/inaccurate the moment a second upfront-cost line (rehab)
    # existed alongside the first (closing costs).
    upfront_extras = [label for label, present in
                      [("closing costs", metrics.get("closing_costs")), ("rehab budget", metrics.get("rehab_cost"))]
                      if present]
    coc_help = ("Cash flow ÷ (your down payment + " + " + ".join(upfront_extras) + ") - your real return on the cash you put in"
                if upfront_extras else
                "Cash flow ÷ your down payment - your real return on the cash you put in")
    rows.append(("🎯 Cash-on-Cash Return (your ROI)", f"{metrics['coc']:.2f}%", coc_help))
    if grade == "excellent":
        rows.append(("✅ Vs. your target", f"+{margin:.2f} pts", f"Clears your {calc_target_yield:.2f}% target"))
    elif grade == "average":
        rows.append(("⚠️ Vs. your target", f"{margin:.2f} pts", f"Falls short of your {calc_target_yield:.2f}% target"))
    else:
        rows.append(("🛑 Vs. your target", "N/A", "Cash flow is negative - the mortgage costs more than the property brings in"))

    breakdown_df = pd.DataFrame(rows, columns=["Metric", "Value", "What it means"])
    st.dataframe(breakdown_df, hide_index=True, width="stretch", height=len(breakdown_df) * 35 + 38)

    st.caption(
        "**Quick glossary** — "
        "**NOI**: rental profit before the mortgage. "
        "**Cap Rate**: NOI ÷ purchase price (return if you paid 100% cash). "
        "**Cash-on-Cash Return (ROI)**: your actual return on just the cash you put down. "
        "**MAO**: the most you could pay and still hit your target return."
    )


def _render_property_detail_tabs(row_item, metrics, calc_target_yield, current_assumptions, user_id, address, key_prefix, idx, reference_point, open_tab=None):
    """Shared tab content (Why This Grade / What-If / Photos / Notes) used by
    the modal dialog. Factored out so the dialog function and any future
    caller render identical content from one source.

    open_tab: if set to "photos", the Photos tab is moved to the front so
    the dialog opens directly on it - used by the card's photo-expand
    button, since st.tabs always starts on its first entry and there's no
    way to jump to an arbitrary tab index after the fact."""
    sv_status = engine.get_street_view_status(row_item.get("latitude"), row_item.get("longitude"))
    has_imagery = sv_status == "OK"
    street_view_url = engine.get_street_view_image_url(row_item.get("latitude"), row_item.get("longitude")) if has_imagery else None

    def _render_why():
        render_grade_explanation(metrics, calc_target_yield)

    def _render_whatif():
        st.caption("Try different financing terms for this specific property - without changing your assumptions for every other property. Drag the sliders, results update instantly.")
        defaults = current_assumptions or {}
        calc_html = render_whatif_calculator_html(row_item, defaults, calc_target_yield)
        components.html(calc_html, height=720, scrolling=True)

    def _render_photos():
        if street_view_url:
            gallery_urls = engine.get_street_view_gallery_urls(row_item.get("latitude"), row_item.get("longitude"))
            if gallery_urls:
                compass_labels = ["North", "East", "South", "West"]
                slide_labels = [compass_labels[i] if i < len(compass_labels) else f"{i * (360 // len(gallery_urls))}°"
                                 for i in range(len(gallery_urls))]
                tour_html = render_photo_carousel_html(gallery_urls, height=440, slide_labels=slide_labels)
                components.html(tour_html, height=440)
                st.caption("Drag/swipe or use the arrows to look around - views looking in each compass direction from this location, not interior listing photos, which require a licensed MLS/IDX data partnership.")
        else:
            st.caption(":material/photo_camera: Google Street View hasn't photographed this exact spot - this happens on some streets even in valid, real locations. The property is still a legitimate match, just without a street-level photo.")

        if address:
            mls_number = row_item.get("mls_number")
            if mls_number:
                mls_label = f"MLS# {mls_number}" + (f" · {row_item['mls_name']}" if row_item.get("mls_name") else "")
                st.caption(mls_label)
            photos_hint = (
                "Want real interior/listing photos for this address? Redfin's search below includes this property's MLS# for a tighter match - not a guaranteed direct link (no property ID from either site is available to us):"
                if mls_number else
                "Want real interior/listing photos for this address? These open a search (not a guaranteed direct link - we have no MLS# for this one, and no property ID from either site) on the site that actually licenses them:"
            )
            st.caption(photos_hint)
            zillow_col, redfin_col = st.columns(2)
            with zillow_col:
                st.link_button(":material/open_in_new: Zillow", engine.build_zillow_search_url(address, mls_number), width="stretch")
            with redfin_col:
                st.link_button(":material/open_in_new: Redfin", engine.build_redfin_search_url(address, mls_number), width="stretch")

    def _render_details():
        # Everything RentCast returns for this listing that isn't already
        # shown elsewhere on the card - the user's own framing was "it
        # brings lots of data, we should show all of it for the
        # property", not just the price/beds/baths summary this app
        # extracted before. Blank/missing fields (a mock listing, or a
        # real one RentCast didn't populate for) are simply omitted
        # rather than shown as "N/A" clutter.
        _clean = clean_value

        detail_rows = []
        hoa_val = _clean(row_item.get("hoa_monthly"))
        if hoa_val:
            detail_rows.append(("HOA fee", f"${float(hoa_val):,.0f}/mo"))
        year_built = _clean(row_item.get("year_built"))
        if year_built:
            detail_rows.append(("Year built", str(int(year_built))))
        lot_size = _clean(row_item.get("lot_size"))
        if lot_size:
            detail_rows.append(("Lot size", f"{int(lot_size):,} sqft"))
        days_on_market = _clean(row_item.get("days_on_market"))
        if days_on_market is not None:
            detail_rows.append(("Days on market", str(int(days_on_market))))
        listed_date = _clean(row_item.get("listed_date"))
        if listed_date:
            detail_rows.append(("Listed", str(listed_date)[:10]))
        listing_type = _clean(row_item.get("listing_type"))
        if listing_type:
            detail_rows.append(("Listing type", str(listing_type)))
        status = _clean(row_item.get("status"))
        if status:
            detail_rows.append(("Status", str(status)))
        county = _clean(row_item.get("county"))
        if county:
            loc_bits = [county]
            state = _clean(row_item.get("state"))
            if state:
                loc_bits.append(state)
            zip_code = _clean(row_item.get("zip_code"))
            if zip_code:
                loc_bits.append(str(zip_code))
            detail_rows.append(("County / State / ZIP", ", ".join(str(b) for b in loc_bits)))

        if detail_rows:
            st.markdown("##### :material/info: Property Details")
            details_df = pd.DataFrame(detail_rows, columns=["Field", "Value"])
            st.dataframe(details_df, hide_index=True, width="stretch", height=len(details_df) * 35 + 38)
        else:
            st.caption("No additional property details available for this listing.")

        agent_name = _clean(row_item.get("listing_agent_name"))
        office_name = _clean(row_item.get("listing_office_name"))
        if agent_name or office_name:
            st.markdown("##### :material/contact_phone: Listing Contact")
            if agent_name:
                agent_line = agent_name
                agent_phone = _clean(row_item.get("listing_agent_phone"))
                if agent_phone:
                    agent_line += f" · {agent_phone}"
                st.caption(f"Agent: {agent_line}")
            if office_name:
                office_line = office_name
                office_phone = _clean(row_item.get("listing_office_phone"))
                if office_phone:
                    office_line += f" · {office_phone}"
                office_email = _clean(row_item.get("listing_office_email"))
                if office_email:
                    office_line += f" · {office_email}"
                st.caption(f"Office: {office_line}")

        raw = _clean(row_item.get("rentcast_raw"))
        if raw:
            with st.expander(":material/data_object: Full RentCast response for this listing"):
                st.caption("Everything RentCast's API returned for this property, unedited - including fields this app doesn't have a dedicated place for yet.")
                st.json(raw, expanded=False)

    def _render_notes():
        # user_id is None for a guest session - never reaches the DB (a
        # fake id isn't used here either, see guest_mode.py), so there's
        # simply no saved note to read yet.
        existing_notes = db.get_property_notes(user_id, address) if user_id else ""
        note_text = st.text_area("Personal notes", value=existing_notes, key=f"{key_prefix}_notes_{idx}",
                                  placeholder="e.g., Call agent Tuesday, check roof condition...")
        note_col1, note_col2 = st.columns([1, 3])
        with note_col1:
            if guest_action_button("Save Note", "save notes", key=f"{key_prefix}_save_note_{idx}",
                                    type="primary", disabled=note_text == existing_notes):
                if not db.is_property_saved(user_id, address):
                    if plan_limits.is_within_limit(st.session_state.user_role, st.session_state.user_plan,
                                                    "saved_properties", db.count_saved_properties(user_id)):
                        db.save_property(user_id, address, row_item['title'], row_item['price'],
                                          row_item.get('beds', 0), row_item.get('baths', 0),
                                          row_item.get('latitude'), row_item.get('longitude'))
                    else:
                        st.toast(f"Your {st.session_state.user_plan} plan's saved-properties limit is reached.", icon=":material/lock:")
                        pricing.render_pricing_dialog()
                        return
                db.update_property_notes(user_id, address, note_text)
                st.toast("Note saved!")
                st.rerun()

        st.markdown("---")
        if reference_point:
            dist = engine.calculate_distance_miles(row_item.get("latitude"), row_item.get("longitude"),
                                                     reference_point["latitude"], reference_point["longitude"])
            if dist is not None:
                st.markdown("##### :material/straighten: Distance")
                st.caption(f"{dist:.1f} miles from {reference_point['label']}")
                st.markdown("---")

        places_configured = engine.is_places_api_configured()
        not_configured_msg = "Requires a Google Maps API key with Places API enabled - see setup notes."
        no_results_msg = "No results found within 1.5km of this location."

        st.markdown("##### :material/school: Nearby Schools")
        schools = engine.get_nearby_places(row_item.get("latitude"), row_item.get("longitude"), "school")
        if schools:
            for s in schools:
                rating_str = f" · ⭐ {s['rating']}" if s.get("rating") else ""
                dist_str = f" · {s['distance_miles']:.1f} mi" if s.get("distance_miles") is not None else ""
                st.caption(f"{s['name']}{rating_str}{dist_str}")
        else:
            st.caption(no_results_msg if places_configured else not_configured_msg)

        st.markdown("##### :material/directions_transit: Nearby Transit")
        transit = engine.get_nearby_places(row_item.get("latitude"), row_item.get("longitude"), "transit_station")
        if transit:
            for t in transit:
                dist_str = f" · {t['distance_miles']:.1f} mi" if t.get("distance_miles") is not None else ""
                st.caption(f"{t['name']}{dist_str}")
        else:
            st.caption(no_results_msg if places_configured else not_configured_msg)

        st.markdown("---")
        pdf_uri = generate_single_property_pdf_link(row_item, metrics, note_text)
        # html.escape() on the filename before it lands inside a quoted HTML
        # attribute - row_item['title'] can originate from RentCast's own
        # listing data (an external source, not something this app
        # controls the contents of), so a title containing a literal `"`
        # would otherwise break out of the download="..." attribute and
        # inject arbitrary markup/attributes into this unsafe_allow_html
        # block.
        safe_filename = html.escape(f"DealRadar_{row_item['title'].replace(' ', '_')}.html", quote=True)
        st.markdown(f"""
            <a href="{pdf_uri}" download="{safe_filename}" style="text-decoration: none;">
                <div style="background-color: var(--radar-neutral); color: white; text-align: center; padding: 8px; border-radius: var(--radar-radius-sm); font-weight: 500; cursor: pointer; font-size: 13px; display:flex; align-items:center; justify-content:center; gap:6px;">
                    {svg_icon("download", size=14, color="white")} Export This Property to PDF / Print
                </div>
            </a>
        """, unsafe_allow_html=True)

    def _render_price_check():
        # Only ever added to tab_defs below when this exact property is
        # currently saved (db.is_property_saved), so user_id is never a
        # guest's None here - saving already requires sign-in.
        check_info = db.get_saved_property_check_info(user_id, address)
        if not check_info:
            st.caption("This property isn't in your saved list.")
            return
        current_price, last_price_checked_at = check_info
        is_admin = roles.is_admin_or_above(st.session_state.user_role)
        has_credits = st.session_state.user_credits > 0
        can_check = is_admin or has_credits
        st.caption("Spend 1 credit (same cost as a live scan, free for staff) to re-fetch this property's current live price from RentCast and see if it's dropped since you last checked.")
        check_cols = st.columns([3, 2])
        with check_cols[0]:
            if last_price_checked_at:
                st.caption(f":material/history: Price checked {relative_time(last_price_checked_at)}")
            else:
                st.caption(":material/history: Price not manually checked yet")
        with check_cols[1]:
            clicked = st.button(
                "Check Now", key=f"{key_prefix}_price_check_{idx}", width="stretch",
                disabled=not can_check,
                help=None if can_check else "Out of credits - buy more or upgrade your plan to check for price drops.",
            )
        if not clicked:
            return
        with st.spinner("Checking current price..."):
            fresh_price = engine.check_saved_property_price(
                row_item.get("latitude"), row_item.get("longitude"), address, user_id=user_id
            )
        if not is_admin:
            db.deduct_credit(user_id)
            st.session_state.user_credits = max(0, st.session_state.user_credits - 1)
        if fresh_price is None:
            db.record_price_check_not_found(user_id, address)
            st.toast(f"{address}: not currently found among active listings - no fresh price data available.", icon=":material/info:")
            st.rerun()
        old_price = db.record_price_check(user_id, address, fresh_price)
        if old_price is not None and fresh_price < old_price:
            st.toast(f"Price dropped: now ${fresh_price:,.0f} (was ${old_price:,.0f}).", icon=":material/trending_down:")
            if st.session_state.user_settings.get("notify_price_drop"):
                email_utils.send_price_drop_email(st.session_state.user_email, address, old_price, fresh_price)
        else:
            st.toast(f"No price drop - still ${fresh_price:,.0f}.", icon=":material/check_circle:")
        st.rerun()

    tab_defs = [
        ("why", ":material/menu_book: Why This Grade", _render_why),
        ("details", ":material/info: Property Details", _render_details),
        ("whatif", ":material/tune: What-If Calculator", _render_whatif),
        ("photos", ":material/photo_camera: Photos", _render_photos),
        ("notes", ":material/edit_note: Notes & Neighborhood", _render_notes),
    ]
    # Price Check only ever shows for a property that's actually saved -
    # moved here from its old spot inline under every card on the Saved
    # Properties grid (Entry 14) so it stays reachable from every view
    # mode (Properties Only/+Map/Map Only/Table View) once that page
    # started reusing the same shared view-mode functions scan results
    # already had, instead of its own one-off 2-column loop.
    if user_id and db.is_property_saved(user_id, address):
        tab_defs.append(("price_check", ":material/trending_down: Price Check", _render_price_check))
    if open_tab == "photos":
        tab_defs.sort(key=lambda t: t[0] != "photos")

    rendered_tabs = st.tabs([label for _, label, _ in tab_defs])
    for tab_widget, (_, _, render_fn) in zip(rendered_tabs, tab_defs):
        with tab_widget:
            render_fn()


@st.dialog("Property Details", width="large")
def render_property_detail_dialog():
    """Native Streamlit modal - opens as a true overlay layer on top of the
    page (with its own close button and background dim), rather than
    expanding inline. Reads whichever property was last clicked from
    session_state, since st.dialog's title/decoration is fixed at import
    time and can't take per-call arguments directly. Exported (not
    module-private) so a caller that already has a row/metrics in hand -
    e.g. the table view's own "eye" icon column - can jump straight to
    this floating dialog instead of routing through render_property_card's
    inline card + its own "View Full Details" button first."""
    ctx = st.session_state.get("property_dialog_ctx")
    if not ctx:
        st.write("No property selected.")
        return

    row_item = ctx["row_item"]
    st.markdown(f"### {row_item.get('title', 'Property')}")
    st.caption(ctx["address"])
    st.markdown(f"##### ${row_item['price']:,.0f} · {row_item.get('beds', '-')} bd · {row_item.get('baths', '-')} ba")
    st.markdown(render_deal_badge(ctx["metrics"]["grade"]), unsafe_allow_html=True)
    st.markdown("---")

    _render_property_detail_tabs(
        row_item, ctx["metrics"], ctx["calc_target_yield"], ctx["current_assumptions"],
        ctx["user_id"], ctx["address"], ctx["key_prefix"], ctx["idx"], ctx["reference_point"],
        open_tab=ctx.get("open_tab"),
    )


def render_property_card(idx, row_item, metrics, view_mode, key_prefix, is_focused, user_id, reference_point=None,
                          calc_target_yield=8.0, current_assumptions=None, photo_height=250):
    """One property rendered as a photo-forward visual card. Returns True if
    this card was clicked this run (used by the caller to toggle focus on/off).

    photo_height: lets a caller with a cards-per-row control (see
    CARDS_PER_ROW_PHOTO_HEIGHT in analytics_results.py) shrink the photo to
    match a narrower card at a higher per-row count - defaults to this
    app's original fixed 250px for any caller that doesn't have one."""
    focus_clicked = False
    address = row_item.get('address', '')
    card_key = f"{key_prefix}_card_{idx}"

    # Staggered fade-in-up entrance animation, capped so a long results list
    # doesn't force a multi-second wait before the last cards appear.
    entrance_delay = min(idx * 0.06, 0.6)

    st.markdown(f"""
        <style>
        @keyframes cardFadeInUp {{
            from {{ opacity: 0; transform: translateY(14px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}
        div.st-key-{card_key} {{
            background: {'var(--radar-surface-alt)' if is_focused else 'transparent'};
            animation: cardFadeInUp 0.45s ease-out forwards;
            animation-delay: {entrance_delay}s;
            opacity: 0;
            display: flex !important;
            flex-direction: column !important;
            height: 100% !important;
        }}
        /* Cards in the same row already stretch to match the tallest
        sibling (Streamlit's own column layout does this natively), but a
        card with less content (no HOA line, no MLS# line, a one-line vs.
        two-line address) would otherwise leave its "View Full Details"/
        Zillow/Redfin row floating right after its own shorter content,
        misaligned against a taller neighbor's buttons. Pinning the LAST
        direct child (whichever block that is - the link row, or the
        button if address is blank) to the bottom via margin-top:auto
        keeps every card's buttons on the same line regardless of how
        much conditional content came before them. */
        div.st-key-{card_key} > div:last-child {{
            margin-top: auto !important;
        }}
        div.st-key-{card_key}_clicktarget button {{
            background: transparent !important;
            border: none !important;
            padding: 0 !important;
            text-align: left !important;
            font-weight: 700 !important;
            font-size: var(--radar-text-md) !important;
            box-shadow: none !important;
            width: 100% !important;
            justify-content: flex-start !important;
            min-height: 0 !important;
        }}
        div.st-key-{card_key}_clicktarget button:hover {{
            color: var(--radar-primary) !important;
            background: transparent !important;
        }}
        /* The address IS the "Focus" control the caption above the card
        grid refers to - previously styled identically to plain heading
        text (no color, no underline), so nothing on the card visually
        promised it was clickable; a user had to blindly hover it to
        discover the tooltip. The small target icon now gives it the same
        kind of at-a-glance affordance every other clickable icon in this
        app already has. */
        div.st-key-{card_key}_clicktarget button span[role="img"] {{
            color: var(--radar-primary) !important; font-size: 15px !important;
        }}
        div.st-key-{card_key}_clicktarget button:hover span[role="img"] {{
            color: var(--radar-primary-dark) !important;
        }}
        div.st-key-{card_key}_favbtn button {{
            border: none !important;
            background: transparent !important;
            box-shadow: none !important;
            font-size: 26px !important;
            line-height: 1 !important;
            padding: 2px !important;
            min-height: 0 !important;
            color: var(--radar-warning) !important;
        }}
        div.st-key-{card_key}_favbtn button p,
        div.st-key-{card_key}_favbtn button div {{
            font-size: 26px !important;
            line-height: 1 !important;
            color: var(--radar-warning) !important;
        }}
        div.st-key-{card_key}_photowrap {{ position: relative; }}
        div.st-key-{card_key}_expand_btn {{
            position: absolute; top: 18px; right: 18px; z-index: 5; width: 30px;
        }}
        div.st-key-{card_key}_expand_btn button {{
            background: rgba(15,23,42,0.55) !important;
            border: none !important;
            color: white !important;
            border-radius: 50% !important;
            width: 30px !important; height: 30px !important;
            padding: 0 !important; min-height: 0 !important;
            font-size: 14px !important; box-shadow: none !important;
        }}
        div.st-key-{card_key}_expand_btn button:hover {{
            background: rgba(15,23,42,0.85) !important;
        }}
        </style>
    """, unsafe_allow_html=True)

    with st.container(border=True, key=card_key):
        # NOTE: this check only decides which photo to show. It must never
        # cause the property itself to be skipped - a missing photo is not a
        # reason to hide a real match.
        sv_status = engine.get_street_view_status(row_item.get("latitude"), row_item.get("longitude"))
        has_imagery = sv_status == "OK"
        gallery_urls = engine.get_street_view_gallery_urls(row_item.get("latitude"), row_item.get("longitude")) if has_imagery else []
        street_view_url = gallery_urls[0] if gallery_urls else None

        # Photo, price, badge, and dot navigation all render inside one
        # self-contained HTML/JS component - see photo_carousel.py for why.
        with st.container(key=f"{card_key}_photowrap"):
            carousel_html = render_photo_carousel_html(gallery_urls, f"${row_item['price']:,.0f}", render_deal_badge(metrics["grade"]), height=photo_height)
            components.html(carousel_html, height=photo_height)

            # A real Streamlit button positioned in the photo's corner - not
            # a click handler on the image itself, since the carousel lives
            # inside an iframe that can't call back into Python directly.
            # Opens the same details dialog, jumped straight to the big
            # swipeable Photos tab instead of the default first tab.
            if gallery_urls:
                with st.container(key=f"{card_key}_expand_btn"):
                    if st.button(":material/open_in_full:", key=f"{key_prefix}_expand_{idx}", help="View photos full-size"):
                        st.session_state.property_dialog_ctx = {
                            "row_item": row_item, "metrics": metrics, "address": address,
                            "user_id": user_id, "reference_point": reference_point,
                            "calc_target_yield": calc_target_yield, "current_assumptions": current_assumptions,
                            "key_prefix": key_prefix, "idx": idx, "open_tab": "photos",
                        }
                        render_property_detail_dialog()

        info_col, action_col = st.columns([4, 1])
        with info_col:
            with st.container(key=f"{card_key}_clicktarget"):
                if st.button(f":material/center_focus_strong: {address}", key=f"{key_prefix}_{idx}", width="stretch",
                             help="Focus this property on the map"):
                    focus_clicked = True
            info_parts = [f"{row_item.get('beds', '-')} bd", f"{row_item.get('baths', '-')} ba"]
            sqft = row_item.get('sqft')
            if sqft:
                info_parts.append(f"{int(sqft):,} sqft")
            prop_type = row_item.get('property_type')
            if prop_type:
                info_parts.append(str(prop_type))
            hoa_summary = clean_value(row_item.get('hoa_monthly'))
            if hoa_summary:
                # A real, per-listing dollar cost from RentCast - shown
                # right in the summary line (not just inside the detail
                # dialog) since it directly affects whether this is
                # actually a good deal, same reasoning as beds/baths/sqft
                # being visible without a click.
                info_parts.append(f"HOA ${float(hoa_summary):,.0f}/mo")
            st.caption(" · ".join(info_parts))
            mls_number = row_item.get('mls_number')
            if mls_number:
                # Real, legitimately-licensed data straight from RentCast's
                # own response (not scraped) - safe to show as-is.
                mls_label = f"MLS# {mls_number}" + (f" · {row_item['mls_name']}" if row_item.get('mls_name') else "")
                st.caption(mls_label)
        with action_col:
            # user_id is None for a guest session - nothing is ever saved
            # for one, so it can't be "already saved" either.
            is_saved = db.is_property_saved(user_id, address) if user_id else False
            with st.container(key=f"{card_key}_favbtn"):
                fav_icon = "★" if is_saved else "☆"
                if guest_action_button(fav_icon, "save this property", key=f"{key_prefix}_fav_{idx}",
                                        help="Saved" if is_saved else "Save"):
                    if is_saved:
                        db.unsave_property(user_id, address)
                        st.rerun()
                    elif plan_limits.is_within_limit(st.session_state.user_role, st.session_state.user_plan,
                                                      "saved_properties", db.count_saved_properties(user_id)):
                        db.save_property(user_id, address, row_item['title'], row_item['price'],
                                          row_item.get('beds', 0), row_item.get('baths', 0),
                                          row_item.get('latitude'), row_item.get('longitude'))
                        st.rerun()
                    else:
                        st.toast(f"Your {st.session_state.user_plan} plan's saved-properties limit is reached.", icon=":material/lock:")
                        pricing.render_pricing_dialog()

        # Opens as a true modal layer on top of the page (native Streamlit
        # dialog), instead of expanding inline - closer to how Zillow's
        # click-through detail view behaves.
        if st.button(":material/search: View Full Details", key=f"{key_prefix}_viewdetails_{idx}", width="stretch"):
            st.session_state.property_dialog_ctx = {
                "row_item": row_item, "metrics": metrics, "address": address,
                "user_id": user_id, "reference_point": reference_point,
                "calc_target_yield": calc_target_yield, "current_assumptions": current_assumptions,
                "key_prefix": key_prefix, "idx": idx,
            }
            render_property_detail_dialog()

        if address:
            mls_number = row_item.get('mls_number')
            zillow_help = "Opens Zillow's own search for this address - not a guaranteed direct link, since we have no Zillow property ID for this listing (an MLS# alone isn't reliable either - it's only unique within its own MLS board, not nationally)"
            redfin_help = ("Searches Redfin (via Google) for this address plus its MLS# for a tighter match - not a guaranteed direct link, since we have no Redfin listing ID for this property"
                            if mls_number else
                            "Opens a Redfin-scoped search for this address - not a guaranteed direct link, since we have no MLS# for this property and no Redfin listing ID either")
            zillow_col, redfin_col = st.columns(2)
            with zillow_col:
                st.link_button(":material/open_in_new: Zillow", engine.build_zillow_search_url(address, mls_number), width="stretch",
                                help=zillow_help)
            with redfin_col:
                st.link_button(":material/open_in_new: Redfin", engine.build_redfin_search_url(address, mls_number), width="stretch",
                                help=redfin_help)

    return focus_clicked