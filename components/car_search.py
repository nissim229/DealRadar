"""
car_search.py
The redesigned Cars-category flow: search runs immediately on one page, no
saved profile required first - replaces the old two-step Manage Car Search
Criteria -> Run Car Scans pattern for cars only (real estate's own flow in
analytics.py/strategy_config.py is untouched). "Save this search" is an
optional, secondary action offered next to the results, for the minority
of users who want to revisit or re-run one - see render_saved_car_searches_page.

Real data comes from car_engine.fetch_live_car_listings (Auto.dev) when
configured and quota allows; car_engine.generate_mock_car_listings is the
offline/test-scan fallback, exactly mirroring how the real-estate side
falls back to its own local simulator.
"""

import streamlit as st
import database as db
import roles
import car_engine
from components.car_card import render_car_card
from icons import icon as svg_icon


def _inject_css():
    st.markdown("""
        <style>
        div.st-key-car_search_hero {
            background: var(--radar-gradient-hero);
            padding: var(--radar-space-6) var(--radar-space-7) 56px var(--radar-space-7);
            margin-bottom: -36px;
            border-radius: 0 0 var(--radar-radius-xl) var(--radar-radius-xl);
        }
        div.st-key-car_search_action_card {
            background: var(--radar-surface);
            border-radius: var(--radar-radius-lg);
            padding: var(--radar-space-5) var(--radar-space-5);
            box-shadow: var(--radar-shadow-lg);
        }
        div.st-key-car_search_action_card button[kind="primary"] {
            background-color: var(--radar-primary) !important;
            font-weight: 700 !important;
        }
        div.st-key-car_search_save_popover [data-testid="stPopoverButton"] {
            border: 1.5px solid var(--radar-primary) !important;
            color: var(--radar-primary) !important;
            border-radius: var(--radar-radius-pill) !important;
            font-weight: 700 !important;
        }
        </style>
    """, unsafe_allow_html=True)


def _render_hero():
    with st.container(key="car_search_hero"):
        st.markdown(f"""
            <div style='text-align:center; max-width:760px; margin:0 auto;'>
                <div style='display:flex; align-items:center; justify-content:center; gap:14px; margin-bottom:10px;'>
                    <div style='background: var(--radar-gradient-brand); width: 48px; height: 48px;
                                border-radius: var(--radar-radius-md); display:flex; align-items:center; justify-content:center; flex-shrink:0;'>
                        {svg_icon("car", size=24, color="white")}
                    </div>
                    <div style='font-family:var(--radar-font-display); font-size:32px; font-weight:800; color:white; line-height:1.2;'>Find a Used Car</div>
                </div>
                <div style='font-size:16px; color:var(--radar-text-on-dark-muted);'>
                    Search live inventory across dealers - no saved profile required. Just tell us what you're looking for.
                </div>
            </div>
        """, unsafe_allow_html=True)


def _run_search(make, model, min_year, max_price, max_mileage, zip_code, radius, use_live):
    listings = None
    if use_live:
        listings = car_engine.fetch_live_car_listings(
            make=None if make == "Any make" else make,
            model=None if model == "Any model" else model,
            min_year=min_year, max_price=max_price, max_mileage=max_mileage,
            zip_code=zip_code or None, radius=radius, user_id=st.session_state.user_id,
        )
    if listings is None:
        listings = car_engine.generate_mock_car_listings(
            make=None if make == "Any make" else make,
            model=None if model == "Any model" else model,
            min_year=min_year, max_price=max_price, max_mileage=max_mileage,
            zip_code=zip_code, count=9,
        )
        was_live = False
    else:
        was_live = True

    st.session_state.car_search_results = listings
    st.session_state.car_search_was_live = was_live
    st.session_state.car_search_criteria_label = _criteria_label(make, model, min_year, max_price, zip_code, radius)


def _criteria_label(make, model, min_year, max_price, zip_code, radius):
    bits = []
    make_model = " ".join(p for p in [None if make == "Any make" else make, None if model == "Any model" else model] if p)
    if make_model:
        bits.append(f"{min_year}+ {make_model}")
    elif min_year:
        bits.append(f"{min_year}+")
    if max_price:
        bits.append(f"under ${max_price:,.0f}")
    if zip_code:
        bits.append(f"within {radius} mi of {zip_code}")
    return " · ".join(bits) if bits else "All listings"


