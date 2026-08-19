"""
car_engine.py
Mock data + deal-grading for DealRadar's used-car category preview, plus
(as of the Auto.dev integration below) the real listings fetch itself -
mirrors agent_engine.py's split between a mock property generator and
_fetch_rentcast_listings for the real one. generate_mock_car_listings stays
in place for the staff-only "Run Test Scan" path (see components/analytics.py's
existing allow_live convention) and as an offline fallback.
"""

import os
import random
import urllib.parse

import database as db
from dotenv import load_dotenv

load_dotenv()

autodev_api_key = os.getenv("AUTODEV_API_KEY")

# Auto.dev's free tier is a flat 1,000 calls/month, no admin-editable plan
# config yet (unlike RentCast's db.get_rentcast_config()) - this is a
# straightforward port of that same monthly-cap pattern for one vendor;
# promoting it to an admin-editable setting is natural follow-up work, not
# done here since only one plan tier exists to configure yet.
AUTODEV_MONTHLY_LIMIT = 1000


def is_autodev_configured():
    # os.getenv returns "" (not None) for a key present in .env with nothing
    # after the "=" - checking truthiness, not just "is not None", avoids
    # treating that as configured and burning a call before failing.
    return bool(autodev_api_key)

# (make, model) -> approximate new-MSRP baseline used to estimate a used
# listing's fair market value via simple mileage/age depreciation below.
# Deliberately a short, recognizable list (not real-time trim/package
# pricing) - good enough to make the mock market-value comparison behave
# sensibly, not a real valuation source.
CAR_CATALOG = {
    "Toyota": {"Camry": 28000, "Corolla": 23000, "RAV4": 30000, "Highlander": 40000, "Tacoma": 34000},
    "Honda": {"Civic": 24000, "Accord": 28000, "CR-V": 31000, "Pilot": 40000},
    "Ford": {"F-150": 38000, "Escape": 29000, "Explorer": 39000, "Mustang": 32000},
    "Chevrolet": {"Silverado": 39000, "Equinox": 28000, "Malibu": 26000, "Tahoe": 55000},
    "Tesla": {"Model 3": 42000, "Model Y": 47000},
    "BMW": {"3 Series": 45000, "X5": 62000},
    "Jeep": {"Wrangler": 34000, "Grand Cherokee": 39000},
    "Subaru": {"Outback": 30000, "Forester": 28000},
}

CAR_MAKES = sorted(CAR_CATALOG.keys())

DEALER_NAMES = [
    "Metro Auto Group", "Sunrise Motors", "Valley Preowned", "Highline Auto Sales",
    "Crossroads Motors", "Summit Auto Outlet", "Riverside Car Co.", "Trailhead Motors",
]


def models_for_make(make):
    return sorted(CAR_CATALOG.get(make, {}).keys())


def _estimate_market_value(make, model, year, mileage, current_year=2026):
    """Simple age + mileage depreciation off the catalog baseline - not a
    real valuation, just enough for "this listing is X% below a plausible
    market price" to mean something in the mock preview."""
    base = CAR_CATALOG.get(make, {}).get(model, 30000)
    age = max(0, current_year - year)
    age_factor = 0.86 ** age
    mileage_penalty = mileage * 0.04
    value = base * age_factor - mileage_penalty
    return max(2500, round(value, -2))


def generate_mock_car_listings(make=None, model=None, min_year=None, max_price=None,
                                max_mileage=None, zip_code=None, count=6):
    """Returns a list of mock car listing dicts, each already graded. Every
    field a real listings API would plausibly provide is present (even if
    only mocked) so the results UI and a future real integration share the
    exact same shape - see CarListing-shaped keys below."""
    min_year = min_year or 2016
    max_price = max_price or 45000
    max_mileage = max_mileage or 90000
    current_year = 2026

    candidates = []
    if make and make in CAR_CATALOG:
        model_pool = [(make, model)] if model and model in CAR_CATALOG[make] else [(make, m) for m in CAR_CATALOG[make]]
    else:
        model_pool = [(mk, m) for mk, models in CAR_CATALOG.items() for m in models]
    candidates = model_pool

    listings = []
    for i in range(count):
        pick_make, pick_model = random.choice(candidates)
        year = random.randint(min_year, current_year)
        mileage = random.randint(5000, max_mileage)
        market_value = _estimate_market_value(pick_make, pick_model, year, mileage, current_year)

        # Skew toward realistic listing prices clustered around market
        # value, with enough spread that some listings land as genuine
        # deals and some as overpriced - a flat random range wouldn't
        # produce a believable "most listings are close to fair, a few
        # stand out" distribution.
        price = max(2000, round(market_value * random.uniform(0.78, 1.15), -2))
        if price > max_price:
            price = round(max_price * random.uniform(0.85, 1.0), -2)

        listings.append({
            "id": f"mock-car-{i}-{random.randint(1000, 9999)}",
            "make": pick_make,
            "model": pick_model,
            "year": year,
            "mileage": mileage,
            "price": price,
            "market_value": market_value,
            "dealer_name": random.choice(DEALER_NAMES),
            "zip_code": zip_code or "80301",
            "vin": f"MOCK{random.randint(10**12, 10**13 - 1)}",
            "is_mock": True,
        })

    return listings


