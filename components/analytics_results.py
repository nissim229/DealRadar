"""
components/analytics_results.py
The full scan-results rendering group, split out of components/analytics.py
(Section 5 monolith-split plan): the quick-filter toolbar, all 4 view-mode
branches (Properties Only / Properties + Map / Map Only / Table View), the
shared _render_scan_results orchestrator, and _render_hero_map_and_results
(the one shared map area under the search form, before/after a scan). Moved
together as one unit since the view-mode functions are only ever called
from _render_scan_results and nowhere else, so nothing here needs a facade
re-export except _render_scan_results/_render_hero_map_and_results
themselves - both still consumed by components/analytics.py's
_render_history_tab and render_analytics_dashboard.
"""
import html
import streamlit as st
import database as db
import agent_engine as engine
import json
import pandas as pd
import plotly.express as px
from underwriting import compute_deal_metrics
from pdf_export import generate_pdf_download_link
from components.property_card import render_property_card, render_property_detail_dialog
from components import pricing
import plan_limits
from icons import icon as svg_icon
from components.settings import RESULTS_VIEW_OPTIONS
from location_picker import render_city_picker_map

from components.analytics_atoms import _format_price_short, _safe_hoa
from components.analytics_map import _render_clustered_results_map


def _render_quick_filter_toolbar(key_prefix, coords_json):
    """The one compact, icon-driven toolbar row for scan results: view-
    mode icon cluster, distance-reference popover, and price/beds/baths/
    deal-grade quick filters. Extracted out of _render_scan_results as
    step 1 of splitting that function (Section 5 monolith-split plan) -
    a pure extract-method, same CSS/key= strings, same logic, just drawn
    into its own named boundary with an explicit return value instead of
    falling straight through into the view-mode branches that used to
    follow it in the same function body.

    Returns (view_toggle, filter_min_price, filter_max_price,
    filter_min_beds, filter_min_baths, filter_grades)."""
    # One compact, icon-driven toolbar instead of several stacked rows
    # (a view-mode radio with long text labels, a permanently-visible
    # "set a distance reference" expander header, a price/beds/baths pill
    # row, a caption line, then a deal-grade pill row) - real feedback
    # was that the filter section alone "takes too much screen space".
    # View mode becomes a small icon-only button cluster (tooltip shows
    # the full name), distance reference becomes an icon button opening
    # the same kind of popover the price/beds/baths pills already use,
    # and everything shares one flex-wrapping row. Same proven CSS
    # pattern as the hero's Quick Access/mini-results chips: the toolbar
    # container needs flex-direction:row (Streamlit defaults to column),
    # AND each direct-child wrapper needs flex:none + width:fit-content
    # (Streamlit's per-widget wrapper otherwise defaults to full width,
    # which forces a wrap after every single item regardless of the
    # parent's own row layout) - see [[hero_redesign_compact_results]]
    # for how that was originally worked out.
    _view_options = [
        (":material/grid_view:", ":material/grid_view: Properties Only", "Properties Only"),
        (":material/splitscreen:", ":material/splitscreen: Properties + Map", "Properties + Map"),
        (":material/map:", ":material/map: Map Only", "Map Only"),
        (":material/table_chart:", ":material/table_chart: Table View", "Table View"),
    ]
    _default_view_index = RESULTS_VIEW_OPTIONS.index(st.session_state.user_settings["default_results_view"])
    view_mode_state_key = f"{key_prefix}_scan_results_view_mode"
    if view_mode_state_key not in st.session_state:
        st.session_state[view_mode_state_key] = _view_options[_default_view_index][1]

    toolbar_key = f"{key_prefix}_filter_toolbar"
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
        /* View-mode icon cluster: small circles, active one filled solid
        instead of a text-labeled radio row. */
        div[class*="st-key-{toolbar_key}_viewbtn_"] button {{
            width: 34px !important; height: 34px !important; min-height: 0 !important;
            border-radius: 50% !important; padding: 0 !important;
            border: 1.5px solid var(--radar-border) !important; background: var(--radar-surface) !important;
        }}
        div[class*="st-key-{toolbar_key}_viewbtn_"] button[kind="primary"] {{
            background: var(--radar-primary) !important; border-color: var(--radar-primary) !important;
        }}
        div.st-key-{toolbar_key} .stVerticalBlockBorderWrapper {{ gap: 0 !important; }}
        div.st-key-{toolbar_key} [data-testid="stMarkdownContainer"] p {{ margin: 0 !important; }}
        </style>
    """, unsafe_allow_html=True)

    with st.container(key=toolbar_key):
        for i, (icon, full_value, label) in enumerate(_view_options):
            with st.container(key=f"{toolbar_key}_viewbtn_{i}"):
                is_active = st.session_state[view_mode_state_key] == full_value
                if st.button(icon, key=f"{toolbar_key}_viewbtn_btn_{i}", help=label,
                             type="primary" if is_active else "secondary"):
                    st.session_state[view_mode_state_key] = full_value
                    st.rerun()

        with st.popover(":material/straighten:", help="Set a distance reference point"):
            st.caption("Measure every property's distance from an address (e.g. your workplace or downtown).")
            ref_input = st.text_input("Address to measure distance from",
                                       key=f"{key_prefix}_distance_reference_input", placeholder="e.g., 1600 Pennsylvania Ave, Washington DC",
                                       label_visibility="collapsed")
            if st.button("Set", key=f"{key_prefix}_set_distance_reference_btn", width="stretch"):
                geo_result = engine.validate_and_geocode_location(ref_input)
                if geo_result:
                    st.session_state.distance_reference_point = {
                        "label": ref_input, "latitude": geo_result["latitude"], "longitude": geo_result["longitude"]
                    }
                    st.rerun()
                else:
                    st.error("Couldn't find that address.")
            if st.session_state.get("distance_reference_point"):
                st.caption(f"✓ Measuring from: **{st.session_state.distance_reference_point['label']}**")
                if st.button("Clear reference point", key=f"{key_prefix}_clear_distance_reference_btn"):
                    st.session_state.distance_reference_point = None
                    st.rerun()

        # Cards-per-row control - real feedback was "i dont see how i can
        # control if in card + map, or just cards the option to change how
        # many cards i can see in each line". Seeded from the user's saved
        # default (Settings), same pattern as the view-mode toggle above -
        # a click here only changes THIS session, it doesn't write back to
        # Settings (matching view-mode's own behavior). Card width shrinks
        # automatically (Streamlit sizes each column to 1/N of the row), so
        # the only other thing that needs to actively respond is the photo
        # height - see CARDS_PER_ROW_PHOTO_HEIGHT below.
        cards_per_row_key = f"{key_prefix}_cards_per_row"
        if cards_per_row_key not in st.session_state:
            st.session_state[cards_per_row_key] = st.session_state.user_settings.get("default_cards_per_row", 3)
        with st.popover(f":material/grid_view: {st.session_state[cards_per_row_key]}/row"):
            picked_cards_per_row = st.select_slider(
                "Cards per row", options=[2, 3, 4, 5], value=st.session_state[cards_per_row_key],
                key=f"{key_prefix}_cards_per_row_slider",
                help="More per row = smaller cards, so you can compare more at once.",
            )
            if picked_cards_per_row != st.session_state[cards_per_row_key]:
                st.session_state[cards_per_row_key] = picked_cards_per_row
                st.rerun()

        # Price / Beds / Baths / Deal-grade filters share this same
        # toolbar row (moved out of their own separate row + caption
        # line below) - filter the CURRENT scan's results instantly, no
        # new scan needed. Computed from whatever this scan actually
        # returned, so the range always matches the real data.
        filter_min_price, filter_max_price, filter_min_beds, filter_min_baths = None, None, 0, 0
        filter_grades = ["excellent", "average", "critical"]
        if coords_json:
            try:
                _filter_check_points = json.loads(coords_json)
                if _filter_check_points:
                    _prices = [p["price"] for p in _filter_check_points]
                    _beds = [p.get("beds", 0) for p in _filter_check_points]
                    _baths = [p.get("baths", 0) for p in _filter_check_points]
                    price_floor, price_ceiling = int(min(_prices)), int(max(_prices))
                    # Every listing in a scan already meets the search profile's
                    # own min-beds/baths criteria (enforced both server-side in
                    # the mock generator and client-side on real RentCast
                    # results), so a dropdown starting at 0 offered options that
                    # could never filter out a single row - looking like the
                    # filter "did nothing" when a user picked a value at or
                    # below the search's own minimum. Starting the range at
                    # what's actually present in this scan's data means every
                    # selectable option is guaranteed to have a visible effect.
                    min_beds_available = int(min(_beds)) if _beds else 0
                    max_beds_available = int(max(_beds)) if _beds else 0
                    min_baths_available = int(min(_baths)) if _baths else 0
                    max_baths_available = int(max(_baths)) if _baths else 0

                    # Each filter is a rounded pill that opens a popover with the actual
                    # control inside, and the pill's own label shows the current
                    # selection (e.g. "$350K - $800K") like Zillow's filter row - rather
                    # than a slider/selectbox sitting permanently visible in a bordered
                    # card, which was the previous version of this bar.
                    price_range_key = f"{key_prefix}_quick_filter_price_range"
                    min_beds_key = f"{key_prefix}_quick_filter_min_beds"
                    min_baths_key = f"{key_prefix}_quick_filter_min_baths"
                    current_price_range = st.session_state.get(price_range_key, (price_floor, price_ceiling))
                    current_min_beds = st.session_state.get(min_beds_key, min_beds_available)
                    current_min_baths = st.session_state.get(min_baths_key, min_baths_available)

                    price_pill_label = ("Any Price" if current_price_range == (price_floor, price_ceiling)
                                         else f"${current_price_range[0]:,} - ${current_price_range[1]:,}")
                    beds_pill_label = "Any Beds" if current_min_beds <= min_beds_available else f"{current_min_beds}+ Beds"
                    baths_pill_label = "Any Baths" if current_min_baths <= min_baths_available else f"{current_min_baths}+ Baths"

                    if price_ceiling > price_floor:
                        with st.popover(f":material/attach_money: {price_pill_label}", width="stretch"):
                            filter_min_price, filter_max_price = st.slider(
                                "Price range", min_value=price_floor, max_value=price_ceiling,
                                value=(price_floor, price_ceiling), key=price_range_key,
                                format="$%d"
                            )
                    else:
                        filter_min_price, filter_max_price = price_floor, price_ceiling
                    with st.popover(f":material/bed: {beds_pill_label}", width="stretch"):
                        if max_beds_available > min_beds_available:
                            filter_min_beds = st.selectbox(
                                "Min beds", options=list(range(min_beds_available, max_beds_available + 1)),
                                index=0, key=min_beds_key,
                                help=f"Every result already has at least {min_beds_available} bed(s), so that option won't change your results."
                            )
                        else:
                            st.caption(f"Every result in this scan has exactly {min_beds_available} bed(s) - nothing to filter.")
                            filter_min_beds = min_beds_available
                    with st.popover(f":material/bathtub: {baths_pill_label}", width="stretch"):
                        if max_baths_available > min_baths_available:
                            filter_min_baths = st.selectbox(
                                "Min baths", options=list(range(min_baths_available, max_baths_available + 1)),
                                index=0, key=min_baths_key,
                                help=f"Every result already has at least {min_baths_available} bath(s), so that option won't change your results."
                            )
                        else:
                            st.caption(f"Every result in this scan has exactly {min_baths_available} bath(s) - nothing to filter.")
                            filter_min_baths = min_baths_available

                    grade_defs = [
                        ("excellent", "🟢 Outstanding"),
                        ("average", "🟡 Average"),
                        ("critical", "🔴 Negative Cash Flow"),
                    ]
                    grade_labels = [label for _, label in grade_defs]
                    grade_key_by_label = {label: key for key, label in grade_defs}

                    picked_grade_labels = st.pills(
                        "Deal grade", grade_labels, selection_mode="multi",
                        default=grade_labels, key=f"{key_prefix}_quick_filter_grades_pills",
                        label_visibility="collapsed", help="Deal grade - all shown by default, click one to hide it",
                    )
                    filter_grades = [grade_key_by_label[label] for label in (picked_grade_labels or [])]
            except Exception as e:
                # A failure anywhere in this block silently drops the whole
                # quick-filter toolbar (price/beds/baths/grade pills) with
                # no visible sign anything went wrong - logged so a UI
                # regression here doesn't go unnoticed indefinitely.
                print(f"[Analytics] Quick-filter toolbar failed to render: {e}")

    view_toggle = st.session_state[view_mode_state_key]
    cards_per_row = st.session_state[cards_per_row_key]
    return view_toggle, filter_min_price, filter_max_price, filter_min_beds, filter_min_baths, filter_grades, cards_per_row


# Photo carousel height per cards-per-row setting - a fixed 250px photo
# (this app's long-standing default, sized for a 3-per-row grid) looks
# disproportionately tall/squat once the card itself is much narrower at
# 4-5 per row, or has room to be bigger at 2 per row. Shared by both
# _render_properties_only_view and _render_properties_and_map_view so the
# same cards-per-row choice looks consistent in either.
CARDS_PER_ROW_PHOTO_HEIGHT = {2: 300, 3: 250, 4: 200, 5: 165}


def _render_properties_only_view(coords_json, filter_min_price, filter_max_price, filter_min_beds,
                                   filter_min_baths, filter_grades, calc_rent, calc_vacancy_pct,
                                   calc_tax_rate, calc_ins_rate, calc_down_pct, calc_interest,
                                   calc_target_yield, view_mode, key_prefix, focused_key, cards_per_row=3):
    """Full-width property grid, no map alongside - lets the cards use the
    whole page width (3 per row instead of 2) for someone who just wants to
    compare listings without the map competing for space. Extracted out of
    _render_scan_results as part of splitting its 4 view-mode branches into
    named functions (Section 5 monolith-split plan) - each branch takes every
    parent-scope local it references as an explicit parameter, no implicit
    closures."""
    # Full-width property grid, no map alongside - lets the
    # cards use the whole page width (3 per row instead of 2)
    # for someone who just wants to compare listings without
    # the map competing for space.
    if coords_json:
        try:
            parsed_points = json.loads(coords_json)
            df_listings_grid = pd.DataFrame(parsed_points)
            if filter_min_price is not None:
                df_listings_grid = df_listings_grid[
                    (df_listings_grid["price"] >= filter_min_price) &
                    (df_listings_grid["price"] <= filter_max_price) &
                    (df_listings_grid["beds"] >= filter_min_beds) &
                    (df_listings_grid["baths"] >= filter_min_baths)
                ].reset_index(drop=True)
            if filter_grades and len(filter_grades) < 3 and not df_listings_grid.empty:
                grade_mask = []
                for _, r in df_listings_grid.iterrows():
                    m = compute_deal_metrics(float(r["price"]), calc_rent, calc_vacancy_pct, calc_tax_rate,
                                              calc_ins_rate, calc_down_pct, calc_interest, calc_target_yield,
                                              hoa_monthly=_safe_hoa(r))
                    grade_mask.append(m["grade"] in filter_grades)
                df_listings_grid = df_listings_grid[grade_mask].reset_index(drop=True)

            if df_listings_grid.empty:
                st.info("No properties match your current filters. Try widening the price range or lowering the min beds.")
            else:
                photo_height = CARDS_PER_ROW_PHOTO_HEIGHT.get(cards_per_row, 250)
                row_indices = list(df_listings_grid.index)
                for pair_start in range(0, len(row_indices), cards_per_row):
                    pair_indices = row_indices[pair_start:pair_start + cards_per_row]
                    grid_cols = st.columns(cards_per_row)
                    for slot, idx in enumerate(pair_indices):
                        row_item = df_listings_grid.loc[idx]
                        with grid_cols[slot]:
                            metrics = compute_deal_metrics(
                                float(row_item["price"]), calc_rent, calc_vacancy_pct, calc_tax_rate,
                                calc_ins_rate, calc_down_pct, calc_interest, calc_target_yield,
                                hoa_monthly=_safe_hoa(row_item)
                            )
                            is_focused = st.session_state[focused_key] == idx
                            if render_property_card(idx, row_item, metrics, view_mode, f"{key_prefix}_grid_only_card", is_focused,
                                                     st.session_state.user_id, st.session_state.get("distance_reference_point"),
                                                     calc_target_yield,
                                                     {"down_pct": calc_down_pct, "interest": calc_interest, "rent": calc_rent,
                                                      "vacancy": calc_vacancy_pct, "tax_rate": calc_tax_rate, "ins_rate": calc_ins_rate},
                                                     photo_height=photo_height):
                                st.session_state[focused_key] = None if is_focused else idx
                                st.rerun()
        except Exception as e:
            print(f"[Analytics] Properties-only grid render failed: {e}")
            st.caption("Unable to load property listings for this scan.")


def _render_properties_and_map_view(coords_json, filter_min_price, filter_max_price, filter_min_beds,
                                      filter_min_baths, filter_grades, calc_rent, calc_vacancy_pct,
                                      calc_tax_rate, calc_ins_rate, calc_down_pct, calc_interest,
                                      calc_target_yield, view_mode, key_prefix, focused_key, cards_per_row=2):
    """Cards in a fixed-height scrollable left column (position:sticky was
    tested and failed in this Streamlit layout, so a scroll box is used
    instead) beside a map that re-centers/zooms on whichever card was
    Focused. Extracted out of _render_scan_results as part of splitting its
    4 view-mode branches into named functions (Section 5 monolith-split
    plan) - each branch takes every parent-scope local it references as an
    explicit parameter, no implicit closures."""
    # Give the cards their own fixed-height scrollable box (like
    # Zillow's left panel) instead of trying to make the map
    # "stick" while the whole page scrolls. This is more reliable
    # than position:sticky, which was tested and failed in this
    # Streamlit layout - the map simply isn't part of the
    # scrolling region at all, so it can't move regardless.
    scroll_box_key = f"{key_prefix}_cards_scroll_box"
    st.markdown(f"""
        <style>
        div.st-key-{scroll_box_key} {{
            max-height: 800px;
            overflow-y: auto;
            padding-right: 12px;
        }}
        </style>
    """, unsafe_allow_html=True)

    cards_col, map_col = st.columns([0.85, 1.3])

    if coords_json:
        try:
            parsed_points = json.loads(coords_json)
            df_listings_grid = pd.DataFrame(parsed_points)
            if filter_min_price is not None:
                df_listings_grid = df_listings_grid[
                    (df_listings_grid["price"] >= filter_min_price) &
                    (df_listings_grid["price"] <= filter_max_price) &
                    (df_listings_grid["beds"] >= filter_min_beds) &
                    (df_listings_grid["baths"] >= filter_min_baths)
                ].reset_index(drop=True)
            if filter_grades and len(filter_grades) < 3 and not df_listings_grid.empty:
                grade_mask = []
                for _, r in df_listings_grid.iterrows():
                    m = compute_deal_metrics(float(r["price"]), calc_rent, calc_vacancy_pct, calc_tax_rate,
                                              calc_ins_rate, calc_down_pct, calc_interest, calc_target_yield,
                                              hoa_monthly=_safe_hoa(r))
                    grade_mask.append(m["grade"] in filter_grades)
                df_listings_grid = df_listings_grid[grade_mask].reset_index(drop=True)

            with cards_col:
                if df_listings_grid.empty:
                    st.info("No properties match your current filters. Try widening the price range or lowering the min beds.")
                st.caption("Click **Focus** on any card to zoom the map to that property. Scroll within the list below to see more.")
                with st.container(key=scroll_box_key):
                    # This column only gets ~40% of the page width (the map
                    # takes the rest), so the SAME cards-per-row number
                    # produces a much narrower card here than in the
                    # full-width Properties Only grid - at 5/row this column
                    # was measured at ~8% of page width per card, vs ~20% for
                    # Properties Only at 5/row, and the card's own content
                    # (especially the address) doesn't reflow at that width -
                    # it wraps one or two characters per line instead of
                    # wrapping at word boundaries, since there's no min-width
                    # floor on the card. Confirmed live (real bug report):
                    # a user-chosen 5/row here rendered exactly this way.
                    # Capping at 2 for this view specifically, rather than
                    # capping the shared toolbar control's own range (which
                    # would also needlessly limit the full-width Properties
                    # Only grid), keeps this column's cards at a usable
                    # width regardless of what's picked for the other views.
                    effective_cards_per_row = min(cards_per_row, 2)
                    if effective_cards_per_row < cards_per_row:
                        st.caption(f":material/info: Showing 2 per row here - {cards_per_row} would be too narrow to read in this side-by-side view. Try Properties Only for more per row.")
                    photo_height = CARDS_PER_ROW_PHOTO_HEIGHT.get(min(effective_cards_per_row + 1, 5), 200)
                    row_indices = list(df_listings_grid.index)
                    for pair_start in range(0, len(row_indices), effective_cards_per_row):
                        pair_indices = row_indices[pair_start:pair_start + effective_cards_per_row]
                        grid_cols = st.columns(effective_cards_per_row)
                        for slot, idx in enumerate(pair_indices):
                            row_item = df_listings_grid.loc[idx]
                            with grid_cols[slot]:
                                metrics = compute_deal_metrics(
                                    float(row_item["price"]), calc_rent, calc_vacancy_pct, calc_tax_rate,
                                    calc_ins_rate, calc_down_pct, calc_interest, calc_target_yield,
                                    hoa_monthly=_safe_hoa(row_item)
                                )
                                is_focused = st.session_state[focused_key] == idx
                                if render_property_card(idx, row_item, metrics, view_mode, f"{key_prefix}_split_card_focus", is_focused,
                                                         st.session_state.user_id, st.session_state.get("distance_reference_point"),
                                                         calc_target_yield,
                                                         {"down_pct": calc_down_pct, "interest": calc_interest, "rent": calc_rent,
                                                          "vacancy": calc_vacancy_pct, "tax_rate": calc_tax_rate, "ins_rate": calc_ins_rate},
                                                         photo_height=photo_height):
                                    st.session_state[focused_key] = None if is_focused else idx
                                    st.rerun()

            with map_col:
                st.markdown("##### :material/map: Map")
                map_zoom_level = 12
                df_map_filtered = df_listings_grid.copy()

                if st.session_state[focused_key] is not None:
                    target_row_idx = st.session_state[focused_key]
                    focus_lat = df_listings_grid.iloc[target_row_idx]["latitude"]
                    focus_lon = df_listings_grid.iloc[target_row_idx]["longitude"]
                    df_map_filtered = df_listings_grid.iloc[[target_row_idx]]
                    map_zoom_level = 15
                else:
                    focus_lat = df_listings_grid["latitude"].mean()
                    focus_lon = df_listings_grid["longitude"].mean()

                df_map_filtered = df_map_filtered.copy()
                df_map_filtered["_price_label"] = df_map_filtered["price"].apply(_format_price_short)

                fig_map = px.scatter_mapbox(
                    df_map_filtered, lat="latitude", lon="longitude", hover_name="title",
                    hover_data={"address": True, "price": True, "latitude": False, "longitude": False},
                    zoom=map_zoom_level, center={"lat": focus_lat, "lon": focus_lon},
                    text="_price_label",
                )
                fig_map.update_traces(
                    marker=dict(size=15, color="#ef4444"),
                    textposition="top center", textfont=dict(color="#0f172a", size=12, family="Arial Black"),
                )
                fig_map.update_layout(mapbox_style="open-street-map", margin={"r": 0, "t": 0, "l": 0, "b": 0}, height=800)
                st.plotly_chart(fig_map, width="stretch", key=f"{key_prefix}_scatter_map", config={"displayModeBar": True, "scrollZoom": True})
        except Exception as e:
            print(f"[Analytics] Map Only view render failed: {e}")
            st.caption("Unable to load the map for this scan.")


def _render_map_only_view(coords_json, key_prefix, view_mode, calc_rent, calc_vacancy_pct, calc_tax_rate,
                           calc_ins_rate, calc_down_pct, calc_interest, calc_target_yield,
                           filter_min_price, filter_max_price, filter_min_beds, filter_min_baths,
                           filter_grades):
    """Full-width map, click a pin to see that property's full details below
    the map - a thin delegate to _render_clustered_results_map (already its
    own function). Extracted for consistency with the other 3 view-mode
    branches split out of _render_scan_results (Section 5 monolith-split
    plan)."""
    st.caption("Click any pin to see that property's full details below the map. Nearby properties group into clusters - click a cluster to see what's inside.")
    _render_clustered_results_map(
        coords_json, key_prefix, view_mode, calc_rent, calc_vacancy_pct, calc_tax_rate, calc_ins_rate,
        calc_down_pct, calc_interest, calc_target_yield,
        filter_min_price, filter_max_price, filter_min_beds, filter_min_baths, filter_grades,
    )


def _render_table_view(coords_json, filter_min_price, filter_max_price, filter_min_beds, filter_min_baths,
                        filter_grades, calc_rent, calc_vacancy_pct, calc_tax_rate, calc_ins_rate,
                        calc_down_pct, calc_interest, calc_target_yield, key_prefix, is_guest):
    """Every matched property as a sortable/filterable/paginated spreadsheet-
    style grid, with Save/View ButtonColumns wired to the same save-property
    flow and floating property-detail dialog (st.session_state.property_dialog_ctx -
    a real producer/consumer contract with components/property_card.py, key
    name unchanged by this move) the other 3 views use. Extracted out of
    _render_scan_results as the last of its 4 view-mode branches (Section 5
    monolith-split plan) - pure extract-method, no logic/key= changes."""
    st.caption("Drag a column header to reorder it, click a header to sort, or use the toolbar above the table to search, hide columns, or export to CSV.")
    if coords_json:
        try:
            parsed_points = json.loads(coords_json)
            df_listings_grid = pd.DataFrame(parsed_points)
            if filter_min_price is not None:
                df_listings_grid = df_listings_grid[
                    (df_listings_grid["price"] >= filter_min_price) &
                    (df_listings_grid["price"] <= filter_max_price) &
                    (df_listings_grid["beds"] >= filter_min_beds) &
                    (df_listings_grid["baths"] >= filter_min_baths)
                ].reset_index(drop=True)
            if filter_grades and len(filter_grades) < 3 and not df_listings_grid.empty:
                grade_mask = []
                for _, r in df_listings_grid.iterrows():
                    m = compute_deal_metrics(float(r["price"]), calc_rent, calc_vacancy_pct, calc_tax_rate,
                                              calc_ins_rate, calc_down_pct, calc_interest, calc_target_yield,
                                              hoa_monthly=_safe_hoa(r))
                    grade_mask.append(m["grade"] in filter_grades)
                df_listings_grid = df_listings_grid[grade_mask].reset_index(drop=True)

            if df_listings_grid.empty:
                st.info("No properties match your current filters. Try widening the price range or lowering the min beds.")
            else:
                table_page_size = st.selectbox("Rows per page", [10, 25, 50, 100], index=1, key=f"{key_prefix}_table_page_size")
                table_total_rows = len(df_listings_grid)
                table_total_pages = max(1, (table_total_rows + table_page_size - 1) // table_page_size)
                table_current_page = min(st.session_state.get(f"{key_prefix}_table_current_page", 1), table_total_pages)

                table_nav1, table_nav2, table_nav3 = st.columns([1, 2, 1])
                with table_nav1:
                    if st.button(":material/chevron_left: Previous", disabled=table_current_page <= 1, width="stretch", key=f"{key_prefix}_table_prev_page_btn"):
                        st.session_state[f"{key_prefix}_table_current_page"] = table_current_page - 1
                        st.session_state[f"{key_prefix}_table_selected_idx"] = None
                        st.rerun()
                with table_nav2:
                    st.markdown(f"<div style='text-align:center; padding-top:8px; color:var(--radar-text-muted); font-size:13px;'>Page {table_current_page} of {table_total_pages} · {table_total_rows} total properties</div>", unsafe_allow_html=True)
                with table_nav3:
                    if st.button("Next :material/chevron_right:", disabled=table_current_page >= table_total_pages, width="stretch", key=f"{key_prefix}_table_next_page_btn"):
                        st.session_state[f"{key_prefix}_table_current_page"] = table_current_page + 1
                        st.session_state[f"{key_prefix}_table_selected_idx"] = None
                        st.rerun()

                df_listings_page = df_listings_grid.iloc[(table_current_page - 1) * table_page_size: table_current_page * table_page_size].reset_index(drop=True)

                grade_emojis = {"excellent": "🟢", "average": "🟡", "critical": "🔴"}
                table_rows = []
                for idx, row_item in df_listings_page.iterrows():
                    m = compute_deal_metrics(float(row_item["price"]), calc_rent, calc_vacancy_pct, calc_tax_rate,
                                              calc_ins_rate, calc_down_pct, calc_interest, calc_target_yield,
                                              hoa_monthly=_safe_hoa(row_item))
                    is_saved = db.is_property_saved(st.session_state.user_id, row_item.get("address", "")) if st.session_state.user_id else False
                    table_rows.append({
                        "Address": row_item.get("address", ""),
                        "Price": float(row_item["price"]),
                        "Beds": row_item.get("beds", 0),
                        "Baths": row_item.get("baths", 0),
                        "Sqft": row_item.get("sqft"),
                        "Type": row_item.get("property_type", ""),
                        "Grade": f"{grade_emojis.get(m['grade'], '')} {m['grade'].title()}",
                        "Cap Rate %": round(m["cap_rate"], 2),
                        "Cash-on-Cash %": round(m["coc"], 2),
                        "Annual Cash Flow": round(m["cashflow"], 2),
                        # NaN (not None) keeps this column's dtype numeric so
                        # st.column_config.NumberColumn's "$%d" formatting
                        # still applies to every other row - Streamlit renders
                        # a NaN cell blank, an honest "no number to show"
                        # instead of a misleading negative dollar figure when
                        # the target return isn't achievable at any price.
                        "MAO": round(m["mao"], 2) if m["mao"] is not None else float("nan"),
                        "Save": "★" if is_saved else "☆",
                        "View": ":material/visibility:",
                    })
                table_df = pd.DataFrame(table_rows)

                st.dataframe(
                    table_df, width="stretch", hide_index=True, height=len(table_df) * 35 + 38,
                    key=f"{key_prefix}_table_view_grid",
                    column_config={
                        "Price": st.column_config.NumberColumn(format="$%d"),
                        "MAO": st.column_config.NumberColumn(format="$%d"),
                        "Annual Cash Flow": st.column_config.NumberColumn(format="$%d"),
                        "Cap Rate %": st.column_config.NumberColumn(format="%.2f%%"),
                        "Cash-on-Cash %": st.column_config.NumberColumn(format="%.2f%%"),
                        "Save": st.column_config.ButtonColumn("", width="small", type="tertiary", key=f"{key_prefix}_table_save_click"),
                        "View": st.column_config.ButtonColumn("", width="small", type="tertiary", key=f"{key_prefix}_table_view_click"),
                    },
                )

                save_click = st.session_state.get(f"{key_prefix}_table_save_click")
                if save_click and save_click.get("row") is not None and is_guest:
                    st.toast("Sign in to save this property.", icon=":material/lock:")
                    st.session_state.show_login_form = True
                    st.session_state[f"{key_prefix}_table_save_click"] = None
                    st.rerun()
                elif save_click and save_click.get("row") is not None:
                    clicked_row = df_listings_page.iloc[save_click["row"]]
                    clicked_address = clicked_row.get("address", "")
                    if db.is_property_saved(st.session_state.user_id, clicked_address):
                        db.unsave_property(st.session_state.user_id, clicked_address)
                        st.rerun()
                    elif plan_limits.is_within_limit(st.session_state.user_role, st.session_state.user_plan,
                                                      "saved_properties", db.count_saved_properties(st.session_state.user_id)):
                        db.save_property(st.session_state.user_id, clicked_address, clicked_row.get("title", "Property"),
                                          clicked_row["price"], clicked_row.get("beds", 0), clicked_row.get("baths", 0),
                                          clicked_row.get("latitude"), clicked_row.get("longitude"))
                        st.rerun()
                    else:
                        st.toast(f"Your {st.session_state.user_plan} plan's saved-properties limit is reached.", icon=":material/lock:")
                        pricing.render_pricing_dialog()

                # Jumps straight to the same floating detail dialog
                # "View Full Details" opens elsewhere, instead of
                # setting a flag that rendered an inline "Selected
                # Property" card below the (often long) table - easy
                # to miss without scrolling, per direct user feedback
                # ("its not easy for me to see that the information
                # is down the page"). The dialog is also naturally
                # width-capped (st.dialog(width="large")), which
                # fixes a second complaint for free: the same photo
                # carousel rendered at full page width here before
                # was being cropped into an extreme, ugly-looking
                # wide strip - not actually "stretched" (the carousel
                # already uses object-fit:cover, which preserves
                # aspect ratio), but a wide-open container made the
                # crop itself look distorted. A bounded dialog width
                # gives the image a sane aspect ratio to fit into.
                view_click = st.session_state.get(f"{key_prefix}_table_view_click")
                if view_click and view_click.get("row") is not None:
                    idx = view_click["row"]
                    if idx < len(df_listings_page):
                        sel_row = df_listings_page.iloc[idx]
                        sel_metrics = compute_deal_metrics(
                            float(sel_row["price"]), calc_rent, calc_vacancy_pct, calc_tax_rate,
                            calc_ins_rate, calc_down_pct, calc_interest, calc_target_yield,
                            hoa_monthly=_safe_hoa(sel_row)
                        )
                        st.session_state.property_dialog_ctx = {
                            "row_item": sel_row, "metrics": sel_metrics, "address": sel_row.get("address", ""),
                            "user_id": st.session_state.user_id,
                            "reference_point": st.session_state.get("distance_reference_point"),
                            "calc_target_yield": calc_target_yield,
                            "current_assumptions": {"down_pct": calc_down_pct, "interest": calc_interest, "rent": calc_rent,
                                                     "vacancy": calc_vacancy_pct, "tax_rate": calc_tax_rate, "ins_rate": calc_ins_rate},
                            "key_prefix": f"{key_prefix}_table_view_dialog", "idx": idx,
                        }
                        render_property_detail_dialog()
        except Exception as e:
            print(f"[Analytics] Table view render failed: {e}")
            st.caption("Unable to load the table for this scan.")


def _render_scan_results(report_body, profile_name, coords_json, key_prefix, view_mode,
                          calc_rent, calc_vacancy_pct, calc_tax_rate, calc_ins_rate,
                          calc_down_pct, calc_interest, calc_target_yield,
                          show_preview_notice=False, pdf_button_label="Export Report to Document PDF / Print",
                          pdf_filename_prefix="DealRadar_Report", is_guest=False):
    """The full scan-results view (report, best-deal banner, view toggle,
    quick filters, deal-grade chips, distance reference, property
    cards/map in all three view modes, Pro underwriting tabs, PDF export) -
    shared by both the just-ran live scan (analytics_tab1) and a selected
    History entry (analytics_tab2), so browsing your history looks exactly
    like the scan just happened, not a stripped-down summary.

    key_prefix must be unique per call site active in the same script run
    (e.g. "live" vs f"hist_{log_id}") - every internal widget/session_state
    key below is namespaced with it so two calls in the same run (live scan
    still showing, plus a history row selected) never collide."""
    if view_mode == "Pro":
        with st.expander(":material/description: Full Written Report", expanded=False):
            st.markdown(report_body)

    try:
        _header_count = len(json.loads(coords_json))
    except Exception as e:
        print(f"[Analytics] Failed to parse coords_json for results header count: {e}")
        _header_count = 0
    match_word = "Match" if _header_count == 1 else "Matches"

    # Header + any preview/sample-data note share ONE compact line instead
    # of a heading followed by a full-width colored st.info box each -
    # real feedback was that these notices "take too much space" and
    # "disturb the results view" for what's ultimately a small aside, not
    # a headline-level message.
    header_line = f"**:material/apartment: {profile_name}** — {_header_count} {match_word}"
    preview_note = None
    if show_preview_notice and st.session_state.get("last_scan_was_preview"):
        if is_guest:
            preview_note = "sample data as a guest - sign in for real listings"
        elif st.session_state.get("last_scan_was_test"):
            preview_note = "sample data (Test Scan) - no RentCast quota used"
        else:
            preview_note = "sample data - out of credits"
    if preview_note:
        st.caption(f"{header_line} · :material/visibility: {preview_note}")
        if show_preview_notice and st.session_state.get("last_scan_was_preview") and not is_guest and not st.session_state.get("last_scan_was_test"):
            if st.button(":material/add_card: Buy Credits", key=f"{key_prefix}_results_buy_credits_btn"):
                pricing.render_pricing_dialog()
    else:
        st.caption(header_line)

    best_deal_coc, best_deal_address = None, None
    try:
        _best_deal_points = json.loads(coords_json)
        for p in _best_deal_points:
            m = compute_deal_metrics(float(p["price"]), calc_rent, calc_vacancy_pct, calc_tax_rate,
                                      calc_ins_rate, calc_down_pct, calc_interest, calc_target_yield,
                                      hoa_monthly=_safe_hoa(p))
            if best_deal_coc is None or m["coc"] > best_deal_coc:
                best_deal_coc, best_deal_address = m["coc"], p.get("address", "")
    except Exception as e:
        # A crash here looks identical to "no best deal" to the user (the
        # banner just doesn't show) - logged so that silent-but-honest
        # case (see [[feedback_honest_deal_grading]]) can be told apart
        # from an actual bug in the data or the metrics computation.
        print(f"[Analytics] Best-deal computation failed: {e}")

    if best_deal_coc is not None and best_deal_coc > 0:
        st.markdown(f"""
            <div style='background:var(--radar-success-bg); border:1px solid var(--radar-success-border); border-radius:var(--radar-radius-md); padding:12px 16px; margin-bottom:16px; display:flex; align-items:center; gap:8px;'>
                <span style='color:#065f46;'>{svg_icon("trophy", size=16, color="#065f46")}</span>
                <span style='font-weight:700; color:#065f46;'>Best deal in this scan:</span>
                <span style='color:#065f46;'>{best_deal_coc:.1f}% cash-on-cash return at {best_deal_address}</span>
            </div>
        """, unsafe_allow_html=True)

    view_toggle, filter_min_price, filter_max_price, filter_min_beds, filter_min_baths, filter_grades, cards_per_row = (
        _render_quick_filter_toolbar(key_prefix, coords_json)
    )

    focused_key = f"{key_prefix}_focused_card_index"
    if focused_key not in st.session_state:
        st.session_state[focused_key] = None

    if view_toggle == ":material/grid_view: Properties Only":
        _render_properties_only_view(coords_json, filter_min_price, filter_max_price, filter_min_beds,
                                      filter_min_baths, filter_grades, calc_rent, calc_vacancy_pct,
                                      calc_tax_rate, calc_ins_rate, calc_down_pct, calc_interest,
                                      calc_target_yield, view_mode, key_prefix, focused_key, cards_per_row)

    elif view_toggle == ":material/splitscreen: Properties + Map":
        _render_properties_and_map_view(coords_json, filter_min_price, filter_max_price, filter_min_beds,
                                         filter_min_baths, filter_grades, calc_rent, calc_vacancy_pct,
                                         calc_tax_rate, calc_ins_rate, calc_down_pct, calc_interest,
                                         calc_target_yield, view_mode, key_prefix, focused_key, cards_per_row)

    elif view_toggle == ":material/map: Map Only":  # full-width map, click a pin to see that property's details
        _render_map_only_view(coords_json, key_prefix, view_mode, calc_rent, calc_vacancy_pct, calc_tax_rate,
                               calc_ins_rate, calc_down_pct, calc_interest, calc_target_yield,
                               filter_min_price, filter_max_price, filter_min_beds, filter_min_baths,
                               filter_grades)

    else:  # Table View - every matched property as a sortable/filterable spreadsheet-style grid
        _render_table_view(coords_json, filter_min_price, filter_max_price, filter_min_beds, filter_min_baths,
                            filter_grades, calc_rent, calc_vacancy_pct, calc_tax_rate, calc_ins_rate,
                            calc_down_pct, calc_interest, calc_target_yield, key_prefix, is_guest)

    st.markdown("<br>", unsafe_allow_html=True)
    pdf_data_uri = generate_pdf_download_link(profile_name, report_body)
    # html.escape() before this lands inside a quoted HTML attribute -
    # profile_name traces back to a scan's location/search-profile label,
    # not something this function can assume is quote-free, so an
    # unescaped `"` in it would otherwise break out of the download="..."
    # attribute inside this unsafe_allow_html block.
    safe_filename = html.escape(f"{pdf_filename_prefix}_{profile_name.replace(' ', '_')}.html", quote=True)
    st.markdown(f"""
        <a href="{pdf_data_uri}" download="{safe_filename}" style="text-decoration: none;">
            <div style="background-color: var(--radar-primary); color: white; text-align: center; padding: 12px; border-radius: var(--radar-radius-sm); font-weight: 500; cursor: pointer; margin-top: 15px; margin-bottom: 20px; display:flex; align-items:center; justify-content:center; gap:6px;">
                {svg_icon("download", size=15, color="white")} {pdf_button_label}
            </div>
        </a>
    """, unsafe_allow_html=True)


def _render_hero_map_and_results(criteria, view_mode, calc_rent, calc_vacancy_pct, calc_tax_rate, calc_ins_rate,
                                  calc_down_pct, calc_interest, calc_target_yield, is_guest=False):
    """The one shared map area, directly under the search form + button
    row - before a scan, city-picker mode (pick a search area); after a
    scan, the real property cards *with* the map and every view option
    (Properties Only/+Map/Map Only/Table View), rendered directly, not
    tucked behind a toggle - the browsing experience itself isn't "story
    text" to hide away, only the narrative bits inside it (the written
    report, preview notices) are, and those already stay compact/
    collapsed on their own within _render_scan_results. See
    [[hero_redesign_compact_results]]."""
    if "active_scanned_report" in st.session_state and st.session_state.active_scanned_report:
        _render_scan_results(
            st.session_state.active_scanned_report,
            st.session_state.get("active_scanned_profile", "Your Search"),
            st.session_state.active_scanned_coords,
            "live", view_mode, calc_rent, calc_vacancy_pct, calc_tax_rate, calc_ins_rate,
            calc_down_pct, calc_interest, calc_target_yield,
            show_preview_notice=True, pdf_button_label="Export Live Scan Report to Document PDF / Print",
            pdf_filename_prefix="DealRadar_Report", is_guest=is_guest,
        )
    else:
        render_city_picker_map(criteria.get("state") or "Colorado", criteria.get("selected_cities") or [], "scan_form", height=500)

