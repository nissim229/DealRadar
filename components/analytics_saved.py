"""
components/analytics_saved.py
The Saved Properties tab, split out of components/analytics.py (Section 5
monolith-split plan): properties starred from any scan. Reuses the exact
same view-mode toolbar and 4 view-mode render functions (Properties Only/
Properties + Map/Map Only/Table View) that scan results and History
already share (components/analytics_results.py) - see [[saved-properties-
view-and-sort]] - plus its own Sort control (ported from the car search
page's pattern, ported into properties since scan results never had one
either), since a growing saved list is exactly the place ordering matters
most.
"""
import json
import streamlit as st
import database as db
from underwriting import compute_deal_metrics
from icons import icon as svg_icon
from guest_mode import render_guest_banner

from components.analytics_atoms import _safe_hoa, render_empty_state
from components.analytics_results import (
    _render_quick_filter_toolbar,
    _render_properties_only_view,
    _render_properties_and_map_view,
    _render_map_only_view,
    _render_table_view,
)

SORT_OPTIONS = [
    ("best_deal", "Best Deal First"),
    ("price_asc", "Price: Low to High"),
    ("price_desc", "Price: High to Low"),
    ("newest_saved", "Newest Saved"),
    ("oldest_saved", "Oldest Saved"),
]


def _render_sort_control(key_prefix):
    """Sort control for Saved Properties - ported from car search's own
    Sort by popover (components/car_search.py), since scan results never
    had one to reuse (only cars did) and a saved list, unlike a single
    scan's results, keeps growing over days/weeks, where ordering matters
    more. 'Best Deal First' sorts by cash-on-cash return directly (no
    'too few comps to grade' case to special-case here the way cars'
    version has to - compute_deal_metrics always returns a real grade/coc
    for a property, given a price)."""
    sort_label_by_key = dict(SORT_OPTIONS)
    sort_key_by_label = {label: key for key, label in SORT_OPTIONS}
    sort_state_key = f"{key_prefix}_sort"
    if sort_state_key not in st.session_state:
        st.session_state[sort_state_key] = "best_deal"
    with st.popover(f":material/swap_vert: {sort_label_by_key[st.session_state[sort_state_key]]}"):
        picked_label = st.radio(
            "Sort by", [label for _, label in SORT_OPTIONS],
            index=[key for key, _ in SORT_OPTIONS].index(st.session_state[sort_state_key]),
            key=f"{key_prefix}_sort_radio",
        )
        new_key = sort_key_by_label[picked_label]
        if new_key != st.session_state[sort_state_key]:
            st.session_state[sort_state_key] = new_key
            st.rerun()
    return st.session_state[sort_state_key]


