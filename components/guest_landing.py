"""
guest_landing.py
The public, no-login-required browsing experience. Lets anyone run a live
demo search and see property cards with basic numbers (price, Cap Rate,
Cash Flow, deal badge) - matching the "browse like Zillow" pattern. Full
features (Pro calculator, saving, notes, PDF export, real scans against a
saved Hunt Profile) all require an account, and are intentionally NOT
available here.

This is a deliberately separate, simple page rather than a stripped-down
version of the full authenticated dashboard - much lower risk of breaking
the existing logged-in experience, since nothing here touches user_id,
credits, or the database at all.
"""

import streamlit as st
import agent_engine as engine
from underwriting import compute_deal_metrics, render_deal_badge
from photo_carousel import render_photo_carousel_html
from icons import icon as svg_icon
import streamlit.components.v1 as components

# Sensible fixed defaults for the guest demo - matches the app's own "Simple
# mode" defaults elsewhere, so numbers are consistent across the product.
GUEST_RENT = 3500
GUEST_VACANCY = 5
GUEST_TAX_RATE = 1.2
GUEST_INS_RATE = 0.4
GUEST_DOWN_PCT = 25
GUEST_INTEREST = 6.5
GUEST_TARGET_YIELD = 8.0

# Cities with real hardcoded Street View-friendly coordinates (see
# agent_engine.py's city_directory) - used for both the default first-load
# search and the quick-search chips, so results always look good immediately.
QUICK_SEARCH_CITIES = ["Denver, Colorado", "Austin, Texas", "Miami, Florida", "Boulder, Colorado"]


def _run_search(city, max_price, min_beds):
    # allow_live=False: anonymous/guest previews never spend metered RentCast
    # quota - only authenticated, deliberate "Run Scan" actions do.
    listings = engine.fetch_live_listings(city, "Multi-Family", int(max_price), int(min_beds), allow_live=False)
    st.session_state.guest_search_results = listings
    st.session_state.guest_search_city = city


