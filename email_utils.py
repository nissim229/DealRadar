"""
email_utils.py
Outbound transactional email (currently just password-reset links) via
Gmail SMTP with an app password - the simplest option for this app's scale,
same .env-driven configuration pattern as the other API keys in
agent_engine.py. Degrades gracefully (returns False, never raises) when the
credentials aren't configured yet, so the rest of the reset flow can show a
clear "not set up yet" message instead of crashing.
"""
import os
import smtplib
from email.mime.text import MIMEText
from dotenv import load_dotenv

load_dotenv()

GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")


def is_email_configured():
    return bool(GMAIL_ADDRESS) and bool(GMAIL_APP_PASSWORD)


def send_password_reset_email(to_email, reset_link):
    """Sends a plain-text password reset email. Returns True on success,
    False on any failure (not configured, network error, bad credentials,
    etc.) - the caller should treat False as "couldn't send" without
    assuming a specific cause, and never surface raw SMTP errors to the
    end user."""
    if not is_email_configured():
        return False

    body = (
        f"Someone requested a password reset for your DealRadar account.\n\n"
        f"Reset your password here (this link expires in 1 hour):\n{reset_link}\n\n"
        f"If you didn't request this, you can safely ignore this email."
    )
    msg = MIMEText(body)
    msg["Subject"] = "Reset your DealRadar password"
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = to_email

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=10) as server:
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            server.send_message(msg)
        return True
    except Exception as e:
        print(f"[Email] Failed to send password reset email: {e}")
        return False


def _send_plain(to_email, subject, body):
    """Shared send path for the notification emails below - same
    graceful-degrade-on-failure contract as send_password_reset_email
    (returns True/False, never raises), factored out since none of these
    need anything beyond a plain subject/body."""
    if not is_email_configured():
        return False
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = to_email
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=10) as server:
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            server.send_message(msg)
        return True
    except Exception as e:
        print(f"[Email] Failed to send '{subject}' to {to_email}: {e}")
        return False


def send_test_email(to_email):
    """Triggered by the Settings page's 'Send test email' button, so a user
    can confirm their notification emails will actually arrive before
    relying on the real triggers below."""
    return _send_plain(
        to_email, "DealRadar test email",
        "This is a test email from DealRadar - if you're reading this, your notification emails are working.",
    )


def send_deal_found_email(to_email, profile_name, match_count, best_coc):
    """Sent after a real (not mock/preview) live scan finds at least one
    'Outstanding' (excellent-grade) match, if the user has opted in via
    Settings - never sent for a test/preview scan, since alerting someone
    about a randomly-generated fake listing would be actively misleading."""
    body = (
        f"Your search \"{profile_name}\" just found {match_count} outstanding "
        f"{'deal' if match_count == 1 else 'deals'} - the best one clears your target return by "
        f"{best_coc:.1f}% cash-on-cash.\n\n"
        f"Log in to DealRadar to see the full results.\n\n"
        f"You're getting this because deal alerts are turned on in your Settings - you can turn them off there anytime."
    )
    return _send_plain(to_email, f"DealRadar: outstanding deal found in \"{profile_name}\"", body)


def send_low_credits_email(to_email):
    """Sent once when a user's credit balance reaches exactly 0 (not on
    every subsequent 0-credit scan), if opted in via Settings."""
    body = (
        "You're out of DealRadar credits - your next scan will show sample/preview data "
        "instead of real listings until you add more.\n\n"
        "Log in to DealRadar and visit Buy Credits to keep pulling real market data.\n\n"
        "You're getting this because low-credit alerts are turned on in your Settings - you can turn them off there anytime."
    )
    return _send_plain(to_email, "DealRadar: you're out of credits", body)


def send_password_changed_email(to_email):
    """Sent after a successful password change (self-service or
    admin-assisted), if opted in via Settings - a standard security
    notification so an unexpected change is visible even if the user
    themselves didn't make it."""
    body = (
        "Your DealRadar password was just changed.\n\n"
        "If this was you, no action is needed. If you didn't make this change, "
        "reset your password immediately from the sign-in page and contact support.\n\n"
        "You're getting this because security alerts are turned on in your Settings - you can turn them off there anytime."
    )
    return _send_plain(to_email, "DealRadar: your password was changed", body)
