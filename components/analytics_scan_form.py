"""
components/analytics_scan_form.py
The ad-hoc real-estate scan form, its action buttons (Run Live Scan/
Run Test Scan/Buy Credits), and the mini results strip shown beside
them - split out of components/analytics.py (Section 5 monolith-split
plan).
"""
import json
import streamlit as st

import roles
from components import pricing
from underwriting import compute_deal_metrics
from components.property_card import render_property_detail_dialog
from location_picker import render_compact_location_fields, location_display_label
from components.analytics_atoms import _safe_hoa, _format_price_short


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
        run_clicked = st.button(":material/travel_explore: Run Live Scan", type="primary", width="stretch", key="run_scan_btn")
    test_clicked = False
    # Staff-only (any of the 3 tiers - see roles.py): forces mock/sample
    # data regardless of role or credits, so staff can exercise the UI
    # (new views, filters, pagination...) without burning real RentCast
    # quota - previously the only way to get preview data as staff was
    # to hand-edit a test account's credits to 0, since being staff
    # always granted allow_live=True.
    if roles.is_staff(st.session_state.user_role):
        test_clicked = st.button(":material/science: Run Test Scan", width="stretch", key="run_test_scan_btn",
                                  help="Uses mock/sample data - doesn't spend real RentCast quota.")
    if not is_guest and st.session_state.user_credits <= 0 and not roles.is_admin_or_above(st.session_state.user_role):
        if st.button(":material/add_card: Buy Credits", width="stretch", key="buy_credits_trigger_btn"):
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
    except Exception as e:
        # coords_json is produced by this app's own scan pipeline (not
        # user input), so a parse failure here means real corruption or an
        # upstream bug - worth knowing about, not just a quietly-empty strip.
        print(f"[Analytics] Failed to parse coords_json in mini results strip: {e}")
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

