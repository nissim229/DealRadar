import streamlit as st
import database as db
import agent_engine as engine
import email_utils
import json
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
from underwriting import compute_deal_metrics
from pdf_export import generate_pdf_download_link
from components.property_card import render_property_card, render_property_detail_dialog
from components import pricing
import plan_limits
import roles
from icons import icon as svg_icon
from data_utils import clean_value, relative_time
from dashboard_grid import render_dashboard_grid
from guest_mode import guest_action_button, render_guest_banner
from components.settings import RESULTS_VIEW_OPTIONS, format_local_datetime
from scan_loading import render_scan_loading_radar
from location_picker import render_compact_location_fields, render_city_picker_map, location_display_label

from components.analytics_atoms import (
    _format_price_short,
    _safe_hoa,
    _format_relative_time,
    render_empty_state,
    render_stat_card,
    _render_clickable_hero_card,
)


from components.analytics_dialogs import (
    _show_best_deal_dialog,
    _show_deals_meeting_target_dialog,
    _show_total_value_dialog,
)


from components.analytics_map import build_clustered_map_data, _render_clustered_results_map


from components.analytics_scan_form import (
    _render_scan_search_form,
    _render_scan_action_buttons,
    GUEST_QUICK_SEARCH_CITIES,
    _render_mini_results_strip,
)


from components.analytics_scan_engine import (
    _build_coord_list,
    _fetch_listings_for_criteria,
    _load_saved_criteria,
    _run_guest_demo_scan,
    _execute_scan,
)


from components.analytics_results import _render_scan_results, _render_hero_map_and_results



from components.analytics_history import render_history_page


def _render_saved_properties_tab(view_mode, calc_rent, calc_vacancy_pct, calc_tax_rate, calc_ins_rate, calc_down_pct, calc_interest, calc_target_yield):
    st.markdown(f"""
        <div style='display:flex; align-items:center; gap:10px; margin-bottom:2px;'>
            {svg_icon("star-filled", size=20, color="var(--radar-warning)")}
            <span style='font-weight:700; font-size:var(--radar-text-xl); color:var(--radar-navy);'>Your Saved Properties</span>
        </div>
    """, unsafe_allow_html=True)
    st.caption("Properties you've starred from any scan, with your personal notes attached. Note: since DealRadar currently uses simulated listing data, there's no live 'still active' status to verify here - that would require a licensed MLS/IDX data feed.")

    saved_rows = db.get_saved_properties(st.session_state.user_id)
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
                address, title, price, beds, baths, latitude, longitude, notes, saved_at = s_row
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
    else:
        render_empty_state(
            "star-outline", "No saved properties yet",
            "Star (☆) any property from a scan to keep track of it here, along with your own notes.",
            accent="var(--radar-warning)",
        )


