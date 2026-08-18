"""
property_card.py
The property card component - photo, badge, price, and the tabbed detail
expander (Why This Grade / What-If Calculator / Photos / Notes & Neighborhood).
"""

import streamlit as st
import streamlit.components.v1 as components
import database as db
import agent_engine as engine
import pandas as pd
import plan_limits
from underwriting import GRADE_STYLES, render_deal_badge
from pdf_export import generate_single_property_pdf_link
from whatif_calculator import render_whatif_calculator_html
from photo_carousel import render_photo_carousel_html
from components import pricing
from icons import icon as svg_icon


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
        ("📊 Net Operating Income (NOI)", f"${metrics['noi']:,.0f}/yr", "Income minus taxes/insurance - your profit before the mortgage"),
        ("🏦 Mortgage payment", f"${metrics['a_debt']:,.0f}/yr", "What you pay the bank each year on the loan"),
        ("💰 Cash flow", f"${metrics['cashflow']:,.0f}/yr", "NOI minus mortgage payment - what's left in your pocket"),
        ("🎯 Cash-on-Cash Return (your ROI)", f"{metrics['coc']:.2f}%", "Cash flow ÷ your down payment - your real return on the cash you put in"),
    ]
    if grade == "excellent":
        rows.append(("✅ Vs. your target", f"+{margin:.2f} pts", f"Clears your {calc_target_yield:.2f}% target"))
    elif grade == "average":
        rows.append(("⚠️ Vs. your target", f"{margin:.2f} pts", f"Falls short of your {calc_target_yield:.2f}% target"))
    else:
        rows.append(("🛑 Vs. your target", "N/A", "Cash flow is negative - the mortgage costs more than the property brings in"))

    breakdown_df = pd.DataFrame(rows, columns=["Metric", "Value", "What it means"])
    st.dataframe(breakdown_df, hide_index=True, use_container_width=True, height=len(breakdown_df) * 35 + 38)

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
                st.link_button(":material/open_in_new: Search Zillow", engine.build_zillow_search_url(address, mls_number), use_container_width=True)
            with redfin_col:
                st.link_button(":material/open_in_new: Search Redfin", engine.build_redfin_search_url(address, mls_number), use_container_width=True)

    def _render_notes():
        existing_notes = db.get_property_notes(user_id, address)
        note_text = st.text_area("Personal notes", value=existing_notes, key=f"{key_prefix}_notes_{idx}",
                                  placeholder="e.g., Call agent Tuesday, check roof condition...")
        note_col1, note_col2 = st.columns([1, 3])
        with note_col1:
            if st.button("Save Note", key=f"{key_prefix}_save_note_{idx}", type="primary", disabled=note_text == existing_notes):
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
        st.markdown(f"""
            <a href="{pdf_uri}" download="DealRadar_{row_item['title'].replace(' ', '_')}.html" style="text-decoration: none;">
                <div style="background-color: var(--radar-neutral); color: white; text-align: center; padding: 8px; border-radius: var(--radar-radius-sm); font-weight: 500; cursor: pointer; font-size: 13px; display:flex; align-items:center; justify-content:center; gap:6px;">
                    {svg_icon("download", size=14, color="white")} Export This Property to PDF / Print
                </div>
            </a>
        """, unsafe_allow_html=True)

    tab_defs = [
        ("why", ":material/menu_book: Why This Grade", _render_why),
        ("whatif", ":material/tune: What-If Calculator", _render_whatif),
        ("photos", ":material/photo_camera: Photos", _render_photos),
        ("notes", ":material/edit_note: Notes & Neighborhood", _render_notes),
    ]
    if open_tab == "photos":
        tab_defs.sort(key=lambda t: t[0] != "photos")

    rendered_tabs = st.tabs([label for _, label, _ in tab_defs])
    for tab_widget, (_, _, render_fn) in zip(rendered_tabs, tab_defs):
        with tab_widget:
            render_fn()


@st.dialog("Property Details", width="large")
def _property_detail_dialog():
    """Native Streamlit modal - opens as a true overlay layer on top of the
    page (with its own close button and background dim), rather than
    expanding inline. Reads whichever property was last clicked from
    session_state, since st.dialog's title/decoration is fixed at import
    time and can't take per-call arguments directly."""
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
                          calc_target_yield=8.0, current_assumptions=None):
    """One property rendered as a photo-forward visual card. Returns True if
    this card was clicked this run (used by the caller to toggle focus on/off)."""
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
            carousel_html = render_photo_carousel_html(gallery_urls, f"${row_item['price']:,.0f}", render_deal_badge(metrics["grade"]))
            components.html(carousel_html, height=250)

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
                        _property_detail_dialog()

        info_col, action_col = st.columns([4, 1])
        with info_col:
            with st.container(key=f"{card_key}_clicktarget"):
                if st.button(address, key=f"{key_prefix}_{idx}", use_container_width=True,
                             help="Click to focus this property on the map"):
                    focus_clicked = True
            info_parts = [f"{row_item.get('beds', '-')} bd", f"{row_item.get('baths', '-')} ba"]
            sqft = row_item.get('sqft')
            if sqft:
                info_parts.append(f"{int(sqft):,} sqft")
            prop_type = row_item.get('property_type')
            if prop_type:
                info_parts.append(str(prop_type))
            st.caption(" · ".join(info_parts))
            mls_number = row_item.get('mls_number')
            if mls_number:
                # Real, legitimately-licensed data straight from RentCast's
                # own response (not scraped) - safe to show as-is.
                mls_label = f"MLS# {mls_number}" + (f" · {row_item['mls_name']}" if row_item.get('mls_name') else "")
                st.caption(mls_label)
        with action_col:
            is_saved = db.is_property_saved(user_id, address)
            with st.container(key=f"{card_key}_favbtn"):
                fav_icon = "★" if is_saved else "☆"
                if st.button(fav_icon, key=f"{key_prefix}_fav_{idx}", help="Saved" if is_saved else "Save"):
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
        if st.button(":material/search: View Full Details", key=f"{key_prefix}_viewdetails_{idx}", use_container_width=True):
            st.session_state.property_dialog_ctx = {
                "row_item": row_item, "metrics": metrics, "address": address,
                "user_id": user_id, "reference_point": reference_point,
                "calc_target_yield": calc_target_yield, "current_assumptions": current_assumptions,
                "key_prefix": key_prefix, "idx": idx,
            }
            _property_detail_dialog()

        if address:
            mls_number = row_item.get('mls_number')
            zillow_help = "Opens Zillow's own search for this address - not a guaranteed direct link, since we have no Zillow property ID for this listing (an MLS# alone isn't reliable either - it's only unique within its own MLS board, not nationally)"
            redfin_help = ("Searches Redfin (via Google) for this address plus its MLS# for a tighter match - not a guaranteed direct link, since we have no Redfin listing ID for this property"
                            if mls_number else
                            "Opens a Redfin-scoped search for this address - not a guaranteed direct link, since we have no MLS# for this property and no Redfin listing ID either")
            zillow_col, redfin_col = st.columns(2)
            with zillow_col:
                st.link_button("Search Zillow", engine.build_zillow_search_url(address, mls_number), use_container_width=True,
                                help=zillow_help)
            with redfin_col:
                st.link_button("Search Redfin", engine.build_redfin_search_url(address, mls_number), use_container_width=True,
                                help=redfin_help)

    return focus_clicked