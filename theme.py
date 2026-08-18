"""
theme.py
Sitewide Light/Dark/Auto theme system for DealRadar.

Streamlit doesn't support runtime theme-switching natively (its theme config
lives in .streamlit/config.toml and only applies at startup), so this works by
injecting CSS that overrides Streamlit's internal element attributes
(data-testid selectors, which are the most stable way to target Streamlit's
generated markup across versions - though not perfectly guaranteed across
every future Streamlit release).

"Auto" mode is handled natively via the CSS prefers-color-scheme media query,
so it tracks the OS/browser's live dark-mode setting without any Python-side
detection - light rules apply by default, and dark rules are wrapped in an
@media block that only activates when the OS is set to dark.

Usage: call inject_theme(mode) once near the top of a page, where mode is
"light", "dark", or "auto".
"""

import streamlit as st

LIGHT = {
    "bg": "#f8fafc",
    "bg_secondary": "#ffffff",
    "panel": "#ffffff",
    "panel_border": "#e2e8f0",
    "text": "#1e293b",
    "text_dim": "#64748b",
    "sidebar_bg": "#ffffff",
    "input_bg": "#ffffff",
    "input_border": "#cbd5e1",
    "accent": "#2563eb",
    "accent_hover": "#1d4ed8",
}

DARK = {
    "bg": "#0f172a",
    "bg_secondary": "#16213a",
    "panel": "#16213a",
    "panel_border": "#2a3958",
    "text": "#f1f5f9",
    "text_dim": "#8fa0bd",
    "sidebar_bg": "#0f172a",
    "input_bg": "#1c2942",
    "input_border": "#2a3958",
    "accent": "#3b82f6",
    "accent_hover": "#2563eb",
}


def _build_css_rules(t):
    """Returns the raw CSS rule body (no <style> wrapper) for a given token set."""
    return f"""
        /* Main app background */
        [data-testid="stAppViewContainer"] {{
            background: {t['bg']};
        }}
        [data-testid="stMain"] {{
            background: {t['bg']};
        }}

        /* Sidebar */
        [data-testid="stSidebar"] {{
            background: {t['sidebar_bg']};
            border-right: 1px solid {t['panel_border']};
        }}
        [data-testid="stSidebar"] * {{
            color: {t['text']} !important;
        }}

        /* General text - broadened + !important to override Streamlit's own
        OS-driven dark/light auto-detection on native widget text, which can
        conflict with our custom toggle independently of it. */
        [data-testid="stAppViewContainer"] p,
        [data-testid="stAppViewContainer"] span,
        [data-testid="stAppViewContainer"] label,
        [data-testid="stAppViewContainer"] li,
        [data-testid="stAppViewContainer"] h1,
        [data-testid="stAppViewContainer"] h2,
        [data-testid="stAppViewContainer"] h3,
        [data-testid="stAppViewContainer"] h4,
        [data-testid="stAppViewContainer"] h5 {{
            color: {t['text']} !important;
        }}
        [data-testid="stCaptionContainer"] {{
            color: {t['text_dim']} !important;
        }}

        /* Widget labels (the text above sliders, inputs, selects, radios) */
        [data-testid="stWidgetLabel"] p,
        [data-testid="stWidgetLabel"] label,
        [data-testid="stWidgetLabel"] span {{
            color: {t['text']} !important;
        }}

        /* Markdown-rendered text blocks */
        [data-testid="stMarkdownContainer"] p,
        [data-testid="stMarkdownContainer"] li,
        [data-testid="stMarkdownContainer"] span,
        [data-testid="stMarkdownContainer"] strong,
        [data-testid="stMarkdownContainer"] em {{
            color: {t['text']} !important;
        }}

        /* Radio / checkbox option labels */
        [data-testid="stRadio"] label p,
        [data-testid="stCheckbox"] label p,
        [data-testid="stSelectbox"] label p {{
            color: {t['text']} !important;
        }}

        /* Selectbox/dropdown selected value and option list text */
        [data-baseweb="select"] * {{
            color: {t['text']} !important;
        }}
        [data-baseweb="popover"] {{
            background: {t['panel']} !important;
        }}
        [data-baseweb="menu"] li {{
            color: {t['text']} !important;
            background: {t['panel']} !important;
        }}

        /* Bordered containers (property cards, panels) */
        [data-testid="stVerticalBlockBorderWrapper"] {{
            background: {t['panel']};
            border-color: {t['panel_border']} !important;
        }}

        /* Buttons */
        .stButton button {{
            background: {t['panel']};
            color: {t['text']} !important;
            border: 1px solid {t['input_border']};
        }}
        .stButton button p {{
            color: {t['text']} !important;
        }}
        .stButton button:hover {{
            border-color: {t['accent']};
            color: {t['accent']} !important;
        }}
        .stButton button[kind="primary"] {{
            background: {t['accent']};
            color: white !important;
            border: none;
        }}
        .stButton button[kind="primary"] p {{
            color: white !important;
        }}
        .stButton button[kind="primary"]:hover {{
            background: {t['accent_hover']};
        }}

        /* Disabled buttons (e.g. "Save" before any field has actually
        changed) - overrides kind="primary"'s hardcoded accent color, which
        otherwise renders identically whether the button is clickable or
        not. This is the one visual cue that a Save button is "live". */
        .stButton button:disabled, .stButton button[kind="primary"]:disabled {{
            background: {t['panel']} !important;
            color: {t['text_dim']} !important;
            border: 1px solid {t['panel_border']};
            opacity: 0.6;
            cursor: not-allowed;
        }}
        .stButton button:disabled p, .stButton button[kind="primary"]:disabled p {{
            color: {t['text_dim']} !important;
        }}
        .stButton button:disabled:hover, .stButton button[kind="primary"]:disabled:hover {{
            border-color: {t['panel_border']} !important;
            color: {t['text_dim']} !important;
        }}

        /* Text / number inputs, selects, textareas */
        .stTextInput input, .stNumberInput input, .stTextArea textarea,
        [data-baseweb="select"] > div {{
            background: {t['input_bg']};
            color: {t['text']};
            border-color: {t['input_border']};
        }}

        /* Tabs */
        .stTabs [data-baseweb="tab-list"] {{
            border-bottom: 1px solid {t['panel_border']};
        }}
        .stTabs [data-baseweb="tab"] {{
            color: {t['text_dim']};
        }}
        .stTabs [aria-selected="true"] {{
            color: {t['accent']} !important;
        }}

        /* Metrics */
        [data-testid="stMetric"] {{
            background: {t['panel']};
            border: 1px solid {t['panel_border']};
            border-radius: 8px;
            padding: 10px 14px;
        }}
        [data-testid="stMetricValue"] {{
            color: {t['text']};
        }}
        [data-testid="stMetricLabel"] {{
            color: {t['text_dim']};
        }}

        /* Expanders */
        [data-testid="stExpander"] {{
            background: {t['panel']};
            border-color: {t['panel_border']} !important;
        }}

        /* Popovers */
        [data-testid="stPopoverBody"] {{
            background: {t['panel']};
            color: {t['text']};
            border-color: {t['panel_border']};
        }}

        /* Sliders */
        .stSlider [data-baseweb="slider"] > div > div {{
            background: {t['accent']};
        }}
    """


