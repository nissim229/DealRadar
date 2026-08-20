"""
guest_mode.py
Shared building blocks for the anonymous "browse the real app" experience -
st.session_state.is_guest is the single source of truth for whether this is
a guest session, and every page that needs to gate a write action or show a
"this is sample data" note does it through the two functions below, instead
of separate ad-hoc checks scattered across analytics.py, portfolio.py,
car_search.py, and settings.py.
"""

import streamlit as st


def guest_action_button(label, action_label, key=None, **kwargs):
    """Drop-in replacement for st.button on any action that writes data
    (save, delete, add, run a real scan). Behaves exactly like st.button
    for a real session. For a guest session, clicking it prompts sign-in
    instead of returning True, so the caller's write code never runs."""
    clicked = st.button(label, key=key, **kwargs)
    if not clicked:
        return False
    if st.session_state.get("is_guest"):
        st.toast(f"Sign in to {action_label}.", icon=":material/lock:")
        st.session_state.show_login_form = True
        st.rerun()
        return False
    return True


def render_guest_banner(what_it_shows):
    """The small, consistent 'sample data' note shown once near the top of
    each page's guest branch - one wording/style for all five pages."""
    st.info(f":material/visibility: You're viewing sample data - {what_it_shows}. Sign in to use your own.",
            icon=":material/info:")
