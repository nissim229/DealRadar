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


def _safe_hoa(source):
    """hoa_monthly, defaulting to 0 - the 0-default (not None) is what
    every compute_deal_metrics call site here expects. Missing-value
    normalization itself lives in data_utils.clean_value."""
    val = clean_value(source.get("hoa_monthly"))
    if val is None:
        return 0
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0


def _format_relative_time(timestamp_str):
    """'Saved 3 hours ago' - deliberately a freshness note, not a claim
    about whether the listing is still active - this app has no live
    MLS/IDX feed to verify that, so the honest signal to show is how long
    ago the snapshot was taken, matching how the major listing sites
    handle results they can't re-verify in real time either. Bucketing
    itself lives in data_utils.relative_time; this just owns the "Saved"
    framing and the on-parse-failure fallback shape."""
    try:
        datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return f"Saved {timestamp_str}"
    return f"Saved {relative_time(timestamp_str)}"


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
        <div class='dealradar-stat-card' style='background:var(--radar-surface); border:1px solid var(--radar-border); border-radius:var(--radar-radius-md); padding:10px 14px;
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
    st.caption("Full results with every match are below the search form.")


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
    st.caption("Full results with map and filters are below the search form.")


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


def _render_scan_search_form(is_guest=False):
    """Ad-hoc search form for a real-estate scan - mirrors car_search.py's
    own pattern (search runs immediately, no saved profile required first)
    instead of requiring a "Manage Searches" profile to exist before
    scanning at all, per real feedback that a separate nav item just to
    set up a search before you could ever run one was confusing. Used
    identically for both a real session and a guest preview - the same
    rich location picker either way, matching the "almost identical to
    the real page" parity guest mode is built around; only what happens
    after Run Live Scan differs (see the caller). Returns criteria only -
    the Run Live Scan/Test Scan/Buy Credits buttons live in
    _render_scan_action_buttons instead, called separately alongside the
    compact results strip rather than as part of the form itself (see
    [[hero_redesign_compact_results]])."""
    selected_state, selected_cities, zip_code = render_compact_location_fields("scan_form")

    prop_col, price_col, beds_col = st.columns(3)
    with prop_col:
        property_type = st.selectbox("Property Type", ["Single Family Home", "Condo", "Multi-Family", "Townhouse"],
                                      key="scan_form_property_type")
    with price_col:
        max_price = st.number_input("Maximum Budget ($)", min_value=0, value=750000, step=25000, key="scan_form_max_price")
    with beds_col:
        min_beds = st.number_input("Minimum Bedrooms", min_value=0, value=3, step=1, key="scan_form_min_beds")

    return {
        "location": location_display_label(selected_state, selected_cities, zip_code),
        "property_type": property_type, "max_price": max_price, "min_beds": min_beds,
        "state": selected_state, "selected_cities": selected_cities, "zip_code": zip_code,
    }


