"""
car_card.py
The used-car listing card for DealRadar's cars-category preview - mirrors
property_card.py's visual language (bordered card, price + deal badge up
top, key-stats caption line, outbound links). Renders either a real
Auto.dev listing (car_engine.fetch_live_car_listings - has a real photo,
a direct dealer listing_url, and Carfax/history fields) or a mock one
(car_engine.generate_mock_car_listings - none of those, is_mock=True) with
the same layout, falling back to a placeholder icon and site-scoped Google
search links wherever a real listing's own fields aren't present.
"""

import streamlit as st
from icons import icon as svg_icon
from car_engine import build_autotrader_search_url, build_carsdotcom_search_url, render_car_deal_badge

_GRADE_ACCENT = {
    "excellent": "var(--radar-success)",
    "average": "var(--radar-warning)",
    "critical": "var(--radar-danger)",
}


def render_car_card(idx, listing, key_prefix):
    """One car listing (real or mock) rendered as a card. Grade, market
    value, and grade_adjustments are precomputed on the listing itself by
    car_engine.py (compute_car_deal_metrics for mock, _grade_real_listings
    for real) rather than passed in separately, so every listing dict -
    whichever source it came from - already carries the same fields."""
    card_key = f"{key_prefix}_car_card_{idx}"
    has_reliable_grade = listing.get("has_reliable_grade", True)
    grade = listing.get("grade")
    photo_url = listing.get("primary_image")

    with st.container(border=True, key=card_key):
        if photo_url:
            # Double quotes around the URL, not single - the outer <div
            # style='...'> tag is itself single-quoted, so a single-quoted
            # url('...') here would prematurely close that attribute at the
            # URL's own opening quote, silently truncating the style and
            # dropping the photo entirely (confirmed live: every real
            # listing's card rendered background-image: url("") with the
            # URL missing, even though listing["primary_image"] was set).
            photo_html = f"""background-image:url("{photo_url}"); background-size:cover; background-position:center;"""
            icon_html = ""
        else:
            photo_html = "background: linear-gradient(135deg, #1e293b, #334155);"
            icon_html = svg_icon("car", size=56, color="#64748b")
        # No badge at all when there's not enough data to grade confidently
        # - a neutral "Not enough data" chip, not a colored grade badge
        # that would look like a real assessment happened. See
        # [[feedback_honest_deal_grading]].
        badge_html = render_car_deal_badge(grade) if has_reliable_grade else (
            "<span style='background-color:#f1f5f9; color:#64748b; padding:6px 12px; "
            "border-radius:6px; font-weight:700; font-size:12px; border:1px solid #e2e8f0; "
            "white-space:nowrap;'>Not enough data to grade</span>"
        )
        st.markdown(f"""
            <div style='position:relative; height:150px; border-radius:var(--radar-radius-md);
                        {photo_html}
                        display:flex; align-items:center; justify-content:center; margin-bottom:10px;'>{icon_html}
                <div style='position:absolute; top:10px; left:10px; background:rgba(15,23,42,0.75); color:white;
                            padding:4px 10px; border-radius:var(--radar-radius-pill); font-weight:700; font-size:15px;'>
                    ${listing['price']:,.0f}
                </div>
                <div style='position:absolute; top:10px; right:10px;'>
                    {badge_html}
                </div>
            </div>
        """, unsafe_allow_html=True)

        trim = f" {listing['trim']}" if listing.get("trim") else ""
        st.markdown(f"**{listing['year']} {listing['make']} {listing['model']}{trim}**")
        location_bit = f"{listing['city']}, {listing['state']}" if listing.get("city") else f"ZIP {listing['zip_code']}"
        st.caption(f"{listing['mileage']:,} mi · {listing['dealer_name']} · {location_bit}")

        if has_reliable_grade:
            accent = _GRADE_ACCENT[grade]
            pct = listing["pct_below_market"]
            dollars = listing["dollars_below_market"]
            if pct >= 0:
                comparison_html = f"${dollars:,.0f} ({pct:.0f}%) below estimated market value"
            else:
                comparison_html = f"${abs(dollars):,.0f} ({abs(pct):.0f}%) above estimated market value"
            st.markdown(f"<span style='color:{accent}; font-weight:700; font-size:13px;'>{comparison_html}</span>", unsafe_allow_html=True)
            st.caption(f"Estimated market value: ${listing['market_value']:,.0f} (based on comparable listings)")
            if listing.get("grade_adjustments"):
                st.caption("Grade adjusted for: " + ", ".join(listing["grade_adjustments"]))
        else:
            st.caption("No other similar listings in this search to compare price against - shown for reference, not graded.")

        # Real vehicle history (Carfax-backed) is worth surfacing right on
        # the card, not buried behind a click - it's exactly the "is this
        # actually a good deal" context a plain Google search doesn't
        # surface inline. None of these fields exist on a mock listing.
        if listing.get("accident_count") is not None or listing.get("one_owner") is not None:
            history_bits = []
            if listing.get("accident_count") == 0:
                history_bits.append("No reported accidents")
            elif listing.get("accident_count"):
                n = listing["accident_count"]
                history_bits.append(f"{n} reported accident{'s' if n != 1 else ''}")
            if listing.get("one_owner"):
                history_bits.append("1 owner")
            elif listing.get("owner_count"):
                history_bits.append(f"{listing['owner_count']} owners")
            if listing.get("cpo"):
                history_bits.append("Certified Pre-Owned")
            if history_bits:
                st.caption(" · ".join(history_bits))

        if listing.get("listing_url"):
            st.link_button(":material/open_in_new: View Listing", listing["listing_url"], use_container_width=True)
            if listing.get("carfax_url"):
                st.link_button(":material/fact_check: Carfax Report", listing["carfax_url"], use_container_width=True)
        else:
            link_col1, link_col2 = st.columns(2)
            with link_col1:
                st.link_button(
                    ":material/open_in_new: AutoTrader",
                    build_autotrader_search_url(listing["year"], listing["make"], listing["model"]),
                    use_container_width=True,
                )
            with link_col2:
                st.link_button(
                    ":material/open_in_new: Cars.com",
                    build_carsdotcom_search_url(listing["year"], listing["make"], listing["model"]),
                    use_container_width=True,
                )