# Cars get their own badge wording rather than reusing
# underwriting.GRADE_STYLES verbatim - that dict's labels ("Negative Cash
# Flow", "Outstanding Deal") are written for a rental property's monthly
# cash flow, which a car purchase doesn't have. Same bg/fg/border colors
# (so render_deal_badge's visual language still matches everywhere else
# in the app), just car-appropriate copy - confirmed live that showing
# "Negative Cash Flow" on a used Jeep read as nonsensical.
CAR_GRADE_STYLES = {
    "critical": {"label": "🔴 Above Market", "bg": "#fee2e2", "fg": "#991b1b", "border": "#fca5a5"},
    "excellent": {"label": "🟢 Great Deal", "bg": "#d1fae5", "fg": "#065f46", "border": "#6ee7b7"},
    "average": {"label": "🟡 Fair Deal", "bg": "#fef3c7", "fg": "#92400e", "border": "#fcd34d"},
}


def render_car_deal_badge(grade):
    style = CAR_GRADE_STYLES[grade]
    return (
        f"<span style='background-color:{style['bg']}; color:{style['fg']}; "
        f"padding:6px 12px; border-radius:6px; font-weight:700; font-size:13px; "
        f"border:1px solid {style['border']}; white-space:nowrap;'>{style['label']}</span>"
    )


def compute_car_deal_metrics(price, market_value):
    """Grades a car listing the same three-tier way (excellent/average/
    critical) as underwriting.compute_deal_metrics grades a property, so
    render_deal_badge(grade) can be reused as-is on car cards - just graded
    on percent-below-market instead of cash-on-cash return."""
    if market_value <= 0:
        pct_below = 0.0
    else:
        pct_below = (market_value - price) / market_value * 100

    if pct_below >= 12:
        grade = "excellent"
    elif pct_below >= 0:
        grade = "average"
    else:
        grade = "critical"

    return {
        "price": price,
        "market_value": market_value,
        "pct_below_market": pct_below,
        "dollars_below_market": market_value - price,
        "grade": grade,
    }


def _estimate_market_values_from_comps(listings):
    """Sets market_value on each listing in-place using the other listings
    in the same batch as comps (same make/model, within 1 model year -
    widened to any year of the same make/model if that's too few) - the
    same comps-based idea RentCast-backed real-estate scans already use,
    just computed here instead of coming from a dedicated valuation
    endpoint, since Auto.dev's listings API doesn't return one. A listing
    with no comps at all (e.g. a one-result search) falls back to its own
    price, which grades it as an even "average" deal rather than crashing
    on an empty comp set."""
    def _same_model(a, b):
        # Case-insensitive - confirmed live that Auto.dev's own data isn't
        # consistently cased for the same model (a "2025 Toyota CAMRY" sat
        # alongside seventeen "Camry"s and matched none of them), which
        # silently excluded a real listing from its own comp group.
        return a["make"].lower() == b["make"].lower() and a["model"].lower() == b["model"].lower()

    for i, target in enumerate(listings):
        comps = [l for j, l in enumerate(listings)
                 if j != i and _same_model(l, target) and abs(l["year"] - target["year"]) <= 1]
        if len(comps) < 2:
            comps = [l for j, l in enumerate(listings) if j != i and _same_model(l, target)]
        if comps:
            avg_price = sum(c["price"] for c in comps) / len(comps)
            avg_mileage = sum(c["mileage"] for c in comps) / len(comps)
            # Same $0.04/mile scale generate_mock_car_listings' depreciation
            # uses, so a real and a mock listing "feel" comparably graded.
            mileage_adjustment = (avg_mileage - target["mileage"]) * 0.04
            target["market_value"] = max(1000, round(avg_price + mileage_adjustment, -2))
        else:
            target["market_value"] = target["price"]
    return listings


