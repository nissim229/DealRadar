"""
components/analytics_history.py
The History page group, split out of components/analytics.py (Section 5
monolith-split plan): the delete-confirmation dialog, the History tab
content (search/bulk-cleanup/pagination/archived-scan viewer), and
render_history_page - the top-level page main.py imports directly.
"""
import streamlit as st
import database as db
import pandas as pd
import json
from datetime import datetime, timedelta
from underwriting import compute_deal_metrics
from icons import icon as svg_icon
from components.settings import format_local_datetime
from guest_mode import render_guest_banner

from components.analytics_atoms import _format_price_short, _safe_hoa, render_empty_state
from components.analytics_results import _render_scan_results


def _clear_hist_delete_target():
    st.session_state.hist_delete_target = None


@st.dialog("Delete Scan Report", on_dismiss=_clear_hist_delete_target)
def _delete_history_dialog():
    """Same floating-dialog shape as car_search.py's
    _delete_saved_car_search_dialog (see [[table_action_pattern]]) - both the grid's
    trash icon and the "Remove" button under an opened report set
    hist_delete_target and land here, so there's exactly one delete
    confirmation, not two different ones with different behavior (the
    "Remove" button used to skip confirmation entirely). on_dismiss clears
    the target on every dismissal path, not just Cancel - see
    [[table_action_pattern]] for why that matters (a dialog dismissed via
    the native X otherwise reopens on the next unrelated interaction)."""
    ctx = st.session_state.get("hist_delete_target")
    if not ctx:
        st.write("No report selected.")
        return

    st.warning(f"Delete **{ctx['name']}** from your scan history? This can't be undone.")
    confirm_col, cancel_col = st.columns(2)
    with confirm_col:
        if st.button(":material/delete_forever: Confirm Delete", type="primary", width="stretch"):
            db.delete_history_log(st.session_state.user_id, ctx["id"])
            st.session_state.hist_delete_target = None
            st.toast("Removed from your scan history.")
            st.rerun()
    with cancel_col:
        if st.button("Cancel", width="stretch"):
            st.session_state.hist_delete_target = None
            st.rerun()


