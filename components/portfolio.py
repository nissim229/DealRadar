import os
import uuid
import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import date, datetime
import database as db
import plan_limits
from icons import icon as svg_icon
from components.analytics import render_empty_state, render_stat_card
from components import pricing
from underwriting import GRADE_STYLES
from nav import render_side_nav

PROPERTY_TYPES = [
    "Primary Residence", "Single Family Rental", "Multi-Family Rental",
    "Condo Rental", "Townhouse Rental", "Vacation / Short-Term Rental",
    "Land / Lot", "Commercial Property", "Other",
]


def _parse_date(s):
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _months_between(start_date, end_date=None):
    if not start_date:
        return 0
    end_date = end_date or date.today()
    return max(0, (end_date.year - start_date.year) * 12 + (end_date.month - start_date.month))


def _amortize(loan_amount, annual_rate_pct, term_years, months_elapsed):
    """Standard fixed-rate amortization math (same monthly-payment formula
    used elsewhere in the app - see underwriting.compute_deal_metrics).
    Returns None when there isn't enough info to compute a schedule yet."""
    if not loan_amount or not term_years:
        return None
    n = int(term_years * 12)
    r = (annual_rate_pct / 100) / 12
    months_elapsed = max(0, min(months_elapsed, n))

    if r > 0:
        payment = loan_amount * (r * (1 + r) ** n) / ((1 + r) ** n - 1)

        def balance_after(k):
            return loan_amount * ((1 + r) ** n - (1 + r) ** k) / ((1 + r) ** n - 1)
    else:
        payment = loan_amount / n

        def balance_after(k):
            return loan_amount - payment * k

    remaining = max(0, balance_after(months_elapsed))
    prev_balance = max(0, balance_after(months_elapsed - 1)) if months_elapsed > 0 else loan_amount
    principal_this_month = max(0, prev_balance - remaining) if months_elapsed > 0 else 0
    interest_this_month = max(0, payment - principal_this_month) if months_elapsed > 0 else 0

    return {
        "monthly_payment": payment,
        "remaining_balance": remaining,
        "months_elapsed": months_elapsed,
        "months_remaining": max(0, n - months_elapsed),
        "interest_this_month": interest_this_month,
        "principal_this_month": principal_this_month,
    }


def _amortization_schedule(loan_amount, annual_rate_pct, term_years):
    """Full year-by-year schedule for the entire life of the loan (not just
    up to today, unlike _amortize) - how much of each year's payments went
    to interest vs. principal, and the balance remaining at year-end."""
    if not loan_amount or not term_years:
        return []
    n = int(term_years * 12)
    r = (annual_rate_pct / 100) / 12
    if r > 0:
        payment = loan_amount * (r * (1 + r) ** n) / ((1 + r) ** n - 1)

        def balance_after(k):
            return max(0, loan_amount * ((1 + r) ** n - (1 + r) ** k) / ((1 + r) ** n - 1))
    else:
        payment = loan_amount / n

        def balance_after(k):
            return max(0, loan_amount - payment * k)

    rows = []
    cumulative_interest = 0
    cumulative_principal = 0
    prev_balance = loan_amount
    for year in range(1, int(term_years) + 1):
        end_balance = balance_after(year * 12)
        principal_paid = prev_balance - end_balance
        interest_paid = payment * 12 - principal_paid
        cumulative_interest += interest_paid
        cumulative_principal += principal_paid
        rows.append({
            "Year": year, "Payment": payment * 12, "Principal Paid": principal_paid,
            "Interest Paid": interest_paid, "Ending Balance": end_balance,
            "Cumulative Interest": cumulative_interest, "Cumulative Principal": cumulative_principal,
        })
        prev_balance = end_balance
    return rows


def _monthly_fixed_costs(p):
    """Mortgage P&I + PMI + HOA + insurance/12 + property tax/12 + property
    management + any catch-all other expenses - the full recurring carrying
    cost of a property regardless of whether it's rented out."""
    return (
        (p.get("monthly_mortgage_payment") or 0)
        + (p.get("monthly_pmi") or 0)
        + (p.get("hoa_monthly") or 0)
        + (p.get("insurance_annual") or 0) / 12
        + (p.get("property_tax_annual") or 0) / 12
        + (p.get("property_management_monthly") or 0)
        + (p.get("other_expenses_monthly") or 0)
    )


def _monthly_cash_flow(p):
    """Rent minus carrying costs. None (not a number) for properties that
    aren't rented out - a primary residence has a housing cost, not a
    cash-flow verdict, since it produces no income to net against."""
    if p.get("is_rented"):
        return (p.get("monthly_rent") or 0) - _monthly_fixed_costs(p)
    return None


def _monthly_net_position(p):
    """Rent (if any) minus carrying costs, for every property regardless of
    rental status - unlike _monthly_cash_flow, a primary residence counts
    here as a straight negative (its cost, no income), so this is the number
    that reflects a whole-portfolio monthly cash position, not just rentals."""
    return (p.get("monthly_rent") or 0 if p.get("is_rented") else 0) - _monthly_fixed_costs(p)


def _current_value(p):
    """Falls back to purchase price when no current estimate was entered,
    so equity/value totals are never silently zero for a freshly-added
    property that just hasn't had its value updated yet."""
    return p.get("current_value_estimate") or p.get("purchase_price") or 0


def _save_property_fields(p, **changed_fields):
    """Updates a property, keeping every field not explicitly passed at its
    current saved value. update_portfolio_property overwrites every column
    each call, so a focused sub-tab form (e.g. just the Mortgage fields) must
    merge its edits onto the existing row rather than submitting only its own
    subset - otherwise every other field would get nulled out."""
    merged = {f: p.get(f) for f in db.PORTFOLIO_FIELDS}
    merged.update(changed_fields)
    db.update_portfolio_property(p["id"], st.session_state.user_id, **merged)


