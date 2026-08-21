"""
components/analytics_scan_engine.py
Scan orchestration: turning raw listings into the persisted coord-list
shape, resolving search criteria into real/mock listings, loading a
saved search's criteria back for a Quick Access chip, the guest ad-hoc
demo scan, and the real scan executor - split out of
components/analytics.py (Section 5 monolith-split plan). Kept together
as one module since _execute_scan and _run_guest_demo_scan both call
into _build_coord_list/_fetch_listings_for_criteria, exactly as the
original code's own docstrings describe (shared between the real and
guest scan paths).
"""
import json
import streamlit as st
import database as db
import agent_engine as engine
import email_utils
import roles
import plan_limits

from underwriting import compute_deal_metrics
from scan_loading import render_scan_loading_radar
from components.analytics_atoms import _safe_hoa


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
    except Exception as e:
        print(f"[Analytics] Live scan execution failed: {e}")
        st.error("Something went wrong running this scan. Please try again.")
    finally:
        loading_placeholder.empty()