def _render_scan_action_buttons(is_guest=False):
    """The Run Live Scan / Run Test Scan / Buy Credits buttons - split out
    of the search form so they can sit beside the compact results strip
    (small property chips + Quick Access) in one row instead of the form
    fields' own full-width row. Returns (run_clicked, test_clicked)."""
    # Final "Secure Sector" treatment (user-approved after prototyping
    # separately as a standalone artifact) - dark bg, faint border at
    # rest, and on hover: border/glow brighten, an 8px grid overlay
    # reveals, and a 128px conic-gradient "radar sweep" behind the
    # icon spins continuously. Streamlit's <button> has no child spans
    # to hang the grid/sweep layers on (unlike the raw HTML artifact),
    # so both are built as ::before (grid) / ::after (sweep)
    # pseudo-elements instead - only 2 available, so this button
    # can't also carry the earlier prototype's corner-accent/scanline
    # (dropped in favor of the approved design). Colors are the
    # artifact's own cyan (#22d3ee), not DealRadar's usual blue - a
    # first pass here quietly swapped to the app's blue and missed
    # that the approved version was cyan. font-weight:900 also needs
    # Work Sans' 900 file actually loaded (design_tokens.py's Google
    # Fonts link only pulled 400/500/600 before) or the browser just
    # fake-bolds a lighter weight instead of true black.
    st.markdown("""
        <style>
        div.st-key-run_scan_btn_glow button[kind="primary"] {
            position: relative !important;
            background: var(--radar-navy) !important;
            border: 1px solid rgba(var(--radar-accent-rgb), 0.2) !important;
            border-radius: 8px !important;
            color: var(--radar-accent) !important;
            overflow: hidden !important;
            text-transform: uppercase !important;
            letter-spacing: 0.05em !important;
            font-weight: 900 !important;
            transition: border-color 0.3s ease, box-shadow 0.3s ease !important;
        }
        div.st-key-run_scan_btn_glow button[kind="primary"] p,
        div.st-key-run_scan_btn_glow button[kind="primary"] span {
            color: var(--radar-accent) !important;
            font-weight: 900 !important;
            position: relative !important;
            z-index: 10 !important;
        }
        /* Grid overlay - hidden at rest, revealed on hover */
        div.st-key-run_scan_btn_glow button[kind="primary"]::before {
            content: "" !important; position: absolute !important; inset: 0 !important;
            z-index: 1 !important; opacity: 0 !important;
            transition: opacity 0.3s ease !important;
            background-image:
                repeating-linear-gradient(0deg, rgba(var(--radar-accent-rgb), 0.18) 0 1px, transparent 1px 8px),
                repeating-linear-gradient(90deg, rgba(var(--radar-accent-rgb), 0.18) 0 1px, transparent 1px 8px) !important;
        }
        /* Radar sweep - centered circle behind the icon/label, spins on hover */
        div.st-key-run_scan_btn_glow button[kind="primary"]::after {
            content: "" !important; position: absolute !important;
            top: 50% !important; left: 50% !important;
            width: 128px !important; height: 128px !important;
            border-radius: 50% !important;
            transform: translate(-50%, -50%) !important;
            z-index: 1 !important; opacity: 0 !important;
            background: conic-gradient(from 0deg, transparent 50%, rgba(var(--radar-accent-rgb), 0.25) 100%) !important;
            transition: opacity 0.3s ease !important;
        }
        div.st-key-run_scan_btn_glow button[kind="primary"]:hover {
            border-color: var(--radar-accent) !important;
            box-shadow: 0 0 30px rgba(var(--radar-accent-rgb), 0.3) !important;
        }
        div.st-key-run_scan_btn_glow button[kind="primary"]:hover::before {
            opacity: 1 !important;
        }
        div.st-key-run_scan_btn_glow button[kind="primary"]:hover::after {
            opacity: 1 !important;
            animation: dealradar-sweep 2.5s linear infinite !important;
        }
        @keyframes dealradar-sweep {
            to { transform: translate(-50%, -50%) rotate(360deg); }
        }
        </style>
    """, unsafe_allow_html=True)

    # Scanning itself is never blocked - a user out of credits still
    # gets a full, useful preview scan (sample data), so they can see
    # what the tool does before ever paying. Credits only decide
    # whether THIS scan pulls real market data instead of a preview.
    # Stacked vertically, not 3 side-by-side columns, since this now
    # shares its row with the compact results strip instead of getting
    # the form's own full width.
    with st.container(key="run_scan_btn_glow"):
        run_clicked = st.button(":material/travel_explore: Run Live Scan", type="primary", use_container_width=True, key="run_scan_btn")
    test_clicked = False
    # Staff-only (any of the 3 tiers - see roles.py): forces mock/sample
    # data regardless of role or credits, so staff can exercise the UI
    # (new views, filters, pagination...) without burning real RentCast
    # quota - previously the only way to get preview data as staff was
    # to hand-edit a test account's credits to 0, since being staff
    # always granted allow_live=True.
    if roles.is_staff(st.session_state.user_role):
        test_clicked = st.button(":material/science: Run Test Scan", use_container_width=True, key="run_test_scan_btn",
                                  help="Uses mock/sample data - doesn't spend real RentCast quota.")
    if not is_guest and st.session_state.user_credits <= 0 and not roles.is_admin_or_above(st.session_state.user_role):
        if st.button(":material/add_card: Buy Credits", use_container_width=True, key="buy_credits_trigger_btn"):
            pricing.render_pricing_dialog()

    return run_clicked, test_clicked


# (state, city) pairs, not free text - each must be a real curated city in
# location_data.py so the location picker's own map/coords resolution
# handles them identically to a manually-picked one. Used for the guest
# preview's quick-search chips and its default first-load search.
GUEST_QUICK_SEARCH_CITIES = [
    ("Colorado", "Denver"), ("Texas", "Austin"), ("Florida", "Miami"), ("Colorado", "Boulder"),
]