def render_guest_landing():
    if "show_login_form" not in st.session_state:
        st.session_state.show_login_form = False

    # --- Simple public header: logo left, Sign In button right ---
    st.markdown("""
        <style>
        div.st-key-guest_topbar {
            background-color: var(--radar-navy);
            padding: 14px 28px;
            margin-bottom: 24px;
        }
        div.st-key-guest_topbar button {
            background-color: var(--radar-primary) !important;
            color: white !important;
            border: none !important;
            font-weight: 600 !important;
        }
        div.st-key-guest_topbar button:hover {
            background-color: var(--radar-primary-dark) !important;
        }
        </style>
    """, unsafe_allow_html=True)

    with st.container(key="guest_topbar"):
        col_logo, col_spacer, col_signin = st.columns([2, 3, 1])
        with col_logo:
            st.markdown("""
                <div style='display: flex; align-items: center; gap: 10px;'>
                    <div style='background: var(--radar-gradient-brand); width: 34px; height: 34px; border-radius: var(--radar-radius-md); display: flex; align-items: center; justify-content: center;'>
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                            <circle cx="12" cy="12" r="9" />
                            <circle cx="12" cy="12" r="5" />
                            <path d="M12 12 L18 6" />
                            <circle cx="17" cy="7" r="1.4" fill="white" stroke="none" />
                        </svg>
                    </div>
                    <span style='font-size: 16px; font-weight: 700; color: white !important;'>DealRadar</span>
                </div>
            """, unsafe_allow_html=True)
        with col_signin:
            if st.button(":material/login: Sign In / Register", key="guest_signin_btn", use_container_width=True):
                st.session_state.show_login_form = True
                st.rerun()

    # --- Hero section: dark gradient banner with headline + search + quick chips ---
    st.markdown("""
        <style>
        div.st-key-guest_hero {
            background: var(--radar-gradient-hero);
            padding: 48px 40px 64px 40px;
            margin-bottom: -40px;
            border-radius: 0 0 var(--radar-radius-xl) var(--radar-radius-xl);
        }
        div.st-key-guest_search_card {
            background: var(--radar-surface);
            border-radius: var(--radar-radius-lg);
            padding: 20px 24px;
            box-shadow: var(--radar-shadow-lg);
            max-width: 900px;
            margin: 0 auto;
        }
        div.st-key-guest_search_card button {
            background-color: var(--radar-primary) !important;
            color: white !important;
            border: none !important;
            font-weight: 700 !important;
        }
        div.st-key-guest_search_card button:hover {
            background-color: var(--radar-primary-dark) !important;
        }
        div.st-key-guest_benefit {
            background: var(--radar-surface);
            border: 1px solid var(--radar-border);
            border-radius: var(--radar-radius-md);
            padding: 16px 14px;
            text-align: center;
            height: 100%;
        }
        div.st-key-guest_chip button {
            background-color: transparent !important;
            color: var(--radar-text-on-dark-muted) !important;
            border: 1px solid var(--radar-navy-light) !important;
            font-weight: 500 !important;
            font-size: 12px !important;
            border-radius: var(--radar-radius-pill) !important;
            padding: 4px 12px !important;
            min-height: 0 !important;
        }
        div.st-key-guest_chip button:hover {
            background-color: rgba(37,99,235,0.15) !important;
            color: white !important;
            border-color: var(--radar-primary) !important;
        }
        </style>
    """, unsafe_allow_html=True)

    with st.container(key="guest_hero"):
        st.markdown(f"""
            <div style='text-align:center; max-width:760px; margin:0 auto 28px auto;'>
                <div style='display:flex; align-items:center; justify-content:center; gap:14px; margin-bottom:10px;'>
                    <div style='background: var(--radar-gradient-brand); width: 48px; height: 48px;
                                border-radius: var(--radar-radius-md); display:flex; align-items:center; justify-content:center; flex-shrink:0;'>
                        {svg_icon("radar", size=24, color="white")}
                    </div>
                    <div style='font-size:32px; font-weight:800; color:white; line-height:1.2;'>Find your next great deal in seconds</div>
                </div>
                <div style='font-size:16px; color:var(--radar-text-on-dark-muted);'>
                    Search any city for a free instant preview - real property matches, real numbers,
                    graded by cash flow. No account required to try it.
                </div>
            </div>
        """, unsafe_allow_html=True)

        with st.container(key="guest_search_card"):
            with st.form("guest_search_form"):
                c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
                with c1:
                    city = st.text_input("City", placeholder="e.g., Denver, Colorado",
                                          value=st.session_state.get("guest_search_city", ""))
                with c2:
                    max_price = st.number_input("Max price ($)", min_value=50000, value=750000, step=25000)
                with c3:
                    min_beds = st.number_input("Min beds", min_value=0, value=3, step=1)
                with c4:
                    st.markdown("<div style='margin-top:28px;'></div>", unsafe_allow_html=True)
                    search_clicked = st.form_submit_button(":material/travel_explore: Search", use_container_width=True)

        st.markdown("<div style='text-align:center; margin-top:14px;'>", unsafe_allow_html=True)
        st.markdown("<span style='color:var(--radar-text-on-dark-muted); font-size:12px; margin-right:8px;'>Popular:</span>", unsafe_allow_html=True)
        chip_cols = st.columns([1, 1, 1, 1, 1, 3])
        chip_clicked_city = None
        for i, chip_city in enumerate(QUICK_SEARCH_CITIES):
            with chip_cols[i]:
                with st.container(key=f"guest_chip_{i}"):
                    if st.button(chip_city.split(",")[0], key=f"guest_chip_btn_{i}", use_container_width=True):
                        chip_clicked_city = chip_city
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<div style='height:56px;'></div>", unsafe_allow_html=True)

    # --- Benefits strip: what signing in actually unlocks ---
    st.markdown("<div style='text-align:center; font-weight:700; color:var(--radar-text); font-size:15px; margin-bottom:14px;'>What you get with a free account</div>", unsafe_allow_html=True)
    benefits = [
        ("chart", "Full Pro Calculator", "DSCR, GRM, MAO, and a Suggested Max Offer for every property"),
        ("star-filled", "Save & Track Deals", "Star properties across scans, add your own notes"),
        ("download", "Export Reports", "Download a clean PDF for any property or full scan"),
        ("crosshair", "Saved Searches", "Set up hunt profiles and re-run them anytime"),
    ]
    benefit_cols = st.columns(4)
    for (icon_name, title, desc), bcol in zip(benefits, benefit_cols):
        with bcol:
            with st.container(key=f"guest_benefit_{title.replace(' ', '_')}"):
                st.markdown(f"""
                    <div style='margin-bottom:8px;'>{svg_icon(icon_name, size=24, color="var(--radar-primary)")}</div>
                    <div style='font-weight:700; color:var(--radar-text); font-size:13.5px; margin-bottom:4px;'>{title}</div>
                    <div style='font-size:11.5px; color:var(--radar-text-muted); line-height:1.4;'>{desc}</div>
                """, unsafe_allow_html=True)

    st.markdown("<div style='height:20px;'></div>", unsafe_allow_html=True)
    _render_pro_calculator_teaser()
    st.markdown("<div style='height:32px;'></div>", unsafe_allow_html=True)

    # --- Resolve search: quick chip takes priority, then form submit, then
    # auto-run a default search on first load so the page never looks empty ---
    if chip_clicked_city:
        with st.spinner("Searching..."):
            _run_search(chip_clicked_city, 750000, 3)
        st.rerun()
    elif search_clicked and city:
        with st.spinner("Searching..."):
            _run_search(city, max_price, min_beds)
    elif search_clicked and not city:
        st.warning("Enter a city to search.")
    elif "guest_search_results" not in st.session_state:
        with st.spinner("Loading a sample search..."):
            _run_search(QUICK_SEARCH_CITIES[0], 750000, 3)

    results = st.session_state.get("guest_search_results")
    if results:
        st.markdown(f"### {len(results)} properties found near {st.session_state.get('guest_search_city', '')}")

        # Best-match callout - computed from the same math the Pro dashboard
        # uses, so it's a genuine preview of the real product's value.
        all_metrics = [
            compute_deal_metrics(float(item["price"]), GUEST_RENT, GUEST_VACANCY, GUEST_TAX_RATE,
                                  GUEST_INS_RATE, GUEST_DOWN_PCT, GUEST_INTEREST, GUEST_TARGET_YIELD)
            for item in results
        ]
        best_idx = max(range(len(all_metrics)), key=lambda i: all_metrics[i]["coc"])
        best_metrics = all_metrics[best_idx]
        best_listing = results[best_idx]
        if best_metrics["coc"] > 0:
            st.markdown(f"""
                <div style='background:var(--radar-success-bg); border:1px solid var(--radar-success-border); border-radius:var(--radar-radius-md); padding:12px 16px; margin-bottom:16px; display:flex; align-items:center; gap:8px;'>
                    {svg_icon("trophy", size=16, color="#065f46")}
                    <span style='font-weight:700; color:#065f46;'>Best deal found:</span>
                    <span style='color:#065f46;'>{best_metrics['coc']:.1f}% cash-on-cash return at {best_listing.get('address', '')}</span>
                </div>
            """, unsafe_allow_html=True)

        st.caption(":material/lightbulb: Showing basic numbers only. Sign in for the full Pro calculator (DSCR, GRM, Suggested Max Offer), saving, and notes.")

        cols_per_row = 3
        for row_start in range(0, len(results), cols_per_row):
            row_items = list(enumerate(results))[row_start:row_start + cols_per_row]
            row_cols = st.columns(cols_per_row)
            for (idx, item), col in zip(row_items, row_cols):
                with col:
                    _render_guest_card(item, idx)


