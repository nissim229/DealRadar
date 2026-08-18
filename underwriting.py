"""
underwriting.py
Pure underwriting math and grade styling - no Streamlit UI calls, so this
module has zero dependency on the app framework and is easy to unit test.
"""

def compute_deal_metrics(price, calc_rent, calc_vacancy_pct, calc_tax_rate, calc_ins_rate,
                          calc_down_pct, calc_interest, calc_target_yield):
    """Shared underwriting math - used identically by the summary cards, the property
    cards, and the detailed Pro tabs, so the numbers never disagree with each other."""
    v_loss = (calc_rent * 12) * (calc_vacancy_pct / 100)
    eff_gross = (calc_rent * 12) - v_loss
    taxes = price * (calc_tax_rate / 100)
    insurance = price * (calc_ins_rate / 100)
    expenses = taxes + insurance
    noi = max(0.0, eff_gross - expenses)
    cap_rate = (noi / price) * 100 if price > 0 else 0.0

    down_amt = price * (calc_down_pct / 100)
    loan_amt = price - down_amt
    if loan_amt > 0 and calc_interest > 0:
        m_rate = (calc_interest / 100) / 12
        p_count = 30 * 12
        m_debt = loan_amt * (m_rate * (1 + m_rate) ** p_count) / ((1 + m_rate) ** p_count - 1)
        a_debt = m_debt * 12
    else:
        a_debt = 0.0

    cashflow = noi - a_debt
    coc = (cashflow / down_amt) * 100 if down_amt > 0 else 0.0

    target_yield = calc_target_yield / 100
    down_ratio = calc_down_pct / 100
    tax_ins_ratio = (calc_tax_rate / 100) + (calc_ins_rate / 100)
    if calc_interest > 0:
        m_rate = (calc_interest / 100) / 12
        p_count = 30 * 12
        debt_factor = 12 * (m_rate * (1 + m_rate) ** p_count) / ((1 + m_rate) ** p_count - 1)
    else:
        debt_factor = 0.0
    denom = tax_ins_ratio + (debt_factor * (1 - down_ratio)) + (target_yield * down_ratio)
    mao = eff_gross / denom if denom > 0 else price
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
        "vacancy_loss": v_loss,
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


def render_deal_badge(grade):
    style = GRADE_STYLES[grade]
    return (
        f"<span style='background-color:{style['bg']}; color:{style['fg']}; "
        f"padding:6px 12px; border-radius:6px; font-weight:700; font-size:13px; "
        f"border:1px solid {style['border']}; white-space:nowrap;'>{style['label']}</span>"
    )



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
        m_rate = (calc_interest / 100) / 12
        p_count = max(1, int(loan_term_years)) * 12
        m_debt = loan_amt * (m_rate * (1 + m_rate) ** p_count) / ((1 + m_rate) ** p_count - 1)
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
