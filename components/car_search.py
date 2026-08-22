"""
car_search.py
The redesigned Cars-category flow: search runs immediately on one page, no
saved profile required first - replaces the old two-step Manage Car Search
Criteria -> Run Car Scans pattern. Real estate's own flow (analytics.py)
was later brought to this same ad-hoc shape too - see
nav_simplification_ad_hoc_search. "Save this search" is an
optional, secondary action offered next to the results, for the minority
of users who want to revisit or re-run one - see render_saved_car_searches_page.

Real data comes from car_engine.fetch_live_car_listings (Auto.dev) when
configured and quota allows; car_engine.generate_mock_car_listings is the
offline/test-scan fallback, exactly mirroring how the real-estate side
falls back to its own local simulator.
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import database as db
import roles
import car_engine
from components.car_card import render_car_card
from components.analytics import build_clustered_map_data
from icons import icon as svg_icon
from scan_loading import render_scan_loading_radar
from guest_mode import guest_action_button, render_guest_banner

# Car cards' photo block is a plain 150px div (not an iframe like property
# cards' carousel), sized for a 3-per-row grid - shrinks/grows with the
# cards-per-row control the same way analytics_results.py's
# CARDS_PER_ROW_PHOTO_HEIGHT does for properties.
CAR_CARDS_PER_ROW_PHOTO_HEIGHT = {2: 190, 3: 150, 4: 120, 5: 100}


def _car_price_short(price):
    """Same idea as analytics.py's _format_price_short, kept as its own
    tiny copy rather than importing a module-private (leading underscore)
    name across files - a used car's price never needs the $1M+ tier that
    function's own branching handles."""
    try:
        price = float(price)
    except (TypeError, ValueError):
        return ""
    return f"${price / 1_000:.0f}K" if price >= 1_000 else f"${price:.0f}"


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


