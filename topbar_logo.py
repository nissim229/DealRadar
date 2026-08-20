"""
topbar_logo.py
Builds the topbar "DEAL RADAR" logo lockup - a circular icon badge (house
for real estate, car for cars) + "DEAL"/"RADAR" wordmark + a descriptive
caption, each category colored from its own token (--radar-primary for
real estate, --radar-accent for cars). This coded version is the default;
an admin can override it per category with raw HTML pasted in Admin
Controls > Brand & Design (components/admin_controls.py's
_render_brand_design_tab), which is why the HTML-building logic lives
here as plain string functions rather than straight st.markdown calls in
main.py - both main.py's real topbar and admin_controls.py's live preview
need to build the exact same markup.
"""

import streamlit as st
import database as db

_ICON_PATHS = {
    "real_estate": (
        '<path d="M2.25 12l8.954-8.955c.44-.439 1.152-.439 1.591 0L21.75 12M4.5 9.75v10.125c0 .621.504 1.125 1.125 '
        '1.125H9.75v-4.875c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125V21h4.125c.621 0 1.125-.504 '
        '1.125-1.125V9.75M8.25 21h8.25" />'
    ),
    "cars": (
        '<path d="M15.75 6H8.25L6.155 9.143a.75.75 0 00-.096.36V15c0 .414.336.75.75.75h1.5a.75.75 0 00.75-.75v-.75h10.5'
        'v.75a.75.75 0 00.75.75h1.5a.75.75 0 00.75-.75V9.502a.75.75 0 00-.096-.36L15.75 6zm-7.875 5.25a.75.75 0 110-1.5'
        '.75.75 0 010 1.5zm8.25 0a.75.75 0 110-1.5.75.75 0 010 1.5zM4.5 16.5h15M6 16.5v1.5a.75.75 0 01-.75.75H4.5A.75.75 '
        '0 013.75 18v-1.5M20.25 16.5V18a.75.75 0 01-.75.75h-.75a.75.75 0 01-.75-.75v-1.5" />'
    ),
}
_CAPTIONS = {
    "real_estate": "PREMIUM REAL ESTATE LOCATOR",
    "cars": "PREMIUM AUTOMOTIVE TRACKER",
}
_COLOR_VARS = {
    "real_estate": "var(--radar-primary)",
    "cars": "var(--radar-accent)",
}


def build_default_logo_html(category_value):
    """The coded fallback lockup - a raw HTML string, not an st.markdown
    call, so both the real topbar and the admin's live preview can build
    the exact same markup. A custom logo image uploaded via Brand &
    Design's single global uploader still swaps in for the icon (dropping
    the ring, which is chrome for *our* icon), same as before per-category
    HTML overrides existed."""
    icon_path_html = _ICON_PATHS.get(category_value, _ICON_PATHS["real_estate"])
    caption = _CAPTIONS.get(category_value, _CAPTIONS["real_estate"])
    logo_color_var = _COLOR_VARS.get(category_value, _COLOR_VARS["real_estate"])

    custom_logo = db.get_brand_settings()["logo_data_uri"]
    if custom_logo:
        scope_content = f"<img src='{custom_logo}' style='width: 100%; height: 100%; object-fit: cover; border-radius: 50%;' />"
    else:
        scope_content = (
            '<svg class="dealradar-logo-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" '
            'stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">'
            f"{icon_path_html}</svg>"
        )

    return (
        f"<div class='dealradar-logo-group' style='--logo-color: {logo_color_var};'>"
        f"<div class='dealradar-logo-scope'>{scope_content}</div>"
        "<div class='dealradar-logo-text'>"
        "<div class='dealradar-logo-word-row'>"
        "<span class='dealradar-logo-word-deal'>DEAL</span>"
        "<span class='dealradar-logo-word-radar'>RADAR</span>"
        "</div>"
        f"<span class='dealradar-logo-caption'>{caption}</span>"
        "</div>"
        "</div>"
    )


def get_logo_html(category_value):
    """Whatever should actually render for this category - the admin's
    saved raw-HTML override if they've set one for it, else the coded
    default above."""
    brand = db.get_brand_settings()
    override = brand.get(f"logo_html_{category_value}", "")
    return override if override else build_default_logo_html(category_value)


def render_topbar_logo_html(category_value):
    st.markdown(get_logo_html(category_value), unsafe_allow_html=True)
