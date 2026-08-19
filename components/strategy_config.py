import json
import streamlit as st
import pandas as pd
import plotly.express as px
from geopy.distance import geodesic
import database as db
import agent_engine as engine
import plan_limits
import location_data
from icons import icon as svg_icon
from components import pricing
from nav import render_side_nav

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


def _render_location_picker(key_prefix):
    """State -> city picker replacing the old free-text "Target City" field.
    Lives outside any st.form since the map's click-to-select and the
    state/city dropdowns all need live reruns, which forms don't give
    per-widget. Returns (state, selected_cities, zip_code) - selected_cities
    is [] when "Any city" is chosen. Session state (not a return value) is
    the source of truth across reruns, since this renders across multiple
    Streamlit script runs as the user interacts with it."""
    state_key = f"{key_prefix}_state"
    mode_key = f"{key_prefix}_city_mode"
    cities_key = f"{key_prefix}_selected_cities"
    zip_key = f"{key_prefix}_zip"

    if cities_key not in st.session_state:
        st.session_state[cities_key] = []

    selected_state = st.selectbox("State", location_data.US_STATES, key=state_key)

    # A state change (or first render) invalidates any previously-selected
    # cities that belonged to a different state - self-correcting on every
    # render instead of needing explicit change-detection.
    valid_cities_here = location_data.US_CITIES_BY_STATE.get(selected_state, [])
    st.session_state[cities_key] = [c for c in st.session_state[cities_key] if c in valid_cities_here]

    nav_col, content_col = st.columns([1, 3])
    with nav_col:
        city_mode = render_side_nav(
            [
                {"label": "Any city", "icon": ":material/public:"},
                {"label": "Choose specific cities", "icon": ":material/location_city:"},
            ],
            key_prefix=f"{key_prefix}_city_mode_nav",
            state_key=mode_key,
        )

    with content_col:
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

        # --- Map: every curated city in this state, colored by selection state,
        # with a search-radius circle around each currently-selected city.
        # Clicking a marker toggles that city in/out of the selection, kept in
        # sync with the checkboxes above via the same session_state list.
        with st.spinner(f"Loading map for {selected_state}..."):
            city_points = []
            for city in valid_cities_here:
                coords = engine.resolve_city_coords(city, selected_state)
                if coords:
                    city_points.append({"city": city, "lat": coords[0], "lon": coords[1],
                                         "Selected": "Yes" if city in st.session_state[cities_key] else "No"})

        if city_points:
            map_df = pd.DataFrame(city_points)
            fig = px.scatter_mapbox(
                map_df, lat="lat", lon="lon", hover_name="city", color="Selected",
                color_discrete_map={"Yes": "#2563eb", "No": "#94a3b8"},
                zoom=5, height=380, mapbox_style="open-street-map",
            )
            for city in st.session_state[cities_key]:
                match = next((p for p in city_points if p["city"] == city), None)
                if match:
                    ring = _circle_points(match["lat"], match["lon"])
                    fig.add_scattermapbox(
                        lat=[p[0] for p in ring], lon=[p[1] for p in ring], mode="lines",
                        line=dict(color="#2563eb", width=2), showlegend=False, hoverinfo="skip",
                    )
            fig.update_layout(margin=dict(l=0, r=0, t=0, b=0), legend=dict(title=None))
            map_event = st.plotly_chart(fig, use_container_width=True, on_select="rerun",
                                         selection_mode="points", key=f"{key_prefix}_map")
            clicked_points = (map_event or {}).get("selection", {}).get("points", [])
            # curve_number 0 is the base city-marker trace; the circle overlays
            # added afterward are separate traces - only a click on an actual
            # city marker should toggle a selection.
            marker_clicks = [p for p in clicked_points if p.get("curve_number") == 0]
            if marker_clicks:
                clicked_city = map_df.iloc[marker_clicks[0]["point_index"]]["city"]
                if clicked_city in st.session_state[cities_key]:
                    st.session_state[cities_key].remove(clicked_city)
                    st.session_state[pills_key] = list(st.session_state[cities_key])
                elif len(st.session_state[cities_key]) < MAX_CITIES_PER_SEARCH:
                    st.session_state[cities_key].append(clicked_city)
                    st.session_state[pills_key] = list(st.session_state[cities_key])
                    st.session_state[mode_key] = "Choose specific cities"
                else:
                    st.warning(f"You can select up to {MAX_CITIES_PER_SEARCH} cities per search.")
                st.rerun()
        else:
            st.caption("Couldn't load the map for this state right now - your city/ZIP selection above still works.")

    selected_cities = st.session_state[cities_key] if city_mode == "Choose specific cities" else []
    return selected_state, selected_cities, zip_code.strip()


