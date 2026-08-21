import os
import random
import sqlite3
import urllib.parse
import database as db
import email_utils
from dotenv import load_dotenv
from openai import OpenAI
from firecrawl import FirecrawlApp

# Load environment variables securely
load_dotenv()

# Initialize API Clients
# Guard against missing keys so the app can still start and use the local
# mock fallback - the OpenAI SDK now validates the key immediately on
# client creation, not just when a call is made, so a missing key would
# otherwise crash the entire app on import.
openai_api_key = os.getenv("OPENAI_API_KEY")
openai_client = OpenAI(api_key=openai_api_key) if openai_api_key else None

firecrawl_api_key = os.getenv("FIRECRAWL_API_KEY")
firecrawl_app = FirecrawlApp(api_key=firecrawl_api_key) if firecrawl_api_key else None

google_maps_api_key = os.getenv("GOOGLE_MAPS_API_KEY")

rentcast_api_key = os.getenv("RENTCAST_API_KEY")

# Fallback only - the real, admin-editable limit lives in
# db.get_rentcast_config()["monthly_limit"] (Admin Controls > Pricing),
# so upgrading to a paid RentCast plan with a higher quota takes effect
# immediately without a code change. This constant is used only if that
# config read somehow fails.
RENTCAST_MONTHLY_LIMIT = 50

# Maps this app's property type labels (what the UI shows) to RentCast's
# own enum values (what its API expects) - the two vocabularies are close
# but not identical ("Single Family Home" here vs. "Single Family" there).
RENTCAST_PROPERTY_TYPE_MAP = {
    "Single Family Home": "Single Family",
    "Condo": "Condo",
    "Multi-Family": "Multi-Family",
    "Townhouse": "Townhouse",
}


def is_rentcast_configured():
    # os.getenv returns "" (not None) for a key present in .env with nothing
    # after the "=", so checking truthiness here (not just "is not None")
    # matters - otherwise an empty RENTCAST_API_KEY= line would still read
    # as "configured" and burn a real API call before failing.
    return bool(rentcast_api_key)


def get_street_view_status(latitude, longitude):
    """Checks whether real Street View imagery exists at these coordinates,
    using Google's metadata endpoint (free - doesn't count against the paid
    image quota). Returns 'OK' if imagery exists, or a status string like
    'ZERO_RESULTS' if not. Returns None if no key is configured.

    IMPORTANT: this only controls what photo (if any) gets displayed - it
    must never be used to filter out or hide a property from results. A
    property with no available photo is still a real match and should still
    appear, just with the placeholder icon instead of a broken image."""
    if not google_maps_api_key or latitude is None or longitude is None:
        return None
    try:
        import requests
        url = "https://maps.googleapis.com/maps/api/streetview/metadata"
        params = {"location": f"{latitude},{longitude}", "key": google_maps_api_key}
        response = requests.get(url, params=params, timeout=5)
        return response.json().get("status")
    except Exception as e:
        # Best-effort only - per this function's own docstring, a failure
        # here just means the placeholder icon shows instead of a real
        # photo, never that the property gets hidden. Logged (not silent)
        # so a persistent failure (bad key, quota, network) is at least
        # visible to whoever's watching server logs.
        print(f"[Street View] Metadata check failed: {e}")
        return None


def get_street_view_image_url(latitude, longitude, width=400, height=300, heading=0):
    """Builds a Google Street View Static API image URL for the given coordinates,
    looking in the direction specified by heading (0-360 degrees, compass-style:
    0=North, 90=East, 180=South, 270=West). Returns None if no API key is
    configured, so callers can gracefully fall back to a placeholder icon."""
    if not google_maps_api_key or latitude is None or longitude is None:
        return None
    return (
        "https://maps.googleapis.com/maps/api/streetview"
        f"?size={width}x{height}&location={latitude},{longitude}&heading={heading}&key={google_maps_api_key}"
    )


def get_street_view_gallery_urls(latitude, longitude, width=400, height=300, angle_count=4):
    """Returns a list of Street View image URLs at evenly spaced compass headings
    around the same coordinates - a simple 'look around' gallery from one spot,
    since real per-listing photos (interior, etc.) aren't legally available without
    an MLS/IDX data partnership. Returns an empty list if no API key is configured."""
    if not google_maps_api_key or latitude is None or longitude is None:
        return []
    step = 360 // angle_count
    return [
        get_street_view_image_url(latitude, longitude, width=width, height=height, heading=i * step)
        for i in range(angle_count)
    ]