def _render_mini_results_strip(coords_json, calc_rent, calc_vacancy_pct, calc_tax_rate, calc_ins_rate,
                                calc_down_pct, calc_interest, calc_target_yield, key_prefix, max_cards=5):
    """A small, right-aligned row of property chips shown beside the Run
    Live Scan button once a scan has results - "see properties without
    scrolling" taken further still: not a row below the form, a glance
    right next to the button that produced them. Deliberately only the
    top few by cash-on-cash return, not the full result set - the
    complete list, map, filters, and written report are one click away
    via "View Full Results" below the map (see [[hero_redesign_compact_results]]),
    not crammed in here too. Click a chip to open the same floating
    detail dialog every other card in the app uses."""
    if not coords_json:
        return
    try:
        points = json.loads(coords_json)
    except Exception:
        return
    if not points:
        return

    scored = []
    for p in points:
        m = compute_deal_metrics(float(p["price"]), calc_rent, calc_vacancy_pct, calc_tax_rate,
                                  calc_ins_rate, calc_down_pct, calc_interest, calc_target_yield,
                                  hoa_monthly=_safe_hoa(p))
        scored.append((p, m))
    scored.sort(key=lambda pm: pm[1]["coc"], reverse=True)
    top = scored[:max_cards]

    grade_emojis = {"excellent": "🟢", "average": "🟡", "critical": "🔴"}
    st.markdown(f"""
        <style>
        /* Each st.container(key=...) call made inside this outer
        container becomes its own direct-child wrapper div - Streamlit's
        default flex-direction:column on the outer is what stacks them
        vertically; overriding it to row here is what actually lays the
        chips out side by side (confirmed live via computed styles, not
        guessed - the outer key-classed div itself is the real flex
        parent, each chip's own wrapper is just one of its several direct
        children, not nested one level deeper). */
        div.st-key-{key_prefix}_mini_strip {{
            display: flex !important; flex-direction: row !important;
            flex-wrap: wrap !important; justify-content: flex-end !important; gap: 6px !important;
        }}
        /* Each st.container() call's own direct-child wrapper still
        defaults to Streamlit's normal full-width single-column sizing,
        which forces flex-wrap to push every next chip onto its own line
        even though the row above is correctly flex-direction:row -
        confirmed live (computed width equaled the whole row's width
        until this was added). Has to be targeted separately from the
        grandchild rule below since it's an anonymous wrapper div with no
        stable class of its own - `> div` reaches it by position instead. */
        div.st-key-{key_prefix}_mini_strip > div {{
            flex: none !important; width: fit-content !important;
        }}
        div[class*="st-key-{key_prefix}_mini_chip_"] {{
            flex: none !important; width: fit-content !important;
        }}
        div[class*="st-key-{key_prefix}_mini_chip_"] button {{
            font-size: 12px !important; font-weight: 600 !important;
            padding: 5px 12px !important; min-height: 0 !important;
            border-radius: var(--radar-radius-pill) !important; white-space: nowrap !important;
        }}
        </style>
    """, unsafe_allow_html=True)

    with st.container(key=f"{key_prefix}_mini_strip"):
        for idx, (p, m) in enumerate(top):
            street = (p.get("address", "") or p.get("title", "Property")).split(",")[0]
            label = f"{grade_emojis.get(m['grade'], '')} {_format_price_short(p['price'])} · {street}"
            with st.container(key=f"{key_prefix}_mini_chip_{idx}"):
                if st.button(label, key=f"{key_prefix}_mini_chip_btn_{idx}"):
                    st.session_state.property_dialog_ctx = {
                        "row_item": p, "metrics": m, "address": p.get("address", ""),
                        "user_id": st.session_state.user_id, "reference_point": st.session_state.get("distance_reference_point"),
                        "calc_target_yield": calc_target_yield,
                        "current_assumptions": {"down_pct": calc_down_pct, "interest": calc_interest, "rent": calc_rent,
                                                 "vacancy": calc_vacancy_pct, "tax_rate": calc_tax_rate, "ins_rate": calc_ins_rate},
                        "key_prefix": f"{key_prefix}_mini", "idx": idx,
                    }
                    render_property_detail_dialog()


