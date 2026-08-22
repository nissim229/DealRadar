"""
components/analytics_atoms.py
Low-level formatting helpers + generic UI atoms, split out of
components/analytics.py (Section 5 monolith-split plan).
render_empty_state/render_stat_card are NOT analytics-specific despite
having lived there - components/portfolio.py imports both directly.
Re-exported by components/analytics.py so both that cross-file import
and every internal analytics.py caller keep working unchanged.
"""
import streamlit as st
from datetime import datetime

from icons import icon as svg_icon
from data_utils import clean_value, relative_time


def _format_price_short(price):
    """Abbreviates a price for map pin labels ($450,000 -> "$450K"), matching
    how Zillow shows price directly on unclustered pins - useful for an
    investor eyeballing price spread across the map before clicking anything."""
    try:
        price = float(price)
    except (TypeError, ValueError):
        return ""
    if price >= 1_000_000:
        return f"${price / 1_000_000:.2g}M"
    return f"${price / 1_000:.0f}K"


def _safe_hoa(source):
    """hoa_monthly, defaulting to 0 - the 0-default (not None) is what
    every compute_deal_metrics call site here expects. Missing-value
    normalization itself lives in data_utils.clean_value."""
    val = clean_value(source.get("hoa_monthly"))
    if val is None:
        return 0
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0


def _format_relative_time(timestamp_str):
    """'Saved 3 hours ago' - deliberately a freshness note, not a claim
    about whether the listing is still active - this app has no live
    MLS/IDX feed to verify that, so the honest signal to show is how long
    ago the snapshot was taken, matching how the major listing sites
    handle results they can't re-verify in real time either. Bucketing
    itself lives in data_utils.relative_time; this just owns the "Saved"
    framing and the on-parse-failure fallback shape."""
    try:
        datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return f"Saved {timestamp_str}"
    return f"Saved {relative_time(timestamp_str)}"


def render_empty_state(icon_name, title, description, cta_label=None, cta_page=None, accent="var(--radar-primary)"):
    """A designed empty state (icon + headline + description + optional
    navigation button) instead of a bare st.info() one-liner - this is the
    first thing a brand-new user with no data yet actually sees, so it's
    worth more than a single line of text."""
    st.markdown(f"""
        <div style='text-align:center; padding:var(--radar-space-8) var(--radar-space-5); background:var(--radar-surface-alt);
                    border:1px dashed var(--radar-border); border-radius:var(--radar-radius-lg);'>
            <div style='width:56px; height:56px; border-radius:50%; background:var(--radar-surface); display:flex; align-items:center;
                        justify-content:center; margin:0 auto var(--radar-space-4) auto; box-shadow:var(--radar-shadow-sm);'>
                {svg_icon(icon_name, size=26, color=accent)}
            </div>
            <div style='font-weight:700; font-size:var(--radar-text-lg); color:var(--radar-navy); margin-bottom:6px;'>{title}</div>
            <div style='color:var(--radar-text-muted); font-size:14px; max-width:420px; margin:0 auto;'>{description}</div>
        </div>
    """, unsafe_allow_html=True)
    if cta_label and cta_page:
        st.markdown("<div style='height:12px;'></div>", unsafe_allow_html=True)
        _, btn_col, _ = st.columns([1, 1.4, 1])
        with btn_col:
            if st.button(cta_label, key=f"empty_state_cta_{cta_page}_{title}", type="primary", width="stretch"):
                st.session_state.current_page = cta_page
                st.rerun()


def render_stat_card(icon_name, label, value, accent="var(--radar-primary)"):
    st.markdown(f"""
        <div class='dealradar-stat-card' style='background:var(--radar-surface); border:1px solid var(--radar-border); border-radius:var(--radar-radius-md); padding:10px 14px;
                    border-left: 3px solid {accent}; display:flex; align-items:center; gap:10px;'>
            <div style='flex-shrink:0; color:{accent};'>{svg_icon(icon_name, size=19)}</div>
            <div style='line-height:1.15;'>
                <div style='font-size:16px; font-weight:800; color:var(--radar-navy);'>{value}</div>
                <div style='font-size:10.5px; color:var(--radar-text-muted); font-weight:600; letter-spacing:0.2px;'>{label}</div>
            </div>
        </div>
    """, unsafe_allow_html=True)


def _render_clickable_hero_card(card_id, icon_shortcode, value, label, on_click):
    """Same CSS-restyled-button pattern used for the admin dashboard's stat
    cards (components/admin_controls.py) - a real st.button dressed up as a
    card, since a plain HTML div can't open an st.dialog on click."""
    with st.container(key=f"dashboard_hero_card_{card_id}"):
        if st.button(f"{icon_shortcode} **{value}**\n{label}", key=f"dashboard_hero_card_btn_{card_id}",
                     width="stretch"):
            on_click()

