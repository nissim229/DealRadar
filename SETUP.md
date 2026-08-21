# DealRadar - Setup Guide

## 1. Place these files

Copy this whole folder to wherever you want your project, e.g.:
```
D:\Projects\DealRadar\
```

Final structure should look like (abridged - the real tree has more modules
in both places as the app has grown, this just shows the shape):
```
DealRadar\
│   main.py
│   database.py
│   agent_engine.py
│   car_engine.py
│   plan_limits.py / roles.py
│   topbar.py / nav.py / theme.py / design_tokens.py / icons.py
│   requirements.txt
│   requirements-lock.txt   (full pinned dependency freeze, incl. transitive)
│   .python-version
│   .env.example
└───components\
        __init__.py
        auth_portal.py
        analytics.py
        admin_controls.py
        car_search.py / car_card.py
        portfolio.py / pricing.py / settings.py / property_card.py
```

## 2. Create a virtual environment

Open PowerShell, navigate into the project folder, then run:

```powershell
cd D:\Projects\DealRadar
python -m venv venv
```

## 3. Activate the virtual environment

```powershell
.\venv\Scripts\Activate.ps1
```

If PowerShell blocks this with an execution policy error, run this once (as a normal user, not admin):
```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```
Then try activating again.

You'll know it worked when your prompt shows `(venv)` at the start.

## 4. Install dependencies

With the venv active:
```powershell
pip install -r requirements.txt
```

For an exact reproduction of the tested environment (including transitive
dependencies, not just the ~9 direct ones `requirements.txt` pins), install
from the full freeze instead:
```powershell
pip install -r requirements-lock.txt
```

## 5. Set up your API keys

Copy `.env.example` to a new file named `.env` in the same folder:
```powershell
copy .env.example .env
```

Open `.env` in a text editor and replace the placeholder values with your real keys:
```
OPENAI_API_KEY=sk-...your real key...
FIRECRAWL_API_KEY=fc-...your real key...
```

If you don't have these keys yet, the app will still run fine - `agent_engine.py`
automatically falls back to a local mock report generator whenever the OpenAI
call fails (including for a missing/invalid key), so you can test the whole
app end-to-end before paying for any API usage.

You do **not** need to add a `PASSWORD_PEPPER` line yourself - `database.py`
generates one automatically on first run and appends it to `.env`. Once any
real password has been hashed with it, back up `.env`: losing that value
would make every stored password unrecoverable (the app will refuse to start
and regenerate a new one if it detects this situation, rather than silently
locking everyone out).

## 6. Run the app

```powershell
streamlit run main.py
```

This should open your browser automatically to something like `http://localhost:8501`.

## 7. Log in

The app auto-provisions a master admin account on first run:
- **Email:** admin@scoutai.com
- **Password:** admin123

Log in with that, or register a new account (new accounts get 3 free credits).

> ⚠️ **BEFORE GOING LIVE:** rotate the seeded admin password away from
> `admin123`. It's kept as-is intentionally during development, but it is
> permanently visible in this repo's git history - treat it as public,
> not secret, the moment this project or its history becomes public or
> production-facing.

## Bugs fixed in this version

1. `agent_engine.py` - fixed missing `[0]` index that crashed every successful
   (non-fallback) OpenAI call.
2. `agent_engine.py` / `analytics.py` - `run_agent_workflow()` now requires
   `user_id`, preventing cross-tenant profile lookups when two users share a
   profile name.
3. `strategy_config.py` (this module has since been removed entirely -
   real-estate search is now ad-hoc, like cars, see `components/analytics.py`)
   - fixed the Decommission tab, which previously passed a list instead of a
   single row index, breaking all profile deletion.