def build_zillow_search_url(address, mls_number=None):
    """Deep-links to Zillow's own search (confirmed working pattern:
    zillow.com/homes/{query}_rb/ - not an official Zillow partnership or
    API, just their public search page). Neither RentCast nor this app has
    real listing photos (see _fetch_rentcast_listings' note above), so this
    is the escape hatch for a user who wants to see actual listing photos
    for a real match.

    Deliberately address-only, mls_number accepted only for call-site
    symmetry with build_redfin_search_url. An MLS number is NOT a globally
    unique identifier - it's only unique within the MLS board that issued
    it, and different regional boards independently reuse the same numbers
    (confirmed live: searching Redfin for one MLS# alone surfaced unrelated
    properties in five different states - see build_redfin_search_url).
    There's no confirmed working format for combining address + MLS# in
    this specific _rb/ slug, so rather than guess at one and risk breaking
    the one pattern that IS confirmed to work, this stays address-only."""
    if not address:
        return None
    slug = address.strip().replace(" ", "-")
    return f"https://www.zillow.com/homes/{urllib.parse.quote(slug, safe='-,')}_rb/"


def build_redfin_search_url(address, mls_number=None):
    """Redfin has no confirmed public 'raw address/MLS# -> search results'
    URL the way Zillow does (its own search bar resolves queries through an
    internal autocomplete API before navigating, so a bare URL can't
    reliably reproduce that) - rather than guess and risk shipping a broken
    deep link, this routes through a site-scoped Google search instead.

    mls_number alone is NOT enough to disambiguate - confirmed live: a
    Google search for site:redfin.com "MLS# 1065651" (a real number from
    this app) returned five real Redfin listings in five different states,
    since MLS numbers are only unique per-MLS-board, not nationally. The
    address is what anchors the search to the right city/region; the
    quoted MLS# (when known) then narrows further within that to the exact
    listing - so both are always included together, never MLS# alone."""
    if not address and not mls_number:
        return None
    query_parts = [p for p in [address, f'"MLS# {mls_number}"' if mls_number else None] if p]
    search_text = "site:redfin.com " + " ".join(query_parts)
    return f"https://www.google.com/search?q={urllib.parse.quote(search_text)}"


def _log_rentcast_call_and_maybe_alert(success, user_id=None):
    """Wraps db.log_rentcast_call with the quota-threshold check, so every
    real RentCast call - success or failed-but-billed, both count against
    the quota - is checked against the admin-configured alert threshold in
    one place instead of duplicating the check at each of this module's
    call sites."""
    db.log_rentcast_call(success=success, user_id=user_id)
    _maybe_send_rentcast_quota_alert()


def _maybe_send_rentcast_quota_alert():
    """Emails every admin/super_admin once per calendar month, the moment
    RentCast usage this month first reaches the admin-configured alert
    threshold (default 85%) - so quota exhaustion, which silently degrades
    every scan to simulated data, is something staff actually get told
    about instead of only being visible if someone happens to open Admin
    Controls and check the usage card."""
    if db.was_rentcast_alert_sent_this_month():
        return
    config = db.get_rentcast_config()
    limit = config["monthly_limit"]
    if limit <= 0:
        return
    used = db.get_rentcast_usage_this_month()
    if (used / limit) * 100 < config["alert_threshold_pct"]:
        return
    db.mark_rentcast_alert_sent()
    for staff_email in db.get_admin_staff_emails():
        email_utils.send_rentcast_quota_alert_email(staff_email, used, limit, config["alert_threshold_pct"])