def _render_pro_calculator_teaser():
    """A dimmed, non-interactive glimpse of the Pro calculator's numbers,
    with a lock overlay - shows concretely what signing in unlocks instead
    of just describing it in text."""
    st.markdown("""
        <div style='position:relative; max-width:640px; margin:0 auto; border-radius:var(--radar-radius-lg); overflow:hidden;
                    border:1px solid var(--radar-border);'>
            <div style='filter: blur(3px); opacity:0.55; background:var(--radar-navy); padding:18px 20px;
                        display:grid; grid-template-columns:repeat(4,1fr); gap:12px; font-family:monospace;'>
                <div style='color:var(--radar-text-on-dark-muted); font-size:10px;'>CAP RATE<br><span style='color:white; font-size:16px; font-weight:800;'>7.24%</span></div>
                <div style='color:var(--radar-text-on-dark-muted); font-size:10px;'>DSCR<br><span style='color:white; font-size:16px; font-weight:800;'>1.42</span></div>
                <div style='color:var(--radar-text-on-dark-muted); font-size:10px;'>GRM<br><span style='color:white; font-size:16px; font-weight:800;'>9.8</span></div>
                <div style='color:var(--radar-text-on-dark-muted); font-size:10px;'>MAO<br><span style='color:white; font-size:16px; font-weight:800;'>$412K</span></div>
            </div>
            <div style='position:absolute; inset:0; display:flex; flex-direction:column; align-items:center;
                        justify-content:center; background:rgba(15,23,42,0.35);'>
                <div style='font-size:22px;'>🔒</div>
                <div style='color:white; font-weight:700; font-size:13px; margin-top:4px;'>Sign in to see the full Pro breakdown</div>
            </div>
        </div>
    """, unsafe_allow_html=True)