def fetch_live_car_listings(make, model, min_year, max_price, max_mileage, zip_code, radius=50, user_id=None, limit=20):
    """Calls Auto.dev's real vehicle-listings API (api.auto.dev/listings)
    and maps the response into this app's internal listing shape - mirrors
    agent_engine.py's _fetch_rentcast_listings: returns None on any failure
    (no key, quota exhausted, network error, bad response) so the caller
    can fall back to generate_mock_car_listings, and should never raise.

    market_value is estimated via _estimate_market_values_from_comps since
    Auto.dev's listings response carries no valuation field itself - see
    that function's docstring."""
    if not autodev_api_key:
        return None

    usage_this_month = db.get_autodev_usage_this_month()
    if usage_this_month >= AUTODEV_MONTHLY_LIMIT:
        print(f"[CarEngine] Auto.dev monthly limit reached ({usage_this_month}/{AUTODEV_MONTHLY_LIMIT}) - skipping the real API call and using the local simulator instead.")
        return None

    try:
        import requests
        current_year = 2026
        params = {
            "limit": min(limit, 20),
            # No explicit sort - "retailListing.price.asc" was tried first
            # and reliably surfaced Auto.dev's data-quality outliers first
            # (multiple real dealer listings with retailListing.price in
            # the $300-600 range for ordinary $20k+ vehicles, confirmed by
            # hand against their live API - almost certainly a monthly
            # payment or placeholder value leaking into the price field
            # upstream, not something this app can fix). The default sort
            # returns a normal, plausible-priced sample instead.
            "vehicle.year": f"{min_year or current_year - 10}-{current_year}",
        }
        if make and make != "Any make":
            params["vehicle.make"] = make
        if model and model != "Any model":
            params["vehicle.model"] = model
        if max_price:
            params["retailListing.price"] = f"0-{int(max_price)}"
        if zip_code:
            params["zip"] = zip_code
            params["distance"] = radius

        response = requests.get(
            "https://api.auto.dev/listings", params=params,
            headers={"Authorization": f"Bearer {autodev_api_key}", "Content-Type": "application/json"},
            timeout=10,
        )
        # A response means this request counted against the plan's monthly
        # quota regardless of what it contains - log it now, before any
        # further parsing that could itself raise and skip the log below.
        if response.status_code != 200:
            db.log_autodev_call(success=False, user_id=user_id)
            print(f"[CarEngine] Auto.dev API returned status {response.status_code}.")
            return None

        payload = response.json()
        raw_results = payload.get("data")
        if not isinstance(raw_results, list):
            db.log_autodev_call(success=False, user_id=user_id)
            return None

        listings = []
        for item in raw_results:
            vehicle = item.get("vehicle") or {}
            retail = item.get("retailListing") or {}
            history = item.get("history") or {}
            price, mileage, year = retail.get("price"), retail.get("miles"), vehicle.get("year")
            if price is None or mileage is None or year is None:
                continue
            if max_mileage and mileage > max_mileage:
                continue
            # Defensive floor, not just belt-and-suspenders: confirmed live
            # against Auto.dev's API that some dealer listings carry a
            # bogus few-hundred-dollar retailListing.price for an ordinary
            # vehicle (see the sort-param note above) - excluding anything
            # under $1,500 is far below any real used car's price, so this
            # can only ever drop broken data, never a genuine cheap listing.
            if price < 1500:
                continue
            listings.append({
                "id": item.get("vin") or vehicle.get("vin"),
                "vin": item.get("vin") or vehicle.get("vin"),
                "make": vehicle.get("make", make),
                "model": vehicle.get("model", model),
                "trim": vehicle.get("trim"),
                "year": int(year),
                "mileage": int(mileage),
                "price": int(price),
                "dealer_name": retail.get("dealer") or "Private Seller",
                "city": retail.get("city"),
                "state": retail.get("state"),
                "zip_code": retail.get("zip") or zip_code,
                "primary_image": retail.get("primaryImage"),
                "listing_url": retail.get("vdp"),
                "carfax_url": retail.get("carfaxUrl"),
                "cpo": bool(retail.get("cpo")),
                "accident_count": history.get("accidentCount"),
                "one_owner": history.get("oneOwner"),
                "owner_count": history.get("ownerCount"),
                "is_mock": False,
            })

        db.log_autodev_call(success=True, user_id=user_id)
        return _estimate_market_values_from_comps(listings) if listings else []
    except Exception as e:
        # An exception (timeout, connection error, JSON parse failure) means
        # we can't be sure Auto.dev's server actually processed the
        # request, so it's deliberately NOT logged as a used call - matches
        # _fetch_rentcast_listings' same reasoning.
        print(f"[CarEngine] Auto.dev API call failed: {e}")
        return None


def build_autotrader_search_url(year, make, model):
    """Same site-scoped-Google-search pattern agent_engine.py's
    build_redfin_search_url uses - AutoTrader/Cars.com have no confirmed
    public raw-query search URL the way Zillow does, so rather than guess
    at one and risk a broken deep link, this routes through Google."""
    query = " ".join(str(p) for p in [year, make, model] if p)
    return f"https://www.google.com/search?q=site%3Aautotrader.com+{urllib.parse.quote(query)}"


def build_carsdotcom_search_url(year, make, model):
    query = " ".join(str(p) for p in [year, make, model] if p)
    return f"https://www.google.com/search?q=site%3Acars.com+{urllib.parse.quote(query)}"
