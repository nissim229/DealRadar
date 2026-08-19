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
import time
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


# In-process cache for the facets-based make/model lookups below - module-
# level dict, not st.cache_data (car_engine.py otherwise has no Streamlit
# dependency, matching agent_engine.py's own split between logic and UI).
# Resets on server restart, which just costs one extra API call on first
# use after a restart - fine for data (makes/models) that doesn't change
# within a day, and shared across every user's search rather than
# per-session, so it amortizes to near-zero calls regardless of traffic.
_facets_cache = {}
_FACETS_CACHE_TTL_SECONDS = 6 * 3600


def _facet_labels_to_list(facet_dict):
    # Facet keys look like "Ford (17487)" - the count is Auto.dev's own
    # inventory count for that value, not something this app tracks, so
    # it's stripped rather than parsed and displayed.
    return sorted(k.rsplit(" (", 1)[0] for k in facet_dict.keys())


def _fetch_autodev_facets(extra_params, user_id=None):
    """One shared call path for both get_available_makes and
    get_available_models - returns the full facets dict, or None on any
    failure (no key, quota exhausted, network error), same never-raise
    contract as fetch_live_car_listings."""
    if not autodev_api_key:
        return None
    usage_this_month = db.get_autodev_usage_this_month()
    if usage_this_month >= AUTODEV_MONTHLY_LIMIT:
        return None
    try:
        import requests
        params = {"limit": 1, "includes": "facets"}
        params.update(extra_params)
        response = requests.get(
            "https://api.auto.dev/listings", params=params,
            headers={"Authorization": f"Bearer {autodev_api_key}", "Content-Type": "application/json"},
            timeout=10,
        )
        if response.status_code != 200:
            db.log_autodev_call(success=False, user_id=user_id)
            return None
        db.log_autodev_call(success=True, user_id=user_id)
        return response.json().get("facets")
    except Exception as e:
        print(f"[CarEngine] Auto.dev facets call failed: {e}")
        return None


def _cached_facets(cache_key, fetch_fn):
    now = time.time()
    cached = _facets_cache.get(cache_key)
    if cached and (now - cached[0]) < _FACETS_CACHE_TTL_SECONDS:
        return cached[1]
    value = fetch_fn()
    if value:
        _facets_cache[cache_key] = (now, value)
    return value


def get_available_makes(user_id=None):
    """Live list of makes actually in Auto.dev's current US inventory,
    replacing the old fixed CAR_CATALOG (8 makes) with the real thing - a
    single search earlier this session using the hardcoded list couldn't
    even offer "Acura" or "RAM", both of which showed up in real results.
    Falls back to the static CAR_MAKES if Auto.dev isn't configured, quota
    is exhausted, or the call fails, so the Make dropdown never breaks."""
    def _fetch():
        facets = _fetch_autodev_facets({}, user_id=user_id)
        return _facet_labels_to_list(facets["makes"]) if facets and facets.get("makes") else None

    return _cached_facets("makes", _fetch) or CAR_MAKES