def _render_saved_properties_tab(view_mode, calc_rent, calc_vacancy_pct, calc_tax_rate, calc_ins_rate, calc_down_pct, calc_interest, calc_target_yield):
    st.markdown(f"""
        <div style='display:flex; align-items:center; gap:10px; margin-bottom:2px;'>
            {svg_icon("star-filled", size=20, color="var(--radar-warning)")}
            <span style='font-weight:700; font-size:var(--radar-text-xl); color:var(--radar-navy);'>Your Saved Properties</span>
        </div>
    """, unsafe_allow_html=True)
    st.caption("Properties you've starred from any scan, with your personal notes attached. Note: since DealRadar currently uses simulated listing data, there's no live 'still active' status to verify here - that would require a licensed MLS/IDX data feed.")

    saved_rows = db.get_saved_properties(st.session_state.user_id)
    if not saved_rows:
        render_empty_state(
            "star-outline", "No saved properties yet",
            "Star (☆) any property from a scan to keep track of it here, along with your own notes.",
            accent="var(--radar-warning)",
        )
        return

    key_prefix = "saved"
    # Precompute each row's metrics once, up front, rather than inside
    # each of the 4 view functions separately - needed for the Best Deal
    # sort (by coc) and cheap to carry along as extra keys in the same
    # dict the JSON-based view functions already expect.
    enriched_rows = []
    for address, title, price, beds, baths, latitude, longitude, notes, saved_at, last_price_checked_at in saved_rows:
        row_item = {
            "title": title, "address": address, "price": price,
            "beds": beds, "baths": baths, "latitude": latitude, "longitude": longitude,
        }
        metrics = compute_deal_metrics(
            float(price), calc_rent, calc_vacancy_pct, calc_tax_rate,
            calc_ins_rate, calc_down_pct, calc_interest, calc_target_yield,
            # Saved-property rows don't carry HOA yet - see
            # [[deferred-rentcast-raw-data-and-hoa]].
            hoa_monthly=_safe_hoa(row_item)
        )
        row_item["_coc"] = metrics["coc"]
        row_item["_saved_at"] = saved_at
        enriched_rows.append(row_item)

    sort_cols = st.columns([1, 4])
    with sort_cols[0]:
        sort_choice = _render_sort_control(key_prefix)

    if sort_choice == "best_deal":
        enriched_rows = sorted(enriched_rows, key=lambda r: r["_coc"], reverse=True)
    elif sort_choice == "price_asc":
        enriched_rows = sorted(enriched_rows, key=lambda r: r["price"])
    elif sort_choice == "price_desc":
        enriched_rows = sorted(enriched_rows, key=lambda r: r["price"], reverse=True)
    elif sort_choice == "newest_saved":
        enriched_rows = sorted(enriched_rows, key=lambda r: r["_saved_at"] or "", reverse=True)
    elif sort_choice == "oldest_saved":
        enriched_rows = sorted(enriched_rows, key=lambda r: r["_saved_at"] or "")

    coords_json = json.dumps(enriched_rows)
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
    elif view_toggle == ":material/map: Map Only":
        _render_map_only_view(coords_json, key_prefix, view_mode, calc_rent, calc_vacancy_pct, calc_tax_rate,
                               calc_ins_rate, calc_down_pct, calc_interest, calc_target_yield,
                               filter_min_price, filter_max_price, filter_min_beds, filter_min_baths,
                               filter_grades)
    else:
        _render_table_view(coords_json, filter_min_price, filter_max_price, filter_min_beds, filter_min_baths,
                            filter_grades, calc_rent, calc_vacancy_pct, calc_tax_rate, calc_ins_rate,
                            calc_down_pct, calc_interest, calc_target_yield, key_prefix, is_guest=False)


def render_saved_properties_page(is_guest=False):
    """Top-level Saved Properties page - promoted out of the bottom of Run
    Property Scans into its own navbar item, same move and same reasoning
    as History's own promotion (see render_history_page): the owner found
    the scan page too long to scroll past just to reach it, and a page you
    have to already be on Run Property Scans to notice is a worse place for
    it than the main navbar. Content itself (_render_saved_properties_tab)
    is unchanged - just given a real page shell and, since there's no
    longer an interactive Pro sidebar up here to source calc_* from, the
    user's saved default assumptions instead (still fully adjustable per
    property from within the results themselves) - identical pattern to
    render_history_page."""
    st.markdown("""
        <style>
        div.st-key-saved_properties_hero {
            background: var(--radar-gradient-hero);
            padding: var(--radar-space-6) var(--radar-space-7);
            margin-bottom: var(--radar-space-5);
            border-radius: 0 0 var(--radar-radius-xl) var(--radar-radius-xl);
        }
        </style>
    """, unsafe_allow_html=True)

    with st.container(key="saved_properties_hero"):
        st.markdown(f"""
            <div style='text-align:center; max-width:760px; margin:0 auto;'>
                <div style='display:flex; align-items:center; justify-content:center; gap:14px; margin-bottom:10px;'>
                    <div style='background: var(--radar-gradient-brand); width: 48px; height: 48px;
                                border-radius: var(--radar-radius-md); display:flex; align-items:center; justify-content:center; flex-shrink:0;'>
                        {svg_icon("star-filled", size=24, color="white")}
                    </div>
                    <div style='font-family:var(--radar-font-display); font-size:32px; font-weight:800; color:white; line-height:1.2;'>Saved Properties</div>
                </div>
                <div style='font-size:16px; color:var(--radar-text-on-dark-muted);'>Every property you've starred, in one place</div>
            </div>
        """, unsafe_allow_html=True)

    if is_guest:
        render_guest_banner("saved properties aren't kept in a demo session")
        render_empty_state(
            "star-outline", "Sign in to save properties",
            "Star (☆) any property from a scan to keep track of it here, along with your own notes.",
            accent="var(--radar-warning)",
        )
        return

    _defaults = st.session_state.user_settings
    view_mode = _defaults.get("default_underwriter_mode", "Simple")
    _render_saved_properties_tab(
        view_mode, 3500, _defaults["default_vacancy_pct"], _defaults["default_tax_rate"],
        _defaults["default_insurance_rate"], _defaults["default_down_pct"], _defaults["default_interest_rate"],
        _defaults["default_target_yield"],
    )