def get_theme_css(mode):
    """Returns the full <style> block for the given mode: 'light', 'dark', or 'auto'.

    - light: light rules only, always applied.
    - dark: dark rules only, always applied (forced dark regardless of OS).
    - auto: light rules as the default, with dark rules wrapped in an
      @media (prefers-color-scheme: dark) block, so the browser/OS setting
      decides live - no Python-side detection needed.
    """
    if mode == "dark":
        body = _build_css_rules(DARK)
    elif mode == "auto":
        light_rules = _build_css_rules(LIGHT)
        dark_rules = _build_css_rules(DARK)
        body = f"""
            {light_rules}
            @media (prefers-color-scheme: dark) {{
                {dark_rules}
            }}
        """
    else:
        body = _build_css_rules(LIGHT)

    return f"""
    <style>
        {body}
        /* NOTE: Streamlit's native st.dataframe / st.data_editor tables have
        their own internal styling engine that isn't fully covered by this
        override set - they may look slightly inconsistent in dark mode.
        Flag this if you spot it and we can patch further. */
    </style>
    """


def inject_theme(mode):
    st.markdown(get_theme_css(mode), unsafe_allow_html=True)


def theme_toggle_control(key="theme_mode_selector", on_change=None):
    """Renders a Light / Dark / Auto selector and returns the currently
    selected mode. Persists the choice in session_state, and calls
    on_change(new_mode) if provided (used to save the choice to the database
    so it survives future logins)."""
    if "theme_mode" not in st.session_state:
        st.session_state.theme_mode = "light"

    options = ["Light", "Dark", "Auto"]
    current_label = st.session_state.theme_mode.capitalize()
    if current_label not in options:
        current_label = "Light"

    selected_label = st.radio(
        "Appearance", options, horizontal=True, key=key,
        index=options.index(current_label),
    )
    new_mode = selected_label.lower()

    if new_mode != st.session_state.theme_mode:
        st.session_state.theme_mode = new_mode
        if on_change:
            on_change(new_mode)
        st.rerun()

    return st.session_state.theme_mode