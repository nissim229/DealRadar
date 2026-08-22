"""
location_picker.py
The state -> city (or ZIP, or "any city in this state") picker with a live
map, used to target a real-estate scan. Extracted out of the old
strategy_config.py (the "Manage Searches" page, since removed - real-estate
scans are now ad-hoc, mirroring how car_search.py already works, see
[[nav_simplification_ad_hoc_search]]) since this widget is genuinely
reusable on its own and has nothing to do with saved-search CRUD.
"""

import streamlit as st
import pandas as pd
import plotly.express as px
from geopy.distance import geodesic
import agent_engine as engine
import location_data

MAX_CITIES_PER_SEARCH = 5
SEARCH_RADIUS_MILES = 8


def _circle_points(lat, lon, radius_miles=SEARCH_RADIUS_MILES, num_points=36):
    """A ring of lat/lon points approximating a circle of the given radius
    around a center point - used to draw the search-area overlay on the
    location picker's map, so a user can see exactly how far a city search
    actually reaches (this app's older flat 25-mile default was invisible
    and part of why unrelated-city results were confusing)."""
    return [
        (geodesic(miles=radius_miles).destination((lat, lon), (360 / num_points) * i).latitude,
         geodesic(miles=radius_miles).destination((lat, lon), (360 / num_points) * i).longitude)
        for i in range(num_points + 1)
    ]


def render_compact_location_fields(key_prefix):
    """State + city control for the hero search form - a plain selectbox
    next to a popover trigger (mode toggle, city pills, ZIP), no inline
    map. Replaces the old full-width state dropdown + always-visible map
    block - real feedback was that the picker took over the whole screen
    for a field that's usually just "any city in this state" (see
    [[hero_redesign_unified_map]]). The map itself isn't gone - it moved
    to render_city_picker_map, shown once in the shared results area
    instead of duplicated here too ("we only need one map").

    Returns (state, selected_cities, zip_code) - selected_cities is []
    when "Any city" is chosen. Session state (not a return value) is the
    source of truth, shared by name with render_city_picker_map (both use
    f"{key_prefix}_selected_cities") so a click on that map and a pick
    made here stay in sync."""
    state_key = f"{key_prefix}_state"
    mode_key = f"{key_prefix}_city_mode"
    cities_key = f"{key_prefix}_selected_cities"
    zip_key = f"{key_prefix}_zip"

    if cities_key not in st.session_state:
        st.session_state[cities_key] = []

    col_state, col_city = st.columns(2)
    with col_state:
        selected_state = st.selectbox("State", location_data.US_STATES, key=state_key)

    # A state change (or first render) invalidates any previously-selected
    # cities that belonged to a different state - self-correcting on every
    # render instead of needing explicit change-detection.
    valid_cities_here = location_data.US_CITIES_BY_STATE.get(selected_state, [])
    st.session_state[cities_key] = [c for c in st.session_state[cities_key] if c in valid_cities_here]

    with col_city:
        zip_val = st.session_state.get(zip_key, "")
        n_picked = len(st.session_state[cities_key])
        if zip_val:
            trigger_label = f":material/location_on: {zip_val}"
        elif n_picked:
            trigger_label = f":material/location_city: {n_picked} cit{'y' if n_picked == 1 else 'ies'} selected"
        else:
            trigger_label = ":material/public: Any city"
        st.markdown('<div class="dealradar-navstyle-label">City</div>', unsafe_allow_html=True)
        with st.popover(trigger_label, width="stretch"):
            city_mode = st.radio(
                "City selection", ["Any city", "Choose specific cities"], key=mode_key,
                horizontal=True, label_visibility="collapsed",
            )
            pills_key = f"{key_prefix}_city_pills_{selected_state}"
            if city_mode == "Choose specific cities":
                # st.pills (single widget, internal multi-select state) instead of
                # one st.checkbox per city - checkboxes proved unreliable for both
                # automated clicks and a real user earlier in this project (see
                # feedback_checkbox_reveal_ux memory), and this is the same class of
                # "many small independently-clickable toggles" problem.
                picked = st.pills(f"Cities in {selected_state}", valid_cities_here, selection_mode="multi",
                                   default=st.session_state[cities_key], key=pills_key, label_visibility="collapsed")
                picked = picked or []
                if len(picked) > MAX_CITIES_PER_SEARCH:
                    st.warning(f"You can select up to {MAX_CITIES_PER_SEARCH} cities per search - using your first {MAX_CITIES_PER_SEARCH}.")
                    picked = picked[:MAX_CITIES_PER_SEARCH]
                st.session_state[cities_key] = picked

            zip_code = st.text_input("ZIP Code (optional)", key=zip_key, max_chars=5,
                                      placeholder="e.g., 80301", help="Narrows the search further within your selection.")

    selected_cities = st.session_state[cities_key] if city_mode == "Choose specific cities" else []
    return selected_state, selected_cities, zip_code.strip()