def _fetch_rentcast_listings(center_lat, center_lon, property_type, max_p, min_b, radius=25, user_id=None):
    """Calls RentCast's real active-listings API (v1/listings/sale) and maps
    the response into this app's internal listing shape. Returns None on
    any failure (no key, network error, bad response, unexpected shape) so
    the caller can fall back to the local simulator - this should never
    raise, since a flaky external API degrading gracefully beats crashing a
    scan. Filters server-side by location/property type, then re-checks
    price/beds client-side too, since RentCast's exact range-query syntax
    for those fields isn't something to bet a silent wrong-results bug on.

    Note: RentCast doesn't return listing photos in this response - so
    property cards for real listings still fall back to Street View
    exterior imagery, exactly like they already do for simulated ones.

    Cache-aside by AREA first (rounded lat/lon + property_type + radius,
    NOT price/beds - those are applied as a filter on whatever this
    returns, same as the client-side price/beds re-check below), so two
    different users' searches against the same city share one real
    RentCast call instead of each spending their own. A 24h TTL costs
    nothing real - RentCast itself only refreshes listings at least once a
    day. See [[deferred_rentcast_caching_plan]] for the full reasoning."""
    cache_key = f"{round(center_lat, 2)},{round(center_lon, 2)},{property_type},{radius}"
    cached_listings = db.get_cached_rentcast_area(cache_key)
    if cached_listings is not None:
        return [l for l in cached_listings if l["price"] <= max_p and l["beds"] >= min_b]

    usage_this_month = db.get_rentcast_usage_this_month()
    monthly_limit = db.get_rentcast_config().get("monthly_limit", RENTCAST_MONTHLY_LIMIT)
    if usage_this_month >= monthly_limit:
        print(f"[Agent] RentCast monthly limit reached ({usage_this_month}/{monthly_limit}) - skipping the real API call and using the local simulator instead.")
        return None

    try:
        import requests
        url = "https://api.rentcast.io/v1/listings/sale"
        params = {
            "latitude": center_lat,
            "longitude": center_lon,
            "radius": radius,
            "status": "Active",
            # RentCast bills per request, not per result - up to 500 listings
            # cost exactly the same one call as up to 50 did, and now that a
            # single area fetch is shared/cached across every search that
            # lands in it (see cache_key above), a wider haul per call
            # matters even more than before.
            "limit": 500,
        }
        rc_property_type = RENTCAST_PROPERTY_TYPE_MAP.get(property_type)
        if rc_property_type:
            params["propertyType"] = rc_property_type

        response = requests.get(url, params=params, headers={"X-Api-Key": rentcast_api_key}, timeout=10)
        # A response means this request counted against the plan's monthly
        # quota regardless of what it contains (RentCast bills per request
        # sent, not per useful result) - log it now, before any further
        # parsing that could itself raise and skip the log call below.
        if response.status_code != 200:
            _log_rentcast_call_and_maybe_alert(success=False, user_id=user_id)
            print(f"[Agent] RentCast API returned status {response.status_code}.")
            return None

        raw_results = response.json()
        if not isinstance(raw_results, list):
            _log_rentcast_call_and_maybe_alert(success=False, user_id=user_id)
            return None

        listings = []
        for item in raw_results:
            price = item.get("price")
            beds = item.get("bedrooms")
            lat = item.get("latitude")
            lon = item.get("longitude")
            if price is None or beds is None or lat is None or lon is None:
                continue
            listing_agent = item.get("listingAgent") or {}
            listing_office = item.get("listingOffice") or {}
            listings.append({
                "title": item.get("addressLine1") or item.get("formattedAddress", "Property"),
                "address": item.get("formattedAddress", ""),
                "price": int(price),
                "beds": int(beds),
                "baths": float(item.get("bathrooms") or 0),
                "sqft": item.get("squareFootage"),
                "property_type": item.get("propertyType", property_type),
                "url": "#",
                "latitude": lat,
                "longitude": lon,
                # Kept alongside formattedAddress specifically so callers can
                # exact-match filter results down to one searched city -
                # RentCast's radius search alone can't do that (see
                # fetch_live_listings_for_targets).
                "city": item.get("city"),
                # RentCast includes these directly in a real listing's own
                # response - legitimately licensed data, safe to display and
                # to use for a more precise Zillow/Redfin search (see
                # build_zillow_search_url/build_redfin_search_url), no
                # scraping needed. None for a mock/preview listing, which
                # has no real MLS record behind it.
                "mls_number": item.get("mlsNumber"),
                "mls_name": item.get("mlsName"),
                # Real HOA fee, confirmed live against RentCast's actual
                # response shape (an {"fee": <monthly dollars>} object, not
                # a flat field) rather than assumed - previously fetched
                # and silently discarded, so a listing with a real monthly
                # HOA was graded as if it had none. See underwriting.py's
                # compute_deal_metrics(hoa_monthly=...).
                "hoa_monthly": (item.get("hoa") or {}).get("fee"),
                # The rest of what RentCast returns per listing that this
                # app wasn't surfacing at all - the user's ask was "it
                # brings lots of data, we should show all of it", not just
                # HOA specifically.
                "year_built": item.get("yearBuilt"),
                "lot_size": item.get("lotSize"),
                "days_on_market": item.get("daysOnMarket"),
                "listed_date": item.get("listedDate"),
                "listing_type": item.get("listingType"),
                "status": item.get("status"),
                "county": item.get("county"),
                "state": item.get("state"),
                "zip_code": item.get("zipCode"),
                "listing_agent_name": listing_agent.get("name"),
                "listing_agent_phone": listing_agent.get("phone"),
                "listing_office_name": listing_office.get("name"),
                "listing_office_phone": listing_office.get("phone"),
                "listing_office_email": listing_office.get("email"),
                # The full, unmodified response for this listing - a catch-
                # all so nothing RentCast sends is silently dropped just
                # because this app doesn't have a named field for it yet
                # (e.g. `history`, which isn't worth its own column but is
                # still real data the user paid quota for).
                "rentcast_raw": item,
            })
        _log_rentcast_call_and_maybe_alert(success=True, user_id=user_id)
        db.save_rentcast_area_cache(cache_key, listings)
        return [l for l in listings if l["price"] <= max_p and l["beds"] >= min_b]
    except Exception as e:
        # An exception here (timeout, connection error, JSON parse failure)
        # means we can't be sure RentCast's server actually processed the
        # request, so it's deliberately NOT logged as a used call - only a
        # request that got an HTTP response back (success or not, above)
        # counts against the monthly quota.
        print(f"[Agent] RentCast API call failed: {e}")
        return None


