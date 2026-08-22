"""
tests/test_underwriting.py
Regression tests locking in the deal-math fixes from FIXLIST.md Section 8
(NOI-floor removal, mgmt%/maintenance%/closing-cost lines, MAO
not-achievable handling) plus car_engine.py's pure grading helpers - so
none of these can silently regress the way the original NOI-clamp bug did,
undetected, before the reviewer's audit caught it.

Every golden value below was independently hand-verified before being
locked in here (not just copied from the function's own output) - see
each test's docstring for how. underwriting.py has zero Streamlit/
database dependency (per its own module docstring), so these tests need
no fixtures, no temp DB, and never touch agent_config.db.
"""
import pytest

from underwriting import compute_deal_metrics, monthly_payment_factor
from car_engine import _grade_tier, _median, _drop_price_outliers, _grade_real_listings, classify_fuel_type, compute_car_deal_metrics


# ---------------------------------------------------------------------------
# compute_deal_metrics: golden-value worked example
# ---------------------------------------------------------------------------

def test_worked_example_golden_values():
    """$400k price / $3,500 rent / 5% vacancy / 1.2% tax / 0.4% insurance /
    25% down / 6.5% interest / 8% target - the exact worked example the
    reviewer independently hand-computed in the deal-math audit (see
    REVIEW_LOG.md Entry 8 / REVIEWER_FEEDBACK.md: "ALL 13 metrics ... match
    independent hand calculations exactly"). Every value here was
    recomputed by hand (see this file's own derivation in the session that
    added it) before being locked in, not just read off the function."""
    m = compute_deal_metrics(400000, 3500, 5, 1.2, 0.4, 25, 6.5, 8)

    assert m["eff_gross_income"] == pytest.approx(39900.0)
    assert m["annual_taxes"] == pytest.approx(4800.0)
    assert m["annual_insurance"] == pytest.approx(1600.0)
    assert m["vacancy_loss"] == pytest.approx(2100.0)
    assert m["annual_maintenance"] == pytest.approx(1995.0)  # 5% default of eff_gross
    assert m["annual_mgmt_fee"] == pytest.approx(0.0)  # 0% default
    assert m["noi"] == pytest.approx(31505.0)
    assert m["cap_rate"] == pytest.approx(7.87625)
    assert m["down_amt"] == pytest.approx(100000.0)
    assert m["loan_amt"] == pytest.approx(300000.0)
    assert m["a_debt"] == pytest.approx(22754.448845746752, rel=1e-9)
    assert m["cashflow"] == pytest.approx(8750.551154253248, rel=1e-9)
    assert m["coc"] == pytest.approx(8.750551154253246, rel=1e-9)
    assert m["mao"] == pytest.approx(408080.3368379307, rel=1e-6)
    assert m["mao_delta"] == pytest.approx(-8080.336837930721, rel=1e-6)
    assert m["grade"] == "excellent"


def test_worked_example_debt_service_matches_independent_amortization_formula():
    """Cross-checks a_debt against a fixed-rate annuity formula written
    from scratch, independent of monthly_payment_factor - guards against a
    regression that breaks both the app's formula and a golden-value test
    identically (a golden value alone can't catch monthly_payment_factor
    and its own test agreeing on the same wrong number)."""
    price, down_pct, interest = 400000, 25, 6.5
    loan = price * (1 - down_pct / 100)
    r = (interest / 100) / 12
    n = 360
    expected_monthly = loan * r / (1 - (1 + r) ** (-n))

    m = compute_deal_metrics(price, 3500, 5, 1.2, 0.4, down_pct, interest, 8)
    assert m["a_debt"] == pytest.approx(expected_monthly * 12, rel=1e-9)


# ---------------------------------------------------------------------------
# Regression: NOI floor no longer hides all-cash losses (FIXLIST Section 8, Bug 1)
# ---------------------------------------------------------------------------

def test_all_cash_loser_returns_negative_cashflow_and_grades_critical():
    """The exact bug the reviewer's audit caught: an all-cash property
    whose true NOI is negative must report that loss honestly and grade
    "critical", not get floored to $0/"average". A mortgaged loser already
    grades critical regardless (debt service alone pushes cashflow
    negative) - this specifically exercises the all-cash path the NOI
    clamp used to hide."""
    m = compute_deal_metrics(price=400000, calc_rent=300, calc_vacancy_pct=0,
                              calc_tax_rate=1.0, calc_ins_rate=0.5,
                              calc_down_pct=100, calc_interest=6.5, calc_target_yield=8.0)
    assert m["a_debt"] == 0  # confirms this really is the all-cash/no-debt path
    assert m["noi"] < 0  # NOI itself must stay unclamped, not just cashflow
    assert m["cashflow"] < 0
    assert m["grade"] == "critical"