def render_city_picker_map(state, selected_cities, key_prefix, height=380):
    """The map half of the old combined picker, now shown on its own -
    in the shared results area, in place of the results map until a scan
    has actually run, rather than as a second map duplicated inside the
    search form too. Every curated city in `state`, colored by selection
    state, with a search-radius circle around each currently-selected
    one; clicking a marker toggles that city in/out of
    st.session_state[f"{key_prefix}_selected_cities"] - the same key
    render_compact_location_fields reads, so a click here is reflected
    there on the next rerun without any extra wiring."""
    cities_key = f"{key_prefix}_selected_cities"
    mode_key = f"{key_prefix}_city_mode"
    pills_key = f"{key_prefix}_city_pills_{state}"
    valid_cities_here = location_data.US_CITIES_BY_STATE.get(state, [])

    with st.spinner(f"Loading map for {state}..."):
        city_points = []
        for city in valid_cities_here:
            coords = engine.resolve_city_coords(city, state)
            if coords:
                city_points.append({"city": city, "lat": coords[0], "lon": coords[1],
                                     "Selected": "Yes" if city in selected_cities else "No"})

    if not city_points:
        st.caption("Couldn't load the map for this state right now - your city/ZIP selection above still works.")
        return

    map_df = pd.DataFrame(city_points)
    fig = px.scatter_mapbox(
        map_df, lat="lat", lon="lon", hover_name="city", color="Selected",
        color_discrete_map={"Yes": "#2563eb", "No": "#94a3b8"},
        zoom=5, height=height, mapbox_style="open-street-map",
    )
    for city in selected_cities:
        match = next((p for p in city_points if p["city"] == city), None)
        if match:
            ring = _circle_points(match["lat"], match["lon"])
            fig.add_scattermapbox(
                lat=[p[0] for p in ring], lon=[p[1] for p in ring], mode="lines",
                line=dict(color="#2563eb", width=2), showlegend=False, hoverinfo="skip",
            )
    fig.update_layout(margin=dict(l=0, r=0, t=0, b=0), legend=dict(title=None))
    map_event = st.plotly_chart(fig, width="stretch", on_select="rerun",
                                 selection_mode="points", key=f"{key_prefix}_map")
    clicked_points = (map_event or {}).get("selection", {}).get("points", [])
    # curve_number 0 is the base city-marker trace; the circle overlays
    # added afterward are separate traces - only a click on an actual
    # city marker should toggle a selection.
    marker_clicks = [p for p in clicked_points if p.get("curve_number") == 0]
    if marker_clicks:
        clicked_city = map_df.iloc[marker_clicks[0]["point_index"]]["city"]
        current = st.session_state.get(cities_key, [])
        if clicked_city in current:
            current.remove(clicked_city)
        elif len(current) < MAX_CITIES_PER_SEARCH:
            current.append(clicked_city)
            st.session_state[mode_key] = "Choose specific cities"
        else:
            st.warning(f"You can select up to {MAX_CITIES_PER_SEARCH} cities per search.")
        st.session_state[cities_key] = current
        st.session_state[pills_key] = list(current)
        st.rerun()


def location_display_label(state, selected_cities, zip_code):
    """The human-readable location string used as both the scan's display
    label and its auto-saved search name - same formatting the old
    Manage Searches form used, so a "Denver, Colorado"-style name reads
    naturally as a Quick Access chip."""
    if selected_cities:
        return f"{', '.join(selected_cities)}, {state}"
    if zip_code:
        return f"{zip_code}, {state}"
    return f"Any city in {state}"
