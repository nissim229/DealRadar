"""
car_card.py
The used-car listing card for DealRadar's cars-category preview - mirrors
property_card.py's visual language (bordered card, price + deal badge up
top, key-stats caption line, outbound search links) but stays intentionally
simpler: no Street View photos, PDF export, or what-if calculator, since
none of those apply to a car and this renders mock data (see car_engine.py)
rather than a real listings feed yet.
"""

import streamlit as st
from underwriting import render_deal_badge
from icons import icon as svg_icon
from car_engine import build_autotrader_search_url, build_carsdotcom_search_url

_GRADE_ACCENT = {
    "excellent": "var(--radar-success)",
    "average": "var(--radar-warning)",
    "critical": "var(--radar-danger)",
}


def render_car_card(idx, listing, metrics, key_prefix):
    """One mock car listing rendered as a card."""
    card_key = f"{key_prefix}_car_card_{idx}"
    grade = metrics["grade"]
    accent = _GRADE_ACCENT[grade]

    with st.container(border=True, key=card_key):
        st.markdown(f"""
            <div style='position:relative; height:150px; border-radius:var(--radar-radius-md);
                        background: linear-gradient(135deg, #1e293b, #334155);
                        display:flex; align-items:center; justify-content:center; margin-bottom:10px;'>
                {svg_icon("car", size=56, color="#64748b")}
                <div style='position:absolute; top:10px; left:10px; background:rgba(15,23,42,0.75); color:white;
                            padding:4px 10px; border-radius:var(--radar-radius-pill); font-weight:700; font-size:15px;'>
                    ${listing['price']:,.0f}
                </div>
                <div style='position:absolute; top:10px; right:10px;'>
                    {render_deal_badge(grade)}
                </div>
            </div>
        """, unsafe_allow_html=True)

        st.markdown(f"**{listing['year']} {listing['make']} {listing['model']}**")
        st.caption(f"{listing['mileage']:,} mi · {listing['dealer_name']} · ZIP {listing['zip_code']}")

        pct = metrics["pct_below_market"]
        dollars = metrics["dollars_below_market"]
        if pct >= 0:
            comparison_html = f"${dollars:,.0f} ({pct:.0f}%) below estimated market value"
        else:
            comparison_html = f"${abs(dollars):,.0f} ({abs(pct):.0f}%) above estimated market value"
        st.markdown(f"<span style='color:{accent}; font-weight:700; font-size:13px;'>{comparison_html}</span>", unsafe_allow_html=True)
        st.caption(f"Estimated market value: ${listing['market_value']:,.0f}")

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
