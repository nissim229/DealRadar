"""
underwriting.py
Pure underwriting math and grade styling - no Streamlit UI calls, so this
module has zero dependency on the app framework and is easy to unit test.
"""


def monthly_payment_factor(annual_rate_pct, n_periods):
    """Standard fixed-rate loan monthly-payment-per-dollar-of-principal
    factor - multiply by the loan amount to get the actual payment. This
    is the one formula every debt-service number in the app (deal grading,
    the What-If sandbox, and the Portfolio amortization schedule) is
    ultimately built on; previously it was hand-written independently in
    5 different places. Callers own their own zero/negative-rate handling
    since "no rate" means different things in different contexts (a
    data-completeness guard here vs. genuine 0% financing elsewhere)."""
    m_rate = (annual_rate_pct / 100) / 12
    return (m_rate * (1 + m_rate) ** n_periods) / ((1 + m_rate) ** n_periods - 1)


def compute_deal_metrics(price, calc_rent, calc_vacancy_pct, calc_tax_rate, calc_ins_rate,
                          calc_down_pct, calc_interest, calc_target_yield, hoa_monthly=0.0,
                          calc_mgmt_pct=0.0, calc_maint_pct=5.0, calc_closing_costs=0.0,
                          calc_rehab_cost=0.0):
    """Shared underwriting math - used identically by the summary cards, the property
    cards, and the detailed Pro tabs, so the numbers never disagree with each other.

    hoa_monthly defaults to 0 (not None) so every existing call site that
    doesn't know a listing's HOA - a manual what-if entry, a portfolio
    property with no HOA, mock data that predates this field - keeps
    computing exactly what it did before this was added, rather than
    needing to be touched. Real/mock RentCast listings pass their actual
    hoa_monthly (see agent_engine.py) so a $300/mo HOA condo doesn't get
    graded as if it had none - a real gap flagged by the user: "i dont
    think we [are] adding that to the calculation to decide if it [is a]
    good outstanding deal."

    calc_mgmt_pct/calc_maint_pct/calc_closing_costs mirror the What-If
    sandbox's own property-management %, maintenance-reserve %, and
    closing-cost inputs - previously only the sandbox modeled these,
    so the exact same listing could grade "excellent" on its card but
    drop to "average" the moment someone opened What-If for it (both
    surfaces were internally correct, just different models - see the
    reviewer's deal-math audit, Gaps 2-3). Folding them into this one
    shared function instead of duplicating the sandbox's math again
    means the two surfaces can no longer disagree. Defaults
    (mgmt 0%, maintenance 5%, closing $0) match What-If's own slider
    defaults exactly, so an existing call site that doesn't pass these
    picks up the same "out of the box" assumptions a fresh What-If
    session would - maintenance is the one line that was already
    nonzero by default, so every card's numbers get a little more
    realistic even without any caller changes; management/closing stay
    a no-op until a caller opts in.

    calc_rehab_cost is a one-time renovation budget, not modeled in the
    What-If sandbox either at the time this was added (the reviewer's
    original deal-math audit flagged it as the one real-world cost line
    missing from BOTH surfaces, alongside mgmt/maintenance/closing which
    the sandbox already had). Treated identically to calc_closing_costs
    in every formula below - both are cash required upfront that never
    touches NOI/cashflow, only the CoC denominator and MAO's numerator -
    since a renovation budget and a closing-cost budget are the same
    kind of cost from the math's perspective (a dollar spent before
    move-in, once, not a recurring operating expense), even though they
    get their own separate line items for display so a user can see
    where their total cash requirement actually comes from."""
    v_loss = (calc_rent * 12) * (calc_vacancy_pct / 100)
    eff_gross = (calc_rent * 12) - v_loss
    taxes = price * (calc_tax_rate / 100)
    insurance = price * (calc_ins_rate / 100)
    hoa_annual = (hoa_monthly or 0) * 12
    mgmt_fee = eff_gross * (calc_mgmt_pct / 100)
    maintenance = eff_gross * (calc_maint_pct / 100)
    expenses = taxes + insurance + hoa_annual + mgmt_fee + maintenance
    # NOI itself must stay unclamped - cashflow/CoC/grade all derive from it,
    # and flooring it at 0 was hiding real losses on all-cash (or near
    # free-and-clear) deals: with no debt service, cashflow = noi, so a
    # clamped $0 noi produced a $0 cashflow instead of the true negative
    # figure, misgrading a money-losing all-cash property "average"
    # instead of "critical" (a mortgaged deal never hit this - debt service
    # alone pushes cashflow negative regardless of the NOI clamp). Only the
    # cap-rate *display* value is floored, so a loss reads as "0% cap rate"
    # rather than a possibly-confusing negative percentage.
    noi = eff_gross - expenses
    cap_rate = (max(0.0, noi) / price) * 100 if price > 0 else 0.0

    down_amt = price * (calc_down_pct / 100)
    loan_amt = price - down_amt
    if loan_amt > 0 and calc_interest > 0:
        m_debt = loan_amt * monthly_payment_factor(calc_interest, 30 * 12)
        a_debt = m_debt * 12
    else:
        a_debt = 0.0

    cashflow = noi - a_debt
    # Total cash needed includes closing costs AND rehab budget alongside
    # the down payment - a buyer sinking $10k into closing plus $30k into
    # rehab before move-in has a real return on capital lower than one who
    # only put down the purchase-price fraction, and this was previously
    # invisible on every card/summary surface.
    total_cash = down_amt + calc_closing_costs + calc_rehab_cost
    coc = (cashflow / total_cash) * 100 if total_cash > 0 else 0.0

    target_yield = calc_target_yield / 100
    down_ratio = calc_down_pct / 100
    tax_ins_ratio = (calc_tax_rate / 100) + (calc_ins_rate / 100)
    if calc_interest > 0:
        debt_factor = 12 * monthly_payment_factor(calc_interest, 30 * 12)
    else:
        debt_factor = 0.0
    denom = tax_ins_ratio + (debt_factor * (1 - down_ratio)) + (target_yield * down_ratio)
    # HOA/mgmt/maintenance are fixed-dollar or rent-proportional costs, not
    # rate-of-price like tax/insurance, so none of them can fold into
    # tax_ins_ratio the same way (that ratio is what makes this formula
    # solvable for price in the first place) - each instead reduces the
    # income available to cover everything else, in the numerator. Closing
    # costs and rehab budget land in the numerator too (scaled by
    # target_yield, since both add directly to the total-cash denominator
    # of the CoC this MAO is solving for) rather than the denominator,
    # matching the exact algebraic derivation used by What-If's own
    # suggested-max-offer calculation (see whatif_calculator.py's
    # compute()) - both are the same closed-form now, not two
    # independently-derived formulas that happen to agree.
    mao_numerator = eff_gross - hoa_annual - mgmt_fee - maintenance - (target_yield * (calc_closing_costs + calc_rehab_cost))
    # A non-positive numerator means expenses/financing terms are too high
    # to hit the target return at ANY price; a non-positive denom is its
    # own (much rarer) degenerate case. What-If's own compute() treats
    # both the same way - "Not achievable" - via the identical
    # `denom>0 && numerator>0` guard (see whatif_calculator.py). Matching
    # that here (rather than the previous Python-only fallback of
    # returning `price` when denom<=0) means None consistently means "not
    # achievable at these assumptions" instead of silently rendering a
    # negative dollar figure like "$-45,000" on a card/PDF - a confusing
    # number, not an honest one. Every consumer must handle mao is None.
    mao = mao_numerator / denom if (denom > 0 and mao_numerator > 0) else None
    mao_delta = (price - mao) if mao is not None else None

    if cashflow < 0:
        grade = "critical"
    elif coc >= calc_target_yield:
        grade = "excellent"
    else:
        grade = "average"

    return {
        "noi": noi, "cap_rate": cap_rate, "cashflow": cashflow, "coc": coc,
        "down_amt": down_amt, "loan_amt": loan_amt, "a_debt": a_debt,
        "mao": mao, "mao_delta": mao_delta, "grade": grade,
        "eff_gross_income": eff_gross, "annual_taxes": taxes, "annual_insurance": insurance,
        "vacancy_loss": v_loss, "annual_hoa": hoa_annual, "monthly_hoa": hoa_monthly or 0,
        "annual_mgmt_fee": mgmt_fee, "annual_maintenance": maintenance,
        "closing_costs": calc_closing_costs, "rehab_cost": calc_rehab_cost,
        "total_cash_needed": total_cash,
    }