def _build_coord_list(raw_listings_data):
    """Turns raw listing dicts (from RentCast or the mock generator) into
    the reduced, hand-picked field set that actually survives into
    history/reload and every card-rendering/grading code path downstream
    (see [[rentcast_raw_data_and_hoa]] for why this, not the raw listing
    itself, is the real choke point). Shared between a real scan
    (_execute_scan) and the guest ad-hoc demo scan below so both build
    results in the identical shape."""
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
                # Everything else RentCast (or the mock generator, for
                # parity) provides that this app wasn't persisting
                # before - HOA specifically so it can factor into
                # compute_deal_metrics's grading, the rest so the
                # "Full Details" section on the property card has
                # something real to show instead of just re-deriving
                # from the summary fields above. This dict (not
                # `listing` itself) is what actually survives into
                # history/reload, so a field missing here is a field
                # that's gone the moment this scan isn't the active one.
                "hoa_monthly": listing.get("hoa_monthly"),
                "year_built": listing.get("year_built"),
                "lot_size": listing.get("lot_size"),
                "days_on_market": listing.get("days_on_market"),
                "listed_date": listing.get("listed_date"),
                "listing_type": listing.get("listing_type"),
                "status": listing.get("status"),
                "county": listing.get("county"),
                "state": listing.get("state"),
                "zip_code": listing.get("zip_code"),
                "listing_agent_name": listing.get("listing_agent_name"),
                "listing_agent_phone": listing.get("listing_agent_phone"),
                "listing_office_name": listing.get("listing_office_name"),
                "listing_office_phone": listing.get("listing_office_phone"),
                "listing_office_email": listing.get("listing_office_email"),
                "rentcast_raw": listing.get("rentcast_raw"),
            })
    return coord_list


def _fetch_listings_for_criteria(criteria, allow_live, user_id=None):
    """Resolves a search's criteria (state + specific cities OR a ZIP OR
    "any city in this state", from the location picker) into actual
    listings - shared by the real ad-hoc scan path and the guest demo
    path below, which differ only in allow_live and what happens to the
    result afterward. state=None is the legacy shape (a saved search from
    before the state/city picker existed, resolved by free-text location
    instead) - preserved so those old saved searches still work."""
    location = criteria["location"]
    property_type = criteria["property_type"]
    max_price = criteria["max_price"]
    min_beds = criteria["min_beds"]
    state = criteria.get("state")

    if state is None:
        return engine.fetch_live_listings(location, property_type, max_price, min_beds, allow_live=allow_live, user_id=user_id)

    selected_cities = criteria.get("selected_cities") or []
    zip_code = criteria.get("zip_code")
    targets = []
    if selected_cities:
        for city in selected_cities:
            coords = engine.resolve_city_coords(city, state)
            if coords:
                targets.append({"lat": coords[0], "lon": coords[1], "label": f"{city}, {state}", "city_name": city})
    elif zip_code:
        geo_result = engine.validate_and_geocode_location(f"{zip_code}, {state}")
        if geo_result:
            targets.append({"lat": geo_result["latitude"], "lon": geo_result["longitude"], "label": f"{zip_code}, {state}", "city_name": None})
    else:
        geo_result = engine.validate_and_geocode_location(state)
        if geo_result:
            targets.append({"lat": geo_result["latitude"], "lon": geo_result["longitude"], "label": f"Any city in {state}", "city_name": None})

    if not targets:
        return []
    return engine.fetch_live_listings_for_targets(targets, property_type, max_price, min_beds, allow_live=allow_live, user_id=user_id)


def _load_saved_criteria(name, user_id):
    """Loads one auto-saved search's criteria back from the reports table
    by name, for a Quick Access chip click - re-running a past search is
    a single click (load criteria, then run), not "select it, then also
    click Run" the way the old profile dropdown required."""
    import sqlite3
    conn = sqlite3.connect(db.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT location, property_type, max_price, min_beds, state, cities_json, zip_code "
            "FROM reports WHERE user_id=? AND profile_name=?",
            (int(user_id), name)
        )
        row = cursor.fetchone()
    finally:
        conn.close()
    if not row:
        return None
    return {
        "location": row[0], "property_type": row[1], "max_price": row[2], "min_beds": row[3],
        "state": row[4], "selected_cities": json.loads(row[5]) if row[5] else [], "zip_code": row[6],
    }