def _clean_num(value):
    """None or a real number stays as-is; NaN (a pandas-read NULL column,
    read back as a float, not None) becomes None too - `if value:` alone
    doesn't catch NaN, since NaN is truthy in Python. Same trap already
    documented for zip_code/make/model in this file, now applied to
    max_price/max_mileage/max_year, which can be genuinely NULL ("Any
    price"/"Any mileage" was picked) as well as pandas-NaN once read back
    from a saved search."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _run_search(make, model, trim, min_year, max_year, max_price, max_mileage, zip_code, radius, use_live, fuel_type=None):
    max_price, max_mileage, max_year = _clean_num(max_price), _clean_num(max_mileage), _clean_num(max_year)
    fuel_type = fuel_type if fuel_type and fuel_type != "Any fuel type" else None
    listings = None
    if use_live:
        listings = car_engine.fetch_live_car_listings(
            make=None if make == "Any make" else make,
            model=None if model == "Any model" else model,
            trim=None if trim == "Any trim" else trim,
            min_year=min_year, max_year=max_year, max_price=max_price, max_mileage=max_mileage,
            zip_code=zip_code or None, radius=radius, fuel_type=fuel_type, user_id=st.session_state.user_id,
        )
    if listings is None:
        listings = car_engine.generate_mock_car_listings(
            make=None if make == "Any make" else make,
            model=None if model == "Any model" else model,
            trim=None if trim == "Any trim" else trim,
            min_year=min_year, max_year=max_year, max_price=max_price, max_mileage=max_mileage,
            zip_code=zip_code, fuel_type=fuel_type, count=9,
        )
        was_live = False
    else:
        was_live = True

    st.session_state.car_search_results = listings
    st.session_state.car_search_was_live = was_live
    criteria_label = _criteria_label(make, model, trim, min_year, max_year, max_price, max_mileage, zip_code, radius, fuel_type)
    st.session_state.car_search_criteria_label = criteria_label

    if st.session_state.get("is_guest"):
        return

    # Lightweight log row (no report_content/coordinates_json - this page
    # doesn't build a saved report the way real-estate scans do) purely so
    # the topbar notification bell has real recent-activity data for Cars,
    # not just real estate. Same table/function real-estate scans use,
    # tagged category="cars" - see save_history_log's docstring.
    db.save_history_log(st.session_state.user_id, "Car Search", criteria_label, "", was_live=was_live, category="cars")


def _criteria_label(make, model, trim, min_year, max_year, max_price, max_mileage, zip_code, radius, fuel_type=None):
    zip_code = zip_code if isinstance(zip_code, str) else None
    fuel_type = fuel_type if isinstance(fuel_type, str) and fuel_type != "Any fuel type" else None
    max_price, max_mileage, max_year = _clean_num(max_price), _clean_num(max_mileage), _clean_num(max_year)
    bits = []
    make_model = " ".join(p for p in [None if make == "Any make" else make, None if model == "Any model" else model] if p)
    year_bit = f"{min_year}+" if min_year else ""
    if max_year:
        year_bit = f"{min_year}-{max_year}" if min_year else f"up to {max_year}"
    if make_model:
        bits.append(f"{year_bit} {make_model}".strip())
    elif year_bit:
        bits.append(year_bit)
    if trim and trim != "Any trim":
        bits.append(f"{trim} trim")
    if fuel_type and fuel_type in car_engine.FUEL_TYPE_DISPLAY:
        bits.append(car_engine.FUEL_TYPE_DISPLAY[fuel_type][1])
    bits.append(f"under ${max_price:,.0f}" if max_price else "any price")
    bits.append(f"under {max_mileage:,.0f} mi" if max_mileage else "any mileage")
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
            row1 = st.columns(6)
            with row1[0]:
                make = st.selectbox("Make", ["Any make"] + car_engine.get_available_makes(user_id=st.session_state.user_id), key="car_search_make")
            with row1[1]:
                fuel_options = ["Any fuel type"] + list(car_engine.FUEL_TYPE_DISPLAY.keys())
                fuel_type = st.selectbox(
                    "Fuel Type", fuel_options, key="car_search_fuel_type",
                    format_func=lambda v: v if v == "Any fuel type" else f"{car_engine.FUEL_TYPE_DISPLAY[v][0]} {car_engine.FUEL_TYPE_DISPLAY[v][1]}",
                )
            with row1[2]:
                model_options = ["Any model"] + (car_engine.get_available_models(make, user_id=st.session_state.user_id) if make != "Any make" else [])
                if st.session_state.get("car_search_model") not in model_options:
                    st.session_state.car_search_model = "Any model"
                model = st.selectbox("Model", model_options, key="car_search_model")
            with row1[3]:
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
            with row1[4]:
                min_year = st.number_input("Year (min)", min_value=1990, max_value=2026, value=st.session_state.get("car_search_min_year", 2018), step=1, key="car_search_min_year")
            with row1[5]:
                max_year = st.number_input("Year (max)", min_value=1990, max_value=2026, value=st.session_state.get("car_search_max_year", 2026), step=1, key="car_search_max_year",
                                            help="Together with Year (min) above, this sets a real year range - not just a floor.")

            row2 = st.columns(4)
            with row2[0]:
                # Every "Any X" checkbox below still renders its number_input
                # (disabled, not hidden) so the grid's row height doesn't
                # jump when toggled - but the number_input's own value is
                # discarded in favor of None once the checkbox is checked,
                # so a stale/leftover number never silently leaks back in
                # as a real cap.
                price_unlimited = st.checkbox("Any price", value=st.session_state.get("car_search_price_unlimited", False), key="car_search_price_unlimited")
                price_input = st.number_input("Max price ($)", min_value=1000, value=st.session_state.get("car_search_max_price", 30000), step=1000,
                                               key="car_search_max_price", disabled=price_unlimited)
                max_price = None if price_unlimited else price_input
            with row2[1]:
                mileage_unlimited = st.checkbox("Any mileage", value=st.session_state.get("car_search_mileage_unlimited", False), key="car_search_mileage_unlimited")
                mileage_input = st.number_input("Max mileage", min_value=0, value=st.session_state.get("car_search_max_mileage", 80000), step=5000,
                                                 key="car_search_max_mileage", disabled=mileage_unlimited)
                max_mileage = None if mileage_unlimited else mileage_input
            with row2[2]:
                zip_code = st.text_input("ZIP code", value=st.session_state.get("car_search_zip", ""), placeholder="e.g., 60614", key="car_search_zip")
            with row2[3]:
                radius_options = [10, 25, 50, 75, 100, 150, 250]
                radius = st.selectbox("Radius of ZIP (mi)", radius_options,
                                       index=radius_options.index(st.session_state.get("car_search_radius", 50)) if st.session_state.get("car_search_radius", 50) in radius_options else 2,
                                       key="car_search_radius", help="Only applies when a ZIP code is set above - results are limited to within this distance of it.")

            btn_col1, btn_col2, _ = st.columns([1, 1.4, 2.6])
            with btn_col1:
                search_clicked = st.button(":material/travel_explore: Search", type="primary", use_container_width=True, key="car_search_btn")
            test_clicked = False
            if roles.is_staff(st.session_state.user_role):
                with btn_col2:
                    test_clicked = st.button(":material/science: Search with sample data", key="car_search_test_btn", use_container_width=True,
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
                _run_search(make, model, trim, min_year, max_year, max_price, max_mileage, zip_code.strip(), radius,
                             use_live=(not test_clicked) and not is_guest, fuel_type=fuel_type)
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
                                max_price, 0, None, st.session_state.user_email, "08:00",
                                zip_code=zip_code or None, category="cars",
                                car_make=None if make == "Any make" else make,
                                car_model=None if model == "Any model" else model,
                                car_min_year=int(min_year), car_max_year=int(max_year),
                                car_max_mileage=int(max_mileage) if max_mileage is not None else None,
                                car_trim=None if trim == "Any trim" else trim,
                                car_fuel_type=None if fuel_type == "Any fuel type" else fuel_type,
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

    _render_car_results_view(results, "car_search")


@st.dialog("Vehicle Details", width="large")
def _render_car_detail_dialog():
    """Reuses render_car_card as the dialog's whole body - a car listing
    doesn't have the mortgage-specific "What-If Calculator"/"Notes &
    Neighborhood" tabs a property does (nothing to negotiate financing
    terms on, no nearby-schools relevance for a dealer lot), so a single
    rich view (photo, price/badge, market-value breakdown, vehicle
    history, outbound links - everything the card already shows) is the
    right-sized equivalent here, not a truncated copy of the property
    dialog's tab set."""
    ctx = st.session_state.get("car_dialog_ctx")
    if not ctx:
        st.write("No listing selected.")
        return
    render_car_card(ctx["idx"], ctx["listing"], ctx["key_prefix"])


