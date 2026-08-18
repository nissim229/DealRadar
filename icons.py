"""
icons.py
A small set of hand-drawn line icons matching the app's existing radar-logo
style (round caps/joins, 2.5 stroke-width, no fill except small solid dots)
- for the custom HTML areas (stat cards, hero callouts, badges) where
Streamlit's native :material/icon_name: shortcode isn't usable, since that
only works inside real widget labels (st.button, st.tabs, st.expander),
not inside raw HTML strings passed to st.markdown(unsafe_allow_html=True).

Each icon is just an inner-SVG fragment (viewBox 0 0 24 24) so it can be
sized and colored per call site via the wrapping icon() helper, and drops
in wherever an emoji used to sit.
"""

_PATHS = {
    "trophy": """
        <path d="M7 4h10v4a5 5 0 0 1-10 0V4Z" />
        <path d="M7 5H4a3 3 0 0 0 3 3" />
        <path d="M17 5h3a3 3 0 0 1-3 3" />
        <path d="M12 13v3" />
        <path d="M9 20h6" />
        <path d="M10 16.5h4a1 1 0 0 1 1 1V20h-6v-2.5a1 1 0 0 1 1-1Z" />
    """,
    "check-circle": """
        <circle cx="12" cy="12" r="9" />
        <path d="m8 12.5 2.5 2.5L16 9.5" />
    """,
    "dollar": """
        <circle cx="12" cy="12" r="9" />
        <path d="M12 6.5v11" />
        <path d="M15 9a3 3 0 0 0-3-1.5c-1.7 0-3 1-3 2.3 0 3 6 1.5 6 4.4 0 1.4-1.3 2.3-3 2.3a3.3 3.3 0 0 1-3-1.6" />
    """,
    "camera": """
        <path d="M4 8.5A1.5 1.5 0 0 1 5.5 7h2l1-2h7l1 2h2A1.5 1.5 0 0 1 20 8.5v9A1.5 1.5 0 0 1 18.5 19h-13A1.5 1.5 0 0 1 4 17.5v-9Z" />
        <circle cx="12" cy="13" r="3.3" />
    """,
    "search": """
        <circle cx="11" cy="11" r="6.5" />
        <path d="m20 20-4.3-4.3" />
    """,
    "star-outline": """
        <path d="M12 4.5 14.5 9.7 20.3 10.5 16.1 14.5 17.1 20.3 12 17.5 6.9 20.3 7.9 14.5 3.7 10.5 9.5 9.7 12 4.5Z" />
    """,
    "star-filled": """
        <path d="M12 4.5 14.5 9.7 20.3 10.5 16.1 14.5 17.1 20.3 12 17.5 6.9 20.3 7.9 14.5 3.7 10.5 9.5 9.7 12 4.5Z" fill="currentColor" stroke="none" />
    """,
    "home": """
        <path d="M4 11.5 12 4l8 7.5" />
        <path d="M6 10v9.5h12V10" />
        <path d="M10 19.5v-6h4v6" />
    """,
    "map-pin": """
        <path d="M12 21s7-6.4 7-11.5a7 7 0 1 0-14 0C5 14.6 12 21 12 21Z" />
        <circle cx="12" cy="9.5" r="2.4" />
    """,
    "chart": """
        <path d="M4 20V9" />
        <path d="M10 20V4" />
        <path d="M16 20v-7" />
        <path d="M4 20h16" />
    """,
    "download": """
        <path d="M12 4v11.5" />
        <path d="m7.5 11 4.5 4.5 4.5-4.5" />
        <path d="M5 19.5h14" />
    """,
    "alert": """
        <path d="M12 4 21 19.5H3L12 4Z" />
        <path d="M12 10v4" />
        <circle cx="12" cy="16.8" r="0.9" fill="currentColor" stroke="none" />
    """,
    "lightbulb": """
        <path d="M9 18.5h6" />
        <path d="M10 21.5h4" />
        <path d="M12 3.5a6 6 0 0 0-3.5 10.9c.6.45 1 1.15 1 1.9v.7h5v-.7c0-.75.4-1.45 1-1.9A6 6 0 0 0 12 3.5Z" />
    """,
    "expand": """
        <path d="M9 4H4v5" />
        <path d="M15 20h5v-5" />
        <path d="M20 4h-5" />
        <path d="M4 15v5" />
        <path d="m4 20 6-6" />
        <path d="m20 4-6 6" />
    """,
    "shield-check": """
        <path d="M12 3 20 6v5c0 5-3.5 8.5-8 10-4.5-1.5-8-5-8-10V6l8-3Z" />
        <path d="m9 12 2 2 4.5-4.5" />
    """,
    "crosshair": """
        <circle cx="12" cy="12" r="9" />
        <circle cx="12" cy="12" r="5" />
        <circle cx="12" cy="12" r="1" fill="currentColor" stroke="none" />
    """,
    "users": """
        <circle cx="9" cy="9" r="3.2" />
        <path d="M3.5 19c.6-3 2.7-4.7 5.5-4.7s4.9 1.7 5.5 4.7" />
        <path d="M16 8.3a3 3 0 0 1 0 5.9" />
        <path d="M16.2 14.3c2.5.3 4.3 2 4.8 4.7" />
    """,
    "clock": """
        <circle cx="12" cy="12" r="9" />
        <path d="M12 7v5.5l4 2.3" />
    """,
    "trash": """
        <path d="M5 7h14" />
        <path d="M9 7V4.5h6V7" />
        <path d="M6.5 7 7.3 19.5a1.5 1.5 0 0 0 1.5 1.4h6.4a1.5 1.5 0 0 0 1.5-1.4L17.5 7" />
        <path d="M10 11v6" />
        <path d="M14 11v6" />
    """,
    "key": """
        <circle cx="8" cy="15" r="4" />
        <path d="m11 12 8.5-8.5" />
        <path d="M16.5 6.5 19 4" />
        <path d="m14 9 2.5 2.5" />
    """,
    "radar": """
        <circle cx="12" cy="12" r="9" />
        <circle cx="12" cy="12" r="5" />
        <path d="M12 12 L18 6" />
        <circle cx="17" cy="7" r="1.4" fill="currentColor" stroke="none" />
    """,
    "settings": """
        <circle cx="12" cy="12" r="3" />
        <path d="M12 3.5v2.3" /><path d="M12 18.2v2.3" />
        <path d="m6.1 6.1 1.6 1.6" /><path d="m16.3 16.3 1.6 1.6" />
        <path d="M3.5 12h2.3" /><path d="M18.2 12h2.3" />
        <path d="m6.1 17.9 1.6-1.6" /><path d="m16.3 7.7 1.6-1.6" />
    """,
}


def icon(name, size=18, color="currentColor", stroke_width=2.5):
    """Returns an inline <svg> string for the given icon name. Drop this
    directly into an f-string alongside other HTML - it's just markup,
    sized/colored per call site (no external file, no network fetch)."""
    body = _PATHS.get(name, "")
    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
        f'stroke="{color}" stroke-width="{stroke_width}" stroke-linecap="round" '
        f'stroke-linejoin="round" style="display:inline-block; vertical-align:middle; flex-shrink:0;">'
        f'{body}</svg>'
    )