def _run_guest_demo_scan(criteria):
    """The guest-only equivalent of _execute_scan. Never touches the DB -
    no saved-profile row, no credit deduction, no history log - but builds
    st.session_state.active_scanned_coords in the exact shape a real scan
    does via the shared _build_coord_list, so the existing
    _render_scan_results pipeline (filters, map/grid/table views, best-
    deal banner, real property cards) renders guest results identically
    to a real scan instead of a separate simplified view. Report text
    always comes from the offline mock generator, never OpenAI - a guest
    session shouldn't be able to spend the app's shared OpenAI quota."""
    loading_placeholder = st.empty()
    with loading_placeholder.container():
        render_scan_loading_radar("real_estate")
    try:
        raw_listings_data = _fetch_listings_for_criteria(criteria, allow_live=False)
        coord_list = _build_coord_list(raw_listings_data)
        report_result = engine.generate_offline_mock_report(
            "Guest Preview", criteria["location"], criteria["property_type"], criteria["max_price"], criteria["min_beds"], raw_listings_data)

        st.session_state.active_scanned_report = report_result
        st.session_state.active_scanned_profile = "Guest Preview"
        st.session_state.active_scanned_coords = json.dumps(coord_list)
        st.session_state.focused_card_index = None
        st.session_state.last_scan_was_preview = True
        st.session_state.last_scan_was_test = False
        st.rerun()
    finally:
        loading_placeholder.empty()


def _execute_scan(criteria, run_clicked, test_clicked, active_category):
    """Runs the actual scan (credit deduction, engine calls, auto-save,
    history log, notification emails) and shows the loading radar while
    it does. Deliberately called *after* the hero stat cards render (see
    the caller), not from inside the search form alongside its buttons -
    the user wants the loading visual big and on the dark hero
    background, positioned below the 3 cards, with the search form
    staying visible the whole time (nothing hidden/replaced while
    scanning). The 3 cards render from the *previous* scan's still-valid
    session_state before this function ever runs, so they show up
    immediately without waiting on this one.

    criteria comes directly from the ad-hoc search form (or a Quick
    Access chip's saved criteria) - no saved profile row has to exist
    first, unlike the old Manage-Searches-first flow. Every real scan
    still gets auto-saved under its location's name afterward so it
    appears as a Quick Access chip next time, but that's just a
    convenience now, not a precondition for scanning."""
    if not (run_clicked or test_clicked):
        return
    loading_placeholder = st.empty()
    with loading_placeholder.container():
        # "Cyber Radar" loading state, round 4 - big, on the dark hero
        # background (rounds 1-3 anchored it inside the white "Select
        # Target Profile" card, which is why round 2's transparent
        # background looked "white" - it was never on dark ground to
        # begin with). Shared with Cars' Find a Car page (scan_loading.py)
        # so both categories get the same visual, just with the icon/copy
        # swapped to match what's being searched.
        render_scan_loading_radar(active_category)

    try:
        location = criteria["location"]
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

        raw_listings_data = _fetch_listings_for_criteria(criteria, allow_live=allow_live, user_id=st.session_state.user_id)

        # Auto-save the criteria under this location's name so it shows up
        # as a Quick Access chip next time - re-searching the same
        # location just updates that same row (INSERT OR REPLACE keyed on
        # user_id+name) rather than growing without bound. Never blocks
        # the scan itself if the plan's saved-search cap is hit for a
        # genuinely new location - it just isn't remembered for next time,
        # the same "degrade gracefully, never hard-stop" rule credits use.
        existing_names = db.get_all_reports(st.session_state.user_id, category="real_estate")
        if location in existing_names or plan_limits.is_within_limit(
            st.session_state.user_role, st.session_state.user_plan, "saved_searches", len(existing_names)
        ):
            db.save_report_config(
                st.session_state.user_id, location, location, criteria["max_price"], criteria["min_beds"],
                criteria["property_type"], st.session_state.user_email, "",
                state=criteria.get("state"),
                cities_json=json.dumps(criteria["selected_cities"]) if criteria.get("selected_cities") else None,
                zip_code=criteria.get("zip_code") or None, category="real_estate",
            )

        report_result = engine.run_agent_workflow_adhoc(
            location, st.session_state.user_id, location, criteria["property_type"],
            criteria["max_price"], criteria["min_beds"], raw_listings=raw_listings_data,
        )

        coord_list = _build_coord_list(raw_listings_data)
        coord_string_data = json.dumps(coord_list)
        db.save_history_log(st.session_state.user_id, location, location, report_result, coord_string_data, was_live=allow_live)

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
                                      _d["default_target_yield"], hoa_monthly=_safe_hoa(p))
                for p in coord_list
            ]
            _excellent = [m for m in _excellent if m["grade"] == "excellent"]
            if _excellent:
                email_utils.send_deal_found_email(
                    st.session_state.user_email, location, len(_excellent),
                    max(m["coc"] for m in _excellent),
                )

        st.session_state.active_scanned_report = report_result
        st.session_state.active_scanned_profile = location
        st.session_state.active_scanned_coords = coord_string_data
        st.session_state.focused_card_index = None

        st.success("Scan complete!")
        st.rerun()
    except Exception:
        st.error("Something went wrong running this scan. Please try again.")
    finally:
        loading_placeholder.empty()