GRADE_STYLES = {
    "critical": {
        "label": "🔴 Negative Cash Flow",
        "simple_verdict": "This one loses money every month at these terms - probably skip it.",
        "bg": "#fee2e2", "fg": "#991b1b", "border": "#fca5a5",
    },
    "excellent": {
        "label": "🟢 Outstanding Deal",
        "simple_verdict": "This one clears your target return with room to spare.",
        "bg": "#d1fae5", "fg": "#065f46", "border": "#6ee7b7",
    },
    "average": {
        "label": "🟡 Average Deal",
        "simple_verdict": "This one pencils out, but only just - worth a closer look before committing.",
        "bg": "#fef3c7", "fg": "#92400e", "border": "#fcd34d",
    },
}


def render_grade_badge(grade, styles_dict):
    """Shared HTML template behind both render_deal_badge (properties,
    using GRADE_STYLES below) and render_car_deal_badge (car_engine.py,
    using its own CAR_GRADE_STYLES) - only the style dict differs."""
    style = styles_dict[grade]
    return (
        f"<span style='background-color:{style['bg']}; color:{style['fg']}; "
        f"padding:6px 12px; border-radius:6px; font-weight:700; font-size:13px; "
        f"border:1px solid {style['border']}; white-space:nowrap;'>{style['label']}</span>"
    )


def render_deal_badge(grade):
    return render_grade_badge(grade, GRADE_STYLES)

