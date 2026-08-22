"""
components/analytics_map.py
Clustered map data + full-width clustered results map, split out of
components/analytics.py (Section 5 monolith-split plan).
build_clustered_map_data is NOT analytics-specific despite having
lived there - components/car_search.py imports it directly for Cars's
own map. Re-exported through components/analytics.py's facade so both
that cross-file import and every internal caller keep working
unchanged.
"""
import json
import streamlit as st
import pandas as pd
import plotly.express as px

from underwriting import compute_deal_metrics
from components.property_card import render_property_card
from components.analytics_atoms import _safe_hoa, _format_price_short


def build_clustered_map_data(df, cluster_grid_deg=0.008):
    """Groups nearby properties into clusters for map display. Plotly's free
    open-street-map style has no native clustering (that requires a paid
    Mapbox token, which this app doesn't have) - so this buckets properties
    by rounding their lat/lon to a shared grid cell. Cells with more than one
    property become a single cluster marker showing a count; isolated
    properties still render as individual pins color-coded by grade.

    Tested with: far-apart points (no clustering), very-close points (full
    cluster), and a mixed case (one cluster + one isolated point) - all
    produce correct counts, dominant grades, and traceable member indices
    back to the original dataframe."""
    df = df.copy()
    df["_grid_lat"] = (df["latitude"] / cluster_grid_deg).round() * cluster_grid_deg
    df["_grid_lon"] = (df["longitude"] / cluster_grid_deg).round() * cluster_grid_deg

    clustered_rows = []
    for (glat, glon), group in df.groupby(["_grid_lat", "_grid_lon"]):
        if len(group) == 1:
            row = group.iloc[0]
            clustered_rows.append({
                "latitude": row["latitude"], "longitude": row["longitude"],
                "count": 1, "label": f"${row['price']:,.0f}",
                "grade": row["_grade"], "is_cluster": False,
                "title": row["title"], "address": row["address"], "price": row["price"],
                "member_indices": [row.name],
            })
        else:
            avg_lat = group["latitude"].mean()
            avg_lon = group["longitude"].mean()
            avg_price = group["price"].mean()
            dominant_grade = group["_grade"].mode().iloc[0]
            clustered_rows.append({
                "latitude": avg_lat, "longitude": avg_lon,
                "count": len(group), "label": f"{len(group)} homes",
                "grade": dominant_grade, "is_cluster": True,
                "title": f"{len(group)} properties", "address": "", "price": avg_price,
                "member_indices": list(group.index),
            })
    return pd.DataFrame(clustered_rows)


