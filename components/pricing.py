"""
components/pricing.py
The "Buy Scan Credits" package dialog and the shared "you've hit your
plan's limit" upsell block, used from portfolio.py, property_card.py, and
topbar.py, plus analytics.py's credit-exhausted gate. Kept standalone
rather than folded into analytics.py: analytics.py
already imports components/property_card.py, and property_card.py needs
this dialog too - putting it in analytics.py would create a circular import.
"""
import streamlit as st
import database as db
import plan_limits
from icons import icon as svg_icon


def _apply_discount(price, promo):
    """Returns the discounted price for `price` given an applied promo dict
    ({"discount_type": "percent"|"flat", "discount_value": ...}), or the
    unchanged price if promo is None. Never goes below $0."""
    if not promo:
        return price
    if promo["discount_type"] == "percent":
        return max(0, round(price * (1 - promo["discount_value"] / 100), 2))
    return max(0, round(price - promo["discount_value"], 2))


@st.dialog("Choose a Plan")
def render_pricing_dialog():
    """Package/pricing picker - shown when a user hits their plan's credit
    limit or one of the resource caps (portfolio properties, saved
    properties, saved searches). No real payment processor is wired up yet
    (that needs a real decision on a provider, not something to silently
    bolt on) - this is a working visual checkout that simulates the
    purchase by adding credits and upgrading the plan directly, clearly
    labeled as a demo so nobody mistakes it for a real charge.

    Prices/credits/limits come from db.get_credit_packages() - admin-
    editable (Admin Controls > Pricing), not hardcoded."""
    st.caption("Each plan bundles scan credits with higher limits on portfolio properties, saved listings, and saved searches.")

    promo_col1, promo_col2 = st.columns([3, 1])
    with promo_col1:
        promo_input = st.text_input("Promo code", key="pricing_promo_input", placeholder="Optional", label_visibility="collapsed")
    with promo_col2:
        if st.button("Apply", key="pricing_promo_apply_btn", use_container_width=True):
            if promo_input.strip():
                code_row, reason = db.validate_promo_code(promo_input.strip().upper())
                if code_row:
                    st.session_state.applied_promo = code_row
                    st.toast(f"Promo code {code_row['code']} applied.")
                else:
                    st.session_state.applied_promo = None
                    st.error(reason)
            else:
                st.session_state.applied_promo = None

    applied_promo = st.session_state.get("applied_promo")
    if applied_promo:
        discount_label = f"{applied_promo['discount_value']:.0f}% off" if applied_promo["discount_type"] == "percent" else f"${applied_promo['discount_value']:.0f} off"
        st.caption(f"{svg_icon('lightbulb', size=13, color='var(--radar-success)')} Code **{applied_promo['code']}** applied - {discount_label} every package below.", unsafe_allow_html=True)

    packages = db.get_credit_packages()
    tiers = [(name, tier) for name, tier in packages.items() if name != "Free"]
    pkg_cols = st.columns(len(tiers))
    for (tier_name, tier), col in zip(tiers, pkg_cols):
        with col:
            border_color = "var(--radar-primary)" if tier["highlight"] else "var(--radar-border)"
            badge_html = (
                '<div style="background:var(--radar-primary); color:white; font-size:10.5px; font-weight:700; '
                'border-radius:var(--radar-radius-pill); padding:2px 10px; display:inline-block; margin-bottom:8px;">MOST POPULAR</div>'
                if tier["highlight"] else ""
            )
            portfolio_line = "Unlimited" if tier["portfolio_properties"] is None else tier["portfolio_properties"]
            saved_line = "Unlimited" if tier["saved_properties"] is None else tier["saved_properties"]
            searches_line = "Unlimited" if tier["saved_searches"] is None else tier["saved_searches"]
            final_price = _apply_discount(tier["price"], applied_promo)
            price_html = (
                f"<span style='font-size:16px; color:var(--radar-text-muted); text-decoration:line-through; margin-right:6px;'>${tier['price']:.0f}</span>${final_price:.0f}"
                if applied_promo and final_price != tier["price"] else f"${tier['price']:.0f}"
            )
            # Built as one unbroken line, not a multi-line f-string: when
            # badge_html is "" (non-highlighted tiers), the substitution
            # leaves a blank line in the middle of the HTML block, and
            # Streamlit's markdown parser treats a blank line as the end of
            # a raw-HTML block (standard CommonMark behavior) - everything
            # after it then gets parsed as plain text instead of HTML.
            card_html = (
                f"<div style='border:2px solid {border_color}; border-radius:var(--radar-radius-lg); padding:var(--radar-space-4); text-align:center;'>"
                f"{badge_html}"
                f"<div style='font-weight:700; font-size:var(--radar-text-lg); color:var(--radar-navy);'>{tier_name}</div>"
                f"<div style='font-size:28px; font-weight:800; color:var(--radar-navy); margin:8px 0;'>{price_html}</div>"
                f"<div style='color:var(--radar-text-muted); font-size:13px; text-align:left; margin:0 auto 14px auto; display:inline-block;'>"
                f"{tier['credits']} scan credits<br>{portfolio_line} portfolio properties<br>{saved_line} saved properties<br>{searches_line} saved searches"
                f"</div></div>"
            )
            st.markdown(card_html, unsafe_allow_html=True)
            st.markdown("<div style='margin-top:8px;'></div>", unsafe_allow_html=True)
            if st.button("Buy Now", key=f"buy_pkg_{tier_name}", use_container_width=True,
                         type="primary" if tier["highlight"] else "secondary"):
                db.add_purchased_credits(st.session_state.user_id, tier["credits"])
                db.update_user_plan(st.session_state.user_id, tier_name)
                db.log_credit_transaction(st.session_state.user_id, tier_name, final_price, tier["credits"],
                                           promo_code=applied_promo["code"] if applied_promo else None)
                if applied_promo:
                    db.redeem_promo_code(applied_promo["code"])
                    st.session_state.applied_promo = None
                st.session_state.user_credits += tier["credits"]
                if plan_limits.plan_rank(tier_name) > plan_limits.plan_rank(st.session_state.user_plan):
                    st.session_state.user_plan = tier_name
                st.toast(f"Demo purchase complete - {tier['credits']} credits added, plan is now {st.session_state.user_plan}. No real charge was made.")
                st.rerun()
    st.caption(f"{svg_icon('lightbulb', size=13, color='var(--radar-text-subtle)')} This is a demo checkout - no payment is actually processed.", unsafe_allow_html=True)