def fetch_live_listings(location, property_type, max_price, min_beds, allow_live=True, radius=25, override_coords=None, user_id=None):
    """
    Dynamically routes coordinates and simulates property matches
    based on target location, price ceilings, and unit sizing.

    allow_live=False skips the real RentCast call even if a key is configured
    (used for anonymous/guest searches, which shouldn't spend metered quota
    on unauthenticated traffic - see RENTCAST_MONTHLY_LIMIT).

    radius (miles) is passed straight through to the real RentCast search -
    left at the original 25mi default for every existing caller, but
    fetch_live_listings_for_targets calls this with a much tighter radius
    per selected city instead of one wide sweep.

    override_coords=(lat, lon), when given, skips the city_directory/geocode
    lookup below entirely and searches exactly that point - used by
    fetch_live_listings_for_targets, which already resolved coordinates via
    the city_coords_cache (itself backed by validate_and_geocode_location),
    so there's no reason to re-geocode `location` as a string here too.
    """
    # Safe handling: if location arrives as a tuple or row object, extract clean string
    if isinstance(location, (tuple, list)) and len(location) > 0:
        loc_str = str(location[0]).lower()
        loc_display = str(location[0])
    else:
        loc_str = str(location).lower()
        loc_display = str(location)

    # Clean up tuple artifacts or parentheses from display string if passed raw from DB
    loc_display = loc_display.replace("('", "").replace("',)", "").replace("'", "")

    # Safe data type formatting for numeric boundaries calculations
    try:
        max_p = int(max_price[0]) if isinstance(max_price, (tuple, list)) else int(max_price)
    except (TypeError, ValueError):
        max_p = 750000

    try:
        min_b = int(min_beds[0]) if isinstance(min_beds, (tuple, list)) else int(min_beds)
    except (TypeError, ValueError):
        min_b = 3

    # These 4 specific cities get a hardcoded, network-independent lat/lon -
    # deliberately, not just historically: they're exactly
    # GUEST_QUICK_SEARCH_CITIES (analytics.py), the buttons an anonymous
    # visitor clicks first, and guest scans always run with allow_live=False
    # (never spend real RentCast quota), landing here. A live Nominatim
    # geocode call on that critical first-impression path would trade a
    # guaranteed-instant demo for one dependent on a third-party geocoder's
    # uptime/rate limits - not worth it for 4 fixed, known coordinates.
    city_directory = {
        "denver": {"lat": 39.7392, "lon": -104.9903},
        "boulder": {"lat": 40.0205, "lon": -105.2764},
        "austin": {"lat": 30.2672, "lon": -97.7431},
        "miami": {"lat": 25.7617, "lon": -80.1918},
    }

    # One shared pool of plausible-sounding street names for every mock
    # listing regardless of city - previously only the 4 cities above got
    # this variety (5-10 curated real streets each) while every other
    # searched city recycled the same 5 generic names. Merging them into
    # one wider pool means a city outside the guest-demo list gets the same
    # richness instead of a visibly smaller, repeated set.
    MOCK_STREET_NAMES = [
        "Main Street", "Market Street", "Central Avenue", "Pipeline Drive", "Strategic Way",
        "Larimer Street", "Blake Street", "Wynkoop Street", "Capital Avenue",
        "Pearl Street", "Pine Street", "Mapleton Avenue", "Canyon Boulevard", "Broadway",
        "Congress Avenue", "Rainey Street", "South Lamar Boulevard", "6th Street", "Silicon Hills Drive",
        "Brickell Avenue", "Biscayne Boulevard", "Ocean Drive", "Collins Avenue", "Flagler Street",
    ]
    street_options = MOCK_STREET_NAMES

    if override_coords is not None:
        center_lat, center_lon = override_coords
    else:
        # Find matching city key using a clean loop check string layout lookups
        matched_city = None
        for city_key in city_directory:
            if city_key in loc_str:
                matched_city = city_directory[city_key]
                break

        # If the location isn't one of our 4 fast-path cities, geocode it for
        # real so the mock listings (and Street View photos) land somewhere
        # sensible, instead of always defaulting to one generic rural point
        # with no imagery.
        if matched_city is None:
            geo_result = validate_and_geocode_location(loc_display)
            if geo_result:
                center_lat, center_lon = geo_result["latitude"], geo_result["longitude"]
            else:
                center_lat, center_lon = 39.8283, -98.5795  # Geographic Center of the US (Lebanon, Kansas)
        else:
            center_lat, center_lon = matched_city["lat"], matched_city["lon"]

    # If a RentCast API key is configured, try real listings first - falls
    # through to the local simulator below on any failure (no key, network
    # error, bad response), so this never breaks the app before a key has
    # been set up or if RentCast has a bad moment.
    if allow_live and is_rentcast_configured():
        real_listings = _fetch_rentcast_listings(center_lat, center_lon, property_type, max_p, min_b, radius=radius, user_id=user_id)
        if real_listings is not None:
            return real_listings
        print("[Agent] RentCast lookup failed - falling back to local simulator.")

    # Randomized match count each scan - feels more realistic than a fixed
    # number, since real searches rarely return the exact same count twice.
    listing_count = random.randint(3, 7)

    # Bias the price spread so at least one listing is a clear bargain and one
    # is a stretch near the max budget - under default underwriting assumptions
    # this reliably produces a mix of deal grades (green/yellow/red) to look at,
    # rather than leaving it to chance whether any listing clears the target yield.
    price_factors = [random.uniform(0.72, 0.98) for _ in range(listing_count)]
    price_factors[0] = random.uniform(0.35, 0.50)
    if listing_count > 1:
        price_factors[-1] = random.uniform(0.95, 0.99)

    listings = []
    for i in range(listing_count):
        jitter_lat = center_lat + random.uniform(-0.012, 0.012)
        jitter_lon = center_lon + random.uniform(-0.012, 0.012)
        street_name = random.choice(street_options)
        street_number = random.randint(100, 9999)
        listing_beds = min_b + random.choice([0, 0, 1, 1, 2])
        listing_baths = round(random.uniform(1.5, 3.5) * 2) / 2
        listing_sqft = int((900 + listing_beds * 400) * random.uniform(0.85, 1.25))

        # Mock listings exercise the exact same underwriting/rendering code
        # path as real RentCast ones (see compute_deal_metrics's
        # hoa_monthly and the "Full Details" property card section), so
        # they need to carry the same fields, not just enough to look
        # plausible in a card summary. HOA presence/amount is condo- and
        # townhouse-biased, matching how it actually skews in practice -
        # a single-family home has one some of the time (planned
        # communities), a condo/townhouse almost always does.
        has_hoa = random.random() < (0.8 if property_type in ("Condo", "Townhouse") else 0.25)
        mock_hoa = round(random.uniform(150, 450) if property_type in ("Condo", "Townhouse") else random.uniform(35, 180), -1) if has_hoa else 0

        listings.append({
            "title": f"{loc_display} Asset #{i + 1}",
            "address": f"{street_number} {street_name}, {loc_display}",
            "price": int(max_p * price_factors[i]),
            "beds": int(listing_beds),
            "baths": listing_baths,
            "sqft": listing_sqft,
            "property_type": property_type,
            "url": "#",
            "latitude": jitter_lat,
            "longitude": jitter_lon,
            "hoa_monthly": mock_hoa,
            "year_built": random.randint(1965, 2023),
            "lot_size": int(listing_sqft * random.uniform(1.2, 4.0)) if property_type not in ("Condo",) else None,
            "days_on_market": random.randint(1, 120),
            "listing_type": "Standard",
            "status": "Active",
        })

    return listings


