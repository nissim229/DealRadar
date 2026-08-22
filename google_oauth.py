"""
google_oauth.py
"Sign in with Google" via the standard OAuth 2.0 Authorization Code flow,
hit directly with `requests` (already a dependency) rather than pulling in
a third-party Streamlit OAuth component - Google's token/userinfo endpoints
are simple enough that a dedicated library isn't worth the extra dependency
surface. Same .env-driven configuration pattern as email_utils.py's Gmail
credentials, and degrades the same way (returns None/False, never raises)
when the credentials aren't configured yet.
"""
import os
import hmac
import hashlib
import time
import requests
from urllib.parse import urlencode
from dotenv import load_dotenv

load_dotenv()

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_OAUTH_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")

# Must exactly match an Authorized redirect URI configured on the Google
# Cloud OAuth client. Defaults to localhost for local dev; set
# APP_BASE_URL in .env before a real deployment - and update the
# Authorized redirect URI on the Google Cloud OAuth client to match,
# since Google rejects any mismatch (see components/auth_portal.py's
# APP_BASE_URL for the identical fix on the password-reset-link side).
REDIRECT_URI = os.getenv("APP_BASE_URL", "http://localhost:8501")

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
USERINFO_ENDPOINT = "https://www.googleapis.com/oauth2/v3/userinfo"

STATE_MAX_AGE_SECONDS = 600


def is_google_oauth_configured():
    return bool(GOOGLE_CLIENT_ID) and bool(GOOGLE_CLIENT_SECRET)


def _sign(payload):
    return hmac.new((GOOGLE_CLIENT_SECRET or "").encode(), payload.encode(), hashlib.sha256).hexdigest()


def generate_state(mode="signin"):
    """A CSRF token for the OAuth `state` param that doesn't rely on
    st.session_state surviving the round trip - it can't, since Streamlit
    resets session_state on every full page load, and leaving for Google's
    consent screen and being redirected back *is* a full page load. Instead
    this is a timestamp signed with the app's own OAuth client secret, so
    the callback can verify it came from us (and hasn't expired) using only
    the value itself - no server-side state to lose.

    `mode` ("signin" or "register") rides along in the same signed payload,
    for the same reason - it's how the callback knows whether to only look
    up an existing account or offer to create one, without needing to
    remember which tab the user was on before they left for Google."""
    mode = mode if mode in ("signin", "register") else "signin"
    ts = str(int(time.time()))
    payload = f"{ts}.{mode}"
    return f"{payload}.{_sign(payload)}"


def verify_state(state):
    """Returns the verified mode ("signin"/"register") if `state` is a
    genuine, unexpired token this app issued, or None otherwise."""
    if not state or state.count(".") != 2:
        return None
    ts, mode, sig = state.split(".", 2)
    payload = f"{ts}.{mode}"
    if not hmac.compare_digest(sig, _sign(payload)):
        return None
    if mode not in ("signin", "register"):
        return None
    try:
        return mode if (time.time() - int(ts)) <= STATE_MAX_AGE_SECONDS else None
    except ValueError:
        return None


def build_auth_url(mode="signin"):
    """Builds the URL to send the user's browser to, embedding a signed,
    self-verifying `state` token - see generate_state()."""
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "state": generate_state(mode),
        "prompt": "select_account",
    }
    return f"{AUTH_ENDPOINT}?{urlencode(params)}"


def fetch_user_info(code):
    """Exchanges an authorization code for the signed-in user's email/name.
    Returns None on any failure (expired code, network error, bad
    credentials) - the caller should treat None as "couldn't sign in" and
    fall back to the normal login form, never surface raw OAuth errors to
    the end user."""
    if not is_google_oauth_configured():
        return None
    try:
        token_resp = requests.post(TOKEN_ENDPOINT, data={
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": REDIRECT_URI,
        }, timeout=10)
        token_resp.raise_for_status()
        access_token = token_resp.json()["access_token"]

        userinfo_resp = requests.get(
            USERINFO_ENDPOINT,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        userinfo_resp.raise_for_status()
        info = userinfo_resp.json()
        return {"email": info["email"], "name": info.get("name", "")}
    except Exception as e:
        print(f"[GoogleOAuth] Failed to fetch user info: {e}")
        return None