def _render_loan_info_section(e, key_prefix):
    """Renders loan-amount/rate/term/PMI OUTSIDE any st.form - form widgets
    don't rerun/recompute until submit, but this needs to recalculate live
    as the user types, matching a real amortization schedule. Returns a dict
    (not a positional tuple - too many fields now for position-matching
    between call sites to stay safe)."""
    st.caption("This section updates instantly as you type.")
    mode_options = ["I know my payment & balance", "Calculate it for me"]
    mode = st.radio(
        "How do you want to fill this in?", mode_options,
        index=1 if e.get("use_mortgage_calculator") else 0, horizontal=True,
        key=f"{key_prefix}_use_calc",
    )
    use_calc = mode == "Calculate it for me"
    mortgage_rate = st.number_input("Interest Rate (%)", min_value=0.0, value=float(e.get("mortgage_rate") or 0), step=0.125, format="%.3f", key=f"{key_prefix}_rate")

    if use_calc:
        st.caption("Don't know your exact loan amount or start date? Check your mortgage statement or closing documents - they'll have all three below.")
        lc1, lc2, lc3 = st.columns(3)
        with lc1:
            original_loan_amount = st.number_input("Original Loan Amount ($)", min_value=0, value=int(e.get("original_loan_amount") or 0), step=5000, key=f"{key_prefix}_loan_amt")
        with lc2:
            mortgage_start_date = st.date_input("When Did You Take the Mortgage?", value=_parse_date(e.get("mortgage_start_date")) or date.today(), key=f"{key_prefix}_start_date")
        with lc3:
            loan_term_years = st.number_input("Loan Term (years)", min_value=1, value=int(e.get("loan_term_years") or 30), step=1, key=f"{key_prefix}_term")

        calc = _amortize(original_loan_amount, mortgage_rate, loan_term_years, _months_between(mortgage_start_date))
        if calc:
            st.markdown("**Here's what that works out to:**")
            cc1, cc2, cc3, cc4 = st.columns(4)
            cc1.metric("Monthly Payment", f"${calc['monthly_payment']:,.0f}")
            cc2.metric("Remaining Balance", f"${calc['remaining_balance']:,.0f}")
            cc3.metric("This Month: Interest", f"${calc['interest_this_month']:,.0f}")
            cc4.metric("This Month: Principal", f"${calc['principal_this_month']:,.0f}")
            years_left = calc["months_remaining"] / 12
            st.caption(f"{calc['months_elapsed']} of {int(loan_term_years * 12)} payments made - {calc['months_remaining']} months (~{years_left:.1f} years) remaining.")
            st.info("Save below to see your full year-by-year payment schedule and chart.", icon=":material/insights:")
            monthly_mortgage_payment, mortgage_balance = calc["monthly_payment"], calc["remaining_balance"]
        else:
            st.caption("Enter a loan amount and term above to calculate your payment.")
            monthly_mortgage_payment, mortgage_balance = 0, 0
    else:
        original_loan_amount = e.get("original_loan_amount") or 0
        mortgage_start_date = _parse_date(e.get("mortgage_start_date")) or date.today()
        loan_term_years = e.get("loan_term_years") or 30
        mb1, mb2 = st.columns(2)
        with mb1:
            mortgage_balance = st.number_input("Remaining Mortgage Balance ($)", min_value=0, value=int(e.get("mortgage_balance") or 0), step=1000, key=f"{key_prefix}_balance")
        with mb2:
            monthly_mortgage_payment = st.number_input("Monthly Mortgage Payment - P&I ($)", min_value=0, value=int(e.get("monthly_mortgage_payment") or 0), step=25, key=f"{key_prefix}_payment")

    monthly_pmi = st.number_input(
        "PMI - Private Mortgage Insurance ($/mo)", min_value=0, value=int(e.get("monthly_pmi") or 0), step=10,
        help="Only applies if your down payment was under 20% - leave at 0 if you don't have PMI.",
        key=f"{key_prefix}_pmi",
    )

    return {
        "mortgage_balance": mortgage_balance, "monthly_mortgage_payment": monthly_mortgage_payment,
        "mortgage_rate": mortgage_rate, "original_loan_amount": original_loan_amount,
        "mortgage_start_date": mortgage_start_date, "loan_term_years": loan_term_years, "use_calc": use_calc,
        "monthly_pmi": monthly_pmi,
    }


def _render_lender_contact_section(e, key_prefix):
    """Also outside any st.form, purely for consistency with loan info (no
    live-calc need here, but keeps both sections symmetric). Returns a dict."""
    lc1, lc2 = st.columns(2)
    with lc1:
        lender_name = st.text_input("Lender / Company Name", value=e.get("lender_name", ""), placeholder="e.g., Wells Fargo Home Mortgage", key=f"{key_prefix}_lender_name")
        lender_phone = st.text_input("Phone", value=e.get("lender_phone", ""), key=f"{key_prefix}_lender_phone")
        loan_account_number = st.text_input("Loan / Account Number", value=e.get("loan_account_number", ""), key=f"{key_prefix}_loan_acct")
    with lc2:
        loan_officer_name = st.text_input("Loan Officer Name", value=e.get("loan_officer_name", ""), key=f"{key_prefix}_officer")
        lender_email = st.text_input("Email", value=e.get("lender_email", ""), key=f"{key_prefix}_lender_email")

    return {
        "lender_name": lender_name, "loan_officer_name": loan_officer_name,
        "lender_phone": lender_phone, "lender_email": lender_email, "loan_account_number": loan_account_number,
    }


def _render_mortgage_calculator(e, key_prefix):
    """Combines loan info + lender contact in one pass, used only by the
    Add-a-Property flow, which fills everything in one sitting and doesn't
    need the Loan Info / Lender Contact sub-navigation the property-detail
    Mortgage tab uses (see _render_mortgage_subtab)."""
    loan = _render_loan_info_section(e, key_prefix)
    st.markdown("##### Lender Contact")
    lender = _render_lender_contact_section(e, key_prefix)
    return {**loan, **lender}


def _render_schedule_section(p):
    """The full amortization chart/table for a saved calculator-mode
    property - shared by the Mortgage sub-tab."""
    calc = _amortize(
        p.get("original_loan_amount") or 0, p.get("mortgage_rate") or 0,
        p.get("loan_term_years") or 30, _months_between(_parse_date(p.get("mortgage_start_date"))),
    )
    if not calc:
        return
    schedule = _amortization_schedule(p.get("original_loan_amount") or 0, p.get("mortgage_rate") or 0, p.get("loan_term_years") or 30)
    if not schedule:
        return

    years_left = calc["months_remaining"] / 12
    st.markdown(
        f"**Current status:** ${calc['interest_this_month']:,.0f}/mo interest, ${calc['principal_this_month']:,.0f}/mo "
        f"principal - {years_left:.1f} years left on the loan."
    )
    sched_view = st.radio(
        "View", ["Chart", "Table"], horizontal=True, label_visibility="collapsed",
        key=f"portfolio_sched_view_{p['id']}",
    )
    sched_df = pd.DataFrame(schedule)
    current_year = (p.get("loan_term_years") or 30) - (calc["months_remaining"] / 12)

    if sched_view == "Chart":
        chart_font_color = "#e2e8f0" if st.session_state.get("theme_mode") == "dark" else "#0f172a"
        split_df = sched_df.melt(id_vars=["Year"], value_vars=["Principal Paid", "Interest Paid"], var_name="Component", value_name="Amount")
        fig_split = px.bar(
            split_df, x="Year", y="Amount", color="Component", barmode="stack",
            color_discrete_map={"Principal Paid": "#2563eb", "Interest Paid": "#94a3b8"},
        )
        fig_split.add_vline(x=current_year, line_dash="dash", line_color=chart_font_color,
                             annotation_text="Today", annotation_position="top")
        fig_split.update_layout(
            title="Principal vs. Interest Paid Each Year", xaxis_title="Year", yaxis_title="$",
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font_color=chart_font_color,
            height=280, margin=dict(l=10, r=10, t=40, b=10),
        )
        st.plotly_chart(fig_split, use_container_width=True, key=f"portfolio_sched_split_{p['id']}")

        fig_balance = px.line(sched_df, x="Year", y="Ending Balance")
        fig_balance.update_traces(line_color="#2563eb", fill="tozeroy", fillcolor="rgba(37,99,235,0.15)")
        fig_balance.add_vline(x=current_year, line_dash="dash", line_color=chart_font_color,
                               annotation_text="Today", annotation_position="top")
        fig_balance.update_layout(
            title="Remaining Balance by Year", xaxis_title="Year", yaxis_title="$",
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font_color=chart_font_color,
            height=280, margin=dict(l=10, r=10, t=40, b=10),
        )
        st.plotly_chart(fig_balance, use_container_width=True, key=f"portfolio_sched_balance_{p['id']}")
    else:
        table_df = sched_df.copy()
        for col in ["Payment", "Principal Paid", "Interest Paid", "Ending Balance", "Cumulative Interest", "Cumulative Principal"]:
            table_df[col] = table_df[col].apply(lambda v: f"${v:,.0f}")
        st.dataframe(table_df, use_container_width=True, hide_index=True, height=min(len(table_df), 12) * 35 + 38)


