"""
nav.py
The one shared implementation behind every left-side navigation list in
the app (Settings, Portfolio's property picker and property-section list,
Manage Searches, Run Property Scans' result views, Admin Controls) -
flat rows, left-aligned icon+label, a light accent-tinted background (not
a solid block) for the active item. Before this existed, each page had
its own copy of the same CSS with small drifts (different padding, some
still centered instead of left-aligned) - restyling one restyled only
that one page. Every left-nav in the app should call render_side_nav()
rather than re-implementing the button loop + CSS locally.
"""

import streamlit as st


def render_side_nav(items, key_prefix, default=None, state_key=None):
    """Renders a compact vertical nav list and returns the active item's
    value.

    items: list of dicts, each with:
        - "label" (str, required) - the visible button text.
        - "value" (optional) - what's actually stored in session_state and
          returned. Defaults to "label" if omitted. Use this when labels
          aren't guaranteed unique or aren't a stable identity - e.g.
          Portfolio's property nav selects by property id, not by the
          (truncated, possibly-colliding) address text shown as the label.
        - "icon" (str, optional) - a ":material/x:" shortcode prefixed to
          the label.
        - "caption" (str, optional) - small text rendered below the
          button, inside the same row (e.g. Portfolio's $/mo cash flow).
        - "accent" (str, optional) - a CSS color for a left border on the
          item's outer container, independent of the active/selected
          state - e.g. Portfolio's cash-flow health color. Selection is
          always shown via the button's own background tint, so this
          accent color and the "is this selected" signal never compete
          for the same visual channel.
    key_prefix: unique per nav instance - scopes both the CSS selectors
        and the session_state/button keys, so multiple navs can exist on
        the same page (e.g. Portfolio's property list AND its per-property
        section list) without colliding.
    default: value to select on first render. Defaults to the first item's
        value.
    state_key: session_state key to read/write selection from, overriding
        the default "{key_prefix}_active". Use this when other code in the
        page already reads/writes a specific key directly (e.g. Portfolio's
        "portfolio_selected_id", set from the delete/add-property flows
        too, not just this nav) - pointing the nav at that same key avoids
        two separate stores of "which one is selected" going out of sync.
    """
    state_key = state_key or f"{key_prefix}_active"
    values = [item.get("value", item["label"]) for item in items]
    if state_key not in st.session_state or st.session_state[state_key] not in values:
        st.session_state[state_key] = default if default in values else values[0]

    st.markdown(f"""
        <style>
        div[class*="st-key-{key_prefix}_item_"] {{
            margin-bottom: 1px;
        }}
        div[class*="st-key-{key_prefix}_item_"] button {{
            text-align: left !important; justify-content: flex-start !important;
            background: transparent !important; border: none !important; box-shadow: none !important;
            border-radius: var(--radar-radius-sm) !important; border-left: 3px solid transparent !important;
            padding: 7px 10px 7px 9px !important; min-height: 0 !important; height: auto !important;
        }}
        /* Streamlit nests the label in button > div > span > div > p, and
        the div/span each default to justify-content:center - styling the
        button's own justify-content isn't enough on its own. */
        div[class*="st-key-{key_prefix}_item_"] button div,
        div[class*="st-key-{key_prefix}_item_"] button span {{
            justify-content: flex-start !important;
        }}
        div[class*="st-key-{key_prefix}_item_"] button p {{
            font-size: 13.5px !important; font-weight: 500 !important; text-align: left !important;
        }}
        div[class*="st-key-{key_prefix}_item_"] button[kind="secondary"] {{
            color: var(--radar-text-muted) !important;
        }}
        div[class*="st-key-{key_prefix}_item_"] button[kind="secondary"] p {{
            color: var(--radar-text-muted) !important;
        }}
        div[class*="st-key-{key_prefix}_item_"] button[kind="secondary"]:hover {{
            background: var(--radar-surface-alt) !important;
        }}
        div[class*="st-key-{key_prefix}_item_"] button[kind="secondary"]:hover p {{
            color: var(--radar-text) !important;
        }}
        div[class*="st-key-{key_prefix}_item_"] button[kind="primary"] {{
            background: rgba(37,99,235,0.08) !important;
            border-left: 3px solid var(--radar-primary) !important;
        }}
        div[class*="st-key-{key_prefix}_item_"] button[kind="primary"] p {{
            color: var(--radar-primary) !important; font-weight: 700 !important;
        }}
        div[class*="st-key-{key_prefix}_item_"] .stCaption {{
            padding-left: 9px !important; margin-top: -4px !important;
        }}
        </style>
    """, unsafe_allow_html=True)

    for i, item in enumerate(items):
        # Index-based keys, not label/value-based - relying on how
        # Streamlit slugifies an arbitrary string into a CSS class name is
        # fragile. label/value are only ever used for the button's visible
        # text and the session_state value, never for key construction.
        label = item["label"]
        value = item.get("value", label)
        icon = item.get("icon", "")
        caption = item.get("caption")
        accent = item.get("accent")
        is_active = st.session_state[state_key] == value
        with st.container(key=f"{key_prefix}_item_{i}"):
            if accent:
                st.markdown(f"""<style>div.st-key-{key_prefix}_item_{i} {{
                    border-left: 3px solid {accent}; }}</style>""", unsafe_allow_html=True)
            button_label = f"{icon} {label}".strip() if icon else label
            if st.button(button_label, key=f"{key_prefix}_btn_{i}", use_container_width=True,
                         type="primary" if is_active else "secondary"):
                st.session_state[state_key] = value
                st.rerun()
            if caption:
                st.caption(caption)

    return st.session_state[state_key]
