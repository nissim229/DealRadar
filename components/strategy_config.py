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
                    <div style='font-family:var(--radar-font-display); font-size:32px; font-weight:800; color:white; line-height:1.2;'>Manage Hunt Criteria</div>
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
                {"label": "Establish Hunt Criteria", "icon": ":material/add_circle:"},
                {"label": "Modify Hunt Criteria", "icon": ":material/edit:"},
                {"label": "Decommission Hunt Criteria", "icon": ":material/delete:"},
            ],
            key_prefix="hunt_nav",
        )

    with content_col:
        if active_section == "Establish Hunt Criteria":
            _render_establish_tab()
        elif active_section == "Modify Hunt Criteria":
            _render_modify_tab()
        else:
            _render_decommission_tab()


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



def _render_modify_tab():
    st.markdown("### Edit a Saved Search")
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

    if rows:
        df = pd.DataFrame(rows, columns=["Profile Name", "Location", "Max Budget ($)", "Min Beds", "Asset Type", "Target Email", "Scan Time", "_state", "_cities_json", "_zip_code"])
        grid_control1, grid_control2 = st.columns([2.5, 1])
        with grid_control1:
            search_query = st.text_input("Search", placeholder="Start typing a search name or location...")
        with grid_control2:
            page_size = st.selectbox("Rows per page", options=[10, 20, 50], index=1)

        if search_query:
            df = df[df["Profile Name"].str.contains(search_query, case=False, na=False) | df["Location"].str.contains(search_query, case=False, na=False)]

        modify_total_rows = len(df)
        modify_total_pages = max(1, (modify_total_rows + page_size - 1) // page_size)
        modify_current_page = min(st.session_state.get("modify_searches_current_page", 1), modify_total_pages)

        st.markdown("##### Your Searches")
        modify_nav1, modify_nav2, modify_nav3 = st.columns([1, 2, 1])
        with modify_nav1:
            if st.button(":material/chevron_left: Previous", disabled=modify_current_page <= 1, use_container_width=True, key="modify_searches_prev_page_btn"):
                st.session_state.modify_searches_current_page = modify_current_page - 1
                st.rerun()
        with modify_nav2:
            st.markdown(f"<div style='text-align:center; padding-top:8px; color:var(--radar-text-muted); font-size:13px;'>Page {modify_current_page} of {modify_total_pages} · {modify_total_rows} total searches</div>", unsafe_allow_html=True)
        with modify_nav3:
            if st.button("Next :material/chevron_right:", disabled=modify_current_page >= modify_total_pages, use_container_width=True, key="modify_searches_next_page_btn"):
                st.session_state.modify_searches_current_page = modify_current_page + 1
                st.rerun()

        df_paginated = df.iloc[(modify_current_page - 1) * page_size: modify_current_page * page_size]
        visible_columns = ["Profile Name", "Location", "Max Budget ($)", "Min Beds", "Asset Type", "Target Email", "Scan Time"]
        # Key includes the page number so a page change starts with a
        # clean selection instead of a stale row index from the
        # previous page's row count potentially pointing at the wrong
        # search (same page-relative-indexing risk documented for the
        # Table View / admin Users table selections).
        selected_row_data = st.dataframe(
            df_paginated, use_container_width=True, hide_index=True, on_select="rerun",
            selection_mode="single-row", key=f"modify_profiles_ledger_grid_p{modify_current_page}",
            column_order=visible_columns, height=len(df_paginated) * 35 + 38,
        )
        selected_rows_indices = selected_row_data.get("selection", {}).get("rows", [])

        edit_name, edit_loc, edit_type, edit_price, edit_beds, edit_email, edit_time, form_disabled_state = "", "", "Multi-Family", 750000, 3, st.session_state.user_email, "08:00", True
        edit_state, edit_cities_json, edit_zip = None, None, None

        if selected_rows_indices:
            row_index = selected_rows_indices[0]
            edit_name = df_paginated.iloc[row_index]["Profile Name"]
            edit_loc = df_paginated.iloc[row_index]["Location"]
            edit_price = int(df_paginated.iloc[row_index]["Max Budget ($)"])
            edit_beds = int(df_paginated.iloc[row_index]["Min Beds"])
            edit_type = df_paginated.iloc[row_index]["Asset Type"]
            edit_email = df_paginated.iloc[row_index]["Target Email"]
            edit_time = df_paginated.iloc[row_index]["Scan Time"]
            # Not editable from this tab (see location_picker_feature memory
            # for why) - carried through unchanged so saving other field
            # changes here can't silently wipe a search's precise
            # city/state selection back to the old unfiltered behavior.
            edit_state = df_paginated.iloc[row_index]["_state"]
            edit_cities_json = df_paginated.iloc[row_index]["_cities_json"]
            edit_zip = df_paginated.iloc[row_index]["_zip_code"]
            form_disabled_state = False
            if edit_state:
                st.caption(f"This search uses the precise city picker ({edit_loc}). Target City below is display-only here - to change which cities are searched, delete this search and create a new one.")
            st.success(f"Editing: {edit_name}")
        else:
            st.info("Click a row above to edit that search.")

        with st.form("modify_criteria_form", clear_on_submit=False):
            st.markdown("##### Edit Details")
            mod_col1, mod_col2 = st.columns(2)

            with mod_col1:
                st.text_input("Search Name (can't be changed)", value=edit_name, disabled=True)
                new_location = st.text_input("Target City", value=edit_loc, disabled=form_disabled_state)
                new_property_type = st.selectbox("Property Type", ["Single Family Home", "Condo", "Multi-Family", "Townhouse"], index=["Single Family Home", "Condo", "Multi-Family", "Townhouse"].index(edit_type) if edit_type in ["Single Family Home", "Condo", "Multi-Family", "Townhouse"] else 0, disabled=form_disabled_state)
            with mod_col2:
                new_max_price = st.number_input("Maximum Budget ($)", min_value=0, value=edit_price, step=25000, disabled=form_disabled_state)
                new_min_beds = st.number_input("Minimum Bedrooms", min_value=0, value=edit_beds, step=1, disabled=form_disabled_state)
                st.markdown("<div style='margin-bottom: 27px;'></div>", unsafe_allow_html=True)

            st.markdown("<br>", unsafe_allow_html=True)
            st.markdown("##### Notifications & Schedule")
            with st.container(border=True):
                mod_sub1, mod_sub2 = st.columns(2)
                with mod_sub1:
                    new_recipient_email = st.text_input("Send Reports To", value=edit_email, disabled=form_disabled_state)
                with mod_sub2:
                    new_schedule_time = st.text_input("Daily Scan Time (24h format)", value=edit_time, disabled=form_disabled_state)

            st.markdown("<br>", unsafe_allow_html=True)
            update_button = st.form_submit_button(":material/save: Save Changes", type="primary", use_container_width=True, disabled=form_disabled_state)

            if update_button:
                if new_location and new_recipient_email:
                    db.save_report_config(st.session_state.user_id, edit_name, new_location, int(new_max_price), int(new_min_beds), new_property_type, new_recipient_email, new_schedule_time,
                                           state=edit_state, cities_json=edit_cities_json, zip_code=edit_zip)
                    st.toast("Search updated!")
                    st.session_state.save_success_flash = f"'{edit_name}' updated successfully!"
                    st.rerun()
                else:
                    st.error("Please fill in all fields before saving.")
    else:
        _render_empty_state("crosshair", "No searches yet", "Create your first search in the \"Establish Hunt Criteria\" tab, then come back here to edit it.")



def _render_decommission_tab():
    st.markdown("### Delete a Saved Search")
    # Real estate only - see the note in _render_modify_tab above.
    import sqlite3
    conn = sqlite3.connect(db.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT profile_name, location, max_price, min_beds, property_type, recipient_email, schedule_time "
            "FROM reports WHERE user_id=? AND (category IS NULL OR category='real_estate')", (int(st.session_state.user_id),))
        rows = cursor.fetchall()
    finally:
        conn.close()

    if rows:
        df_del = pd.DataFrame(rows, columns=["Profile Name", "Location", "Max Budget ($)", "Min Beds", "Asset Type", "Target Email", "Scan Time"])
        del_grid_control1, del_grid_control2 = st.columns([2.5, 1])
        with del_grid_control1:
            search_query_del = st.text_input("Search", placeholder="Type a search name or location...", key="purge_search_input_unique_key")
        with del_grid_control2:
            del_page_size = st.selectbox("Rows per page", options=[10, 20, 50], index=1, key="decommission_page_size")

        if search_query_del:
            df_del = df_del[df_del["Profile Name"].str.contains(search_query_del, case=False, na=False) | df_del["Location"].str.contains(search_query_del, case=False, na=False)]

        del_total_rows = len(df_del)
        del_total_pages = max(1, (del_total_rows + del_page_size - 1) // del_page_size)
        del_current_page = min(st.session_state.get("decommission_current_page", 1), del_total_pages)

        st.markdown("##### Your Searches")
        del_nav1, del_nav2, del_nav3 = st.columns([1, 2, 1])
        with del_nav1:
            if st.button(":material/chevron_left: Previous", disabled=del_current_page <= 1, use_container_width=True, key="decommission_prev_page_btn"):
                st.session_state.decommission_current_page = del_current_page - 1
                st.rerun()
        with del_nav2:
            st.markdown(f"<div style='text-align:center; padding-top:8px; color:var(--radar-text-muted); font-size:13px;'>Page {del_current_page} of {del_total_pages} · {del_total_rows} total searches</div>", unsafe_allow_html=True)
        with del_nav3:
            if st.button("Next :material/chevron_right:", disabled=del_current_page >= del_total_pages, use_container_width=True, key="decommission_next_page_btn"):
                st.session_state.decommission_current_page = del_current_page + 1
                st.rerun()

        df_del_paginated = df_del.iloc[(del_current_page - 1) * del_page_size: del_current_page * del_page_size]
        selected_row_del = st.dataframe(
            df_del_paginated, use_container_width=True, hide_index=True, on_select="rerun", selection_mode="single-row",
            key=f"decommission_grid_p{del_current_page}", height=len(df_del_paginated) * 35 + 38,
        )
        selected_rows_indices_del = selected_row_del.get("selection", {}).get("rows", [])

        if selected_rows_indices_del:
            row_index_del = selected_rows_indices_del[0]
            target_delete_name = df_del_paginated.iloc[row_index_del]["Profile Name"]
            target_delete_loc = df_del_paginated.iloc[row_index_del]["Location"]

            st.markdown(f"""
                <div style='background-color: var(--radar-danger-bg); padding: var(--radar-space-4); border-radius: var(--radar-radius-md); border: 1px solid var(--radar-danger); margin-top: var(--radar-space-4); margin-bottom: var(--radar-space-4); display:flex; align-items:flex-start; gap:8px;'>
                    <span style='color: #991b1b; flex-shrink:0; margin-top:1px;'>{svg_icon("alert", size=15, color="#991b1b")}</span>
                    <span>
                        <span style='color: #991b1b; font-weight: 600;'>Warning:</span>
                        <span style='color: #b91c1c; font-size: 14px;'>Deleting this search will remove it permanently. This cannot be undone.</span>
                    </span>
                </div>
            """, unsafe_allow_html=True)

            with st.container(border=True):
                st.error(f"You're about to delete: {target_delete_name} ({target_delete_loc})")
                if st.button(":material/delete_forever: Delete This Search", type="primary", use_container_width=True):
                    db.delete_report_config(st.session_state.user_id, target_delete_name)
                    st.toast("Search deleted.")
                    st.rerun()
        else:
            st.info("Click a row above to select a search to delete.")
    else:
        _render_empty_state("crosshair", "Nothing to delete", "You don't have any saved searches yet - once you create one, it'll show up here.")