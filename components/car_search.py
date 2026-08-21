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
import pandas as pd
import database as db
import roles
import car_engine
from components.car_card import render_car_card
from icons import icon as svg_icon
from scan_loading import render_scan_loading_radar
from guest_mode import guest_action_button, render_guest_banner


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


def _render_hero_title(title, subtitle, icon_name="car"):
    """Just the title/icon/subtitle markup - deliberately doesn't wrap its
    own st.container(key="car_search_hero"), unlike the old _render_hero,
    so the caller can nest the action card (and, on the search page, the
    scan-loading radar) *inside* the same dark hero block - matching how
    analytics.py's dashboard_hero wraps its action card + stat cards, so
    the two categories look structurally identical to a customer instead
    of Cars' search form floating in the light page body below a
    separate, shorter hero. See [[brand-design-admin-panel]]/
    [[cyber-radar-button-and-loading]] for why this consistency matters."""
    st.markdown(f"""
        <div style='text-align:center; max-width:760px; margin:0 auto;'>
            <div style='display:flex; align-items:center; justify-content:center; gap:14px; margin-bottom:10px;'>
                <div style='background: var(--radar-gradient-brand); width: 48px; height: 48px;
                            border-radius: var(--radar-radius-md); display:flex; align-items:center; justify-content:center; flex-shrink:0;'>
                    {svg_icon(icon_name, size=24, color="white")}
                </div>
                <div style='font-family:var(--radar-font-display); font-size:32px; font-weight:800; color:white; line-height:1.2;'>{title}</div>
            </div>
            <div style='font-size:16px; color:var(--radar-text-on-dark-muted);'>
                {subtitle}
            </div>
        </div>
    """, unsafe_allow_html=True)


def _run_search(make, model, trim, min_year, max_price, max_mileage, zip_code, radius, use_live):
    listings = None
    if use_live:
        listings = car_engine.fetch_live_car_listings(
            make=None if make == "Any make" else make,
            model=None if model == "Any model" else model,
            trim=None if trim == "Any trim" else trim,
            min_year=min_year, max_price=max_price, max_mileage=max_mileage,
            zip_code=zip_code or None, radius=radius, user_id=st.session_state.user_id,
        )
    if listings is None:
        listings = car_engine.generate_mock_car_listings(
            make=None if make == "Any make" else make,
            model=None if model == "Any model" else model,
            trim=None if trim == "Any trim" else trim,
            min_year=min_year, max_price=max_price, max_mileage=max_mileage,
            zip_code=zip_code, count=9,
        )
        was_live = False
    else:
        was_live = True

    st.session_state.car_search_results = listings
    st.session_state.car_search_was_live = was_live
    criteria_label = _criteria_label(make, model, trim, min_year, max_price, zip_code, radius)
    st.session_state.car_search_criteria_label = criteria_label

    if st.session_state.get("is_guest"):
        return

    # Lightweight log row (no report_content/coordinates_json - this page
    # doesn't build a saved report the way real-estate scans do) purely so
    # the topbar notification bell has real recent-activity data for Cars,
    # not just real estate. Same table/function real-estate scans use,
    # tagged category="cars" - see save_history_log's docstring.
    db.save_history_log(st.session_state.user_id, "Car Search", criteria_label, "", was_live=was_live, category="cars")


def _criteria_label(make, model, trim, min_year, max_price, zip_code, radius):
    # zip_code (and in principle min_year/max_price too) can arrive as
    # NaN from a pandas-read DB column with nulls in it, not just a plain
    # None - `if zip_code:` alone doesn't catch that, since NaN is truthy
    # in Python. Confirmed live: rows saved without a ZIP rendered "within
    # 50 mi of nan" until this normalized it away first.
    zip_code = zip_code if isinstance(zip_code, str) else None
    bits = []
    make_model = " ".join(p for p in [None if make == "Any make" else make, None if model == "Any model" else model] if p)
    if make_model:
        bits.append(f"{min_year}+ {make_model}")
    elif min_year:
        bits.append(f"{min_year}+")
    if trim and trim != "Any trim":
        bits.append(f"{trim} trim")
    if max_price:
        bits.append(f"under ${max_price:,.0f}")
    if zip_code:
        bits.append(f"within {radius} mi of {zip_code}")
    return " · ".join(bits) if bits else "All listings"