def _render_car_view_toolbar(results, key_prefix):
    """Icon-driven view-mode + quick-filter toolbar for car results -
    mirrors analytics.py's _render_scan_results toolbar pixel-for-pixel
    (same CSS classes/pattern, same 3-part flex-row fix documented in
    [[hero_redesign_compact_results]]/[[hero_redesign_filter_toolbar]]),
    adapted to cars' own filter dimensions (price/mileage instead of
    price/beds/baths) and grade labels (Great Deal/Fair Deal/Above Market
    instead of Outstanding/Average/Negative Cash Flow). Not a literally
    shared function with analytics.py's version since the two categories'
    underlying data shapes (a list of car dicts vs. a JSON-encoded
    property coords blob) differ enough that forcing one shared renderer
    would need as much branching as this dedicated one - but
    build_clustered_map_data (used by the Map Only view below) IS
    genuinely shared, reused as-is rather than reimplemented.

    Returns (view_mode, filtered_results)."""
    view_options = [
        (":material/grid_view:", "grid", "Cars Only"),
        (":material/splitscreen:", "split", "Cars + Map"),
        (":material/map:", "map", "Map Only"),
        (":material/table_chart:", "table", "Table View"),
    ]
    view_mode_key = f"{key_prefix}_car_view_mode"
    if view_mode_key not in st.session_state:
        st.session_state[view_mode_key] = "grid"

    toolbar_key = f"{key_prefix}_car_toolbar"
    st.markdown(f"""
        <style>
        div.st-key-{toolbar_key} {{
            display: flex !important; flex-direction: row !important;
            flex-wrap: wrap !important; align-items: center !important; gap: 6px !important;
            margin-bottom: 14px !important;
        }}
        div.st-key-{toolbar_key} > div {{
            flex: none !important; width: fit-content !important;
        }}
        div.st-key-{toolbar_key} [data-testid="stPopoverButton"] {{
            border-radius: var(--radar-radius-pill) !important;
            border: 1.5px solid var(--radar-border) !important;
            background: var(--radar-surface) !important;
            font-weight: 600 !important; font-size: 13px !important;
            padding: 6px 14px !important; min-height: 34px !important;
            color: var(--radar-navy) !important; box-shadow: var(--radar-shadow-sm);
            white-space: nowrap !important;
        }}
        div.st-key-{toolbar_key} [data-testid="stPopoverButton"]:hover {{
            border-color: var(--radar-primary) !important; color: var(--radar-primary) !important;
        }}
        div[class*="st-key-{toolbar_key}_viewbtn_"] button {{
            width: 34px !important; height: 34px !important; min-height: 0 !important;
            border-radius: 50% !important; padding: 0 !important;
            border: 1.5px solid var(--radar-border) !important; background: var(--radar-surface) !important;
        }}
        div[class*="st-key-{toolbar_key}_viewbtn_"] button[kind="primary"] {{
            background: var(--radar-primary) !important; border-color: var(--radar-primary) !important;
        }}
        </style>
    """, unsafe_allow_html=True)

    filter_min_price = filter_max_price = filter_min_mileage = filter_max_mileage = None
    filter_grades = ["excellent", "average", "critical"]

    cards_per_row_key = f"{key_prefix}_car_cards_per_row"
    if cards_per_row_key not in st.session_state:
        st.session_state[cards_per_row_key] = st.session_state.user_settings.get("default_cards_per_row", 3)

    with st.container(key=toolbar_key):
        for i, (icon, mode_val, label) in enumerate(view_options):
            with st.container(key=f"{toolbar_key}_viewbtn_{i}"):
                is_active = st.session_state[view_mode_key] == mode_val
                if st.button(icon, key=f"{toolbar_key}_viewbtn_btn_{i}", help=label,
                             type="primary" if is_active else "secondary"):
                    st.session_state[view_mode_key] = mode_val
                    st.rerun()

        # Same cards-per-row control as the property side
        # (analytics_results.py's _render_quick_filter_toolbar) - not
        # literally shared (see this function's own docstring on why cars
        # keep a dedicated toolbar), but the same user-facing control and
        # session-state/Settings-default pattern.
        with st.popover(f":material/grid_view: {st.session_state[cards_per_row_key]}/row"):
            picked_cards_per_row = st.select_slider(
                "Cards per row", options=[2, 3, 4, 5], value=st.session_state[cards_per_row_key],
                key=f"{key_prefix}_car_cards_per_row_slider",
                help="More per row = smaller cards, so you can compare more at once.",
            )
            if picked_cards_per_row != st.session_state[cards_per_row_key]:
                st.session_state[cards_per_row_key] = picked_cards_per_row
                st.rerun()

        if results:
            prices = [r["price"] for r in results]
            mileages = [r["mileage"] for r in results]
            price_floor, price_ceiling = int(min(prices)), int(max(prices))
            mileage_floor, mileage_ceiling = int(min(mileages)), int(max(mileages))
            filter_min_price, filter_max_price = price_floor, price_ceiling
            filter_min_mileage, filter_max_mileage = mileage_floor, mileage_ceiling

            price_range_key = f"{key_prefix}_car_filter_price"
            current_price_range = st.session_state.get(price_range_key, (price_floor, price_ceiling))
            price_label = ("Any Price" if current_price_range == (price_floor, price_ceiling)
                            else f"${current_price_range[0]:,} - ${current_price_range[1]:,}")
            if price_ceiling > price_floor:
                with st.popover(f":material/attach_money: {price_label}", use_container_width=True):
                    filter_min_price, filter_max_price = st.slider(
                        "Price range", min_value=price_floor, max_value=price_ceiling,
                        value=(price_floor, price_ceiling), key=price_range_key, format="$%d"
                    )

            mileage_range_key = f"{key_prefix}_car_filter_mileage"
            current_mileage_range = st.session_state.get(mileage_range_key, (mileage_floor, mileage_ceiling))
            mileage_label = ("Any Mileage" if current_mileage_range == (mileage_floor, mileage_ceiling)
                              else f"{current_mileage_range[0]:,} - {current_mileage_range[1]:,} mi")
            if mileage_ceiling > mileage_floor:
                with st.popover(f":material/speed: {mileage_label}", use_container_width=True):
                    filter_min_mileage, filter_max_mileage = st.slider(
                        "Mileage range", min_value=mileage_floor, max_value=mileage_ceiling,
                        value=(mileage_floor, mileage_ceiling), key=mileage_range_key, format="%d mi"
                    )

            grade_defs = [("excellent", "🟢 Great Deal"), ("average", "🟡 Fair Deal"), ("critical", "🔴 Above Market")]
            grade_labels = [label for _, label in grade_defs]
            grade_key_by_label = {label: key for key, label in grade_defs}
            picked_grade_labels = st.pills(
                "Deal grade", grade_labels, selection_mode="multi", default=grade_labels,
                key=f"{key_prefix}_car_filter_grades", label_visibility="collapsed",
                help="Deal grade - all shown by default, click one to hide it",
            )
            filter_grades = [grade_key_by_label[label] for label in (picked_grade_labels or [])]

            # Sort control - defaults to Best Deal First so results arrive
            # best-to-worst without any click needed, but stays a real,
            # user-adjustable choice (not just a fixed default) since price/
            # mileage/year are all legitimate ways to want a list ordered.
            sort_options = [
                ("best_deal", "Best Deal First"),
                ("price_asc", "Price: Low to High"),
                ("price_desc", "Price: High to Low"),
                ("mileage_asc", "Mileage: Low to High"),
                ("year_desc", "Year: Newest First"),
                ("year_asc", "Year: Oldest First"),
            ]
            sort_label_by_key = dict(sort_options)
            sort_key_by_label = {label: key for key, label in sort_options}
            sort_state_key = f"{key_prefix}_car_sort"
            if sort_state_key not in st.session_state:
                st.session_state[sort_state_key] = "best_deal"
            with st.popover(f":material/swap_vert: {sort_label_by_key[st.session_state[sort_state_key]]}", use_container_width=True):
                picked_sort_label = st.radio(
                    "Sort by", [label for _, label in sort_options],
                    index=[key for key, _ in sort_options].index(st.session_state[sort_state_key]),
                    key=f"{key_prefix}_car_sort_radio",
                )
                # The popover's own trigger label above was already built
                # from the OLD session_state value before this radio ran -
                # without the rerun, picking a new sort correctly reorders
                # the results below (that code runs later in this same
                # script) but the button itself keeps showing the previous
                # choice until some other interaction happens to trigger a
                # second rerun. Matches the view-mode buttons' own
                # st.rerun()-on-change pattern just above.
                new_sort_key = sort_key_by_label[picked_sort_label]
                if new_sort_key != st.session_state[sort_state_key]:
                    st.session_state[sort_state_key] = new_sort_key
                    st.rerun()

    if not results:
        return st.session_state[view_mode_key], [], st.session_state[cards_per_row_key]

    def _passes_grade_filter(listing):
        # A listing with no reliable grade (too few comps) never claimed
        # to be any grade in the first place - excluding it based on a
        # grade filter would be arbitrary, so it always passes here and
        # is only ever filtered by price/mileage like everything else.
        if len(filter_grades) == 3 or not listing.get("has_reliable_grade"):
            return True
        return listing.get("grade") in filter_grades

    filtered = [
        r for r in results
        if filter_min_price <= r["price"] <= filter_max_price
        and filter_min_mileage <= r["mileage"] <= filter_max_mileage
        and _passes_grade_filter(r)
    ]

    sort_choice = st.session_state.get(f"{key_prefix}_car_sort", "best_deal")
    if sort_choice == "best_deal":
        # Graded listings first, best pct_below_market first; ungraded
        # listings (too few comps for a real grade) go to the end rather
        # than being sorted in among them - there's no honest "best" rank
        # to give a listing that was never confidently graded in the
        # first place. See [[feedback_honest_deal_grading]].
        graded = sorted((r for r in filtered if r.get("has_reliable_grade")), key=lambda r: r["pct_below_market"], reverse=True)
        ungraded = [r for r in filtered if not r.get("has_reliable_grade")]
        filtered = graded + ungraded
    elif sort_choice == "price_asc":
        filtered = sorted(filtered, key=lambda r: r["price"])
    elif sort_choice == "price_desc":
        filtered = sorted(filtered, key=lambda r: r["price"], reverse=True)
    elif sort_choice == "mileage_asc":
        filtered = sorted(filtered, key=lambda r: r["mileage"])
    elif sort_choice == "year_desc":
        filtered = sorted(filtered, key=lambda r: r["year"], reverse=True)
    elif sort_choice == "year_asc":
        filtered = sorted(filtered, key=lambda r: r["year"])

    return st.session_state[view_mode_key], filtered, st.session_state[cards_per_row_key]