# --- ADD-PROPERTY FORM (used only by the "Add a Property" tab - a fresh
# property doesn't have sub-tabs yet since there's nothing to switch between) ---

def _property_form(existing=None, key_prefix="add"):
    """Renders the add-property field set. Returns a dict of PORTFOLIO_FIELDS
    values from the submitted form, or None if not yet submitted."""
    e = existing or {}

    st.markdown("##### Mortgage")
    with st.container(border=True):
        mtg = _render_mortgage_calculator(e, key_prefix)

    with st.form(f"{key_prefix}_portfolio_form", clear_on_submit=(existing is None)):
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("##### Property")
            with st.container(border=True):
                address = st.text_input("Address", value=e.get("address", ""), placeholder="123 Main St, Denver, CO 80202", key=f"{key_prefix}_address")
                property_type = st.selectbox("Type", PROPERTY_TYPES, index=PROPERTY_TYPES.index(e.get("property_type")) if e.get("property_type") in PROPERTY_TYPES else 0, key=f"{key_prefix}_type", help="Have something that doesn't fit? Pick 'Other' and note details later.")
                purchase_price = st.number_input("Purchase Price ($)", min_value=0, value=int(e.get("purchase_price") or 0), step=5000, key=f"{key_prefix}_price")
                current_value_estimate = st.number_input("Current Estimated Value ($)", min_value=0, value=int(e.get("current_value_estimate") or 0), step=5000, help="Leave at 0 to use the purchase price until you update it.", key=f"{key_prefix}_value")

        with col2:
            st.markdown("##### Carrying Costs")
            with st.container(border=True):
                hoa_monthly = st.number_input("Monthly HOA ($)", min_value=0, value=int(e.get("hoa_monthly") or 0), step=10, key=f"{key_prefix}_hoa")
                c1, c2 = st.columns(2)
                with c1:
                    insurance_annual = st.number_input("Annual Insurance ($)", min_value=0, value=int(e.get("insurance_annual") or 0), step=50, key=f"{key_prefix}_ins")
                with c2:
                    property_tax_annual = st.number_input("Annual Property Tax ($)", min_value=0, value=int(e.get("property_tax_annual") or 0), step=50, key=f"{key_prefix}_tax")
                property_management_monthly = st.number_input("Property Management ($/mo)", min_value=0, value=int(e.get("property_management_monthly") or 0), step=25, help="What you pay a property manager, if any.", key=f"{key_prefix}_mgmt")

        st.markdown("##### Rental Status")
        with st.container(border=True):
            r1, r2 = st.columns(2)
            with r1:
                rental_status = st.selectbox("Status", db.RENTAL_STATUSES, index=db.RENTAL_STATUSES.index(e.get("rental_status")) if e.get("rental_status") in db.RENTAL_STATUSES else 0, key=f"{key_prefix}_status")
            with r2:
                monthly_rent = st.number_input("Monthly Rent ($)", min_value=0, value=int(e.get("monthly_rent") or 0), step=25, help="Only counted toward cash flow when status is 'Occupied'.", key=f"{key_prefix}_rent")

        st.markdown("##### Other Expenses")
        with st.container(border=True):
            o1, o2 = st.columns([1, 2])
            with o1:
                other_expenses_monthly = st.number_input("Other Monthly Expenses ($)", min_value=0, value=int(e.get("other_expenses_monthly") or 0), step=25, help="Anything not covered above - utilities you cover, landscaping, pest control, repairs reserve, etc.", key=f"{key_prefix}_other_amt")
            with o2:
                other_expenses_notes = st.text_input("What's included in that?", value=e.get("other_expenses_notes", ""), placeholder="e.g., Lawn care $80 + water $70", key=f"{key_prefix}_other_notes")

        notes = st.text_area("Notes", value=e.get("notes", ""), placeholder="Anything else worth remembering about this property...", key=f"{key_prefix}_notes")

        st.caption("Once added, you'll be able to fill in tenants, documents, and occupancy details from the property's own page.")
        submitted = st.form_submit_button(":material/add_home: Add Property", type="primary", use_container_width=True)

    if submitted:
        errors = []
        if not address:
            errors.append("Address is required.")
        if purchase_price <= 0:
            errors.append("Purchase Price must be greater than $0.")
        if rental_status == "Occupied" and monthly_rent <= 0:
            errors.append("Monthly Rent must be greater than $0 for a property marked 'Occupied'.")
        if errors:
            for err in errors:
                st.error(err)
            return None
        return {
            "address": address, "property_type": property_type,
            "purchase_price": purchase_price, "purchase_date": e.get("purchase_date", ""),
            "current_value_estimate": current_value_estimate, "mortgage_balance": mtg["mortgage_balance"],
            "mortgage_rate": mtg["mortgage_rate"], "monthly_mortgage_payment": mtg["monthly_mortgage_payment"],
            "hoa_monthly": hoa_monthly, "insurance_annual": insurance_annual,
            "property_tax_annual": property_tax_annual, "rental_status": rental_status,
            "monthly_rent": monthly_rent, "property_management_monthly": property_management_monthly,
            "other_expenses_monthly": other_expenses_monthly, "other_expenses_notes": other_expenses_notes,
            "original_loan_amount": mtg["original_loan_amount"],
            "mortgage_start_date": mtg["mortgage_start_date"].isoformat() if mtg["use_calc"] else e.get("mortgage_start_date", ""),
            "loan_term_years": int(mtg["loan_term_years"]), "use_mortgage_calculator": int(mtg["use_calc"]),
            "monthly_pmi": mtg["monthly_pmi"], "lender_name": mtg["lender_name"],
            "loan_officer_name": mtg["loan_officer_name"], "lender_phone": mtg["lender_phone"],
            "lender_email": mtg["lender_email"], "loan_account_number": mtg["loan_account_number"],
            "notes": notes,
        }
    return None