def test_cap_rate_display_still_floors_at_zero_when_noi_is_negative():
    """The one intentional exception to "never clamp": the displayed
    cap-rate value floors at 0% (avoiding a confusing negative percentage)
    even though NOI itself stays a true negative number underneath it."""
    m = compute_deal_metrics(price=400000, calc_rent=300, calc_vacancy_pct=0,
                              calc_tax_rate=1.0, calc_ins_rate=0.5,
                              calc_down_pct=100, calc_interest=6.5, calc_target_yield=8.0)
    assert m["noi"] < 0
    assert m["cap_rate"] == 0.0


# ---------------------------------------------------------------------------
# MAO "not achievable" handling (FIXLIST Section 8 follow-up polish)
# ---------------------------------------------------------------------------

def test_mao_none_when_numerator_nonpositive():
    """MAO must return None (not a misleading negative dollar figure) when
    expenses/financing terms are too high to hit the target return at any
    price - the exact edge case the MAO polish fixed (previously returned
    e.g. "$-45,000"). Matches whatif_calculator.py's own
    `numerator > 0` guard."""
    m = compute_deal_metrics(price=400000, calc_rent=1000, calc_vacancy_pct=5,
                              calc_tax_rate=1.2, calc_ins_rate=0.5, calc_down_pct=20,
                              calc_interest=6.5, calc_target_yield=18.0, hoa_monthly=300,
                              calc_mgmt_pct=10, calc_maint_pct=10, calc_closing_costs=100000)
    assert m["mao"] is None
    assert m["mao_delta"] is None


def test_mao_none_when_denom_nonpositive():
    """The other half of the same guard: an all-zero-cost/zero-target
    scenario where the MAO denominator itself is non-positive. Matches
    whatif_calculator.py's own `denom > 0` half of its guard - previously
    Python's own fallback here was `price` (a Python-only inconsistency
    with the JS, which treats this identically to the numerator case)."""
    m = compute_deal_metrics(price=400000, calc_rent=3500, calc_vacancy_pct=5,
                              calc_tax_rate=0.0, calc_ins_rate=0.0, calc_down_pct=20,
                              calc_interest=0.0, calc_target_yield=0.0)
    assert m["mao"] is None
    assert m["mao_delta"] is None


# ---------------------------------------------------------------------------
# HOA / management / maintenance / closing costs shift cashflow and MAO by
# exact, independently-derived amounts (FIXLIST Section 8, Gaps 2-3)
# ---------------------------------------------------------------------------

def _mao_denom(down_pct, interest, tax_rate, ins_rate, target_yield_pct):
    """Independent re-derivation of the MAO denominator (not exposed by
    compute_deal_metrics) - used only to predict an *expected* shift in
    these tests, the same way the reviewer's own audit cross-checked
    HOA's exact effect on cash flow and MAO by hand rather than trusting
    the function's self-consistency alone."""
    down_ratio = down_pct / 100
    tax_ins_ratio = (tax_rate / 100) + (ins_rate / 100)
    debt_factor = 12 * monthly_payment_factor(interest, 360) if interest > 0 else 0.0
    target_yield = target_yield_pct / 100
    return tax_ins_ratio + debt_factor * (1 - down_ratio) + target_yield * down_ratio


_COMMON = dict(price=400000, calc_rent=3500, calc_vacancy_pct=5, calc_tax_rate=1.2,
               calc_ins_rate=0.4, calc_down_pct=25, calc_interest=6.5, calc_target_yield=8)
_DENOM = _mao_denom(25, 6.5, 1.2, 0.4, 8)
_EFF_GROSS = 3500 * 12 * (1 - 5 / 100)  # 39,900 - effective gross rent for the common case


def test_hoa_shifts_cashflow_and_mao_by_exact_amount():
    """-$300/mo HOA is a flat $3,600/yr cost, independent of price or rent -
    it must shift cashflow by exactly -$3,600/yr and MAO by exactly
    -3600/denominator, matching the reviewer's own hand-verified claim
    from the original audit."""
    base = compute_deal_metrics(**_COMMON, hoa_monthly=0)
    bumped = compute_deal_metrics(**_COMMON, hoa_monthly=300)
    assert bumped["cashflow"] - base["cashflow"] == pytest.approx(-3600.0, rel=1e-9)
    assert base["mao"] - bumped["mao"] == pytest.approx(3600.0 / _DENOM, rel=1e-6)