def _render_clustered_results_map(coords_json, key_prefix, view_mode, calc_rent, calc_vacancy_pct, calc_tax_rate, calc_ins_rate,
                                   calc_down_pct, calc_interest, calc_target_yield,
                                   filter_min_price=None, filter_max_price=None, filter_min_beds=0, filter_min_baths=0,
                                   filter_grades=None, height=650):
    """Full-width, grade-colored, clustered results map with click-a-pin
    (or a cluster) for detail - originally _render_scan_results's own
    "Map Only" view mode, extracted so the hero's compact results area
    (see [[hero_redesign_compact_results]]) can show the exact same map
    instead of a second, differently-built one. filter_* default to "no
    filtering", so a caller with no quick-filter bar of its own (the
    hero) can just omit them."""
    if filter_grades is None:
        filter_grades = ["excellent", "average", "critical"]
    if not coords_json:
        return
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
            return

        grades_for_map = []
        for _, r in df_listings_grid.iterrows():
            m = compute_deal_metrics(float(r["price"]), calc_rent, calc_vacancy_pct, calc_tax_rate,
                                      calc_ins_rate, calc_down_pct, calc_interest, calc_target_yield,
                                      hoa_monthly=_safe_hoa(r))
            grades_for_map.append(m["grade"])
        df_listings_grid["_grade"] = grades_for_map

        if filter_grades and len(filter_grades) < 3:
            df_listings_grid = df_listings_grid[df_listings_grid["_grade"].isin(filter_grades)].reset_index(drop=True)

        if df_listings_grid.empty:
            st.info("No properties match your current filters. Try widening the price range, lowering the min beds, or including more deal grades.")
            return

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
            height=height, showlegend=False,
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
                        calc_ins_rate, calc_down_pct, calc_interest, calc_target_yield,
                        hoa_monthly=_safe_hoa(sel_row)
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
    except Exception:
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
                        with st.popover(f":material/attach_money: {price_pill_label}", use_container_width=True):
                            filter_min_price, filter_max_price = st.slider(
                                "Price range", min_value=price_floor, max_value=price_ceiling,
                                value=(price_floor, price_ceiling), key=price_range_key,
                                format="$%d"
                            )
                    else:
                        filter_min_price, filter_max_price = price_floor, price_ceiling
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
            except Exception:
                pass

    view_toggle = st.session_state[view_mode_state_key]

    focused_key = f"{key_prefix}_focused_card_index"
    if focused_key not in st.session_state:
        st.session_state[focused_key] = None

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
                                                  calc_ins_rate, calc_down_pct, calc_interest, calc_target_yield,
                                                  hoa_monthly=_safe_hoa(r))
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
                                    calc_ins_rate, calc_down_pct, calc_interest, calc_target_yield,
                                    hoa_monthly=_safe_hoa(row_item)
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
                                                  calc_ins_rate, calc_down_pct, calc_interest, calc_target_yield,
                                                  hoa_monthly=_safe_hoa(r))
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
                                        calc_ins_rate, calc_down_pct, calc_interest, calc_target_yield,
                                        hoa_monthly=_safe_hoa(row_item)
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
        _render_clustered_results_map(
            coords_json, key_prefix, view_mode, calc_rent, calc_vacancy_pct, calc_tax_rate, calc_ins_rate,
            calc_down_pct, calc_interest, calc_target_yield,
            filter_min_price, filter_max_price, filter_min_beds, filter_min_baths, filter_grades,
        )

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
            except Exception:
                st.caption("Unable to load the table for this scan.")

    st.markdown("<br>", unsafe_allow_html=True)
    pdf_data_uri = generate_pdf_download_link(profile_name, report_body)
    st.markdown(f"""
        <a href="{pdf_data_uri}" download="{pdf_filename_prefix}_{profile_name.replace(' ', '_')}.html" style="text-decoration: none;">
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


def _clear_hist_delete_target():
    st.session_state.hist_delete_target = None


@st.dialog("Delete Scan Report", on_dismiss=_clear_hist_delete_target)
def _delete_history_dialog():
    """Same floating-dialog shape as strategy_config.py's
    _delete_search_dialog (see [[table_action_pattern]]) - both the grid's
    trash icon and the "Remove" button under an opened report set
    hist_delete_target and land here, so there's exactly one delete
    confirmation, not two different ones with different behavior (the
    "Remove" button used to skip confirmation entirely). on_dismiss clears
    the target on every dismissal path, not just Cancel - see
    [[table_action_pattern]] for why that matters (a dialog dismissed via
    the native X otherwise reopens on the next unrelated interaction)."""
    ctx = st.session_state.get("hist_delete_target")
    if not ctx:
        st.write("No report selected.")
        return

    st.warning(f"Delete **{ctx['name']}** from your scan history? This can't be undone.")
    confirm_col, cancel_col = st.columns(2)
    with confirm_col:
        if st.button(":material/delete_forever: Confirm Delete", type="primary", use_container_width=True):
            db.delete_history_log(st.session_state.user_id, ctx["id"])
            st.session_state.hist_delete_target = None
            st.toast("Removed from your scan history.")
            st.rerun()
    with cancel_col:
        if st.button("Cancel", use_container_width=True):
            st.session_state.hist_delete_target = None
            st.rerun()


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
                                              calc_ins_rate, calc_down_pct, calc_interest, calc_target_yield,
                                              hoa_monthly=_safe_hoa(p))
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
            st.session_state.hist_delete_target = {
                "id": df_hist_page.iloc[delete_click["row"]]["Log ID"],
                "name": df_hist_page.iloc[delete_click["row"]]["Profile Name"],
            }

        if st.session_state.get("hist_delete_target"):
            _delete_history_dialog()

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
                    st.session_state.hist_delete_target = {"id": archived_log_id, "name": archived_report_name}
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


def render_history_page(is_guest=False):
    """Top-level History page - promoted out of a nested tab on Run
    Property Scans into its own navbar item, per real feedback that the
    main navbar was the clearer place to find it than a sub-tab someone
    has to already be on the scan page to notice (see
    [[nav_simplification_ad_hoc_search]]). Content itself (_render_history_tab)
    is unchanged - just given a real page shell and, since there's no
    longer an interactive Pro sidebar to source calc_* from up here, the
    user's saved default assumptions instead (still fully adjustable per
    property from within the results themselves)."""
    st.markdown("""
        <style>
        div.st-key-history_hero {
            background: var(--radar-gradient-hero);
            padding: var(--radar-space-6) var(--radar-space-7);
            margin-bottom: var(--radar-space-5);
            border-radius: 0 0 var(--radar-radius-xl) var(--radar-radius-xl);
        }
        </style>
    """, unsafe_allow_html=True)

    with st.container(key="history_hero"):
        st.markdown(f"""
            <div style='text-align:center; max-width:760px; margin:0 auto;'>
                <div style='display:flex; align-items:center; justify-content:center; gap:14px; margin-bottom:10px;'>
                    <div style='background: var(--radar-gradient-brand); width: 48px; height: 48px;
                                border-radius: var(--radar-radius-md); display:flex; align-items:center; justify-content:center; flex-shrink:0;'>
                        {svg_icon("clock", size=24, color="white")}
                    </div>
                    <div style='font-family:var(--radar-font-display); font-size:32px; font-weight:800; color:white; line-height:1.2;'>History</div>
                </div>
                <div style='font-size:16px; color:var(--radar-text-on-dark-muted);'>Every past scan, free to browse back through anytime</div>
            </div>
        """, unsafe_allow_html=True)

    if is_guest:
        render_guest_banner("your scan history isn't tracked in a demo session")
        render_empty_state(
            "clock", "Sign in to keep a history",
            "Every real scan you run gets saved here automatically once you have an account.",
        )
        return

    _defaults = st.session_state.user_settings
    view_mode = _defaults.get("default_underwriter_mode", "Simple")
    _render_history_tab(
        view_mode, 3500, _defaults["default_vacancy_pct"], _defaults["default_tax_rate"],
        _defaults["default_insurance_rate"], _defaults["default_down_pct"], _defaults["default_interest_rate"],
        _defaults["default_target_yield"],
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
