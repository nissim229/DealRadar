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
                          calc_down_pct, calc_interest, calc_target_yield, hoa_monthly=0.0):
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
    good outstanding deal."""
    v_loss = (calc_rent * 12) * (calc_vacancy_pct / 100)
    eff_gross = (calc_rent * 12) - v_loss
    taxes = price * (calc_tax_rate / 100)
    insurance = price * (calc_ins_rate / 100)
    hoa_annual = (hoa_monthly or 0) * 12
    expenses = taxes + insurance + hoa_annual
    noi = max(0.0, eff_gross - expenses)
    cap_rate = (noi / price) * 100 if price > 0 else 0.0

    down_amt = price * (calc_down_pct / 100)
    loan_amt = price - down_amt
    if loan_amt > 0 and calc_interest > 0:
        m_debt = loan_amt * monthly_payment_factor(calc_interest, 30 * 12)
        a_debt = m_debt * 12
    else:
        a_debt = 0.0

    cashflow = noi - a_debt
    coc = (cashflow / down_amt) * 100 if down_amt > 0 else 0.0

    target_yield = calc_target_yield / 100
    down_ratio = calc_down_pct / 100
    tax_ins_ratio = (calc_tax_rate / 100) + (calc_ins_rate / 100)
    if calc_interest > 0:
        debt_factor = 12 * monthly_payment_factor(calc_interest, 30 * 12)
    else:
        debt_factor = 0.0
    denom = tax_ins_ratio + (debt_factor * (1 - down_ratio)) + (target_yield * down_ratio)
    # HOA is a fixed dollar cost, not a rate-of-price like tax/insurance,
    # so it can't be folded into tax_ins_ratio the same way (that ratio
    # is what makes this formula solvable for price in the first place).
    # Treating it as a straight reduction of the income available to
    # cover everything else is a simplification, but it's directionally
    # correct: a higher HOA lowers the max price this deal can still
    # justify, instead of MAO silently ignoring it.
    mao = (eff_gross - hoa_annual) / denom if denom > 0 else price
    mao_delta = price - mao

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



def compute_whatif_metrics(price, calc_rent, calc_vacancy_pct, calc_tax_rate, calc_ins_rate,
                            calc_down_pct, calc_interest, calc_target_yield,
                            loan_term_years=30, mgmt_fee_pct=0.0, maintenance_pct=0.0,
                            hoa_monthly=0.0, closing_costs=0.0):
    """Extended underwriting math for the What-If sandbox - adds loan term,
    property management fee, maintenance reserve, HOA, and closing costs on top
    of the base compute_deal_metrics logic. Kept separate from compute_deal_metrics
    so the main card grades stay driven by the simpler baseline everywhere else."""
    v_loss = (calc_rent * 12) * (calc_vacancy_pct / 100)
    eff_gross = (calc_rent * 12) - v_loss
    taxes = price * (calc_tax_rate / 100)
    insurance = price * (calc_ins_rate / 100)
    mgmt_fee = eff_gross * (mgmt_fee_pct / 100)
    maintenance = eff_gross * (maintenance_pct / 100)
    hoa_annual = hoa_monthly * 12
    total_expenses = taxes + insurance + mgmt_fee + maintenance + hoa_annual
    noi = max(0.0, eff_gross - total_expenses)
    cap_rate = (noi / price) * 100 if price > 0 else 0.0

    down_amt = price * (calc_down_pct / 100)
    loan_amt = price - down_amt
    if loan_amt > 0 and calc_interest > 0:
        p_count = max(1, int(loan_term_years)) * 12
        m_debt = loan_amt * monthly_payment_factor(calc_interest, p_count)
        a_debt = m_debt * 12
    else:
        a_debt = 0.0

    cashflow = noi - a_debt
    total_cash_invested = down_amt + closing_costs
    coc = (cashflow / total_cash_invested) * 100 if total_cash_invested > 0 else 0.0

    if cashflow < 0:
        grade = "critical"
    elif coc >= calc_target_yield:
        grade = "excellent"
    else:
        grade = "average"

    return {
        "noi": noi, "cap_rate": cap_rate, "cashflow": cashflow, "coc": coc,
        "down_amt": down_amt, "loan_amt": loan_amt, "a_debt": a_debt, "grade": grade,
        "mgmt_fee": mgmt_fee, "maintenance": maintenance, "hoa_annual": hoa_annual,
        "total_expenses": total_expenses, "total_cash_invested": total_cash_invested,
    }
