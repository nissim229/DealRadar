"""
car_engine.py
Mock data + deal-grading for DealRadar's used-car category preview. This
exists to let the UI (search form, results cards) be seen and clicked
through end-to-end before any real listings API is wired in - mirrors how
agent_engine.py's mock property generator lets the real-estate side run
with allow_live=False. No network calls, no API key, nothing here should
ever be mistaken for real inventory - every listing carries is_mock=True.

Swapping in a real API later means writing a fetch_live_car_listings(...)
alongside this, the same way _fetch_rentcast_listings sits next to
agent_engine.py's mock generator - this module doesn't need to change.
"""

import random
import urllib.parse

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