def render_car_search_page(is_guest=False):
    _inject_css()
    if is_guest:
        render_guest_banner("live results are sample listings, not real Auto.dev inventory")

    # The action card and the scan-loading radar are nested *inside* this
    # same dark hero container, not separate blocks in the light page body
    # below a short hero - matching analytics.py's dashboard_hero, which
    # wraps its action card + stat cards the same way. Cars used to be its
    # own shorter hero with the white search card merely overlapping its
    # bottom edge (a negative margin trick, not real nesting), which made
    # the category look structurally different from Properties - a real
    # inconsistency the user caught and asked to have unified so customers
    # don't get a different mental model per category.
    with st.container(key="car_search_hero"):
        _render_hero_title(
            "Find a Used Car",
            "Search live inventory across dealers - no saved profile required. Just tell us what you're looking for.",
            icon_name="car",
        )

        # Make -> Model dependent dropdown deliberately lives outside any
        # st.form() - a form only reruns on submit, so a dependent selectbox
        # inside one would keep showing the *previous* Make's model options
        # after picking a new Make (see [[cars-category-feature]]).
        with st.container(key="car_search_action_card"):
            row1 = st.columns(5)
            with row1[0]:
                make = st.selectbox("Make", ["Any make"] + car_engine.get_available_makes(user_id=st.session_state.user_id), key="car_search_make")
            with row1[1]:
                model_options = ["Any model"] + (car_engine.get_available_models(make, user_id=st.session_state.user_id) if make != "Any make" else [])
                if st.session_state.get("car_search_model") not in model_options:
                    st.session_state.car_search_model = "Any model"
                model = st.selectbox("Model", model_options, key="car_search_model")
            with row1[2]:
                # Trim depends on BOTH Make and Model (Auto.dev's live facets
                # only return real trims once a specific model is picked -
                # see car_engine.get_available_trims) - same "outside any
                # st.form()" requirement as Model depending on Make, for the
                # same reason: a form only reruns on submit, so a dependent
                # selectbox inside one would keep showing the *previous*
                # pick's options for one extra click.
                trim_options = ["Any trim"] + (car_engine.get_available_trims(make, model, user_id=st.session_state.user_id) if model != "Any model" else [])
                if st.session_state.get("car_search_trim") not in trim_options:
                    st.session_state.car_search_trim = "Any trim"
                trim = st.selectbox("Trim", trim_options, key="car_search_trim",
                                     help="Populated from real current inventory once a specific Make and Model are picked." if model != "Any model" else "Pick a specific Make and Model first.")
            with row1[3]:
                min_year = st.number_input("Year (min)", min_value=1990, max_value=2026, value=st.session_state.get("car_search_min_year", 2018), step=1, key="car_search_min_year")
            with row1[4]:
                max_price = st.number_input("Max price ($)", min_value=1000, value=st.session_state.get("car_search_max_price", 30000), step=1000, key="car_search_max_price")

            row2 = st.columns(4)
            with row2[0]:
                max_mileage = st.number_input("Max mileage", min_value=0, value=st.session_state.get("car_search_max_mileage", 80000), step=5000, key="car_search_max_mileage")
            with row2[1]:
                zip_code = st.text_input("ZIP code", value=st.session_state.get("car_search_zip", ""), placeholder="e.g., 60614", key="car_search_zip")
            with row2[2]:
                radius_options = [10, 25, 50, 75, 100, 150, 250]
                radius = st.selectbox("Radius of ZIP (mi)", radius_options,
                                       index=radius_options.index(st.session_state.get("car_search_radius", 50)) if st.session_state.get("car_search_radius", 50) in radius_options else 2,
                                       key="car_search_radius", help="Only applies when a ZIP code is set above - results are limited to within this distance of it.")
            with row2[3]:
                st.markdown("<div style='margin-top:28px;'></div>", unsafe_allow_html=True)
                search_clicked = st.button(":material/travel_explore: Search", type="primary", use_container_width=True, key="car_search_btn")

            test_clicked = False
            if roles.is_staff(st.session_state.user_role):
                test_clicked = st.button(":material/science: Search with sample data", key="car_search_test_btn",
                                          help="Uses mock/sample data - doesn't spend real Auto.dev quota.")

        if search_clicked or test_clicked:
            # Same big radar-scope loading state as real estate's Run Live
            # Scan (see scan_loading.py) - a car icon instead of a house, but
            # otherwise identical mechanic/colors. try/finally so the
            # placeholder still clears if _run_search raises, matching what
            # st.spinner used to guarantee for free.
            loading_placeholder = st.empty()
            with loading_placeholder.container():
                render_scan_loading_radar("cars")
            try:
                _run_search(make, model, trim, min_year, max_price, max_mileage, zip_code.strip(), radius,
                             use_live=(not test_clicked) and not is_guest)
            finally:
                loading_placeholder.empty()
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
                    if guest_action_button(":material/save: Save", "save this search", key="car_search_save_confirm_btn",
                                            type="primary", use_container_width=True):
                        if save_name.strip():
                            db.save_report_config(
                                st.session_state.user_id, save_name.strip(), zip_code or "Nationwide",
                                int(max_price), 0, None, st.session_state.user_email, "08:00",
                                zip_code=zip_code or None, category="cars",
                                car_make=None if make == "Any make" else make,
                                car_model=None if model == "Any model" else model,
                                car_min_year=int(min_year), car_max_mileage=int(max_mileage),
                                car_trim=None if trim == "Any trim" else trim,
                            )
                            st.toast(f"Saved '{save_name.strip()}'")
                        else:
                            st.error("Give this search a name first.")

    # Only a listing with has_reliable_grade=True (a real comp group behind
    # it, not a broken/thin one) is eligible to be called "the best deal" -
    # never force a highlight onto the least-bad option just to have one.
    # See [[feedback_honest_deal_grading]]: the user's own framing was "I
    # dont want to lie to my customer" - a search with nothing confidently
    # good in it should say so, not manufacture a banner.
    gradeable = [c for c in results if c.get("has_reliable_grade") and c["pct_below_market"] > 0]
    if gradeable:
        best = max(gradeable, key=lambda c: c["pct_below_market"])
        st.markdown(f"""
            <div style='background:var(--radar-success-bg); border:1px solid var(--radar-success-border); border-radius:var(--radar-radius-md); padding:12px 16px; margin:12px 0 16px 0; display:flex; align-items:center; gap:8px;'>
                <span style='color:#065f46;'>{svg_icon("trophy", size=16, color="#065f46")}</span>
                <span style='font-weight:700; color:#065f46;'>Best deal in this search:</span>
                <span style='color:#065f46;'>{best['pct_below_market']:.0f}% below market on the {best['year']} {best['make']} {best['model']}</span>
            </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown(f"""
            <div style='background:var(--radar-surface-alt); border:1px solid var(--radar-border); border-radius:var(--radar-radius-md); padding:12px 16px; margin:12px 0 16px 0; display:flex; align-items:center; gap:8px;'>
                <span style='color:var(--radar-text-muted);'>{svg_icon("crosshair", size=16, color="var(--radar-text-muted)")}</span>
                <span style='color:var(--radar-text-muted);'>No confidently-graded deals in this search right now - save it to get notified if one shows up.</span>
            </div>
        """, unsafe_allow_html=True)

    for row_start in range(0, len(results), 3):
        row = results[row_start:row_start + 3]
        cols = st.columns(3)
        for slot, listing in enumerate(row):
            with cols[slot]:
                render_car_card(row_start + slot, listing, "car_search")


def _clear_car_saved_delete_target():
    st.session_state.car_saved_delete_target = None


@st.dialog("Delete Search", on_dismiss=_clear_car_saved_delete_target)
def _delete_saved_car_search_dialog():
    """Same floating-dialog shape as strategy_config.py's
    _delete_search_dialog (see [[table_action_pattern]]) - no edit dialog
    needed alongside it here, since a saved car search has nothing to
    edit in place (the whole point of this flow is search-then-optionally-
    save, not maintain a profile - see this module's own docstring).
    on_dismiss clears the target on every dismissal path, not just
    Cancel - see [[table_action_pattern]]."""
    ctx = st.session_state.get("car_saved_delete_target")
    if not ctx:
        st.write("No search selected.")
        return

    st.warning(f"Delete **{ctx['name']}**? This can't be undone.")
    confirm_col, cancel_col = st.columns(2)
    with confirm_col:
        if st.button(":material/delete_forever: Confirm Delete", type="primary", use_container_width=True):
            db.delete_report_config(st.session_state.user_id, ctx["name"])
            st.session_state.car_saved_delete_target = None
            st.toast("Search deleted.")
            st.rerun()
    with cancel_col:
        if st.button("Cancel", use_container_width=True):
            st.session_state.car_saved_delete_target = None
            st.rerun()


def render_saved_car_searches_page(is_guest=False):
    with st.container(key="car_search_hero"):
        _render_hero_title(
            "Saved Searches",
            "Searches you've bookmarked from Find a Car - re-run one anytime.",
            icon_name="crosshair",
        )
    _inject_css()

    if is_guest:
        render_guest_banner("searches aren't saved in a demo session")
        st.info("Sign in to bookmark a search from Find a Car and get notified when new matches appear.", icon=":material/bookmark_border:")
        return

    import sqlite3
    conn = sqlite3.connect(db.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT profile_name, max_price, zip_code, car_make, car_model, car_min_year, car_max_mileage, car_trim "
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

    df = pd.DataFrame(rows, columns=["Profile Name", "Max Price", "ZIP", "Make", "Model", "Min Year", "Max Mileage", "Trim"])
    # `mk or "Any make"` looks right but isn't: a NULL car_make column
    # reads back through pandas as NaN (a float), not None, once the
    # column has any real string values mixed in - and NaN is truthy in
    # Python, so `or` never falls through to the default, and
    # _criteria_label's string .join() then chokes on a float. Checking
    # isinstance(..., str) catches both None and NaN the same way.
    df["Criteria"] = [
        _criteria_label(mk if isinstance(mk, str) else "Any make", md if isinstance(md, str) else "Any model",
                         tr if isinstance(tr, str) else "Any trim", yr, pr, zp, 50)
        for mk, md, tr, yr, pr, zp in zip(df["Make"], df["Model"], df["Trim"], df["Min Year"], df["Max Price"], df["ZIP"])
    ]
    df["Run"] = ":material/travel_explore:"
    df["Delete"] = ":material/delete:"
    st.dataframe(
        df, use_container_width=True, hide_index=True, key="saved_car_searches_grid",
        column_order=["Profile Name", "Criteria", "Run", "Delete"],
        height=len(df) * 35 + 38,
        column_config={
            "Run": st.column_config.ButtonColumn("", width="small", type="tertiary", key="saved_car_run_click"),
            "Delete": st.column_config.ButtonColumn("", width="small", type="tertiary", key="saved_car_delete_click"),
        },
    )

    run_click = st.session_state.get("saved_car_run_click")
    if run_click and run_click.get("row") is not None:
        row = df.iloc[run_click["row"]]
        # Same NaN-is-truthy trap as the Criteria column above - `or`
        # alone doesn't catch it.
        car_make = row["Make"] if isinstance(row["Make"], str) else "Any make"
        car_model = row["Model"] if isinstance(row["Model"], str) else "Any model"
        car_trim = row["Trim"] if isinstance(row["Trim"], str) else "Any trim"
        min_year = int(row["Min Year"]) if pd.notna(row["Min Year"]) else 2018
        max_price = int(row["Max Price"]) if pd.notna(row["Max Price"]) else 30000
        max_mileage = int(row["Max Mileage"]) if pd.notna(row["Max Mileage"]) else 80000
        zip_code = row["ZIP"] if isinstance(row["ZIP"], str) else ""
        st.session_state.car_search_make = car_make
        st.session_state.car_search_model = car_model
        st.session_state.car_search_trim = car_trim
        st.session_state.car_search_min_year = min_year
        st.session_state.car_search_max_price = max_price
        st.session_state.car_search_max_mileage = max_mileage
        st.session_state.car_search_zip = zip_code
        st.session_state.car_search_radius = 50
        _run_search(car_make, car_model, car_trim, min_year, max_price, max_mileage, zip_code, 50, use_live=True)
        st.session_state.current_page = "Find a Car"
        st.rerun()

    delete_click = st.session_state.get("saved_car_delete_click")
    if delete_click and delete_click.get("row") is not None:
        st.session_state.car_saved_delete_target = {"name": df.iloc[delete_click["row"]]["Profile Name"]}

    if st.session_state.get("car_saved_delete_target"):
        _delete_saved_car_search_dialog()
