"""
components/analytics.py
Facade for the Run Property Scans / History / Saved Properties feature
group (Section 5 monolith-split plan). The actual code now lives in
sibling modules - analytics_atoms, analytics_dialogs, analytics_map,
analytics_scan_form, analytics_scan_engine, analytics_results,
analytics_history, analytics_saved, analytics_dashboard - this file only
re-exports the names other files import directly:
  - main.py: render_analytics_dashboard, render_history_page
  - components/portfolio.py: render_empty_state, render_stat_card
  - components/car_search.py: build_clustered_map_data
"""
from components.analytics_atoms import render_empty_state, render_stat_card
from components.analytics_map import build_clustered_map_data
from components.analytics_history import render_history_page
from components.analytics_dashboard import render_analytics_dashboard