def render_plan_limit_notice(resource, current_count):
    """Inline upsell block shown in place of an "add" action once a user
    has hit their plan's cap on `resource` (one of plan_limits.RESOURCE_LABELS'
    keys). Clicking the button opens the same dialog buying credits does."""
    plan = st.session_state.get("user_plan", "Free")
    limit = plan_limits.get_limit(plan, resource)
    label = plan_limits.RESOURCE_LABELS.get(resource, resource)
    st.markdown(f"""
        <div style='background: var(--radar-surface-alt); border: 1px solid var(--radar-border); border-radius: var(--radar-radius-md);
                    padding: var(--radar-space-4); text-align:center; margin-bottom: var(--radar-space-3);'>
            {svg_icon("lightbulb", size=20, color="var(--radar-primary)")}
            <div style='margin-top: var(--radar-space-2); color: var(--radar-text); font-weight: var(--radar-weight-semibold);'>
                Your {plan} plan allows {limit} {label} - you're at {current_count}.
            </div>
            <div style='color: var(--radar-text-muted); font-size: var(--radar-text-sm); margin-top: 4px;'>
                Upgrade to raise this limit.
            </div>
        </div>
    """, unsafe_allow_html=True)
    if st.button("View Plans", type="primary", key=f"upgrade_cta_{resource}"):
        render_pricing_dialog()
