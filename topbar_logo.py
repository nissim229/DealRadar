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


# --- Guest landing logo (a third, separate variant - not the circular
# real_estate/cars style above, but the earlier rounded-square badge with
# a spinning dashed ring + glow ping dot + small mono tag, per the user's
# own HTML spec built specifically for the anonymous/guest experience).
# Its CSS is self-contained (injected here, not scoped under any
# particular `.st-key-*` container) because - unlike real_estate/cars,
# whose CSS lives in main.py and is already on every authenticated page
# including Admin Controls - guest_landing.py's own topbar never renders
# on an authenticated page, so the admin's live preview in Brand & Design
# would have no matching stylesheet to inherit from if this were scoped
# the same way. Injecting the CSS wherever the markup is used (both the
# real guest page and the admin preview) makes it portable instead.
_GUEST_ICON_PATH = (
    '<path d="M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0A17.933 17.933 0 0112 '
    '21.75c-2.676 0-5.216-.584-7.499-1.632z" />'
)

_GUEST_LOGO_CSS = """
<style>
@keyframes dealradar-guestlogo-spin {
    to { transform: rotate(360deg); }
}
.dealradar-guestlogo-group {
    display: flex; align-items: center; gap: 14px; cursor: pointer;
}
.dealradar-guestlogo-scope {
    position: relative; width: 36px; height: 36px; flex: none;
    display: flex; align-items: center; justify-content: center;
    border-radius: 8px;
    background: rgba(15, 23, 42, 0.6);
    border: 1px solid var(--radar-navy-light);
    transition: border-color 0.5s ease, box-shadow 0.5s ease;
}
.dealradar-guestlogo-group:hover .dealradar-guestlogo-scope {
    border-color: rgba(var(--radar-accent-rgb), 0.4);
    box-shadow: 0 0 20px rgba(var(--radar-accent-rgb), 0.15);
}
.dealradar-guestlogo-ring {
    position: absolute; inset: 4px;
    border: 1px dashed rgba(var(--radar-accent-rgb), 0.2);
    border-radius: 50%;
    animation: dealradar-guestlogo-spin 20s linear infinite;
}
.dealradar-guestlogo-icon {
    position: relative; z-index: 1;
    width: 14px; height: 14px; color: var(--radar-accent) !important;
    transition: transform 0.5s ease;
}
.dealradar-guestlogo-group:hover .dealradar-guestlogo-icon {
    transform: scale(1.1);
}
.dealradar-guestlogo-ping {
    position: absolute; top: 6px; right: 6px;
    width: 4px; height: 4px; border-radius: 50%;
    background: var(--radar-accent);
    box-shadow: 0 0 6px var(--radar-accent);
}
.dealradar-guestlogo-word-deal {
    font-family: var(--radar-font-display) !important;
    font-size: 16px; font-weight: 900; color: var(--radar-text-on-dark) !important;
    text-transform: uppercase; letter-spacing: normal;
    transition: color 0.3s ease;
}
.dealradar-guestlogo-group:hover .dealradar-guestlogo-word-deal {
    color: white !important;
}
.dealradar-guestlogo-word-radar {
    font-family: var(--radar-font-display) !important;
    font-size: 16px; font-weight: 300; color: var(--radar-accent) !important;
    text-transform: uppercase; letter-spacing: 0.025em;
}
.dealradar-guestlogo-tag {
    font-family: var(--radar-font-mono) !important;
    font-size: 7px; font-weight: 700; letter-spacing: 0.15em;
    color: #94a3b8 !important; text-transform: uppercase;
    margin-left: 8px; background: var(--radar-navy);
    padding: 2px 6px; border-radius: 4px;
    border: 1px solid var(--radar-navy-light);
}
.dealradar-guestlogo-text {
    display: flex; flex-direction: column; line-height: 1.2;
}
.dealradar-guestlogo-word-row {
    display: flex; align-items: center; gap: 6px;
}
.dealradar-guestlogo-caption {
    font-family: var(--radar-font-mono) !important;
    font-size: 8px; font-weight: 600; letter-spacing: 0.1em;
    color: #64748b !important; text-transform: uppercase;
    margin-top: 1px;
}
</style>
"""


def build_default_guest_logo_html():
    custom_logo = db.get_brand_settings()["logo_data_uri"]
    if custom_logo:
        scope_content = f"<img src='{custom_logo}' style='width: 100%; height: 100%; object-fit: cover; border-radius: 8px;' />"
    else:
        scope_content = (
            "<span class='dealradar-guestlogo-ring'></span>"
            '<svg class="dealradar-guestlogo-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" '
            'stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">'
            f"{_GUEST_ICON_PATH}</svg>"
            "<span class='dealradar-guestlogo-ping'></span>"
        )
    return (
        "<div class='dealradar-guestlogo-group'>"
        f"<div class='dealradar-guestlogo-scope'>{scope_content}</div>"
        "<div class='dealradar-guestlogo-text'>"
        "<div class='dealradar-guestlogo-word-row'>"
        "<span class='dealradar-guestlogo-word-deal'>DEAL</span>"
        "<span class='dealradar-guestlogo-word-radar'>RADAR</span>"
        "<span class='dealradar-guestlogo-tag'>GUEST</span>"
        "</div>"
        "<span class='dealradar-guestlogo-caption'>ANONYMOUS TRACKING NODE ACTIVE</span>"
        "</div>"
        "</div>"
    )


def get_guest_logo_html():
    brand = db.get_brand_settings()
    override = brand.get("logo_html_guest", "")
    return override if override else build_default_guest_logo_html()


def inject_guest_logo_css():
    """Public so callers outside this module (the admin preview) can pull
    in the guest-logo CSS without reaching into a private module
    attribute - render_guest_logo_html itself just uses this internally."""
    st.markdown(_GUEST_LOGO_CSS, unsafe_allow_html=True)


def render_guest_logo_html():
    inject_guest_logo_css()
    st.markdown(get_guest_logo_html(), unsafe_allow_html=True)