def _clear_location_picker(key_prefix):
    """Resets the picker to a blank state after a search is saved, so the
    next "new search" doesn't start pre-filled with the last one's picks."""
    for key in list(st.session_state.keys()):
        if key.startswith(f"{key_prefix}_"):
            del st.session_state[key]


def _render_empty_state(icon_name, title, description):
    """Lightweight version of the same empty-state pattern used on the
    dashboard - kept local instead of importing from components.analytics
    to avoid a cross-dependency between sibling page modules."""
    st.markdown(f"""
        <div style='text-align:center; padding:var(--radar-space-8) var(--radar-space-5); background:var(--radar-surface-alt);
                    border:1px dashed var(--radar-border); border-radius:var(--radar-radius-lg);'>
            <div style='width:56px; height:56px; border-radius:50%; background:var(--radar-surface); display:flex; align-items:center;
                        justify-content:center; margin:0 auto var(--radar-space-4) auto; box-shadow:var(--radar-shadow-sm);'>
                {svg_icon(icon_name, size=26, color="var(--radar-primary)")}
            </div>
            <div style='font-weight:700; font-size:var(--radar-text-lg); color:var(--radar-navy); margin-bottom:6px;'>{title}</div>
            <div style='color:var(--radar-text-muted); font-size:14px; max-width:420px; margin:0 auto;'>{description}</div>
        </div>
    """, unsafe_allow_html=True)


def render_strategy_configuration():
    st.markdown("""
        <style>
        div.st-key-strategy_hero {
            background: var(--radar-gradient-hero);
            padding: var(--radar-space-6) var(--radar-space-7);
            margin-bottom: var(--radar-space-5);
            border-radius: 0 0 var(--radar-radius-xl) var(--radar-radius-xl);
        }
        </style>
    """, unsafe_allow_html=True)

    with st.container(key="strategy_hero"):
        st.markdown(f"""
            <div style='text-align:center; max-width:760px; margin:0 auto;'>
                <div style='display:flex; align-items:center; justify-content:center; gap:14px; margin-bottom:10px;'>
                    <div style='background: var(--radar-gradient-brand); width: 48px; height: 48px;
                                border-radius: var(--radar-radius-md); display:flex; align-items:center; justify-content:center; flex-shrink:0;'>
                        {svg_icon("crosshair", size=24, color="white")}
                    </div>
                    <div style='font-family:var(--radar-font-display); font-size:32px; font-weight:800; color:white; line-height:1.2;'>Manage Searches</div>
                </div>
                <div style='font-size:16px; color:var(--radar-text-on-dark-muted);'>Create, edit, or remove your automated property searches</div>
            </div>
        """, unsafe_allow_html=True)

    if "save_success_flash" in st.session_state and st.session_state.save_success_flash:
        st.success(st.session_state.save_success_flash)
        st.session_state.save_success_flash = None

    nav_col, content_col = st.columns([1, 4])
    with nav_col:
        active_section = render_side_nav(
            [
                {"label": "New Search", "icon": ":material/add_circle:"},
                {"label": "Your Searches", "icon": ":material/list_alt:"},
            ],
            key_prefix="hunt_nav",
        )

    with content_col:
        if active_section == "New Search":
            _render_establish_tab()
        else:
            _render_your_searches_tab()