# --- PROPERTY DETAIL SUB-TABS (each is its own focused mini-form with its
# own save action, so editing one aspect of a property never risks losing
# unsaved changes in another - and no single screen is ever too long) ---

def _render_overview_subtab(p):
    equity = _current_value(p) - (p.get("mortgage_balance") or 0)
    cash_flow = _monthly_cash_flow(p)

    top_col, badge_col = st.columns([3, 1.3])
    with top_col:
        st.markdown(f"**{p['address']}**  &nbsp;·&nbsp; {p['property_type']}  &nbsp;·&nbsp; {p.get('rental_status', 'Vacant')}")
    with badge_col:
        if cash_flow is None:
            st.markdown("<div style='text-align:right; color:var(--radar-text-muted); font-size:13px; font-weight:600;'>Not rented</div>", unsafe_allow_html=True)
        else:
            color = "var(--radar-success)" if cash_flow >= 0 else "var(--radar-danger)"
            sign = "+" if cash_flow >= 0 else "-"
            st.markdown(f"<div style='text-align:right; color:{color}; font-size:15px; font-weight:800;'>{sign}${abs(cash_flow):,.0f}/mo</div>", unsafe_allow_html=True)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Purchase Price", f"${p['purchase_price']:,.0f}")
    m2.metric("Current Value", f"${_current_value(p):,.0f}")
    m3.metric("Equity", f"${equity:,.0f}")
    if p.get("is_rented"):
        m4.metric("Monthly Rent", f"${p['monthly_rent']:,.0f}")
    else:
        m4.metric("Monthly Housing Cost", f"${_monthly_fixed_costs(p):,.0f}")

    extra_costs = []
    if p.get("monthly_pmi"):
        extra_costs.append(f"PMI ${p['monthly_pmi']:,.0f}/mo")
    if p.get("property_management_monthly"):
        extra_costs.append(f"Property mgmt ${p['property_management_monthly']:,.0f}/mo")
    if p.get("other_expenses_monthly"):
        detail = f" ({p['other_expenses_notes']})" if p.get("other_expenses_notes") else ""
        extra_costs.append(f"Other ${p['other_expenses_monthly']:,.0f}/mo{detail}")
    if extra_costs:
        st.caption("Also includes: " + " · ".join(extra_costs))

    if p.get("num_occupants") or p.get("num_keys_given"):
        st.caption(f"{int(p.get('num_occupants') or 0)} occupant(s) · {int(p.get('num_keys_given') or 0)} key(s) given")

    if p.get("lender_name") or p.get("loan_officer_name"):
        lender_bits = [b for b in [p.get("lender_name"), p.get("loan_officer_name"), p.get("lender_phone")] if b]
        st.caption("Lender: " + " · ".join(lender_bits))

    if p.get("notes"):
        st.caption(p["notes"])

    st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)
    with st.expander(":material/delete: Remove This Property"):
        st.warning("This permanently deletes the property along with its tenants and uploaded documents.")
        if st.button(":material/delete: Confirm Remove", key=f"portfolio_delete_{p['id']}", use_container_width=True):
            db.delete_portfolio_property(p["id"], st.session_state.user_id)
            st.session_state.pop("portfolio_selected_id", None)
            st.toast("Property removed from your portfolio.")
            st.rerun()


def _render_mortgage_subtab(p):
    key_prefix = f"prop_{p['id']}_mortgage"

    nav_col, content_col = st.columns([1, 3])
    with nav_col:
        section = render_side_nav(
            [
                {"label": "Loan Information", "icon": ":material/account_balance:"},
                {"label": "Lender Contact", "icon": ":material/call:"},
            ],
            key_prefix=f"{key_prefix}_section_nav",
        )

    with content_col:
        if section == "Loan Information":
            loan = _render_loan_info_section(p, key_prefix)

            # Mirrors the exact default-value expressions _render_loan_info_section
            # used to initialize each widget from p, so this only lights up on a
            # real difference from what's actually saved - not a false positive
            # from int/float/None coercion mismatches.
            loan_has_changes = (
                loan["mortgage_rate"] != float(p.get("mortgage_rate") or 0) or
                loan["monthly_pmi"] != int(p.get("monthly_pmi") or 0) or
                loan["use_calc"] != bool(p.get("use_mortgage_calculator")) or
                (loan["use_calc"] and (
                    loan["original_loan_amount"] != int(p.get("original_loan_amount") or 0) or
                    loan["mortgage_start_date"] != (_parse_date(p.get("mortgage_start_date")) or date.today()) or
                    int(loan["loan_term_years"]) != int(p.get("loan_term_years") or 30)
                )) or
                (not loan["use_calc"] and (
                    loan["mortgage_balance"] != int(p.get("mortgage_balance") or 0) or
                    loan["monthly_mortgage_payment"] != int(p.get("monthly_mortgage_payment") or 0)
                ))
            )
            if st.button(":material/save: Save Loan Information", key=f"{key_prefix}_save_loan", type="primary", use_container_width=True, disabled=not loan_has_changes):
                _save_property_fields(
                    p, mortgage_balance=loan["mortgage_balance"], monthly_mortgage_payment=loan["monthly_mortgage_payment"],
                    mortgage_rate=loan["mortgage_rate"], original_loan_amount=loan["original_loan_amount"],
                    mortgage_start_date=loan["mortgage_start_date"].isoformat() if loan["use_calc"] else p.get("mortgage_start_date", ""),
                    loan_term_years=int(loan["loan_term_years"]), use_mortgage_calculator=int(loan["use_calc"]),
                    monthly_pmi=loan["monthly_pmi"],
                )
                st.toast("Loan information updated.")
                st.rerun()

            # Widgets here write to session_state live as the user types, even
            # without saving - so typing a change and switching away (to another
            # section, tab, or property) without clicking Save would otherwise
            # leave that abandoned draft sitting here indefinitely, masking the
            # real saved value next time this section is viewed.
            if st.button("Discard changes", key=f"{key_prefix}_discard_loan", use_container_width=True):
                for suffix in ["use_calc", "rate", "loan_amt", "start_date", "term", "balance", "payment", "pmi"]:
                    st.session_state.pop(f"{key_prefix}_{suffix}", None)
                st.rerun()

            if p.get("use_mortgage_calculator"):
                st.markdown("---")
                _render_schedule_section(p)

        else:
            lender = _render_lender_contact_section(p, key_prefix)

            lender_has_changes = (
                lender["lender_name"] != p.get("lender_name", "") or lender["loan_officer_name"] != p.get("loan_officer_name", "") or
                lender["lender_phone"] != p.get("lender_phone", "") or lender["lender_email"] != p.get("lender_email", "") or
                lender["loan_account_number"] != p.get("loan_account_number", "")
            )
            if st.button(":material/save: Save Lender Contact", key=f"{key_prefix}_save_lender", type="primary", use_container_width=True, disabled=not lender_has_changes):
                _save_property_fields(
                    p, lender_name=lender["lender_name"], loan_officer_name=lender["loan_officer_name"],
                    lender_phone=lender["lender_phone"], lender_email=lender["lender_email"],
                    loan_account_number=lender["loan_account_number"],
                )
                st.toast("Lender contact updated.")
                st.rerun()

            if st.button("Discard changes", key=f"{key_prefix}_discard_lender", use_container_width=True):
                for suffix in ["lender_name", "lender_phone", "loan_acct", "officer", "lender_email"]:
                    st.session_state.pop(f"{key_prefix}_{suffix}", None)
                st.rerun()