def _render_clustered_results_map(coords_json, key_prefix, view_mode, calc_rent, calc_vacancy_pct, calc_tax_rate, calc_ins_rate,
                                   calc_down_pct, calc_interest, calc_target_yield,
                                   filter_min_price=None, filter_max_price=None, filter_min_beds=0, filter_min_baths=0,
                                   filter_grades=None, height=650):
    """Full-width, grade-colored, clustered results map with click-a-pin
    (or a cluster) for detail - originally _render_scan_results's own
    "Map Only" view mode, extracted so the hero's compact results area
    (see [[hero_redesign_compact_results]]) can show the exact same map
    instead of a second, differently-built one. filter_* default to "no
    filtering", so a caller with no quick-filter bar of its own (the
    hero) can just omit them."""
    if filter_grades is None:
        filter_grades = ["excellent", "average", "critical"]
    if not coords_json:
        return
    try:
        parsed_points = json.loads(coords_json)
        df_listings_grid = pd.DataFrame(parsed_points)
        if filter_min_price is not None:
            df_listings_grid = df_listings_grid[
                (df_listings_grid["price"] >= filter_min_price) &
                (df_listings_grid["price"] <= filter_max_price) &
                (df_listings_grid["beds"] >= filter_min_beds) &
                (df_listings_grid["baths"] >= filter_min_baths)
            ].reset_index(drop=True)

        if df_listings_grid.empty:
            st.info("No properties match your current filters. Try widening the price range or lowering the min beds.")
            return

        grades_for_map = []
        for _, r in df_listings_grid.iterrows():
            m = compute_deal_metrics(float(r["price"]), calc_rent, calc_vacancy_pct, calc_tax_rate,
                                      calc_ins_rate, calc_down_pct, calc_interest, calc_target_yield,
                                      hoa_monthly=_safe_hoa(r))
            grades_for_map.append(m["grade"])
        df_listings_grid["_grade"] = grades_for_map

        if filter_grades and len(filter_grades) < 3:
            df_listings_grid = df_listings_grid[df_listings_grid["_grade"].isin(filter_grades)].reset_index(drop=True)

        if df_listings_grid.empty:
            st.info("No properties match your current filters. Try widening the price range, lowering the min beds, or including more deal grades.")
            return

        grade_colors = {"excellent": "#10b981", "average": "#f59e0b", "critical": "#ef4444"}

        cluster_df = build_clustered_map_data(df_listings_grid)
        # Unclustered pins get a bigger marker than before (was 18px) so a
        # short price label like "$450K" actually fits and stays legible -
        # at a glance across the map, not just on hover/click, matching how
        # Zillow shows price directly on individual (non-clustered) pins.
        cluster_df["_marker_size"] = cluster_df["count"].apply(lambda c: 30 if c == 1 else min(24 + c * 3, 46))
        cluster_df["_marker_text"] = cluster_df.apply(
            lambda row: str(row["count"]) if row["is_cluster"] else _format_price_short(row["price"]), axis=1
        )

        fig_full_map = px.scatter_mapbox(
            cluster_df, lat="latitude", lon="longitude", hover_name="title",
            hover_data={"address": True, "price": True, "count": True, "latitude": False, "longitude": False},
            color="grade", color_discrete_map=grade_colors,
            size="_marker_size", size_max=46, text="_marker_text",
            zoom=11, center={"lat": df_listings_grid["latitude"].mean(), "lon": df_listings_grid["longitude"].mean()}
        )
        fig_full_map.update_traces(textfont=dict(color="white", size=11, family="Arial Black"), textposition="middle center")
        fig_full_map.update_layout(
            mapbox_style="open-street-map", margin={"r": 0, "t": 0, "l": 0, "b": 0},
            height=height, showlegend=False,
        )

        map_event = st.plotly_chart(
            fig_full_map, width="stretch", key=f"{key_prefix}_full_map_view_chart",
            on_select="rerun", selection_mode="points",
            config={"displayModeBar": True, "scrollZoom": True},
        )

        selected_points = map_event.get("selection", {}).get("points", []) if map_event else []
        if selected_points:
            point_index = selected_points[0].get("point_index")
            if point_index is not None and point_index < len(cluster_df):
                clicked = cluster_df.iloc[point_index]
                st.markdown("---")
                if clicked["is_cluster"]:
                    st.markdown(f"#### :material/location_on: {clicked['count']} properties in this area")
                    st.caption("Zoom in on the map or narrow your filters above to click an individual property.")
                    member_rows = df_listings_grid.iloc[clicked["member_indices"]]
                    summary_df = member_rows[["title", "address", "price", "beds", "baths"]].copy()
                    summary_df["price"] = summary_df["price"].apply(lambda p: f"${p:,.0f}")
                    st.dataframe(summary_df, hide_index=True, width="stretch", height=len(summary_df) * 35 + 38)
                else:
                    st.markdown("#### :material/location_on: Selected Property")
                    sel_idx = clicked["member_indices"][0]
                    sel_row = df_listings_grid.iloc[sel_idx]
                    sel_metrics = compute_deal_metrics(
                        float(sel_row["price"]), calc_rent, calc_vacancy_pct, calc_tax_rate,
                        calc_ins_rate, calc_down_pct, calc_interest, calc_target_yield,
                        hoa_monthly=_safe_hoa(sel_row)
                    )
                    render_property_card(sel_idx, sel_row, sel_metrics, view_mode, f"{key_prefix}_map_view_card", True,
                                          st.session_state.user_id, st.session_state.get("distance_reference_point"),
                                          calc_target_yield,
                                          {"down_pct": calc_down_pct, "interest": calc_interest, "rent": calc_rent,
                                           "vacancy": calc_vacancy_pct, "tax_rate": calc_tax_rate, "ins_rate": calc_ins_rate})
        else:
            st.info("Click a pin above to see that property's price, deal grade, and full details.", icon=":material/lightbulb:")
    except Exception as e:
        print(f"[Analytics] Split-view map render failed: {e}")
        st.caption("Unable to load the map for this scan.")