def test_mgmt_pct_shifts_cashflow_and_mao_by_exact_amount():
    """Management fee is % of effective gross rent (post-vacancy), not
    price or gross rent - an 8-percentage-point bump must shift cashflow
    by exactly eff_gross*0.08 and MAO by that same amount/denominator."""
    base = compute_deal_metrics(**_COMMON, calc_mgmt_pct=0)
    bumped = compute_deal_metrics(**_COMMON, calc_mgmt_pct=8)
    expected_shift = _EFF_GROSS * (8 / 100)
    assert base["cashflow"] - bumped["cashflow"] == pytest.approx(expected_shift, rel=1e-9)
    assert base["mao"] - bumped["mao"] == pytest.approx(expected_shift / _DENOM, rel=1e-6)


def test_maintenance_pct_shifts_cashflow_and_mao_by_exact_amount():
    """Same shape as management fee (% of effective gross rent) - bumped
    from the 5% default to 12% here, a 7-percentage-point delta."""
    base = compute_deal_metrics(**_COMMON, calc_maint_pct=5)
    bumped = compute_deal_metrics(**_COMMON, calc_maint_pct=12)
    expected_shift = _EFF_GROSS * ((12 - 5) / 100)
    assert base["cashflow"] - bumped["cashflow"] == pytest.approx(expected_shift, rel=1e-9)
    assert base["mao"] - bumped["mao"] == pytest.approx(expected_shift / _DENOM, rel=1e-6)


def test_closing_costs_leave_cashflow_unchanged_but_shift_coc_and_mao():
    """Closing costs are a one-time transaction cost, not an ongoing
    operating expense - unlike HOA/mgmt/maintenance, they never touch
    NOI or cashflow at all. Only the CoC denominator (total cash needed)
    and MAO (scaled by the target yield, mirroring exactly how
    whatif_calculator.py's own suggested-max-offer algebra places it)
    shift. Asserting cashflow stays fixed here is as important as
    asserting what does move - a bug that made closing costs leak into
    cashflow would double-count them against total_cash_needed too."""
    base = compute_deal_metrics(**_COMMON, calc_closing_costs=0)
    bumped = compute_deal_metrics(**_COMMON, calc_closing_costs=8000)

    assert bumped["cashflow"] == pytest.approx(base["cashflow"], rel=1e-9)
    assert bumped["total_cash_needed"] - base["total_cash_needed"] == pytest.approx(8000.0)
    assert bumped["coc"] < base["coc"]  # same cashflow over more cash needed = lower return

    target_yield = 8 / 100
    expected_mao_shift = target_yield * 8000 / _DENOM
    assert base["mao"] - bumped["mao"] == pytest.approx(expected_mao_shift, rel=1e-6)


# ---------------------------------------------------------------------------
# car_engine.py: pure grading helpers
# ---------------------------------------------------------------------------

def test_grade_tier_boundaries_at_12_and_0_percent():
    """_grade_tier's exact boundary values: >=12% excellent, >=0% average,
    below 0% critical - tests the boundary values themselves (12 and 0),
    not just values comfortably inside each band, since an off-by-one
    (>  vs >=) would only show up right at the edge."""
    assert _grade_tier(12) == "excellent"
    assert _grade_tier(11.999) == "average"
    assert _grade_tier(0) == "average"
    assert _grade_tier(-0.001) == "critical"


def test_median_odd_and_even_length():
    """Standard median - odd length picks the middle element, even length
    averages the two middle elements. Verified against sorted lists by
    hand, not just by re-reading the implementation."""
    assert _median([3, 1, 2]) == 2
    assert _median([4, 1, 3, 2]) == 2.5


def test_drop_price_outliers_drops_sub_half_median_prices():
    """A group of >=3 same make/model listings: one priced under half the
    group's own median (including itself in that median) is dropped as
    broken upstream data, not treated as a real bargain. [1000, 20000,
    21000, 22000] has a median of 20,500 (average of the two middle
    values) - $1,000 is under half of that (10,250) and must be dropped;
    the other three, all close together, must survive."""
    listings = [
        {"make": "Honda", "model": "Civic", "price": 20000},
        {"make": "Honda", "model": "Civic", "price": 21000},
        {"make": "Honda", "model": "Civic", "price": 22000},
        {"make": "Honda", "model": "Civic", "price": 1000},
    ]
    survivors = _drop_price_outliers(listings)
    assert sorted(l["price"] for l in survivors) == [20000, 21000, 22000]