def _render_history_tab(view_mode, calc_rent, calc_vacancy_pct, calc_tax_rate, calc_ins_rate, calc_down_pct, calc_interest, calc_target_yield):
    st.markdown(f"""
        <div style='display:flex; align-items:center; gap:10px; margin-bottom:2px;'>
            {svg_icon("clock", size=20, color="var(--radar-primary)")}
            <span style='font-weight:700; font-size:var(--radar-text-xl); color:var(--radar-navy);'>Historical Scans Registry Archive</span>
        </div>
    """, unsafe_allow_html=True)
    st.caption("Review any past scan for free - browsing your history doesn't use any credits.")

    history_rows = db.get_history_logs(st.session_state.user_id)
    if history_rows:
        df_hist = pd.DataFrame(history_rows, columns=["Log ID", "Profile Name", "Geographic Location", "Generation Date", "Hidden Raw Content", "Hidden Coordinates"])
        # Stored as UTC (SQLite's CURRENT_TIMESTAMP) - convert to this
        # user's own timezone (Settings) before it's ever displayed, so
        # a scan from "10 minutes ago" doesn't read like it happened at
        # a confusing hour this morning.
        _user_tz = st.session_state.user_settings.get("timezone")
        df_hist["Generation Date"] = df_hist["Generation Date"].apply(lambda d: format_local_datetime(d, _user_tz))
        search_hist = st.text_input(":material/search: Search History Log", placeholder="Start typing...", key="hist_search_field_unique")
        if search_hist:
            df_hist = df_hist[df_hist["Profile Name"].str.contains(search_hist, case=False, na=False)]

        with st.expander(":material/delete_sweep: Bulk cleanup - delete old logs"):
            bulk_col1, bulk_col2 = st.columns([2, 1])
            with bulk_col1:
                bulk_days = st.number_input("Delete every log older than this many days", min_value=1, value=90, step=1, key="hist_bulk_days")
            with bulk_col2:
                st.markdown("<div style='margin-top:28px;'></div>", unsafe_allow_html=True)
                if st.button(":material/delete_sweep: Preview & Delete", width="stretch", key="hist_bulk_delete_trigger"):
                    st.session_state.hist_bulk_pending = bulk_days

            if st.session_state.get("hist_bulk_pending"):
                pending_days = st.session_state.hist_bulk_pending
                cutoff_label = (datetime.now() - timedelta(days=int(pending_days))).strftime("%B %d, %Y")
                st.warning(f"Delete every scan log from before **{cutoff_label}** ({int(pending_days)}+ days old)? This can't be undone.")
                bulk_confirm_col, bulk_cancel_col = st.columns(2)
                with bulk_confirm_col:
                    if st.button(":material/delete_sweep: Confirm Bulk Delete", type="primary", width="stretch", key="hist_bulk_confirm_btn"):
                        deleted_count = db.delete_history_logs_older_than(st.session_state.user_id, pending_days)
                        st.session_state.hist_bulk_pending = None
                        st.toast(f"Deleted {deleted_count} old log{'s' if deleted_count != 1 else ''}.")
                        st.rerun()
                with bulk_cancel_col:
                    if st.button("Cancel", width="stretch", key="hist_bulk_cancel_btn"):
                        st.session_state.hist_bulk_pending = None
                        st.rerun()

        page_size = st.selectbox("Rows per page", [10, 25, 50, 100], index=1, key="hist_page_size")
        total_rows = len(df_hist)
        total_pages = max(1, (total_rows + page_size - 1) // page_size)
        current_page = min(st.session_state.get("hist_current_page", 1), total_pages)

        page_nav1, page_nav2, page_nav3 = st.columns([1, 2, 1])
        with page_nav1:
            if st.button(":material/chevron_left: Previous", disabled=current_page <= 1, width="stretch", key="hist_prev_page_btn"):
                st.session_state.hist_current_page = current_page - 1
                st.rerun()
        with page_nav2:
            st.markdown(f"<div style='text-align:center; padding-top:8px; color:var(--radar-text-muted); font-size:13px;'>Page {current_page} of {total_pages} · {total_rows} total scans</div>", unsafe_allow_html=True)
        with page_nav3:
            if st.button("Next :material/chevron_right:", disabled=current_page >= total_pages, width="stretch", key="hist_next_page_btn"):
                st.session_state.hist_current_page = current_page + 1
                st.rerun()

        df_hist_page = df_hist.iloc[(current_page - 1) * page_size: current_page * page_size]

        def _summarize_history_row(coords_raw):
            """Matches / price range / deal-grade breakdown for one
            history row - computed from the archived listing snapshot
            using the CURRENT underwriting assumptions (same sidebar
            inputs the results view itself uses), not whatever
            assumptions were active when the scan originally ran."""
            try:
                pts = json.loads(coords_raw)
                if not pts:
                    return "-", "-", "-"
                prices = [float(p["price"]) for p in pts]
                price_range = (_format_price_short(min(prices)) if min(prices) == max(prices)
                               else f"{_format_price_short(min(prices))}–{_format_price_short(max(prices))}")
                grade_counts = {"excellent": 0, "average": 0, "critical": 0}
                for p in pts:
                    m = compute_deal_metrics(float(p["price"]), calc_rent, calc_vacancy_pct, calc_tax_rate,
                                              calc_ins_rate, calc_down_pct, calc_interest, calc_target_yield,
                                              hoa_monthly=_safe_hoa(p))
                    grade_counts[m["grade"]] += 1
                grades_str = f"🟢{grade_counts['excellent']} 🟡{grade_counts['average']} 🔴{grade_counts['critical']}"
                return str(len(pts)), price_range, grades_str
            except Exception as e:
                print(f"[Analytics] History row summary failed: {e}")
                return "-", "-", "-"

        summaries = df_hist_page["Hidden Coordinates"].apply(_summarize_history_row)
        df_hist_display = df_hist_page[["Profile Name", "Geographic Location"]].copy()
        df_hist_display["Matches"] = [s[0] for s in summaries]
        df_hist_display["Price Range"] = [s[1] for s in summaries]
        df_hist_display["Grades (🟢/🟡/🔴)"] = [s[2] for s in summaries]
        df_hist_display["Generation Date"] = df_hist_page["Generation Date"]
        df_hist_display["Delete"] = ":material/delete:"
        selected_log_grid = st.dataframe(
            df_hist_display, width="stretch", hide_index=True, on_select="rerun", selection_mode="single-row", key="history_log_grid",
            height=len(df_hist_display) * 35 + 38,
            column_config={
                "Matches": st.column_config.TextColumn(width="small"),
                "Price Range": st.column_config.TextColumn(width="small"),
                "Grades (🟢/🟡/🔴)": st.column_config.TextColumn(width="small"),
                "Delete": st.column_config.ButtonColumn("", width="small", type="tertiary", key="hist_delete_btn_click"),
            },
        )
        selected_log_indices = selected_log_grid.get("selection", {}).get("rows", [])

        delete_click = st.session_state.get("hist_delete_btn_click")
        if delete_click and delete_click.get("row") is not None:
            st.session_state.hist_delete_target = {
                "id": df_hist_page.iloc[delete_click["row"]]["Log ID"],
                "name": df_hist_page.iloc[delete_click["row"]]["Profile Name"],
            }

        if st.session_state.get("hist_delete_target"):
            _delete_history_dialog()

        if selected_log_indices:
            target_log_row_idx = selected_log_indices[0]

            archived_log_id = df_hist_page.iloc[target_log_row_idx]["Log ID"]
            archived_report_body = str(df_hist_page.iloc[target_log_row_idx]["Hidden Raw Content"])
            archived_report_name = str(df_hist_page.iloc[target_log_row_idx]["Profile Name"])
            archived_coords_raw = str(df_hist_page.iloc[target_log_row_idx]["Hidden Coordinates"])

            st.markdown("---")
            info_col, delete_col = st.columns([5, 1])
            with info_col:
                st.info(f"Viewing Historical Saved Archive Record: **{archived_report_name}**")
            with delete_col:
                st.markdown("<div style='margin-top:6px;'></div>", unsafe_allow_html=True)
                if st.button(":material/delete: Remove", key=f"delete_history_{archived_log_id}", width="stretch"):
                    st.session_state.hist_delete_target = {"id": archived_log_id, "name": archived_report_name}
                    st.rerun()

            _render_scan_results(
                archived_report_body, archived_report_name, archived_coords_raw,
                f"hist_{archived_log_id}", view_mode, calc_rent, calc_vacancy_pct, calc_tax_rate, calc_ins_rate,
                calc_down_pct, calc_interest, calc_target_yield,
                show_preview_notice=False, pdf_button_label="Export Archived Report to Document PDF / Print",
                pdf_filename_prefix="DealRadar_Archive",
            )
        else:
            st.info("Click any row above to view that scan's full report.", icon=":material/lightbulb:")
    else:
        render_empty_state(
            "clock", "No scans yet",
            "Once you run a search, every scan gets saved here automatically - free to browse back through anytime, no credits used.",
        )


def render_history_page(is_guest=False):
    """Top-level History page - promoted out of a nested tab on Run
    Property Scans into its own navbar item, per real feedback that the
    main navbar was the clearer place to find it than a sub-tab someone
    has to already be on the scan page to notice (see
    [[nav_simplification_ad_hoc_search]]). Content itself (_render_history_tab)
    is unchanged - just given a real page shell and, since there's no
    longer an interactive Pro sidebar to source calc_* from up here, the
    user's saved default assumptions instead (still fully adjustable per
    property from within the results themselves)."""
    st.markdown("""
        <style>
        div.st-key-history_hero {
            background: var(--radar-gradient-hero);
            padding: var(--radar-space-6) var(--radar-space-7);
            margin-bottom: var(--radar-space-5);
            border-radius: 0 0 var(--radar-radius-xl) var(--radar-radius-xl);
        }
        </style>
    """, unsafe_allow_html=True)

    with st.container(key="history_hero"):
        st.markdown(f"""
            <div style='text-align:center; max-width:760px; margin:0 auto;'>
                <div style='display:flex; align-items:center; justify-content:center; gap:14px; margin-bottom:10px;'>
                    <div style='background: var(--radar-gradient-brand); width: 48px; height: 48px;
                                border-radius: var(--radar-radius-md); display:flex; align-items:center; justify-content:center; flex-shrink:0;'>
                        {svg_icon("clock", size=24, color="white")}
                    </div>
                    <div style='font-family:var(--radar-font-display); font-size:32px; font-weight:800; color:white; line-height:1.2;'>History</div>
                </div>
                <div style='font-size:16px; color:var(--radar-text-on-dark-muted);'>Every past scan, free to browse back through anytime</div>
            </div>
        """, unsafe_allow_html=True)

    if is_guest:
        render_guest_banner("your scan history isn't tracked in a demo session")
        render_empty_state(
            "clock", "Sign in to keep a history",
            "Every real scan you run gets saved here automatically once you have an account.",
        )
        return

    _defaults = st.session_state.user_settings
    view_mode = _defaults.get("default_underwriter_mode", "Simple")
    _render_history_tab(
        view_mode, 3500, _defaults["default_vacancy_pct"], _defaults["default_tax_rate"],
        _defaults["default_insurance_rate"], _defaults["default_down_pct"], _defaults["default_interest_rate"],
        _defaults["default_target_yield"],
    )


