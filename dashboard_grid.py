"""
dashboard_grid.py
Shared, persisted, GUI-customizable grid layout for dashboard cards - used
by both the admin dashboard (components/admin_controls.py) and the
customer-facing analytics dashboard (components/analytics.py), so both get
the same layout behavior from one implementation instead of two drifting
copies.

Streamlit has no native drag-and-drop positioning, so this doesn't attempt
one. Instead each card gets an explicit (row, col, span) position - row and
col are plain integers the user sets from the customize controls, not
derived from card order - so two same-width cards can be placed on separate
rows even though a naive left-to-right packing would have sat them side by
side. Cards can also be hidden entirely (visible=False) without losing
their saved position, so re-showing one later restores where it was.
"""
import streamlit as st
import database as db


def render_dashboard_grid(dashboard_type, cards, default_grid_columns=4):
    """cards: list of {"id": str, "title": str, "render": callable(),
    "default_row": int, "default_col": int, "default_span": int}.

    Layout (grid width + each card's row/col/span/visible) is saved per
    user per dashboard_type via database.py's dashboard_layouts table. A
    "Customize Layout" toggle reveals inline Row/Col/Span/Show controls on
    every known card (including currently-hidden ones, so they can be
    re-shown) rather than a separate settings screen - every change is
    written immediately, nothing to explicitly "save".
    """
    user_id = st.session_state.user_id
    card_by_id = {c["id"]: c for c in cards}
    saved = db.get_dashboard_layout(user_id, dashboard_type)
    if saved and saved.get("cards"):
        layout = saved
        saved_ids = {c["id"] for c in layout["cards"]}
        for c in cards:
            if c["id"] not in saved_ids:
                layout["cards"].append({
                    "id": c["id"], "row": c["default_row"], "col": c["default_col"],
                    "span": c["default_span"], "visible": True,
                })
    else:
        layout = {
            "grid_columns": default_grid_columns,
            "cards": [
                {"id": c["id"], "row": c["default_row"], "col": c["default_col"],
                 "span": c["default_span"], "visible": True}
                for c in cards
            ],
        }
    # Backfill for layouts saved under the older span-only schema (before
    # row/col/visible existed) - fall back to that card's current code
    # default rather than raising a KeyError on a stale saved shape.
    for c in layout["cards"]:
        c.setdefault("visible", True)
        default_card = card_by_id.get(c["id"], {})
        c.setdefault("row", default_card.get("default_row", 1))
        c.setdefault("col", default_card.get("default_col", 1))

    customize_key = f"dashboard_customize_{dashboard_type}"
    customizing = st.session_state.get(customize_key, False)

    toggle_col1, toggle_col2 = st.columns([3, 1])
    with toggle_col2:
        if st.button(":material/tune: Customize Layout" if not customizing else ":material/check: Done Customizing",
                     key=f"{customize_key}_btn", use_container_width=True):
            st.session_state[customize_key] = not customizing
            st.rerun()

    grid_columns = layout["grid_columns"]
    if customizing:
        with toggle_col1:
            grid_options = [2, 3, 4]
            current_idx = grid_options.index(grid_columns) if grid_columns in grid_options else 2
            new_grid_columns = st.selectbox("Grid width", grid_options, index=current_idx,
                                             key=f"{customize_key}_columns", format_func=lambda n: f"{n}-column grid",
                                             label_visibility="collapsed")
            if new_grid_columns != grid_columns:
                layout["grid_columns"] = new_grid_columns
                db.save_dashboard_layout(user_id, dashboard_type, layout)
                st.rerun()
            grid_columns = new_grid_columns

        st.markdown("<div style='height:4px;'></div>", unsafe_allow_html=True)
        with st.container(key=f"{customize_key}_controls"):
            st.markdown(f"""<style>div.st-key-{customize_key}_controls {{ background: var(--radar-surface-alt, #f1f5f9);
                border: 1px solid var(--radar-border); border-radius: var(--radar-radius-md);
                padding: var(--radar-space-3) var(--radar-space-4); margin-bottom: var(--radar-space-3); }}</style>""",
                        unsafe_allow_html=True)

            # One shared multiselect for visibility rather than a checkbox
            # per card - this project has twice confirmed that a row of
            # many independently-clickable st.checkbox widgets is
            # unreliable here (both for automated clicks and, per real
            # user feedback logged elsewhere in this app, for people too);
            # a single multi-select widget doesn't have that failure mode.
            id_to_title = {c["id"]: c["title"] for c in cards}
            title_to_id = {c["title"]: c["id"] for c in cards}
            currently_visible_titles = [id_to_title[e["id"]] for e in layout["cards"]
                                         if e["visible"] and e["id"] in id_to_title]
            chosen_titles = st.multiselect("Cards shown on this dashboard", options=[c["title"] for c in cards],
                                            default=currently_visible_titles, key=f"{customize_key}_visible_titles")
            chosen_ids = {title_to_id[t] for t in chosen_titles}
            visibility_changed = False
            for entry in layout["cards"]:
                new_visible = entry["id"] in chosen_ids
                if entry["visible"] != new_visible:
                    entry["visible"] = new_visible
                    visibility_changed = True
            if visibility_changed:
                db.save_dashboard_layout(user_id, dashboard_type, layout)
                st.rerun()

            st.markdown("<div style='height:4px;'></div>", unsafe_allow_html=True)

            for c in cards:
                cid = c["id"]
                if cid not in chosen_ids:
                    continue
                entry = next(cc for cc in layout["cards"] if cc["id"] == cid)
                row_c1, row_c2, row_c3, row_c4 = st.columns([2.2, 1, 1, 1])
                with row_c1:
                    st.caption(f"**{c['title']}**")
                with row_c2:
                    new_row = st.number_input("Row", min_value=1, max_value=20, value=entry["row"],
                                               key=f"{customize_key}_row_{cid}")
                with row_c3:
                    new_col = st.number_input("Col", min_value=1, max_value=grid_columns, value=min(entry["col"], grid_columns),
                                               key=f"{customize_key}_col_{cid}")
                with row_c4:
                    span_options = list(range(1, grid_columns + 1))
                    current_span = min(entry["span"], grid_columns)
                    new_span = st.selectbox("Span", span_options, index=span_options.index(current_span),
                                             key=f"{customize_key}_span_{cid}")
                if (new_row, new_col, new_span) != (entry["row"], entry["col"], entry["span"]):
                    entry["row"], entry["col"], entry["span"] = new_row, new_col, new_span
                    db.save_dashboard_layout(user_id, dashboard_type, layout)
                    st.rerun()

    st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)

    visible_cards = [c for c in layout["cards"] if c["visible"] and c["id"] in card_by_id]
    if not visible_cards:
        st.caption("No cards are visible - turn on Customize Layout to show one.")
        return

    rows = sorted({c["row"] for c in visible_cards})
    for row_num in rows:
        row_cards = sorted([c for c in visible_cards if c["row"] == row_num], key=lambda c: c["col"])
        widths, placements = [], []
        current_col = 1
        for entry in row_cards:
            start_col = max(entry["col"], current_col)
            if start_col > grid_columns:
                continue
            if start_col > current_col:
                widths.append(start_col - current_col)
                placements.append(None)
            span = max(1, min(entry["span"], grid_columns - start_col + 1))
            widths.append(span)
            placements.append(entry["id"])
            current_col = start_col + span
        if current_col <= grid_columns:
            widths.append(grid_columns - current_col + 1)
            placements.append(None)
        widths = [max(1, w) for w in widths]

        row_cols = st.columns(widths)
        for col_widget, cid in zip(row_cols, placements):
            if cid:
                with col_widget:
                    card_by_id[cid]["render"]()