def _render_property_details_subtab(p):
    key_prefix = f"prop_{p['id']}_details"
    with st.form(f"{key_prefix}_form"):
        col1, col2 = st.columns(2)
        with col1:
            address = st.text_input("Address", value=p.get("address", ""), key=f"{key_prefix}_address")
            property_type = st.selectbox("Type", PROPERTY_TYPES, index=PROPERTY_TYPES.index(p.get("property_type")) if p.get("property_type") in PROPERTY_TYPES else 0, key=f"{key_prefix}_type")
            purchase_price = st.number_input("Purchase Price ($)", min_value=0, value=int(p.get("purchase_price") or 0), step=5000, key=f"{key_prefix}_price")
            current_value_estimate = st.number_input("Current Estimated Value ($)", min_value=0, value=int(p.get("current_value_estimate") or 0), step=5000, help="Leave at 0 to use the purchase price.", key=f"{key_prefix}_value")
        with col2:
            hoa_monthly = st.number_input("Monthly HOA ($)", min_value=0, value=int(p.get("hoa_monthly") or 0), step=10, key=f"{key_prefix}_hoa")
            c1, c2 = st.columns(2)
            with c1:
                insurance_annual = st.number_input("Annual Insurance ($)", min_value=0, value=int(p.get("insurance_annual") or 0), step=50, key=f"{key_prefix}_ins")
            with c2:
                property_tax_annual = st.number_input("Annual Property Tax ($)", min_value=0, value=int(p.get("property_tax_annual") or 0), step=50, key=f"{key_prefix}_tax")
            property_management_monthly = st.number_input("Property Management ($/mo)", min_value=0, value=int(p.get("property_management_monthly") or 0), step=25, help="What you pay a property manager, if any.", key=f"{key_prefix}_mgmt")
        submitted = st.form_submit_button(":material/save: Save Property Details", type="primary", use_container_width=True)

    if submitted:
        if not address:
            st.error("Address is required.")
            return
        if purchase_price <= 0:
            st.error("Purchase Price must be greater than $0.")
            return
        _save_property_fields(
            p, address=address, property_type=property_type, purchase_price=purchase_price,
            current_value_estimate=current_value_estimate, hoa_monthly=hoa_monthly,
            insurance_annual=insurance_annual, property_tax_annual=property_tax_annual,
            property_management_monthly=property_management_monthly,
        )
        st.toast("Property details updated.")
        st.rerun()


def _render_rental_status_subtab(p):
    key_prefix = f"prop_{p['id']}_status"
    with st.form(f"{key_prefix}_form"):
        rental_status = st.selectbox(
            "Status", db.RENTAL_STATUSES,
            index=db.RENTAL_STATUSES.index(p.get("rental_status")) if p.get("rental_status") in db.RENTAL_STATUSES else 0,
            key=f"{key_prefix}_rs",
        )
        monthly_rent = st.number_input("Monthly Rent ($)", min_value=0, value=int(p.get("monthly_rent") or 0), step=25, help="Only counted toward cash flow when status is 'Occupied'.", key=f"{key_prefix}_rent")
        submitted = st.form_submit_button(":material/save: Save Rental Status", type="primary", use_container_width=True)

    if submitted:
        if rental_status == "Occupied" and monthly_rent <= 0:
            st.error("Monthly Rent must be greater than $0 when status is 'Occupied'.")
            return
        _save_property_fields(p, rental_status=rental_status, monthly_rent=monthly_rent)
        st.toast("Rental status updated.")
        st.rerun()


def _render_occupancy_subtab(p):
    key_prefix = f"prop_{p['id']}_occ"
    with st.form(f"{key_prefix}_form"):
        c1, c2 = st.columns(2)
        with c1:
            num_occupants = st.number_input("Number of Occupants", min_value=0, value=int(p.get("num_occupants") or 0), step=1, key=f"{key_prefix}_n")
            move_in_date = st.date_input("Move-In Date", value=_parse_date(p.get("move_in_date")) or date.today(), key=f"{key_prefix}_movein")
        with c2:
            num_keys_given = st.number_input("Number of Keys Given", min_value=0, value=int(p.get("num_keys_given") or 0), step=1, key=f"{key_prefix}_keys")
            parking_storage_info = st.text_input("Parking / Storage Assigned", value=p.get("parking_storage_info", ""), placeholder="e.g., Spot #12, Storage unit B", key=f"{key_prefix}_park")
        submitted = st.form_submit_button(":material/save: Save Occupancy Details", type="primary", use_container_width=True)

    if submitted:
        _save_property_fields(
            p, num_occupants=num_occupants, num_keys_given=num_keys_given,
            move_in_date=move_in_date.isoformat(), parking_storage_info=parking_storage_info,
        )
        st.toast("Occupancy details updated.")
        st.rerun()


def _render_tenant_card(t):
    with st.container(border=True):
        st.markdown(f"**{t['name'] or 'Unnamed tenant'}**")
        st.caption(f"{t['phone'] or 'No phone on file'} · {t['email'] or 'No email on file'}")
        st.caption(f"Lease: {t['lease_start'] or '?'} to {t['lease_end'] or '?'}")
        if t.get("notes"):
            st.caption(t["notes"])
        with st.expander(":material/edit: Edit or Remove"):
            key_prefix = f"tenant_{t['id']}"
            with st.form(f"{key_prefix}_form"):
                name = st.text_input("Name", value=t.get("name", ""), key=f"{key_prefix}_name")
                tc1, tc2 = st.columns(2)
                with tc1:
                    phone = st.text_input("Phone", value=t.get("phone", ""), key=f"{key_prefix}_phone")
                with tc2:
                    email = st.text_input("Email", value=t.get("email", ""), key=f"{key_prefix}_email")
                td1, td2 = st.columns(2)
                with td1:
                    lease_start = st.date_input("Lease Start", value=_parse_date(t.get("lease_start")) or date.today(), key=f"{key_prefix}_start")
                with td2:
                    lease_end = st.date_input("Lease End", value=_parse_date(t.get("lease_end")) or date.today(), key=f"{key_prefix}_end")
                notes = st.text_area("Notes", value=t.get("notes", ""), key=f"{key_prefix}_notes")
                submitted = st.form_submit_button(":material/save: Save Tenant", type="primary", use_container_width=True)
            if submitted:
                if not name:
                    st.error("Tenant name is required.")
                else:
                    db.update_tenant(t["id"], st.session_state.user_id, name, phone, email, lease_start.isoformat(), lease_end.isoformat(), notes)
                    st.toast("Tenant updated.")
                    st.rerun()
            if st.button(":material/delete: Remove Tenant", key=f"{key_prefix}_delete", use_container_width=True):
                db.delete_tenant(t["id"], st.session_state.user_id)
                st.toast("Tenant removed.")
                st.rerun()


