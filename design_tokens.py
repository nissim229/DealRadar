"""
design_tokens.py
Sitewide design tokens (color, spacing, radius, shadow, type scale) for the
custom HTML blocks scattered across this app - heroes, stat cards, badges,
callouts. These are a different concern from theme.py's LIGHT/DARK dicts:
theme.py re-skins Streamlit's own native widgets for light/dark mode, while
this file is the shared vocabulary for the bespoke HTML/CSS this app builds
by hand (via st.markdown(unsafe_allow_html=True)) on top of those widgets.

Previously each file hardcoded its own hex/px values (e.g. "#2563eb",
"20px", "0 12px 32px rgba(15,23,42,0.18)") independently, so nothing
guaranteed a hero in one file used the same radius or shadow as a card in
another. Injecting one :root token set means every custom block can
reference var(--radar-primary) etc. and the whole app reads as one
deliberate system - and a future rebrand/retune is a one-line edit here
instead of a file-by-file hunt.

Usage: call inject_design_tokens() once, as early as possible in main.py -
before the guest/auth/authenticated router split, so every page (including
pages that render before login) can use these variables.
"""

import streamlit as st
import database as db

# Curated Google Fonts options for Admin Controls > Brand & Design's 3
# typeface pickers - a fixed list (not free text) so a saved choice can
# never reference a family that isn't actually loaded or typo into
# nothing rendering. Each entry maps the friendly dropdown label to
# (Google Fonts family name, weight string for the CSS2 API, CSS
# fallback stack) - the weight string controls exactly which cuts get
# downloaded, same reasoning as the original hardcoded
# "Work+Sans:wght@400;500;600;900" import this replaces.
DISPLAY_FONT_OPTIONS = {
    "Sora": ("Sora", "600;700;800", "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"),
    "Space Grotesk": ("Space Grotesk", "600;700", "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"),
    "Orbitron": ("Orbitron", "600;700;800", "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"),
    "Rajdhani": ("Rajdhani", "600;700", "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"),
    "Poppins": ("Poppins", "600;700;800", "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"),
}
BODY_FONT_OPTIONS = {
    "Work Sans": ("Work Sans", "400;500;600;900", "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"),
    "Inter": ("Inter", "400;500;600;900", "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"),
    "Rajdhani": ("Rajdhani", "400;500;600;700", "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"),
    "Roboto": ("Roboto", "400;500;700;900", "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"),
}
MONO_FONT_OPTIONS = {
    "JetBrains Mono": ("JetBrains Mono", "400;500;700", "ui-monospace, 'SF Mono', Consolas, monospace"),
    "Roboto Mono": ("Roboto Mono", "400;500;700", "ui-monospace, 'SF Mono', Consolas, monospace"),
    "Space Mono": ("Space Mono", "400;700", "ui-monospace, 'SF Mono', Consolas, monospace"),
    "IBM Plex Mono": ("IBM Plex Mono", "400;500;600", "ui-monospace, 'SF Mono', Consolas, monospace"),
}


def _shade_hex(hex_color, factor):
    """Scales a #rrggbb color toward black (factor<1) or white (factor>1)
    - used to derive a "-dark" hover/gradient variant from the admin's
    one chosen accent color instead of asking them to pick two colors
    that have to stay visually related."""
    hex_color = hex_color.lstrip("#")
    if len(hex_color) != 6:
        return "#0f172a"
    try:
        r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return "#0f172a"
    if factor <= 1:
        r, g, b = (int(c * factor) for c in (r, g, b))
    else:
        r, g, b = (int(c + (255 - c) * (factor - 1)) for c in (r, g, b))
    r, g, b = (max(0, min(255, c)) for c in (r, g, b))
    return f"#{r:02x}{g:02x}{b:02x}"


def _hex_to_rgb_str(hex_color):
    """'#22d3ee' -> '34, 211, 238' - the comma-separated component form
    needed to drive rgba(var(--radar-accent-rgb), 0.3)-style translucent
    fills from the admin's single hex picker, since CSS can't extract
    components out of a var() holding a full #rrggbb string."""
    hex_color = hex_color.lstrip("#")
    if len(hex_color) != 6:
        return "34, 211, 238"
    try:
        r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return "34, 211, 238"
    return f"{r}, {g}, {b}"


