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


def inject_design_tokens():
    st.markdown(f"<style>{TOKENS_CSS}</style>", unsafe_allow_html=True)