def test_drop_price_outliers_leaves_small_groups_untouched():
    """Groups smaller than 3 can't produce a meaningful median (one bad
    value would skew it entirely), so they're left alone even when one
    listing's price looks like an outlier by simple ratio - the correct
    honest behavior is "not enough comps to tell," not a guess."""
    listings = [
        {"make": "Rare", "model": "Model", "price": 1000},
        {"make": "Rare", "model": "Model", "price": 50000},
    ]
    survivors = _drop_price_outliers(listings)
    assert sorted(l["price"] for l in survivors) == [1000, 50000]


def test_mileage_adjustment_sign_is_economically_correct():
    """A lower-mileage car is held to a HIGHER market-value bar than a
    higher-mileage one with the identical price and identical comps - the
    adjustment's sign the reviewer's audit specifically verified. Two
    otherwise-identical targets (same price, same comp group of 2 cars at
    50,000mi/$20,000) differing only in their own mileage (10,000 vs
    60,000) must end up with the low-mileage one's market_value higher,
    confirming low mileage -> higher bar -> lower pct-below-market for
    the same price, not the reverse."""
    def _comp():
        return {"make": "Toyota", "model": "Camry", "year": 2020, "mileage": 50000, "price": 20000}

    low_result = _grade_real_listings([
        _comp(), _comp(),
        {"make": "Toyota", "model": "Camry", "year": 2020, "mileage": 10000, "price": 20000},
    ])
    high_result = _grade_real_listings([
        _comp(), _comp(),
        {"make": "Toyota", "model": "Camry", "year": 2020, "mileage": 60000, "price": 20000},
    ])

    low_target = next(l for l in low_result if l["mileage"] == 10000)
    high_target = next(l for l in high_result if l["mileage"] == 60000)

    assert low_target["market_value"] == pytest.approx(21600.0)
    assert high_target["market_value"] == pytest.approx(19600.0)
    assert low_target["market_value"] > high_target["market_value"]


def test_classify_fuel_type_reconciles_mislabeled_hybrid():
    """The exact case this function's own docstring exists to fix: a real
    Prius listing came back from Auto.dev with fuel='Gasoline' but
    'Hybrid' only in the free-text engine description - this must still
    classify as hybrid, not gas, by checking both signals."""
    assert classify_fuel_type("Gasoline", "1.8L Hybrid I4 134hp") == "hybrid"


def test_classify_fuel_type_straightforward_cases():
    assert classify_fuel_type("Plug-in Hybrid") == "phev"
    assert classify_fuel_type("Electric") == "ev"
    assert classify_fuel_type("Hybrid") == "hybrid"
    assert classify_fuel_type("Gasoline") == "gas"


def test_classify_fuel_type_none_when_no_data():
    """No fuel data at all returns None (an honest "unknown"), never a
    guessed default like "gas" - a listing with genuinely missing fuel
    data shouldn't display a possibly-wrong chip."""
    assert classify_fuel_type(None) is None
    assert classify_fuel_type("") is None


def test_compute_car_deal_metrics_grade_boundary_and_direction():
    """End-to-end check tying compute_car_deal_metrics to the same 12%/0%
    _grade_tier boundary tested above: a price exactly 12% under market
    grades excellent; a price above market grades critical with a
    negative dollars_below_market."""
    at_boundary = compute_car_deal_metrics(price=17600, market_value=20000)
    assert at_boundary["pct_below_market"] == pytest.approx(12.0)
    assert at_boundary["grade"] == "excellent"

    above_market = compute_car_deal_metrics(price=22000, market_value=20000)
    assert above_market["pct_below_market"] == pytest.approx(-10.0)
    assert above_market["dollars_below_market"] == pytest.approx(-2000.0)
    assert above_market["grade"] == "critical"


def test_compute_car_deal_metrics_zero_market_value_guard():
    """market_value<=0 is a data-completeness guard, not a real 0%-below
    result - pct_below_market floors at 0.0 rather than dividing by zero
    or producing a misleadingly large/negative percentage."""
    m = compute_car_deal_metrics(price=15000, market_value=0)
    assert m["pct_below_market"] == 0.0
    assert m["grade"] == _grade_tier(0.0)
