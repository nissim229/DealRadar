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

TOKENS_CSS = """
:root {
    /* Typography - Sora for headings/hero titles (geometric, a little more
    character than the body face, used sparingly so it stays a display
    face rather than blending into body copy), Work Sans for everything
    else (labels, buttons, tables, captions - built for long runs of UI
    text at small sizes), JetBrains Mono wherever digits/identifiers need
    to line up (table cell alignment, file paths, addresses). Previously
    unset - every page rendered on the browser's bare default font, which
    is why DealRadar never actually had a typographic identity until now. */
    --radar-font-display: 'Sora', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    --radar-font-body: 'Work Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    --radar-font-mono: 'JetBrains Mono', ui-monospace, 'SF Mono', Consolas, monospace;

    /* Brand */
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
}
"""


# Google Fonts is the one external font host Streamlit's own CSP-free
# markdown rendering can reach reliably (no build step to bundle a local
# @font-face file into) - loaded once, here, so every page (including the
# pre-login guest/auth screens, which render before theme.py ever runs)
# gets the real typeface instead of falling back to it only after login.
FONT_IMPORT_HTML = """
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Sora:wght@600;700;800&family=Work+Sans:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
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
    category dropdown chevron. */
    [data-testid="stIconMaterial"] {
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


def inject_design_tokens():
    st.markdown(FONT_IMPORT_HTML, unsafe_allow_html=True)
    st.markdown(f"<style>{TOKENS_CSS}{FONT_CSS}</style>", unsafe_allow_html=True)