def get_available_models(make, user_id=None):
    """Same idea as get_available_makes, scoped to one make - falls back
    to the static CAR_CATALOG's models for that make (empty list for a
    make not in that small catalog, e.g. one only the live facets know
    about) on any failure."""
    if not make or make == "Any make":
        return []

    def _fetch():
        facets = _fetch_autodev_facets({"vehicle.make": make}, user_id=user_id)
        return _facet_labels_to_list(facets["models"]) if facets and facets.get("models") else None

    return _cached_facets(f"models:{make.lower()}", _fetch) or models_for_make(make)


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

        metrics = compute_car_deal_metrics(price, market_value)
        listings.append({
            "id": f"mock-car-{i}-{random.randint(1000, 9999)}",
            "make": pick_make,
            "model": pick_model,
            "year": year,
            "mileage": mileage,
            "price": price,
            "dealer_name": random.choice(DEALER_NAMES),
            "zip_code": zip_code or "80301",
            "vin": f"MOCK{random.randint(10**12, 10**13 - 1)}",
            "is_mock": True,
            **metrics,
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
    """Base three-tier grade (excellent/average/critical) from price vs.
    market value alone - the whole story for a mock listing (no accident/
    owner/usage-type data exists to adjust with), and the starting point
    _grade_real_listings further adjusts for a real one. Mock listings also
    get has_reliable_grade=True and empty grade_adjustments so every
    listing dict - mock or real - carries the same fields regardless of
    source, and callers (car_card.py, car_search.py) never need to branch
    on is_mock to know what to display."""
    if market_value <= 0:
        pct_below = 0.0
    else:
        pct_below = (market_value - price) / market_value * 100

    return {
        "price": price,
        "market_value": market_value,
        "pct_below_market": pct_below,
        "dollars_below_market": market_value - price,
        "grade": _grade_tier(pct_below),
        "grade_adjustments": [],
        "has_reliable_grade": True,
    }


_GRADE_TIERS = ["excellent", "average", "critical"]


def _grade_tier(pct_below):
    if pct_below >= 12:
        return "excellent"
    elif pct_below >= 0:
        return "average"
    return "critical"


def _downgrade_tier(grade, steps):
    return _GRADE_TIERS[min(len(_GRADE_TIERS) - 1, _GRADE_TIERS.index(grade) + steps)]


def _same_model(a, b):
    # Case-insensitive - confirmed live that Auto.dev's own data isn't
    # consistently cased for the same model (a "2025 Toyota CAMRY" sat
    # alongside seventeen "Camry"s and matched none of them), which
    # silently excluded a real listing from its own comp group.
    return a["make"].lower() == b["make"].lower() and a["model"].lower() == b["model"].lower()


def _median(values):
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2


def _drop_price_outliers(listings):
    """Removes listings whose price looks like broken upstream data rather
    than a real price - confirmed live against Auto.dev's own API that a
    meaningful share of dealer-fed listings carry a wrong price (a cluster
    of ordinary $20k+ BMWs listed at $1,000-$1,700, and separately a
    listing whose $5,000 "price" was actually its dealer's discount
    amount, not the selling price). A fixed dollar floor can't catch the
    second kind - it's compared against its own comp group's median price
    instead: same make/model, at least 3 other listings to get a median
    that isn't itself skewed by one bad value, and a price under half that
    median is treated as broken, not "an incredible deal" - see
    [[feedback_honest_deal_grading]]. Groups too small to get a meaningful
    median (fewer than 3) are left alone here; those listings simply won't
    have enough comps to earn a confident grade later, which is the
    correct honest outcome for data this app can't independently verify."""
    by_model = {}
    for l in listings:
        by_model.setdefault((l["make"].lower(), l["model"].lower()), []).append(l)

    dropped = 0
    survivors = []
    for group in by_model.values():
        if len(group) >= 3:
            group_median = _median([l["price"] for l in group])
            for l in group:
                if l["price"] < group_median * 0.5:
                    dropped += 1
                    continue
                survivors.append(l)
        else:
            survivors.extend(group)
    if dropped:
        print(f"[CarEngine] Dropped {dropped} listing(s) with a price under half their comp group's median - likely broken upstream data, not real bargains.")
    return survivors


def _grade_real_listings(listings):
    """The real-data grading pass: drops price outliers first (see
    _drop_price_outliers), then for each survivor computes market value
    from its comp group (same make/model, within 1 model year - widened to
    any year of the same make/model if that's too few) and a base price-
    vs-market grade, then applies visible downgrades for accident history,
    owner count, rental/fleet usage, and materially-above-comps mileage -
    each one is recorded in grade_adjustments so the UI can show its
    reasoning instead of presenting one opaque number. A listing with zero
    comps gets has_reliable_grade=False and no grade at all rather than a
    default "average" that would falsely look like a real assessment -
    see [[feedback_honest_deal_grading]]."""
    listings = _drop_price_outliers(listings)

    for i, target in enumerate(listings):
        comps = [l for j, l in enumerate(listings)
                 if j != i and _same_model(l, target) and abs(l["year"] - target["year"]) <= 1]
        if len(comps) < 2:
            comps = [l for j, l in enumerate(listings) if j != i and _same_model(l, target)]

        if not comps:
            target.update(market_value=None, pct_below_market=None, dollars_below_market=None,
                           grade=None, grade_adjustments=[], has_reliable_grade=False)
            continue

        comp_median_price = _median([c["price"] for c in comps])
        comp_median_mileage = _median([c["mileage"] for c in comps])
        # Same $0.04/mile scale generate_mock_car_listings' depreciation
        # uses, so a real and a mock listing "feel" comparably graded.
        mileage_adjustment = (comp_median_mileage - target["mileage"]) * 0.04
        market_value = max(1000, round(comp_median_price + mileage_adjustment, -2))
        pct_below = (market_value - target["price"]) / market_value * 100 if market_value > 0 else 0.0

        grade = _grade_tier(pct_below)
        adjustments = []

        accident_count = target.get("accident_count")
        if accident_count and accident_count >= 2:
            grade = _downgrade_tier(grade, 2)
            adjustments.append(f"{accident_count} reported accidents")
        elif accident_count == 1:
            grade = _downgrade_tier(grade, 1)
            adjustments.append("1 reported accident")

        owner_count = target.get("owner_count")
        if owner_count and owner_count >= 4:
            grade = _downgrade_tier(grade, 1)
            adjustments.append(f"{owner_count} previous owners")

        usage_type = (target.get("usage_type") or "").lower()
        if "rental" in usage_type or "fleet" in usage_type:
            adjustments.append(f"{target['usage_type']} vehicle")
            grade = _downgrade_tier(grade, 1)

        if comp_median_mileage and target["mileage"] > comp_median_mileage * 1.25:
            grade = _downgrade_tier(grade, 1)
            adjustments.append("well above typical mileage for similar listings")

        target.update(
            market_value=market_value, pct_below_market=pct_below,
            dollars_below_market=market_value - target["price"],
            grade=grade, grade_adjustments=adjustments, has_reliable_grade=True,
        )

    return listings


def fetch_live_car_listings(make, model, min_year, max_price, max_mileage, zip_code, radius=50, user_id=None, limit=20):
    """Calls Auto.dev's real vehicle-listings API (api.auto.dev/listings)
    and maps the response into this app's internal listing shape - mirrors
    agent_engine.py's _fetch_rentcast_listings: returns None on any failure
    (no key, quota exhausted, network error, bad response) so the caller
    can fall back to generate_mock_car_listings, and should never raise.

    market_value and grade come from _grade_real_listings since Auto.dev's
    listings response carries no valuation field itself - see that
    function's docstring."""
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
                "usage_type": history.get("usageType"),
                "is_mock": False,
            })

        db.log_autodev_call(success=True, user_id=user_id)
        return _grade_real_listings(listings) if listings else []
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