def _render_tenants_subtab(p):
    tenants = db.get_tenants(p["id"], st.session_state.user_id)

    expiring = []
    for t in tenants:
        lease_end = _parse_date(t.get("lease_end"))
        if lease_end:
            days_left = (lease_end - date.today()).days
            if 0 <= days_left <= 60:
                expiring.append((t, days_left))
    if expiring:
        names = ", ".join(f"{t['name'] or 'Tenant'} ({d} days left)" for t, d in expiring)
        st.warning(f"Lease ending soon: {names}", icon=":material/schedule:")

    if not tenants:
        st.caption("No tenants on file for this property yet.")
    else:
        for t in tenants:
            _render_tenant_card(t)

    st.markdown("###### Add a Tenant")
    with st.form(f"prop_{p['id']}_add_tenant"):
        name = st.text_input("Name", key=f"prop_{p['id']}_new_tenant_name")
        c1, c2 = st.columns(2)
        with c1:
            phone = st.text_input("Phone", key=f"prop_{p['id']}_new_tenant_phone")
        with c2:
            email = st.text_input("Email", key=f"prop_{p['id']}_new_tenant_email")
        d1, d2 = st.columns(2)
        with d1:
            lease_start = st.date_input("Lease Start", value=date.today(), key=f"prop_{p['id']}_new_tenant_start")
        with d2:
            lease_end = st.date_input("Lease End", value=date.today(), key=f"prop_{p['id']}_new_tenant_end")
        notes = st.text_area("Notes", key=f"prop_{p['id']}_new_tenant_notes")
        submitted = st.form_submit_button(":material/person_add: Add Tenant", type="primary", use_container_width=True)

    if submitted:
        if not name:
            st.error("Tenant name is required.")
        else:
            db.add_tenant(p["id"], st.session_state.user_id, name, phone, email, lease_start.isoformat(), lease_end.isoformat(), notes)
            st.toast(f"Added tenant {name}.")
            st.rerun()


def _render_documents_subtab(p):
    docs = db.get_documents(p["id"], st.session_state.user_id)
    if not docs:
        st.caption("No documents uploaded yet.")
    else:
        for d in docs:
            col1, col2, col3 = st.columns([3, 1.2, 1])
            with col1:
                st.markdown(f"**{d['original_filename']}**")
                st.caption(f"Uploaded {d['uploaded_at']}")
            with col2:
                file_path = os.path.join(db.PORTFOLIO_UPLOADS_DIR, d["stored_filename"])
                if os.path.exists(file_path):
                    with open(file_path, "rb") as f:
                        st.download_button(":material/download: Download", f.read(), file_name=d["original_filename"], key=f"dl_doc_{d['id']}", use_container_width=True)
            with col3:
                if st.button(":material/delete: Remove", key=f"del_doc_{d['id']}", use_container_width=True):
                    db.delete_document(d["id"], st.session_state.user_id)
                    st.toast("Document removed.")
                    st.rerun()

    st.markdown("###### Upload a Document")
    st.caption("Lease agreements, insurance policies, inspection reports - anything worth keeping with this property.")
    uploaded = st.file_uploader("Choose a file", key=f"prop_{p['id']}_uploader", label_visibility="collapsed")
    if uploaded is not None:
        if st.button(":material/upload: Save This Document", key=f"prop_{p['id']}_save_upload", type="primary", use_container_width=True):
            ext = os.path.splitext(uploaded.name)[1]
            stored_filename = f"{p['id']}_{uuid.uuid4().hex}{ext}"
            with open(os.path.join(db.PORTFOLIO_UPLOADS_DIR, stored_filename), "wb") as f:
                f.write(uploaded.getbuffer())
            db.add_document(p["id"], st.session_state.user_id, uploaded.name, stored_filename)
            st.toast(f"Uploaded {uploaded.name}.")
            st.rerun()


def _render_expenses_notes_subtab(p):
    key_prefix = f"prop_{p['id']}_exp"
    with st.form(f"{key_prefix}_form"):
        st.markdown("##### Other Expenses")
        o1, o2 = st.columns([1, 2])
        with o1:
            other_expenses_monthly = st.number_input("Other Monthly Expenses ($)", min_value=0, value=int(p.get("other_expenses_monthly") or 0), step=25, help="Utilities you cover, landscaping, pest control, repairs reserve, etc.", key=f"{key_prefix}_amt")
        with o2:
            other_expenses_notes = st.text_input("What's included in that?", value=p.get("other_expenses_notes", ""), placeholder="e.g., Lawn care $80 + water $70", key=f"{key_prefix}_line")
        st.markdown("##### Notes")
        notes = st.text_area("General notes about this property", value=p.get("notes", ""), label_visibility="collapsed", placeholder="Anything else worth remembering...", key=f"{key_prefix}_notes")
        submitted = st.form_submit_button(":material/save: Save", type="primary", use_container_width=True)

    if submitted:
        _save_property_fields(p, other_expenses_monthly=other_expenses_monthly, other_expenses_notes=other_expenses_notes, notes=notes)
        st.toast("Updated.")
        st.rerun()


def _render_property_nav(properties):
    """Left-hand property picker. Colored left border on each row mirrors
    the cash-flow status (green/red/gray), same visual language used
    elsewhere in the app for deal grades, so status reads at a glance
    without needing to open each property."""
    losing_ids = {p["id"] for p in properties if _monthly_cash_flow(p) is not None and _monthly_cash_flow(p) < 0}
    properties_sorted = sorted(properties, key=lambda p: 0 if p["id"] in losing_ids else 1)

    valid_ids = {p["id"] for p in properties}
    if st.session_state.get("portfolio_selected_id") not in valid_ids:
        st.session_state.portfolio_selected_id = properties_sorted[0]["id"]

    items = []
    for p in properties_sorted:
        cash_flow = _monthly_cash_flow(p)
        if cash_flow is None:
            accent, cf_text = "var(--radar-border)", "Not rented"
        elif cash_flow >= 0:
            accent, cf_text = "var(--radar-success)", f"+${cash_flow:,.0f}/mo"
        else:
            accent, cf_text = "var(--radar-danger)", f"-${abs(cash_flow):,.0f}/mo"
        label = p["address"] if len(p["address"]) <= 30 else p["address"][:29] + "…"
        items.append({"label": label, "value": p["id"], "caption": cf_text, "accent": accent})

    # state_key points directly at portfolio_selected_id (not the nav's own
    # default key) since the delete/add-property flows elsewhere in this
    # file also read/write that exact key - a separate nav-internal key
    # would silently fall out of sync with those.
    selected_id = render_side_nav(items, key_prefix="portfolio_nav", state_key="portfolio_selected_id")
    return next(p for p in properties_sorted if p["id"] == selected_id)