def _render_guest_card(listing, idx=0):
    metrics = compute_deal_metrics(
        float(listing["price"]), GUEST_RENT, GUEST_VACANCY, GUEST_TAX_RATE,
        GUEST_INS_RATE, GUEST_DOWN_PCT, GUEST_INTEREST, GUEST_TARGET_YIELD
    )
    card_key = f"guest_card_{idx}_{listing.get('address', '')[:10].replace(' ', '_')}"
    entrance_delay = min(idx * 0.06, 0.6)

    st.markdown(f"""
        <style>
        @keyframes guestCardFadeInUp {{
            from {{ opacity: 0; transform: translateY(14px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}
        div.st-key-{card_key} {{
            animation: guestCardFadeInUp 0.45s ease-out forwards;
            animation-delay: {entrance_delay}s;
            opacity: 0;
        }}
        </style>
    """, unsafe_allow_html=True)

    with st.container(border=True, key=card_key):
        gallery_urls = engine.get_street_view_gallery_urls(listing.get("latitude"), listing.get("longitude"))
        carousel_html = render_photo_carousel_html(gallery_urls, f"${listing['price']:,.0f}", render_deal_badge(metrics["grade"]))
        components.html(carousel_html, height=200)

        st.markdown(f"**{listing.get('address', '')}**")
        info_parts = [f"{listing.get('beds', '-')} bd", f"{listing.get('baths', '-')} ba"]
        sqft = listing.get('sqft')
        if sqft:
            info_parts.append(f"{int(sqft):,} sqft")
        prop_type = listing.get('property_type')
        if prop_type:
            info_parts.append(str(prop_type))
        st.caption(" · ".join(info_parts))

        m1, m2 = st.columns(2)
        with m1:
            st.metric("Cap Rate", f"{metrics['cap_rate']:.2f}%")
        with m2:
            st.metric("Cash Flow", f"${metrics['cashflow']:,.0f}/yr")

        if st.button(":material/lock: Unlock Full Pro Analysis", key=f"guest_unlock_{idx}_{listing.get('address', '')}", use_container_width=True):
            st.session_state.show_login_form = True
            st.rerun()