def _render_car_split_view(filtered, key_prefix):
    """Cards in a scrollable left box + a results map on the right,
    clicking a card's title zooms the map to that listing's dealer -
    mirrors analytics.py's Properties + Map view/[[hero_redesign_unified_map]]'s
    "one map, reused" principle applied to cars' own results."""
    cards_col, map_col = st.columns([0.85, 1.3])
    with_coords = [r for r in filtered if r.get("latitude") is not None]
    focused_key = f"{key_prefix}_car_focused_idx"
    if focused_key not in st.session_state:
        st.session_state[focused_key] = None

    with cards_col:
        st.caption("Click a listing's title to focus the map on its dealer. Scroll to see more.")
        scroll_box_key = f"{key_prefix}_car_cards_scroll_box"
        st.markdown(f"""
            <style>
            div.st-key-{scroll_box_key} {{ max-height: 800px; overflow-y: auto; padding-right: 12px; }}
            </style>
        """, unsafe_allow_html=True)
        with st.container(key=scroll_box_key):
            for idx, listing in enumerate(filtered):
                is_focused = st.session_state[focused_key] == idx
                if render_car_card(idx, listing, f"{key_prefix}_split", is_focused=is_focused, focusable=True):
                    st.session_state[focused_key] = None if is_focused else idx
                    st.rerun()

    with map_col:
        st.markdown("##### :material/map: Map")
        if not with_coords:
            st.caption("No dealer locations available to map for these results.")
            return

        focused_idx = st.session_state[focused_key]
        if focused_idx is not None and focused_idx < len(filtered) and filtered[focused_idx].get("latitude") is not None:
            map_points = [filtered[focused_idx]]
            zoom_level = 12
        else:
            map_points = with_coords
            zoom_level = 9

        map_df = pd.DataFrame(map_points)
        map_df["_price_label"] = map_df["price"].apply(_car_price_short)
        fig = px.scatter_mapbox(
            map_df, lat="latitude", lon="longitude", hover_name="dealer_name",
            hover_data={"price": True, "latitude": False, "longitude": False},
            zoom=zoom_level, center={"lat": map_df["latitude"].mean(), "lon": map_df["longitude"].mean()},
            text="_price_label",
        )
        fig.update_traces(
            marker=dict(size=15, color="#2563eb"),
            textposition="top center", textfont=dict(color="#0f172a", size=12, family="Arial Black"),
        )
        fig.update_layout(mapbox_style="open-street-map", margin={"r": 0, "t": 0, "l": 0, "b": 0}, height=800)
        st.plotly_chart(fig, use_container_width=True, key=f"{key_prefix}_car_split_map", config={"displayModeBar": True, "scrollZoom": True})