def _render_property_detail(p):
    nav_col, content_col = st.columns([1, 3])
    with nav_col:
        active_section = render_side_nav(
            [
                {"label": "Overview", "icon": ":material/dashboard:"},
                {"label": "Mortgage", "icon": ":material/account_balance:"},
                {"label": "Property", "icon": ":material/home:"},
                {"label": "Rental Status", "icon": ":material/key:"},
                {"label": "Occupancy", "icon": ":material/groups:"},
                {"label": "Tenants", "icon": ":material/badge:"},
                {"label": "Documents", "icon": ":material/description:"},
                {"label": "Other & Notes", "icon": ":material/payments:"},
            ],
            key_prefix="property_detail_nav",
        )
    with content_col:
        if active_section == "Overview":
            _render_overview_subtab(p)
        elif active_section == "Mortgage":
            _render_mortgage_subtab(p)
        elif active_section == "Property":
            _render_property_details_subtab(p)
        elif active_section == "Rental Status":
            _render_rental_status_subtab(p)
        elif active_section == "Occupancy":
            _render_occupancy_subtab(p)
        elif active_section == "Tenants":
            _render_tenants_subtab(p)
        elif active_section == "Documents":
            _render_documents_subtab(p)
        else:
            _render_expenses_notes_subtab(p)


def _render_summary_tab(properties):
    if not properties:
        render_empty_state(
            "chart", "Nothing to summarize yet",
            "Add a property first, then this tab will show cash flow and equity charts across your whole portfolio.",
        )
        return

    df = pd.DataFrame([{
        "Address": p["address"],
        "Type": p["property_type"],
        "Current Value": _current_value(p),
        "Equity": _current_value(p) - (p.get("mortgage_balance") or 0),
        "Mortgage Balance": p.get("mortgage_balance") or 0,
        "Rented": "Yes" if p.get("is_rented") else "No",
        "Monthly Rent": (p.get("monthly_rent") or 0) if p.get("is_rented") else 0,
        "Monthly Costs": _monthly_fixed_costs(p),
        "Monthly Cash Position": _monthly_net_position(p),
    } for p in properties])

    rented_count = int((df["Rented"] == "Yes").sum())
    total_value = df["Current Value"].sum()
    total_equity = df["Equity"].sum()
    total_position = df["Monthly Cash Position"].sum()
    position_color = "var(--radar-success)" if total_position >= 0 else "var(--radar-danger)"
    position_verb = "netting" if total_position >= 0 else "losing"

    st.markdown(f"""
        <div style='background:var(--radar-surface-alt); border-left:4px solid var(--radar-primary); border-radius:var(--radar-radius-md);
                    padding:var(--radar-space-4) var(--radar-space-5); margin-bottom:var(--radar-space-5);'>
            <p style='margin:0; color:var(--radar-navy); font-size:15px; line-height:1.7;'>
                You own <strong>{len(properties)}</strong> propert{'y' if len(properties) == 1 else 'ies'} worth <strong>${total_value:,.0f}</strong> combined,
                with <strong>${total_equity:,.0f}</strong> in equity. <strong>{rented_count}</strong> of them {'is' if rented_count == 1 else 'are'} currently rented out.
                Across everything you own, you're <strong style='color:{position_color};'>{position_verb} ${abs(total_position):,.0f}/mo</strong>.
            </p>
        </div>
    """, unsafe_allow_html=True)

    # Charts render transparent so they sit naturally on the app's own light
    # or dark background rather than showing a boxed-in white/black card -
    # font color is picked to stay legible against whichever mode is active.
    chart_font_color = "#e2e8f0" if st.session_state.get("theme_mode") == "dark" else "#0f172a"
    chart_layout = dict(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font_color=chart_font_color)
    chart_height = max(220, 70 * len(properties))

    view = st.radio(
        "Chart view", ["Cash Flow", "Equity vs. Mortgage", "Income & Expenses", "Portfolio Composition"],
        horizontal=True, label_visibility="collapsed", key="portfolio_summary_view",
    )

    if view == "Cash Flow":
        cash_df = df.sort_values("Monthly Cash Position")
        cash_df["Status"] = cash_df["Monthly Cash Position"].apply(lambda v: "Losing money" if v < 0 else "Cash flow positive")
        fig = px.bar(
            cash_df, x="Monthly Cash Position", y="Address", orientation="h", color="Status",
            color_discrete_map={"Losing money": "#ef4444", "Cash flow positive": "#10b981"},
            text=cash_df["Monthly Cash Position"].apply(lambda v: f"${v:,.0f}"),
        )
        fig.update_traces(textposition="outside")
        fig.update_layout(title="Monthly Cash Position by Property", xaxis_title="$ / month", yaxis_title="",
                           height=chart_height, margin=dict(l=10, r=10, t=40, b=10), **chart_layout)
        st.plotly_chart(fig, use_container_width=True, key="portfolio_cashflow_chart")

    elif view == "Equity vs. Mortgage":
        equity_df = df.melt(id_vars=["Address"], value_vars=["Equity", "Mortgage Balance"], var_name="Component", value_name="Amount")
        fig = px.bar(
            equity_df, x="Amount", y="Address", orientation="h", color="Component", barmode="stack",
            color_discrete_map={"Equity": "#2563eb", "Mortgage Balance": "#94a3b8"},
        )
        fig.update_layout(title="Equity vs. Mortgage Balance by Property", xaxis_title="$", yaxis_title="",
                           height=chart_height, margin=dict(l=10, r=10, t=40, b=10), **chart_layout)
        st.plotly_chart(fig, use_container_width=True, key="portfolio_equity_chart")

    elif view == "Income & Expenses":
        # Expenses plotted as negative values so each property's bar naturally
        # stacks around zero - the point where the bar crosses zero visually
        # is that property's net cash position, with the full cost breakdown
        # visible instead of just the net number.
        rows = []
        for p in properties:
            if p.get("is_rented"):
                rows.append({"Address": p["address"], "Category": "Rent Income", "Amount": p.get("monthly_rent") or 0})
            for label, val in [
                ("Mortgage", p.get("monthly_mortgage_payment") or 0),
                ("PMI", p.get("monthly_pmi") or 0),
                ("HOA", p.get("hoa_monthly") or 0),
                ("Insurance", (p.get("insurance_annual") or 0) / 12),
                ("Property Tax", (p.get("property_tax_annual") or 0) / 12),
                ("Property Mgmt", p.get("property_management_monthly") or 0),
                ("Other Expenses", p.get("other_expenses_monthly") or 0),
            ]:
                if val:
                    rows.append({"Address": p["address"], "Category": label, "Amount": -val})
        ie_df = pd.DataFrame(rows)
        fig = px.bar(
            ie_df, x="Amount", y="Address", orientation="h", color="Category", barmode="relative",
            color_discrete_map={
                "Rent Income": "#10b981", "Mortgage": "#1e3a8a", "PMI": "#7c3aed", "HOA": "#2563eb", "Insurance": "#60a5fa",
                "Property Tax": "#94a3b8", "Property Mgmt": "#f59e0b", "Other Expenses": "#ef4444",
            },
        )
        fig.add_vline(x=0, line_width=1, line_color=chart_font_color)
        fig.update_layout(title="Monthly Income & Expenses by Property", xaxis_title="$ / month", yaxis_title="",
                           height=chart_height, margin=dict(l=10, r=10, t=40, b=10), **chart_layout)
        st.plotly_chart(fig, use_container_width=True, key="portfolio_income_expense_chart")

    elif view == "Portfolio Composition":
        fig = px.pie(df, names="Address", values="Current Value", hole=0.45,
                     color_discrete_sequence=px.colors.qualitative.Set2)
        fig.update_traces(textinfo="label+percent", textposition="outside")
        fig.update_layout(title="Portfolio Value by Property", showlegend=False,
                           height=chart_height + 100, margin=dict(l=10, r=10, t=40, b=10), **chart_layout)
        st.plotly_chart(fig, use_container_width=True, key="portfolio_composition_chart")

    st.markdown("##### All Properties")
    display_df = df[["Address", "Type", "Current Value", "Equity", "Rented", "Monthly Rent", "Monthly Costs", "Monthly Cash Position"]].copy()
    for col in ["Current Value", "Equity", "Monthly Rent", "Monthly Costs", "Monthly Cash Position"]:
        display_df[col] = display_df[col].apply(lambda v: f"${v:,.0f}")
    st.dataframe(display_df, use_container_width=True, hide_index=True, height=len(display_df) * 35 + 38)