def resolve_city_coords(city, state):
    """City/state -> (lat, lon), backed by database.py's city_coords_cache
    so a given city is only ever geocoded once. Returns None if the
    geocoder can't resolve it (bad city name, Nominatim down, etc.)."""
    cached = db.get_cached_city_coords(city, state)
    if cached is not None:
        return cached
    geo_result = validate_and_geocode_location(f"{city}, {state}")
    if geo_result is None:
        return None
    lat, lon = geo_result["latitude"], geo_result["longitude"]
    db.cache_city_coords(city, state, lat, lon)
    return (lat, lon)


def fetch_live_listings_for_targets(targets, property_type, max_price, min_beds, allow_live=True, user_id=None):
    """
    Runs a scan across one or more resolved points instead of a single
    wide-radius search - this is the fix for searches like "Boulder, CO"
    pulling in Thornton/Denver: each target gets its own tight 8-mile
    RentCast search (instead of one flat 25-mile sweep from the old
    single-point fetch_live_listings), and results are filtered down to
    listings actually inside the searched city when the target names one.

    `targets` is a list of dicts: {"lat", "lon", "label" (used for the
    listing's display address/title), "city_name" (the specific city being
    searched, for the exact-match filter - None for a state-wide "Any city"
    or ZIP-only search, which has nothing narrower to filter results against)}.

    Cost note: each target is its own real RentCast request when
    allow_live - selecting N cities spends N requests against the 50/month
    quota for one scan, not 1. Callers should cap how many targets they
    allow per search (the location picker caps it at 5) to keep this bounded.
    """
    seen_addresses = set()
    combined = []
    for target in targets:
        target_listings = fetch_live_listings(
            target["label"], property_type, max_price, min_beds,
            allow_live=allow_live, radius=8, override_coords=(target["lat"], target["lon"]), user_id=user_id,
        )
        city_name = target.get("city_name")
        for listing in target_listings:
            if city_name and listing.get("city") and listing["city"].strip().lower() != city_name.strip().lower():
                continue
            dedupe_key = listing.get("address") or listing.get("title")
            if dedupe_key in seen_addresses:
                continue
            seen_addresses.add(dedupe_key)
            combined.append(listing)
    return combined