def render_car_search_page():
    _inject_css()
    _render_hero()

    # Make -> Model dependent dropdown deliberately lives outside any
    # st.form() - a form only reruns on submit, so a dependent selectbox
    # inside one would keep showing the *previous* Make's model options
    # after picking a new Make (see [[cars-category-feature]]).
    with st.container(key="car_search_action_card"):
        row1 = st.columns(4)
        with row1[0]:
            make = st.selectbox("Make", ["Any make"] + car_engine.CAR_MAKES, key="car_search_make")
        with row1[1]:
            model_options = ["Any model"] + (car_engine.models_for_make(make) if make != "Any make" else [])
            if st.session_state.get("car_search_model") not in model_options:
                st.session_state.car_search_model = "Any model"
            model = st.selectbox("Model", model_options, key="car_search_model")
        with row1[2]:
            min_year = st.number_input("Year (min)", min_value=1990, max_value=2026, value=st.session_state.get("car_search_min_year", 2018), step=1, key="car_search_min_year")
        with row1[3]:
            max_price = st.number_input("Max price ($)", min_value=1000, value=st.session_state.get("car_search_max_price", 30000), step=1000, key="car_search_max_price")

        row2 = st.columns(4)
        with row2[0]:
            max_mileage = st.number_input("Max mileage", min_value=0, value=st.session_state.get("car_search_max_mileage", 80000), step=5000, key="car_search_max_mileage")
        with row2[1]:
            zip_code = st.text_input("ZIP code", value=st.session_state.get("car_search_zip", ""), placeholder="e.g., 60614", key="car_search_zip")
        with row2[2]:
            radius = st.selectbox("Radius (mi)", [25, 50, 100, 250], index=[25, 50, 100, 250].index(st.session_state.get("car_search_radius", 50)), key="car_search_radius")
        with row2[3]:
            st.markdown("<div style='margin-top:28px;'></div>", unsafe_allow_html=True)
            search_clicked = st.button(":material/travel_explore: Search", type="primary", use_container_width=True, key="car_search_btn")

        test_clicked = False
        if roles.is_staff(st.session_state.user_role):
            test_clicked = st.button(":material/science: Search with sample data", key="car_search_test_btn",
                                      help="Uses mock/sample data - doesn't spend real Auto.dev quota.")

    if search_clicked or test_clicked:
        with st.spinner("Searching live inventory..." if not test_clicked else "Generating sample results..."):
            _run_search(make, model, min_year, max_price, max_mileage, zip_code.strip(), radius, use_live=not test_clicked)
        st.rerun()

    results = st.session_state.get("car_search_results")
    if results is None:
        return

    st.markdown("<div style='height:32px;'></div>", unsafe_allow_html=True)

    if not results:
        st.info("No matches for these criteria - try widening the price, mileage, or radius.", icon=":material/search_off:")
        return

    if not st.session_state.get("car_search_was_live", True):
        st.info(
            ":material/science: **Preview data** - Auto.dev isn't configured, quota is exhausted, or you used sample data on purpose. "
            "Deal grading compares each listing's price to an estimated market value based on comparable listings.",
        )

    header_col1, header_col2 = st.columns([3, 2])
    with header_col1:
        st.markdown(f"<div style='font-family:var(--radar-font-display); font-size:18px; font-weight:700;'>{len(results)} matches</div>", unsafe_allow_html=True)
        st.caption(st.session_state.get("car_search_criteria_label", ""))
    with header_col2:
        save_col, _ = st.columns([1, 1])
        with save_col:
            with st.container(key="car_search_save_popover"):
                with st.popover(":material/bookmark: Save this search", use_container_width=True):
                    st.caption("Get notified by email when a new match like these appears.")
                    save_name = st.text_input("Name this search", key="car_search_save_name", placeholder="e.g., Family SUV under $30k")
                    if st.button(":material/save: Save", key="car_search_save_confirm_btn", type="primary", use_container_width=True):
                        if save_name.strip():
                            db.save_report_config(
                                st.session_state.user_id, save_name.strip(), zip_code or "Nationwide",
                                int(max_price), 0, None, st.session_state.user_email, "08:00",
                                zip_code=zip_code or None, category="cars",
                                car_make=None if make == "Any make" else make,
                                car_model=None if model == "Any model" else model,
                                car_min_year=int(min_year), car_max_mileage=int(max_mileage),
                            )
                            st.toast(f"Saved '{save_name.strip()}'")
                        else:
                            st.error("Give this search a name first.")

    best = max(results, key=lambda c: car_engine.compute_car_deal_metrics(c["price"], c["market_value"])["pct_below_market"])
    best_metrics = car_engine.compute_car_deal_metrics(best["price"], best["market_value"])
    if best_metrics["pct_below_market"] > 0:
        st.markdown(f"""
            <div style='background:var(--radar-success-bg); border:1px solid var(--radar-success-border); border-radius:var(--radar-radius-md); padding:12px 16px; margin:12px 0 16px 0; display:flex; align-items:center; gap:8px;'>
                <span style='color:#065f46;'>{svg_icon("trophy", size=16, color="#065f46")}</span>
                <span style='font-weight:700; color:#065f46;'>Best deal in this search:</span>
                <span style='color:#065f46;'>{best_metrics['pct_below_market']:.0f}% below market on the {best['year']} {best['make']} {best['model']}</span>
            </div>
        """, unsafe_allow_html=True)

    for row_start in range(0, len(results), 3):
        row = results[row_start:row_start + 3]
        cols = st.columns(3)
        for slot, listing in enumerate(row):
            metrics = car_engine.compute_car_deal_metrics(listing["price"], listing["market_value"])
            with cols[slot]:
                render_car_card(row_start + slot, listing, metrics, "car_search")


