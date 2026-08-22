"""
tests/test_pure_helpers.py
Regression tests for small, pure (no I/O) helper functions spread across
agent_engine.py, google_oauth.py, and email_utils.py - reviewer-flagged
as easy, high-value coverage since none of them need a database or
network access to test.
"""
import pytest

import agent_engine as ae
import google_oauth
import email_utils


# ---------------------------------------------------------------------------
# agent_engine.py: outbound search-link builders
# ---------------------------------------------------------------------------

def test_build_zillow_search_url_happy_path():
    """Confirmed-working pattern: address spaces become hyphens, the whole
    slug is URL-quoted (commas preserved unescaped per the safe='-,' arg),
    landing on Zillow's own public search page - see the function's own
    docstring for why this is address-only (no reliable way to add an
    MLS# to this specific slug format)."""
    url = ae.build_zillow_search_url("123 Main St, Denver, CO")
    assert url == "https://www.zillow.com/homes/123-Main-St,-Denver,-CO_rb/"


def test_build_zillow_search_url_ignores_mls_number():
    """mls_number is accepted only for call-site symmetry with
    build_redfin_search_url - it must never appear in the Zillow URL."""
    with_mls = ae.build_zillow_search_url("123 Main St, Denver, CO", mls_number="1065651")
    without_mls = ae.build_zillow_search_url("123 Main St, Denver, CO")
    assert with_mls == without_mls
    assert "1065651" not in with_mls


def test_build_zillow_search_url_returns_none_without_address():
    assert ae.build_zillow_search_url("") is None
    assert ae.build_zillow_search_url(None) is None


def test_build_redfin_search_url_includes_mls_when_known():
    """Both address and a quoted MLS# together, site-scoped to redfin.com -
    an MLS# alone isn't enough to disambiguate (see the function's own
    docstring: the same MLS# matched real listings in 5 different states),
    so the address must always be present to anchor the search."""
    url = ae.build_redfin_search_url("123 Main St, Denver, CO", mls_number="1065651")
    assert url == 'https://www.google.com/search?q=site%3Aredfin.com%20123%20Main%20St%2C%20Denver%2C%20CO%20%22MLS%23%201065651%22'


def test_build_redfin_search_url_address_only():
    url = ae.build_redfin_search_url("123 Main St, Denver, CO")
    assert url == "https://www.google.com/search?q=site%3Aredfin.com%20123%20Main%20St%2C%20Denver%2C%20CO"
    assert "MLS" not in url


def test_build_redfin_search_url_returns_none_with_nothing():
    assert ae.build_redfin_search_url(None, None) is None


# ---------------------------------------------------------------------------
# agent_engine.py: distance calculation
# ---------------------------------------------------------------------------

def test_calculate_distance_miles_zero_for_identical_points():
    assert ae.calculate_distance_miles(39.7392, -104.9903, 39.7392, -104.9903) == 0.0


def test_calculate_distance_miles_known_real_world_distance():
    """NYC to LA (great-circle 'as the crow flies', not driving distance)
    is a well-known ~2,450 mile reference figure - sanity-checks that
    geopy's geodesic calculation is wired up correctly, not just that it
    returns *some* number."""
    miles = ae.calculate_distance_miles(40.7128, -74.0060, 34.0522, -118.2437)
    assert miles == pytest.approx(2451.0, abs=5.0)


def test_calculate_distance_miles_none_when_any_coordinate_missing():
    """A data-completeness guard, not a computation - any None coordinate
    (e.g. a listing with no lat/lon) must short-circuit to None rather
    than raise, since this runs once per property card render."""
    assert ae.calculate_distance_miles(None, -104.9903, 39.7392, -104.9903) is None
    assert ae.calculate_distance_miles(39.7392, None, 39.7392, -104.9903) is None
    assert ae.calculate_distance_miles(39.7392, -104.9903, None, -104.9903) is None
    assert ae.calculate_distance_miles(39.7392, -104.9903, 39.7392, None) is None


# ---------------------------------------------------------------------------
# google_oauth.py / email_utils.py: configuration-presence checks
# ---------------------------------------------------------------------------

def test_is_google_oauth_configured_requires_both_id_and_secret(monkeypatch):
    monkeypatch.setattr(google_oauth, "GOOGLE_CLIENT_ID", "fake-id")
    monkeypatch.setattr(google_oauth, "GOOGLE_CLIENT_SECRET", "fake-secret")
    assert google_oauth.is_google_oauth_configured() is True

    monkeypatch.setattr(google_oauth, "GOOGLE_CLIENT_SECRET", None)
    assert google_oauth.is_google_oauth_configured() is False

    monkeypatch.setattr(google_oauth, "GOOGLE_CLIENT_ID", None)
    monkeypatch.setattr(google_oauth, "GOOGLE_CLIENT_SECRET", "fake-secret")
    assert google_oauth.is_google_oauth_configured() is False


def test_is_email_configured_requires_both_address_and_password(monkeypatch):
    monkeypatch.setattr(email_utils, "GMAIL_ADDRESS", "test@example.com")
    monkeypatch.setattr(email_utils, "GMAIL_APP_PASSWORD", "fakepassword1234")
    assert email_utils.is_email_configured() is True

    monkeypatch.setattr(email_utils, "GMAIL_APP_PASSWORD", None)
    assert email_utils.is_email_configured() is False

    monkeypatch.setattr(email_utils, "GMAIL_ADDRESS", None)
    monkeypatch.setattr(email_utils, "GMAIL_APP_PASSWORD", "fakepassword1234")
    assert email_utils.is_email_configured() is False