def generate_offline_mock_report(profile_name, location, property_type, max_price, min_beds, listings):
    """Generates a high-fidelity local markdown mockup if OpenAI API limits are met."""
    if not listings:
        return f"""
# 📊 Real Estate Investment Report: {profile_name}
**Target Market:** {location} | **Asset Class:** {property_type} | *(Simulated Local Analysis due to API Quota Limit)*

---

### No Matching Properties Found
No active `{property_type}` listings under **${max_price:,}** with at least {min_beds} bed(s) were found in **{location}** for this scan. Try widening your price range, lowering the minimum bedrooms, or broadening the target area.
"""

    deal_rows = ""
    for item in listings:
        est_rent = int(item['price'] * 0.007)
        est_coc = "7.8%" if item['price'] < (max_price * 0.9) else "6.2%"
        deal_rows += f"| {item['address']} | ${item['price']:,} | {item['beds']} | ${est_rent}/mo | {est_coc} |\n"

    return f"""
# 📊 Real Estate Investment Report: {profile_name}
**Target Market:** {location} | **Asset Class:** {property_type} | *(Simulated Local Analysis due to API Quota Limit)*

---

### 1. Executive Market Summary
The real estate landscape in **{location}** continues to demonstrate robust baseline demand and strong macroeconomic indicators. Inventory for `{property_type}` assets under **${max_price:,}** remains highly competitive, requiring investors to target micro-markets aggressively. 

### 2. Structured Property Evaluation Matrix
Below is a comparative data model summarizing filtered pipeline properties meeting your exact criteria (Min Bedrooms: {min_beds}):

| Property Address | Purchase Price | Beds | Est. Market Rent | Est. Cash-on-Cash |
| :--- | :--- | :--- | :--- | :--- |
{deal_rows}

### 3. Investment Strategy & Underwriting Metrics
* **Financing Strategy:** Projections assume a 25% down payment structural architecture at market interest rates.
* **Cap Rate Environment:** Average compressed cap rates for the `{location}` perimeter hover between 4.8% and 5.5%.
* **Value-Add Potential:** Multi-bedroom layout adjustments represent the fastest mechanism to optimize gross yield metrics.

### 4. Next Steps & Tactical Recommendation
Property **`{listings[0]['address']}`** represents the optimal operational target. It offers a defensive margin below your maximum threshold budget of **${max_price:,}**, while presenting structural upside to scale monthly yield metrics. 
"""

