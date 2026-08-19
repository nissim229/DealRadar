import streamlit as st
import database as db
import agent_engine as engine
import email_utils
import json
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
from underwriting import compute_deal_metrics, GRADE_STYLES, render_deal_badge
from pdf_export import generate_pdf_download_link
from components.property_card import render_property_card
from components.car_card import render_car_card
from components import pricing
import plan_limits
import roles
import car_engine
from icons import icon as svg_icon
from dashboard_grid import render_dashboard_grid
from components.settings import RESULTS_VIEW_OPTIONS, format_local_datetime
from nav import render_side_nav


def _format_price_short(price):
    """Abbreviates a price for map pin labels ($450,000 -> "$450K"), matching
    how Zillow shows price directly on unclustered pins - useful for an
    investor eyeballing price spread across the map before clicking anything."""
    try:
        price = float(price)
    except (TypeError, ValueError):
        return ""
    if price >= 1_000_000:
        return f"${price / 1_000_000:.2g}M"
    return f"${price / 1_000:.0f}K"


def _format_relative_time(timestamp_str):
    """Turns a SQLite CURRENT_TIMESTAMP string ('2026-08-16 07:31:28', UTC)
    into a relative label like 'Saved 3 hours ago'. This is deliberately a
    freshness note, not a claim about whether the listing is still active -
    this app has no live MLS/IDX feed to verify that, so the honest signal
    to show is how long ago the snapshot was taken, matching how the major
    listing sites handle results they can't re-verify in real time either."""
    try:
        saved_dt = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return f"Saved {timestamp_str}"

    delta = datetime.utcnow() - saved_dt
    seconds = delta.total_seconds()
    if seconds < 60:
        return "Saved just now"
    if seconds < 3600:
        minutes = int(seconds // 60)
        return f"Saved {minutes} minute{'s' if minutes != 1 else ''} ago"
    if seconds < 86400:
        hours = int(seconds // 3600)
        return f"Saved {hours} hour{'s' if hours != 1 else ''} ago"
    days = int(seconds // 86400)
    if days < 30:
        return f"Saved {days} day{'s' if days != 1 else ''} ago"
    if days < 365:
        months = days // 30
        return f"Saved {months} month{'s' if months != 1 else ''} ago"
    years = days // 365
    return f"Saved {years} year{'s' if years != 1 else ''} ago"


def render_empty_state(icon_name, title, description, cta_label=None, cta_page=None, accent="var(--radar-primary)"):
    """A designed empty state (icon + headline + description + optional
    navigation button) instead of a bare st.info() one-liner - this is the
    first thing a brand-new user with no data yet actually sees, so it's
    worth more than a single line of text."""
    st.markdown(f"""
        <div style='text-align:center; padding:var(--radar-space-8) var(--radar-space-5); background:var(--radar-surface-alt);
                    border:1px dashed var(--radar-border); border-radius:var(--radar-radius-lg);'>
            <div style='width:56px; height:56px; border-radius:50%; background:var(--radar-surface); display:flex; align-items:center;
                        justify-content:center; margin:0 auto var(--radar-space-4) auto; box-shadow:var(--radar-shadow-sm);'>
                {svg_icon(icon_name, size=26, color=accent)}
            </div>
            <div style='font-weight:700; font-size:var(--radar-text-lg); color:var(--radar-navy); margin-bottom:6px;'>{title}</div>
            <div style='color:var(--radar-text-muted); font-size:14px; max-width:420px; margin:0 auto;'>{description}</div>
        </div>
    """, unsafe_allow_html=True)
    if cta_label and cta_page:
        st.markdown("<div style='height:12px;'></div>", unsafe_allow_html=True)
        _, btn_col, _ = st.columns([1, 1.4, 1])
        with btn_col:
            if st.button(cta_label, key=f"empty_state_cta_{cta_page}_{title}", type="primary", use_container_width=True):
                st.session_state.current_page = cta_page
                st.rerun()


def render_stat_card(icon_name, label, value, accent="var(--radar-primary)"):
    st.markdown(f"""
        <div style='background:var(--radar-surface); border:1px solid var(--radar-border); border-radius:var(--radar-radius-md); padding:10px 14px;
                    border-left: 3px solid {accent}; display:flex; align-items:center; gap:10px;'>
            <div style='flex-shrink:0; color:{accent};'>{svg_icon(icon_name, size=19)}</div>
            <div style='line-height:1.15;'>
                <div style='font-size:16px; font-weight:800; color:var(--radar-navy);'>{value}</div>
                <div style='font-size:10.5px; color:var(--radar-text-muted); font-weight:600; letter-spacing:0.2px;'>{label}</div>
            </div>
        </div>
    """, unsafe_allow_html=True)


def _render_clickable_hero_card(card_id, icon_shortcode, value, label, on_click):
    """Same CSS-restyled-button pattern used for the admin dashboard's stat
    cards (components/admin_controls.py) - a real st.button dressed up as a
    card, since a plain HTML div can't open an st.dialog on click."""
    with st.container(key=f"dashboard_hero_card_{card_id}"):
        if st.button(f"{icon_shortcode} **{value}**\n{label}", key=f"dashboard_hero_card_btn_{card_id}",
                     use_container_width=True):
            on_click()


@st.dialog("Best Deal Details")
def _show_best_deal_dialog(pts, metrics, best_idx):
    if best_idx is None:
        st.caption("No scan data yet - run a live scan to see your best deal here.")
        return
    p, m = pts[best_idx], metrics[best_idx]
    st.markdown(f"**{p.get('address') or p.get('title', 'Untitled Property')}**")
    detail_bits = []
    if p.get("beds"):
        detail_bits.append(f"{p['beds']} bd")
    if p.get("baths"):
        detail_bits.append(f"{p['baths']} ba")
    if p.get("sqft"):
        detail_bits.append(f"{p['sqft']:,} sqft")
    if p.get("property_type"):
        detail_bits.append(p["property_type"])
    if detail_bits:
        st.caption(" · ".join(str(b) for b in detail_bits))
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Price", f"${p['price']:,.0f}")
        st.metric("Cash-on-Cash Return", f"{m['coc']:.2f}%")
    with col2:
        st.metric("Cap Rate", f"{m['cap_rate']:.2f}%")
        st.metric("Annual Cash Flow", f"${m['cashflow']:,.2f}")
    st.caption("Full results with every match are in the 'Execute Live Scan' tab below.")


@st.dialog("Deals Meeting Your Target")
def _show_deals_meeting_target_dialog(pts, metrics):
    if not pts:
        st.caption("No scan data yet - run a live scan to see matches here.")
        return
    matches = [(p, m) for p, m in zip(pts, metrics) if m["grade"] == "excellent"]
    if not matches:
        st.caption("No deals meet your target return yet in this scan. Try lowering your target return in the sidebar.")
        return
    matches.sort(key=lambda pm: pm[1]["coc"], reverse=True)
    st.dataframe(
        pd.DataFrame([
            {"Address": p.get("address") or p.get("title", "-"), "Price": f"${p['price']:,.0f}", "CoC Return": f"{m['coc']:.1f}%"}
            for p, m in matches
        ]),
        use_container_width=True, hide_index=True, height=min(len(matches), 10) * 35 + 38,
    )
    st.caption("Full results with map and filters are in the 'Execute Live Scan' tab below.")


@st.dialog("Portfolio Value Breakdown")
def _show_total_value_dialog(pts):
    if not pts:
        st.caption("No scan data yet - run a live scan to see a breakdown here.")
        return

    def _city_of(addr):
        parts = [x.strip() for x in (addr or "").split(",")]
        return parts[-2] if len(parts) >= 2 else (addr or "Unknown")

    by_city = {}
    for p in pts:
        city = _city_of(p.get("address", ""))
        entry = by_city.setdefault(city, {"count": 0, "total": 0})
        entry["count"] += 1
        entry["total"] += p.get("price", 0)
    rows = sorted(by_city.items(), key=lambda kv: kv[1]["total"], reverse=True)
    st.dataframe(
        pd.DataFrame([
            {"City": city, "Properties": info["count"], "Total Value": f"${info['total']:,.0f}"}
            for city, info in rows
        ]),
        use_container_width=True, hide_index=True, height=min(len(rows), 10) * 35 + 38,
    )
    st.caption(f"{len(pts)} propert{'y' if len(pts) == 1 else 'ies'} scanned across {len(by_city)} location{'s' if len(by_city) != 1 else ''} in this scan.")


def build_clustered_map_data(df, cluster_grid_deg=0.008):
    """Groups nearby properties into clusters for map display. Plotly's free
    open-street-map style has no native clustering (that requires a paid
    Mapbox token, which this app doesn't have) - so this buckets properties
    by rounding their lat/lon to a shared grid cell. Cells with more than one
    property become a single cluster marker showing a count; isolated
    properties still render as individual pins color-coded by grade.

    Tested with: far-apart points (no clustering), very-close points (full
    cluster), and a mixed case (one cluster + one isolated point) - all
    produce correct counts, dominant grades, and traceable member indices
    back to the original dataframe."""
    df = df.copy()
    df["_grid_lat"] = (df["latitude"] / cluster_grid_deg).round() * cluster_grid_deg
    df["_grid_lon"] = (df["longitude"] / cluster_grid_deg).round() * cluster_grid_deg

    clustered_rows = []
    for (glat, glon), group in df.groupby(["_grid_lat", "_grid_lon"]):
        if len(group) == 1:
            row = group.iloc[0]
            clustered_rows.append({
                "latitude": row["latitude"], "longitude": row["longitude"],
                "count": 1, "label": f"${row['price']:,.0f}",
                "grade": row["_grade"], "is_cluster": False,
                "title": row["title"], "address": row["address"], "price": row["price"],
                "member_indices": [row.name],
            })
        else:
            avg_lat = group["latitude"].mean()
            avg_lon = group["longitude"].mean()
            avg_price = group["price"].mean()
            dominant_grade = group["_grade"].mode().iloc[0]
            clustered_rows.append({
                "latitude": avg_lat, "longitude": avg_lon,
                "count": len(group), "label": f"{len(group)} homes",
                "grade": dominant_grade, "is_cluster": True,
                "title": f"{len(group)} properties", "address": "", "price": avg_price,
                "member_indices": list(group.index),
            })
    return pd.DataFrame(clustered_rows)


def _render_scan_action(raw_profiles):
    default_index = 0
    if st.session_state.get("dashboard_quick_selected_profile") in raw_profiles:
        default_index = raw_profiles.index(st.session_state.dashboard_quick_selected_profile)

    col1, col2 = st.columns([3, 1])
    with col1:
        selected_profile = st.selectbox("Select Target Profile to Execute", options=raw_profiles,
                                         index=default_index, key="scan_profile_selectbox")
    with col2:
        st.markdown("<div style='margin-top:28px;'></div>", unsafe_allow_html=True)
        # Scanning itself is never blocked - a user out of credits still
        # gets a full, useful preview scan (sample data), so they can see
        # what the tool does before ever paying. Credits only decide
        # whether THIS scan pulls real market data instead of a preview.
        run_clicked = st.button(":material/travel_explore: Run Live Scan", type="primary", use_container_width=True, key="run_scan_btn")
        # Staff-only (any of the 3 tiers - see roles.py): forces mock/sample
        # data regardless of role or credits, so staff can exercise the UI
        # (new views, filters, pagination...) without burning real RentCast
        # quota - previously the only way to get preview data as staff was
        # to hand-edit a test account's credits to 0, since being staff
        # always granted allow_live=True.
        test_clicked = False
        if roles.is_staff(st.session_state.user_role):
            test_clicked = st.button(":material/science: Run Test Scan", use_container_width=True, key="run_test_scan_btn",
                                      help="Uses mock/sample data - doesn't spend real RentCast quota.")
        if st.session_state.user_credits <= 0 and not roles.is_admin_or_above(st.session_state.user_role):
            if st.button(":material/add_card: Buy Credits for real data", use_container_width=True, key="buy_credits_trigger_btn"):
                pricing.render_pricing_dialog()

    if run_clicked or test_clicked:
        loading_placeholder = st.empty()
        with loading_placeholder.container():
            st.markdown("""
            <style>
            @keyframes radarPulse {
                0% { transform: scale(0.3); opacity: 0.9; }
                100% { transform: scale(1.9); opacity: 0; }
            }
            @keyframes radarSpin {
                from { transform: rotate(0deg); }
                to { transform: rotate(360deg); }
            }
            .scout-loading-wrap {
                display:flex; flex-direction:column; align-items:center; justify-content:center;
                padding: 36px 0;
            }
            .scout-radar { position: relative; width: 90px; height: 90px; margin-bottom: 18px; }
            .scout-radar-ring {
                position: absolute; inset:0; border-radius:50%;
                border: 3px solid var(--radar-primary);
                animation: radarPulse 1.6s ease-out infinite;
            }
            .scout-radar-ring:nth-child(2) { animation-delay: 0.5s; }
            .scout-radar-ring:nth-child(3) { animation-delay: 1.0s; }
            .scout-radar-core {
                position:absolute; inset:30px; border-radius:50%;
                background: var(--radar-gradient-brand);
                display:flex; align-items:center; justify-content:center; font-size:22px;
                animation: radarSpin 2s linear infinite;
            }
            .scout-loading-text { font-weight:600; color:var(--radar-navy); font-size:15px; }
            .scout-loading-sub { color:var(--radar-text-muted); font-size:13px; margin-top:4px; }
            </style>
            <div class="scout-loading-wrap">
                <div class="scout-radar">
                    <div class="scout-radar-ring"></div>
                    <div class="scout-radar-ring"></div>
                    <div class="scout-radar-ring"></div>
                    <div class="scout-radar-core">🛰️</div>
                </div>
                <div class="scout-loading-text">Scanning the market...</div>
                <div class="scout-loading-sub">Matching properties against your criteria</div>
            </div>
            """, unsafe_allow_html=True)

        try:
            # Credits are the real-data currency, independent of plan tier -
            # a scan with credits available spends one and pulls real
            # RentCast listings; a scan with none left still runs (never
            # blocked) but falls back to preview/sample data, same as a
            # Free-plan or guest search. This lets a user who's exhausted
            # their free credits keep experiencing the tool - grading,
            # underwriting, the full UI - without ever hitting a wall,
            # while still giving them a clear reason to buy more credits
            # (real listings) rather than a hard stop.
            allow_live = (not test_clicked) and (roles.is_admin_or_above(st.session_state.user_role) or st.session_state.user_credits > 0)
            if allow_live and not roles.is_admin_or_above(st.session_state.user_role):
                db.deduct_credit(st.session_state.user_id)
                _credits_before = st.session_state.user_credits
                st.session_state.user_credits = max(0, st.session_state.user_credits - 1)
                # Fires once, exactly when the balance crosses into 0 - not
                # on every subsequent 0-credit scan, since that would mean
                # an email every single time an out-of-credits user keeps
                # using the app's still-available preview mode.
                if _credits_before == 1 and st.session_state.user_settings.get("notify_low_credits"):
                    email_utils.send_low_credits_email(st.session_state.user_email)
            st.session_state.last_scan_was_preview = not allow_live
            st.session_state.last_scan_was_test = test_clicked

            import sqlite3
            conn = sqlite3.connect(db.DB_NAME)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT location, property_type, max_price, min_beds, state, cities_json, zip_code, category, car_make, car_model, car_min_year, car_max_mileage "
                "FROM reports WHERE user_id=? AND profile_name=?",
                (int(st.session_state.user_id), selected_profile)
            )
            p_row = cursor.fetchone()
            conn.close()

            # Cars category: mock listings only for now (see car_engine.py's
            # module docstring) - deliberately skipped from the real-estate
            # pipeline below (run_agent_workflow's written report, history
            # log's lat/long-shaped coords, deal-found email) rather than
            # bent to fit a shape built for property listings. Results are
            # shown directly, not persisted to history, until this category
            # gets its own real backing data and it's worth designing that
            # storage properly.
            if p_row and p_row[7] == "cars":
                car_listings = car_engine.generate_mock_car_listings(
                    make=p_row[8], model=p_row[9], min_year=p_row[10], max_price=int(p_row[2]),
                    max_mileage=p_row[11], zip_code=p_row[6], count=6,
                )
                st.session_state.active_scanned_car_listings = car_listings
                st.session_state.active_scanned_profile = selected_profile
                st.session_state.active_scanned_category = "cars"
                st.session_state.active_scanned_report = None
                st.session_state.active_scanned_coords = None
                st.success("Scan complete!")
                st.rerun()
                return

            st.session_state.active_scanned_category = "real_estate"

            profile_location = str(p_row[0]) if p_row else "Unknown"
            profile_type = str(p_row[1]) if p_row else "Multi-Family"
            profile_max_price = int(p_row[2]) if p_row else 750000
            profile_min_beds = int(p_row[3]) if p_row else 3
            profile_state = p_row[4] if p_row else None
            profile_cities_json = p_row[5] if p_row else None
            profile_zip = p_row[6] if p_row else None

            if profile_state is None:
                # Legacy search, saved before the state/city picker existed
                # (or the auto-seeded "My First Search" from registration) -
                # unchanged behavior, exactly as it worked before this change.
                raw_listings_data = engine.fetch_live_listings(profile_location, profile_type, profile_max_price, profile_min_beds, allow_live=allow_live, user_id=st.session_state.user_id)
            else:
                selected_cities = json.loads(profile_cities_json) if profile_cities_json else []
                targets = []
                if selected_cities:
                    for city in selected_cities:
                        coords = engine.resolve_city_coords(city, profile_state)
                        if coords:
                            targets.append({"lat": coords[0], "lon": coords[1], "label": f"{city}, {profile_state}", "city_name": city})
                elif profile_zip:
                    geo_result = engine.validate_and_geocode_location(f"{profile_zip}, {profile_state}")
                    if geo_result:
                        targets.append({"lat": geo_result["latitude"], "lon": geo_result["longitude"], "label": f"{profile_zip}, {profile_state}", "city_name": None})
                else:
                    geo_result = engine.validate_and_geocode_location(profile_state)
                    if geo_result:
                        targets.append({"lat": geo_result["latitude"], "lon": geo_result["longitude"], "label": f"Any city in {profile_state}", "city_name": None})
                raw_listings_data = engine.fetch_live_listings_for_targets(targets, profile_type, profile_max_price, profile_min_beds, allow_live=allow_live, user_id=st.session_state.user_id) if targets else []
            report_result = engine.run_agent_workflow(selected_profile, st.session_state.user_id, raw_listings=raw_listings_data)

            coord_list = []
            for listing in raw_listings_data:
                if "latitude" in listing and "longitude" in listing:
                    coord_list.append({
                        "title": listing.get("title", "Asset Match"),
                        "address": listing.get("address", ""),
                        "price": listing.get("price", 0),
                        "beds": listing.get("beds", 0),
                        "baths": listing.get("baths", 0),
                        "sqft": listing.get("sqft"),
                        "property_type": listing.get("property_type"),
                        "latitude": listing["latitude"],
                        "longitude": listing["longitude"],
                        "mls_number": listing.get("mls_number"),
                        "mls_name": listing.get("mls_name"),
                    })

            coord_string_data = json.dumps(coord_list)
            db.save_history_log(st.session_state.user_id, selected_profile, profile_location, report_result, coord_string_data, was_live=allow_live)

            # Deal-found email - only for a real live scan (never a mock/
            # preview scan, since alerting someone about a fake randomly-
            # generated listing would be actively misleading) and only if
            # opted in via Settings. Graded against the user's saved default
            # assumptions (not whatever the sidebar happens to show right
            # now) so the trigger is stable regardless of in-session sidebar
            # fiddling.
            if allow_live and st.session_state.user_settings.get("notify_deal_found") and coord_list:
                _d = st.session_state.user_settings
                _excellent = [
                    # Same 0.7%-of-price rule-of-thumb rent estimate used
                    # elsewhere in this app when no real income figure is
                    # available (see generate_offline_mock_report) - a flat
                    # dollar rent would badly misgrade anything far from
                    # that number.
                    compute_deal_metrics(p["price"], p["price"] * 0.007, _d["default_vacancy_pct"], _d["default_tax_rate"],
                                          _d["default_insurance_rate"], _d["default_down_pct"], _d["default_interest_rate"],
                                          _d["default_target_yield"])
                    for p in coord_list
                ]
                _excellent = [m for m in _excellent if m["grade"] == "excellent"]
                if _excellent:
                    email_utils.send_deal_found_email(
                        st.session_state.user_email, selected_profile, len(_excellent),
                        max(m["coc"] for m in _excellent),
                    )

            st.session_state.active_scanned_report = report_result
            st.session_state.active_scanned_profile = selected_profile
            st.session_state.active_scanned_coords = coord_string_data
            st.session_state.focused_card_index = None

            st.success("Scan complete!")
            st.rerun()
        except Exception:
            st.error("Something went wrong running this scan. Please try again.")
        finally:
            loading_placeholder.empty()


def _render_scan_results(report_body, profile_name, coords_json, key_prefix, view_mode,
                          calc_rent, calc_vacancy_pct, calc_tax_rate, calc_ins_rate,
                          calc_down_pct, calc_interest, calc_target_yield,
                          show_preview_notice=False, pdf_button_label="Export Report to Document PDF / Print",
                          pdf_filename_prefix="DealRadar_Report"):
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
    st.markdown("---")

    if view_mode == "Pro":
        with st.expander(":material/description: Full Written Report", expanded=True):
            st.markdown(report_body)
    else:
        st.info("Simple mode is showing you deal cards below. Switch to Pro mode in the sidebar for the full written analyst report and detailed underwriting.", icon=":material/lightbulb:")

    try:
        _header_count = len(json.loads(coords_json))
    except Exception:
        _header_count = 0
    match_word = "Match" if _header_count == 1 else "Matches"
    st.markdown(f"### :material/apartment: {profile_name} — {_header_count} {match_word}")

    if show_preview_notice and st.session_state.get("last_scan_was_preview"):
        if st.session_state.get("last_scan_was_test"):
            st.info(":material/science: This was a **Test Scan** - showing mock/sample data so you can check the UI without spending real RentCast quota. Use Run Live Scan when you want real listings.")
        else:
            notice_col1, notice_col2 = st.columns([4, 1])
            with notice_col1:
                st.info("This scan is showing preview/sample data - you're out of credits. Buy more to pull real listings for this search.")
            with notice_col2:
                st.markdown("<div style='margin-top:6px;'></div>", unsafe_allow_html=True)
                if st.button(":material/add_card: Buy Credits", use_container_width=True, key=f"{key_prefix}_results_buy_credits_btn"):
                    pricing.render_pricing_dialog()

    best_deal_coc, best_deal_address = None, None
    try:
        _best_deal_points = json.loads(coords_json)
        for p in _best_deal_points:
            m = compute_deal_metrics(float(p["price"]), calc_rent, calc_vacancy_pct, calc_tax_rate,
                                      calc_ins_rate, calc_down_pct, calc_interest, calc_target_yield)
            if best_deal_coc is None or m["coc"] > best_deal_coc:
                best_deal_coc, best_deal_address = m["coc"], p.get("address", "")
    except Exception:
        pass

    if best_deal_coc is not None and best_deal_coc > 0:
        st.markdown(f"""
            <div style='background:var(--radar-success-bg); border:1px solid var(--radar-success-border); border-radius:var(--radar-radius-md); padding:12px 16px; margin-bottom:16px; display:flex; align-items:center; gap:8px;'>
                <span style='color:#065f46;'>{svg_icon("trophy", size=16, color="#065f46")}</span>
                <span style='font-weight:700; color:#065f46;'>Best deal in this scan:</span>
                <span style='color:#065f46;'>{best_deal_coc:.1f}% cash-on-cash return at {best_deal_address}</span>
            </div>
        """, unsafe_allow_html=True)

    _view_options = [":material/grid_view: Properties Only", ":material/splitscreen: Properties + Map",
                      ":material/map: Map Only", ":material/table_chart: Table View"]
    _default_view_index = RESULTS_VIEW_OPTIONS.index(st.session_state.user_settings["default_results_view"])
    view_toggle = st.radio(
        "View", _view_options, index=_default_view_index,
        horizontal=True, key=f"{key_prefix}_scan_results_view_mode", label_visibility="collapsed",
    )

    with st.expander(":material/straighten: Set a distance reference point (optional)"):
        ref_col1, ref_col2 = st.columns([3, 1])
        with ref_col1:
            ref_input = st.text_input("Address to measure distance from (e.g. your workplace, downtown)",
                                       key=f"{key_prefix}_distance_reference_input", placeholder="e.g., 1600 Pennsylvania Ave, Washington DC")
        with ref_col2:
            st.markdown("<div style='margin-top:28px;'></div>", unsafe_allow_html=True)
            if st.button("Set", key=f"{key_prefix}_set_distance_reference_btn", use_container_width=True):
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

    focused_key = f"{key_prefix}_focused_card_index"
    if focused_key not in st.session_state:
        st.session_state[focused_key] = None

    # Quick filter chips - filter the CURRENT scan's results instantly,
    # no new scan needed. Computed from whatever this scan actually
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

                filter_bar_key = f"{key_prefix}_quick_filter_bar"
                with st.container(key=filter_bar_key):
                    st.markdown(f"""
                        <style>
                        div.st-key-{filter_bar_key} {{ max-width: 820px; }}
                        div.st-key-{filter_bar_key} [data-testid="stPopoverButton"] {{
                            border-radius: var(--radar-radius-pill) !important;
                            border: 1.5px solid var(--radar-border) !important;
                            background: var(--radar-surface) !important;
                            font-weight: 600 !important;
                            font-size: 13px !important;
                            padding: 6px 16px !important;
                            min-height: 34px !important;
                            color: var(--radar-navy) !important;
                            box-shadow: var(--radar-shadow-sm);
                        }}
                        div.st-key-{filter_bar_key} [data-testid="stPopoverButton"]:hover {{
                            border-color: var(--radar-primary) !important;
                            color: var(--radar-primary) !important;
                        }}
                        </style>
                    """, unsafe_allow_html=True)

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

                    pc1, pc2, pc3, _ = st.columns([1.7, 1.1, 1.1, 2.1])
                    with pc1:
                        if price_ceiling > price_floor:
                            with st.popover(f":material/attach_money: {price_pill_label}", use_container_width=True):
                                filter_min_price, filter_max_price = st.slider(
                                    "Price range", min_value=price_floor, max_value=price_ceiling,
                                    value=(price_floor, price_ceiling), key=price_range_key,
                                    format="$%d"
                                )
                        else:
                            filter_min_price, filter_max_price = price_floor, price_ceiling
                    with pc2:
                        with st.popover(f":material/bed: {beds_pill_label}", use_container_width=True):
                            if max_beds_available > min_beds_available:
                                filter_min_beds = st.selectbox(
                                    "Min beds", options=list(range(min_beds_available, max_beds_available + 1)),
                                    index=0, key=min_beds_key,
                                    help=f"Every result already has at least {min_beds_available} bed(s), so that option won't change your results."
                                )
                            else:
                                st.caption(f"Every result in this scan has exactly {min_beds_available} bed(s) - nothing to filter.")
                                filter_min_beds = min_beds_available
                    with pc3:
                        with st.popover(f":material/bathtub: {baths_pill_label}", use_container_width=True):
                            if max_baths_available > min_baths_available:
                                filter_min_baths = st.selectbox(
                                    "Min baths", options=list(range(min_baths_available, max_baths_available + 1)),
                                    index=0, key=min_baths_key,
                                    help=f"Every result already has at least {min_baths_available} bath(s), so that option won't change your results."
                                )
                            else:
                                st.caption(f"Every result in this scan has exactly {min_baths_available} bath(s) - nothing to filter.")
                                filter_min_baths = min_baths_available

                    st.markdown("<div style='height:12px;'></div>", unsafe_allow_html=True)

                    grade_defs = [
                        ("excellent", "🟢 Outstanding"),
                        ("average", "🟡 Average"),
                        ("critical", "🔴 Negative Cash Flow"),
                    ]
                    grade_labels = [label for _, label in grade_defs]
                    grade_key_by_label = {label: key for key, label in grade_defs}

                    st.caption("Deal grade - all shown by default, click one to hide it from your results below")
                    picked_grade_labels = st.pills(
                        "Deal grade", grade_labels, selection_mode="multi",
                        default=grade_labels, key=f"{key_prefix}_quick_filter_grades_pills",
                        label_visibility="collapsed",
                    )
                    filter_grades = [grade_key_by_label[label] for label in (picked_grade_labels or [])]
        except Exception:
            pass

    if view_toggle == ":material/grid_view: Properties Only":
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
                                                  calc_ins_rate, calc_down_pct, calc_interest, calc_target_yield)
                        grade_mask.append(m["grade"] in filter_grades)
                    df_listings_grid = df_listings_grid[grade_mask].reset_index(drop=True)

                if df_listings_grid.empty:
                    st.info("No properties match your current filters. Try widening the price range or lowering the min beds.")
                else:
                    row_indices = list(df_listings_grid.index)
                    for pair_start in range(0, len(row_indices), 3):
                        pair_indices = row_indices[pair_start:pair_start + 3]
                        grid_cols = st.columns(3)
                        for slot, idx in enumerate(pair_indices):
                            row_item = df_listings_grid.loc[idx]
                            with grid_cols[slot]:
                                metrics = compute_deal_metrics(
                                    float(row_item["price"]), calc_rent, calc_vacancy_pct, calc_tax_rate,
                                    calc_ins_rate, calc_down_pct, calc_interest, calc_target_yield
                                )
                                is_focused = st.session_state[focused_key] == idx
                                if render_property_card(idx, row_item, metrics, view_mode, f"{key_prefix}_grid_only_card", is_focused,
                                                         st.session_state.user_id, st.session_state.get("distance_reference_point"),
                                                         calc_target_yield,
                                                         {"down_pct": calc_down_pct, "interest": calc_interest, "rent": calc_rent,
                                                          "vacancy": calc_vacancy_pct, "tax_rate": calc_tax_rate, "ins_rate": calc_ins_rate}):
                                    st.session_state[focused_key] = None if is_focused else idx
                                    st.rerun()
            except Exception:
                st.caption("Unable to load property listings for this scan.")

    elif view_toggle == ":material/splitscreen: Properties + Map":
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
                                                  calc_ins_rate, calc_down_pct, calc_interest, calc_target_yield)
                        grade_mask.append(m["grade"] in filter_grades)
                    df_listings_grid = df_listings_grid[grade_mask].reset_index(drop=True)

                with cards_col:
                    if df_listings_grid.empty:
                        st.info("No properties match your current filters. Try widening the price range or lowering the min beds.")
                    st.caption("Click **Focus** on any card to zoom the map to that property. Scroll within the list below to see more.")
                    with st.container(key=scroll_box_key):
                        row_indices = list(df_listings_grid.index)
                        for pair_start in range(0, len(row_indices), 2):
                            pair_indices = row_indices[pair_start:pair_start + 2]
                            grid_cols = st.columns(2)
                            for slot, idx in enumerate(pair_indices):
                                row_item = df_listings_grid.loc[idx]
                                with grid_cols[slot]:
                                    metrics = compute_deal_metrics(
                                        float(row_item["price"]), calc_rent, calc_vacancy_pct, calc_tax_rate,
                                        calc_ins_rate, calc_down_pct, calc_interest, calc_target_yield
                                    )
                                    is_focused = st.session_state[focused_key] == idx
                                    if render_property_card(idx, row_item, metrics, view_mode, f"{key_prefix}_split_card_focus", is_focused,
                                                             st.session_state.user_id, st.session_state.get("distance_reference_point"),
                                                             calc_target_yield,
                                                             {"down_pct": calc_down_pct, "interest": calc_interest, "rent": calc_rent,
                                                              "vacancy": calc_vacancy_pct, "tax_rate": calc_tax_rate, "ins_rate": calc_ins_rate}):
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
                    st.plotly_chart(fig_map, use_container_width=True, key=f"{key_prefix}_scatter_map", config={"displayModeBar": True, "scrollZoom": True})
            except Exception:
                st.caption("Unable to load the map for this scan.")

    elif view_toggle == ":material/map: Map Only":  # full-width map, click a pin to see that property's details
        st.caption("Click any pin to see that property's full details below the map. Nearby properties group into clusters - click a cluster to see what's inside.")
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

                if df_listings_grid.empty:
                    st.info("No properties match your current filters. Try widening the price range or lowering the min beds.")
                else:
                    grades_for_map = []
                    for _, r in df_listings_grid.iterrows():
                        m = compute_deal_metrics(float(r["price"]), calc_rent, calc_vacancy_pct, calc_tax_rate,
                                                  calc_ins_rate, calc_down_pct, calc_interest, calc_target_yield)
                        grades_for_map.append(m["grade"])
                    df_listings_grid["_grade"] = grades_for_map

                    if filter_grades and len(filter_grades) < 3:
                        df_listings_grid = df_listings_grid[df_listings_grid["_grade"].isin(filter_grades)].reset_index(drop=True)

                    if df_listings_grid.empty:
                        st.info("No properties match your current filters. Try widening the price range, lowering the min beds, or including more deal grades.")
                    else:
                        grade_colors = {"excellent": "#10b981", "average": "#f59e0b", "critical": "#ef4444"}

                        cluster_df = build_clustered_map_data(df_listings_grid)
                        # Unclustered pins get a bigger marker than before (was 18px) so a
                        # short price label like "$450K" actually fits and stays legible -
                        # at a glance across the map, not just on hover/click, matching how
                        # Zillow shows price directly on individual (non-clustered) pins.
                        cluster_df["_marker_size"] = cluster_df["count"].apply(lambda c: 30 if c == 1 else min(24 + c * 3, 46))
                        cluster_df["_marker_text"] = cluster_df.apply(
                            lambda row: str(row["count"]) if row["is_cluster"] else _format_price_short(row["price"]), axis=1
                        )

                        fig_full_map = px.scatter_mapbox(
                            cluster_df, lat="latitude", lon="longitude", hover_name="title",
                            hover_data={"address": True, "price": True, "count": True, "latitude": False, "longitude": False},
                            color="grade", color_discrete_map=grade_colors,
                            size="_marker_size", size_max=46, text="_marker_text",
                            zoom=11, center={"lat": df_listings_grid["latitude"].mean(), "lon": df_listings_grid["longitude"].mean()}
                        )
                        fig_full_map.update_traces(textfont=dict(color="white", size=11, family="Arial Black"), textposition="middle center")
                        fig_full_map.update_layout(
                            mapbox_style="open-street-map", margin={"r": 0, "t": 0, "l": 0, "b": 0},
                            height=650, showlegend=False,
                        )

                        map_event = st.plotly_chart(
                            fig_full_map, use_container_width=True, key=f"{key_prefix}_full_map_view_chart",
                            on_select="rerun", selection_mode="points",
                            config={"displayModeBar": True, "scrollZoom": True},
                        )

                        selected_points = map_event.get("selection", {}).get("points", []) if map_event else []
                        if selected_points:
                            point_index = selected_points[0].get("point_index")
                            if point_index is not None and point_index < len(cluster_df):
                                clicked = cluster_df.iloc[point_index]
                                st.markdown("---")
                                if clicked["is_cluster"]:
                                    st.markdown(f"#### :material/location_on: {clicked['count']} properties in this area")
                                    st.caption("Zoom in on the map or narrow your filters above to click an individual property.")
                                    member_rows = df_listings_grid.iloc[clicked["member_indices"]]
                                    summary_df = member_rows[["title", "address", "price", "beds", "baths"]].copy()
                                    summary_df["price"] = summary_df["price"].apply(lambda p: f"${p:,.0f}")
                                    st.dataframe(summary_df, hide_index=True, use_container_width=True, height=len(summary_df) * 35 + 38)
                                else:
                                    st.markdown("#### :material/location_on: Selected Property")
                                    sel_idx = clicked["member_indices"][0]
                                    sel_row = df_listings_grid.iloc[sel_idx]
                                    sel_metrics = compute_deal_metrics(
                                        float(sel_row["price"]), calc_rent, calc_vacancy_pct, calc_tax_rate,
                                        calc_ins_rate, calc_down_pct, calc_interest, calc_target_yield
                                    )
                                    render_property_card(sel_idx, sel_row, sel_metrics, view_mode, f"{key_prefix}_map_view_card", True,
                                                          st.session_state.user_id, st.session_state.get("distance_reference_point"),
                                                          calc_target_yield,
                                                          {"down_pct": calc_down_pct, "interest": calc_interest, "rent": calc_rent,
                                                           "vacancy": calc_vacancy_pct, "tax_rate": calc_tax_rate, "ins_rate": calc_ins_rate})
                        else:
                            st.info("Click a pin above to see that property's price, deal grade, and full details.", icon=":material/lightbulb:")
            except Exception:
                st.caption("Unable to load the map for this scan.")

    else:  # Table View - every matched property as a sortable/filterable spreadsheet-style grid
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
                                                  calc_ins_rate, calc_down_pct, calc_interest, calc_target_yield)
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
                        if st.button(":material/chevron_left: Previous", disabled=table_current_page <= 1, use_container_width=True, key=f"{key_prefix}_table_prev_page_btn"):
                            st.session_state[f"{key_prefix}_table_current_page"] = table_current_page - 1
                            st.session_state[f"{key_prefix}_table_selected_idx"] = None
                            st.rerun()
                    with table_nav2:
                        st.markdown(f"<div style='text-align:center; padding-top:8px; color:var(--radar-text-muted); font-size:13px;'>Page {table_current_page} of {table_total_pages} · {table_total_rows} total properties</div>", unsafe_allow_html=True)
                    with table_nav3:
                        if st.button("Next :material/chevron_right:", disabled=table_current_page >= table_total_pages, use_container_width=True, key=f"{key_prefix}_table_next_page_btn"):
                            st.session_state[f"{key_prefix}_table_current_page"] = table_current_page + 1
                            st.session_state[f"{key_prefix}_table_selected_idx"] = None
                            st.rerun()

                    df_listings_page = df_listings_grid.iloc[(table_current_page - 1) * table_page_size: table_current_page * table_page_size].reset_index(drop=True)

                    grade_emojis = {"excellent": "🟢", "average": "🟡", "critical": "🔴"}
                    table_rows = []
                    for idx, row_item in df_listings_page.iterrows():
                        m = compute_deal_metrics(float(row_item["price"]), calc_rent, calc_vacancy_pct, calc_tax_rate,
                                                  calc_ins_rate, calc_down_pct, calc_interest, calc_target_yield)
                        is_saved = db.is_property_saved(st.session_state.user_id, row_item.get("address", ""))
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
                            "MAO": round(m["mao"], 2),
                            "Save": "★" if is_saved else "☆",
                            "View": ":material/visibility:",
                        })
                    table_df = pd.DataFrame(table_rows)

                    st.dataframe(
                        table_df, use_container_width=True, hide_index=True, height=len(table_df) * 35 + 38,
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
                    if save_click and save_click.get("row") is not None:
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

                    view_click = st.session_state.get(f"{key_prefix}_table_view_click")
                    if view_click and view_click.get("row") is not None:
                        st.session_state[f"{key_prefix}_table_selected_idx"] = view_click["row"]

                    table_selected_idx = st.session_state.get(f"{key_prefix}_table_selected_idx")
                    if table_selected_idx is not None and table_selected_idx < len(df_listings_page):
                        st.markdown("---")
                        st.markdown("#### :material/location_on: Selected Property")
                        sel_row = df_listings_page.iloc[table_selected_idx]
                        sel_metrics = compute_deal_metrics(
                            float(sel_row["price"]), calc_rent, calc_vacancy_pct, calc_tax_rate,
                            calc_ins_rate, calc_down_pct, calc_interest, calc_target_yield
                        )
                        render_property_card(table_selected_idx, sel_row, sel_metrics, view_mode, f"{key_prefix}_table_view_card", True,
                                              st.session_state.user_id, st.session_state.get("distance_reference_point"),
                                              calc_target_yield,
                                              {"down_pct": calc_down_pct, "interest": calc_interest, "rent": calc_rent,
                                               "vacancy": calc_vacancy_pct, "tax_rate": calc_tax_rate, "ins_rate": calc_ins_rate})
            except Exception:
                st.caption("Unable to load the table for this scan.")

    # ---- PRO MODE ONLY: full underwriting tab breakdown ----
    if view_mode == "Pro" and coords_json:
        try:
            parsed_points = json.loads(coords_json)
            df_listings_grid = pd.DataFrame(parsed_points)

            st.markdown("---")
            st.markdown("### :material/apartment: Full Underwriting Breakdown")
            st.caption("Click a property's tab below to see its full underwriting numbers and deal grade.")

            property_titles_list = [row_item["title"] for idx, row_item in df_listings_grid.iterrows()]

            if property_titles_list:
                asset_sub_tabs = st.tabs(property_titles_list)

                for idx, row_item in df_listings_grid.iterrows():
                    prop_title = row_item["title"]
                    prop_price = float(row_item["price"])
                    prop_address = row_item["address"]

                    metrics = compute_deal_metrics(prop_price, calc_rent, calc_vacancy_pct, calc_tax_rate,
                                                    calc_ins_rate, calc_down_pct, calc_interest, calc_target_yield)

                    with asset_sub_tabs[idx]:
                        col_b1, col_b2 = st.columns([2.5, 1])
                        with col_b1:
                            st.markdown(f"#### :material/location_on: {prop_title}")
                            st.caption(f"Address: {prop_address}")
                        with col_b2:
                            st.markdown("<div style='margin-top:10px;'></div>", unsafe_allow_html=True)
                            st.markdown(render_deal_badge(metrics["grade"]), unsafe_allow_html=True)

                        st.markdown("---")
                        col_mao1, col_mao2 = st.columns([1.5, 2])
                        with col_mao1:
                            st.metric(label="Maximum Allowable Offer (MAO)", value=f"${metrics['mao']:,.2f}",
                                      delta=f"-${metrics['mao_delta']:,.2f}" if metrics['mao_delta'] > 0 else None,
                                      delta_color="inverse")
                        with col_mao2:
                            st.info(f"**Suggested Offer:** This price targets a **{calc_target_yield:.2f}% cash-on-cash return**.", icon=":material/lightbulb:")
                        st.markdown("---")

                        c1, c2, c3, c4 = st.columns(4)
                        with c1:
                            st.metric(label="Purchase Price", value=f"${prop_price:,.2f}")
                            st.metric(label="Cap Rate", value=f"{metrics['cap_rate']:.2f}%")
                        with c2:
                            st.metric(label="Down Payment", value=f"${metrics['down_amt']:,.2f}")
                            st.metric(label="Cash-on-Cash", value=f"{metrics['coc']:.2f}%")
                        with c3:
                            st.metric(label="Annual NOI", value=f"${metrics['noi']:,.2f}")
                            st.metric(label="Loan Amount", value=f"${metrics['loan_amt']:,.2f}")
                        with c4:
                            st.metric(label="Annual Cash Flow", value=f"${metrics['cashflow']:,.2f}")
                            st.metric(label="Annual Debt Expense", value=f"${metrics['a_debt']:,.2f}")
        except Exception:
            pass

    st.markdown("<br>", unsafe_allow_html=True)
    pdf_data_uri = generate_pdf_download_link(profile_name, report_body)
    st.markdown(f"""
        <a href="{pdf_data_uri}" download="{pdf_filename_prefix}_{profile_name.replace(' ', '_')}.html" style="text-decoration: none;">
            <div style="background-color: var(--radar-primary); color: white; text-align: center; padding: 12px; border-radius: var(--radar-radius-sm); font-weight: 500; cursor: pointer; margin-top: 15px; margin-bottom: 20px; display:flex; align-items:center; justify-content:center; gap:6px;">
                {svg_icon("download", size=15, color="white")} {pdf_button_label}
            </div>
        </a>
    """, unsafe_allow_html=True)


def _render_car_scan_results(car_listings, profile_name):
    st.markdown("---")
    st.info(
        ":material/science: **Preview category** - these are mock listings, not a live feed. "
        "Deal grading here compares each listing's price to an estimated market value based on its year, mileage, and model.",
    )
    st.markdown(f"### :material/directions_car: {profile_name} — {len(car_listings)} {'Match' if len(car_listings) == 1 else 'Matches'}")

    best = max(car_listings, key=lambda c: car_engine.compute_car_deal_metrics(c["price"], c["market_value"])["pct_below_market"])
    best_metrics = car_engine.compute_car_deal_metrics(best["price"], best["market_value"])
    if best_metrics["pct_below_market"] > 0:
        st.markdown(f"""
            <div style='background:var(--radar-success-bg); border:1px solid var(--radar-success-border); border-radius:var(--radar-radius-md); padding:12px 16px; margin-bottom:16px; display:flex; align-items:center; gap:8px;'>
                <span style='color:#065f46;'>{svg_icon("trophy", size=16, color="#065f46")}</span>
                <span style='font-weight:700; color:#065f46;'>Best deal in this scan:</span>
                <span style='color:#065f46;'>{best_metrics['pct_below_market']:.0f}% below market on the {best['year']} {best['make']} {best['model']}</span>
            </div>
        """, unsafe_allow_html=True)

    row_indices = list(range(len(car_listings)))
    for pair_start in range(0, len(row_indices), 3):
        pair_indices = row_indices[pair_start:pair_start + 3]
        grid_cols = st.columns(3)
        for slot, idx in enumerate(pair_indices):
            listing = car_listings[idx]
            metrics = car_engine.compute_car_deal_metrics(listing["price"], listing["market_value"])
            with grid_cols[slot]:
                render_car_card(idx, listing, metrics, "car_scan")


def _render_execute_scan_tab(raw_profiles, view_mode, calc_rent, calc_vacancy_pct, calc_tax_rate, calc_ins_rate, calc_down_pct, calc_interest, calc_target_yield):
    if raw_profiles:
        if st.session_state.get("active_scanned_category") == "cars" and st.session_state.get("active_scanned_car_listings"):
            _render_car_scan_results(
                st.session_state.active_scanned_car_listings,
                st.session_state.get("active_scanned_profile", "Your Search"),
            )
        elif "active_scanned_report" in st.session_state and st.session_state.active_scanned_report:
            _render_scan_results(
                st.session_state.active_scanned_report,
                st.session_state.get("active_scanned_profile", "Your Search"),
                st.session_state.active_scanned_coords,
                "live", view_mode, calc_rent, calc_vacancy_pct, calc_tax_rate, calc_ins_rate,
                calc_down_pct, calc_interest, calc_target_yield,
                show_preview_notice=True, pdf_button_label="Export Live Scan Report to Document PDF / Print",
                pdf_filename_prefix="DealRadar_Report",
            )
    else:
        st.info("No searches set up yet. Head to 'Manage Hunt Criteria' to create one.")


def _render_history_tab(view_mode, calc_rent, calc_vacancy_pct, calc_tax_rate, calc_ins_rate, calc_down_pct, calc_interest, calc_target_yield):
    st.markdown(f"""
        <div style='display:flex; align-items:center; gap:10px; margin-bottom:2px;'>
            {svg_icon("clock", size=20, color="var(--radar-primary)")}
            <span style='font-weight:700; font-size:var(--radar-text-xl); color:var(--radar-navy);'>Historical Scans Registry Archive</span>
        </div>
    """, unsafe_allow_html=True)
    st.caption("Review any past scan for free - browsing your history doesn't use any credits.")

    history_rows = db.get_history_logs(st.session_state.user_id)
    if history_rows:
        df_hist = pd.DataFrame(history_rows, columns=["Log ID", "Profile Name", "Geographic Location", "Generation Date", "Hidden Raw Content", "Hidden Coordinates"])
        # Stored as UTC (SQLite's CURRENT_TIMESTAMP) - convert to this
        # user's own timezone (Settings) before it's ever displayed, so
        # a scan from "10 minutes ago" doesn't read like it happened at
        # a confusing hour this morning.
        _user_tz = st.session_state.user_settings.get("timezone")
        df_hist["Generation Date"] = df_hist["Generation Date"].apply(lambda d: format_local_datetime(d, _user_tz))
        search_hist = st.text_input(":material/search: Search History Log", placeholder="Start typing...", key="hist_search_field_unique")
        if search_hist:
            df_hist = df_hist[df_hist["Profile Name"].str.contains(search_hist, case=False, na=False)]

        with st.expander(":material/delete_sweep: Bulk cleanup - delete old logs"):
            bulk_col1, bulk_col2 = st.columns([2, 1])
            with bulk_col1:
                bulk_days = st.number_input("Delete every log older than this many days", min_value=1, value=90, step=1, key="hist_bulk_days")
            with bulk_col2:
                st.markdown("<div style='margin-top:28px;'></div>", unsafe_allow_html=True)
                if st.button(":material/delete_sweep: Preview & Delete", use_container_width=True, key="hist_bulk_delete_trigger"):
                    st.session_state.hist_bulk_pending = bulk_days

            if st.session_state.get("hist_bulk_pending"):
                pending_days = st.session_state.hist_bulk_pending
                cutoff_label = (datetime.now() - timedelta(days=int(pending_days))).strftime("%B %d, %Y")
                st.warning(f"Delete every scan log from before **{cutoff_label}** ({int(pending_days)}+ days old)? This can't be undone.")
                bulk_confirm_col, bulk_cancel_col = st.columns(2)
                with bulk_confirm_col:
                    if st.button(":material/delete_sweep: Confirm Bulk Delete", type="primary", use_container_width=True, key="hist_bulk_confirm_btn"):
                        deleted_count = db.delete_history_logs_older_than(st.session_state.user_id, pending_days)
                        st.session_state.hist_bulk_pending = None
                        st.toast(f"Deleted {deleted_count} old log{'s' if deleted_count != 1 else ''}.")
                        st.rerun()
                with bulk_cancel_col:
                    if st.button("Cancel", use_container_width=True, key="hist_bulk_cancel_btn"):
                        st.session_state.hist_bulk_pending = None
                        st.rerun()

        page_size = st.selectbox("Rows per page", [10, 25, 50, 100], index=1, key="hist_page_size")
        total_rows = len(df_hist)
        total_pages = max(1, (total_rows + page_size - 1) // page_size)
        current_page = min(st.session_state.get("hist_current_page", 1), total_pages)

        page_nav1, page_nav2, page_nav3 = st.columns([1, 2, 1])
        with page_nav1:
            if st.button(":material/chevron_left: Previous", disabled=current_page <= 1, use_container_width=True, key="hist_prev_page_btn"):
                st.session_state.hist_current_page = current_page - 1
                st.rerun()
        with page_nav2:
            st.markdown(f"<div style='text-align:center; padding-top:8px; color:var(--radar-text-muted); font-size:13px;'>Page {current_page} of {total_pages} · {total_rows} total scans</div>", unsafe_allow_html=True)
        with page_nav3:
            if st.button("Next :material/chevron_right:", disabled=current_page >= total_pages, use_container_width=True, key="hist_next_page_btn"):
                st.session_state.hist_current_page = current_page + 1
                st.rerun()

        df_hist_page = df_hist.iloc[(current_page - 1) * page_size: current_page * page_size]

        def _summarize_history_row(coords_raw):
            """Matches / price range / deal-grade breakdown for one
            history row - computed from the archived listing snapshot
            using the CURRENT underwriting assumptions (same sidebar
            inputs the results view itself uses), not whatever
            assumptions were active when the scan originally ran."""
            try:
                pts = json.loads(coords_raw)
                if not pts:
                    return "-", "-", "-"
                prices = [float(p["price"]) for p in pts]
                price_range = (_format_price_short(min(prices)) if min(prices) == max(prices)
                               else f"{_format_price_short(min(prices))}–{_format_price_short(max(prices))}")
                grade_counts = {"excellent": 0, "average": 0, "critical": 0}
                for p in pts:
                    m = compute_deal_metrics(float(p["price"]), calc_rent, calc_vacancy_pct, calc_tax_rate,
                                              calc_ins_rate, calc_down_pct, calc_interest, calc_target_yield)
                    grade_counts[m["grade"]] += 1
                grades_str = f"🟢{grade_counts['excellent']} 🟡{grade_counts['average']} 🔴{grade_counts['critical']}"
                return str(len(pts)), price_range, grades_str
            except Exception:
                return "-", "-", "-"

        summaries = df_hist_page["Hidden Coordinates"].apply(_summarize_history_row)
        df_hist_display = df_hist_page[["Profile Name", "Geographic Location"]].copy()
        df_hist_display["Matches"] = [s[0] for s in summaries]
        df_hist_display["Price Range"] = [s[1] for s in summaries]
        df_hist_display["Grades (🟢/🟡/🔴)"] = [s[2] for s in summaries]
        df_hist_display["Generation Date"] = df_hist_page["Generation Date"]
        df_hist_display["Delete"] = ":material/delete:"
        selected_log_grid = st.dataframe(
            df_hist_display, use_container_width=True, hide_index=True, on_select="rerun", selection_mode="single-row", key="history_log_grid",
            height=len(df_hist_display) * 35 + 38,
            column_config={
                "Matches": st.column_config.TextColumn(width="small"),
                "Price Range": st.column_config.TextColumn(width="small"),
                "Grades (🟢/🟡/🔴)": st.column_config.TextColumn(width="small"),
                "Delete": st.column_config.ButtonColumn("", width="small", type="tertiary", key="hist_delete_btn_click"),
            },
        )
        selected_log_indices = selected_log_grid.get("selection", {}).get("rows", [])

        delete_click = st.session_state.get("hist_delete_btn_click")
        if delete_click and delete_click.get("row") is not None:
            st.session_state.hist_pending_delete = {
                "id": df_hist_page.iloc[delete_click["row"]]["Log ID"],
                "name": df_hist_page.iloc[delete_click["row"]]["Profile Name"],
            }

        if st.session_state.get("hist_pending_delete"):
            pending = st.session_state.hist_pending_delete
            st.warning(f"Delete **{pending['name']}** from your scan history? This can't be undone.")
            confirm_col, cancel_col = st.columns(2)
            with confirm_col:
                if st.button(":material/delete: Confirm Delete", type="primary", use_container_width=True, key="hist_confirm_delete_btn"):
                    db.delete_history_log(st.session_state.user_id, pending["id"])
                    st.session_state.hist_pending_delete = None
                    st.toast("Removed from your scan history.")
                    st.rerun()
            with cancel_col:
                if st.button("Cancel", use_container_width=True, key="hist_cancel_delete_btn"):
                    st.session_state.hist_pending_delete = None
                    st.rerun()

        if selected_log_indices:
            target_log_row_idx = selected_log_indices[0]

            archived_log_id = df_hist_page.iloc[target_log_row_idx]["Log ID"]
            archived_report_body = str(df_hist_page.iloc[target_log_row_idx]["Hidden Raw Content"])
            archived_report_name = str(df_hist_page.iloc[target_log_row_idx]["Profile Name"])
            archived_coords_raw = str(df_hist_page.iloc[target_log_row_idx]["Hidden Coordinates"])

            st.markdown("---")
            info_col, delete_col = st.columns([5, 1])
            with info_col:
                st.info(f"Viewing Historical Saved Archive Record: **{archived_report_name}**")
            with delete_col:
                st.markdown("<div style='margin-top:6px;'></div>", unsafe_allow_html=True)
                if st.button(":material/delete: Remove", key=f"delete_history_{archived_log_id}", use_container_width=True):
                    db.delete_history_log(st.session_state.user_id, archived_log_id)
                    st.toast("Removed from your scan history.")
                    st.rerun()

            _render_scan_results(
                archived_report_body, archived_report_name, archived_coords_raw,
                f"hist_{archived_log_id}", view_mode, calc_rent, calc_vacancy_pct, calc_tax_rate, calc_ins_rate,
                calc_down_pct, calc_interest, calc_target_yield,
                show_preview_notice=False, pdf_button_label="Export Archived Report to Document PDF / Print",
                pdf_filename_prefix="DealRadar_Archive",
            )
        else:
            st.info("Click any row above to view that scan's full report.", icon=":material/lightbulb:")
    else:
        render_empty_state(
            "clock", "No scans yet",
            "Once you run a search, every scan gets saved here automatically - free to browse back through anytime, no credits used.",
        )


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
                    calc_ins_rate, calc_down_pct, calc_interest, calc_target_yield
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


def render_analytics_dashboard():
    # Apply the user's saved default distance reference point (Settings)
    # once per session, only if they haven't already set/cleared one during
    # this session - a real geocode call, so it's guarded to run at most
    # once rather than on every rerun.
    if not st.session_state.get("_default_reference_point_checked"):
        st.session_state._default_reference_point_checked = True
        default_ref_address = st.session_state.user_settings.get("default_reference_address")
        if default_ref_address and not st.session_state.get("distance_reference_point"):
            geo_result = engine.validate_and_geocode_location(default_ref_address)
            if geo_result:
                st.session_state.distance_reference_point = {
                    "label": default_ref_address, "latitude": geo_result["latitude"], "longitude": geo_result["longitude"]
                }

    active_category = st.session_state.get("active_category", "real_estate")
    raw_profiles = db.get_all_reports(st.session_state.user_id, category=active_category)

    # Apply a pending quick-access chip click to the selectbox's own widget
    # state before that widget is instantiated below. Setting the widget's
    # session_state key from inside the chip button's own handler doesn't
    # work - by the time that handler runs, the selectbox has already been
    # instantiated earlier in that same script run, and Streamlit raises
    # "cannot be modified after the widget ... is instantiated" for that.
    # Doing it here, before _render_scan_action() creates the selectbox,
    # avoids that restriction entirely.
    pending_profile = st.session_state.get("dashboard_quick_selected_profile")
    if pending_profile in raw_profiles and st.session_state.get("scan_profile_selectbox") != pending_profile:
        st.session_state.scan_profile_selectbox = pending_profile

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
                    except Exception:
                        default_sidebar_price = 500000
                else:
                    default_sidebar_price = 500000

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
                                                         calc_ins_rate, calc_down_pct, calc_interest, calc_target_yield)
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
            # _render_execute_scan_tab and friends take them
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
                                          calc_ins_rate, calc_down_pct, calc_interest, calc_target_yield)
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
        except Exception:
            pass

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
        div.st-key-dashboard_action_card [data-testid="stWidgetLabel"] p {
            font-size: 15px !important;
            font-weight: 600 !important;
        }
        div.st-key-dashboard_action_card [data-baseweb="select"] * {
            font-size: 15px !important;
        }
        div.st-key-dashboard_action_card [data-baseweb="select"] > div {
            min-height: 44px !important;
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

    _hero_subtitle = ("Scan your active car searches and evaluate pipeline vehicle deals" if active_category == "cars"
                       else "Scan your active targets and evaluate pipeline real estate returns")
    _hero_icon = "car" if active_category == "cars" else "radar"

    with st.container(key="dashboard_hero"):
        st.markdown(f"""
            <div style='text-align:center; max-width:760px; margin:0 auto 24px auto;'>
                <div style='display:flex; align-items:center; justify-content:center; gap:14px; margin-bottom:10px;'>
                    <div style='background: var(--radar-gradient-brand); width: 48px; height: 48px;
                                border-radius: var(--radar-radius-md); display:flex; align-items:center; justify-content:center; flex-shrink:0;'>
                        {svg_icon(_hero_icon, size=24, color="white")}
                    </div>
                    <div style='font-size:32px; font-weight:800; color:white; line-height:1.2;'>Analytics Dashboard</div>
                </div>
                <div style='font-size:16px; color:var(--radar-text-on-dark-muted);'>{_hero_subtitle}</div>
            </div>
        """, unsafe_allow_html=True)

        with st.container(key="dashboard_action_card"):
            if raw_profiles:
                _render_scan_action(raw_profiles)
            else:
                render_empty_state(
                    "crosshair", "Set up your first search",
                    "Tell us what you're looking for - target city, budget, and property type - and we'll scan for matching deals whenever you like.",
                    cta_label="Create Your First Search",
                    cta_page="Manage Car Search Criteria" if active_category == "cars" else "Manage Hunt Criteria",
                )

        if len(raw_profiles) > 1:
            st.markdown("<div style='text-align:center; margin-top:14px;'>", unsafe_allow_html=True)
            st.markdown("<span style='color:var(--radar-text-on-dark-muted); font-size:14px; font-weight:600; margin-right:8px;'>Quick access:</span>", unsafe_allow_html=True)
            quick_cols = st.columns([1] * min(len(raw_profiles), 5) + [3])
            for i, profile_name in enumerate(raw_profiles[:5]):
                with quick_cols[i]:
                    with st.container(key=f"dashboard_quick_chip_{i}"):
                        if st.button(profile_name, key=f"dashboard_quick_btn_{i}", use_container_width=True):
                            st.session_state.dashboard_quick_selected_profile = profile_name
                            st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("<div style='height:20px;'></div>", unsafe_allow_html=True)
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

    st.markdown("<div style='height:32px;'></div>", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    nav_col, content_col = st.columns([1, 4])
    with nav_col:
        active_section = render_side_nav(
            [
                {"label": "Execute Live Scan", "icon": ":material/rocket_launch:"},
                {"label": "Scanned Reports History Log", "icon": ":material/history:"},
                {"label": "Saved Properties", "icon": ":material/star:"},
            ],
            key_prefix="scan_results_nav",
        )

    with content_col:
        if active_section == "Execute Live Scan":
            _render_execute_scan_tab(raw_profiles, view_mode, calc_rent, calc_vacancy_pct, calc_tax_rate, calc_ins_rate, calc_down_pct, calc_interest, calc_target_yield)
        elif active_section == "Scanned Reports History Log":
            _render_history_tab(view_mode, calc_rent, calc_vacancy_pct, calc_tax_rate, calc_ins_rate, calc_down_pct, calc_interest, calc_target_yield)
        else:
            _render_saved_properties_tab(view_mode, calc_rent, calc_vacancy_pct, calc_tax_rate, calc_ins_rate, calc_down_pct, calc_interest, calc_target_yield)
