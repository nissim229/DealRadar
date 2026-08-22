"""
components/analytics_dialogs.py
The 3 hero stat-card drill-down dialogs (Best Deal/Deals Meeting
Target/Portfolio Value Breakdown), split out of components/analytics.py
(Section 5 monolith-split plan). Called only from
render_analytics_dashboard's hero card on_click handlers.
"""
import streamlit as st
import pandas as pd


@st.dialog("Best Deal Details")
def _show_best_deal_dialog(pts, metrics, best_idx):
    if best_idx is None:
        st.caption("No scan data yet - run a live scan to see your best deal here.")
        return
    p, m = pts[best_idx], metrics[best_idx]
    st.markdown(f"**{p.get('address') or p.get('title', 'Untitled Property')}**")
    detail_bits = []
    if p.get("beds"):
        detail_bits.append(f"{p['beds']} bd")
    if p.get("baths"):
        detail_bits.append(f"{p['baths']} ba")
    if p.get("sqft"):
        detail_bits.append(f"{p['sqft']:,} sqft")
    if p.get("property_type"):
        detail_bits.append(p["property_type"])
    if detail_bits:
        st.caption(" · ".join(str(b) for b in detail_bits))
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Price", f"${p['price']:,.0f}")
        st.metric("Cash-on-Cash Return", f"{m['coc']:.2f}%")
    with col2:
        st.metric("Cap Rate", f"{m['cap_rate']:.2f}%")
        st.metric("Annual Cash Flow", f"${m['cashflow']:,.2f}")
    st.caption("Full results with every match are below the search form.")


@st.dialog("Deals Meeting Your Target")
def _show_deals_meeting_target_dialog(pts, metrics):
    if not pts:
        st.caption("No scan data yet - run a live scan to see matches here.")
        return
    matches = [(p, m) for p, m in zip(pts, metrics) if m["grade"] == "excellent"]
    if not matches:
        st.caption("No deals meet your target return yet in this scan. Try lowering your target return in the sidebar.")
        return
    matches.sort(key=lambda pm: pm[1]["coc"], reverse=True)
    st.dataframe(
        pd.DataFrame([
            {"Address": p.get("address") or p.get("title", "-"), "Price": f"${p['price']:,.0f}", "CoC Return": f"{m['coc']:.1f}%"}
            for p, m in matches
        ]),
        width="stretch", hide_index=True, height=min(len(matches), 10) * 35 + 38,
    )
    st.caption("Full results with map and filters are below the search form.")


@st.dialog("Portfolio Value Breakdown")
def _show_total_value_dialog(pts):
    if not pts:
        st.caption("No scan data yet - run a live scan to see a breakdown here.")
        return

    def _city_of(addr):
        parts = [x.strip() for x in (addr or "").split(",")]
        return parts[-2] if len(parts) >= 2 else (addr or "Unknown")

    by_city = {}
    for p in pts:
        city = _city_of(p.get("address", ""))
        entry = by_city.setdefault(city, {"count": 0, "total": 0})
        entry["count"] += 1
        entry["total"] += p.get("price", 0)
    rows = sorted(by_city.items(), key=lambda kv: kv[1]["total"], reverse=True)
    st.dataframe(
        pd.DataFrame([
            {"City": city, "Properties": info["count"], "Total Value": f"${info['total']:,.0f}"}
            for city, info in rows
        ]),
        width="stretch", hide_index=True, height=min(len(rows), 10) * 35 + 38,
    )
    st.caption(f"{len(pts)} propert{'y' if len(pts) == 1 else 'ies'} scanned across {len(by_city)} location{'s' if len(by_city) != 1 else ''} in this scan.")