def run_agent_workflow(profile_name, user_id, raw_listings=None):
    """Orchestration engine with dynamic automatic failover to local simulator.
    Scoped by user_id + profile_name together, since the reports table only
    guarantees uniqueness per (user_id, profile_name) pair - looking up by
    profile_name alone risked pulling another tenant's saved criteria.

    Looks the scan's criteria up from a saved `reports` row by name - for a
    scan whose criteria already lives in memory (an ad-hoc real-estate
    search or a guest preview), use run_agent_workflow_adhoc instead, which
    skips this lookup entirely rather than requiring a profile row to exist
    first (see [[nav_simplification_ad_hoc_search]])."""
    conn = sqlite3.connect(db.DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT location, max_price, min_beds, property_type FROM reports WHERE profile_name=? AND user_id=?",
            (str(profile_name), int(user_id))
        )
        row = cursor.fetchone()
    finally:
        conn.close()

    if not row:
        raise ValueError(f"Profile configuration '{profile_name}' not found.")

    location, max_price, min_beds, property_type = row
    return run_agent_workflow_adhoc(profile_name, user_id, location, property_type, max_price, min_beds, raw_listings)


def run_agent_workflow_adhoc(profile_name, user_id, location, property_type, max_price, min_beds, raw_listings=None):
    """The actual report-generation logic (OpenAI with local-simulator
    failover) - shared by run_agent_workflow (looks criteria up from a
    saved profile row first) and called directly by an ad-hoc scan that
    already has its criteria in memory and doesn't need - or might not
    even have - a saved profile row to look them up from."""
    if raw_listings is None:
        raw_listings = fetch_live_listings(location, property_type, max_price, min_beds)

    if openai_client is None:
        print(f"[Agent] No OpenAI API key configured. Using local simulator for {profile_name}...")
        return generate_offline_mock_report(profile_name, location, property_type, max_price, min_beds, raw_listings)

    # Unlike RentCast, every scan used to call OpenAI unconditionally
    # (live, mock, even anonymous guest previews) with no monthly cap at
    # all - a real, unbounded cost-risk. Mirrors the RentCast quota pattern:
    # once the admin-editable monthly limit is hit, fall back to the same
    # local mock report generator used for a missing key/exhausted OpenAI
    # quota, instead of placing another real call.
    openai_usage_this_month = db.get_openai_usage_this_month()
    openai_limit = db.get_openai_config().get("monthly_limit", 500)
    if openai_usage_this_month >= openai_limit:
        print(f"[Agent] OpenAI monthly limit reached ({openai_usage_this_month}/{openai_limit}) - using the local simulator instead.")
        return generate_offline_mock_report(profile_name, location, property_type, max_price, min_beds, raw_listings)

    try:
        print(f"[Agent] Contacting OpenAI API for {profile_name}...")
        prompt = f"Analyze: {location}, Budget: {max_price}, Listings: {str(raw_listings)}"

        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a professional investment analyst asset."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7
        )
        db.log_openai_call(user_id=user_id)
        return response.choices[0].message.content

    except Exception as e:
        # Check if the error is due to insufficient credit quota balance
        if "insufficient_quota" in str(e) or "429" in str(e):
            print("[Warning] OpenAI Quota Exhausted. Transitioning to local analytical simulator pipeline...")
            return generate_offline_mock_report(profile_name, location, property_type, max_price, min_beds, raw_listings)
        else:
            # Re-raise error if it's a structural syntax bug instead of a billing problem
            raise e

from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut
from geopy.distance import geodesic


def calculate_distance_miles(lat1, lon1, lat2, lon2):
    """Straight-line ('as the crow flies') distance in miles between two
    coordinates, using geopy's geodesic calculation. Not a driving distance -
    that would need a separate routing API - but useful as a quick reference
    (e.g. distance from a property to downtown, or to your workplace)."""
    if None in (lat1, lon1, lat2, lon2):
        return None
    try:
        return geodesic((lat1, lon1), (lat2, lon2)).miles
    except Exception:
        # Deliberately silent, not logged: this is a pure computation (no
        # I/O to fail) called once per property card render, so a malformed
        # coordinate here (e.g. a non-numeric value slipping past the
        # None-check above) would print on every single card - a real bug
        # elsewhere producing bad coordinates deserves its own fix at the
        # source, not console noise from every card that happens to render.
        return None


def is_places_api_configured():
    """Returns True if a Google Maps key is present (best-effort check - doesn't
    verify the Places API specifically is enabled/allowed on it, since that would
    require an extra network call). Used by the UI to distinguish 'not set up'
    from 'genuinely no results found nearby'."""
    return bool(google_maps_api_key)