def _render_car_clustered_map(filtered, key_prefix, height=650):
    """Full-width, grade-colored, clustered map - click a pin (or a
    cluster) for detail. Reuses build_clustered_map_data verbatim from
    analytics.py (it's generic over any lat/longitude/price/_grade/title/
    address dataframe, not property-specific) instead of reimplementing
    the same grid-bucketing logic a second time."""
    with_coords = [r for r in filtered if r.get("latitude") is not None]
    if not with_coords:
        st.info("No dealer locations available to map for these results.")
        return

    df = pd.DataFrame(with_coords).reset_index(drop=True)
    df["title"] = df.apply(lambda r: f"{r['year']} {r['make']} {r['model']}", axis=1)
    df["address"] = df.apply(lambda r: f"{r['dealer_name']} · {r['city']}, {r['state']}" if r.get("city") else r["dealer_name"], axis=1)
    # Map coloring only - an ungraded listing (has_reliable_grade=False)
    # has no real grade value at all, bucketed as "average" (amber) here
    # purely so it still renders a pin color, same neutral treatment the
    # card gives it elsewhere (a plain "Not enough data" chip, not a real
    # grade claim).
    df["_grade"] = df["grade"].fillna("average")

    grade_colors = {"excellent": "#10b981", "average": "#f59e0b", "critical": "#ef4444"}
    cluster_df = build_clustered_map_data(df)
    cluster_df["_marker_size"] = cluster_df["count"].apply(lambda c: 30 if c == 1 else min(24 + c * 3, 46))
    cluster_df["_marker_text"] = cluster_df.apply(
        lambda row: str(row["count"]) if row["is_cluster"] else _car_price_short(row["price"]), axis=1
    )

    fig = px.scatter_mapbox(
        cluster_df, lat="latitude", lon="longitude", hover_name="title",
        hover_data={"address": True, "price": True, "count": True, "latitude": False, "longitude": False},
        color="grade", color_discrete_map=grade_colors,
        size="_marker_size", size_max=46, text="_marker_text",
        zoom=9, center={"lat": df["latitude"].mean(), "lon": df["longitude"].mean()},
    )
    fig.update_traces(textfont=dict(color="white", size=11, family="Arial Black"), textposition="middle center")
    fig.update_layout(mapbox_style="open-street-map", margin={"r": 0, "t": 0, "l": 0, "b": 0}, height=height, showlegend=False)

    map_event = st.plotly_chart(
        fig, use_container_width=True, key=f"{key_prefix}_car_full_map",
        on_select="rerun", selection_mode="points", config={"displayModeBar": True, "scrollZoom": True},
    )
    selected_points = map_event.get("selection", {}).get("points", []) if map_event else []
    if selected_points:
        point_index = selected_points[0].get("point_index")
        if point_index is not None and point_index < len(cluster_df):
            clicked = cluster_df.iloc[point_index]
            st.markdown("---")
            if clicked["is_cluster"]:
                st.markdown(f"#### :material/location_on: {clicked['count']} listings in this area")
                st.caption("Zoom in on the map or narrow your filters above to click an individual listing.")
                member_rows = df.iloc[clicked["member_indices"]]
                summary_df = member_rows[["title", "dealer_name", "price"]].copy()
                summary_df["price"] = summary_df["price"].apply(lambda p: f"${p:,.0f}")
                st.dataframe(summary_df, hide_index=True, use_container_width=True, height=len(summary_df) * 35 + 38)
            else:
                st.markdown("#### :material/location_on: Selected Listing")
                sel_idx = clicked["member_indices"][0]
                render_car_card(sel_idx, df.iloc[sel_idx].to_dict(), f"{key_prefix}_map_view_card")
    else:
        st.info("Click a pin above to see that listing's price, deal grade, and full details.", icon=":material/lightbulb:")


