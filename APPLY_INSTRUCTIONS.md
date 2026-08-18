# ScoutAI analytics.py Split - Apply Instructions

## What this does
Splits the old 1,457-line components/analytics.py into 5 focused files:
- underwriting.py       (root folder)  - pure math, no UI
- pdf_export.py         (root folder)  - PDF/print export
- whatif_calculator.py  (root folder)  - the dark HTML/CSS/JS calculator
- components/property_card.py          - the property card component
- components/analytics.py (replaced)   - slimmed to just the page itself

Every function was extracted with exact line-range copying (not retyped), then
verified with a full simulated import chain and functional math tests before
being packaged here. Nothing was lost, nothing was duplicated.

## STEP 1 - Backup your current file first (safety net)
Open PowerShell in your project folder and run:

    Copy-Item .\components\analytics.py .\components\analytics_BACKUP.py

If anything goes wrong after applying this update, you can instantly restore
by running:

    Copy-Item .\components\analytics_BACKUP.py .\components\analytics.py -Force

## STEP 2 - Extract this zip
Extract it so the files land directly in your project structure:
- underwriting.py, pdf_export.py, whatif_calculator.py -> project root
  (same folder as main.py, database.py, agent_engine.py)
- property_card.py, analytics.py -> components\ folder
  (analytics.py REPLACES your existing one)

## STEP 3 - Verify all 5 files landed correctly, BEFORE restarting the app
Run each of these and confirm each one finds a match:

    Select-String -Path .\underwriting.py -Pattern "def compute_deal_metrics"
    Select-String -Path .\pdf_export.py -Pattern "def generate_pdf_download_link"
    Select-String -Path .\whatif_calculator.py -Pattern "def render_whatif_calculator_html"
    Select-String -Path .\components\property_card.py -Pattern "def render_property_card"
    Select-String -Path .\components\analytics.py -Pattern "def render_analytics_dashboard"

If any of these come back empty, STOP - do not restart the app yet. Tell me
which one failed and we'll fix just that file.

## STEP 4 - Only after all 5 checks pass, restart the app
    streamlit run main.py

If it starts cleanly and the app looks/works the same as before, the split
was successful. If you get an ImportError on startup, tell me the exact
error message and we'll fix it immediately.