def get_nearby_places(latitude, longitude, place_type, radius_meters=1500):
    """Looks up nearby points of interest (schools, transit stations, etc.) using
    Google's Places API Nearby Search. Requires the Places API to be enabled on
    your Google Cloud project AND added to your API key's allowed-APIs list
    (separate from the Street View Static API you already set up) - see setup
    notes. Returns an empty list (not an error) if the key/API isn't configured,
    so callers can gracefully skip the neighborhood section instead of crashing."""
    if not google_maps_api_key or latitude is None or longitude is None:
        return []
    try:
        import requests
        url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
        params = {
            "location": f"{latitude},{longitude}",
            "radius": radius_meters,
            "type": place_type,
            "key": google_maps_api_key,
        }
        response = requests.get(url, params=params, timeout=5)
        data = response.json()
        if data.get("status") not in ("OK", "ZERO_RESULTS"):
            print(f"[Places API] {data.get('status')}: {data.get('error_message', '')}")
            return []
        results = []
        for place in data.get("results", [])[:5]:
            place_lat = place.get("geometry", {}).get("location", {}).get("lat")
            place_lon = place.get("geometry", {}).get("location", {}).get("lng")
            distance = calculate_distance_miles(latitude, longitude, place_lat, place_lon)
            results.append({
                "name": place.get("name", "Unknown"),
                "rating": place.get("rating"),
                "distance_miles": distance,
            })
        return sorted(results, key=lambda r: r["distance_miles"] if r["distance_miles"] is not None else 999)
    except Exception as e:
        print(f"[Places API] Lookup failed: {e}")
        return []


def geocode_dealer(dealer_name, city, state, user_id=None):
    """Finds a specific car dealer's real address/coordinates via Google
    Places' Find Place From Text search - "{dealer_name}, {city}, {state}"
    as a free-text query, same as searching it on Google yourself, which is
    exactly what a real dealer address lookup needs: Auto.dev's own listings
    response only carries city/state/zip, no street address. Cached (see
    get_cached_dealer_coords/cache_dealer_coords) since the same dealer
    shows up across many searches - a cache hit costs nothing and isn't
    logged against the budget below.

    Google Places is pay-per-request billing on the admin's own Google
    Cloud account, not a fixed plan this app can read - places_config's
    monthly_limit is a self-declared budget the admin sets (Admin Controls),
    checked the same way RentCast's real plan limit is, just without any
    claim this app knows Google's actual quota. Returns None on missing
    input, no key configured, no match, or the self-declared budget already
    reached - callers should fall back to no coordinates (or a coarser
    city/ZIP-level geocode) rather than treat this as fatal."""
    if not google_maps_api_key or not dealer_name or not city:
        return None

    cached = db.get_cached_dealer_coords(dealer_name, city, state)
    if cached is not None:
        return cached

    usage_this_month = db.get_places_usage_this_month()
    monthly_limit = db.get_places_config()["monthly_limit"]
    if usage_this_month >= monthly_limit:
        print(f"[Places API] Monthly budget reached ({usage_this_month}/{monthly_limit}) - skipping dealer geocode.")
        return None

    try:
        import requests
        query = f"{dealer_name}, {city}, {state or ''}".strip(", ")
        url = "https://maps.googleapis.com/maps/api/place/findplacefromtext/json"
        params = {
            "input": query, "inputtype": "textquery", "fields": "geometry",
            "key": google_maps_api_key,
        }
        response = requests.get(url, params=params, timeout=5)
        data = response.json()
        candidates = data.get("candidates") or []
        db.log_places_call(success=bool(candidates), user_id=user_id)
        if not candidates:
            return None
        loc = candidates[0]["geometry"]["location"]
        lat, lon = loc["lat"], loc["lng"]
        db.cache_dealer_coords(dealer_name, city, state, lat, lon)
        return (lat, lon)
    except Exception as e:
        print(f"[Places API] Dealer geocode failed: {e}")
        return None


def validate_and_geocode_location(location_input_string):
    """
    Connects to OpenStreetMap to verify if a text location string exists.
    Returns a dictionary with clean strings and coordinates if valid, or None if fake.
    """
    if not location_input_string or len(str(location_input_string).strip()) < 3:
        return None
        
    # Initialize the open-source geolocator with a custom unique user-agent string identifier
    geolocator = Nominatim(user_agent="dealradar_property_scanner_v1")
    
    try:
        # Search the user's string text, restricting search parameters to the US for speed
        location_match = geolocator.geocode(location_input_string, country_codes="us", timeout=5)
        
        if location_match:
            return {
                "display_name": location_match.address,
                "latitude": location_match.latitude,
                "longitude": location_match.longitude
            }
        return None
    except (GeocoderTimedOut, Exception):
        # Fail-safety fallback: if internet lags or connection times out, pass the text through safely
        return {
            "display_name": str(location_input_string),
            "latitude": 39.8283,
            "longitude": -98.5795
        }