def _build_tokens_css():
    """Builds :root's CSS custom properties from the admin's saved brand
    settings (falling back to the original defaults if nothing's been
    saved) - called fresh on every render, same "read the live DB state,
    not a cached value" approach as get_design_standards(), so a save in
    Admin Controls shows up on the very next rerun with no restart."""
    brand = db.get_brand_settings()
    display_family, _, display_fallback = DISPLAY_FONT_OPTIONS.get(brand["font_display"], DISPLAY_FONT_OPTIONS["Sora"])
    body_family, _, body_fallback = BODY_FONT_OPTIONS.get(brand["font_body"], BODY_FONT_OPTIONS["Work Sans"])
    mono_family, _, mono_fallback = MONO_FONT_OPTIONS.get(brand["font_mono"], MONO_FONT_OPTIONS["JetBrains Mono"])
    accent = brand["accent_color"]
    accent_dark = _shade_hex(accent, 0.75)
    accent_rgb = _hex_to_rgb_str(accent)

    return f"""
:root {{
    /* Typography - the 3 roles (display/body/mono) are all admin-
    controlled from Admin Controls > Brand & Design; these are just
    today's saved choice (or the original Sora/Work Sans/JetBrains Mono
    defaults if nothing's been saved yet). */
    --radar-font-display: '{display_family}', {display_fallback};
    --radar-font-body: '{body_family}', {body_fallback};
    --radar-font-mono: '{mono_family}', {mono_fallback};

    /* Brand - --radar-accent is the one color Admin Controls exposes
    (the cyan cyberpunk topbar/button/loading-radar work all reference
    this, not a hardcoded hex, specifically so this control actually
    re-skins them); --radar-primary is the original standing blue used
    everywhere else in the app (ordinary buttons, links, badges) and is
    deliberately NOT tied to the accent picker - the two are allowed to
    diverge (e.g. a cyan accent standing out against the app's normal
    blue chrome) rather than forcing one global recolor. */
    --radar-accent: {accent};
    --radar-accent-dark: {accent_dark};
    --radar-accent-rgb: {accent_rgb};
    --radar-primary: #2563eb;
    --radar-primary-dark: #1d4ed8;
    --radar-navy: #0f172a;
    --radar-navy-light: #1e293b;

    /* Grade / status colors */
    --radar-success: #10b981;
    --radar-success-bg: #d1fae5;
    --radar-success-border: #6ee7b7;
    --radar-warning: #f59e0b;
    --radar-warning-bg: #fef3c7;
    --radar-danger: #ef4444;
    --radar-danger-bg: #fee2e2;

    /* Text */
    --radar-text: #1e293b;
    --radar-text-muted: #64748b;
    --radar-text-subtle: #94a3b8;
    --radar-text-on-dark: #f1f5f9;
    --radar-text-on-dark-muted: #94a3b8;

    /* Surfaces */
    --radar-surface: #ffffff;
    --radar-surface-alt: #f8fafc;
    --radar-border: #e2e8f0;

    /* Neutral (secondary buttons / archived-state actions, as opposed to
    the primary brand blue) */
    --radar-neutral: #4b5563;
    --radar-neutral-dark: #374151;

    /* Spacing scale */
    --radar-space-1: 4px;
    --radar-space-2: 8px;
    --radar-space-3: 12px;
    --radar-space-4: 16px;
    --radar-space-5: 24px;
    --radar-space-6: 32px;
    --radar-space-7: 40px;
    --radar-space-8: 56px;

    /* Radius scale */
    --radar-radius-sm: 6px;
    --radar-radius-md: 10px;
    --radar-radius-lg: 14px;
    --radar-radius-xl: 20px;
    --radar-radius-pill: 999px;

    /* Shadow scale */
    --radar-shadow-sm: 0 1px 3px rgba(15,23,42,0.08);
    --radar-shadow-md: 0 8px 24px rgba(15,23,42,0.12);
    --radar-shadow-lg: 0 12px 32px rgba(15,23,42,0.18);
    --radar-shadow-hero: 0 20px 50px rgba(15,23,42,0.25);

    /* Type scale */
    --radar-text-xs: 11px;
    --radar-text-sm: 12.5px;
    --radar-text-base: 14px;
    --radar-text-md: 15px;
    --radar-text-lg: 16px;
    --radar-text-xl: 20px;
    --radar-text-2xl: 24px;
    --radar-text-3xl: 32px;

    /* Weight */
    --radar-weight-medium: 500;
    --radar-weight-semibold: 600;
    --radar-weight-bold: 700;
    --radar-weight-black: 800;

    /* Gradients (used by every dark hero banner) */
    --radar-gradient-hero: linear-gradient(135deg, var(--radar-navy) 0%, var(--radar-navy-light) 100%);
    --radar-gradient-brand: linear-gradient(135deg, var(--radar-primary), var(--radar-primary-dark));
    --radar-gradient-accent: linear-gradient(135deg, var(--radar-accent), var(--radar-accent-dark));
}}
"""