def _render_car_table_view(filtered, key_prefix):
    if not filtered:
        st.info("No listings match your current filters.")
        return

    table_page_size = st.selectbox("Rows per page", [10, 25, 50], index=1, key=f"{key_prefix}_car_table_page_size")
    total_rows = len(filtered)
    total_pages = max(1, (total_rows + table_page_size - 1) // table_page_size)
    page_key = f"{key_prefix}_car_table_page"
    current_page = min(st.session_state.get(page_key, 1), total_pages)

    nav1, nav2, nav3 = st.columns([1, 2, 1])
    with nav1:
        if st.button(":material/chevron_left: Previous", disabled=current_page <= 1, use_container_width=True, key=f"{key_prefix}_car_table_prev"):
            st.session_state[page_key] = current_page - 1
            st.rerun()
    with nav2:
        st.markdown(f"<div style='text-align:center; padding-top:8px; color:var(--radar-text-muted); font-size:13px;'>Page {current_page} of {total_pages} · {total_rows} total listings</div>", unsafe_allow_html=True)
    with nav3:
        if st.button("Next :material/chevron_right:", disabled=current_page >= total_pages, use_container_width=True, key=f"{key_prefix}_car_table_next"):
            st.session_state[page_key] = current_page + 1
            st.rerun()

    page_slice = filtered[(current_page - 1) * table_page_size: current_page * table_page_size]
    rows = []
    for listing in page_slice:
        grade = listing.get("grade")
        trim = f" {listing['trim']}" if listing.get("trim") else ""
        fuel_type = listing.get("fuel_type")
        fuel_label = f"{car_engine.FUEL_TYPE_DISPLAY[fuel_type][0]} {car_engine.FUEL_TYPE_DISPLAY[fuel_type][1]}" if fuel_type in car_engine.FUEL_TYPE_DISPLAY else "—"
        rows.append({
            "Vehicle": f"{listing['year']} {listing['make']} {listing['model']}{trim}",
            "Fuel": fuel_label,
            "Price": float(listing["price"]),
            "Mileage": listing["mileage"],
            "Dealer": listing["dealer_name"],
            # Same emoji-prefixed labels used everywhere else for cars
            # (cards, filter pills) - not the raw internal grade key
            # title-cased, which would show generic "Critical"/"Average"/
            # "Excellent" instead of car-appropriate "Above Market"/"Fair
            # Deal"/"Great Deal". get_car_grade_label (not a plain dict
            # lookup) is what keeps this honest when "critical" was
            # reached via a condition/history downgrade rather than
            # actually being priced above market - see car_engine's
            # _car_grade_style_key docstring.
            "Grade": car_engine.get_car_grade_label(grade, listing.get("pct_below_market")) if listing.get("has_reliable_grade") and grade else "Not graded",
            "vs. Market %": round(listing["pct_below_market"], 1) if listing.get("has_reliable_grade") else None,
            "View": ":material/visibility:",
        })
    table_df = pd.DataFrame(rows)
    st.dataframe(
        table_df, use_container_width=True, hide_index=True, height=len(table_df) * 35 + 38,
        key=f"{key_prefix}_car_table_grid",
        column_config={
            "Price": st.column_config.NumberColumn(format="$%d"),
            "vs. Market %": st.column_config.NumberColumn(format="%.1f%%"),
            "View": st.column_config.ButtonColumn("", width="small", type="tertiary", key=f"{key_prefix}_car_table_view_click"),
        },
    )

    view_click = st.session_state.get(f"{key_prefix}_car_table_view_click")
    if view_click and view_click.get("row") is not None:
        idx = view_click["row"]
        if idx < len(page_slice):
            st.session_state.car_dialog_ctx = {"idx": idx, "listing": page_slice[idx], "key_prefix": f"{key_prefix}_table_dialog"}
            _render_car_detail_dialog()


def _render_car_results_view(results, key_prefix):
    """The car-category counterpart to analytics.py's view-mode dispatch
    inside _render_scan_results - same 4 view options, same toolbar shape,
    car-appropriate filters/grading. Shared by every caller of
    render_car_search_page (guest and authenticated alike, since both
    already go through that one function), so this parity applies to both
    automatically rather than needing to be built twice."""
    view_mode, filtered, cards_per_row = _render_car_view_toolbar(results, key_prefix)
    if not filtered:
        st.info("No listings match your current filters. Try widening the price or mileage range, or including more deal grades.", icon=":material/search_off:")
        return

    if view_mode == "grid":
        photo_height = CAR_CARDS_PER_ROW_PHOTO_HEIGHT.get(cards_per_row, 150)
        for row_start in range(0, len(filtered), cards_per_row):
            row = filtered[row_start:row_start + cards_per_row]
            cols = st.columns(cards_per_row)
            for slot, listing in enumerate(row):
                with cols[slot]:
                    render_car_card(row_start + slot, listing, key_prefix, photo_height=photo_height)
    elif view_mode == "split":
        _render_car_split_view(filtered, key_prefix)
    elif view_mode == "map":
        _render_car_clustered_map(filtered, key_prefix)
    else:
        _render_car_table_view(filtered, key_prefix)


def _clear_car_saved_delete_target():
    st.session_state.car_saved_delete_target = None


@st.dialog("Delete Search", on_dismiss=_clear_car_saved_delete_target)
def _delete_saved_car_search_dialog():
    """Same floating-dialog shape as analytics.py's
    _delete_history_dialog (see [[table_action_pattern]]) - no edit dialog
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
            "SELECT profile_name, max_price, zip_code, car_make, car_model, car_min_year, car_max_mileage, car_trim, car_max_year, car_fuel_type "
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

    df = pd.DataFrame(rows, columns=["Profile Name", "Max Price", "ZIP", "Make", "Model", "Min Year", "Max Mileage", "Trim", "Max Year", "Fuel Type"])
    # `mk or "Any make"` looks right but isn't: a NULL car_make column
    # reads back through pandas as NaN (a float), not None, once the
    # column has any real string values mixed in - and NaN is truthy in
    # Python, so `or` never falls through to the default, and
    # _criteria_label's string .join() then chokes on a float. Checking
    # isinstance(..., str) catches both None and NaN the same way.
    # Max Price/Max Mileage/Max Year are legitimately NULL when "Any
    # price"/"Any mileage"/no max-year cap was saved (see _clean_num,
    # which _criteria_label already applies) - passed through as-is here.
    df["Criteria"] = [
        _criteria_label(mk if isinstance(mk, str) else "Any make", md if isinstance(md, str) else "Any model",
                         tr if isinstance(tr, str) else "Any trim", yr, my, pr, ml, zp, 50,
                         fuel_type=ft if isinstance(ft, str) else None)
        for mk, md, tr, yr, my, pr, ml, zp, ft in zip(df["Make"], df["Model"], df["Trim"], df["Min Year"], df["Max Year"], df["Max Price"], df["Max Mileage"], df["ZIP"], df["Fuel Type"])
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
        car_fuel_type = row["Fuel Type"] if isinstance(row["Fuel Type"], str) else "Any fuel type"
        min_year = int(row["Min Year"]) if pd.notna(row["Min Year"]) else 2018
        max_year = int(row["Max Year"]) if pd.notna(row["Max Year"]) else 2026
        # NULL here is a genuine, saved "Any price"/"Any mileage" pick, not
        # a missing value to paper over with a made-up default (same
        # distinction _clean_num/_criteria_label already make) - restoring
        # the checkbox state below is what makes the re-run form honestly
        # reflect what was actually saved.
        max_price = int(row["Max Price"]) if pd.notna(row["Max Price"]) else None
        max_mileage = int(row["Max Mileage"]) if pd.notna(row["Max Mileage"]) else None
        zip_code = row["ZIP"] if isinstance(row["ZIP"], str) else ""
        st.session_state.car_search_make = car_make
        st.session_state.car_search_model = car_model
        st.session_state.car_search_trim = car_trim
        st.session_state.car_search_fuel_type = car_fuel_type
        st.session_state.car_search_min_year = min_year
        st.session_state.car_search_max_year = max_year
        st.session_state.car_search_price_unlimited = max_price is None
        if max_price is not None:
            st.session_state.car_search_max_price = max_price
        st.session_state.car_search_mileage_unlimited = max_mileage is None
        if max_mileage is not None:
            st.session_state.car_search_max_mileage = max_mileage
        st.session_state.car_search_zip = zip_code
        st.session_state.car_search_radius = 50
        _run_search(car_make, car_model, car_trim, min_year, max_year, max_price, max_mileage, zip_code, 50, use_live=True, fuel_type=car_fuel_type)
        st.session_state.current_page = "Find a Car"
        st.rerun()

    delete_click = st.session_state.get("saved_car_delete_click")
    if delete_click and delete_click.get("row") is not None:
        st.session_state.car_saved_delete_target = {"name": df.iloc[delete_click["row"]]["Profile Name"]}

    if st.session_state.get("car_saved_delete_target"):
        _delete_saved_car_search_dialog()