def render_portfolio_page():
    st.markdown("""
        <style>
        div.st-key-portfolio_hero {
            background: var(--radar-gradient-hero);
            padding: var(--radar-space-6) var(--radar-space-7);
            margin-bottom: var(--radar-space-5);
            border-radius: 0 0 var(--radar-radius-xl) var(--radar-radius-xl);
        }
        </style>
    """, unsafe_allow_html=True)

    with st.container(key="portfolio_hero"):
        st.markdown(f"""
            <div style='text-align:center; max-width:760px; margin:0 auto;'>
                <div style='display:flex; align-items:center; justify-content:center; gap:14px; margin-bottom:10px;'>
                    <div style='background: var(--radar-gradient-brand); width: 48px; height: 48px;
                                border-radius: var(--radar-radius-md); display:flex; align-items:center; justify-content:center; flex-shrink:0;'>
                        {svg_icon("home", size=24, color="white")}
                    </div>
                    <div style='font-family:var(--radar-font-display); font-size:32px; font-weight:800; color:white; line-height:1.2;'>My Portfolio</div>
                </div>
                <div style='font-size:16px; color:var(--radar-text-on-dark-muted);'>What you own, what it costs, and whether it cash flows</div>
            </div>
        """, unsafe_allow_html=True)

    properties = db.get_portfolio_properties(st.session_state.user_id)

    total_value = sum(_current_value(p) for p in properties)
    total_equity = sum(_current_value(p) - (p.get("mortgage_balance") or 0) for p in properties)
    rental_cash_flows = [_monthly_cash_flow(p) for p in properties if p.get("is_rented")]
    total_rental_cash_flow = sum(rental_cash_flows)
    total_net_position = sum(_monthly_net_position(p) for p in properties)

    stat_cols = st.columns(5)
    with stat_cols[0]:
        render_stat_card("home", "Properties Owned", len(properties), accent="var(--radar-primary)")
    with stat_cols[1]:
        render_stat_card("dollar", "Total Portfolio Value", f"${total_value:,.0f}", accent="#7c3aed")
    with stat_cols[2]:
        render_stat_card("chart", "Total Equity", f"${total_equity:,.0f}", accent="#059669")
    with stat_cols[3]:
        cf_color = "var(--radar-success)" if total_rental_cash_flow >= 0 else "var(--radar-danger)"
        cf_label = f"${total_rental_cash_flow:,.0f}/mo" if rental_cash_flows else "-"
        render_stat_card("trophy", "Rental Cash Flow", cf_label, accent=cf_color)
    with stat_cols[4]:
        net_color = "var(--radar-success)" if total_net_position >= 0 else "var(--radar-danger)"
        net_label = f"${total_net_position:,.0f}/mo" if properties else "-"
        render_stat_card("chart", "Cash Flow (All Properties)", net_label, accent=net_color)

    st.markdown("<div style='height:16px;'></div>", unsafe_allow_html=True)

    tab1, tab2, tab3 = st.tabs([":material/list_alt: My Properties", ":material/add_home: Add a Property", ":material/bar_chart: Summary"])

    with tab1:
        if not properties:
            render_empty_state(
                "home", "No properties yet",
                "Add the properties you own - rentals or your own home - to track equity, costs, and whether your rentals are cash-flow positive.",
            )
        else:
            losing_properties = [p for p in properties if _monthly_cash_flow(p) is not None and _monthly_cash_flow(p) < 0]
            if losing_properties:
                names = ", ".join(f"{p['address']} (-${abs(_monthly_cash_flow(p)):,.0f}/mo)" for p in losing_properties)
                st.error(f"{len(losing_properties)} propert{'y is' if len(losing_properties) == 1 else 'ies are'} losing money each month: {names}", icon=":material/warning:")

            nav_col, detail_col = st.columns([1, 4])
            with nav_col:
                selected = _render_property_nav(properties)
            with detail_col:
                _render_property_detail(selected)

    with tab2:
        if not plan_limits.is_within_limit(st.session_state.user_role, st.session_state.user_plan, "portfolio_properties", len(properties)):
            pricing.render_plan_limit_notice("portfolio_properties", len(properties))
        else:
            new_property = _property_form(key_prefix="add")
            if new_property:
                new_id = db.add_portfolio_property(st.session_state.user_id, **new_property)
                st.session_state.portfolio_selected_id = new_id
                st.success(f"Added {new_property['address']} to your portfolio. Switch to the 'My Properties' tab to fill in tenants, documents, and more.")
                st.rerun()

    with tab3:
        _render_summary_tab(properties)