def render_analytics_dashboard(is_guest=False):
    # Apply the user's saved default distance reference point (Settings)
    # once per session, only if they haven't already set/cleared one during
    # this session - a real geocode call, so it's guarded to run at most
    # once rather than on every rerun. Guests have no saved Settings to
    # read, so this simply doesn't apply to them.
    if not is_guest and not st.session_state.get("_default_reference_point_checked"):
        st.session_state._default_reference_point_checked = True
        default_ref_address = st.session_state.user_settings.get("default_reference_address")
        if default_ref_address and not st.session_state.get("distance_reference_point"):
            geo_result = engine.validate_and_geocode_location(default_ref_address)
            if geo_result:
                st.session_state.distance_reference_point = {
                    "label": default_ref_address, "latitude": geo_result["latitude"], "longitude": geo_result["longitude"]
                }

    active_category = st.session_state.get("active_category", "real_estate")
    # A guest has no saved searches (and no user_id to look any up under) -
    # skip the DB read entirely rather than pass a fake id. Used only for
    # the Quick Access chips now - scanning itself is ad-hoc and never
    # requires one of these to exist first (see [[nav_simplification_ad_hoc_search]]).
    raw_profiles = [] if is_guest else db.get_all_reports(st.session_state.user_id, category=active_category)

    # ---- SIDEBAR: DISPLAY MODE + UNDERWRITER CONSOLE ----
    # Rendered here (before the hero) rather than after it, purely so its
    # calc_* outputs exist in time for the stat cards, which now live inside
    # the hero further down. Streamlit's sidebar renders in its own fixed
    # region regardless of where in the script it's called, so this has no
    # effect on where it visually appears.
    with st.sidebar:
        if active_category == "real_estate":
            st.markdown("""
                <style>
                div.st-key-sidebar_mode_track { display:flex; gap:4px; background:var(--radar-surface-alt);
                    border-radius:var(--radar-radius-pill); padding:4px; margin-bottom:var(--radar-space-4); }
                div.st-key-sidebar_mode_track [data-testid="column"] { width:auto !important; flex:1; }
                div.st-key-sidebar_mode_simple button, div.st-key-sidebar_mode_pro button {
                    width:100%; border-radius:var(--radar-radius-pill) !important; border:none !important;
                    font-weight:600 !important; font-size:13px !important; padding:6px 0 !important;
                    min-height:0 !important; box-shadow:none !important;
                }
                div.st-key-sidebar_card { background:var(--radar-surface); border:1px solid var(--radar-border);
                    border-radius:var(--radar-radius-lg); padding:var(--radar-space-4) var(--radar-space-4);
                    margin-bottom:var(--radar-space-4); }
                [data-testid="stSidebar"] h5 {
                    color:var(--radar-text-muted) !important; font-size:11.5px !important; font-weight:700 !important;
                    letter-spacing:0.4px; text-transform:uppercase; margin-top:var(--radar-space-4) !important;
                }
                </style>
            """, unsafe_allow_html=True)

            _sidebar_mode = st.session_state.get("analytics_view_mode_toggle", st.session_state.user_settings["default_underwriter_mode"])
            with st.container(key="sidebar_mode_track"):
                mode_col1, mode_col2 = st.columns(2)
                with mode_col1:
                    with st.container(key="sidebar_mode_simple"):
                        if st.button("Simple", key="sidebar_mode_btn_simple", use_container_width=True,
                                     type="primary" if _sidebar_mode == "Simple" else "secondary"):
                            st.session_state.analytics_view_mode_toggle = "Simple"
                            st.rerun()
                with mode_col2:
                    with st.container(key="sidebar_mode_pro"):
                        if st.button("Pro", key="sidebar_mode_btn_pro", use_container_width=True,
                                     type="primary" if _sidebar_mode == "Pro" else "secondary"):
                            st.session_state.analytics_view_mode_toggle = "Pro"
                            st.rerun()
            view_mode = _sidebar_mode
            st.caption("Simple hides the detailed underwriting math and just tells you whether a deal looks good. Pro shows full investor metrics.")

            if view_mode == "Pro":
                with st.container(key="sidebar_card"):
                    st.markdown(f"""
                        <div style='display:flex; align-items:center; gap:8px; margin-bottom:2px;'>
                            {svg_icon("chart", size=17, color="var(--radar-primary)")}
                            <span style='font-weight:700; font-size:14.5px; color:var(--radar-navy);'>Underwriter Pro Console</span>
                        </div>
                    """, unsafe_allow_html=True)
                    st.caption("Fine-tune every expense assumption for a precise deal analysis.")

                if "live_scanned_properties_grid" in st.session_state and st.session_state.live_scanned_properties_grid.get("selection", {}).get("rows", []):
                    try:
                        clicked_row_idx = st.session_state.live_scanned_properties_grid["selection"]["rows"][0]
                        parsed_pts = json.loads(st.session_state.active_scanned_coords)
                        default_sidebar_price = int(parsed_pts[clicked_row_idx]["price"])
                        # So this console's own preview numbers match what
                        # the clicked property's card actually shows below
                        # it, instead of quietly assuming no HOA just
                        # because this sidebar has no HOA input of its own.
                        default_sidebar_hoa = _safe_hoa(parsed_pts[clicked_row_idx])
                    except Exception:
                        # Deliberately silent: a stale selection index (the
                        # grid's row selection can briefly point past the
                        # end of parsed_pts during a rerun transition, e.g.
                        # right after a fresh scan replaces the data) is an
                        # expected, harmless race here - falling back to a
                        # generic preview price is the correct UX, not a
                        # bug worth surfacing every time it happens.
                        default_sidebar_price = 500000
                        default_sidebar_hoa = 0
                else:
                    default_sidebar_price = 500000
                    default_sidebar_hoa = 0

                _defaults = st.session_state.user_settings
                calc_price = st.number_input("Target Purchase Price ($)", min_value=0, value=default_sidebar_price, step=25000, key="underwriter_price_input")
                calc_down_pct = st.slider("Down Payment (%)", min_value=0, max_value=100, value=int(_defaults["default_down_pct"]), key="underwriter_down_slider")
                calc_interest = st.number_input("Mortgage Interest Rate (%)", min_value=0.0, value=float(_defaults["default_interest_rate"]), step=0.25, key="underwriter_interest_input")

                st.markdown("##### Monthly Revenue & Vacancy")
                calc_rent = st.number_input("Gross Monthly Rent ($)", min_value=0, value=3500, step=100, key="underwriter_rent_input")
                calc_vacancy_pct = st.slider("Vacancy Allowance (%)", min_value=0, max_value=20, value=int(_defaults["default_vacancy_pct"]), step=1, key="underwriter_vacancy_slider")

                st.markdown("##### Expenses")
                calc_tax_rate = st.number_input("Annual Property Tax Rate (%)", min_value=0.0, max_value=5.0, value=float(_defaults["default_tax_rate"]), step=0.1, key="underwriter_tax_rate_input")
                calc_ins_rate = st.number_input("Annual Hazard Insurance Rate (%)", min_value=0.0, max_value=5.0, value=float(_defaults["default_insurance_rate"]), step=0.05, key="underwriter_ins_rate_input")

                st.markdown("##### Target Return")
                calc_target_yield = st.slider("Desired Cash-on-Cash Return (%)", min_value=1.0, max_value=20.0, value=float(_defaults["default_target_yield"]), step=0.5, key="underwriter_target_yield_slider")

                preview_metrics = compute_deal_metrics(calc_price, calc_rent, calc_vacancy_pct, calc_tax_rate,
                                                         calc_ins_rate, calc_down_pct, calc_interest, calc_target_yield,
                                                         hoa_monthly=default_sidebar_hoa)
                st.markdown("---")
                st.markdown("##### Results")
                st.metric(label="Annual NOI", value=f"${preview_metrics['noi']:,.2f}")
                st.metric(label="Cap Rate", value=f"{preview_metrics['cap_rate']:.2f}%")
                st.metric(label="Annual Cash Flow", value=f"${preview_metrics['cashflow']:,.2f}")
                st.metric(label="Cash-on-Cash Return", value=f"{preview_metrics['coc']:.2f}%")
                st.markdown("---")
            else:
                st.caption("Using your default financing assumptions from Settings. Switch to Pro mode to fine-tune every lever.")
                with st.expander("Quick numbers (optional)"):
                    calc_rent = st.number_input("Expected Monthly Rent ($)", min_value=0, value=3500, step=100, key="simple_rent_input")
                _defaults = st.session_state.user_settings
                calc_price = 500000
                calc_down_pct = _defaults["default_down_pct"]
                calc_interest = _defaults["default_interest_rate"]
                calc_vacancy_pct = _defaults["default_vacancy_pct"]
                calc_tax_rate = _defaults["default_tax_rate"]
                calc_ins_rate = _defaults["default_insurance_rate"]
                calc_target_yield = _defaults["default_target_yield"]
        else:
            # Cars: no mortgage-specific underwriter console (down
            # payment, interest rate, etc. don't apply to a car deal -
            # car_engine.py's grading is self-contained on price vs.
            # estimated market value). These stay defined because
            # _render_hero_map_and_results and friends take them
            # positionally regardless of category; the cars results
            # path never actually reads them.
            view_mode = "Simple"
            calc_price = 500000
            _defaults = st.session_state.user_settings
            calc_rent = 3500
            calc_down_pct = _defaults["default_down_pct"]
            calc_interest = _defaults["default_interest_rate"]
            calc_vacancy_pct = _defaults["default_vacancy_pct"]
            calc_tax_rate = _defaults["default_tax_rate"]
            calc_ins_rate = _defaults["default_insurance_rate"]
            calc_target_yield = _defaults["default_target_yield"]

    # ---- SUMMARY STAT CARDS (values computed here, rendered inside the hero below) ----
    best_deal_display = "-"
    target_met_display = "-"
    total_value_display = "-"
    best_deal_address = None
    best_deal_coc = None
    _pts = None
    scan_metrics = None
    best_pt_idx = None

    if "active_scanned_coords" in st.session_state and st.session_state.active_scanned_coords:
        try:
            _pts = json.loads(st.session_state.active_scanned_coords)
            if _pts:
                scan_metrics = [
                    compute_deal_metrics(p["price"], calc_rent, calc_vacancy_pct, calc_tax_rate,
                                          calc_ins_rate, calc_down_pct, calc_interest, calc_target_yield,
                                          hoa_monthly=_safe_hoa(p))
                    for p in _pts
                ]
                best_coc = max(m["coc"] for m in scan_metrics)
                best_deal_display = f"{best_coc:.1f}%"

                best_pt_idx = max(range(len(scan_metrics)), key=lambda i: scan_metrics[i]["coc"])
                best_deal_address = _pts[best_pt_idx].get("address", "")
                best_deal_coc = best_coc

                meeting_target = sum(1 for m in scan_metrics if m["grade"] == "excellent")
                target_met_display = f"{meeting_target} of {len(scan_metrics)}"

                total_value = sum(p["price"] for p in _pts)
                total_value_display = f"${total_value:,.0f}"
        except Exception as e:
            # These three feed the hero's prominent stat cards (Best Deal/
            # Deals Meeting Target/Total Value) - a crash here silently
            # falls back to their empty-state display, so it's logged
            # rather than left indistinguishable from "no scan run yet".
            print(f"[Analytics] Hero stat card computation failed: {e}")

    st.markdown("""
        <style>
        div.st-key-dashboard_hero {
            background: var(--radar-gradient-hero);
            padding: var(--radar-space-6) var(--radar-space-7) 56px var(--radar-space-7);
            margin-bottom: -36px;
            border-radius: 0 0 var(--radar-radius-xl) var(--radar-radius-xl);
        }
        div.st-key-dashboard_action_card {
            background: var(--radar-surface);
            border-radius: var(--radar-radius-lg);
            padding: var(--radar-space-5) var(--radar-space-5);
            box-shadow: var(--radar-shadow-lg);
        }
        div.st-key-dashboard_action_card button[kind="primary"] {
            background-color: var(--radar-primary) !important;
            font-weight: 700 !important;
            font-size: 16px !important;
            padding-top: 10px !important;
            padding-bottom: 10px !important;
        }
        /* Field labels match the top navbar's own typography (JetBrains
        Mono, uppercase, tracked) instead of Streamlit's default label
        style, so the search form reads as part of the same navbar
        design language rather than a generic form dropped below it. */
        div.st-key-dashboard_action_card [data-testid="stWidgetLabel"] p,
        div.st-key-dashboard_action_card .dealradar-navstyle-label {
            font-family: 'JetBrains Mono', ui-monospace, monospace !important;
            text-transform: uppercase !important;
            letter-spacing: 0.06em !important;
            font-size: 11.5px !important;
            font-weight: 700 !important;
            color: var(--radar-text-muted) !important;
            margin-bottom: 2px !important;
        }
        /* .dealradar-navstyle-label (the popover's own "label", since a
        popover trigger has no real st.widget label of its own) needs its
        own block-level spacing - stWidgetLabel already has it natively. */
        div.st-key-dashboard_action_card .dealradar-navstyle-label {
            display: block;
        }
        div.st-key-dashboard_action_card [data-baseweb="select"] * {
            font-size: 15px !important;
        }
        div.st-key-dashboard_action_card [data-baseweb="select"] > div {
            min-height: 44px !important;
        }
        /* City popover trigger - same accent language as the nav row's
        active-item color, so it reads as "belongs to this navbar family"
        rather than a plain Streamlit button. */
        div.st-key-dashboard_action_card [data-testid="stPopoverButton"] {
            min-height: 44px !important;
            font-weight: 600 !important;
            border-color: var(--radar-border) !important;
        }
        /* Dashboard-grid "Customize Layout" controls (dashboard_grid.py)
        render directly on the dark hero background here - the default
        st.caption gray is nearly unreadable on it, so brighten it to match
        the rest of this hero's on-dark text. */
        div.st-key-dashboard_hero [data-testid="stCaptionContainer"] {
            color: var(--radar-text-on-dark-muted) !important;
        }
        div[class*="st-key-dashboard_hero_card_"] button {
            background: var(--radar-surface) !important;
            border: 1px solid var(--radar-border) !important;
            border-radius: var(--radar-radius-md) !important;
            padding: 10px 14px !important;
            text-align: left !important;
            width: 100% !important;
            height: auto !important;
            white-space: pre-line !important;
        }
        div[class*="st-key-dashboard_hero_card_"] button:hover {
            box-shadow: var(--radar-shadow-sm);
        }
        div[class*="st-key-dashboard_hero_card_"] button p {
            text-align: left !important;
        }
        div.st-key-dashboard_hero_card_best_deal button { border-left: 3px solid #059669 !important; }
        div.st-key-dashboard_hero_card_deals_meeting_target button { border-left: 3px solid var(--radar-primary) !important; }
        div.st-key-dashboard_hero_card_total_value_scanned button { border-left: 3px solid #7c3aed !important; }
        </style>
    """, unsafe_allow_html=True)

    with st.container(key="dashboard_hero"):
        # Shrunk from a large centered icon+title+subtitle block to one
        # slim line - real feedback was that it "takes too much space" for
        # what's mostly restating the navbar item already highlighted
        # right above it ("Run Property Scans"), not information that
        # helps search or view results.
        st.markdown(f"""
            <div style='display:flex; align-items:center; gap:8px; margin-bottom:12px;'>
                {svg_icon("radar", size=16, color="var(--radar-accent)")}
                <span style='font-family:var(--radar-font-mono); font-size:11.5px; font-weight:700;
                             letter-spacing:0.08em; text-transform:uppercase; color:var(--radar-text-on-dark-muted);'>Run Property Scans</span>
            </div>
        """, unsafe_allow_html=True)

        with st.container(key="dashboard_action_card"):
            criteria = _render_scan_search_form(is_guest=is_guest)

            st.markdown("<div style='height:14px;'></div>", unsafe_allow_html=True)
            # Each hero card is a real (CSS-restyled) button, not decorative
            # HTML - click opens a floating st.dialog with drill-down detail,
            # matching the pattern already used for the admin dashboard's stat
            # cards (components/admin_controls.py).
            hero_cards = [
                {"id": "best_deal", "title": "Best Deal in This Scan",
                 "render": lambda: _render_clickable_hero_card(
                     "best_deal", ":material/emoji_events:", best_deal_display, "Best Deal in This Scan (CoC)",
                     lambda: _show_best_deal_dialog(_pts, scan_metrics, best_pt_idx)),
                 "default_row": 1, "default_col": 1, "default_span": 1},
                {"id": "deals_meeting_target", "title": "Deals Meeting Your Target",
                 "render": lambda: _render_clickable_hero_card(
                     "deals_meeting_target", ":material/check_circle:", target_met_display, "Deals Meeting Your Target",
                     lambda: _show_deals_meeting_target_dialog(_pts, scan_metrics)),
                 "default_row": 1, "default_col": 2, "default_span": 1},
                {"id": "total_value_scanned", "title": "Total Portfolio Value Scanned",
                 "render": lambda: _render_clickable_hero_card(
                     "total_value_scanned", ":material/payments:", total_value_display, "Total Portfolio Value Scanned",
                     lambda: _show_total_value_dialog(_pts)),
                 "default_row": 1, "default_col": 3, "default_span": 1},
            ]
            render_dashboard_grid("customer", hero_cards, default_grid_columns=3)

            st.markdown("<div style='height:14px;'></div>", unsafe_allow_html=True)
            # Button + compact results row: Run Live Scan (and friends) on
            # the left, Quick Access + a handful of top-match chips on the
            # right, right-aligned - not a full-width row of its own below
            # the button, and not shown at all until there's actually data
            # to show. See [[hero_redesign_compact_results]].
            btn_col, results_col = st.columns([1, 2.3])
            with btn_col:
                run_clicked, test_clicked = _render_scan_action_buttons(is_guest=is_guest)

            with results_col:
                # Quick Access: click a chip to re-run that exact search
                # immediately (load its saved criteria, then run) - one
                # click, not "select it, then also click Run" the way the
                # old profile dropdown needed. Guests get a fixed, curated
                # set of cities to explore instead of their own saved
                # searches (they have none) - same idea, same compact UI.
                quick_click = None
                if is_guest:
                    quick_items = [city for _, city in GUEST_QUICK_SEARCH_CITIES]
                else:
                    quick_items = raw_profiles[:5]
                if quick_items:
                    st.markdown("""
                        <style>
                        /* See the matching comment on the mini-results-strip
                        CSS - the outer key-classed div is the real flex
                        parent of these chip buttons (each st.container()
                        call is one of its several direct children, not
                        nested a level deeper). */
                        div.st-key-dashboard_quick_row {
                            display: flex !important; flex-direction: row !important;
                            flex-wrap: wrap !important; justify-content: flex-end !important; gap: 6px !important; margin-bottom: 8px !important;
                        }
                        /* See the matching comment on the mini-results-strip
                        CSS - each chip's own anonymous direct-child wrapper
                        still defaults to full-width, which forces a wrap
                        after every single chip unless constrained here too. */
                        div.st-key-dashboard_quick_row > div {
                            flex: none !important; width: fit-content !important;
                        }
                        div[class*="st-key-dashboard_quick_chip_"] {
                            flex: none !important; width: fit-content !important;
                        }
                        div[class*="st-key-dashboard_quick_chip_"] button {
                            font-size: 12px !important; padding: 4px 12px !important; min-height: 0 !important;
                            border-radius: var(--radar-radius-pill) !important; white-space: nowrap !important;
                        }
                        </style>
                    """, unsafe_allow_html=True)
                    with st.container(key="dashboard_quick_row"):
                        for i, item_label in enumerate(quick_items):
                            with st.container(key=f"dashboard_quick_chip_{i}"):
                                if st.button(f":material/history: {item_label}", key=f"dashboard_quick_btn_{i}"):
                                    quick_click = i

                if quick_click is not None:
                    if is_guest:
                        q_state, q_city = GUEST_QUICK_SEARCH_CITIES[quick_click]
                        run_clicked = True
                        criteria = {
                            "location": location_display_label(q_state, [q_city], ""),
                            "property_type": "Multi-Family", "max_price": 750000, "min_beds": 3,
                            "state": q_state, "selected_cities": [q_city], "zip_code": "",
                        }
                    else:
                        loaded = _load_saved_criteria(quick_items[quick_click], st.session_state.user_id)
                        if loaded:
                            criteria, run_clicked = loaded, True

                if is_guest:
                    if run_clicked:
                        _run_guest_demo_scan(criteria)
                    elif "active_scanned_report" not in st.session_state:
                        # First-load default so the page never looks empty for a
                        # brand-new guest, matching the old guest_landing.py's own
                        # "auto-run a sample search" behavior.
                        default_state, default_city = GUEST_QUICK_SEARCH_CITIES[0]
                        _run_guest_demo_scan({
                            "location": location_display_label(default_state, [default_city], ""),
                            "property_type": "Multi-Family", "max_price": 750000, "min_beds": 3,
                            "state": default_state, "selected_cities": [default_city], "zip_code": "",
                        })
                else:
                    _execute_scan(criteria, run_clicked, test_clicked, active_category)

                # Small result chips - only once there's actually a scan to
                # show, never a placeholder beforehand.
                if "active_scanned_report" in st.session_state and st.session_state.active_scanned_report:
                    _render_mini_results_strip(
                        st.session_state.active_scanned_coords, calc_rent, calc_vacancy_pct, calc_tax_rate, calc_ins_rate,
                        calc_down_pct, calc_interest, calc_target_yield, "hero_mini",
                    )

            st.markdown("<div style='height:16px;'></div>", unsafe_allow_html=True)
            # The map and results render inside this SAME bordered box as
            # the search form and Run Live Scan button, directly below the
            # button+chips row - not a separate box further down the page -
            # so the whole flow (search -> scan -> results) reads as one
            # continuous unit instead of several visually disconnected
            # pieces. See [[hero_redesign_unified_map]] and
            # [[hero_redesign_compact_results]].
            _render_hero_map_and_results(criteria, view_mode, calc_rent, calc_vacancy_pct, calc_tax_rate, calc_ins_rate,
                                          calc_down_pct, calc_interest, calc_target_yield, is_guest=is_guest)

    st.markdown("<div style='height:32px;'></div>", unsafe_allow_html=True)

    st.markdown("##### :material/star: Saved Properties")
    if is_guest:
        render_guest_banner("saved properties aren't kept in a demo session")
        render_empty_state(
            "star-outline", "Sign in to save properties",
            "Star (☆) any property from a scan to keep track of it here, along with your own notes.",
            accent="var(--radar-warning)",
        )
    else:
        _render_saved_properties_tab(view_mode, calc_rent, calc_vacancy_pct, calc_tax_rate, calc_ins_rate, calc_down_pct, calc_interest, calc_target_yield)
