"""
scan_loading.py
The "Cyber Radar" scan-in-progress visual (concentric rings, crosshair,
conic-gradient sweep, glowing core with a category icon) - shared between
real estate's Run Live Scan (components/analytics.py) and Cars' Find a Car
(components/car_search.py) so both categories get the same big radar-scope
loading state, just with the icon/copy swapped to match what's being
searched. See [[cyber-radar-button-and-loading]] for how this design was
arrived at (4 rounds, moved from a white card to a self-contained dark
scope) and [[brand-design-admin-panel]] for how its colors are driven by
the admin's saved --radar-accent tokens, not hardcoded hex.
"""

import streamlit as st
from icons import icon as svg_icon

_COPY_BY_CATEGORY = {
    "real_estate": ("home", "Scanning the market...", "Matching properties against your criteria"),
    "cars": ("car", "Scanning the market...", "Matching vehicles against your criteria"),
}


def render_scan_loading_radar(active_category="real_estate"):
    icon_name, title, subtitle = _COPY_BY_CATEGORY.get(active_category, _COPY_BY_CATEGORY["real_estate"])
    st.markdown("""
        <style>
        @keyframes dealradar-radar-sweep {
            to { transform: translate(-50%, -50%) rotate(360deg); }
        }
        .dealradar-scan-wrap {
            display: flex; flex-direction: column; align-items: center; justify-content: center;
            padding: 20px 0 8px 0;
        }
        .dealradar-radar-scope {
            position: relative;
            width: 260px; height: 260px;
            border-radius: 50%;
            margin-bottom: 22px;
            overflow: hidden;
            background:
                repeating-radial-gradient(circle at center, transparent 0, transparent 39px, rgba(var(--radar-accent-rgb), 0.22) 40px, transparent 41px),
                radial-gradient(circle at center, #111c2e 0%, #0a0f1a 100%);
            box-shadow: 0 0 45px rgba(var(--radar-accent-rgb), 0.3), inset 0 0 40px rgba(0, 0, 0, 0.5);
        }
        .dealradar-radar-scope::before, .dealradar-radar-scope::after {
            content: ""; position: absolute; background: rgba(var(--radar-accent-rgb), 0.18);
        }
        .dealradar-radar-scope::before { top: 0; bottom: 0; left: 50%; width: 1px; }
        .dealradar-radar-scope::after { left: 0; right: 0; top: 50%; height: 1px; }
        .dealradar-radar-scope .sweep {
            position: absolute; top: 50%; left: 50%;
            width: 380px; height: 380px;
            transform: translate(-50%, -50%);
            background: conic-gradient(from 0deg, transparent 60%, rgba(var(--radar-accent-rgb), 0.55) 100%);
            animation: dealradar-radar-sweep 2.5s linear infinite;
        }
        .dealradar-radar-scope .core {
            position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%);
            z-index: 10;
            width: 92px; height: 92px; border-radius: 50%;
            background: radial-gradient(circle at 35% 30%, var(--radar-accent), var(--radar-accent-dark));
            box-shadow: 0 0 26px rgba(var(--radar-accent-rgb), 0.85);
            display: flex; align-items: center; justify-content: center;
        }
        .dealradar-radar-scope .core svg { width: 42px; height: 42px; color: #f0fdff; }
        .dealradar-scan-title {
            font-weight: 700; color: white; font-size: 18px;
        }
        .dealradar-scan-sub {
            color: var(--radar-text-on-dark-muted); font-size: 14px; margin-top: 4px;
        }
        </style>
    """, unsafe_allow_html=True)
    st.markdown(
        "<div class='dealradar-scan-wrap'>"
        "<div class='dealradar-radar-scope'>"
        "<span class='sweep'></span>"
        f"<div class='core'>{svg_icon(icon_name, size=42)}</div>"
        "</div>"
        f"<div class='dealradar-scan-title'>{title}</div>"
        f"<div class='dealradar-scan-sub'>{subtitle}</div>"
        "</div>",
        unsafe_allow_html=True,
    )