def _render_establish_tab():
    st.markdown("""
        <div style='background-color: var(--radar-surface-alt); padding: var(--radar-space-5); border-radius: var(--radar-radius-md); border-left: 4px solid var(--radar-primary); margin-bottom: var(--radar-space-6);'>
            <h3 style='margin: 0 0 5px 0; color: var(--radar-navy);'>Set Up a New Search</h3>
            <p style='margin: 0; color: var(--radar-text-muted); font-size: 14px;'>Set your target location, budget, and criteria below - we'll scan for matching deals on your schedule.</p>
        </div>
    """, unsafe_allow_html=True)

    profile_name = st.text_input("Search Name", placeholder="e.g., Denver Wholesale Multi", key="hunt_new_profile_name")

    st.markdown("##### Target Location")
    with st.container(border=True):
        selected_state, selected_cities, zip_code = _render_location_picker("hunt_new")

    with st.form("hunt_criteria_form", clear_on_submit=True):
        panel_col1, panel_col2 = st.columns(2)
        with panel_col1:
            st.markdown("##### Property")
            with st.container(border=True):
                property_type = st.selectbox("Property Type", ["Single Family Home", "Condo", "Multi-Family", "Townhouse"])
        with panel_col2:
            st.markdown("##### Budget & Requirements")
            with st.container(border=True):
                max_price = st.number_input("Maximum Budget ($)", min_value=0, value=750000, step=25000)
                min_beds = st.number_input("Minimum Bedrooms", min_value=0, value=3, step=1)
                st.markdown("<div style='margin-bottom: 27px;'></div>", unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("##### Notifications & Schedule")
        with st.container(border=True):
            sub_col1, sub_col2 = st.columns(2)
            with sub_col1:
                recipient_email = st.text_input("Send Reports To", value=st.session_state.user_email)
            with sub_col2:
                schedule_time = st.text_input("Daily Scan Time (24h format)", value="08:00")

        st.markdown("<br>", unsafe_allow_html=True)
        submit_button = st.form_submit_button(":material/rocket_launch: Save Search", type="primary", use_container_width=True)

        if submit_button:
            if profile_name and selected_state and recipient_email:
                existing_names = db.get_all_reports(st.session_state.user_id)
                if profile_name not in existing_names and not plan_limits.is_within_limit(
                    st.session_state.user_role, st.session_state.user_plan, "saved_searches", len(existing_names)
                ):
                    pricing.render_plan_limit_notice("saved_searches", len(existing_names))
                elif zip_code and (not zip_code.isdigit() or len(zip_code) != 5):
                    st.error("ZIP code must be exactly 5 digits, or left blank.")
                else:
                    if selected_cities:
                        location_display = f"{', '.join(selected_cities)}, {selected_state}"
                    elif zip_code:
                        location_display = f"{zip_code}, {selected_state}"
                    else:
                        location_display = f"Any city in {selected_state}"

                    db.save_report_config(
                        st.session_state.user_id,
                        profile_name,
                        location_display,
                        int(max_price),
                        int(min_beds),
                        property_type,
                        recipient_email,
                        schedule_time,
                        state=selected_state,
                        cities_json=json.dumps(selected_cities) if selected_cities else None,
                        zip_code=zip_code or None,
                    )
                    st.toast("Search created!")
                    st.session_state.save_success_flash = f"'{profile_name}' saved successfully!"
                    _clear_location_picker("hunt_new")
                    st.rerun()
            else:
                st.error("Please fill in a search name, a state, and a recipient email before saving.")



def _clear_hunt_edit_target():
    st.session_state.hunt_edit_target = None


@st.dialog("Edit Search", on_dismiss=_clear_hunt_edit_target)
def _edit_search_dialog():
    """Reads whichever row's pencil icon was clicked from session_state -
    same reason property_card.py's _property_detail_dialog does the same
    thing: st.dialog's title is fixed at decoration time, so per-call data
    has to travel through session_state rather than a function argument
    the call site could vary.

    on_dismiss clears that target on every dismissal path (native X, Esc,
    click-outside), not just the in-dialog Cancel button - confirmed live
    on admin_controls.py's Manage User dialog that skipping this let a
    dialog dismissed via X reopen on the next unrelated click anywhere on
    the page, since the target session_state var was still set."""
    ctx = st.session_state.get("hunt_edit_target")
    if not ctx:
        st.write("No search selected.")
        return

    if ctx["state"]:
        st.caption(f"This search uses the precise city picker ({ctx['location']}). Target City below is display-only here - to change which cities are searched, delete this search and create a new one.")

    new_location = st.text_input("Target City", value=ctx["location"])
    col1, col2 = st.columns(2)
    with col1:
        property_types = ["Single Family Home", "Condo", "Multi-Family", "Townhouse"]
        new_property_type = st.selectbox("Property Type", property_types,
                                          index=property_types.index(ctx["property_type"]) if ctx["property_type"] in property_types else 0)
        new_max_price = st.number_input("Maximum Budget ($)", min_value=0, value=ctx["max_price"], step=25000)
    with col2:
        new_min_beds = st.number_input("Minimum Bedrooms", min_value=0, value=ctx["min_beds"], step=1)
        new_recipient_email = st.text_input("Send Reports To", value=ctx["recipient_email"])
    new_schedule_time = st.text_input("Daily Scan Time (24h format)", value=ctx["schedule_time"])

    st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)
    save_col, cancel_col = st.columns(2)
    with save_col:
        if st.button(":material/save: Save Changes", type="primary", use_container_width=True):
            if new_location and new_recipient_email:
                db.save_report_config(st.session_state.user_id, ctx["name"], new_location, int(new_max_price), int(new_min_beds),
                                       new_property_type, new_recipient_email, new_schedule_time,
                                       state=ctx["state"], cities_json=ctx["cities_json"], zip_code=ctx["zip_code"])
                st.session_state.hunt_edit_target = None
                st.toast("Search updated!")
                st.rerun()
            else:
                st.error("Please fill in all fields before saving.")
    with cancel_col:
        if st.button("Cancel", use_container_width=True):
            st.session_state.hunt_edit_target = None
            st.rerun()