def render_saved_car_searches_page():
    with st.container(key="car_search_hero"):
        st.markdown(f"""
            <div style='text-align:center; max-width:760px; margin:0 auto;'>
                <div style='display:flex; align-items:center; justify-content:center; gap:14px; margin-bottom:10px;'>
                    <div style='background: var(--radar-gradient-brand); width: 48px; height: 48px;
                                border-radius: var(--radar-radius-md); display:flex; align-items:center; justify-content:center; flex-shrink:0;'>
                        {svg_icon("crosshair", size=24, color="white")}
                    </div>
                    <div style='font-family:var(--radar-font-display); font-size:32px; font-weight:800; color:white; line-height:1.2;'>Saved Searches</div>
                </div>
                <div style='font-size:16px; color:var(--radar-text-on-dark-muted);'>
                    Searches you've bookmarked from Find a Car - re-run one anytime.
                </div>
            </div>
        """, unsafe_allow_html=True)
    _inject_css()

    import sqlite3
    conn = sqlite3.connect(db.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT profile_name, max_price, zip_code, car_make, car_model, car_min_year, car_max_mileage "
            "FROM reports WHERE user_id=? AND category='cars' ORDER BY profile_name",
            (int(st.session_state.user_id),),
        )
        rows = cursor.fetchall()
    finally:
        conn.close()

    st.markdown("<div style='height:24px;'></div>", unsafe_allow_html=True)

    if not rows:
        st.info("No saved searches yet - run a search on Find a Car and use \"Save this search\" to bookmark one.", icon=":material/bookmark_border:")
        return

    for name, max_price, zip_code, car_make, car_model, min_year, max_mileage in rows:
        with st.container(border=True):
            label_col, run_col, delete_col = st.columns([4, 1, 1])
            with label_col:
                st.markdown(f"**{name}**")
                st.caption(_criteria_label(car_make or "Any make", car_model or "Any model", min_year, max_price, zip_code, 50))
            with run_col:
                if st.button(":material/travel_explore: Run", key=f"saved_car_run_{name}", use_container_width=True):
                    st.session_state.car_search_make = car_make or "Any make"
                    st.session_state.car_search_model = car_model or "Any model"
                    st.session_state.car_search_min_year = min_year or 2018
                    st.session_state.car_search_max_price = max_price or 30000
                    st.session_state.car_search_max_mileage = max_mileage or 80000
                    st.session_state.car_search_zip = zip_code or ""
                    st.session_state.car_search_radius = 50
                    _run_search(car_make or "Any make", car_model or "Any model", min_year or 2018,
                                max_price or 30000, max_mileage or 80000, zip_code or "", 50, use_live=True)
                    st.session_state.current_page = "Find a Car"
                    st.rerun()
            with delete_col:
                if st.button(":material/delete: Delete", key=f"saved_car_delete_{name}", use_container_width=True):
                    db.delete_report_config(st.session_state.user_id, name)
                    st.rerun()