def _build_font_import_html():
    """Google Fonts is the one external font host Streamlit's own CSP-
    free markdown rendering can reach reliably (no build step to bundle
    a local @font-face file into) - loaded once, here, so every page
    (including the pre-login guest/auth screens, which render before
    theme.py ever runs) gets the real typeface instead of falling back
    to it only after login. Built from the admin's saved font choices
    (or the original defaults) - three separate &family= params in one
    request, same as the original hardcoded URL this replaces."""
    brand = db.get_brand_settings()
    _, display_weights, _ = DISPLAY_FONT_OPTIONS.get(brand["font_display"], DISPLAY_FONT_OPTIONS["Sora"])
    _, body_weights, _ = BODY_FONT_OPTIONS.get(brand["font_body"], BODY_FONT_OPTIONS["Work Sans"])
    _, mono_weights, _ = MONO_FONT_OPTIONS.get(brand["font_mono"], MONO_FONT_OPTIONS["JetBrains Mono"])
    display_family = DISPLAY_FONT_OPTIONS.get(brand["font_display"], DISPLAY_FONT_OPTIONS["Sora"])[0].replace(" ", "+")
    body_family = BODY_FONT_OPTIONS.get(brand["font_body"], BODY_FONT_OPTIONS["Work Sans"])[0].replace(" ", "+")
    mono_family = MONO_FONT_OPTIONS.get(brand["font_mono"], MONO_FONT_OPTIONS["JetBrains Mono"])[0].replace(" ", "+")

    return f"""
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family={display_family}:wght@{display_weights}&family={body_family}:wght@{body_weights}&family={mono_family}:wght@{mono_weights}&display=swap" rel="stylesheet">
"""

# Applied broadly via data-testid/class selectors (same technique theme.py
# already uses for color) rather than a bare `body { font-family }` -
# Streamlit's own component library sets its own font-family on several
# internal elements with enough specificity that a single top-level rule
# doesn't reliably cascade into e.g. dataframe cells or widget labels.
FONT_CSS = """
    html, body, .stApp, [class*="st-"], [data-testid] {
        font-family: var(--radar-font-body);
    }
    /* Material icon glyphs (Streamlit's own auto-added ones, like a
    popover's dropdown chevron - not the icon spans from a `:material/x:`
    shortcode in a label, which already carry their own inline
    font-family and are unaffected) rely on the icon font rendering as a
    ligature. The broad rule above was overriding it to the body
    typeface, which turned the icon into literal readable text like
    "expand_more" instead of a glyph - reproduced live on the topbar's
    category dropdown chevron. stAlertDynamicIcon is the same problem on
    a different testid - the icon= argument on st.info/warning/error/
    success renders through this one instead of stIconMaterial, and was
    still showing literal text ("info", "lightbulb", "visibility")
    overlapping the message body until this was added too - reproduced
    live on the guest-mode banners and the pre-existing Simple-mode
    notice on the scan results page. */
    [data-testid="stIconMaterial"],
    [data-testid="stAlertDynamicIcon"] {
        font-family: "Material Symbols Rounded" !important;
    }
    h1, h2, h3, h4, h5, h6,
    [data-testid="stMarkdownContainer"] h1,
    [data-testid="stMarkdownContainer"] h2,
    [data-testid="stMarkdownContainer"] h3,
    [data-testid="stMarkdownContainer"] h4,
    [data-testid="stMarkdownContainer"] h5 {
        font-family: var(--radar-font-display);
    }
    code, pre, kbd, [data-testid="stCode"] {
        font-family: var(--radar-font-mono);
    }
"""

# A hard-coded st.columns(N) stat-card/metric row (3, 4, or 5 columns,
# depending on the page) has no minimum width per column by default, so
# at in-between browser widths each column gets squeezed well past its
# content's natural size and the value/label text clips instead of the
# row wrapping onto a second line - confirmed live on Portfolio's summary
# cards and its per-property Purchase Price/Current Value/Equity/Monthly
# grid. Rather than hand-fixing each page's card row, this targets the
# two shapes those cards actually come in app-wide - our own
# render_stat_card (analytics.py, tagged with this class specifically so
# it can be targeted) and Streamlit's native st.metric widget - and gives
# each a sensible min-width, letting the browser's own default flex-wrap
# reflow a too-narrow row onto multiple lines instead of crushing text.
# Deliberately NOT a blanket rule on every st.columns() row app-wide -
# plenty of other column layouts (icon-button rows, form fields) are
# intentionally narrow and would look wrong forced to this width.
RESPONSIVE_CSS = """
    div[data-testid="stColumn"]:has(.dealradar-stat-card),
    div[data-testid="stColumn"]:has([data-testid="stMetric"]) {
        min-width: 150px !important;
    }
"""


def inject_design_tokens():
    st.markdown(_build_font_import_html(), unsafe_allow_html=True)
    st.markdown(f"<style>{_build_tokens_css()}{FONT_CSS}{RESPONSIVE_CSS}</style>", unsafe_allow_html=True)