def _clear_hunt_delete_target():
    st.session_state.hunt_delete_target = None


@st.dialog("Delete Search", on_dismiss=_clear_hunt_delete_target)
def _delete_search_dialog():
    ctx = st.session_state.get("hunt_delete_target")
    if not ctx:
        st.write("No search selected.")
        return

    st.warning(f"Delete **{ctx['name']}** ({ctx['location']})? This can't be undone.")
    confirm_col, cancel_col = st.columns(2)
    with confirm_col:
        if st.button(":material/delete_forever: Confirm Delete", type="primary", use_container_width=True):
            db.delete_report_config(st.session_state.user_id, ctx["name"])
            st.session_state.hunt_delete_target = None
            st.toast("Search deleted.")
            st.rerun()
    with cancel_col:
        if st.button("Cancel", use_container_width=True):
            st.session_state.hunt_delete_target = None
            st.rerun()


def _render_your_searches_tab():
    st.markdown("### Your Searches")
    # Cars gets its own dedicated flow now (components/car_search.py) and
    # never reaches this page - real estate only, no category branching
    # needed here anymore (see [[cars-category-feature]]).
    import sqlite3
    conn = sqlite3.connect(db.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT profile_name, location, max_price, min_beds, property_type, recipient_email, schedule_time, state, cities_json, zip_code "
            "FROM reports WHERE user_id=? AND (category IS NULL OR category='real_estate')", (int(st.session_state.user_id),))
        rows = cursor.fetchall()
    finally:
        conn.close()

    if not rows:
        _render_empty_state("crosshair", "No searches yet", "Create your first search in the \"New Search\" tab, then come back here to edit or delete it.")
        return

    df = pd.DataFrame(rows, columns=["Profile Name", "Location", "Max Budget ($)", "Min Beds", "Asset Type", "Target Email", "Scan Time", "_state", "_cities_json", "_zip_code"])
    grid_control1, grid_control2 = st.columns([2.5, 1])
    with grid_control1:
        search_query = st.text_input("Search", placeholder="Start typing a search name or location...")
    with grid_control2:
        page_size = st.selectbox("Rows per page", options=[10, 20, 50], index=1)

    if search_query:
        df = df[df["Profile Name"].str.contains(search_query, case=False, na=False) | df["Location"].str.contains(search_query, case=False, na=False)]

    total_rows = len(df)
    total_pages = max(1, (total_rows + page_size - 1) // page_size)
    current_page = min(st.session_state.get("your_searches_current_page", 1), total_pages)

    nav1, nav2, nav3 = st.columns([1, 2, 1])
    with nav1:
        if st.button(":material/chevron_left: Previous", disabled=current_page <= 1, use_container_width=True, key="your_searches_prev_page_btn"):
            st.session_state.your_searches_current_page = current_page - 1
            st.rerun()
    with nav2:
        st.markdown(f"<div style='text-align:center; padding-top:8px; color:var(--radar-text-muted); font-size:13px;'>Page {current_page} of {total_pages} · {total_rows} total searches</div>", unsafe_allow_html=True)
    with nav3:
        if st.button("Next :material/chevron_right:", disabled=current_page >= total_pages, use_container_width=True, key="your_searches_next_page_btn"):
            st.session_state.your_searches_current_page = current_page + 1
            st.rerun()

    df_paginated = df.iloc[(current_page - 1) * page_size: current_page * page_size].copy()
    df_paginated["Edit"] = ":material/edit:"
    df_paginated["Delete"] = ":material/delete:"
    visible_columns = ["Profile Name", "Location", "Max Budget ($)", "Min Beds", "Asset Type", "Target Email", "Scan Time", "Edit", "Delete"]
    # Key includes the page number so a page change starts with fresh
    # button-column state instead of a stale row index from the previous
    # page's row count potentially pointing at the wrong search (same
    # page-relative-indexing risk documented for Table View / admin Users).
    st.dataframe(
        df_paginated, use_container_width=True, hide_index=True,
        key=f"your_searches_grid_p{current_page}",
        column_order=visible_columns, height=len(df_paginated) * 35 + 38,
        column_config={
            "Edit": st.column_config.ButtonColumn("", width="small", type="tertiary", key="hunt_edit_btn_click"),
            "Delete": st.column_config.ButtonColumn("", width="small", type="tertiary", key="hunt_delete_btn_click"),
        },
    )

    edit_click = st.session_state.get("hunt_edit_btn_click")
    if edit_click and edit_click.get("row") is not None:
        row = df_paginated.iloc[edit_click["row"]]
        st.session_state.hunt_edit_target = {
            "name": row["Profile Name"], "location": row["Location"], "max_price": int(row["Max Budget ($)"]),
            "min_beds": int(row["Min Beds"]), "property_type": row["Asset Type"], "recipient_email": row["Target Email"],
            "schedule_time": row["Scan Time"], "state": row["_state"], "cities_json": row["_cities_json"], "zip_code": row["_zip_code"],
        }

    delete_click = st.session_state.get("hunt_delete_btn_click")
    if delete_click and delete_click.get("row") is not None:
        row = df_paginated.iloc[delete_click["row"]]
        st.session_state.hunt_delete_target = {"name": row["Profile Name"], "location": row["Location"]}

    if st.session_state.get("hunt_edit_target"):
        _edit_search_dialog()
    if st.session_state.get("hunt_delete_target"):
        _delete_search_dialog()